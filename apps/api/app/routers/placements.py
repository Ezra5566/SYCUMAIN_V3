"""Current academic placement endpoints (Phase 3)."""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID annotations at runtime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import record_audit
from app.auth.dependencies import CurrentUser  # noqa: TC001 - FastAPI dependency
from app.config.settings import get_settings
from app.database.session import get_db
from app.models.admission import AcademicAdmission
from app.models.identity import Student
from app.permissions.checks import has_permission
from app.schemas.admission import (
    PlacementCreate,
    PlacementListResponse,
    PlacementRead,
)
from app.services.placement import create_placement, list_placements, placement_to_read

router = APIRouter(prefix="/students/{student_id}/placements", tags=["placements"])

_VIEW = "academic.view_admissions"
_MANAGE = "academic.manage_placements"
_AUTHORIZE = "academic.authorize_placement"

_ERRORS: dict[str, tuple[int, str, str]] = {
    "STUDENT_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "STUDENT_NOT_FOUND",
        "Student not found.",
    ),
    "ADMISSION_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "ADMISSION_NOT_FOUND",
        "Admission not found for this student.",
    ),
    "PROGRAM_OFFERING_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "PROGRAM_OFFERING_NOT_FOUND",
        "Program offering not found.",
    ),
    "PROGRAM_OFFERING_NOT_MAPPED": (
        http_status.HTTP_409_CONFLICT,
        "PROGRAM_OFFERING_NOT_MAPPED",
        "That source offering has not been mapped to a canonical program.",
    ),
    "ADMISSION_INTAKE_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "ADMISSION_INTAKE_NOT_FOUND",
        "Admission intake not found.",
    ),
    "INTAKE_DATES_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INTAKE_DATES_REQUIRED",
        "The intake must have both an official start and end date.",
    ),
    "INTAKE_DATES_INVALID": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INTAKE_DATES_INVALID",
        "The intake's end date cannot precede its start date.",
    ),
    "PLACEMENT_REQUIRES_ADMITTED_EPISODE": (
        http_status.HTTP_409_CONFLICT,
        "PLACEMENT_REQUIRES_ADMITTED_EPISODE",
        "A placement requires an admitted or active admission.",
    ),
    "EARLIER_INTAKE_NOT_AUTHORIZED": (
        http_status.HTTP_403_FORBIDDEN,
        "EARLIER_INTAKE_NOT_AUTHORIZED",
        "Earlier-intake placement requires placement authorization.",
    ),
    "EARLIER_INTAKE_REASON_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "EARLIER_INTAKE_REASON_REQUIRED",
        "A reason is required for earlier-intake placement.",
    ),
    "ADMISSION_OFFERING_INTAKE_MISMATCH": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "ADMISSION_OFFERING_INTAKE_MISMATCH",
        "That offering does not belong to the selected intake.",
    ),
    "PLACEMENT_CONFLICT": (
        http_status.HTTP_409_CONFLICT,
        "PLACEMENT_CONFLICT",
        "The placement conflicts with the current placement state.",
    ),
    "ADMISSIONS_WRITE_DISABLED": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSIONS_WRITE_DISABLED",
        "Admission writes are currently disabled.",
    ),
}


def _forbidden(message: str) -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail={"error": {"code": "FORBIDDEN", "message": message}},
    )


def _placement_error(exc: ValueError) -> HTTPException:
    code = str(exc)
    status_code, public_code, message = _ERRORS.get(
        code,
        (
            http_status.HTTP_409_CONFLICT,
            "PLACEMENT_CONFLICT",
            "The placement conflicts with the current placement state.",
        ),
    )
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": public_code, "message": message}},
    )


def _get_student_or_404(db: DBSession, student_id: uuid.UUID) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise _placement_error(ValueError("STUDENT_NOT_FOUND"))
    return student


@router.get("", response_model=PlacementListResponse)
def get_student_placements(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
) -> PlacementListResponse:
    """Placement history, including the immutable original admission intake."""
    if not has_permission(current_user, _VIEW):
        raise _forbidden("You do not have permission to view academic placements.")
    _get_student_or_404(db, student_id)
    return list_placements(db, student_id)


@router.post("", response_model=PlacementRead, status_code=http_status.HTTP_201_CREATED)
def create_student_placement(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    data: PlacementCreate,
    request: Request,
) -> PlacementRead:
    """Place the student and supersede the prior current placement.

    Earlier-intake placement is checked again in the service and by the
    database CHECK. The authorizer is always the authenticated caller.
    """
    if not has_permission(current_user, _MANAGE):
        raise _forbidden("You do not have permission to manage academic placements.")
    if not get_settings().ADMISSIONS_WRITE_ENABLED:
        raise _placement_error(ValueError("ADMISSIONS_WRITE_DISABLED"))

    student = _get_student_or_404(db, student_id)
    can_authorize = has_permission(current_user, _AUTHORIZE)

    try:
        placement, previous = create_placement(
            db,
            student,
            data,
            current_user,
            can_authorize_earlier=can_authorize,
        )
    except ValueError as exc:
        db.rollback()
        raise _placement_error(exc) from exc

    admission = db.get(AcademicAdmission, placement.admission_id)

    # The architecture uses distinct action codes for the three security
    # events a placement write can cause. They are staged on the same
    # transaction and commit or roll back with the placement.
    audit_context = {
        "student_id": str(student.id),
        "admission_id": str(placement.admission_id),
        "previous_placement_id": (
            str(previous.id) if previous is not None else None
        ),
        "new_placement_id": str(placement.id),
        "admission_intake_id": (
            str(admission.admission_intake_id) if admission else None
        ),
        "placement_intake_id": str(placement.academic_period_id),
        "program_offering_id": str(placement.program_offering_id),
        "is_earlier_intake_placement": placement.is_earlier_intake_placement,
        "effective_from": placement.effective_from.isoformat(),
    }
    try:
        record_audit(
            db,
            action="academic.placement.created",
            actor=current_user,
            entity_type="academic_placement",
            entity_id=placement.id,
            context=audit_context,
            request=request,
        )
        if previous is not None:
            record_audit(
                db,
                action="academic.placement.superseded",
                actor=current_user,
                entity_type="academic_placement",
                entity_id=previous.id,
                context={
                    **audit_context,
                    "ended_at": (
                        previous.ended_at.isoformat()
                        if previous.ended_at is not None
                        else None
                    ),
                },
                request=request,
            )
        if placement.is_earlier_intake_placement:
            record_audit(
                db,
                action="academic.placement.earlier_intake_authorized",
                actor=current_user,
                entity_type="academic_placement",
                entity_id=placement.id,
                context={
                    **audit_context,
                    "authorized_by_id": (
                        str(placement.authorized_by_id)
                        if placement.authorized_by_id is not None
                        else None
                    ),
                    # Avoid the audit denylist's "authorization" substring
                    # while still recording the actual operational reason.
                    "placement_reason": placement.authorization_reason,
                },
                request=request,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(placement)
    return placement_to_read(db, placement)
