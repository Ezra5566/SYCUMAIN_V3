"""Attendance commencement (Phase 2).

The commencement date is the first date a student's attendance is expected to
count. It belongs to one admission episode, and it is never inferred: the
institution approves it, and the approval is what creates the record.

Rules this module owns
----------------------
* Only an ``ACTIVE`` episode can receive a commencement. ``PENDING`` and
  ``ADMITTED`` episodes have not been activated, so a commencement for them
  would date attendance before the student existed as an active student.
* The suggested date is the first instructional working day on or after
  ``max(intake start, activation date)``, and is only a suggestion: weekends,
  holidays and closures are skipped by the same calendar that decides which
  days count. A request must echo the suggestion it reviewed; if the suggestion
  moved (an intake correction or a calendar declaration), it is refused.
* No commencement may be approved on a non-working day. An exceptional working
day declared in the calendar is a working day, so it is accepted.
* ``SCHEDULED`` confirms the suggestion, ``LATE_JOIN`` is strictly later, and
  ``MANUAL`` is any other approved date. All three carry a reason.
* A correction supersedes the current row instead of editing it, so the previous
  date, type, reason and approver remain in the record.

Nothing here creates attendance records, computes percentages or touches the
calendar. A commencement is a date, not a register.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - SQLAlchemy resolves UUID at runtime
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import record_audit
from app.models.academic import AcademicPeriod
from app.models.admission import AcademicAdmission, AcademicAdmissionStatus
from app.models.attendance import AttendanceCommencement, AttendanceCommencementType
from app.models.identity import Student, User
from app.services import calendar as calendar_svc

if TYPE_CHECKING:
    from app.schemas.commencement import CommencementApprove, CommencementCorrect

#: A reason is an institutional justification, not a label.
MIN_REASON_LENGTH = 10

#: A suggestion is a derived date, so it must terminate. A full year of closed
#: days is not a real institution; refusing beyond it keeps the loop bounded.
MAX_SUGGESTION_LOOKAHEAD = 366

#: Statuses that may receive a commencement. A completed or withdrawn episode
#: keeps the commencement it already has, but cannot be given a new one.
APPROVABLE_STATUSES: frozenset[str] = frozenset({AcademicAdmissionStatus.ACTIVE.value})


class CommencementError(ValueError):
    """A commencement refusal carrying a stable, localisable error code."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class Suggestion:
    """The computed suggestion, and which date produced it."""

    suggested_date: date
    intake_start_date: date
    activated_on: date | None
    basis: str  # INTAKE_START | ACTIVATION


def _now() -> datetime:
    return datetime.utcnow()


def _next_working_day(db: DBSession, day: date) -> date:
    """The first instructional day on or after ``day``, from the calendar.

    Derived, never invented: the weekday rule and the institution's declared
    exceptions decide it, exactly as they decide which days count later.
    """
    cursor = day
    for _ in range(MAX_SUGGESTION_LOOKAHEAD):
        if calendar_svc.resolve_date(db, cursor).is_working:
            return cursor
        cursor += timedelta(days=1)
    raise CommencementError(
        "COMMENCEMENT_NO_WORKING_DAY",
        "No instructional working day could be found within a year of "
        f"{day.isoformat()}; review the university calendar.",
    )


def suggest_commencement(
    db: DBSession, *, intake_start_date: date, activated_at: datetime | None
) -> Suggestion:
    """First working day on/after ``max(intake start, activation date)``.

    Still a suggestion, never a decision. The calendar adjustment matters: a
    commencement approved on a Sunday or a public holiday would count no
    instructional days, and the approver would be confirming a date that the
    rest of the module cannot treat as a start.
    """
    activated_on = activated_at.date() if activated_at is not None else None
    if activated_on is None or activated_on <= intake_start_date:
        base = intake_start_date
        basis = "INTAKE_START"
    else:
        base = activated_on
        basis = "ACTIVATION"
    return Suggestion(
        suggested_date=_next_working_day(db, base),
        intake_start_date=intake_start_date,
        activated_on=activated_on,
        basis=basis,
    )


# ── Loading ──


def _load_student(db: DBSession, student_id: uuid.UUID) -> Student:
    student = (
        db.query(Student).filter(Student.id == student_id).with_for_update().first()
    )
    if student is None:
        raise CommencementError(
            "STUDENT_NOT_FOUND", "Student not found.", status_code=404
        )
    return student


def _load_episode(
    db: DBSession, *, student_id: uuid.UUID, admission_id: uuid.UUID
) -> AcademicAdmission:
    """Load the episode only if it belongs to the student.

    A mismatched pair is reported as "not found" rather than "forbidden": the
    caller learns nothing about which admissions exist for another student.
    """
    episode = (
        db.query(AcademicAdmission)
        .filter(
            AcademicAdmission.id == admission_id,
            AcademicAdmission.student_id == student_id,
        )
        .first()
    )
    if episode is None:
        raise CommencementError(
            "COMMENCEMENT_ADMISSION_NOT_FOUND",
            "Admission episode not found for this student.",
            status_code=404,
        )
    return episode


def _load_intake(db: DBSession, episode: AcademicAdmission) -> AcademicPeriod:
    intake = (
        db.query(AcademicPeriod)
        .filter(AcademicPeriod.id == episode.admission_intake_id)
        .first()
    )
    if intake is None:
        raise CommencementError(
            "COMMENCEMENT_INTAKE_NOT_FOUND",
            "The admission's intake could not be found.",
        )
    return intake


def _current_commencement(
    db: DBSession, admission_id: uuid.UUID
) -> AttendanceCommencement | None:
    return (
        db.query(AttendanceCommencement)
        .filter(
            AttendanceCommencement.admission_id == admission_id,
            AttendanceCommencement.superseded_at.is_(None),
        )
        .first()
    )


def _history(
    db: DBSession, admission_id: uuid.UUID
) -> list[AttendanceCommencement]:
    return (
        db.query(AttendanceCommencement)
        .filter(AttendanceCommencement.admission_id == admission_id)
        .order_by(
            AttendanceCommencement.approved_at.desc(),
            AttendanceCommencement.created_at.desc(),
        )
        .all()
    )


def actor_names(
    db: DBSession, records: list[AttendanceCommencement]
) -> dict[uuid.UUID, str]:
    ids = {record.approved_by_id for record in records}
    if not ids:
        return {}
    rows = db.query(User.id, User.full_name).filter(User.id.in_(ids)).all()
    return {row[0]: row[1] for row in rows}


def record_to_read(
    record: AttendanceCommencement, names: dict[uuid.UUID, str]
) -> dict[str, Any]:
    return {
        "id": record.id,
        "admission_id": record.admission_id,
        "student_id": record.student_id,
        "commencement_date": record.commencement_date,
        "commencement_type": record.commencement_type,
        "reason": record.reason,
        "suggested_date": record.suggested_date,
        "supersedes_id": record.supersedes_id,
        "superseded_at": record.superseded_at,
        "approved_by_id": record.approved_by_id,
        "approved_by_name": names.get(record.approved_by_id),
        "approved_at": record.approved_at,
        "created_at": record.created_at,
    }


# ── Validation ──


def _reason(value: str | None) -> str:
    reason = (value or "").strip()
    if len(reason) < MIN_REASON_LENGTH:
        raise CommencementError(
            "COMMENCEMENT_REASON_REQUIRED",
            (
                "An explanation of at least "
                f"{MIN_REASON_LENGTH} characters is required."
            ),
            status_code=422,
        )
    return reason


def _validate(
    *,
    db: DBSession,
    data: CommencementApprove | CommencementCorrect,
    suggestion: Suggestion,
) -> tuple[date, AttendanceCommencementType, str]:
    """Validate one approval or correction; returns (date, type, reason)."""
    if data.confirmed_suggested_date != suggestion.suggested_date:
        raise CommencementError(
            "COMMENCEMENT_SUGGESTION_STALE",
            (
                "The suggested commencement date is now "
                f"{suggestion.suggested_date.isoformat()}. Review and confirm it "
                "again before approving."
            ),
        )

    day = data.commencement_date
    if day < suggestion.intake_start_date:
        raise CommencementError(
            "COMMENCEMENT_DATE_INVALID",
            "A commencement cannot start before its intake begins.",
            status_code=422,
        )
    if suggestion.activated_on is not None and day < suggestion.activated_on:
        raise CommencementError(
            "COMMENCEMENT_BEFORE_ACTIVATION",
            "A commencement cannot start before the admission was activated.",
            status_code=422,
        )

    resolved = calendar_svc.resolve_date(db, day)
    if not resolved.is_working:
        raise CommencementError(
            "COMMENCEMENT_NON_WORKING_DAY",
            (
                f"{day.isoformat()} is not an instructional working day "
                f"({resolved.day_type.value}"
                + (f": {resolved.title}" if resolved.title else "")
                + "). Choose a working day or declare an exceptional working day."
            ),
            status_code=422,
        )

    commencement_type = AttendanceCommencementType(data.commencement_type)
    if commencement_type is AttendanceCommencementType.SCHEDULED:
        if day != suggestion.suggested_date:
            raise CommencementError(
                "COMMENCEMENT_TYPE_MISMATCH",
                (
                    "A scheduled commencement must use the suggested date. "
                    "Record a late join or a manual commencement instead."
                ),
                status_code=422,
            )
    elif commencement_type is AttendanceCommencementType.LATE_JOIN:
        if day <= suggestion.suggested_date:
            raise CommencementError(
                "COMMENCEMENT_TYPE_MISMATCH",
                "A late join must start after the suggested commencement date.",
                status_code=422,
            )
    elif day == suggestion.suggested_date:
        raise CommencementError(
            "COMMENCEMENT_TYPE_MISMATCH",
            (
                "A manual commencement must differ from the suggested date; "
                "confirm the suggestion instead."
            ),
            status_code=422,
        )

    return day, commencement_type, _reason(data.reason)


# ── Reads ──


def _summary_for(
    db: DBSession, episode: AcademicAdmission, *, student: Student, intake: AcademicPeriod
) -> dict[str, Any]:
    suggestion = suggest_commencement(
        db, intake_start_date=intake.start_date, activated_at=episode.activated_at
    )
    records = _history(db, episode.id)
    names = actor_names(db, records)
    current = next(
        (record for record in records if record.superseded_at is None), None
    )

    return {
        "admission_id": episode.id,
        "student_id": student.id,
        "student_name": f"{student.first_name} {student.last_name}".strip(),
        "student_number": student.student_id,
        "admission_status": episode.status,
        "intake_id": intake.id,
        "intake_name": intake.name,
        "intake_start_date": intake.start_date,
        "activated_on": suggestion.activated_on,
        "suggested_date": suggestion.suggested_date,
        "suggestion_basis": suggestion.basis,
        "current": record_to_read(current, names) if current is not None else None,
        "history": [record_to_read(record, names) for record in records],
    }


def get_summary(
    db: DBSession, *, student_id: uuid.UUID, admission_id: uuid.UUID
) -> dict[str, Any]:
    student = db.query(Student).filter(Student.id == student_id).first()
    if student is None:
        raise CommencementError(
            "STUDENT_NOT_FOUND", "Student not found.", status_code=404
        )
    episode = _load_episode(db, student_id=student_id, admission_id=admission_id)
    intake = _load_intake(db, episode)
    return _summary_for(db, episode, student=student, intake=intake)


def list_commencements(
    db: DBSession,
    *,
    status: str = "MISSING",
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Active episodes with their commencement state.

    ``status`` is ``MISSING`` (no current commencement), ``RECORDED`` (one
    exists) or ``ALL``. Only ACTIVE episodes are listed: a PENDING or ADMITTED
    episode cannot be commenced, so offering it here would invite a refusal.
    """
    status_upper = (status or "MISSING").upper()
    if status_upper not in {"MISSING", "RECORDED", "ALL"}:
        raise CommencementError(
            "COMMENCEMENT_STATUS_INVALID",
            "Status must be MISSING, RECORDED or ALL.",
            status_code=422,
        )

    query = (
        db.query(AcademicAdmission, Student, AcademicPeriod)
        .join(Student, Student.id == AcademicAdmission.student_id)
        .join(AcademicPeriod, AcademicPeriod.id == AcademicAdmission.admission_intake_id)
        .filter(AcademicAdmission.status == AcademicAdmissionStatus.ACTIVE.value)
    )

    has_current = (
        db.query(AttendanceCommencement.id)
        .filter(
            AttendanceCommencement.admission_id == AcademicAdmission.id,
            AttendanceCommencement.superseded_at.is_(None),
        )
        .exists()
    )
    if status_upper == "RECORDED":
        query = query.filter(has_current)
    elif status_upper == "MISSING":
        query = query.filter(~has_current)

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Student.student_id.ilike(term),
                Student.first_name.ilike(term),
                Student.last_name.ilike(term),
            )
        )

    total = query.count()
    rows = (
        query.order_by(
            AcademicPeriod.start_date.desc(), Student.last_name, Student.first_name
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for episode, student, intake in rows:
        items.append(_summary_for(db, episode, student=student, intake=intake))

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ── Writes ──


def approve_commencement(
    db: DBSession,
    data: CommencementApprove,
    actor: User,
    *,
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    request: Any = None,
) -> AttendanceCommencement:
    student = _load_student(db, student_id)
    episode = _load_episode(db, student_id=student.id, admission_id=admission_id)

    if episode.status not in APPROVABLE_STATUSES:
        raise CommencementError(
            "COMMENCEMENT_ADMISSION_NOT_ACTIVE",
            (
                "Attendance can only commence for an active admission "
                f"(this episode is {episode.status})."
            ),
        )

    intake = _load_intake(db, episode)
    suggestion = suggest_commencement(
        db, intake_start_date=intake.start_date, activated_at=episode.activated_at
    )
    day, commencement_type, reason = _validate(
        db=db, data=data, suggestion=suggestion
    )

    if _current_commencement(db, episode.id) is not None:
        raise CommencementError(
            "COMMENCEMENT_ALREADY_EXISTS",
            "This admission episode already has a commencement; correct it instead.",
        )

    record = AttendanceCommencement(
        admission_id=episode.id,
        student_id=student.id,
        commencement_date=day,
        commencement_type=commencement_type.value,
        reason=reason,
        suggested_date=suggestion.suggested_date,
        approved_by_id=actor.id,
        approved_at=_now(),
    )

    try:
        db.add(record)
        db.flush()
        record_audit(
            db,
            action="academic.commencement.approved",
            actor=actor,
            entity_type="attendance_commencement",
            entity_id=record.id,
            context={
                "admission_id": str(episode.id),
                "student_id": str(student.id),
                "intake_id": str(intake.id),
                "commencement_date": day.isoformat(),
                "commencement_type": commencement_type.value,
                "suggested_date": suggestion.suggested_date.isoformat(),
                "suggestion_basis": suggestion.basis,
                "admission_status": episode.status,
                "reason": reason,
            },
            request=request,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _current_commencement(db, episode.id) is not None:
            raise CommencementError(
                "COMMENCEMENT_ALREADY_EXISTS",
                (
                    "This admission episode already has a commencement; "
                    "correct it instead."
                ),
            ) from exc
        raise
    except Exception:
        # The record and its audit entry share one transaction.
        db.rollback()
        raise

    db.refresh(record)
    return record


def correct_commencement(
    db: DBSession,
    data: CommencementCorrect,
    actor: User,
    *,
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    request: Any = None,
) -> AttendanceCommencement:
    student = _load_student(db, student_id)
    episode = _load_episode(db, student_id=student.id, admission_id=admission_id)
    intake = _load_intake(db, episode)

    current = _current_commencement(db, episode.id)
    if current is None:
        raise CommencementError(
            "COMMENCEMENT_NOT_FOUND",
            "This admission episode has no commencement to correct.",
            status_code=404,
        )

    suggestion = suggest_commencement(
        db, intake_start_date=intake.start_date, activated_at=episode.activated_at
    )
    day, commencement_type, reason = _validate(
        db=db, data=data, suggestion=suggestion
    )

    if (
        day == current.commencement_date
        and commencement_type.value == current.commencement_type
    ):
        raise CommencementError(
            "COMMENCEMENT_UNCHANGED",
            "The correction does not change the commencement date or type.",
            status_code=422,
        )

    previous = {
        "previous_commencement_id": str(current.id),
        "previous_commencement_date": current.commencement_date.isoformat(),
        "previous_commencement_type": current.commencement_type,
        "previous_reason": current.reason,
    }

    replacement = AttendanceCommencement(
        admission_id=episode.id,
        student_id=student.id,
        commencement_date=day,
        commencement_type=commencement_type.value,
        reason=reason,
        suggested_date=suggestion.suggested_date,
        supersedes_id=current.id,
        approved_by_id=actor.id,
        approved_at=_now(),
    )

    try:
        # Supersede first, then insert: the partial unique index allows one
        # current row per episode, and it is checked on insert.
        current.superseded_at = _now()
        db.flush()
        db.add(replacement)
        db.flush()
        record_audit(
            db,
            action="academic.commencement.corrected",
            actor=actor,
            entity_type="attendance_commencement",
            entity_id=replacement.id,
            context={
                "admission_id": str(episode.id),
                "student_id": str(student.id),
                "intake_id": str(intake.id),
                "commencement_date": day.isoformat(),
                "commencement_type": commencement_type.value,
                "suggested_date": suggestion.suggested_date.isoformat(),
                "reason": reason,
                **previous,
            },
            request=request,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(replacement)
    return replacement


__all__ = [
    "APPROVABLE_STATUSES",
    "MIN_REASON_LENGTH",
    "CommencementError",
    "Suggestion",
    "actor_names",
    "approve_commencement",
    "correct_commencement",
    "get_summary",
    "list_commencements",
    "record_to_read",
    "suggest_commencement",
]
