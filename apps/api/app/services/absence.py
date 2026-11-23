"""Student attendance as absences (Phase 3, corrected model).

The institution counts one attendance figure per student per admission episode.
This module therefore never reasons about subjects, sections or class sessions:
it records a student's absence on a date and derives the percentage from the
university calendar and the approved commencement.

The rules it owns
-----------------
* Only an ACTIVE episode can receive an absence; a terminal episode may still be
  *read*, but its figure stops at the date it ended.
* An absence must fall on an eligible working day, on or after the approved
  commencement, inside the intake's instructional period, and not in the future.
* Absences are the only stored fact. A working day with no absence is a day the
  student attended — no ``PRESENT`` row is ever generated.
* A correction supersedes; a cancellation retires the record without deleting it.
  Both leave the previous date, reason, recorder and timestamp readable, and both
  are audited in the same transaction as the change.
* Only absences that fall on a day the calendar *currently* treats as a working
  day count. A holiday or closure declared afterwards removes that day from both
  sides of the ratio; an exceptional working day adds it back. The record itself
  survives either way.
* The percentage is derived on read: ``(eligible − countable absences) / eligible``.
  It is never stored and never clamped, so a late holiday or a cancelled absence
  cannot leave a stale figure — or be hidden behind a floor of zero — behind it.

Deliberately absent: thresholds, grades, LATE/EXCUSED weighting, automatic
absence generation, and backfill. Those are policy decisions the institution has
not made.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - SQLAlchemy resolves UUID at runtime
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import record_audit
from app.models.academic import (
    AcademicPeriod,
    Enrollment,
    EnrollmentStatus,
    TeacherAssignment,
)
from app.models.admission import AcademicAdmission, AcademicAdmissionStatus
from app.models.attendance import AttendanceCommencement
from app.models.attendance_absence import AttendanceAbsence
from app.models.identity import Staff, Student, User
from app.services import calendar as calendar_svc

if TYPE_CHECKING:
    from app.schemas.absence import AbsenceCancel, AbsenceCorrect, AbsenceCreate

#: Recording an absence needs a reason; correcting a record needs a justification
#: long enough to explain the change to an auditor.
MIN_RECORD_REASON_LENGTH = 1
MIN_CORRECTION_REASON_LENGTH = 10
MIN_CANCELLATION_REASON_LENGTH = 10

#: Statuses that may receive a new absence.
RECORDABLE_STATUSES: frozenset[str] = frozenset(
    {AcademicAdmissionStatus.ACTIVE.value}
)

MAX_PAGE_SIZE = 100


class AbsenceError(ValueError):
    """An attendance refusal carrying a stable, localisable error code."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.utcnow()


def _today() -> date:
    return _now().date()


# ── Access ──


def _role_names(user: User) -> set[str]:
    return {role.name for role in user.roles}


def _teacher_class_ids(db: DBSession, user: User) -> set[uuid.UUID] | None:
    """Class sections the caller teaches, or ``None`` when unrestricted."""
    if {"ADMIN", "MANAGEMENT"} & _role_names(user):
        return None
    staff = db.query(Staff).filter(Staff.user_id == user.id).first()
    if staff is None or not staff.is_active:
        return set()
    rows = (
        db.query(TeacherAssignment.class_section_id)
        .filter(
            TeacherAssignment.staff_id == staff.id,
            TeacherAssignment.is_active.is_(True),
        )
        .all()
    )
    return {row[0] for row in rows}


def ensure_staff(user: User) -> None:
    """The staff surfaces are not for students, who have their own endpoint."""
    if not (_role_names(user) & {"ADMIN", "MANAGEMENT", "TEACHER"}):
        raise AbsenceError(
            "ATTENDANCE_FORBIDDEN",
            "You do not have access to student attendance records.",
            status_code=403,
        )


def ensure_student_access(db: DBSession, user: User, student_id: uuid.UUID) -> None:
    """Staff scope: Admin/Management anywhere, a teacher for their own students.

    A teacher may record an absence only for a student enrolled in a section
    they are assigned to. The attendance *figure* stays university-wide once
    recorded — this is a permission to write, not a filter on the total.
    """
    class_ids = _teacher_class_ids(db, user)
    if class_ids is None:
        return
    if not class_ids:
        raise AbsenceError(
            "ATTENDANCE_STUDENT_OUT_OF_SCOPE",
            "This student is not in one of your class sections.",
            status_code=403,
        )
    enrolled = (
        db.query(Enrollment.id)
        .filter(
            Enrollment.student_id == student_id,
            Enrollment.class_section_id.in_(class_ids),
            Enrollment.status == EnrollmentStatus.ENROLLED.value,
        )
        .first()
    )
    if enrolled is None:
        raise AbsenceError(
            "ATTENDANCE_STUDENT_OUT_OF_SCOPE",
            "This student is not in one of your class sections.",
            status_code=403,
        )


# ── Loading ──


def _load_student(db: DBSession, student_id: uuid.UUID) -> Student:
    student = db.query(Student).filter(Student.id == student_id).first()
    if student is None:
        raise AbsenceError("STUDENT_NOT_FOUND", "Student not found.", status_code=404)
    return student


def _load_episode(
    db: DBSession, *, student_id: uuid.UUID, admission_id: uuid.UUID
) -> AcademicAdmission:
    episode = (
        db.query(AcademicAdmission)
        .filter(
            AcademicAdmission.id == admission_id,
            AcademicAdmission.student_id == student_id,
        )
        .first()
    )
    if episode is None:
        raise AbsenceError(
            "ABSENCE_ADMISSION_NOT_FOUND",
            "Admission episode not found for this student.",
            status_code=404,
        )
    return episode


def _period(db: DBSession, episode: AcademicAdmission) -> AcademicPeriod:
    period = (
        db.query(AcademicPeriod)
        .filter(AcademicPeriod.id == episode.admission_intake_id)
        .first()
    )
    if period is None:
        raise AbsenceError(
            "ABSENCE_PERIOD_NOT_FOUND",
            "The episode's academic period could not be found.",
        )
    return period


def _commencement_date(db: DBSession, admission_id: uuid.UUID) -> date | None:
    row = (
        db.query(AttendanceCommencement.commencement_date)
        .filter(
            AttendanceCommencement.admission_id == admission_id,
            AttendanceCommencement.superseded_at.is_(None),
        )
        .first()
    )
    return row[0] if row else None


# ── Calendar ──


def count_working_days(db: DBSession, start_date: date, end_date: date) -> int:
    """Working days in a closed range, from the Phase 1 calendar.

    The resolver refuses ranges longer than a year, so a long episode is counted
    in chunks rather than inventing a second working-day rule here.
    """
    if end_date < start_date:
        return 0
    total = 0
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=365), end_date)
        total += sum(
            1 for day in calendar_svc.resolve_range(db, cursor, chunk_end) if day.is_working
        )
        cursor = chunk_end + timedelta(days=1)
    return total


# ── Derivation ──


def _window(
    episode: AcademicAdmission, period: AcademicPeriod, commencement: date, today: date
) -> tuple[date, date]:
    start = max(commencement, period.start_date)
    end = min(today, period.end_date)
    if episode.ended_at is not None:
        end = min(end, episode.ended_at.date())
    return start, end


def calculate(
    db: DBSession,
    *,
    episode: AcademicAdmission,
    period: AcademicPeriod,
    commencement: date | None,
    today: date | None = None,
) -> dict[str, Any]:
    """Eligible days, absences and percentage for one episode, right now."""
    today = today or _today()
    if commencement is None:
        return {
            "commencement_date": None,
            "window_start": None,
            "window_end": None,
            "calculation_date": today,
            "eligible_days": 0,
            "absence_count": 0,
            "excluded_absence_count": 0,
            "percentage": None,
        }

    start, end = _window(episode, period, commencement, today)
    if end < start:
        return {
            "commencement_date": commencement,
            "window_start": start,
            "window_end": end,
            "calculation_date": today,
            "eligible_days": 0,
            "absence_count": 0,
            "excluded_absence_count": 0,
            "percentage": None,
        }

    eligible = count_working_days(db, start, end)
    active_dates = [
        row[0]
        for row in db.query(AttendanceAbsence.absence_date)
        .filter(
            AttendanceAbsence.admission_id == episode.id,
            AttendanceAbsence.superseded_at.is_(None),
            AttendanceAbsence.cancelled_at.is_(None),
            AttendanceAbsence.absence_date >= start,
            AttendanceAbsence.absence_date <= end,
        )
        .all()
    ]
    # Calendar-aware: an absence only counts if its date is a working day *now*.
    # A holiday declared after the fact therefore drops out of both the numerator
    # and the denominator; the record stays in the history untouched.
    countable = [
        day for day in active_dates if calendar_svc.resolve_date(db, day).is_working
    ]
    absences = len(countable)
    excluded = len(active_dates) - absences

    percentage = None
    if eligible > 0:
        # No clamping: if these ever diverge, the negative figure is the honest
        # signal that the calendar and the records disagree.
        percentage = round((eligible - absences) / eligible * 100, 1)

    return {
        "commencement_date": commencement,
        "window_start": start,
        "window_end": end,
        "calculation_date": today,
        "eligible_days": eligible,
        "absence_count": absences,
        "excluded_absence_count": excluded,
        "percentage": percentage,
    }


def ineligible_reason(
    episode: AcademicAdmission, commencement: date | None, today: date
) -> str | None:
    if episode.status not in RECORDABLE_STATUSES:
        return "NO_ACTIVE_ADMISSION"
    if commencement is None:
        return "NO_COMMENCEMENT"
    if commencement > today:
        return "NOT_STARTED"
    return None


def _row(
    db: DBSession,
    *,
    student: Student,
    episode: AcademicAdmission,
    period: AcademicPeriod,
    today: date,
) -> dict[str, Any]:
    commencement = _commencement_date(db, episode.id)
    calc = calculate(
        db, episode=episode, period=period, commencement=commencement, today=today
    )
    reason = ineligible_reason(episode, commencement, today)
    return {
        "student_id": student.id,
        "student_number": student.student_id,
        "student_name": f"{student.first_name} {student.last_name}".strip(),
        "admission_id": episode.id,
        "admission_status": episode.status,
        "period_id": period.id,
        "period_name": period.name,
        "commencement_date": commencement,
        "eligible": reason is None,
        "ineligible_reason": reason,
        "eligible_days": calc["eligible_days"],
        "absence_count": calc["absence_count"],
        "excluded_absence_count": calc["excluded_absence_count"],
        "percentage": calc["percentage"],
    }


def _actor_names(db: DBSession, rows: list[AttendanceAbsence]) -> dict[uuid.UUID, str]:
    ids = {row.recorded_by_id for row in rows}
    ids |= {row.cancelled_by_id for row in rows if row.cancelled_by_id is not None}
    if not ids:
        return {}
    return {
        row[0]: row[1]
        for row in db.query(User.id, User.full_name).filter(User.id.in_(ids)).all()
    }


def _absence_read(absence: AttendanceAbsence, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": absence.id,
        "student_id": absence.student_id,
        "admission_id": absence.admission_id,
        "absence_date": absence.absence_date,
        "reason": absence.reason,
        "recorded_by_id": absence.recorded_by_id,
        "recorded_by_name": names.get(absence.recorded_by_id),
        "recorded_at": absence.recorded_at,
        "supersedes_id": absence.supersedes_id,
        "superseded_at": absence.superseded_at,
        "cancelled_at": absence.cancelled_at,
        "cancelled_by_id": absence.cancelled_by_id,
        "cancelled_by_name": (
            names.get(absence.cancelled_by_id)
            if absence.cancelled_by_id is not None
            else None
        ),
        "cancellation_reason": absence.cancellation_reason,
    }


# ── Reads ──


def list_students(
    db: DBSession,
    actor: User,
    *,
    search: str | None = None,
    period_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Active episodes with their current attendance figure."""
    today = _today()
    query = (
        db.query(Student, AcademicAdmission, AcademicPeriod)
        .join(AcademicAdmission, AcademicAdmission.student_id == Student.id)
        .join(AcademicPeriod, AcademicPeriod.id == AcademicAdmission.admission_intake_id)
        .filter(AcademicAdmission.status == AcademicAdmissionStatus.ACTIVE.value)
    )

    if period_id is not None:
        query = query.filter(AcademicPeriod.id == period_id)

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Student.student_id.ilike(term),
                Student.first_name.ilike(term),
                Student.last_name.ilike(term),
            )
        )

    class_ids = _teacher_class_ids(db, actor)
    if class_ids is not None:
        query = query.filter(
            Student.id.in_(
                db.query(Enrollment.student_id).filter(
                    Enrollment.class_section_id.in_(class_ids or {uuid.uuid4()}),
                    Enrollment.status == EnrollmentStatus.ENROLLED.value,
                )
            )
        )

    total = query.count()
    rows = (
        query.order_by(Student.last_name, Student.first_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [
            _row(db, student=student, episode=episode, period=period, today=today)
            for student, episode, period in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _absences_for(
    db: DBSession, *, admission_id: uuid.UUID, include_superseded: bool = True
) -> list[AttendanceAbsence]:
    query = db.query(AttendanceAbsence).filter(
        AttendanceAbsence.admission_id == admission_id
    )
    if not include_superseded:
        query = query.filter(AttendanceAbsence.superseded_at.is_(None))
    return query.order_by(
        AttendanceAbsence.absence_date.desc(), AttendanceAbsence.recorded_at.desc()
    ).all()


def student_detail(
    db: DBSession, actor: User, student_id: uuid.UUID
) -> dict[str, Any]:
    """Every episode of one student, with the current figure and full history."""
    student = _load_student(db, student_id)
    ensure_student_access(db, actor, student_id)
    today = _today()

    episodes = (
        db.query(AcademicAdmission, AcademicPeriod)
        .join(AcademicPeriod, AcademicPeriod.id == AcademicAdmission.admission_intake_id)
        .filter(AcademicAdmission.student_id == student_id)
        .order_by(AcademicAdmission.activated_at.desc(), AcademicAdmission.created_at.desc())
        .all()
    )
    if not episodes:
        raise AbsenceError(
            "ABSENCE_NO_ADMISSION",
            "This student has no admission episode.",
            status_code=404,
        )

    current = next(
        (pair for pair in episodes if pair[0].status in RECORDABLE_STATUSES), episodes[0]
    )
    base = _row(
        db, student=student, episode=current[0], period=current[1], today=today
    )

    all_absences = _absences_for(db, admission_id=current[0].id)
    names = _actor_names(db, all_absences)
    base["absences"] = [_absence_read(row, names) for row in all_absences]
    return base


def my_attendance(db: DBSession, actor: User) -> dict[str, Any]:
    """The student's own figures, for every episode they have ever had."""
    student = db.query(Student).filter(Student.user_id == actor.id).first()
    if student is None:
        raise AbsenceError(
            "STUDENT_NOT_FOUND", "No student record is linked to this account.", status_code=404
        )

    today = _today()
    episodes = (
        db.query(AcademicAdmission, AcademicPeriod)
        .join(AcademicPeriod, AcademicPeriod.id == AcademicAdmission.admission_intake_id)
        .filter(AcademicAdmission.student_id == student.id)
        .order_by(AcademicAdmission.activated_at.desc(), AcademicAdmission.created_at.desc())
        .all()
    )

    items = []
    for episode, period in episodes:
        commencement = _commencement_date(db, episode.id)
        calc = calculate(
            db, episode=episode, period=period, commencement=commencement, today=today
        )
        absences = _absences_for(db, admission_id=episode.id, include_superseded=False)
        names = _actor_names(db, absences)
        items.append(
            {
                "admission_id": episode.id,
                "admission_status": episode.status,
                "period_name": period.name,
                "commencement_date": commencement,
                "eligible": ineligible_reason(episode, commencement, today) is None,
                "eligible_days": calc["eligible_days"],
                "absence_count": calc["absence_count"],
                "excluded_absence_count": calc["excluded_absence_count"],
                "percentage": calc["percentage"],
                "absences": [_absence_read(row, names) for row in absences],
            }
        )

    return {
        "student_id": student.id,
        "student_number": student.student_id,
        "student_name": f"{student.first_name} {student.last_name}".strip(),
        "episodes": items,
    }


# ── Writes ──


def _validate_date(
    db: DBSession,
    *,
    episode: AcademicAdmission,
    period: AcademicPeriod,
    absence_date: date,
    commencement: date | None,
    today: date,
) -> None:
    """Every condition an absence date must satisfy, with its own code."""
    if absence_date > today:
        raise AbsenceError(
            "ABSENCE_IN_FUTURE",
            "An absence cannot be recorded for a future date.",
            status_code=422,
        )
    if commencement is None:
        raise AbsenceError(
            "ABSENCE_NO_COMMENCEMENT",
            "This episode has no approved commencement, so attendance has not started.",
            status_code=422,
        )
    if absence_date < commencement:
        raise AbsenceError(
            "ABSENCE_BEFORE_COMMENCEMENT",
            (
                "Attendance counts from the approved commencement "
                f"({commencement}); this date is earlier."
            ),
            status_code=422,
        )
    if not (period.start_date <= absence_date <= period.end_date):
        raise AbsenceError(
            "ABSENCE_OUTSIDE_PERIOD",
            (
                "The date falls outside the intake's instructional period "
                f"({period.start_date} to {period.end_date})."
            ),
            status_code=422,
        )

    resolved = calendar_svc.resolve_date(db, absence_date)
    if not resolved.is_working:
        raise AbsenceError(
            "ABSENCE_NON_WORKING_DAY",
            (
                "The university calendar does not treat this date as a working "
                f"day ({resolved.day_type.value}"
                + (f": {resolved.title}" if resolved.title else "")
                + ")."
            ),
            status_code=422,
        )


def record_absence(
    db: DBSession,
    data: AbsenceCreate,
    actor: User,
    *,
    student_id: uuid.UUID,
    request: Any | None = None,
) -> dict[str, Any]:
    """Record one absence, atomically with its audit entry."""
    student = _load_student(db, student_id)
    ensure_student_access(db, actor, student_id)
    episode = _load_episode(db, student_id=student_id, admission_id=data.admission_id)
    period = _period(db, episode)
    today = _today()

    if episode.status not in RECORDABLE_STATUSES:
        raise AbsenceError(
            "ABSENCE_ADMISSION_NOT_ACTIVE",
            (
                "Absences can only be recorded for an active admission "
                f"(this episode is {episode.status})."
            ),
        )

    reason = (data.reason or "").strip()
    if len(reason) < MIN_RECORD_REASON_LENGTH:
        raise AbsenceError(
            "ABSENCE_REASON_REQUIRED",
            "A reason is required to record an absence.",
            status_code=422,
        )

    commencement = _commencement_date(db, episode.id)
    _validate_date(
        db,
        episode=episode,
        period=period,
        absence_date=data.absence_date,
        commencement=commencement,
        today=today,
    )

    existing = (
        db.query(AttendanceAbsence)
        .filter(
            AttendanceAbsence.student_id == student_id,
            AttendanceAbsence.admission_id == episode.id,
            AttendanceAbsence.absence_date == data.absence_date,
            AttendanceAbsence.superseded_at.is_(None),
            AttendanceAbsence.cancelled_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        raise AbsenceError(
            "ABSENCE_ALREADY_RECORDED",
            "An absence is already recorded for this student on that date; correct it instead.",
        )

    absence = AttendanceAbsence(
        student_id=student_id,
        admission_id=episode.id,
        absence_date=data.absence_date,
        reason=reason,
        recorded_by_id=actor.id,
        recorded_at=_now(),
    )
    try:
        db.add(absence)
        db.flush()
        record_audit(
            db,
            action="attendance.absence.recorded",
            actor=actor,
            entity_type="attendance_absence",
            entity_id=absence.id,
            context={
                "student_id": str(student.id),
                "student_number": student.student_id,
                "admission_id": str(episode.id),
                "academic_period_id": str(period.id),
                "absence_date": data.absence_date.isoformat(),
                "reason": reason,
            },
            request=request,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AbsenceError(
            "ABSENCE_ALREADY_RECORDED",
            "An absence is already recorded for this student on that date; correct it instead.",
        ) from None
    except Exception:
        # The absence and its audit entry are one unit: if either half fails,
        # neither is kept.
        db.rollback()
        raise

    db.refresh(absence)
    calc = calculate(
        db,
        episode=episode,
        period=period,
        commencement=commencement,
        today=today,
    )
    return {
        "absence": _absence_read(absence, {actor.id: actor.full_name}),
        "calculation": calc,
    }


def correct_absence(
    db: DBSession,
    data: AbsenceCorrect,
    actor: User,
    *,
    student_id: uuid.UUID,
    absence_id: uuid.UUID,
    request: Any | None = None,
) -> dict[str, Any]:
    """Supersede an absence with a corrected date and reason.

    The replaced row is never edited: it keeps its date, reason, recorder and
    timestamp, so a later reader can see both what was claimed and what changed.
    """
    student = _load_student(db, student_id)
    ensure_student_access(db, actor, student_id)

    current = (
        db.query(AttendanceAbsence)
        .filter(
            AttendanceAbsence.id == absence_id,
            AttendanceAbsence.student_id == student_id,
            AttendanceAbsence.superseded_at.is_(None),
            AttendanceAbsence.cancelled_at.is_(None),
        )
        .first()
    )
    if current is None:
        raise AbsenceError(
            "ABSENCE_NOT_FOUND",
            "No current absence with that identifier for this student.",
            status_code=404,
        )

    episode = _load_episode(
        db, student_id=student_id, admission_id=current.admission_id
    )
    period = _period(db, episode)
    today = _today()

    reason = (data.reason or "").strip()
    if len(reason) < MIN_CORRECTION_REASON_LENGTH:
        raise AbsenceError(
            "ABSENCE_CORRECTION_REASON_REQUIRED",
            "Correcting an absence requires a reason of at least 10 characters.",
            status_code=422,
        )

    if data.absence_date == current.absence_date and reason == current.reason:
        raise AbsenceError(
            "ABSENCE_UNCHANGED",
            "The correction does not change the date or the reason.",
            status_code=422,
        )

    commencement = _commencement_date(db, episode.id)
    _validate_date(
        db,
        episode=episode,
        period=period,
        absence_date=data.absence_date,
        commencement=commencement,
        today=today,
    )

    clash = (
        db.query(AttendanceAbsence)
        .filter(
            AttendanceAbsence.student_id == student_id,
            AttendanceAbsence.admission_id == episode.id,
            AttendanceAbsence.absence_date == data.absence_date,
            AttendanceAbsence.id != current.id,
            AttendanceAbsence.superseded_at.is_(None),
            AttendanceAbsence.cancelled_at.is_(None),
        )
        .first()
    )
    if clash is not None:
        raise AbsenceError(
            "ABSENCE_ALREADY_RECORDED",
            "Another current absence already exists on the corrected date.",
        )

    now = _now()
    replacement = AttendanceAbsence(
        student_id=student_id,
        admission_id=episode.id,
        absence_date=data.absence_date,
        reason=reason,
        recorded_by_id=actor.id,
        recorded_at=now,
        supersedes_id=current.id,
    )
    previous_date = current.absence_date
    try:
        # Supersede first, in this transaction: the partial unique index then
        # admits the replacement without ever holding two current rows.
        current.superseded_at = now
        db.flush()

        db.add(replacement)
        db.flush()

        record_audit(
            db,
            action="attendance.absence.corrected",
            actor=actor,
            entity_type="attendance_absence",
            entity_id=replacement.id,
            context={
                "student_id": str(student.id),
                "student_number": student.student_id,
                "admission_id": str(episode.id),
                "academic_period_id": str(period.id),
                "absence_date": data.absence_date.isoformat(),
                "previous_absence_date": previous_date.isoformat(),
                "previous_reason": current.reason,
                "reason": reason,
                "supersedes_id": str(current.id),
            },
            request=request,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AbsenceError(
            "ABSENCE_ALREADY_RECORDED",
            "Another current absence already exists on the corrected date.",
        ) from None
    except Exception:
        db.rollback()
        raise

    db.refresh(replacement)
    calc = calculate(
        db,
        episode=episode,
        period=period,
        commencement=commencement,
        today=today,
    )
    return {
        "absence": _absence_read(replacement, {actor.id: actor.full_name}),
        "calculation": calc,
    }


def cancel_absence(
    db: DBSession,
    data: AbsenceCancel,
    actor: User,
    *,
    student_id: uuid.UUID,
    absence_id: uuid.UUID,
    request: Any | None = None,
) -> dict[str, Any]:
    """Cancel an absence that should not exist, without deleting it.

    The record stays in place and stays readable: its date, reason, recorder and
    timestamp are untouched, and the cancellation adds who cancelled it, when,
    and why. Removing it from the calculation is the whole effect, so the date
    becomes recordable again while the history keeps showing what was claimed and
    that it was withdrawn. A cancelled record cannot be corrected — reopening it
    would blur cancellation into correction — and it cannot be cancelled twice.
    """
    student = _load_student(db, student_id)
    ensure_student_access(db, actor, student_id)

    absence = (
        db.query(AttendanceAbsence)
        .filter(
            AttendanceAbsence.id == absence_id,
            AttendanceAbsence.student_id == student_id,
            AttendanceAbsence.superseded_at.is_(None),
            AttendanceAbsence.cancelled_at.is_(None),
        )
        .first()
    )
    if absence is None:
        raise AbsenceError(
            "ABSENCE_NOT_FOUND",
            "No active absence with that identifier for this student.",
            status_code=404,
        )

    reason = (data.reason or "").strip()
    if len(reason) < MIN_CANCELLATION_REASON_LENGTH:
        raise AbsenceError(
            "ABSENCE_CANCELLATION_REASON_REQUIRED",
            "Cancelling an absence requires a reason of at least 10 characters.",
            status_code=422,
        )

    clash = (
        db.query(AttendanceAbsence.id)
        .filter(
            AttendanceAbsence.student_id == student_id,
            AttendanceAbsence.admission_id == absence.admission_id,
            AttendanceAbsence.absence_date == absence.absence_date,
            AttendanceAbsence.id != absence.id,
            AttendanceAbsence.superseded_at.is_(None),
            AttendanceAbsence.cancelled_at.is_(None),
        )
        .first()
    )
    if clash is not None:
        raise AbsenceError(
            "ABSENCE_ALREADY_RECORDED",
            "Another active absence already exists on this date.",
        )

    episode = _load_episode(
        db, student_id=student_id, admission_id=absence.admission_id
    )
    period = _period(db, episode)
    today = _today()
    commencement = _commencement_date(db, episode.id)

    try:
        absence.cancelled_at = _now()
        absence.cancelled_by_id = actor.id
        absence.cancellation_reason = reason
        db.flush()

        record_audit(
            db,
            action="attendance.absence.cancelled",
            actor=actor,
            entity_type="attendance_absence",
            entity_id=absence.id,
            context={
                "student_id": str(student.id),
                "student_number": student.student_id,
                "admission_id": str(episode.id),
                "academic_period_id": str(period.id),
                "absence_date": absence.absence_date.isoformat(),
                "recorded_reason": absence.reason,
                "reason": reason,
            },
            request=request,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(absence)
    calc = calculate(
        db, episode=episode, period=period, commencement=commencement, today=today
    )
    return {
        "absence": _absence_read(absence, {actor.id: actor.full_name}),
        "calculation": calc,
    }
