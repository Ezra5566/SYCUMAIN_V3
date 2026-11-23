"""Migration verification and original-admission correction (Phase 2).

Only ``record_origin = 'MIGRATED'`` episodes enter this workflow. Every
confirmation or revocation is appended to
``academic_admission_verification_acts``; slot columns on the admission keep
the latest state, while earlier actors and timestamps remain in the acts table.

The service deliberately never commits. The router commits once, so the act,
the slot state, the trust state, the pointer and every audit entry share one
transaction. Any failure rolls the whole operation back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import record_audit
from app.models.academic import AcademicPeriod, Program, ProgramOffering
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionStatus,
    AcademicAdmissionVerificationAct,
    AdmissionConfirmationState,
    AdmissionEvidenceType,
    AdmissionRecordOrigin,
    AdmissionVerificationAction,
    AdmissionVerificationSlot,
    AdmissionVerificationStatus,
    StudentOriginalAdmissionHistory,
)
from app.models.identity import Student, User
from app.schemas.admission import (
    MigratedAdmissionCreate,
    MigratedAdmissionUpdate,
    OriginalAdmissionCorrection,
    VerificationActRead,
    VerificationConfirm,
    VerificationRevoke,
)

LIVE_STATUSES = (
    AcademicAdmissionStatus.PENDING,
    AcademicAdmissionStatus.ADMITTED,
    AcademicAdmissionStatus.ACTIVE,
)

MIGRATION_AUDIT = "academic.admission.migration"


class OriginalAdmissionOrderConflictError(Exception):
    """The newly verified admission predates the existing pointer.

    The verification itself remains valid and is committed; the pointer is not
    moved. ADMIN must correct it deliberately through the correction workflow.
    """

    def __init__(self, admission: AcademicAdmission):
        super().__init__("ORIGINAL_ADMISSION_ORDER_CONFLICT")
        self.admission = admission


def _now() -> datetime:
    return datetime.now(UTC)


def _lock_student(db: DBSession, student_id: uuid.UUID) -> Student:
    student = db.query(Student).filter(Student.id == student_id).with_for_update().first()
    if student is None:
        raise ValueError("STUDENT_NOT_FOUND")
    return student


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
    db: DBSession,
    student_id: uuid.UUID,
    intake_id: uuid.UUID,
    *,
    exclude_id: uuid.UUID | None = None,
) -> AcademicAdmission | None:
    query = db.query(AcademicAdmission).filter(
        AcademicAdmission.student_id == student_id,
        AcademicAdmission.admission_intake_id == intake_id,
        AcademicAdmission.status.in_([status.value for status in LIVE_STATUSES]),
    )
    if exclude_id is not None:
        query = query.filter(AcademicAdmission.id != exclude_id)
    return query.first()


def _constraint_name(exc: IntegrityError) -> str:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) or ""


def _flush_or_conflict(db: DBSession) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if "uq_academic_admission_student_intake_live" in constraint:
            raise ValueError("ADMISSION_INTAKE_ALREADY_LIVE") from exc
        if "uq_academic_admission_one_active" in constraint:
            raise ValueError("ADMISSION_ALREADY_ACTIVE") from exc
        raise ValueError("ADMISSION_CONFLICT") from exc


def _audit_or_rollback(
    db: DBSession, entries: list[dict[str, Any]]
) -> None:
    """Write audit entries in the caller's transaction; never leave a partial act."""
    try:
        for entry in entries:
            record_audit(db, **entry)
    except Exception:
        db.rollback()
        raise


def _admission_for_update(
    db: DBSession, student_id: uuid.UUID, admission_id: uuid.UUID
) -> AcademicAdmission:
    admission = (
        db.query(AcademicAdmission)
        .filter(
            AcademicAdmission.id == admission_id,
            AcademicAdmission.student_id == student_id,
        )
        .with_for_update()
        .first()
    )
    if admission is None:
        raise ValueError("ADMISSION_NOT_FOUND")
    return admission


def _require_migrated(admission: AcademicAdmission) -> None:
    if admission.record_origin != AdmissionRecordOrigin.MIGRATED.value:
        raise ValueError("ADMISSION_NOT_MIGRATED")


def _require_candidate_editable(admission: AcademicAdmission) -> None:
    _require_migrated(admission)
    # A disputed candidate must remain correctable: the two slots disagree, and
    # revoking one slot alone cannot resolve the disagreement. Verified and
    # revoked records stay locked; their historical candidate is not rewritten.
    if admission.verification_status not in (
        AdmissionVerificationStatus.UNVERIFIED.value,
        AdmissionVerificationStatus.DISPUTED.value,
    ):
        raise ValueError("CANDIDATE_LOCKED")


def _slot_fields(
    admission: AcademicAdmission, slot: AdmissionVerificationSlot
) -> tuple[str, uuid.UUID | None, datetime | None, datetime | None, str | None]:
    if slot is AdmissionVerificationSlot.MANAGEMENT:
        return (
            admission.management_confirmation_state,
            admission.management_confirmed_by_id,
            admission.management_confirmed_at,
            admission.management_revoked_at,
            admission.management_revocation_reason,
        )
    return (
        admission.admin_confirmation_state,
        admission.admin_confirmed_by_id,
        admission.admin_confirmed_at,
        admission.admin_revoked_at,
        admission.admin_revocation_reason,
    )


def _set_slot_confirmed(
    admission: AcademicAdmission,
    slot: AdmissionVerificationSlot,
    *,
    actor_id: uuid.UUID,
    acted_at: datetime,
) -> None:
    if slot is AdmissionVerificationSlot.MANAGEMENT:
        admission.management_confirmation_state = AdmissionConfirmationState.CONFIRMED.value
        admission.management_confirmed_by_id = actor_id
        admission.management_confirmed_at = acted_at
        admission.management_revoked_by_id = None
        admission.management_revoked_at = None
        admission.management_revocation_reason = None
    else:
        admission.admin_confirmation_state = AdmissionConfirmationState.CONFIRMED.value
        admission.admin_confirmed_by_id = actor_id
        admission.admin_confirmed_at = acted_at
        admission.admin_revoked_by_id = None
        admission.admin_revoked_at = None
        admission.admin_revocation_reason = None


def _set_slot_revoked(
    admission: AcademicAdmission,
    slot: AdmissionVerificationSlot,
    *,
    actor_id: uuid.UUID,
    acted_at: datetime,
    reason: str,
) -> None:
    if slot is AdmissionVerificationSlot.MANAGEMENT:
        admission.management_confirmation_state = AdmissionConfirmationState.REVOKED.value
        admission.management_revoked_by_id = actor_id
        admission.management_revoked_at = acted_at
        admission.management_revocation_reason = reason
    else:
        admission.admin_confirmation_state = AdmissionConfirmationState.REVOKED.value
        admission.admin_revoked_by_id = actor_id
        admission.admin_revoked_at = acted_at
        admission.admin_revocation_reason = reason


def _latest_confirmation(
    db: DBSession,
    admission_id: uuid.UUID,
    slot: AdmissionVerificationSlot,
) -> AcademicAdmissionVerificationAct | None:
    return (
        db.query(AcademicAdmissionVerificationAct)
        .filter(
            AcademicAdmissionVerificationAct.admission_id == admission_id,
            AcademicAdmissionVerificationAct.slot == slot.value,
            AcademicAdmissionVerificationAct.action
            == AdmissionVerificationAction.CONFIRM.value,
        )
        .order_by(
            AcademicAdmissionVerificationAct.acted_at.desc(),
            AcademicAdmissionVerificationAct.id.desc(),
        )
        .first()
    )


def _recompute_verification(
    db: DBSession, admission: AcademicAdmission
) -> tuple[AdmissionVerificationStatus, bool]:
    """Return the trust state after a slot change and whether both acts agree."""
    both_confirmed = (
        admission.management_confirmation_state
        == AdmissionConfirmationState.CONFIRMED.value
        and admission.admin_confirmation_state
        == AdmissionConfirmationState.CONFIRMED.value
    )
    if not both_confirmed:
        # A revoked or disputed state is sticky until both slots agree again.
        current = AdmissionVerificationStatus(admission.verification_status)
        if current is AdmissionVerificationStatus.VERIFIED:
            return AdmissionVerificationStatus.UNVERIFIED, False
        return current, False

    management_act = _latest_confirmation(
        db, admission.id, AdmissionVerificationSlot.MANAGEMENT
    )
    admin_act = _latest_confirmation(db, admission.id, AdmissionVerificationSlot.ADMIN)
    if management_act is None or admin_act is None:
        return AdmissionVerificationStatus.UNVERIFIED, False

    agree = (
        management_act.candidate_intake_id == admin_act.candidate_intake_id
        and management_act.candidate_program_id == admin_act.candidate_program_id
    )
    if not agree:
        return AdmissionVerificationStatus.DISPUTED, False
    return AdmissionVerificationStatus.VERIFIED, True


def create_migrated_candidate(
    db: DBSession,
    student: Student,
    data: MigratedAdmissionCreate,
    actor: User,
    request: Any | None = None,
) -> AcademicAdmission:
    """Propose an original admission; it is untrusted until both slots confirm."""
    locked = _lock_student(db, student.id)
    intake = _load_intake(db, data.admission_intake_id)
    offering = _load_offering(db, intake, data.program_offering_id)

    if _live_episode_for_intake(db, locked.id, intake.id) is not None:
        raise ValueError("ADMISSION_INTAKE_ALREADY_LIVE")
    if _active_episode(db, locked.id) is not None:
        # A migrated admission is reconstructed as ADMITTED, not activated;
        # the database guard forbids ADMITTED while another episode is active.
        raise ValueError("ADMISSION_ALREADY_ACTIVE")

    now = _now()
    admission = AcademicAdmission(
        id=uuid.uuid4(),
        student_id=locked.id,
        admission_intake_id=intake.id,
        admitted_program_id=offering.program_id,
        admitted_program_offering_id=offering.id,
        current_program_id=offering.program_id,
        status=AcademicAdmissionStatus.ADMITTED.value,
        initial_status=AcademicAdmissionStatus.ADMITTED.value,
        record_origin=AdmissionRecordOrigin.MIGRATED.value,
        verification_status=AdmissionVerificationStatus.UNVERIFIED.value,
        management_confirmation_state=AdmissionConfirmationState.NONE.value,
        admin_confirmation_state=AdmissionConfirmationState.NONE.value,
        created_by_id=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(admission)
    _flush_or_conflict(db)

    _audit_or_rollback(
        db,
        [
            {
                "action": f"{MIGRATION_AUDIT}.candidate_saved",
                "actor": actor,
                "entity_type": "academic_admission",
                "entity_id": admission.id,
                "context": {
                    "student_id": str(locked.id),
                    "intake_id": str(admission.admission_intake_id),
                    "program_id": str(admission.admitted_program_id),
                    "created": True,
                },
                "request": request,
            }
        ],
    )
    return admission


def update_migrated_candidate(
    db: DBSession,
    student: Student,
    admission_id: uuid.UUID,
    data: MigratedAdmissionUpdate,
    actor: User,
    request: Any | None = None,
) -> AcademicAdmission:
    """Correct an unverified candidate; prior confirmation snapshots stay as acts."""
    locked = _lock_student(db, student.id)
    admission = _admission_for_update(db, locked.id, admission_id)
    _require_candidate_editable(admission)

    if data.admission_intake_id is None and data.program_offering_id is None:
        raise ValueError("MIGRATION_VALIDATION_ERROR")

    intake_id = data.admission_intake_id or admission.admission_intake_id
    offering_id = data.program_offering_id or admission.admitted_program_offering_id
    intake = _load_intake(db, intake_id)
    offering = _load_offering(db, intake, offering_id)

    if _live_episode_for_intake(
        db, locked.id, intake.id, exclude_id=admission.id
    ) is not None:
        raise ValueError("ADMISSION_INTAKE_ALREADY_LIVE")

    admission.admission_intake_id = intake.id
    admission.admitted_program_offering_id = offering.id
    admission.admitted_program_id = offering.program_id
    admission.current_program_id = offering.program_id
    admission.updated_at = _now()
    _flush_or_conflict(db)

    _audit_or_rollback(
        db,
        [
            {
                "action": f"{MIGRATION_AUDIT}.candidate_saved",
                "actor": actor,
                "entity_type": "academic_admission",
                "entity_id": admission.id,
                "context": {
                    "student_id": str(locked.id),
                    "intake_id": str(admission.admission_intake_id),
                    "program_id": str(admission.admitted_program_id),
                    "created": False,
                },
                "request": request,
            }
        ],
    )
    return admission


def confirm_slot(
    db: DBSession,
    student: Student,
    admission_id: uuid.UUID,
    slot: AdmissionVerificationSlot,
    data: VerificationConfirm,
    actor: User,
    request: Any | None = None,
) -> AcademicAdmission:
    """Append one confirmation act and recompute trust for the admission."""
    locked = _lock_student(db, student.id)
    admission = _admission_for_update(db, locked.id, admission_id)
    _require_migrated(admission)

    state, confirmed_by, _, _, _ = _slot_fields(admission, slot)
    if state == AdmissionConfirmationState.CONFIRMED.value:
        raise ValueError("SLOT_ALREADY_CONFIRMED")

    other_slot = (
        AdmissionVerificationSlot.ADMIN
        if slot is AdmissionVerificationSlot.MANAGEMENT
        else AdmissionVerificationSlot.MANAGEMENT
    )
    other_state, other_confirmed_by, _, _, _ = _slot_fields(admission, other_slot)
    if (
        other_state == AdmissionConfirmationState.CONFIRMED.value
        and other_confirmed_by == actor.id
    ):
        raise ValueError("CONFIRMATION_ACTOR_MUST_DIFFER")

    reference = data.evidence_reference.strip()
    if not reference:
        raise ValueError("EVIDENCE_REQUIRED")
    note = (data.evidence_note or "").strip() or None

    now = _now()
    _set_slot_confirmed(admission, slot, actor_id=actor.id, acted_at=now)
    if (
        admission.verification_status == AdmissionVerificationStatus.REVOKED.value
        and admission.management_confirmation_state
        != AdmissionConfirmationState.REVOKED.value
        and admission.admin_confirmation_state
        != AdmissionConfirmationState.REVOKED.value
    ):
        # ck_revoked_requires_slot would reject the intermediate row while the
        # reconfirmed slot is CONFIRMED but the trust state still says REVOKED.
        admission.verification_status = AdmissionVerificationStatus.UNVERIFIED.value

    act = AcademicAdmissionVerificationAct(
        id=uuid.uuid4(),
        admission_id=admission.id,
        slot=slot.value,
        action=AdmissionVerificationAction.CONFIRM.value,
        actor_id=actor.id,
        acted_at=now,
        candidate_intake_id=admission.admission_intake_id,
        candidate_program_id=admission.admitted_program_id,
        evidence_type=AdmissionEvidenceType(data.evidence_type).value,
        evidence_reference=reference,
        evidence_note=note,
        resulting_verification_status=admission.verification_status,
    )
    db.add(act)
    _flush_or_conflict(db)

    status, agreed = _recompute_verification(db, admission)
    admission.verification_status = status.value
    pointer_assigned = False
    pointer_order_conflict = False
    if status is AdmissionVerificationStatus.VERIFIED and agreed:
        admission.verified_at = now
        if locked.original_admission_id is None:
            locked.original_admission_id = admission.id
            pointer_assigned = True
        elif locked.original_admission_id != admission.id:
            pointer_admission = db.get(
                AcademicAdmission, locked.original_admission_id
            )
            if pointer_admission is not None:
                pointer_intake = db.get(
                    AcademicPeriod, pointer_admission.admission_intake_id
                )
                new_intake = db.get(AcademicPeriod, admission.admission_intake_id)
                if (
                    pointer_intake is not None
                    and new_intake is not None
                    and pointer_intake.start_date is not None
                    and new_intake.start_date is not None
                    and new_intake.start_date < pointer_intake.start_date
                ):
                    # Keep the verification and its acts, but never move an
                    # existing pointer silently. The router commits and then
                    # returns ORIGINAL_ADMISSION_ORDER_CONFLICT.
                    pointer_order_conflict = True
    act.resulting_verification_status = status.value
    _flush_or_conflict(db)

    audit_entries: list[dict[str, Any]] = [
        {
            "action": f"{MIGRATION_AUDIT}.{slot.value.lower()}_confirmed",
            "actor": actor,
            "entity_type": "academic_admission",
            "entity_id": admission.id,
            "context": {
                "student_id": str(locked.id),
                "intake_id": str(admission.admission_intake_id),
                "program_id": str(admission.admitted_program_id),
                "slot": slot.value,
                "evidence_type": act.evidence_type,
                "resulting_verification_status": status.value,
            },
            "request": request,
        }
    ]
    if status is AdmissionVerificationStatus.VERIFIED:
        audit_entries.append(
            {
                "action": f"{MIGRATION_AUDIT}.verified",
                "actor": actor,
                "entity_type": "academic_admission",
                "entity_id": admission.id,
                "context": {
                    "student_id": str(locked.id),
                    "intake_id": str(admission.admission_intake_id),
                    "program_id": str(admission.admitted_program_id),
                    "pointer_assigned": pointer_assigned,
                    "pointer_order_conflict": pointer_order_conflict,
                },
                "request": request,
            }
        )
        if pointer_assigned:
            audit_entries.append(
                {
                    "action": f"{MIGRATION_AUDIT}.pointer_set",
                    "actor": actor,
                    "entity_type": "student",
                    "entity_id": locked.id,
                    "context": {
                        "student_id": str(locked.id),
                        "admission_id": str(admission.id),
                        "intake_id": str(admission.admission_intake_id),
                    },
                    "request": request,
                }
            )
    elif status is AdmissionVerificationStatus.DISPUTED:
        audit_entries.append(
            {
                "action": f"{MIGRATION_AUDIT}.disputed",
                "actor": actor,
                "entity_type": "academic_admission",
                "entity_id": admission.id,
                "context": {
                    "student_id": str(locked.id),
                    "management_intake_id": str(
                        _latest_confirmation(
                            db,
                            admission.id,
                            AdmissionVerificationSlot.MANAGEMENT,
                        ).candidate_intake_id
                    ),
                    "admin_intake_id": str(
                        _latest_confirmation(
                            db, admission.id, AdmissionVerificationSlot.ADMIN
                        ).candidate_intake_id
                    ),
                },
                "request": request,
            }
        )

    _audit_or_rollback(db, audit_entries)
    if pointer_order_conflict:
        raise OriginalAdmissionOrderConflictError(admission)
    return admission


def revoke_slot(
    db: DBSession,
    student: Student,
    admission_id: uuid.UUID,
    slot: AdmissionVerificationSlot,
    data: VerificationRevoke,
    actor: User,
    request: Any | None = None,
) -> AcademicAdmission:
    """Revoke one slot without deleting its prior confirmation act."""
    locked = _lock_student(db, student.id)
    admission = _admission_for_update(db, locked.id, admission_id)
    _require_migrated(admission)

    state, confirmed_by, confirmed_at, _, _ = _slot_fields(admission, slot)
    if state == AdmissionConfirmationState.REVOKED.value:
        raise ValueError("SLOT_ALREADY_REVOKED")
    if state != AdmissionConfirmationState.CONFIRMED.value:
        raise ValueError("SLOT_NOT_CONFIRMED")

    reason = data.reason.strip()
    if not reason:
        raise ValueError("REVOCATION_REASON_REQUIRED")

    now = _now()
    _set_slot_revoked(admission, slot, actor_id=actor.id, acted_at=now, reason=reason)

    act = AcademicAdmissionVerificationAct(
        id=uuid.uuid4(),
        admission_id=admission.id,
        slot=slot.value,
        action=AdmissionVerificationAction.REVOKE.value,
        actor_id=actor.id,
        acted_at=now,
        candidate_intake_id=admission.admission_intake_id,
        candidate_program_id=admission.admitted_program_id,
        revocation_reason=reason,
        resulting_verification_status=admission.verification_status,
    )
    db.add(act)

    if admission.verification_status == AdmissionVerificationStatus.VERIFIED.value:
        admission.verification_status = AdmissionVerificationStatus.REVOKED.value
    # DISPUTED stays DISPUTED; UNVERIFIED stays UNVERIFIED.
    act.resulting_verification_status = admission.verification_status
    _flush_or_conflict(db)

    _audit_or_rollback(
        db,
        [
            {
                "action": f"{MIGRATION_AUDIT}.confirmation_revoked",
                "actor": actor,
                "entity_type": "academic_admission",
                "entity_id": admission.id,
                "context": {
                    "student_id": str(locked.id),
                    "intake_id": str(admission.admission_intake_id),
                    "program_id": str(admission.admitted_program_id),
                    "slot": slot.value,
                    "reason": reason,
                    "retained_confirmer_id": (
                        str(confirmed_by) if confirmed_by else None
                    ),
                    "retained_confirmed_at": (
                        confirmed_at.isoformat() if confirmed_at else None
                    ),
                    "resulting_verification_status": admission.verification_status,
                },
                "request": request,
            }
        ],
    )
    return admission


def list_verification_acts(
    db: DBSession, student_id: uuid.UUID, admission_id: uuid.UUID
) -> list[AcademicAdmissionVerificationAct]:
    admission = _admission_for_update(db, student_id, admission_id)
    _require_migrated(admission)
    return (
        db.query(AcademicAdmissionVerificationAct)
        .filter(AcademicAdmissionVerificationAct.admission_id == admission.id)
        .order_by(
            AcademicAdmissionVerificationAct.acted_at.asc(),
            AcademicAdmissionVerificationAct.id.asc(),
        )
        .all()
    )


def verification_acts_to_read(
    db: DBSession, acts: list[AcademicAdmissionVerificationAct]
) -> list[VerificationActRead]:
    """Attach names so conflicting snapshots are legible in the console."""
    actor_ids = {act.actor_id for act in acts}
    intake_ids = {act.candidate_intake_id for act in acts}
    program_ids = {
        act.candidate_program_id for act in acts if act.candidate_program_id is not None
    }
    actors = dict(
        db.query(User.id, User.full_name).filter(User.id.in_(actor_ids)).all()
    )
    intakes = {
        period.id: period
        for period in db.query(AcademicPeriod)
        .filter(AcademicPeriod.id.in_(intake_ids))
        .all()
    }
    programs = dict(
        db.query(Program.id, Program.name)
        .filter(Program.id.in_(program_ids))
        .all()
    )
    return [
        VerificationActRead(
            id=act.id,
            admission_id=act.admission_id,
            slot=act.slot,
            action=act.action,
            actor_id=act.actor_id,
            actor_name=actors.get(act.actor_id),
            acted_at=act.acted_at,
            candidate_intake_id=act.candidate_intake_id,
            candidate_intake_name=(
                intakes[act.candidate_intake_id].name
                if act.candidate_intake_id in intakes
                else None
            ),
            candidate_intake_code=(
                intakes[act.candidate_intake_id].code
                if act.candidate_intake_id in intakes
                else None
            ),
            candidate_program_id=act.candidate_program_id,
            candidate_program_name=programs.get(act.candidate_program_id),
            evidence_type=act.evidence_type,
            evidence_reference=act.evidence_reference,
            evidence_note=act.evidence_note,
            revocation_reason=act.revocation_reason,
            resulting_verification_status=act.resulting_verification_status,
        )
        for act in acts
    ]


def correct_original_admission(
    db: DBSession,
    student: Student,
    data: OriginalAdmissionCorrection,
    actor: User,
    request: Any | None = None,
) -> Student:
    """Replace the pointer through the only path the database trigger accepts."""
    locked = _lock_student(db, student.id)
    target = _admission_for_update(db, locked.id, data.new_admission_id)
    if target.verification_status != AdmissionVerificationStatus.VERIFIED.value:
        raise ValueError("POINTER_TARGET_NOT_VERIFIED")
    if locked.original_admission_id == target.id:
        raise ValueError("POINTER_UNCHANGED")

    reason = data.reason.strip()
    if not reason:
        raise ValueError("POINTER_REASON_REQUIRED")
    evidence = (data.evidence_reference or "").strip() or None
    previous = locked.original_admission_id

    db.add(
        StudentOriginalAdmissionHistory(
            id=uuid.uuid4(),
            student_id=locked.id,
            previous_admission_id=previous,
            new_admission_id=target.id,
            reason=reason,
            actor_id=actor.id,
            created_at=_now(),
        )
    )
    db.flush()

    # The Phase 0 trigger accepts an update only when this transaction-local
    # flag is on and a matching history row exists. Clearing remains impossible.
    db.execute(
        text("SELECT set_config('scu.original_admission_correction', 'on', true)")
    )
    locked.original_admission_id = target.id
    _flush_or_conflict(db)

    _audit_or_rollback(
        db,
        [
            {
                "action": "academic.admission.pointer_corrected",
                "actor": actor,
                "entity_type": "student",
                "entity_id": locked.id,
                "context": {
                    "student_id": str(locked.id),
                    "previous_admission_id": str(previous) if previous else None,
                    "new_admission_id": str(target.id),
                    "new_intake_id": str(target.admission_intake_id),
                    "reason": reason,
                    "evidence_reference": evidence,
                },
                "request": request,
            }
        ],
    )
    return locked


__all__ = [
    "confirm_slot",
    "correct_original_admission",
    "create_migrated_candidate",
    "list_verification_acts",
    "revoke_slot",
    "verification_acts_to_read",
    "update_migrated_candidate",
]
