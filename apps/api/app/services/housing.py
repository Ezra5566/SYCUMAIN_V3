"""Housing business logic service with occupancy calculation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
    RoomStatus,
)
from app.models.identity import Student, User
from app.schemas.housing import (
    BedResponse,
    BuildingBrief,
    BuildingDetail,
    BuildingOverview,
    FloorInBuilding,
    FloorOverview,
    HousingAssignmentResponse,
    HousingOverviewResponse,
    RoomBrief,
    RoomDetail,
    RoomOverview,
    StudentHousingResponse,
)


class HousingRuleError(ValueError):
    """A housing rule violation that maps to a stable API error code.

    Carries the code — and therefore the HTTP status — alongside the message so
    routers never have to infer intent from the exception's prose. Previously
    the update endpoint decided between 404 and 409 by searching the message for
    the substring "not found", which is both fragile and impossible to localise
    on the client: every distinct rule collapsed into the single code
    ``CONFLICT``.

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers keep
    working and a missed conversion degrades to the generic behaviour rather
    than escaping as a 500.
    """

    def __init__(self, code: str, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.not_found = not_found


def calculate_room_occupancy(room: Room) -> dict:
    """Calculate occupancy for a room based on active assignments."""
    active_count = 0
    for bed in room.beds:
        if bed.is_active:
            for assignment in bed.assignments:
                if assignment.status == HousingAssignmentStatus.ACTIVE:
                    active_count += 1
                    break

    total_beds = sum(1 for b in room.beds if b.is_active)
    available = total_beds - active_count

    # Determine occupancy status
    if room.status == RoomStatus.OUT_OF_SERVICE:
        occupancy_status = "OUT_OF_SERVICE"
    elif room.status == RoomStatus.RESERVED:
        occupancy_status = "RESERVED"
    elif active_count == 0:
        occupancy_status = "AVAILABLE"
    elif active_count >= total_beds:
        occupancy_status = "FULL"
    else:
        occupancy_status = "PARTIAL"

    return {
        "occupied": active_count,
        "available": available,
        "total_beds": total_beds,
        "occupancy_status": occupancy_status,
    }


def get_buildings(db: DBSession) -> list[BuildingBrief]:
    """Get all buildings."""
    buildings = (
        db.query(Building)
        .filter(Building.is_active.is_(True))
        .order_by(Building.name)
        .all()
    )
    return [BuildingBrief.model_validate(b) for b in buildings]


def get_building_detail(db: DBSession, building_id: uuid.UUID) -> BuildingDetail | None:
    """Get building with floors and occupancy summary."""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        return None

    floor_count = 0
    room_count = 0
    bed_count = 0
    occupied_count = 0
    floors_data = []

    for floor in sorted(building.floors, key=lambda f: f.floor_number):
        if not floor.is_active:
            continue
        floor_count += 1

        floor_room_count = 0
        floor_bed_count = 0
        floor_occupied = 0
        floor_available = 0
        floor_status = "AVAILABLE"

        for room in floor.rooms:
            if not room.is_active:
                continue
            floor_room_count += 1
            occ = calculate_room_occupancy(room)
            floor_bed_count += occ["total_beds"]
            floor_occupied += occ["occupied"]
            floor_available += occ["available"]

            if occ["occupancy_status"] == "FULL":
                floor_status = "FULL"
            elif occ["occupancy_status"] == "PARTIAL" and floor_status != "FULL":
                floor_status = "PARTIAL"
            elif (
                occ["occupancy_status"] in ("OUT_OF_SERVICE", "RESERVED")
                and floor_status not in ("FULL", "PARTIAL")
            ):
                floor_status = occ["occupancy_status"]

        room_count += floor_room_count
        bed_count += floor_bed_count
        occupied_count += floor_occupied

        floors_data.append(FloorInBuilding(
            id=floor.id,
            floor_number=floor.floor_number,
            is_active=floor.is_active,
            room_count=floor_room_count,
            bed_count=floor_bed_count,
            occupied_count=floor_occupied,
            available_count=floor_available,
            occupancy_status=floor_status,
        ))

    # Overall building occupancy
    if occupied_count == 0:
        building_status = "AVAILABLE"
    elif occupied_count >= bed_count:
        building_status = "FULL"
    else:
        building_status = "PARTIAL"

    return BuildingDetail(
        id=building.id,
        name=building.name,
        description=building.description,
        is_active=building.is_active,
        floor_count=floor_count,
        room_count=room_count,
        bed_count=bed_count,
        occupied_count=occupied_count,
        available_count=bed_count - occupied_count,
        occupancy_status=building_status,
        floors=floors_data,
    )


def get_floor_rooms(db: DBSession, floor_id: uuid.UUID) -> list[RoomBrief]:
    """Get rooms for a floor with occupancy."""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        return []

    result = []
    for room in sorted(floor.rooms, key=lambda r: r.room_number):
        if not room.is_active:
            continue
        occ = calculate_room_occupancy(room)
        result.append(RoomBrief(
            id=room.id,
            room_number=room.room_number,
            capacity=room.capacity,
            status=room.status,
            occupied=occ["occupied"],
            available=occ["available"],
            occupancy_status=occ["occupancy_status"],
        ))

    return result


def get_room_detail(db: DBSession, room_id: uuid.UUID) -> RoomDetail | None:
    """Get detailed room view with beds."""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        return None

    occ = calculate_room_occupancy(room)

    # `bed_number` is the permanent physical-bed identity and is kept for
    # history. The interface numbers only the beds currently in service, so a
    # retirement leaves a dense 1..n sequence without rewriting any row.
    active_beds = sorted(
        (bed for bed in room.beds if bed.is_active), key=lambda bed: bed.bed_number
    )
    beds = []
    for display_number, bed in enumerate(active_beds, start=1):
        if not bed.is_active:
            continue

        # Find active assignment for this bed
        active_assignment = None
        for assignment in bed.assignments:
            if assignment.status == HousingAssignmentStatus.ACTIVE:
                active_assignment = assignment
                break

        # Get student name
        student_name = None
        student_id = None
        student_record_id = None
        assignment_id = None
        if active_assignment:
            student = db.query(User).filter(
                User.id == active_assignment.student_id
            ).first()
            if student:
                student_name = student.full_name
            record = (
                db.query(Student)
                .filter(Student.user_id == active_assignment.student_id)
                .first()
            )
            if record:
                student_record_id = record.id
            student_id = active_assignment.student_id
            assignment_id = active_assignment.id

        beds.append(BedResponse(
            id=bed.id,
            bed_number=bed.bed_number,
            display_number=display_number,
            label=bed.label,
            is_active=bed.is_active,
            is_occupied=active_assignment is not None,
            student_name=student_name,
            student_id=student_id,
            student_record_id=student_record_id,
            assignment_id=assignment_id,
        ))

    return RoomDetail(
        id=room.id,
        room_number=room.room_number,
        capacity=room.capacity,
        status=room.status,
        occupied=occ["occupied"],
        available=occ["available"],
        occupancy_status=occ["occupancy_status"],
        beds=beds,
        floor_number=room.floor.floor_number if room.floor else None,
        building_name=(
            room.floor.building.name
            if room.floor and room.floor.building
            else None
        ),
    )


def get_housing_overview(db: DBSession) -> HousingOverviewResponse:
    """Get complete housing overview for dormitory visualization."""
    buildings = (
        db.query(Building)
        .filter(Building.is_active.is_(True))
        .order_by(Building.name)
        .all()
    )

    total_rooms = 0
    total_beds = 0
    total_occupied = 0

    buildings_data = []

    for building in buildings:
        b_room_count = 0
        b_bed_count = 0
        b_occupied = 0
        floors_data = []

        for floor in sorted(building.floors, key=lambda f: f.floor_number):
            if not floor.is_active:
                continue

            f_room_count = 0
            f_bed_count = 0
            f_occupied = 0
            rooms_data = []

            for room in floor.rooms:
                if not room.is_active:
                    continue
                occ = calculate_room_occupancy(room)
                f_room_count += 1
                f_bed_count += occ["total_beds"]
                f_occupied += occ["occupied"]
                rooms_data.append(RoomOverview(
                    id=room.id,
                    room_number=room.room_number,
                    capacity=room.capacity,
                    is_active=room.is_active,
                    status=room.status,
                    occupied=occ["occupied"],
                    available=occ["available"],
                    occupancy_status=occ["occupancy_status"],
                ))

            b_room_count += f_room_count
            b_bed_count += f_bed_count
            b_occupied += f_occupied

            floors_data.append(FloorOverview(
                id=floor.id,
                floor_number=floor.floor_number,
                is_active=floor.is_active,
                room_count=f_room_count,
                bed_count=f_bed_count,
                occupied_count=f_occupied,
                available_count=f_bed_count - f_occupied,
                rooms=rooms_data,
            ))

        total_rooms += b_room_count
        total_beds += b_bed_count
        total_occupied += b_occupied

        # Building occupancy status
        if b_occupied == 0:
            b_status = "AVAILABLE"
        elif b_occupied >= b_bed_count:
            b_status = "FULL"
        else:
            b_status = "PARTIAL"

        buildings_data.append(BuildingOverview(
            id=building.id,
            name=building.name,
            floor_count=len([f for f in building.floors if f.is_active]),
            room_count=b_room_count,
            bed_count=b_bed_count,
            occupied_count=b_occupied,
            available_count=b_bed_count - b_occupied,
            occupancy_status=b_status,
            floors=floors_data,
        ))

    return HousingOverviewResponse(
        buildings=buildings_data,
        total_buildings=len(buildings_data),
        total_rooms=total_rooms,
        total_beds=total_beds,
        total_occupied=total_occupied,
        total_available=total_beds - total_occupied,
    )


def get_assignment(
    db: DBSession, assignment_id: uuid.UUID
) -> HousingAssignmentResponse | None:
    """Get a single housing assignment (any status, so history is readable)."""
    assignment = (
        db.query(HousingAssignment)
        .filter(HousingAssignment.id == assignment_id)
        .first()
    )
    if assignment is None:
        return None
    return _build_assignment_response(db, assignment)


def update_housing_assignment(
    db: DBSession,
    assignment_id: uuid.UUID,
    data: dict,
    actor_id: uuid.UUID | None = None,
) -> HousingAssignmentResponse:
    """Partially update a housing assignment.

    Only notes, end_date, and status are editable. Bed and student are never
    mutable here: a move is a transfer, which preserves history.
    """
    assignment = (
        db.query(HousingAssignment)
        .filter(HousingAssignment.id == assignment_id)
        .with_for_update()
        .first()
    )
    if assignment is None:
        raise HousingRuleError(
            "ASSIGNMENT_NOT_FOUND", "Assignment not found.", not_found=True
        )

    if "notes" in data:
        assignment.notes = data["notes"]

    new_status = data.get("status")
    if new_status is not None:
        if isinstance(new_status, str):
            new_status = HousingAssignmentStatus(new_status)

        if (
            new_status == HousingAssignmentStatus.ACTIVE
            and assignment.status != HousingAssignmentStatus.ACTIVE
        ):
            # Re-activating would risk a second active occupant or assignment,
            # so require an explicit new assignment instead.
            raise HousingRuleError(
                "ASSIGNMENT_NOT_REACTIVATABLE",
                "A closed assignment cannot be reactivated; "
                "create a new assignment instead.",
            )
        was_active = assignment.status == HousingAssignmentStatus.ACTIVE
        assignment.status = new_status
        if new_status != HousingAssignmentStatus.ACTIVE and was_active:
            assignment.ended_by_id = actor_id
            assignment.ended_at = datetime.now(UTC)
        if new_status != HousingAssignmentStatus.ACTIVE and assignment.end_date is None:
            assignment.end_date = data.get("end_date") or datetime.now(UTC)

    if "end_date" in data and data["end_date"] is not None:
        assignment.end_date = data["end_date"]

    db.commit()
    db.refresh(assignment)
    return _build_assignment_response(db, assignment)


def create_housing_assignment(
    db: DBSession,
    student_id: uuid.UUID,
    bed_id: uuid.UUID,
    start_date: datetime,
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> HousingAssignmentResponse:
    """Create a housing assignment with validation."""
    # Validate the occupant. Without this the insert reaches the foreign key
    # and surfaces as an unhandled IntegrityError (HTTP 500) naming the
    # constraint — which both leaks schema detail and is the likely outcome of
    # passing a student *record* id, since every other endpoint takes one.
    # The row lock also serializes two attempts to assign the same student.
    occupant = (
        db.query(User)
        .filter(User.id == student_id)
        .with_for_update()
        .first()
    )
    if occupant is None or not any(r.name == "STUDENT" for r in occupant.roles):
        raise HousingRuleError(
            "STUDENT_NOT_FOUND",
            "That student does not exist or has no student account.",
            not_found=True,
        )

    # Validate bed exists and is active. The row lock makes two concurrent
    # assignments to the same bed wait for one another; the partial unique
    # index remains the final guarantee even if this check is bypassed.
    bed = (
        db.query(Bed)
        .filter(Bed.id == bed_id, Bed.is_active.is_(True))
        .with_for_update()
        .first()
    )
    if not bed:
        raise HousingRuleError(
            "BED_NOT_FOUND", "That bed does not exist or is not in service.", not_found=True
        )

    # Validate room is not out of service
    room = db.query(Room).filter(Room.id == bed.room_id).first()
    if room and room.status == RoomStatus.OUT_OF_SERVICE:
        raise HousingRuleError(
            "ROOM_OUT_OF_SERVICE",
            "That room is out of service and cannot take new occupants.",
        )

    # Check bed is not already occupied by an active assignment
    existing = db.query(HousingAssignment).filter(
        and_(
            HousingAssignment.bed_id == bed_id,
            HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
        )
    ).first()
    if existing:
        raise HousingRuleError(
            "BED_OCCUPIED", "That bed is already occupied."
        )

    # Check student does not have an active assignment
    student_active = db.query(HousingAssignment).filter(
        and_(
            HousingAssignment.student_id == student_id,
            HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
        )
    ).first()
    if student_active:
        raise HousingRuleError(
            "STUDENT_ALREADY_ASSIGNED",
            "This student already has an active housing assignment. "
            "Transfer them instead of creating a second one.",
        )

    # Create assignment
    assignment = HousingAssignment(
        student_id=student_id,
        bed_id=bed_id,
        start_date=start_date,
        status=HousingAssignmentStatus.ACTIVE,
        notes=notes,
        created_by_id=actor_id,
    )
    db.add(assignment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # The unique index is authoritative; translate it to the same stable
        # rule code the pre-check produces rather than leaking a DB error.
        bed_taken = db.query(HousingAssignment.id).filter(
            HousingAssignment.bed_id == bed_id,
            HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
        ).first()
        if bed_taken:
            raise HousingRuleError("BED_OCCUPIED", "That bed is already occupied.") from None
        raise HousingRuleError(
            "STUDENT_ALREADY_ASSIGNED",
            "This student already has an active housing assignment. "
            "Transfer them instead of creating a second one.",
        ) from None
    db.refresh(assignment)

    return _build_assignment_response(db, assignment)


def transfer_student(
    db: DBSession,
    assignment_id: uuid.UUID,
    new_bed_id: uuid.UUID,
    transfer_date: datetime,
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> HousingAssignmentResponse:
    """Transfer student to a new bed atomically."""
    # Lock the current assignment so two concurrent transfers cannot both end
    # it and create a successor.
    assignment = (
        db.query(HousingAssignment)
        .filter(
            and_(
                HousingAssignment.id == assignment_id,
                HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
            )
        )
        .with_for_update()
        .first()
    )
    if not assignment:
        raise HousingRuleError(
            "ASSIGNMENT_NOT_FOUND", "Active assignment not found.", not_found=True
        )

    # Validate new bed, locking it for the duration of the transfer.
    new_bed = (
        db.query(Bed)
        .filter(Bed.id == new_bed_id, Bed.is_active.is_(True))
        .with_for_update()
        .first()
    )
    if not new_bed:
        raise HousingRuleError(
            "BED_NOT_FOUND", "That bed does not exist or is not in service.", not_found=True
        )

    # Validate the destination room is in service. Creation refuses an
    # out-of-service room, so without the same check here a transfer was a way
    # around the rule.
    new_room = db.query(Room).filter(Room.id == new_bed.room_id).first()
    if new_room and new_room.status == RoomStatus.OUT_OF_SERVICE:
        raise HousingRuleError(
            "ROOM_OUT_OF_SERVICE",
            "That room is out of service and cannot take new occupants.",
        )

    # Check new bed is not occupied
    existing = db.query(HousingAssignment).filter(
        and_(
            HousingAssignment.bed_id == new_bed_id,
            HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
        )
    ).first()
    if existing:
        raise HousingRuleError(
            "BED_OCCUPIED", "The destination bed is already occupied."
        )

    # Atomic transfer. Flush the close before inserting the successor so the
    # one-active-assignment indexes see a valid intermediate state.
    assignment.status = HousingAssignmentStatus.ENDED
    assignment.end_date = transfer_date
    assignment.ended_by_id = actor_id
    assignment.ended_at = datetime.now(UTC)
    if notes:
        assignment.notes = (assignment.notes or "") + f"\nTransfer: {notes}"
    db.flush()

    new_assignment = HousingAssignment(
        student_id=assignment.student_id,
        bed_id=new_bed_id,
        start_date=transfer_date,
        status=HousingAssignmentStatus.ACTIVE,
        notes=notes,
        created_by_id=actor_id,
    )
    db.add(new_assignment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HousingRuleError(
            "BED_OCCUPIED", "The destination bed is already occupied."
        ) from None
    db.refresh(new_assignment)

    return _build_assignment_response(db, new_assignment)


def end_housing_assignment(
    db: DBSession, assignment_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> HousingAssignmentResponse:
    """End a housing assignment."""

    assignment = (
        db.query(HousingAssignment)
        .filter(
            and_(
                HousingAssignment.id == assignment_id,
                HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
            )
        )
        .with_for_update()
        .first()
    )
    if not assignment:
        raise HousingRuleError(
            "ASSIGNMENT_NOT_FOUND", "Active assignment not found.", not_found=True
        )

    assignment.status = HousingAssignmentStatus.ENDED
    assignment.end_date = datetime.now(UTC)
    assignment.ended_by_id = actor_id
    assignment.ended_at = datetime.now(UTC)
    db.commit()
    db.refresh(assignment)

    return _build_assignment_response(db, assignment)


def get_student_housing(
    db: DBSession, student_id: uuid.UUID
) -> StudentHousingResponse:
    """Get student's current housing assignment."""
    assignment = (
        db.query(HousingAssignment)
        .filter(
            and_(
                HousingAssignment.student_id == student_id,
                HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
            )
        )
        .first()
    )

    if not assignment:
        return StudentHousingResponse(has_assignment=False)

    return StudentHousingResponse(
        has_assignment=True,
        assignment=_build_assignment_response(db, assignment),
    )


# --- Structure administration ---
#
# The dormitory structure used to be seed-only: an operator could visualise it
# but never change it, so a new building or a room that lost a bed required
# hand-editing the database. These functions make it configurable while keeping
# two invariants that the read paths already assume:
#
#   1. `Room.capacity` equals the number of beds in service. Capacity is not an
#      independent number an operator types; it follows the beds, so a room can
#      never advertise four beds while holding three.
#   2. Beds are retired, never deleted, and a bed holding a student cannot be
#      retired at all. Assignments are historical records and must not be
#      orphaned or silently vacated.


def _sync_room_capacity(db: DBSession, room: Room) -> int:
    """Recompute a room's capacity from the beds that are in service."""
    room.capacity = (
        db.query(func.count())
        .select_from(Bed)
        .filter(Bed.room_id == room.id, Bed.is_active.is_(True))
        .scalar()
        or 0
    )
    return room.capacity


def _next_bed_number(db: DBSession, room_id: uuid.UUID) -> int:
    """Next free bed number, so numbering stays dense and predictable."""
    highest = (
        db.query(func.max(Bed.bed_number)).filter(Bed.room_id == room_id).scalar()
    )
    return (highest or 0) + 1


def _active_beds(db: DBSession, room_id: uuid.UUID) -> list[Bed]:
    """A room's beds in service, lowest number first.

    Read with a query rather than through ``Room.beds`` on purpose. The
    relationship is cached per session, so a collection loaded before an
    assignment was created would still look empty afterwards — and a capacity
    check that consults stale data is exactly the check that lets a student be
    evicted by an edit.
    """
    return (
        db.query(Bed)
        .filter(Bed.room_id == room_id, Bed.is_active.is_(True))
        .order_by(Bed.bed_number)
        .all()
    )


def _occupied_bed_ids(db: DBSession, room_id: uuid.UUID) -> set[uuid.UUID]:
    """Ids of beds in this room that currently hold a student."""
    rows = (
        db.query(HousingAssignment.bed_id)
        .join(Bed, Bed.id == HousingAssignment.bed_id)
        .filter(
            Bed.room_id == room_id,
            HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
        )
        .all()
    )
    return {row[0] for row in rows}


def _ensure_bed(
    db: DBSession, room_id: uuid.UUID, number: int, label: str | None = None
) -> None:
    """Make bed `number` available in a room.

    A retired bed keeps its ``(room_id, bed_number)`` row, so raising capacity
    after a reduction must reinstate that row rather than insert a duplicate —
    which the unique constraint would (correctly) reject as a 500.
    """
    existing = (
        db.query(Bed)
        .filter(Bed.room_id == room_id, Bed.bed_number == number)
        .first()
    )
    if existing:
        existing.is_active = True
        if label is not None:
            existing.label = label
        return
    db.add(Bed(room_id=room_id, bed_number=number, label=label))


def _bed_is_occupied(db: DBSession, bed_id: uuid.UUID) -> bool:
    """Whether a bed has a live occupant, read from the database."""
    return (
        db.query(HousingAssignment.id)
        .filter(
            HousingAssignment.bed_id == bed_id,
            HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
        )
        .first()
        is not None
    )


def create_building(
    db: DBSession, name: str, description: str | None = None
) -> BuildingDetail:
    """Add a building. Names are unique case-insensitively."""
    clean = name.strip()
    clash = (
        db.query(Building)
        .filter(func.lower(Building.name) == clean.lower())
        .first()
    )
    if clash:
        raise HousingRuleError(
            "BUILDING_NAME_TAKEN", f"A building named '{clean}' already exists."
        )

    building = Building(name=clean, description=description)
    db.add(building)
    db.commit()
    db.refresh(building)

    detail = get_building_detail(db, building.id)
    assert detail is not None  # just created
    return detail


def update_building(
    db: DBSession,
    building_id: uuid.UUID,
    changes: dict,
) -> BuildingDetail:
    """Edit or archive a building."""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HousingRuleError(
            "BUILDING_NOT_FOUND", "That building does not exist.", not_found=True
        )

    if changes.get("name"):
        clean = changes["name"].strip()
        clash = (
            db.query(Building)
            .filter(
                func.lower(Building.name) == clean.lower(),
                Building.id != building_id,
            )
            .first()
        )
        if clash:
            raise HousingRuleError(
                "BUILDING_NAME_TAKEN", f"A building named '{clean}' already exists."
            )
        building.name = clean

    if "description" in changes:
        building.description = changes["description"]
    if changes.get("is_active") is not None:
        building.is_active = changes["is_active"]

    db.commit()
    db.refresh(building)

    detail = get_building_detail(db, building_id)
    assert detail is not None
    return detail


def create_floor(
    db: DBSession, building_id: uuid.UUID, floor_number: int
) -> BuildingDetail:
    """Add a floor to a building."""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HousingRuleError(
            "BUILDING_NOT_FOUND", "That building does not exist.", not_found=True
        )

    clash = (
        db.query(Floor)
        .filter(Floor.building_id == building_id, Floor.floor_number == floor_number)
        .first()
    )
    if clash:
        raise HousingRuleError(
            "FLOOR_NUMBER_TAKEN",
            f"Floor {floor_number} already exists in this building.",
        )

    db.add(Floor(building_id=building_id, floor_number=floor_number))
    db.commit()

    detail = get_building_detail(db, building_id)
    assert detail is not None
    return detail


def update_floor(
    db: DBSession, floor_id: uuid.UUID, changes: dict
) -> BuildingDetail:
    """Edit or archive a floor, returning its building."""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HousingRuleError(
            "FLOOR_NOT_FOUND", "That floor does not exist.", not_found=True
        )

    new_number = changes.get("floor_number")
    if new_number is not None and new_number != floor.floor_number:
        clash = (
            db.query(Floor)
            .filter(
                Floor.building_id == floor.building_id,
                Floor.floor_number == new_number,
                Floor.id != floor_id,
            )
            .first()
        )
        if clash:
            raise HousingRuleError(
                "FLOOR_NUMBER_TAKEN",
                f"Floor {new_number} already exists in this building.",
            )
        floor.floor_number = new_number

    if changes.get("is_active") is not None:
        floor.is_active = changes["is_active"]

    building_id = floor.building_id
    db.commit()

    detail = get_building_detail(db, building_id)
    assert detail is not None
    return detail


def create_room(
    db: DBSession,
    floor_id: uuid.UUID,
    room_number: str,
    capacity: int,
    status: RoomStatus = RoomStatus.AVAILABLE,
) -> RoomDetail:
    """Add a room with `capacity` beds."""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HousingRuleError(
            "FLOOR_NOT_FOUND", "That floor does not exist.", not_found=True
        )

    clean = room_number.strip()
    clash = (
        db.query(Room)
        .filter(Room.floor_id == floor_id, Room.room_number == clean)
        .first()
    )
    if clash:
        raise HousingRuleError(
            "ROOM_NUMBER_TAKEN",
            f"Room {clean} already exists on this floor.",
        )

    room = Room(
        floor_id=floor_id,
        room_number=clean,
        status=status,
        capacity=capacity,
    )
    db.add(room)
    db.flush()

    for number in range(1, capacity + 1):
        db.add(Bed(room_id=room.id, bed_number=number))

    db.commit()
    _sync_room_capacity(db, room)
    db.commit()
    db.refresh(room)

    detail = get_room_detail(db, room.id)
    assert detail is not None
    return detail


def update_room(db: DBSession, room_id: uuid.UUID, changes: dict) -> RoomDetail:
    """Edit a room, adjusting its beds to match a new capacity.

    Lowering capacity below the number of occupied beds is refused rather than
    resolved automatically: silently evicting a student to satisfy a capacity
    edit is exactly the kind of destructive shortcut an operator must not be
    able to trigger by accident.
    """
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HousingRuleError(
            "ROOM_NOT_FOUND", "That room does not exist.", not_found=True
        )

    if changes.get("room_number"):
        clean = changes["room_number"].strip()
        clash = (
            db.query(Room)
            .filter(
                Room.floor_id == room.floor_id,
                Room.room_number == clean,
                Room.id != room_id,
            )
            .first()
        )
        if clash:
            raise HousingRuleError(
                "ROOM_NUMBER_TAKEN",
                f"Room {clean} already exists on this floor.",
            )
        room.room_number = clean

    if changes.get("status") is not None:
        new_status = changes["status"]
        if isinstance(new_status, str):
            new_status = RoomStatus(new_status)
        room.status = new_status

    if changes.get("is_active") is not None:
        room.is_active = changes["is_active"]

    capacity = changes.get("capacity")
    if capacity is not None:
        active = _active_beds(db, room_id)
        occupied_ids = _occupied_bed_ids(db, room_id)

        if capacity < len(occupied_ids):
            raise HousingRuleError(
                "ROOM_CAPACITY_EXCEEDED",
                f"This room has {len(occupied_ids)} occupied bed(s). "
                f"Move those students before reducing capacity to {capacity}.",
            )

        if capacity > len(active):
            for number in range(1, capacity + 1):
                if not any(bed.bed_number == number for bed in active):
                    _ensure_bed(db, room_id, number)
        elif capacity < len(active):
            # Retire the highest-numbered empty beds first.
            to_retire = len(active) - capacity
            for bed in reversed(active):
                if to_retire == 0:
                    break
                if bed.id in occupied_ids:
                    continue
                bed.is_active = False
                to_retire -= 1

    db.commit()
    _sync_room_capacity(db, room)
    db.commit()
    db.refresh(room)

    detail = get_room_detail(db, room.id)
    assert detail is not None
    return detail


def create_bed(
    db: DBSession,
    room_id: uuid.UUID,
    label: str | None = None,
    bed_number: int | None = None,
) -> RoomDetail:
    """Add a bed to a room, raising the room's capacity."""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HousingRuleError(
            "ROOM_NOT_FOUND", "That room does not exist.", not_found=True
        )

    number = bed_number or _next_bed_number(db, room_id)
    clash = (
        db.query(Bed)
        .filter(Bed.room_id == room_id, Bed.bed_number == number)
        .first()
    )
    if clash and clash.is_active:
        raise HousingRuleError(
            "BED_NUMBER_TAKEN", f"Bed {number} already exists in this room."
        )

    # Reinstating a retired bed is the natural way to undo a reduction.
    _ensure_bed(db, room_id, number, label)
    db.commit()
    _sync_room_capacity(db, room)
    db.commit()

    detail = get_room_detail(db, room_id)
    assert detail is not None
    return detail


def update_bed(
    db: DBSession, bed_id: uuid.UUID, changes: dict
) -> RoomDetail:
    """Rename or retire a bed.

    Retiring an occupied bed is refused: the student would lose the bed they
    are recorded as living in, and the assignment history would point at a bed
    that no longer exists.
    """
    bed = db.query(Bed).filter(Bed.id == bed_id).first()
    if not bed:
        raise HousingRuleError(
            "BED_NOT_FOUND", "That bed does not exist.", not_found=True
        )

    room_id = bed.room_id
    if "label" in changes:
        bed.label = changes["label"]

    if changes.get("is_active") is False and bed.is_active:
        if _bed_is_occupied(db, bed_id):
            raise HousingRuleError(
                "BED_OCCUPIED",
                "That bed is occupied. Move the student out before retiring it.",
            )
        bed.is_active = False
    elif changes.get("is_active") is True:
        bed.is_active = True

    db.commit()

    room = db.query(Room).filter(Room.id == room_id).first()
    if room:
        _sync_room_capacity(db, room)
        db.commit()

    detail = get_room_detail(db, room_id)
    assert detail is not None
    return detail


def get_room_assignment_history(
    db: DBSession, room_id: uuid.UUID
) -> list[HousingAssignmentResponse]:
    """Every assignment ever recorded for a room, newest first."""
    assignments = (
        db.query(HousingAssignment)
        .join(Bed, Bed.id == HousingAssignment.bed_id)
        .filter(Bed.room_id == room_id)
        .order_by(HousingAssignment.start_date.desc(), HousingAssignment.created_at.desc())
        .all()
    )
    return [_build_assignment_response(db, a) for a in assignments]


def get_bed_assignment_history(
    db: DBSession, bed_id: uuid.UUID
) -> list[HousingAssignmentResponse]:
    """Every assignment ever recorded for a bed, newest first."""
    assignments = (
        db.query(HousingAssignment)
        .filter(HousingAssignment.bed_id == bed_id)
        .order_by(HousingAssignment.start_date.desc(), HousingAssignment.created_at.desc())
        .all()
    )
    return [_build_assignment_response(db, a) for a in assignments]


def _build_assignment_response(
    db: DBSession, assignment: HousingAssignment
) -> HousingAssignmentResponse:
    """Build a housing assignment response with related data."""
    bed = db.query(Bed).filter(Bed.id == assignment.bed_id).first()
    room = db.query(Room).filter(Room.id == bed.room_id).first() if bed else None
    floor = (
        db.query(Floor).filter(Floor.id == room.floor_id).first()
        if room
        else None
    )
    building = (
        db.query(Building)
        .filter(Building.id == floor.building_id)
        .first()
        if floor
        else None
    )

    # Get student name
    student = db.query(User).filter(User.id == assignment.student_id).first()
    created_by = (
        db.query(User).filter(User.id == assignment.created_by_id).first()
        if assignment.created_by_id
        else None
    )
    ended_by = (
        db.query(User).filter(User.id == assignment.ended_by_id).first()
        if assignment.ended_by_id
        else None
    )

    return HousingAssignmentResponse(
        id=assignment.id,
        student_id=assignment.student_id,
        student_name=student.full_name if student else None,
        bed_id=assignment.bed_id,
        bed_label=bed.label if bed else None,
        room_number=room.room_number if room else None,
        floor_number=floor.floor_number if floor else None,
        building_name=building.name if building else None,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        status=assignment.status,
        notes=assignment.notes,
        created_by_id=assignment.created_by_id,
        created_by_name=created_by.full_name if created_by else None,
        ended_by_id=assignment.ended_by_id,
        ended_by_name=ended_by.full_name if ended_by else None,
        ended_at=assignment.ended_at,
        created_at=assignment.created_at,
    )
