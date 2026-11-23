"""Current academic placement and earlier-intake authorization.

Placement is intentionally separate from admission:

* the admission keeps its immutable original intake, admitted programme and
  admitted offering;
* the placement records where the student is currently being taught;
* the student-facing projection follows the current placement, but no
  enrollment, attendance, grade or timetable row is moved.

Every write locks the student and the current placement row, so concurrent
supersessions cannot leave two current placements. The database CHECK and
composite FK remain the final arbiter.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.models.academic import AcademicPeriod, Program, ProgramOffering
from app.models.admission import AcademicAdmission, AcademicAdmissionStatus, AcademicPlacement
from app.models.identity import Student, User
from app.schemas.admission import (
    PlacementCreate,
    PlacementListResponse,
    PlacementRead,
)


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


def _load_admission(
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


def _load_offering(
    db: DBSession, offering_id: uuid.UUID
) -> tuple[ProgramOffering, AcademicPeriod, Program]:
    offering = db.get(ProgramOffering, offering_id)
    if offering is None:
        raise ValueError("PROGRAM_OFFERING_NOT_FOUND")
    if offering.program_id is None:
        raise ValueError("PROGRAM_OFFERING_NOT_MAPPED")
    program = db.get(Program, offering.program_id)
    if program is None:
        raise ValueError("PROGRAM_OFFERING_NOT_MAPPED")
    intake = db.get(AcademicPeriod, offering.academic_period_id)
    if intake is None:
        raise ValueError("ADMISSION_INTAKE_NOT_FOUND")
    return offering, intake, program


def _require_intake_dates(intake: AcademicPeriod) -> None:
    if intake.start_date is None or intake.end_date is None:
        raise ValueError("INTAKE_DATES_REQUIRED")
    if intake.end_date < intake.start_date:
        raise ValueError("INTAKE_DATES_INVALID")


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


def create_placement(
    db: DBSession,
    student: Student,
    data: PlacementCreate,
    actor: User,
    *,
    can_authorize_earlier: bool,
) -> tuple[AcademicPlacement, AcademicPlacement | None]:
    """Create a placement and close the prior current row.

    The caller owns the transaction and writes the audit entry before commit.
    The service never commits, so an audit failure rolls back both rows and the
    student projection together.
    """
    locked = _lock_student(db, student.id)
    admission = _load_admission(db, locked.id, data.admission_id)

    status = AcademicAdmissionStatus(admission.status)
    if status not in (
        AcademicAdmissionStatus.ADMITTED,
        AcademicAdmissionStatus.ACTIVE,
    ):
        raise ValueError("PLACEMENT_REQUIRES_ADMITTED_EPISODE")

    offering, placement_intake, program = _load_offering(
        db, data.program_offering_id
    )
    admission_intake = db.get(AcademicPeriod, admission.admission_intake_id)
    if admission_intake is None:
        raise ValueError("ADMISSION_INTAKE_NOT_FOUND")
    _require_intake_dates(admission_intake)
    _require_intake_dates(placement_intake)

    earlier = placement_intake.start_date < admission_intake.start_date
    reason = (data.reason or "").strip()
    if earlier and not can_authorize_earlier:
        raise ValueError("EARLIER_INTAKE_NOT_AUTHORIZED")
    if earlier and not reason:
        raise ValueError("EARLIER_INTAKE_REASON_REQUIRED")

    now = _now()
    previous = _current_placement(db, locked.id)
    if previous is not None:
        previous.ended_at = now
        # Flush the closure before inserting the replacement: the partial
        # unique index permits exactly one row with ended_at IS NULL.
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise ValueError("PLACEMENT_CONFLICT") from exc

    placement = AcademicPlacement(
        id=uuid.uuid4(),
        student_id=locked.id,
        admission_id=admission.id,
        academic_period_id=placement_intake.id,
        program_offering_id=offering.id,
        is_earlier_intake_placement=earlier,
        authorized_by_id=actor.id if earlier else None,
        authorization_reason=reason if earlier else None,
        effective_from=data.effective_from or date.today(),
        created_by_id=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(placement)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if "uq_academic_placement_current" in constraint:
            raise ValueError("PLACEMENT_CONFLICT") from exc
        if "fk_placement_offering_in_period" in constraint:
            raise ValueError("ADMISSION_OFFERING_INTAKE_MISMATCH") from exc
        raise ValueError("PLACEMENT_CONFLICT") from exc

    return placement, previous


def placement_to_read(
    db: DBSession,
    placement: AcademicPlacement,
    *,
    admission_intake: AcademicPeriod | None = None,
    placement_intake: AcademicPeriod | None = None,
    offering: ProgramOffering | None = None,
    program: Program | None = None,
) -> PlacementRead:
    admission = db.get(AcademicAdmission, placement.admission_id)
    admission_intake = admission_intake or (
        db.get(AcademicPeriod, admission.admission_intake_id) if admission else None
    )
    placement_intake = placement_intake or db.get(
        AcademicPeriod, placement.academic_period_id
    )
    offering = offering or db.get(ProgramOffering, placement.program_offering_id)
    program = program or (
        db.get(Program, offering.program_id)
        if offering is not None and offering.program_id is not None
        else None
    )
    authorized_by = (
        db.get(User, placement.authorized_by_id)
        if placement.authorized_by_id is not None
        else None
    )
    created_by = db.get(User, placement.created_by_id)
    return PlacementRead(
        id=placement.id,
        student_id=placement.student_id,
        admission_id=placement.admission_id,
        admission_intake_id=(
            admission.admission_intake_id if admission else placement.academic_period_id
        ),
        admission_intake_code=(
            admission_intake.code if admission_intake is not None else None
        ),
        admission_intake_name=(
            admission_intake.name if admission_intake is not None else None
        ),
        admission_intake_start_date=(
            admission_intake.start_date if admission_intake is not None else None
        ),
        placement_intake_id=placement.academic_period_id,
        placement_intake_code=(
            placement_intake.code if placement_intake is not None else None
        ),
        placement_intake_name=(
            placement_intake.name if placement_intake is not None else None
        ),
        placement_intake_start_date=(
            placement_intake.start_date if placement_intake is not None else None
        ),
        program_id=offering.program_id if offering is not None else None,
        program_name=program.name if program is not None else None,
        program_offering_id=placement.program_offering_id,
        program_offering_name=offering.name if offering is not None else None,
        is_earlier_intake_placement=placement.is_earlier_intake_placement,
        authorized_by_id=placement.authorized_by_id,
        authorized_by_name=authorized_by.full_name if authorized_by else None,
        authorization_reason=placement.authorization_reason,
        effective_from=placement.effective_from,
        ended_at=placement.ended_at,
        is_current=placement.ended_at is None,
        created_by_id=placement.created_by_id,
        created_by_name=created_by.full_name if created_by else None,
        created_at=placement.created_at,
    )


def list_placements(
    db: DBSession, student_id: uuid.UUID
) -> PlacementListResponse:
    placements = (
        db.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == student_id)
        .order_by(
            AcademicPlacement.created_at.desc(),
            AcademicPlacement.id.desc(),
        )
        .all()
    )
    return PlacementListResponse(
        items=[placement_to_read(db, placement) for placement in placements],
        total=len(placements),
    )
