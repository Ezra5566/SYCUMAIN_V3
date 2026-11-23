"""Dormitory attendance service.

The rules this module owns
--------------------------
* A student is eligible for dormitory attendance only while an institutional
  housing assignment covers the date. Eligibility is resolved from the
  assignment's own ``start_date``/``end_date`` — never from the student's
  *current* housing status, and never only from their latest assignment. A
  student who moved out keeps the absences recorded while resident; a student
  who returns starts a second, separate set against the new stay.
* Every calendar day counts. Weekends, public holidays and vacations are not
  exceptions here, and the university calendar is never consulted: an academic
  exception must not move a residential record.
* Only absences are stored. Physical presence is handled outside the system, so
  there is no ``PRESENT`` row and no daily check-in.
* A correction supersedes. The previous date, points, reason and recorder stay
  readable, and the change is audited in the same transaction.
* Points are administrative. No default, no threshold and no derived penalty:
  the institution has not published a scale, so this module never invents one.

There is no percentage, no term window and no admission coupling. A student with
no active admission but an active bed is still a resident, and vice versa.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - SQLAlchemy resolves UUID at runtime
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, not_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import record_audit
from app.models.dormitory_absence import DormitoryAbsence
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
)
from app.models.identity import Student, User

if TYPE_CHECKING:
    from app.schemas.dormitory_attendance import (
        DormitoryAbsenceCancel,
        DormitoryAbsenceCorrect,
        DormitoryAbsenceCreate,
    )

#: A correction must explain itself; recording an absence only needs a reason
#: for the absence. Both mirror the academic attendance contract so staff learn
#: one set of expectations.
MIN_CORRECTION_REASON_LENGTH = 10

MAX_PAGE_SIZE = 100

#: Staff roles that may read and write dormitory attendance. Teachers are
#: deliberately absent: the institution has not approved dormitory access for
#: them, and a class roster is not a residential roster.
DORMITORY_STAFF_ROLES: frozenset[str] = frozenset({"ADMIN", "MANAGEMENT"})

#: The predicate for a row that still counts. A superseded row was replaced by a
#: correction; a cancelled row was withdrawn outright. Neither contributes to a
#: count, a points total or a duplicate check — only the live record does.
_ACTIVE = (
    DormitoryAbsence.superseded_at.is_(None),
    DormitoryAbsence.cancelled_at.is_(None),
)


class DormitoryError(ValueError):
    """A dormitory rule refusal carrying a stable, localisable error code."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


# ── Time helpers ──


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


def _as_date(value: datetime | None) -> date | None:
    """The UTC calendar date of a stored timestamp.

    Housing timestamps are written in UTC. Comparing in UTC on both sides keeps
    this service and the database trigger in agreement regardless of the
    server's local timezone.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(UTC).date()


def _covers(assignment: HousingAssignment, day: date) -> bool:
    """Whether a stay includes ``day``.

    The end date is **inclusive**: it is the last day of residency. That is what
    makes a transfer gapless — the old assignment ends on the transfer date and
    the new one starts on it — and it matches how the housing service writes
    ``end_date`` when a student moves out.
    """
    start = _as_date(assignment.start_date)
    end = _as_date(assignment.end_date)
    if start is None or day < start:
        return False
    return end is None or day <= end


# ── Access ──


def _role_names(user: User) -> set[str]:
    return {role.name for role in user.roles}


def ensure_staff(user: User) -> None:
    """Dormitory surfaces are for Admin and Management only.

    Students have their own read-only endpoint; teachers have no access at all,
    because a teaching assignment says nothing about who lives in the dormitory.
    """
    if not (_role_names(user) & DORMITORY_STAFF_ROLES):
        raise DormitoryError(
            "DORMITORY_FORBIDDEN",
            "You do not have access to dormitory attendance records.",
            status_code=403,
        )


# ── Loading ──


def _load_student(db: DBSession, student_id: uuid.UUID) -> Student:
    student = db.query(Student).filter(Student.id == student_id).first()
    if student is None:
        raise DormitoryError(
            "STUDENT_NOT_FOUND", "Student not found.", status_code=404
        )
    return student


def _assignments(db: DBSession, student: Student) -> list[HousingAssignment]:
    """Every stay that can carry attendance, newest first.

    ``CANCELLED`` assignments are excluded: a cancelled placement is treated as
    one that never took effect, so it can neither justify an absence nor appear
    in the residency history. ``ENDED`` stays are kept — they are exactly the
    history this module must preserve.
    """
    return (
        db.query(HousingAssignment)
        .filter(
            HousingAssignment.student_id == student.user_id,
            HousingAssignment.status != HousingAssignmentStatus.CANCELLED.value,
        )
        .order_by(
            HousingAssignment.start_date.desc(),
            HousingAssignment.created_at.desc(),
        )
        .all()
    )


def _labels(db: DBSession, assignment_ids: list[uuid.UUID]) -> dict:
    """Building / floor / room / bed for a set of assignments, in one query."""
    if not assignment_ids:
        return {}
    rows = (
        db.query(
            HousingAssignment.id,
            Building.name,
            Floor.floor_number,
            Room.room_number,
            Bed.label,
            Bed.bed_number,
        )
        .join(Bed, Bed.id == HousingAssignment.bed_id)
        .join(Room, Room.id == Bed.room_id)
        .join(Floor, Floor.id == Room.floor_id)
        .join(Building, Building.id == Floor.building_id)
        .filter(HousingAssignment.id.in_(assignment_ids))
        .all()
    )
    return {
        row[0]: {
            "building_name": row[1],
            "floor_number": row[2],
            "room_number": row[3],
            "bed_label": row[4],
            "bed_number": row[5],
        }
        for row in rows
    }


def _residency_state(
    assignments: list[HousingAssignment], today: date
) -> tuple[bool, str | None]:
    """``(is_resident_today, ineligible_reason)`` for a set of stays."""
    if not assignments:
        return False, "NO_HOUSING_ASSIGNMENT"
    if any(_covers(assignment, today) for assignment in assignments):
        return True, None

    starts = [start for start in (_as_date(a.start_date) for a in assignments) if start]
    if starts and min(starts) > today:
        return False, "ASSIGNMENT_NOT_STARTED"
    if any(start > today for start in starts):
        # An assignment exists but has not begun, and none covers today: the
        # student is between two stays rather than gone for good.
        return False, "BETWEEN_ASSIGNMENTS"
    return False, "ASSIGNMENT_ENDED"


def _resolve_assignment(
    db: DBSession,
    student: Student,
    day: date,
    explicit_id: uuid.UUID | None = None,
) -> HousingAssignment:
    """The stay an absence on ``day`` belongs to."""
    assignments = _assignments(db, student)

    if explicit_id is not None:
        match = next((a for a in assignments if a.id == explicit_id), None)
        if match is None:
            raise DormitoryError(
                "DORMITORY_ASSIGNMENT_NOT_FOUND",
                "That housing assignment does not belong to this student.",
                status_code=404,
            )
        if not _covers(match, day):
            raise DormitoryError(
                "DORMITORY_DATE_OUTSIDE_ASSIGNMENT",
                "That date is outside the effective period of the housing assignment.",
                status_code=422,
            )
        return match

    covering = [a for a in assignments if _covers(a, day)]
    if covering:
        # `_assignments` is newest-first, so the most recent stay wins when two
        # assignments share a date (a transfer boundary).
        return covering[0]

    if not assignments:
        raise DormitoryError(
            "DORMITORY_NO_HOUSING_ASSIGNMENT",
            "The student has no institutional housing assignment.",
            status_code=422,
        )
    raise DormitoryError(
        "DORMITORY_DATE_OUTSIDE_ASSIGNMENT",
        "The student was not resident in institutional housing on that date.",
        status_code=422,
    )


def _points(value: float) -> Decimal:
    """Store points at the column's scale without binary-float drift."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


# ── Reads ──


def list_students(
    db: DBSession,
    *,
    search: str | None = None,
    residency: str = "all",
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """Students with a housing history, current residents first.

    Only students who have ever held a non-cancelled assignment appear: a
    student with no institutional room has no dormitory attendance to manage.
    Their ineligibility is still proved by the detail endpoint and by the
    refusal to record.
    """
    latest = (
        db.query(
            HousingAssignment.id.label("assignment_id"),
            HousingAssignment.student_id.label("user_id"),
            HousingAssignment.start_date.label("start_date"),
            HousingAssignment.end_date.label("end_date"),
            HousingAssignment.status.label("status"),
        )
        .filter(HousingAssignment.status != HousingAssignmentStatus.CANCELLED.value)
        .distinct(HousingAssignment.student_id)
        .order_by(
            HousingAssignment.student_id,
            HousingAssignment.start_date.desc(),
            HousingAssignment.created_at.desc(),
        )
        .subquery()
    )

    now = _now()
    is_current = and_(
        latest.c.start_date <= now,
        or_(latest.c.end_date.is_(None), latest.c.end_date >= now),
    )

    base = (
        db.query(
            Student.id.label("student_id"),
            Student.student_id.label("student_number"),
            User.full_name.label("student_name"),
            Student.user_id.label("user_id"),
            latest.c.assignment_id,
            latest.c.start_date,
            latest.c.end_date,
            latest.c.status,
            is_current.label("is_current"),
        )
        .join(User, User.id == Student.user_id)
        .join(latest, latest.c.user_id == Student.user_id)
    )

    if search and search.strip():
        term = f"%{search.strip()}%"
        base = base.filter(
            or_(Student.student_id.ilike(term), User.full_name.ilike(term))
        )
    if residency == "current":
        base = base.filter(is_current)
    elif residency == "former":
        base = base.filter(not_(is_current))

    total = base.count()
    rows = (
        base.order_by(
            is_current.desc(), User.full_name.asc(), Student.student_id.asc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    if not rows:
        return {"items": [], "total": total, "page": page, "page_size": page_size}

    student_ids = [row.student_id for row in rows]
    user_ids = [row.user_id for row in rows]

    # Points and counts are student-level, across every stay: the accumulated
    # figure is what an administrator asks for, not a per-room subtotal.
    stats: dict[uuid.UUID, tuple[int, Decimal]] = {}
    for student_id, count, points in (
        db.query(
            DormitoryAbsence.student_id,
            func.count(DormitoryAbsence.id),
            func.coalesce(func.sum(DormitoryAbsence.points), 0),
        )
        .filter(
            DormitoryAbsence.student_id.in_(student_ids),
            *_ACTIVE,
        )
        .group_by(DormitoryAbsence.student_id)
        .all()
    ):
        stats[student_id] = (count, points)

    labels = _labels(db, [row.assignment_id for row in rows])

    # All stays per student, so a student between two assignments is labelled
    # "between assignments" rather than "former resident".
    stays: dict[uuid.UUID, list[HousingAssignment]] = defaultdict(list)
    for assignment in (
        db.query(HousingAssignment)
        .filter(
            HousingAssignment.student_id.in_(user_ids),
            HousingAssignment.status != HousingAssignmentStatus.CANCELLED.value,
        )
        .all()
    ):
        stays[assignment.student_id].append(assignment)

    today = _today()
    items = []
    for row in rows:
        is_resident, reason = _residency_state(stays[row.user_id], today)
        label = labels.get(row.assignment_id, {})
        count, points = stats.get(row.student_id, (0, Decimal("0")))
        items.append(
            {
                "student_id": row.student_id,
                "student_number": row.student_number,
                "student_name": row.student_name,
                "housing_assignment_id": row.assignment_id,
                "building_name": label.get("building_name"),
                "floor_number": label.get("floor_number"),
                "room_number": label.get("room_number"),
                "bed_label": label.get("bed_label"),
                "bed_number": label.get("bed_number"),
                "assignment_start_date": _as_date(row.start_date),
                "assignment_end_date": _as_date(row.end_date),
                "assignment_status": row.status,
                "is_current_resident": is_resident,
                "eligible_today": is_resident,
                "ineligible_reason": reason,
                "absence_count": count,
                "points_total": float(points),
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def student_detail(db: DBSession, student_id: uuid.UUID) -> dict:
    """One student's stays, absences, correction history and accumulated points."""
    student = _load_student(db, student_id)
    user = db.query(User).filter(User.id == student.user_id).first()
    if user is None:
        raise DormitoryError("STUDENT_NOT_FOUND", "Student not found.", status_code=404)

    assignments = _assignments(db, student)
    labels = _labels(db, [a.id for a in assignments])

    absences = (
        db.query(DormitoryAbsence)
        .filter(DormitoryAbsence.student_id == student.id)
        .order_by(
            DormitoryAbsence.absence_date.desc(),
            DormitoryAbsence.recorded_at.desc(),
        )
        .all()
    )

    recorder_ids = {row.recorded_by_id for row in absences}
    recorder_ids |= {
        row.cancelled_by_id for row in absences if row.cancelled_by_id is not None
    }
    recorders: dict[uuid.UUID, str] = {}
    if recorder_ids:
        recorders = {
            row.id: row.full_name
            for row in db.query(User).filter(User.id.in_(recorder_ids)).all()
        }

    per_assignment: dict[uuid.UUID, tuple[int, Decimal]] = {}
    for assignment_id, count, points in (
        db.query(
            DormitoryAbsence.housing_assignment_id,
            func.count(DormitoryAbsence.id),
            func.coalesce(func.sum(DormitoryAbsence.points), 0),
        )
        .filter(
            DormitoryAbsence.student_id == student.id,
            *_ACTIVE,
        )
        .group_by(DormitoryAbsence.housing_assignment_id)
        .all()
    ):
        per_assignment[assignment_id] = (count, points)

    today = _today()
    is_resident, reason = _residency_state(assignments, today)
    current = next((a for a in assignments if _covers(a, today)), None)

    def assignment_payload(assignment: HousingAssignment) -> dict:
        label = labels.get(assignment.id, {})
        count, points = per_assignment.get(assignment.id, (0, Decimal("0")))
        return {
            "id": assignment.id,
            "building_name": label.get("building_name"),
            "floor_number": label.get("floor_number"),
            "room_number": label.get("room_number"),
            "bed_label": label.get("bed_label"),
            "bed_number": label.get("bed_number"),
            "start_date": _as_date(assignment.start_date),
            "end_date": _as_date(assignment.end_date),
            "status": assignment.status,
            "is_current": _covers(assignment, today),
            "absence_count": count,
            "points_total": float(points),
        }

    absence_payload = [
        {
            "id": row.id,
            "student_id": row.student_id,
            "housing_assignment_id": row.housing_assignment_id,
            "absence_date": row.absence_date,
            "points": float(row.points),
            "reason": row.reason,
            "recorded_by_id": row.recorded_by_id,
            "recorded_by_name": recorders.get(row.recorded_by_id),
            "recorded_at": row.recorded_at,
            "supersedes_id": row.supersedes_id,
            "superseded_at": row.superseded_at,
            "cancelled_at": row.cancelled_at,
            "cancelled_by_id": row.cancelled_by_id,
            "cancelled_by_name": (
                recorders.get(row.cancelled_by_id) if row.cancelled_by_id else None
            ),
            "cancellation_reason": row.cancellation_reason,
            "is_active": row.superseded_at is None and row.cancelled_at is None,
        }
        for row in absences
    ]

    current_rows = [
        row
        for row in absences
        if row.superseded_at is None and row.cancelled_at is None
    ]

    return {
        "student_id": student.id,
        "student_number": student.student_id,
        "student_name": user.full_name,
        "has_assignment": bool(assignments),
        "is_current_resident": is_resident,
        "eligible_today": is_resident,
        "ineligible_reason": reason,
        "current_assignment": assignment_payload(current) if current else None,
        "assignments": [assignment_payload(a) for a in assignments],
        "absences": absence_payload,
        "absence_count": len(current_rows),
        "points_total": float(sum((row.points for row in current_rows), Decimal("0"))),
    }


def my_dormitory(db: DBSession, user: User) -> dict:
    """The signed-in student's own dormitory history."""
    student = db.query(Student).filter(Student.user_id == user.id).first()
    if student is None:
        raise DormitoryError(
            "DORMITORY_NO_STUDENT_RECORD",
            "No student record is linked to this account.",
            status_code=404,
        )
    return student_detail(db, student.id)


# ── Writes ──


def _duplicate_exists(
    db: DBSession,
    *,
    student_id: uuid.UUID,
    assignment_id: uuid.UUID,
    day: date,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    query = db.query(DormitoryAbsence.id).filter(
        DormitoryAbsence.student_id == student_id,
        DormitoryAbsence.housing_assignment_id == assignment_id,
        DormitoryAbsence.absence_date == day,
        *_ACTIVE,
    )
    if exclude_id is not None:
        query = query.filter(DormitoryAbsence.id != exclude_id)
    return query.first() is not None


def _absence_payload(db: DBSession, row: DormitoryAbsence) -> dict:
    recorder = db.query(User).filter(User.id == row.recorded_by_id).first()
    canceller = (
        db.query(User).filter(User.id == row.cancelled_by_id).first()
        if row.cancelled_by_id
        else None
    )
    return {
        "id": row.id,
        "student_id": row.student_id,
        "housing_assignment_id": row.housing_assignment_id,
        "absence_date": row.absence_date,
        "points": float(row.points),
        "reason": row.reason,
        "recorded_by_id": row.recorded_by_id,
        "recorded_by_name": recorder.full_name if recorder else None,
        "recorded_at": row.recorded_at,
        "supersedes_id": row.supersedes_id,
        "superseded_at": row.superseded_at,
        "cancelled_at": row.cancelled_at,
        "cancelled_by_id": row.cancelled_by_id,
        "cancelled_by_name": canceller.full_name if canceller else None,
        "cancellation_reason": row.cancellation_reason,
        "is_active": row.superseded_at is None and row.cancelled_at is None,
    }


def _totals(db: DBSession, student_id: uuid.UUID) -> tuple[int, float]:
    count, points = (
        db.query(
            func.count(DormitoryAbsence.id),
            func.coalesce(func.sum(DormitoryAbsence.points), 0),
        )
        .filter(
            DormitoryAbsence.student_id == student_id,
            *_ACTIVE,
        )
        .one()
    )
    return count, float(points)


def record_absence(
    db: DBSession,
    data: DormitoryAbsenceCreate,
    actor: User,
    *,
    student_id: uuid.UUID,
    request: object | None = None,
) -> dict:
    """Record one absence against the stay that covers its date."""
    student = _load_student(db, student_id)

    day = data.absence_date
    if day > _today():
        raise DormitoryError(
            "DORMITORY_ABSENCE_IN_FUTURE",
            "A dormitory absence cannot be recorded for a future date.",
            status_code=422,
        )

    reason = data.reason.strip()
    if not reason:
        raise DormitoryError(
            "DORMITORY_REASON_REQUIRED",
            "A reason is required for a dormitory absence.",
            status_code=422,
        )

    assignment = _resolve_assignment(db, student, day, data.housing_assignment_id)

    if _duplicate_exists(
        db,
        student_id=student.id,
        assignment_id=assignment.id,
        day=day,
    ):
        raise DormitoryError(
            "DORMITORY_ABSENCE_ALREADY_RECORDED",
            "An absence is already recorded for that student, housing assignment "
            "and date. Correct the existing record instead.",
        )

    row = DormitoryAbsence(
        student_id=student.id,
        housing_assignment_id=assignment.id,
        absence_date=day,
        points=_points(data.points),
        reason=reason,
        recorded_by_id=actor.id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # The partial unique index is authoritative; translate it rather than
        # leaking a database error, so a concurrent duplicate reads the same as
        # a sequential one.
        db.rollback()
        raise DormitoryError(
            "DORMITORY_ABSENCE_ALREADY_RECORDED",
            "An absence is already recorded for that student, housing assignment "
            "and date. Correct the existing record instead.",
        ) from None

    # The absence and its audit entry are one transaction. Rolling back on an
    # audit failure is not decoration: without it the flushed row would stay
    # pending in the session, and any later commit in the same request would
    # persist an absence that no audit entry describes.
    try:
        record_audit(
            db,
            action="dormitory.absence.recorded",
            actor=actor,
            entity_type="dormitory_absence",
            entity_id=row.id,
            context={
                "student_id": student.id,
                "housing_assignment_id": assignment.id,
                "absence_date": day,
                "points": float(row.points),
                "reason": reason,
            },
            request=request,
        )
    except Exception:
        db.rollback()
        raise
    db.commit()
    db.refresh(row)

    count, points_total = _totals(db, student.id)
    return {
        "absence": _absence_payload(db, row),
        "absence_count": count,
        "points_total": points_total,
    }


def correct_absence(
    db: DBSession,
    data: DormitoryAbsenceCorrect,
    actor: User,
    *,
    student_id: uuid.UUID,
    absence_id: uuid.UUID,
    request: object | None = None,
) -> dict:
    """Supersede a current absence, keeping the previous row readable."""
    student = _load_student(db, student_id)

    original = (
        db.query(DormitoryAbsence)
        .filter(
            DormitoryAbsence.id == absence_id,
            DormitoryAbsence.student_id == student.id,
            *_ACTIVE,
        )
        .with_for_update()
        .first()
    )
    if original is None:
        raise DormitoryError(
            "DORMITORY_ABSENCE_NOT_FOUND",
            "That absence does not exist, has already been replaced, or has "
            "been cancelled.",
            status_code=404,
        )

    reason = data.reason.strip()
    if len(reason) < MIN_CORRECTION_REASON_LENGTH:
        raise DormitoryError(
            "DORMITORY_CORRECTION_REASON_REQUIRED",
            "A correction needs a reason of at least "
            f"{MIN_CORRECTION_REASON_LENGTH} characters.",
            status_code=422,
        )

    day = data.absence_date
    if day > _today():
        raise DormitoryError(
            "DORMITORY_ABSENCE_IN_FUTURE",
            "A dormitory absence cannot be recorded for a future date.",
            status_code=422,
        )

    points = _points(data.points)
    if (day, points, reason) == (
        original.absence_date,
        original.points,
        original.reason,
    ):
        raise DormitoryError(
            "DORMITORY_ABSENCE_UNCHANGED",
            "The corrected record is identical to the current one.",
            status_code=422,
        )

    # A correction may move the absence to another stay in the student's real
    # housing history — that is what makes it possible to fix a record filed
    # against the wrong room after a transfer. An explicit assignment is always
    # honoured when it covers the corrected date. Otherwise an unchanged date
    # keeps the stay the absence was recorded against (re-resolving could
    # silently move it), and a changed date resolves the stay that covers the
    # new date.
    if data.housing_assignment_id is not None:
        assignment = _resolve_assignment(
            db, student, day, data.housing_assignment_id
        )
    elif day == original.absence_date:
        assignment = _resolve_assignment(
            db, student, day, original.housing_assignment_id
        )
    else:
        assignment = _resolve_assignment(db, student, day, None)

    if _duplicate_exists(
        db,
        student_id=student.id,
        assignment_id=assignment.id,
        day=day,
        exclude_id=original.id,
    ):
        raise DormitoryError(
            "DORMITORY_ABSENCE_ALREADY_RECORDED",
            "An absence is already recorded for that student, housing assignment "
            "and date.",
        )

    previous = {
        "previous_absence_date": original.absence_date,
        "previous_points": float(original.points),
        "previous_reason": original.reason,
        "previous_housing_assignment_id": original.housing_assignment_id,
    }

    original.superseded_at = _now()
    replacement = DormitoryAbsence(
        student_id=student.id,
        housing_assignment_id=assignment.id,
        absence_date=day,
        points=points,
        reason=reason,
        recorded_by_id=actor.id,
        supersedes_id=original.id,
    )
    db.add(replacement)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise DormitoryError(
            "DORMITORY_ABSENCE_ALREADY_RECORDED",
            "An absence is already recorded for that student, housing assignment "
            "and date.",
        ) from None

    try:
        record_audit(
            db,
            action="dormitory.absence.corrected",
            actor=actor,
            entity_type="dormitory_absence",
            entity_id=replacement.id,
            context={
                **previous,
                "student_id": student.id,
                "housing_assignment_id": assignment.id,
                "absence_date": day,
                "points": float(points),
                "reason": reason,
            },
            request=request,
        )
    except Exception:
        db.rollback()
        raise
    db.commit()
    db.refresh(replacement)

    count, points_total = _totals(db, student.id)
    return {
        "absence": _absence_payload(db, replacement),
        "absence_count": count,
        "points_total": points_total,
    }


def cancel_absence(
    db: DBSession,
    data: DormitoryAbsenceCancel,
    actor: User,
    *,
    student_id: uuid.UUID,
    absence_id: uuid.UUID,
    request: object | None = None,
) -> dict:
    """Withdraw an absence without deleting it.

    Cancellation is not a correction to zero points. A zero-point absence still
    asserts the student was absent; a cancellation asserts they were not. The
    row stays exactly where it is — with its original date, points, reason and
    recorder — and the three cancellation columns record who withdrew it, when
    and why. From that moment it contributes to no count and no points total,
    and the date is free for a correct record.
    """
    student = _load_student(db, student_id)

    original = (
        db.query(DormitoryAbsence)
        .filter(
            DormitoryAbsence.id == absence_id,
            DormitoryAbsence.student_id == student.id,
            *_ACTIVE,
        )
        .with_for_update()
        .first()
    )
    if original is None:
        raise DormitoryError(
            "DORMITORY_ABSENCE_NOT_FOUND",
            "That absence does not exist, has already been replaced, or has "
            "already been cancelled.",
            status_code=404,
        )

    reason = data.reason.strip()
    if len(reason) < MIN_CORRECTION_REASON_LENGTH:
        raise DormitoryError(
            "DORMITORY_CANCELLATION_REASON_REQUIRED",
            "A cancellation needs a reason of at least "
            f"{MIN_CORRECTION_REASON_LENGTH} characters.",
            status_code=422,
        )

    previous = {
        "absence_date": original.absence_date,
        "points": float(original.points),
        "reason": original.reason,
        "housing_assignment_id": original.housing_assignment_id,
    }

    original.cancelled_at = _now()
    original.cancelled_by_id = actor.id
    original.cancellation_reason = reason

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise DormitoryError(
            "DORMITORY_ABSENCE_NOT_FOUND",
            "That absence was changed by another request. Reload and retry.",
        ) from None

    try:
        record_audit(
            db,
            action="dormitory.absence.cancelled",
            actor=actor,
            entity_type="dormitory_absence",
            entity_id=original.id,
            context={
                **previous,
                "student_id": student.id,
                "cancellation_reason": reason,
            },
            request=request,
        )
    except Exception:
        db.rollback()
        raise
    db.commit()
    db.refresh(original)

    count, points_total = _totals(db, student.id)
    return {
        "absence": _absence_payload(db, original),
        "absence_count": count,
        "points_total": points_total,
    }
