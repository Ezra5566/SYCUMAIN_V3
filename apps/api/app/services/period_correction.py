"""Controlled correction of an intake's official dates (Phase 5).

The Phase 0 schema already contains the correction table and the placement
reflagging trigger. This module owns the service-level rules that a database
constraint cannot express: ordering, academic-record fit, completed-intake
authority, placement authorization and the all-or-nothing transaction.

Nothing here changes an admission intake, a placement intake, a Student
projection or an immigration cohort pointer. A correction changes the dates of
the term only and records why.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - SQLAlchemy resolves UUID at runtime
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Date, cast, or_
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.models.academic import (
    AcademicPeriod,
    Assessment,
    AttendanceRecord,
    ClassSection,
    Enrollment,
    ProgramOffering,
    TimetableEntry,
)
from app.models.admission import (
    AcademicAdmission,
    AcademicPeriodDateCorrection,
    AcademicPlacement,
)

if TYPE_CHECKING:
    from app.schemas.academic import AcademicPeriodDateCorrectionCreate

_MIN_REASON_LENGTH = 20


class PeriodCorrectionError(ValueError):
    """A correction refusal carrying a stable, localisable error code."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class PeriodCorrectionResult:
    correction: AcademicPeriodDateCorrection
    period: AcademicPeriod
    placements_reflagged: int
    admissions_rechecked: int


def periods_with_dependants(
    db: DBSession, period_ids: list[uuid.UUID] | set[uuid.UUID]
) -> set[uuid.UUID]:
    """Return the ids whose dates must go through the correction workflow.

    The set mirrors the documented dependants: an offering, admission,
    placement, class section or timetable entry. The queries are set-based so
    listing a page of intakes does not run one query per row.
    """

    ids = list(period_ids)
    if not ids:
        return set()

    found: set[uuid.UUID] = set()
    found.update(
        row[0]
        for row in db.query(ProgramOffering.academic_period_id)
        .filter(ProgramOffering.academic_period_id.in_(ids))
        .distinct()
        .all()
    )
    found.update(
        row[0]
        for row in db.query(AcademicAdmission.admission_intake_id)
        .filter(AcademicAdmission.admission_intake_id.in_(ids))
        .distinct()
        .all()
    )
    found.update(
        row[0]
        for row in db.query(AcademicPlacement.academic_period_id)
        .filter(AcademicPlacement.academic_period_id.in_(ids))
        .distinct()
        .all()
    )
    found.update(
        row[0]
        for row in db.query(ClassSection.academic_period_id)
        .filter(ClassSection.academic_period_id.in_(ids))
        .distinct()
        .all()
    )
    found.update(
        row[0]
        for row in db.query(ClassSection.academic_period_id)
        .join(TimetableEntry, TimetableEntry.class_section_id == ClassSection.id)
        .filter(ClassSection.academic_period_id.in_(ids))
        .distinct()
        .all()
    )
    return found


def period_has_dependants(db: DBSession, period_id: uuid.UUID) -> bool:
    return bool(periods_with_dependants(db, [period_id]))


def _clear_reason(data: AcademicPeriodDateCorrectionCreate) -> str:
    reason = (data.reason or "").strip()
    if len(reason) < _MIN_REASON_LENGTH:
        raise PeriodCorrectionError(
            "PERIOD_CORRECTION_REASON_REQUIRED",
            f"A reason of at least {_MIN_REASON_LENGTH} characters is required.",
            status_code=422,
        )
    return reason


def _dates(
    data: AcademicPeriodDateCorrectionCreate,
) -> tuple[date, date]:
    if data.new_start_date is None or data.new_end_date is None:
        raise PeriodCorrectionError(
            "INTAKE_DATES_REQUIRED",
            "Both the corrected start and end date are required.",
            status_code=422,
        )
    if data.new_end_date < data.new_start_date:
        raise PeriodCorrectionError(
            "INTAKE_DATES_INVALID",
            "The corrected end date cannot precede the corrected start date.",
            status_code=422,
        )
    return data.new_start_date, data.new_end_date


def _assert_order_preserved(
    db: DBSession,
    period: AcademicPeriod,
    new_start: date,
) -> None:
    """Keep the global start-date sequence intact.

    The target may move within its existing slot but not past either neighbour.
    Locking every period row serializes corrections, so two administrators
    cannot each validate against a sequence the other is about to change.
    """

    ordered = (
        db.query(AcademicPeriod)
        .order_by(AcademicPeriod.start_date, AcademicPeriod.id)
        .with_for_update()
        .all()
    )
    index = next((i for i, row in enumerate(ordered) if row.id == period.id), None)
    if index is None:  # pragma: no cover - the row was loaded above
        raise PeriodCorrectionError(
            "ACADEMIC_PERIOD_NOT_FOUND",
            "Academic period not found.",
            status_code=404,
        )

    previous = ordered[index - 1] if index > 0 else None
    following = ordered[index + 1] if index + 1 < len(ordered) else None

    if previous is not None and new_start < previous.start_date:
        raise PeriodCorrectionError(
            "PERIOD_CORRECTION_REORDERS_ADMISSION_HISTORY",
            "That correction would move the intake past an earlier intake.",
        )
    if following is not None and new_start > following.start_date:
        raise PeriodCorrectionError(
            "PERIOD_CORRECTION_REORDERS_ADMISSION_HISTORY",
            "That correction would move the intake past a later intake.",
        )



def _assert_admission_history_not_reordered(
    db: DBSession,
    period: AcademicPeriod,
    new_start: date,
) -> None:
    """Keep each student's verified admission sequence in intake order.

    Global period ordering catches most crossings, but two intakes can share a
    start date. This per-student check makes the admission-history rule
    explicit and refuses moving a target intake before a verified sibling
    intake recorded at or before its current start date.
    """

    for admission in db.query(AcademicAdmission).filter(
        AcademicAdmission.admission_intake_id == period.id
    ):
        preceding = (
            db.query(AcademicPeriod)
            .join(
                AcademicAdmission,
                AcademicAdmission.admission_intake_id == AcademicPeriod.id,
            )
            .filter(
                AcademicAdmission.student_id == admission.student_id,
                AcademicAdmission.id != admission.id,
                AcademicAdmission.verification_status == "VERIFIED",
                AcademicPeriod.id != period.id,
                AcademicPeriod.start_date <= period.start_date,
            )
            .order_by(AcademicPeriod.start_date.desc(), AcademicPeriod.id.desc())
            .first()
        )
        if preceding is not None and new_start < preceding.start_date:
            raise PeriodCorrectionError(
                "PERIOD_CORRECTION_REORDERS_ADMISSION_HISTORY",
                "That correction would move the intake before a verified admission intake.",
            )


def _assert_academic_records_fit(
    db: DBSession,
    period: AcademicPeriod,
    start: date,
    end: date,
) -> None:
    """Refuse a correction that would strand an academic record outside term.

    Class sections and timetable entries carry no independent date: their term
    is the period row. A live recurring slot is checked against the corrected
    range so a one-day or otherwise shortened term cannot silently leave every
    occurrence outside it. Enrolment timestamps, attendance sessions and
    assessment due dates are checked directly. Nothing is moved.
    """

    enrollment_conflict = (
        db.query(Enrollment.id)
        .join(ClassSection, ClassSection.id == Enrollment.class_section_id)
        .filter(
            ClassSection.academic_period_id == period.id,
            or_(
                cast(Enrollment.enrolled_at, Date) < start,
                cast(Enrollment.enrolled_at, Date) > end,
                cast(Enrollment.dropped_at, Date) < start,
                cast(Enrollment.dropped_at, Date) > end,
            ),
        )
        .first()
    )
    if enrollment_conflict is not None:
        raise PeriodCorrectionError(
            "PERIOD_DATES_CONFLICT_WITH_ACADEMIC_RECORD",
            "An enrolment date would fall outside the corrected intake.",
        )

    attendance_conflict = (
        db.query(AttendanceRecord.id)
        .join(ClassSection, ClassSection.id == AttendanceRecord.class_section_id)
        .filter(
            ClassSection.academic_period_id == period.id,
            or_(
                AttendanceRecord.session_date < start,
                AttendanceRecord.session_date > end,
            ),
        )
        .first()
    )
    if attendance_conflict is not None:
        raise PeriodCorrectionError(
            "PERIOD_DATES_CONFLICT_WITH_ACADEMIC_RECORD",
            "An attendance session would fall outside the corrected intake.",
        )

    assessment_conflict = (
        db.query(Assessment.id)
        .join(ClassSection, ClassSection.id == Assessment.class_section_id)
        .filter(
            ClassSection.academic_period_id == period.id,
            Assessment.due_date.is_not(None),
            or_(Assessment.due_date < start, Assessment.due_date > end),
        )
        .first()
    )
    if assessment_conflict is not None:
        raise PeriodCorrectionError(
            "PERIOD_DATES_CONFLICT_WITH_ACADEMIC_RECORD",
            "An assessment due date would fall outside the corrected intake.",
        )

    timetable_entries = (
        db.query(TimetableEntry)
        .join(ClassSection, ClassSection.id == TimetableEntry.class_section_id)
        .filter(
            ClassSection.academic_period_id == period.id,
            TimetableEntry.is_deleted.is_(False),
        )
        .all()
    )
    for entry in timetable_entries:
        first_occurrence = start + timedelta(
            days=(entry.day_of_week - start.weekday()) % 7
        )
        if first_occurrence > end:
            raise PeriodCorrectionError(
                "PERIOD_DATES_CONFLICT_WITH_ACADEMIC_RECORD",
                "A scheduled class would have no occurrence inside the corrected intake.",
            )


def _admissions_in_period(
    db: DBSession, period: AcademicPeriod
) -> list[AcademicAdmission]:
    return (
        db.query(AcademicAdmission)
        .filter(AcademicAdmission.admission_intake_id == period.id)
        .with_for_update()
        .all()
    )


def _current_placements(
    db: DBSession, period: AcademicPeriod
) -> list[AcademicPlacement]:
    return (
        db.query(AcademicPlacement)
        .filter(
            AcademicPlacement.academic_period_id == period.id,
            AcademicPlacement.ended_at.is_(None),
        )
        .with_for_update()
        .all()
    )


def correct_period_dates(
    db: DBSession,
    period_id: uuid.UUID,
    data: AcademicPeriodDateCorrectionCreate,
    *,
    actor: object,
) -> PeriodCorrectionResult:
    """Validate, apply and stage one audited correction.

    The caller records the audit entry and commits. Any refusal leaves the
    period dates, placement flags and correction table untouched.
    """

    reason = _clear_reason(data)
    new_start, new_end = _dates(data)

    # Lock the target first. `_assert_order_preserved` locks the full ordered
    # set, which serializes concurrent corrections.
    period = (
        db.query(AcademicPeriod)
        .filter(AcademicPeriod.id == period_id)
        .with_for_update()
        .first()
    )
    if period is None:
        raise PeriodCorrectionError(
            "ACADEMIC_PERIOD_NOT_FOUND",
            "Academic period not found.",
            status_code=404,
        )

    if period.status == "COMPLETED":
        roles = {getattr(role, "name", "") for role in getattr(actor, "roles", [])}
        if "ADMIN" not in roles:
            raise PeriodCorrectionError(
                "PERIOD_CORRECTION_COMPLETED_REQUIRES_ADMIN",
                "Only an administrator may correct a completed intake.",
                status_code=403,
            )

    if new_start == period.start_date and new_end == period.end_date:
        raise PeriodCorrectionError(
            "PERIOD_DATES_UNCHANGED",
            "The corrected dates are the same as the current dates.",
        )

    _assert_admission_history_not_reordered(db, period, new_start)
    _assert_order_preserved(db, period, new_start)
    _assert_academic_records_fit(db, period, new_start, new_end)

    admissions = _admissions_in_period(db, period)
    placements = _current_placements(db, period)

    placement_flags: list[tuple[AcademicPlacement, bool]] = []
    for placement in placements:
        admission = db.query(AcademicAdmission).filter(
            AcademicAdmission.id == placement.admission_id
        ).first()
        if admission is None:  # pragma: no cover - FK guarantees this
            continue
        admission_intake = db.query(AcademicPeriod).filter(
            AcademicPeriod.id == admission.admission_intake_id
        ).first()
        if admission_intake is None:  # pragma: no cover - FK guarantees this
            continue

        # A placement in its own admission intake can never be earlier than
        # that intake, including while the same row is being corrected.
        would_be_earlier = (
            placement.academic_period_id != admission.admission_intake_id
            and new_start < admission_intake.start_date
        )
        authorized = (
            placement.authorized_by_id is not None
            and placement.authorization_reason is not None
            and placement.authorization_reason.strip() != ""
        )
        if would_be_earlier and not authorized:
            raise PeriodCorrectionError(
                "PERIOD_CORRECTION_REQUIRES_PLACEMENT_AUTHORIZATION",
                "That correction would make a placement an unauthorized earlier-intake placement.",
            )
        placement_flags.append((placement, would_be_earlier))

    previous_start = period.start_date
    previous_end = period.end_date
    period.start_date = new_start
    period.end_date = new_end
    db.flush()  # fires trg_period_dates_recheck in migrated databases

    reflagged = 0
    for placement, would_be_earlier in placement_flags:
        if placement.is_earlier_intake_placement != would_be_earlier:
            reflagged += 1
        # The trigger has already done this in a migrated database. Doing it
        # here too keeps the service correct in test databases built from the
        # ORM metadata, where migration-created triggers do not exist.
        placement.is_earlier_intake_placement = would_be_earlier
        placement.updated_at = datetime.now(UTC)

    correction = AcademicPeriodDateCorrection(
        academic_period_id=period.id,
        previous_start_date=previous_start,
        previous_end_date=previous_end,
        new_start_date=new_start,
        new_end_date=new_end,
        reason=reason,
        actor_id=getattr(actor, "id", None),
        placements_reflagged=reflagged,
        admissions_rechecked=len(admissions),
    )
    db.add(correction)
    db.flush()

    return PeriodCorrectionResult(
        correction=correction,
        period=period,
        placements_reflagged=reflagged,
        admissions_rechecked=len(admissions),
    )
