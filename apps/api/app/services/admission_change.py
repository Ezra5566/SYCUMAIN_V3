"""Controlled changes inside one admission episode (Phase 4).

A programme change is a same-episode event: it updates the episode's current
programme (and, when requested, its current placement) while leaving the
originally admitted programme and intake untouched. It never creates an
admission episode.

The only transition that creates a new episode is a fresh admission after the
previous one is terminal. That rule lives in :mod:`app.services.admission`; this
module deliberately has no create-episode path.

Every write locks the student, then the admission, then the request. Review
locks the same rows and re-reads the request with ``status = 'PENDING'``, so two
reviewers cannot both apply a decision. The partial unique index on
``(admission_id, change_type)`` is the final race guard for request creation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.models.academic import (
    AcademicPeriod,
    EntityStatus,
    Program,
    ProgramOffering,
)
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionChange,
    AcademicAdmissionStatus,
    AcademicPlacement,
    AdmissionChangeStatus,
    AdmissionChangeType,
)
from app.models.identity import Student, User
from app.schemas.admission import (
    AdmissionChangeCreate,
    AdmissionChangeRead,
    AdmissionChangeReview,
    AdmissionStatusCorrection,
    AdmissionTransition,
    PlacementCreate,
)
from app.services.admission import (
    ALLOWED_TRANSITIONS,
    _active_episode,
    correct_admission_status,
    transition_admission,
)
from app.services.placement import create_placement
from app.services.student_academic import effective_admission_priority

TERMINAL_STATUSES = {
    AcademicAdmissionStatus.COMPLETED,
    AcademicAdmissionStatus.WITHDRAWN,
    AcademicAdmissionStatus.CANCELLED,
}
LIVE_STATUSES = {
    AcademicAdmissionStatus.PENDING,
    AcademicAdmissionStatus.ADMITTED,
    AcademicAdmissionStatus.ACTIVE,
}
PLACEMENT_STATUSES = {
    AcademicAdmissionStatus.ADMITTED,
    AcademicAdmissionStatus.ACTIVE,
}
REASON_REQUIRED_TYPES = {
    AdmissionChangeType.PLACEMENT_CHANGE,
    AdmissionChangeType.EARLIER_INTAKE_PLACEMENT,
    AdmissionChangeType.WITHDRAWAL,
    AdmissionChangeType.STATUS_CORRECTION,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _constraint_name(exc: IntegrityError) -> str:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) or ""


def _lock_student(db: DBSession, student_id: uuid.UUID) -> Student:
    student = (
        db.query(Student).filter(Student.id == student_id).with_for_update().first()
    )
    if student is None:
        raise ValueError("STUDENT_NOT_FOUND")
    return student


def _lock_admission(
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


def _current_placement(
    db: DBSession, student_id: uuid.UUID
) -> AcademicPlacement | None:
    return (
        db.query(AcademicPlacement)
        .filter(
            AcademicPlacement.student_id == student_id,
            AcademicPlacement.ended_at.is_(None),
        )
        .with_for_update()
        .first()
    )


def _load_program(db: DBSession, program_id: uuid.UUID | None) -> Program:
    if program_id is None:
        raise ValueError("PROGRAM_CHANGE_TARGET_REQUIRED")
    program = db.get(Program, program_id)
    if program is None:
        raise ValueError("PROGRAM_CHANGE_TARGET_NOT_FOUND")
    if program.status != EntityStatus.ACTIVE:
        raise ValueError("PROGRAM_CHANGE_TARGET_INACTIVE")
    return program


def _load_offering(db: DBSession, offering_id: uuid.UUID) -> ProgramOffering:
    offering = db.get(ProgramOffering, offering_id)
    if offering is None:
        raise ValueError("PROGRAM_OFFERING_NOT_FOUND")
    if offering.program_id is None:
        raise ValueError("PROGRAM_OFFERING_NOT_MAPPED")
    return offering


def _require_intake_dates(intake: AcademicPeriod) -> None:
    if intake.start_date is None or intake.end_date is None:
        raise ValueError("INTAKE_DATES_REQUIRED")
    if intake.end_date < intake.start_date:
        raise ValueError("INTAKE_DATES_INVALID")


def _snapshot(
    db: DBSession,
    admission: AcademicAdmission,
    placement: AcademicPlacement | None,
) -> dict:
    """A safe, human-readable before-state; never credentials or free text."""
    return {
        "status": admission.status,
        "admission_intake_id": str(admission.admission_intake_id),
        "admitted_program_id": (
            str(admission.admitted_program_id)
            if admission.admitted_program_id is not None
            else None
        ),
        "current_program_id": (
            str(admission.current_program_id)
            if admission.current_program_id is not None
            else None
        ),
        "current_placement_id": str(placement.id) if placement else None,
        "current_placement_offering_id": (
            str(placement.program_offering_id) if placement else None
        ),
        "current_placement_intake_id": (
            str(placement.academic_period_id) if placement else None
        ),
        "current_program_offering_id": (
            str(placement.program_offering_id)
            if placement
            else str(admission.admitted_program_offering_id)
        ),
    }


def _validate_reason(data: AdmissionChangeCreate, change_type: AdmissionChangeType) -> str | None:
    reason = (data.reason or "").strip()
    if change_type in REASON_REQUIRED_TYPES and not reason:
        if change_type is AdmissionChangeType.EARLIER_INTAKE_PLACEMENT:
            raise ValueError("EARLIER_INTAKE_REASON_REQUIRED")
        raise ValueError("CHANGE_REASON_REQUIRED")
    return reason or None


def _prepare_change(
    db: DBSession,
    *,
    student: Student,
    admission: AcademicAdmission,
    data: AdmissionChangeCreate,
    placement: AcademicPlacement | None,
) -> AcademicAdmissionChange:
    """Validate a request against current rows and build the pending row."""
    change_type = AdmissionChangeType(data.change_type)
    status = AcademicAdmissionStatus(admission.status)
    if status in TERMINAL_STATUSES and change_type is not AdmissionChangeType.STATUS_CORRECTION:
        raise ValueError("ADMISSION_TERMINAL")
    reason = _validate_reason(data, change_type)
    admission_intake = db.get(AcademicPeriod, admission.admission_intake_id)
    if admission_intake is None:
        raise ValueError("ADMISSION_INTAKE_NOT_FOUND")
    _require_intake_dates(admission_intake)

    current_program_id = admission.current_program_id or admission.admitted_program_id
    from_offering_id = (
        placement.program_offering_id
        if placement is not None
        else admission.admitted_program_offering_id
    )
    to_program_id = data.to_program_id
    to_offering_id = data.to_program_offering_id
    target_period_id = data.target_period_id
    proposed = dict(data.proposed_data or {})

    if change_type is AdmissionChangeType.PROGRAM_CHANGE:
        program = _load_program(db, to_program_id)
        if current_program_id == program.id:
            raise ValueError("PROGRAM_CHANGE_SAME_PROGRAM")

        if to_offering_id is not None:
            if status not in PLACEMENT_STATUSES:
                raise ValueError("PLACEMENT_REQUIRES_ADMITTED_EPISODE")
            offering = _load_offering(db, to_offering_id)
            if offering.academic_period_id != admission.admission_intake_id:
                raise ValueError("PROGRAM_CHANGE_OFFERING_INTAKE_MISMATCH")
            if offering.program_id != program.id:
                raise ValueError("PROGRAM_CHANGE_OFFERING_MISMATCH")
            target_period_id = offering.academic_period_id
        proposed = {
            **proposed,
            "to_program_id": str(program.id),
            "to_program_offering_id": (
                str(to_offering_id) if to_offering_id is not None else None
            ),
            "effective": "IMMEDIATE",
        }

    elif change_type in (
        AdmissionChangeType.PLACEMENT_CHANGE,
        AdmissionChangeType.EARLIER_INTAKE_PLACEMENT,
    ):
        if to_offering_id is None:
            raise ValueError("PLACEMENT_OFFERING_REQUIRED")
        offering = _load_offering(db, to_offering_id)
        target_intake = db.get(AcademicPeriod, offering.academic_period_id)
        if target_intake is None:
            raise ValueError("ADMISSION_INTAKE_NOT_FOUND")
        _require_intake_dates(target_intake)
        earlier = target_intake.start_date < admission_intake.start_date

        if change_type is AdmissionChangeType.EARLIER_INTAKE_PLACEMENT:
            if not earlier:
                raise ValueError("NOT_EARLIER_INTAKE_PLACEMENT")
        elif earlier:
            # Earlier-intake placement is a distinct, separately authorized
            # request type. Silently treating a placement change as one would
            # bypass the authorization gate.
            raise ValueError("USE_EARLIER_INTAKE_PLACEMENT")

        if target_period_id is not None and target_period_id != target_intake.id:
            raise ValueError("ADMISSION_OFFERING_INTAKE_MISMATCH")
        target_period_id = target_intake.id
        to_program_id = offering.program_id
        proposed = {
            **proposed,
            "to_program_id": str(to_program_id),
            "to_program_offering_id": str(offering.id),
            "target_period_id": str(target_intake.id),
            "is_earlier_intake_placement": earlier,
        }

    elif change_type is AdmissionChangeType.WITHDRAWAL:
        if status is not AcademicAdmissionStatus.ACTIVE:
            raise ValueError("ADMISSION_TRANSITION_NOT_ALLOWED")
        proposed = {**proposed, "status": AcademicAdmissionStatus.WITHDRAWN.value}

    elif change_type is AdmissionChangeType.STATUS_CORRECTION:
        requested_status = str(proposed.get("status", "")).upper()
        if not requested_status:
            raise ValueError("CHANGE_PROPOSED_STATUS_REQUIRED")
        try:
            target = AcademicAdmissionStatus(requested_status)
        except ValueError as exc:
            raise ValueError("CHANGE_PROPOSED_STATUS_INVALID") from exc
        if target is status:
            raise ValueError("CHANGE_PROPOSED_STATUS_INVALID")
        allowed = (
            {candidate for candidate in AcademicAdmissionStatus if candidate is not status}
            if status in TERMINAL_STATUSES
            else ALLOWED_TRANSITIONS.get(status, set())
        )
        if target not in allowed:
            raise ValueError("ADMISSION_TRANSITION_NOT_ALLOWED")
        if (
            target
            in (AcademicAdmissionStatus.ADMITTED, AcademicAdmissionStatus.ACTIVE)
            and _active_episode(db, student.id, exclude_id=admission.id) is not None
        ):
            code = (
                "ADMISSION_ALREADY_ACTIVE"
                if target is AcademicAdmissionStatus.ACTIVE
                else "ADMISSION_MUST_BE_PENDING"
            )
            raise ValueError(code)
        if (
            target
            in (
                AcademicAdmissionStatus.WITHDRAWN,
                AcademicAdmissionStatus.CANCELLED,
            )
            and not reason
        ):
            raise ValueError("CHANGE_REASON_REQUIRED")
        proposed = {**proposed, "status": target.value}

    else:  # pragma: no cover - the enum currently has exactly five members
        raise ValueError("CHANGE_TYPE_INVALID")

    return AcademicAdmissionChange(
        id=uuid.uuid4(),
        admission_id=admission.id,
        change_type=change_type.value,
        from_program_id=current_program_id,
        to_program_id=to_program_id,
        from_program_offering_id=from_offering_id,
        to_program_offering_id=to_offering_id,
        target_period_id=target_period_id,
        proposed_data=proposed,
        current_data_snapshot=_snapshot(db, admission, placement),
        reason=reason,
        requested_by_id=student.user_id,
        requested_at=_now(),
        status=AdmissionChangeStatus.PENDING.value,
    )


def request_admission_change(
    db: DBSession,
    student: Student,
    admission_id: uuid.UUID,
    data: AdmissionChangeCreate,
    actor: User,
    *,
    self_service: bool = False,
) -> AcademicAdmissionChange:
    """Create a pending request without changing any academic record.

    Raises:
        ValueError: with a stable code for the router to localize.
    """
    locked = _lock_student(db, student.id)
    admission = _lock_admission(db, locked.id, admission_id)
    placement = _current_placement(db, locked.id)
    change = _prepare_change(
        db,
        student=locked,
        admission=admission,
        data=data,
        placement=placement,
    )
    change.requested_by_id = actor.id
    if self_service:
        change.proposed_data = {**change.proposed_data, "source": "SELF_SERVICE"}

    db.add(change)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if "uq_admission_change_one_pending" in _constraint_name(exc):
            raise ValueError("CHANGE_REQUEST_PENDING_EXISTS") from exc
        if "ck_no_self_approval" in _constraint_name(exc):
            raise ValueError("SELF_APPROVAL_FORBIDDEN") from exc
        raise ValueError("CHANGE_REQUEST_CONFLICT") from exc
    return change


def request_self_service_change(
    db: DBSession,
    student: Student,
    *,
    to_program_id: uuid.UUID | None,
    to_program_offering_id: uuid.UUID | None,
    actor: User,
    reason: str | None = None,
) -> AcademicAdmissionChange:
    """A student proposes a programme change on their live episode.

    Self-service never writes the programme or projection directly. The
    request is pending until an Admin or Management user decides it. The live
    episode is chosen with the same ACTIVE-first precedence as the read-side
    effective resolver, then by the same deterministic tie-break.
    """
    live = (
        db.query(AcademicAdmission)
        .filter(
            AcademicAdmission.student_id == student.id,
            AcademicAdmission.status.in_(
                [
                    AcademicAdmissionStatus.ADMITTED.value,
                    AcademicAdmissionStatus.ACTIVE.value,
                ]
            ),
        )
        .order_by(
            effective_admission_priority(AcademicAdmission),
            AcademicAdmission.created_at.desc(),
            AcademicAdmission.id.desc(),
        )
        .first()
    )
    if live is None:
        raise ValueError("NO_ADMISSION_EPISODE")

    offering = None
    if to_program_offering_id is not None:
        offering = _load_offering(db, to_program_offering_id)
        if offering.academic_period_id != live.admission_intake_id:
            raise ValueError("PROGRAM_CHANGE_OFFERING_INTAKE_MISMATCH")
        if to_program_id is None:
            to_program_id = offering.program_id
        elif offering.program_id != to_program_id:
            raise ValueError("PROGRAM_CHANGE_OFFERING_MISMATCH")

    return request_admission_change(
        db,
        student,
        live.id,
        AdmissionChangeCreate(
            change_type=AdmissionChangeType.PROGRAM_CHANGE,
            to_program_id=to_program_id,
            to_program_offering_id=(
                offering.id if offering is not None else None
            ),
            reason=reason,
        ),
        actor,
        self_service=True,
    )


def _apply_placement(
    db: DBSession,
    *,
    student: Student,
    admission: AcademicAdmission,
    change: AcademicAdmissionChange,
    actor: User,
    can_authorize_earlier: bool,
) -> None:
    if change.to_program_offering_id is None:
        raise ValueError("PLACEMENT_OFFERING_REQUIRED")
    if AcademicAdmissionStatus(admission.status) not in PLACEMENT_STATUSES:
        raise ValueError("PLACEMENT_REQUIRES_ADMITTED_EPISODE")
    create_placement(
        db,
        student,
        PlacementCreate(
            admission_id=admission.id,
            program_offering_id=change.to_program_offering_id,
            effective_from=date.today(),
            reason=change.reason,
        ),
        actor,
        can_authorize_earlier=can_authorize_earlier,
    )


def _apply_approved_change(
    db: DBSession,
    *,
    student: Student,
    admission: AcademicAdmission,
    change: AcademicAdmissionChange,
    actor: User,
    can_authorize_earlier: bool,
    request: Any | None = None,
) -> None:
    """Apply one approved request inside the review transaction."""
    change_type = AdmissionChangeType(change.change_type)
    if (
        AcademicAdmissionStatus(admission.status) in TERMINAL_STATUSES
        and change_type is not AdmissionChangeType.STATUS_CORRECTION
    ):
        raise ValueError("ADMISSION_TERMINAL")
    now = _now()

    if change_type is AdmissionChangeType.PROGRAM_CHANGE:
        if admission.current_program_id != change.from_program_id:
            raise ValueError("CHANGE_REQUEST_STALE")
        program = _load_program(db, change.to_program_id)
        admission.current_program_id = program.id
        admission.current_program_changed_at = now
        admission.updated_at = now

        if change.to_program_offering_id is not None:
            _apply_placement(
                db,
                student=student,
                admission=admission,
                change=change,
                actor=actor,
                can_authorize_earlier=can_authorize_earlier,
            )
        # A programme change without a placement change leaves the historical
        # admitted offering untouched; the current programme is read from the
        # admission episode itself.

    elif change_type in (
        AdmissionChangeType.PLACEMENT_CHANGE,
        AdmissionChangeType.EARLIER_INTAKE_PLACEMENT,
    ):
        _apply_placement(
            db,
            student=student,
            admission=admission,
            change=change,
            actor=actor,
            can_authorize_earlier=can_authorize_earlier,
        )

    elif change_type is AdmissionChangeType.WITHDRAWAL:
        transition_admission(
            db,
            student,
            admission.id,
            AdmissionTransition(
                status=AcademicAdmissionStatus.WITHDRAWN.value,
                reason=change.reason or "Withdrawal approved",
            ),
            actor,
        )

    elif change_type is AdmissionChangeType.STATUS_CORRECTION:
        target = str(change.proposed_data.get("status", "")).upper()
        correct_admission_status(
            db,
            student,
            admission.id,
            AdmissionStatusCorrection(
                target_status=target,
                reason=change.reason or "",
            ),
            actor,
            request=request,
            change_request_id=change.id,
        )


def review_admission_change(
    db: DBSession,
    change_id: uuid.UUID,
    data: AdmissionChangeReview,
    actor: User,
    *,
    can_authorize_earlier: bool,
    request: Any | None = None,
) -> AcademicAdmissionChange:
    """Approve or reject one pending request, atomically.

    ``APPROVE`` applies the change before the decision is recorded. A failure
    anywhere in the application rolls back the request decision too, so a
    half-applied programme/placement change cannot exist.
    """
    candidate = db.get(AcademicAdmissionChange, change_id)
    if candidate is None:
        raise ValueError("CHANGE_REQUEST_NOT_FOUND")

    admission_ref = db.get(AcademicAdmission, candidate.admission_id)
    if admission_ref is None:
        raise ValueError("ADMISSION_NOT_FOUND")
    student = _lock_student(db, admission_ref.student_id)
    admission = _lock_admission(db, student.id, candidate.admission_id)

    change = (
        db.query(AcademicAdmissionChange)
        .filter(
            AcademicAdmissionChange.id == change_id,
            AcademicAdmissionChange.status == AdmissionChangeStatus.PENDING.value,
        )
        .with_for_update()
        .first()
    )
    if change is None:
        raise ValueError("CHANGE_ALREADY_REVIEWED")

    if change.requested_by_id == actor.id:
        raise ValueError("SELF_APPROVAL_FORBIDDEN")

    decision_reason = (data.reason or "").strip() or None
    now = _now()

    if data.decision == "APPROVE":
        _apply_approved_change(
            db,
            student=student,
            admission=admission,
            change=change,
            actor=actor,
            can_authorize_earlier=can_authorize_earlier,
            request=request,
        )
        change.status = AdmissionChangeStatus.APPROVED.value
    else:
        change.status = AdmissionChangeStatus.REJECTED.value

    change.reviewed_by_id = actor.id
    change.reviewed_at = now
    change.decision_reason = decision_reason

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if "ck_no_self_approval" in _constraint_name(exc):
            raise ValueError("SELF_APPROVAL_FORBIDDEN") from exc
        raise ValueError("CHANGE_REQUEST_CONFLICT") from exc
    return change


def _name(db: DBSession, model, row_id):  # noqa: ANN001 - small local helper
    if row_id is None:
        return None
    row = db.get(model, row_id)
    return getattr(row, "name", None) if row is not None else None


def change_to_read(db: DBSession, change: AcademicAdmissionChange) -> AdmissionChangeRead:
    admission = db.get(AcademicAdmission, change.admission_id)
    requester = db.get(User, change.requested_by_id)
    reviewer = db.get(User, change.reviewed_by_id) if change.reviewed_by_id else None
    return AdmissionChangeRead(
        id=change.id,
        admission_id=change.admission_id,
        student_id=admission.student_id if admission else uuid.UUID(int=0),
        change_type=AdmissionChangeType(change.change_type),
        status=AdmissionChangeStatus(change.status),
        from_program_id=change.from_program_id,
        from_program_name=_name(db, Program, change.from_program_id),
        to_program_id=change.to_program_id,
        to_program_name=_name(db, Program, change.to_program_id),
        from_program_offering_id=change.from_program_offering_id,
        from_program_offering_name=_name(
            db, ProgramOffering, change.from_program_offering_id
        ),
        to_program_offering_id=change.to_program_offering_id,
        to_program_offering_name=_name(
            db, ProgramOffering, change.to_program_offering_id
        ),
        target_period_id=change.target_period_id,
        target_period_name=_name(db, AcademicPeriod, change.target_period_id),
        proposed_data=change.proposed_data or {},
        current_data_snapshot=change.current_data_snapshot,
        reason=change.reason,
        requested_by_id=change.requested_by_id,
        requested_by_name=requester.full_name if requester else None,
        requested_at=change.requested_at,
        reviewed_by_id=change.reviewed_by_id,
        reviewed_by_name=reviewer.full_name if reviewer else None,
        reviewed_at=change.reviewed_at,
        decision_reason=change.decision_reason,
    )


def list_admission_changes(
    db: DBSession,
    student_id: uuid.UUID,
    *,
    admission_id: uuid.UUID | None = None,
) -> list[AcademicAdmissionChange]:
    query = (
        db.query(AcademicAdmissionChange)
        .join(
            AcademicAdmission,
            AcademicAdmission.id == AcademicAdmissionChange.admission_id,
        )
        .filter(AcademicAdmission.student_id == student_id)
    )
    if admission_id is not None:
        query = query.filter(AcademicAdmissionChange.admission_id == admission_id)
    return (
        query.order_by(
            AcademicAdmissionChange.requested_at.desc(),
            AcademicAdmissionChange.id.desc(),
        )
        .all()
    )


__all__ = [
    "change_to_read",
    "list_admission_changes",
    "request_admission_change",
    "request_self_service_change",
    "review_admission_change",
]
