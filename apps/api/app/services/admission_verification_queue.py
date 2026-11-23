"""Read-only migration verification queue (Phase 2 console).

The queue is a projection over existing admission/verification data; it does
not create, confirm, revoke or correct anything. Every write continues to go
through the Phase 2 service and its authorization rules.
"""

from __future__ import annotations

import math

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.config.settings import get_settings
from app.models.academic import AcademicPeriod, Program, ProgramOffering
from app.models.admission import (
    AcademicAdmission,
    AdmissionConfirmationState,
    AdmissionRecordOrigin,
    AdmissionVerificationSlot,
    AdmissionVerificationStatus,
)
from app.models.identity import Student
from app.schemas.admission import MigrationQueueItem, MigrationQueueResponse


def list_migration_queue(
    db: DBSession,
    *,
    verification_status: AdmissionVerificationStatus | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> MigrationQueueResponse:
    """Return one page of MIGRATED candidates, newest data first by student."""
    query = (
        db.query(
            AcademicAdmission,
            Student,
            AcademicPeriod,
            ProgramOffering,
            Program,
        )
        .join(Student, Student.id == AcademicAdmission.student_id)
        .join(
            AcademicPeriod,
            AcademicPeriod.id == AcademicAdmission.admission_intake_id,
        )
        .join(
            ProgramOffering,
            ProgramOffering.id == AcademicAdmission.admitted_program_offering_id,
        )
        .outerjoin(Program, Program.id == AcademicAdmission.admitted_program_id)
        .filter(AcademicAdmission.record_origin == AdmissionRecordOrigin.MIGRATED.value)
    )

    if verification_status is not None:
        query = query.filter(
            AcademicAdmission.verification_status == verification_status.value
        )

    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Student.first_name.ilike(pattern),
                Student.last_name.ilike(pattern),
                Student.student_id.ilike(pattern),
                AcademicPeriod.name.ilike(pattern),
                AcademicPeriod.code.ilike(pattern),
                Program.name.ilike(pattern),
                ProgramOffering.name.ilike(pattern),
            )
        )

    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))
    page = min(page, total_pages)
    offset = (page - 1) * page_size
    rows = (
        query.order_by(
            Student.last_name,
            Student.first_name,
            AcademicAdmission.created_at.desc(),
        )
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items: list[MigrationQueueItem] = []
    for admission, student, intake, offering, program in rows:
        outstanding = []
        if (
            admission.management_confirmation_state
            != AdmissionConfirmationState.CONFIRMED.value
        ):
            outstanding.append(AdmissionVerificationSlot.MANAGEMENT)
        if (
            admission.admin_confirmation_state
            != AdmissionConfirmationState.CONFIRMED.value
        ):
            outstanding.append(AdmissionVerificationSlot.ADMIN)

        items.append(
            MigrationQueueItem(
                admission_id=admission.id,
                student_id=student.id,
                student_number=student.student_id,
                student_name=f"{student.first_name} {student.last_name}",
                admission_status=admission.status,
                verification_status=admission.verification_status,
                admission_intake_id=admission.admission_intake_id,
                admission_intake_code=intake.code,
                admission_intake_name=intake.name,
                admission_intake_start_date=intake.start_date,
                admitted_program_id=admission.admitted_program_id,
                admitted_program_name=program.name if program else None,
                admitted_program_offering_id=admission.admitted_program_offering_id,
                admitted_program_offering_name=offering.name,
                management_confirmation_state=admission.management_confirmation_state,
                management_confirmed_by_id=admission.management_confirmed_by_id,
                management_confirmed_at=admission.management_confirmed_at,
                management_revoked_at=admission.management_revoked_at,
                admin_confirmation_state=admission.admin_confirmation_state,
                admin_confirmed_by_id=admission.admin_confirmed_by_id,
                admin_confirmed_at=admission.admin_confirmed_at,
                admin_revoked_at=admission.admin_revoked_at,
                outstanding_slots=outstanding,
                original_admission_id=student.original_admission_id,
                is_original_admission=student.original_admission_id == admission.id,
                verified_at=admission.verified_at,
                corrections_enabled=get_settings().ADMISSION_CORRECTIONS_ENABLED,
                created_at=admission.created_at,
            )
        )

    return MigrationQueueResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


__all__ = ["list_migration_queue"]
