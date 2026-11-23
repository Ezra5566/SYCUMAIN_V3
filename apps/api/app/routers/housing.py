"""Housing API endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi import status as http_status
from fastapi.responses import Response
from sqlalchemy.orm import Session as DBSession

from app.audit import record_audit
from app.auth.dependencies import CurrentUser, get_db
from app.config.settings import get_settings
from app.models.housing import RoomStatus
from app.models.platform import NotificationType
from app.permissions.scope import can_view_housing
from app.schemas.housing import (
    BedCreate,
    BedUpdate,
    BuildingBrief,
    BuildingCreate,
    BuildingDetail,
    BuildingUpdate,
    FloorCreate,
    FloorUpdate,
    HousingAssignmentCreate,
    HousingAssignmentResponse,
    HousingAssignmentTransfer,
    HousingAssignmentUpdate,
    HousingImportReport,
    HousingOverviewResponse,
    RoomBrief,
    RoomCreate,
    RoomDetail,
    RoomUpdate,
    StudentHousingResponse,
)
from app.services.housing import (
    HousingRuleError,
    create_bed,
    create_building,
    create_floor,
    create_housing_assignment,
    create_room,
    end_housing_assignment,
    get_assignment,
    get_bed_assignment_history,
    get_building_detail,
    get_buildings,
    get_floor_rooms,
    get_housing_overview,
    get_room_assignment_history,
    get_room_detail,
    get_student_housing,
    transfer_student,
    update_bed,
    update_building,
    update_floor,
    update_housing_assignment,
    update_room,
)
from app.services.housing_import import (
    ImportFileError,
    apply_housing_import,
    build_template_csv,
    parse_rows,
    preview_housing_import,
)
from app.services.notification import create_notification

router = APIRouter(prefix="/housing", tags=["housing"])


def _rule_error(exc: ValueError) -> HTTPException:
    """Map a housing rule violation to a stable API error.

    ``HousingRuleError`` carries its own code and status, which is what lets the
    client render the precise reason ("that bed is already occupied") in the
    user's language instead of a generic conflict. A bare ``ValueError`` — from
    a path not yet converted — degrades to a generic conflict rather than
    escaping as a 500.
    """
    if isinstance(exc, HousingRuleError):
        return HTTPException(
            status_code=(
                http_status.HTTP_404_NOT_FOUND
                if exc.not_found
                else http_status.HTTP_409_CONFLICT
            ),
            detail={"error": {"code": exc.code, "message": str(exc)}},
        )
    return HTTPException(
        status_code=http_status.HTTP_409_CONFLICT,
        detail={"error": {"code": "CONFLICT", "message": str(exc)}},
    )


def _check_housing_admin(user: CurrentUser) -> None:
    """Check user has housing administration permissions."""
    from app.permissions.checks import has_permission

    if not has_permission(user, "housing.assign"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have housing administration permissions.",
                }
            },
        )


def _check_assignment_scope(db: DBSession, user: CurrentUser, student_id: uuid.UUID) -> None:
    """Students may only read their own assignment.

    The assignment's `student_id` is a *user* id (matching the Stage 4 schema),
    so it is compared directly against the authenticated identity.
    """
    role_names = {r.name for r in user.roles}
    if role_names - {"STUDENT"}:
        return
    if user.id != student_id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You can only access your own housing assignment.",
                }
            },
        )


def _notify_student(
    db: DBSession, assignment: HousingAssignmentResponse, notification_type
) -> None:
    """Notify the affected student about a housing change.

    `student_id` on an assignment is the student's user id, so it can be used
    as a notification recipient directly.
    """
    create_notification(
        db,
        user_id=assignment.student_id,
        notification_type=notification_type,
        params={"bed_label": str(assignment.bed_id)},
        link_url="/app/profile/housing",
        entity_type="housing_assignment",
        entity_id=assignment.id,
    )


def _check_structure_permission(user: CurrentUser, permission: str) -> None:
    """Gate structure changes on `housing.create` / `housing.edit`.

    Deliberately separate from `housing.assign`: placing a student in a bed and
    reshaping the estate are different jobs, and a front-office operator who
    may do the first should not automatically be able to add buildings or
    retire beds.
    """
    from app.permissions.checks import has_permission

    if not has_permission(user, permission):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to change the housing "
                    "structure.",
                }
            },
        )


def _check_housing_access(user: CurrentUser) -> None:
    """Require permission to browse the whole dormitory.

    This guards the building/floor/room/overview endpoints, which expose every
    bed and its occupant. It is deliberately stricter than `housing.view`:
    students hold `housing.view` so they can see *their own* assignment through
    the student profile, and that must never amount to a dormitory directory.
    """
    from app.permissions.checks import has_permission

    if not has_permission(user, "housing.view_all"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to browse the dormitory.",
                }
            },
        )


# --- Building Endpoints ---


@router.get("/buildings", response_model=list[BuildingBrief])
def list_buildings_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
) -> list[BuildingBrief]:
    """List all active buildings."""
    _check_housing_access(current_user)
    return get_buildings(db)


@router.get("/buildings/{building_id}", response_model=BuildingDetail)
def get_building_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    building_id: uuid.UUID,
) -> BuildingDetail:
    """Get building detail with floors and occupancy."""
    _check_housing_access(current_user)
    building = get_building_detail(db, building_id)
    if not building:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Building not found.",
                }
            },
        )
    return building


@router.get("/floors/{floor_id}/rooms", response_model=list[RoomBrief])
def list_floor_rooms(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    floor_id: uuid.UUID,
) -> list[RoomBrief]:
    """List rooms for a floor with occupancy."""
    _check_housing_access(current_user)
    return get_floor_rooms(db, floor_id)


@router.get("/rooms/{room_id}", response_model=RoomDetail)
def get_room(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    room_id: uuid.UUID,
) -> RoomDetail:
    """Get detailed room view with beds."""
    _check_housing_access(current_user)
    room = get_room_detail(db, room_id)
    if not room:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Room not found.",
                }
            },
        )
    return room


# --- Structure administration ---
#
# Buildings, floors, rooms and beds were seed-only before Stage 8B: the estate
# could be visualised but not changed, so adding a building or retiring a bed
# meant editing the database by hand. These endpoints are the operational fix.


@router.post(
    "/buildings",
    response_model=BuildingDetail,
    status_code=http_status.HTTP_201_CREATED,
)
def create_building_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    data: BuildingCreate,
    request: Request,
) -> BuildingDetail:
    """Add a building."""
    _check_structure_permission(current_user, "housing.create")
    try:
        building = create_building(db, name=data.name, description=data.description)
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.building.created",
        actor=current_user,
        entity_type="building",
        entity_id=building.id,
        context={"name": building.name},
        request=request,
    )
    db.commit()
    return building


@router.patch("/buildings/{building_id}", response_model=BuildingDetail)
def update_building_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    building_id: uuid.UUID,
    data: BuildingUpdate,
    request: Request,
) -> BuildingDetail:
    """Edit or archive a building."""
    _check_structure_permission(current_user, "housing.edit")
    changes = data.model_dump(exclude_unset=True)
    try:
        building = update_building(db, building_id, changes)
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.building.updated",
        actor=current_user,
        entity_type="building",
        entity_id=building_id,
        context={"fields": sorted(changes.keys())},
        request=request,
    )
    db.commit()
    return building


@router.post(
    "/buildings/{building_id}/floors",
    response_model=BuildingDetail,
    status_code=http_status.HTTP_201_CREATED,
)
def create_floor_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    building_id: uuid.UUID,
    data: FloorCreate,
    request: Request,
) -> BuildingDetail:
    """Add a floor to a building."""
    _check_structure_permission(current_user, "housing.create")
    try:
        building = create_floor(db, building_id, data.floor_number)
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.floor.created",
        actor=current_user,
        entity_type="floor",
        entity_id=building_id,
        context={"floor_number": data.floor_number},
        request=request,
    )
    db.commit()
    return building


@router.patch("/floors/{floor_id}", response_model=BuildingDetail)
def update_floor_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    floor_id: uuid.UUID,
    data: FloorUpdate,
    request: Request,
) -> BuildingDetail:
    """Edit or archive a floor."""
    _check_structure_permission(current_user, "housing.edit")
    changes = data.model_dump(exclude_unset=True)
    try:
        building = update_floor(db, floor_id, changes)
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.floor.updated",
        actor=current_user,
        entity_type="floor",
        entity_id=floor_id,
        context={"fields": sorted(changes.keys())},
        request=request,
    )
    db.commit()
    return building


@router.post(
    "/floors/{floor_id}/rooms",
    response_model=RoomDetail,
    status_code=http_status.HTTP_201_CREATED,
)
def create_room_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    floor_id: uuid.UUID,
    data: RoomCreate,
    request: Request,
) -> RoomDetail:
    """Add a room, with `capacity` beds, to a floor."""
    _check_structure_permission(current_user, "housing.create")
    try:
        room = create_room(
            db,
            floor_id=floor_id,
            room_number=data.room_number,
            capacity=data.capacity,
            status=RoomStatus(data.status),
        )
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.room.created",
        actor=current_user,
        entity_type="room",
        entity_id=room.id,
        context={"room_number": room.room_number, "capacity": room.capacity},
        request=request,
    )
    db.commit()
    return room


@router.patch("/rooms/{room_id}", response_model=RoomDetail)
def update_room_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    room_id: uuid.UUID,
    data: RoomUpdate,
    request: Request,
) -> RoomDetail:
    """Edit a room: number, operational status, capacity, active flag."""
    _check_structure_permission(current_user, "housing.edit")
    changes = data.model_dump(exclude_unset=True)
    try:
        room = update_room(db, room_id, changes)
    except ValueError as e:
        raise _rule_error(e) from e

    # A status change is an operational event in its own right — a room going
    # out of service matters to whoever next tries to place a student.
    action = (
        "housing.room.status_changed"
        if "status" in changes
        else "housing.room.updated"
    )
    record_audit(
        db,
        action=action,
        actor=current_user,
        entity_type="room",
        entity_id=room_id,
        context={"fields": sorted(changes.keys())},
        request=request,
    )
    db.commit()
    return room


@router.post(
    "/rooms/{room_id}/beds",
    response_model=RoomDetail,
    status_code=http_status.HTTP_201_CREATED,
)
def create_bed_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    room_id: uuid.UUID,
    data: BedCreate,
    request: Request,
) -> RoomDetail:
    """Add a bed to a room. The room's capacity follows its beds."""
    _check_structure_permission(current_user, "housing.create")
    try:
        room = create_bed(
            db, room_id=room_id, label=data.label, bed_number=data.bed_number
        )
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.bed.created",
        actor=current_user,
        entity_type="room",
        entity_id=room_id,
        context={"capacity": room.capacity},
        request=request,
    )
    db.commit()
    return room


@router.patch("/beds/{bed_id}", response_model=RoomDetail)
def update_bed_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    bed_id: uuid.UUID,
    data: BedUpdate,
    request: Request,
) -> RoomDetail:
    """Rename or retire a bed. An occupied bed cannot be retired."""
    _check_structure_permission(current_user, "housing.edit")
    changes = data.model_dump(exclude_unset=True)
    try:
        room = update_bed(db, bed_id, changes)
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.bed.updated",
        actor=current_user,
        entity_type="room",
        entity_id=room.id,
        context={"fields": sorted(changes.keys())},
        request=request,
    )
    db.commit()
    return room


# --- Assignment history ---


@router.get(
    "/rooms/{room_id}/history", response_model=list[HousingAssignmentResponse]
)
def room_assignment_history(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    room_id: uuid.UUID,
) -> list[HousingAssignmentResponse]:
    """Every past and current occupant of a room, newest first."""
    _check_housing_access(current_user)
    return get_room_assignment_history(db, room_id)


@router.get(
    "/beds/{bed_id}/history", response_model=list[HousingAssignmentResponse]
)
def bed_assignment_history(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    bed_id: uuid.UUID,
) -> list[HousingAssignmentResponse]:
    """Every past and current occupant of a bed, newest first."""
    _check_housing_access(current_user)
    return get_bed_assignment_history(db, bed_id)


# --- Housing Overview ---


@router.get("/overview", response_model=HousingOverviewResponse)
def housing_overview_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
) -> HousingOverviewResponse:
    """Get complete housing overview for dormitory visualization."""
    _check_housing_access(current_user)
    return get_housing_overview(db)


# --- Assignment Endpoints ---


@router.post(
    "/assignments",
    response_model=HousingAssignmentResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def create_assignment_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    data: HousingAssignmentCreate,
    request: Request,
) -> HousingAssignmentResponse:
    """Create a housing assignment."""
    _check_housing_admin(current_user)

    try:
        assignment = create_housing_assignment(
            db,
            student_id=data.student_id,
            bed_id=data.bed_id,
            start_date=data.start_date,
            notes=data.notes,
            actor_id=current_user.id,
        )
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.assignment.created",
        actor=current_user,
        entity_type="housing_assignment",
        entity_id=assignment.id,
        context={"bed_id": str(assignment.bed_id)},
        request=request,
    )
    _notify_student(db, assignment, NotificationType.HOUSING_ASSIGNMENT_CREATED)
    db.commit()

    return assignment


@router.get(
    "/assignments/{assignment_id}",
    response_model=HousingAssignmentResponse,
)
def get_assignment_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    assignment_id: uuid.UUID,
) -> HousingAssignmentResponse:
    """Get a housing assignment.

    Students may only read their own assignment; staff with housing access
    may read any.
    """
    _check_housing_access(current_user)
    assignment = get_assignment(db, assignment_id)
    if assignment is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Assignment not found.",
                }
            },
        )
    _check_assignment_scope(db, current_user, assignment.student_id)
    return assignment


@router.patch(
    "/assignments/{assignment_id}",
    response_model=HousingAssignmentResponse,
)
def update_assignment_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    assignment_id: uuid.UUID,
    data: HousingAssignmentUpdate,
    request: Request,
) -> HousingAssignmentResponse:
    """Update notes / end date / status of a housing assignment."""
    _check_housing_admin(current_user)

    try:
        assignment = update_housing_assignment(
            db,
            assignment_id,
            data.model_dump(exclude_unset=True),
            actor_id=current_user.id,
        )
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.assignment.updated",
        actor=current_user,
        entity_type="housing_assignment",
        entity_id=assignment.id,
        context={"fields": sorted(data.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    db.commit()
    return assignment


@router.post(
    "/assignments/{assignment_id}/transfer",
    response_model=HousingAssignmentResponse,
)
def transfer_assignment_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    assignment_id: uuid.UUID,
    data: HousingAssignmentTransfer,
    request: Request,
) -> HousingAssignmentResponse:
    """Transfer a student to a new bed (single transaction)."""
    _check_housing_admin(current_user)

    try:
        new_assignment = transfer_student(
            db,
            assignment_id=assignment_id,
            new_bed_id=data.new_bed_id,
            transfer_date=data.transfer_date,
            notes=data.notes,
            actor_id=current_user.id,
        )
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.assignment.transferred",
        actor=current_user,
        entity_type="housing_assignment",
        entity_id=new_assignment.id,
        context={
            "from_assignment_id": str(assignment_id),
            "bed_id": str(new_assignment.bed_id),
        },
        request=request,
    )
    _notify_student(db, new_assignment, NotificationType.HOUSING_ASSIGNMENT_TRANSFERRED)
    db.commit()

    return new_assignment


@router.post(
    "/assignments/{assignment_id}/end",
    response_model=HousingAssignmentResponse,
)
def end_assignment_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    assignment_id: uuid.UUID,
    request: Request,
) -> HousingAssignmentResponse:
    """End a housing assignment."""
    _check_housing_admin(current_user)
    try:
        assignment = end_housing_assignment(
            db, assignment_id, actor_id=current_user.id
        )
    except ValueError as e:
        raise _rule_error(e) from e

    record_audit(
        db,
        action="housing.assignment.ended",
        actor=current_user,
        entity_type="housing_assignment",
        entity_id=assignment.id,
        request=request,
    )
    _notify_student(db, assignment, NotificationType.HOUSING_ASSIGNMENT_ENDED)
    db.commit()
    return assignment


# --- Student Housing ---


@router.get(
    "/students/{student_id}/housing",
    response_model=StudentHousingResponse,
)
def get_student_housing_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
) -> StudentHousingResponse:
    """Get a student's current housing assignment.

    `housing.view` is a feature permission, not an object-scope decision.
    Students hold it for self-service, so the centralized student-scope policy
    must also prove that the requested student is the caller's own record.
    """
    from app.models.identity import Student

    # Resolve student record to user_id for housing lookup.
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Student not found.",
                }
            },
        )

    if not can_view_housing(db, current_user, student.id):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You can only view your own housing information.",
                }
            },
        )

    return get_student_housing(db, student.user_id)


# --- Controlled import -------------------------------------------------------
#
# The housing office's allocation sheet is imported through preview + confirm:
# the first call validates every row without writing, and the second one applies
# the same file after the operator has seen the report. Importing is a data
# change with physical consequences (a student arrives to a taken bed), so it is
# gated on `housing.assign` and audited with the counts that were applied.


def _require_import_permission(current_user: CurrentUser) -> None:
    from app.permissions.checks import has_permission

    if not has_permission(current_user, "housing.assign"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to import housing assignments.",
                }
            },
        )


def _read_upload(file: UploadFile) -> bytes:
    settings = get_settings()
    limit = settings.MAX_IMPORT_SIZE_MB * 1024 * 1024
    raw = file.file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(
            status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": {
                    "code": "IMPORT_TOO_LARGE",
                    "message": f"The file is larger than {settings.MAX_IMPORT_SIZE_MB} MB.",
                }
            },
        )
    return raw


def _parse_or_400(raw: bytes):
    try:
        return parse_rows(raw, max_rows=get_settings().MAX_IMPORT_ROWS)
    except ImportFileError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": exc.code, "message": exc.message}},
        ) from exc


@router.get("/import/template")
def housing_import_template_endpoint(
    current_user: CurrentUser,
) -> Response:
    """Download the CSV template the housing office fills in."""
    _require_import_permission(current_user)
    return Response(
        content=build_template_csv(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="housing-import-template.csv"',
            # The template contains no personal data, but it is generated per
            # request; a shared cache would be pointless and confusing.
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/import/preview", response_model=HousingImportReport)
def housing_import_preview_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> HousingImportReport:
    """Validate an allocation file without changing any record."""
    _require_import_permission(current_user)
    return preview_housing_import(db, _parse_or_400(_read_upload(file)))


@router.post("/import/apply", response_model=HousingImportReport)
def housing_import_apply_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    request: Request,
    file: Annotated[UploadFile, File()],
    confirm: Annotated[bool, Query()] = False,
    source_reference: Annotated[str | None, Query(max_length=200)] = None,
) -> HousingImportReport:
    """Apply a file that has been previewed and explicitly confirmed."""
    _require_import_permission(current_user)
    if not confirm:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "IMPORT_CONFIRMATION_REQUIRED",
                    "message": "Preview the file and explicitly confirm it before applying.",
                }
            },
        )

    rows = _parse_or_400(_read_upload(file))
    report = apply_housing_import(
        db, rows, actor_id=current_user.id, source_reference=source_reference
    )

    record_audit(
        db,
        action="housing.import.applied",
        actor=current_user,
        entity_type="housing_import",
        entity_id=None,
        context={
            "source_reference": source_reference,
            "total": report.total,
            "created": report.created,
            "skipped": report.skipped,
            "failed": report.failed,
            "aborted": report.aborted,
        },
        request=request,
    )
    # The audit entry commits with the batch that produced it. A failed batch
    # is still worth recording: an attempted import is an operational event.
    db.commit()

    return report
