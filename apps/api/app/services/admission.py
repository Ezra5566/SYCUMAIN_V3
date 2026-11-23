"""Admission episode lifecycle (Phase 1).

The service owns the rules that cannot be expressed as database constraints:

* while one episode is ``ACTIVE``, another episode may only be prepared as
  ``PENDING`` — never ``ADMITTED`` or ``ACTIVE``;
* a future admission may not be recorded in an intake that starts before the
  active episode's intake;
* at most one live episode exists per ``(student, intake)``;
* only an ``ACTIVE`` episode drives the student's academic projection;
* the original-admission pointer is set once, in the same transaction as the
  student's first episode.

Every write locks the student row before reading episodes. That serialises
create/activate requests for one student; the partial unique indexes added in
Phase 0 remain the final arbiter if a non-service writer races us.

The status-history row is written by the database trigger, not here. Keeping a
single writer avoids duplicate rows in production, where the trigger is
installed by the Phase 0 migration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import record_audit
from app.config.settings import get_settings
from app.models.academic import AcademicPeriod, Program, ProgramOffering
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionStatus,
    AcademicPlacement,
    AdmissionConfirmationState,
    AdmissionRecordOrigin,
    AdmissionVerificationStatus,
)
from app.models.identity import Student, User
from app.schemas.admission import (
    AdmissionCreate,
    AdmissionRead,
    AdmissionStatusCorrection,
    AdmissionTransition,
)

LIVE_STATUSES = (
    AcademicAdmissionStatus.PENDING,
    AcademicAdmissionStatus.ADMITTED,
    AcademicAdmissionStatus.ACTIVE,
)
TERMINAL_STATUSES = (
    AcademicAdmissionStatus.COMPLETED,
    AcademicAdmissionStatus.WITHDRAWN,
    AcademicAdmissionStatus.CANCELLED,
)
ALLOWED_TRANSITIONS: dict[AcademicAdmissionStatus, set[AcademicAdmissionStatus]] = {
    AcademicAdmissionStatus.PENDING: {
        AcademicAdmissionStatus.ADMITTED,
        AcademicAdmissionStatus.ACTIVE,
        AcademicAdmissionStatus.CANCELLED,
    },
    AcademicAdmissionStatus.ADMITTED: {
        AcademicAdmissionStatus.ACTIVE,
        AcademicAdmissionStatus.CANCELLED,
    },
    AcademicAdmissionStatus.ACTIVE: {
        AcademicAdmissionStatus.COMPLETED,
        AcademicAdmissionStatus.WITHDRAWN,
    },
}


def _now() -> datetime:
    return datetime.now(UTC)


def _close_open_placements(
    db: DBSession,
    *,
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    ended_at: datetime,
) -> list[AcademicPlacement]:
    """Close the open placement owned by one ending admission episode.

    The student row is already locked by the caller. Locking the placement
    rows here serialises this closure with placement supersession and keeps a
    concurrent writer from leaving an open row behind. The admission and
    offering references are deliberately left untouched; only ``ended_at`` is
    set so the row remains available in placement history.
    """
    placements = (
        db.query(AcademicPlacement)
        .filter(
            AcademicPlacement.student_id == student_id,
            AcademicPlacement.admission_id == admission_id,
            AcademicPlacement.ended_at.is_(None),
        )
        .with_for_update()
        .all()
    )
    for placement in placements:
        placement.ended_at = ended_at
    return placements


def _lock_student(db: DBSession, student_id: uuid.UUID) -> Student:
    student = db.query(Student).filter(Student.id == student_id).with_for_update().first()
    if student is None:
        raise ValueError("STUDENT_NOT_FOUND")
    return student


def _active_episode(
    db: DBSession, student_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None
) -> AcademicAdmission | None:
    query = db.query(AcademicAdmission).filter(
        AcademicAdmission.student_id == student_id,
        AcademicAdmission.status == AcademicAdmissionStatus.ACTIVE,
    )
    if exclude_id is not None:
        query = query.filter(AcademicAdmission.id != exclude_id)
    return query.with_for_update().first()


def _live_episode_for_intake(
    db: DBSession, student_id: uuid.UUID, intake_id: uuid.UUID
) -> AcademicAdmission | None:
    return (
        db.query(AcademicAdmission)
        .filter(
            AcademicAdmission.student_id == student_id,
            AcademicAdmission.admission_intake_id == intake_id,
            AcademicAdmission.status.in_([status.value for status in LIVE_STATUSES]),
        )
        .first()
    )


def _load_intake(db: DBSession, intake_id: uuid.UUID) -> AcademicPeriod:
    intake = db.get(AcademicPeriod, intake_id)
    if intake is None:
        raise ValueError("ADMISSION_INTAKE_NOT_FOUND")
    if intake.start_date is None or intake.end_date is None:
        raise ValueError("INTAKE_DATES_REQUIRED")
    if intake.end_date < intake.start_date:
        raise ValueError("INTAKE_DATES_INVALID")
    return intake


def _load_offering(
    db: DBSession, intake: AcademicPeriod, offering_id: uuid.UUID
) -> ProgramOffering:
    offering = db.get(ProgramOffering, offering_id)
    if offering is None:
        raise ValueError("PROGRAM_OFFERING_NOT_FOUND")
    if offering.academic_period_id != intake.id:
        raise ValueError("ADMISSION_OFFERING_INTAKE_MISMATCH")
    if offering.program_id is None:
        raise ValueError("PROGRAM_OFFERING_NOT_MAPPED")
    return offering


def _constraint_name(exc: IntegrityError) -> str:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) or ""


def _flush_or_conflict(db: DBSession, *, activating: bool = False) -> None:
    """Flush, translating index races into stable lifecycle error codes."""
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if "uq_academic_admission_student_intake_live" in constraint:
            raise ValueError("ADMISSION_INTAKE_ALREADY_LIVE") from exc
        if "uq_academic_admission_one_active" in constraint:
            raise ValueError("ADMISSION_ALREADY_ACTIVE") from exc
        if activating:
            raise ValueError("ADMISSION_ALREADY_ACTIVE") from exc
        raise ValueError("ADMISSION_CONFLICT") from exc


def create_admission(
    db: DBSession,
    student: Student,
    data: AdmissionCreate,
    actor: User,
) -> AcademicAdmission:
    """Record an episode after applying the §2.2 creation guards.

    Raises:
        ValueError: with a stable machine-readable code for the router.
    """
    locked = _lock_student(db, student.id)
    intake = _load_intake(db, data.admission_intake_id)
    offering = _load_offering(db, intake, data.program_offering_id)

    existing_live = _live_episode_for_intake(db, locked.id, intake.id)
    if existing_live is not None:
        # A different programme in the same intake is a programme change on
        # the existing episode, not a second admission. Saying so explicitly
        # keeps the two institutional events separate in the API contract.
        if (
            existing_live.admitted_program_id is not None
            and offering.program_id is not None
            and existing_live.admitted_program_id != offering.program_id
        ):
            raise ValueError("PROGRAM_CHANGE_NOT_NEW_ADMISSION")
        raise ValueError("ADMISSION_INTAKE_ALREADY_LIVE")

    active = _active_episode(db, locked.id)
    requested = AcademicAdmissionStatus(data.initial_status)
    if active is not None:
        if requested is not AcademicAdmissionStatus.PENDING:
            raise ValueError("ADMISSION_MUST_BE_PENDING")
        active_intake = db.get(AcademicPeriod, active.admission_intake_id)
        if active_intake is not None and intake.start_date < active_intake.start_date:
            raise ValueError("ADMISSION_INTAKE_PRECEDES_ACTIVE_EPISODE")

    now = _now()
    episode = AcademicAdmission(
        id=uuid.uuid4(),
        student_id=locked.id,
        admission_intake_id=intake.id,
        admitted_program_id=offering.program_id,
        admitted_program_offering_id=offering.id,
        current_program_id=offering.program_id,
        status=requested.value,
        initial_status=requested.value,
        record_origin=AdmissionRecordOrigin.NEW_ADMISSION.value,
        verification_status=AdmissionVerificationStatus.VERIFIED.value,
        verified_at=now,
        activated_at=(now if requested is AcademicAdmissionStatus.ACTIVE else None),
        created_by_id=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(episode)
    _flush_or_conflict(db)

    # A new admission is authoritative; the first one is also the student's
    # immigration cohort basis. The database permits setting this from NULL
    # once, and forbids replacing it outside the correction workflow.
    if locked.original_admission_id is None:
        locked.original_admission_id = episode.id

    _flush_or_conflict(db)
    return episode


def transition_admission(
    db: DBSession,
    student: Student,
    admission_id: uuid.UUID,
    data: AdmissionTransition,
    actor: User,
) -> AcademicAdmission:
    """Apply one lifecycle transition, or raise a stable refusal code."""
    locked = _lock_student(db, student.id)
    admission = (
        db.query(AcademicAdmission)
        .filter(
            AcademicAdmission.id == admission_id,
            AcademicAdmission.student_id == locked.id,
        )
        .with_for_update()
        .first()
    )
    if admission is None:
        raise ValueError("ADMISSION_NOT_FOUND")

    current = AcademicAdmissionStatus(admission.status)
    target = AcademicAdmissionStatus(data.status)

    if current in TERMINAL_STATUSES:
        raise ValueError("ADMISSION_TERMINAL")
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError("ADMISSION_TRANSITION_NOT_ALLOWED")

    reason = (data.reason or "").strip()
    if (
        target
        in (
            AcademicAdmissionStatus.WITHDRAWN,
            AcademicAdmissionStatus.CANCELLED,
        )
        and not reason
    ):
        raise ValueError("ADMISSION_REASON_REQUIRED")

    if (
        target in (AcademicAdmissionStatus.ADMITTED, AcademicAdmissionStatus.ACTIVE)
        and _active_episode(db, locked.id, exclude_id=admission.id) is not None
    ):
        code = (
            "ADMISSION_ALREADY_ACTIVE"
            if target is AcademicAdmissionStatus.ACTIVE
            else "ADMISSION_MUST_BE_PENDING"
        )
        raise ValueError(code)

    now = _now()
    admission.status = target.value
    if target is AcademicAdmissionStatus.ACTIVE and admission.activated_at is None:
        admission.activated_at = now
    if target in TERMINAL_STATUSES:
        admission.ended_at = now
        admission.end_reason = reason or None

    if current is AcademicAdmissionStatus.ACTIVE and target in (
        AcademicAdmissionStatus.COMPLETED,
        AcademicAdmissionStatus.WITHDRAWN,
    ):
        _close_open_placements(
            db,
            student_id=locked.id,
            admission_id=admission.id,
            ended_at=now,
        )

    _flush_or_conflict(db, activating=target is AcademicAdmissionStatus.ACTIVE)
    return admission


def correct_admission_status(
    db: DBSession,
    student: Student,
    admission_id: uuid.UUID,
    data: AdmissionStatusCorrection,
    actor: User,
    request: Any | None = None,
    *,
    require_terminal: bool = False,
    change_request_id: uuid.UUID | None = None,
) -> AcademicAdmission:
    """Correct a recorded status while preserving every prior transition.

    The database trigger is the single writer of the append-only history row.
    This function opens the trigger's correction gate for this transaction and
    supplies the mandatory reason and actor, then applies the same lifecycle
    guards as an ordinary transition. It never deletes or rewrites a history
    row and never changes the admission's intake or historical programme.
    """
    locked = _lock_student(db, student.id)
    admission = (
        db.query(AcademicAdmission)
        .filter(
            AcademicAdmission.id == admission_id,
            AcademicAdmission.student_id == locked.id,
        )
        .with_for_update()
        .first()
    )
    if admission is None:
        raise ValueError("ADMISSION_NOT_FOUND")

    current = AcademicAdmissionStatus(admission.status)
    target = AcademicAdmissionStatus(data.target_status)
    if require_terminal and current not in TERMINAL_STATUSES:
        raise ValueError("ADMISSION_CORRECTION_NOT_TERMINAL")
    if target is current:
        raise ValueError("ADMISSION_CORRECTION_UNCHANGED")
    if current not in TERMINAL_STATUSES and target not in ALLOWED_TRANSITIONS.get(
        current, set()
    ):
        raise ValueError("ADMISSION_TRANSITION_NOT_ALLOWED")

    reason = (data.reason or "").strip()
    if not reason:
        raise ValueError("ADMISSION_CORRECTION_REASON_REQUIRED")

    if target in (AcademicAdmissionStatus.ADMITTED, AcademicAdmissionStatus.ACTIVE):
        other_active = _active_episode(db, locked.id, exclude_id=admission.id)
        if other_active is not None:
            code = (
                "ADMISSION_ALREADY_ACTIVE"
                if target is AcademicAdmissionStatus.ACTIVE
                else "ADMISSION_MUST_BE_PENDING"
            )
            raise ValueError(code)

    previous_status = current.value
    previous_ended_at = admission.ended_at
    previous_end_reason = admission.end_reason
    now = _now()

    # Transaction-local values consumed by trg_admission_transition_guard.
    db.execute(
        text("SELECT set_config('scu.actor_id', :actor_id, true)"),
        {"actor_id": str(actor.id)},
    )
    db.execute(
        text("SELECT set_config('scu.correction_reason', :reason, true)"),
        {"reason": reason},
    )
    db.execute(text("SELECT set_config('scu.admission_correction', 'on', true)"))

    admission.status = target.value
    admission.updated_at = now
    if target in TERMINAL_STATUSES:
        admission.ended_at = now
        admission.end_reason = (
            reason
            if target
            in (AcademicAdmissionStatus.WITHDRAWN, AcademicAdmissionStatus.CANCELLED)
            else None
        )
    else:
        admission.ended_at = None
        admission.end_reason = None

    if target is AcademicAdmissionStatus.ACTIVE and admission.activated_at is None:
        admission.activated_at = now

    if current is AcademicAdmissionStatus.ACTIVE and target in (
        AcademicAdmissionStatus.COMPLETED,
        AcademicAdmissionStatus.WITHDRAWN,
    ):
        _close_open_placements(
            db,
            student_id=locked.id,
            admission_id=admission.id,
            ended_at=now,
        )

    _flush_or_conflict(db, activating=target is AcademicAdmissionStatus.ACTIVE)

    try:
        record_audit(
            db,
            action="academic.admission.status_corrected",
            actor=actor,
            entity_type="academic_admission",
            entity_id=admission.id,
            context={
                "student_id": str(locked.id),
                "admission_id": str(admission.id),
                "previous_status": previous_status,
                "new_status": target.value,
                "previous_ended_at": (
                    previous_ended_at.isoformat() if previous_ended_at else None
                ),
                "previous_end_reason": previous_end_reason,
                "new_ended_at": (
                    admission.ended_at.isoformat() if admission.ended_at else None
                ),
                "reason": reason,
                "change_request_id": (
                    str(change_request_id) if change_request_id else None
                ),
            },
            request=request,
        )
    except Exception:
        db.rollback()
        raise
    return admission


def list_admissions(db: DBSession, student_id: uuid.UUID) -> list[AcademicAdmission]:
    return (
        db.query(AcademicAdmission)
        .filter(AcademicAdmission.student_id == student_id)
        .order_by(
            AcademicAdmission.created_at.desc(),
            AcademicAdmission.id.desc(),
        )
        .all()
    )


def admission_to_read(db: DBSession, admission: AcademicAdmission) -> AdmissionRead:
    intake = db.get(AcademicPeriod, admission.admission_intake_id)
    offering = db.get(ProgramOffering, admission.admitted_program_offering_id)
    admitted_program = (
        db.get(Program, admission.admitted_program_id)
        if admission.admitted_program_id is not None
        else None
    )
    current_program = (
        db.get(Program, admission.current_program_id)
        if admission.current_program_id is not None
        else None
    )
    return AdmissionRead(
        id=admission.id,
        student_id=admission.student_id,
        status=AcademicAdmissionStatus(admission.status),
        initial_status=AcademicAdmissionStatus(admission.initial_status),
        record_origin=AdmissionRecordOrigin(admission.record_origin),
        verification_status=AdmissionVerificationStatus(admission.verification_status),
        admission_intake_id=admission.admission_intake_id,
        admission_intake_code=intake.code if intake else None,
        admission_intake_name=intake.name if intake else None,
        admission_intake_start_date=intake.start_date if intake else None,
        admission_intake_end_date=intake.end_date if intake else None,
        admitted_program_id=admission.admitted_program_id,
        admitted_program_name=admitted_program.name if admitted_program else None,
        admitted_program_offering_id=admission.admitted_program_offering_id,
        admitted_program_offering_name=offering.name if offering else None,
        current_program_id=admission.current_program_id,
        current_program_name=current_program.name if current_program else None,
        management_confirmation_state=AdmissionConfirmationState(
            admission.management_confirmation_state
        ),
        management_confirmed_by_id=admission.management_confirmed_by_id,
        management_confirmed_at=admission.management_confirmed_at,
        management_revoked_at=admission.management_revoked_at,
        admin_confirmation_state=AdmissionConfirmationState(
            admission.admin_confirmation_state
        ),
        admin_confirmed_by_id=admission.admin_confirmed_by_id,
        admin_confirmed_at=admission.admin_confirmed_at,
        admin_revoked_at=admission.admin_revoked_at,
        activated_at=admission.activated_at,
        ended_at=admission.ended_at,
        end_reason=admission.end_reason,
        verified_at=admission.verified_at,
        corrections_enabled=get_settings().ADMISSION_CORRECTIONS_ENABLED,
        created_at=admission.created_at,
        updated_at=admission.updated_at,
    )


__all__ = [
    "admission_to_read",
    "correct_admission_status",
    "create_admission",
    "list_admissions",
    "transition_admission",
]
