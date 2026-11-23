"""Controlled admission/programme change endpoints (Phase 4)."""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID at runtime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import record_audit
from app.auth.dependencies import CurrentUser  # noqa: TC001 - FastAPI dependency
from app.config.settings import get_settings
from app.database.session import get_db
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionChange,
    AdmissionChangeType,
)
from app.permissions.checks import has_permission
from app.schemas.admission import (
    AdmissionChangeCreate,
    AdmissionChangeListResponse,
    AdmissionChangeRead,
    AdmissionChangeReview,
    AdmissionListResponse,
)
from app.services.admission import admission_to_read, list_admissions
from app.services.admission_change import (
    change_to_read,
    list_admission_changes,
    request_admission_change,
    request_self_service_change,
    review_admission_change,
)
from app.services.student import get_student, get_student_by_user_id

if TYPE_CHECKING:
    from app.models.identity import Student

router = APIRouter(tags=["admission changes"])

_VIEW = "academic.view_admissions"
_MANAGE = "academic.manage_admissions"
_APPROVE = "academic.approve_admission_change"
_AUTHORIZE = "academic.authorize_placement"
_CORRECT_STATUS = "academic.correct_admission_status"
_TERMINAL_STATUSES = {"COMPLETED", "WITHDRAWN", "CANCELLED"}

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
    "CHANGE_REQUEST_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "CHANGE_REQUEST_NOT_FOUND",
        "Change request not found.",
    ),
    "CHANGE_ALREADY_REVIEWED": (
        http_status.HTTP_409_CONFLICT,
        "CHANGE_ALREADY_REVIEWED",
        "This change request has already been decided.",
    ),
    "CHANGE_REQUEST_PENDING_EXISTS": (
        http_status.HTTP_409_CONFLICT,
        "CHANGE_REQUEST_PENDING_EXISTS",
        "A pending request of this type already exists for the admission.",
    ),
    "CHANGE_REQUEST_STALE": (
        http_status.HTTP_409_CONFLICT,
        "CHANGE_REQUEST_STALE",
        "The admission changed after this request was made. Submit a new request.",
    ),
    "CHANGE_REQUEST_CONFLICT": (
        http_status.HTTP_409_CONFLICT,
        "CHANGE_REQUEST_CONFLICT",
        "The change request conflicts with the current admission state.",
    ),
    "SELF_APPROVAL_FORBIDDEN": (
        http_status.HTTP_403_FORBIDDEN,
        "SELF_APPROVAL_FORBIDDEN",
        "You cannot approve or reject your own change request.",
    ),
    "ADMISSION_TERMINAL": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_TERMINAL",
        "A completed, withdrawn or cancelled admission cannot be changed. "
        "Record a new admission instead.",
    ),
    "ADMISSION_TRANSITION_NOT_ALLOWED": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_TRANSITION_NOT_ALLOWED",
        "That status transition is not allowed for this admission.",
    ),
    "PROGRAM_CHANGE_TARGET_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROGRAM_CHANGE_TARGET_REQUIRED",
        "Select the programme the student is changing to.",
    ),
    "PROGRAM_CHANGE_TARGET_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "PROGRAM_CHANGE_TARGET_NOT_FOUND",
        "The selected programme was not found.",
    ),
    "PROGRAM_CHANGE_TARGET_INACTIVE": (
        http_status.HTTP_409_CONFLICT,
        "PROGRAM_CHANGE_TARGET_INACTIVE",
        "The selected programme is not active.",
    ),
    "PROGRAM_CHANGE_SAME_PROGRAM": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROGRAM_CHANGE_SAME_PROGRAM",
        "The selected programme is already the current programme.",
    ),
    "PROGRAM_CHANGE_OFFERING_INTAKE_MISMATCH": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROGRAM_CHANGE_OFFERING_INTAKE_MISMATCH",
        "A programme change offering must belong to the existing admission intake.",
    ),
    "PROGRAM_CHANGE_OFFERING_MISMATCH": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROGRAM_CHANGE_OFFERING_MISMATCH",
        "The selected offering does not belong to the selected programme.",
    ),
    "PLACEMENT_OFFERING_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PLACEMENT_OFFERING_REQUIRED",
        "Select a programme offering for the placement change.",
    ),
    "PLACEMENT_REQUIRES_ADMITTED_EPISODE": (
        http_status.HTTP_409_CONFLICT,
        "PLACEMENT_REQUIRES_ADMITTED_EPISODE",
        "A placement change requires an admitted or active admission.",
    ),
    "PROGRAM_OFFERING_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "PROGRAM_OFFERING_NOT_FOUND",
        "Program offering not found.",
    ),
    "PROGRAM_OFFERING_NOT_MAPPED": (
        http_status.HTTP_409_CONFLICT,
        "PROGRAM_OFFERING_NOT_MAPPED",
        "That source offering has not been mapped to a canonical programme.",
    ),
    "ADMISSION_INTAKE_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "ADMISSION_INTAKE_NOT_FOUND",
        "Intake not found.",
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
    "CHANGE_REASON_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "CHANGE_REASON_REQUIRED",
        "A reason is required for this change request.",
    ),
    "EARLIER_INTAKE_REASON_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "EARLIER_INTAKE_REASON_REQUIRED",
        "A reason is required for earlier-intake placement.",
    ),
    "USE_EARLIER_INTAKE_PLACEMENT": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "USE_EARLIER_INTAKE_PLACEMENT",
        "That intake starts earlier than the admission. Use the earlier-intake placement request.",
    ),
    "NOT_EARLIER_INTAKE_PLACEMENT": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "NOT_EARLIER_INTAKE_PLACEMENT",
        "That offering is not in an earlier intake.",
    ),
    "EARLIER_INTAKE_NOT_AUTHORIZED": (
        http_status.HTTP_403_FORBIDDEN,
        "EARLIER_INTAKE_NOT_AUTHORIZED",
        "Earlier-intake placement requires placement authorization.",
    ),
    "CHANGE_PROPOSED_STATUS_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "CHANGE_PROPOSED_STATUS_REQUIRED",
        "Select the corrected admission status.",
    ),
    "CHANGE_PROPOSED_STATUS_INVALID": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "CHANGE_PROPOSED_STATUS_INVALID",
        "That corrected status is not valid for this admission.",
    ),
    "ADMISSION_CORRECTION_UNCHANGED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "ADMISSION_CORRECTION_UNCHANGED",
        "Select a status different from the recorded status.",
    ),
    "ADMISSION_CORRECTIONS_DISABLED": (
        http_status.HTTP_403_FORBIDDEN,
        "ADMISSION_CORRECTIONS_DISABLED",
        "Admission corrections are currently disabled.",
    ),
    "ADMISSION_ALREADY_ACTIVE": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_ALREADY_ACTIVE",
        "The student already has an active admission. End it before activating another.",
    ),
    "ADMISSION_MUST_BE_PENDING": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_MUST_BE_PENDING",
        "The student already has an active admission. A future admission may only be pending.",
    ),
    "ADMISSION_INTAKE_ALREADY_LIVE": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_INTAKE_ALREADY_LIVE",
        "This student already has a live admission for that intake.",
    ),
    "NO_ADMISSION_EPISODE": (
        http_status.HTTP_409_CONFLICT,
        "NO_ADMISSION_EPISODE",
        "A programme change requires a live admission episode.",
    ),
    "CHANGE_TYPE_INVALID": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "CHANGE_TYPE_INVALID",
        "That change type is not supported.",
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


def _change_error(exc: ValueError) -> HTTPException:
    code = str(exc)
    status_code, public_code, message = _ERRORS.get(
        code,
        (
            http_status.HTTP_409_CONFLICT,
            "CHANGE_REQUEST_CONFLICT",
            "The change request conflicts with the current admission state.",
        ),
    )
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": public_code, "message": message}},
    )


def _require_flag() -> None:
    if not get_settings().ADMISSION_CHANGE_REQUESTS_ENABLED:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "CHANGE_REQUESTS_DISABLED",
                    "message": "Admission change requests are currently disabled.",
                }
            },
        )
    if not get_settings().ADMISSIONS_WRITE_ENABLED:
        raise _change_error(ValueError("ADMISSIONS_WRITE_DISABLED"))


def _require_corrections_enabled() -> None:
    if not get_settings().ADMISSION_CORRECTIONS_ENABLED:
        raise _change_error(ValueError("ADMISSION_CORRECTIONS_DISABLED"))


def _student_or_404(db: DBSession, student_id: uuid.UUID) -> Student:
    student = get_student(db, student_id)
    if student is None:
        raise _change_error(ValueError("STUDENT_NOT_FOUND"))
    return student


def _can_view(current_user, student: Student) -> bool:  # noqa: ANN001
    return current_user.id == student.user_id or has_permission(current_user, _VIEW)


def _audit_request(
    db: DBSession,
    *,
    change: AcademicAdmissionChange,
    student_id: uuid.UUID,
    actor,
    request: Request,
    source: str,
) -> None:
    record_audit(
        db,
        action="academic.admission.change_requested",
        actor=actor,
        entity_type="academic_admission_change",
        entity_id=change.id,
        context={
            "student_id": str(student_id),
            "admission_id": str(change.admission_id),
            "change_type": change.change_type,
            "from_program_id": (
                str(change.from_program_id)
                if change.from_program_id is not None
                else None
            ),
            "to_program_id": (
                str(change.to_program_id) if change.to_program_id is not None else None
            ),
            "source": source,
        },
        request=request,
    )


@router.get(
    "/students/me/admission-changes",
    response_model=AdmissionChangeListResponse,
)
def list_own_admission_changes(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
) -> AdmissionChangeListResponse:
    """A student can read the status and history of their own requests."""
    student = get_student_by_user_id(db, current_user.id)
    if student is None:
        raise _change_error(ValueError("STUDENT_NOT_FOUND"))
    items = list_admission_changes(db, student.id)
    return AdmissionChangeListResponse(
        items=[change_to_read(db, item) for item in items],
        total=len(items),
    )


@router.get("/students/me/admission-episodes", response_model=AdmissionListResponse)
def list_own_admissions(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
) -> AdmissionListResponse:
    """A student's own episode timeline, including the original programme."""
    student = get_student_by_user_id(db, current_user.id)
    if student is None:
        raise _change_error(ValueError("STUDENT_NOT_FOUND"))
    episodes = list_admissions(db, student.id)
    return AdmissionListResponse(
        items=[admission_to_read(db, episode) for episode in episodes],
        total=len(episodes),
    )


@router.get(
    "/students/{student_id}/admission-changes",
    response_model=AdmissionChangeListResponse,
)
def list_student_admission_changes(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
) -> AdmissionChangeListResponse:
    """The programme-change timeline for every episode of one student."""
    student = _student_or_404(db, student_id)
    if not _can_view(current_user, student):
        raise _forbidden("You do not have permission to view admission changes.")
    items = list_admission_changes(db, student.id)
    return AdmissionChangeListResponse(
        items=[change_to_read(db, item) for item in items],
        total=len(items),
    )


@router.get(
    "/students/{student_id}/admissions/{admission_id}/changes",
    response_model=AdmissionChangeListResponse,
)
def list_episode_changes(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
) -> AdmissionChangeListResponse:
    """The change history of one episode, without parsing the audit log."""
    student = _student_or_404(db, student_id)
    if not _can_view(current_user, student):
        raise _forbidden("You do not have permission to view admission changes.")
    items = list_admission_changes(db, student.id, admission_id=admission_id)
    return AdmissionChangeListResponse(
        items=[change_to_read(db, item) for item in items],
        total=len(items),
    )


@router.post(
    "/students/me/admission-changes",
    response_model=AdmissionChangeRead,
    status_code=http_status.HTTP_201_CREATED,
)
def request_own_admission_change(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    data: AdmissionChangeCreate,
    request: Request,
) -> AdmissionChangeRead:
    """A student requests a programme change; nothing is applied immediately."""
    _require_flag()
    if data.change_type is not AdmissionChangeType.PROGRAM_CHANGE:
        raise _change_error(ValueError("CHANGE_TYPE_INVALID"))

    student = get_student_by_user_id(db, current_user.id)
    if student is None:
        raise _change_error(ValueError("STUDENT_NOT_FOUND"))

    try:
        change = request_self_service_change(
            db,
            student,
            to_program_id=data.to_program_id,
            to_program_offering_id=data.to_program_offering_id,
            actor=current_user,
            reason=data.reason,
        )
        _audit_request(
            db,
            change=change,
            student_id=student.id,
            actor=current_user,
            request=request,
            source="SELF_SERVICE",
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _change_error(exc) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(change)
    return change_to_read(db, change)


@router.post(
    "/students/{student_id}/admissions/{admission_id}/changes",
    response_model=AdmissionChangeRead,
    status_code=http_status.HTTP_201_CREATED,
)
def request_student_admission_change(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    data: AdmissionChangeCreate,
    request: Request,
) -> AdmissionChangeRead:
    """Staff request a controlled change on an existing episode."""
    if not has_permission(current_user, _MANAGE):
        raise _forbidden("You do not have permission to manage admission changes.")
    _require_flag()
    if data.change_type is AdmissionChangeType.STATUS_CORRECTION:
        admission_ref = db.get(AcademicAdmission, admission_id)
        if (
            admission_ref is not None
            and admission_ref.student_id == student_id
            and admission_ref.status in _TERMINAL_STATUSES
        ):
            _require_corrections_enabled()
    student = _student_or_404(db, student_id)

    try:
        change = request_admission_change(
            db, student, admission_id, data, current_user
        )
        _audit_request(
            db,
            change=change,
            student_id=student.id,
            actor=current_user,
            request=request,
            source="STAFF",
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _change_error(exc) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(change)
    return change_to_read(db, change)


@router.post(
    "/academic/admission-changes/{change_id}/review",
    response_model=AdmissionChangeRead,
)
def review_admission_change_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    change_id: uuid.UUID,
    data: AdmissionChangeReview,
    request: Request,
) -> AdmissionChangeRead:
    """One Admin or Management decision; no second approval is required."""
    if not has_permission(current_user, _APPROVE):
        raise _forbidden("You do not have permission to review admission changes.")
    _require_flag()

    candidate = db.get(AcademicAdmissionChange, change_id)
    if (
        candidate is not None
        and candidate.change_type == AdmissionChangeType.STATUS_CORRECTION.value
    ):
        admission_ref = db.get(AcademicAdmission, candidate.admission_id)
        if admission_ref is not None and admission_ref.status in _TERMINAL_STATUSES:
            if not has_permission(current_user, _CORRECT_STATUS):
                raise _forbidden(
                    "Only an administrator may approve a terminal status correction."
                )
            _require_corrections_enabled()

    try:
        change = review_admission_change(
            db,
            change_id,
            data,
            current_user,
            can_authorize_earlier=has_permission(current_user, _AUTHORIZE),
            request=request,
        )
        record_audit(
            db,
            action=(
                "academic.admission.change_approved"
                if data.decision == "APPROVE"
                else "academic.admission.change_rejected"
            ),
            actor=current_user,
            entity_type="academic_admission_change",
            entity_id=change.id,
            context={
                "admission_id": str(change.admission_id),
                "change_type": change.change_type,
                "decision": data.decision,
                "from_program_id": (
                    str(change.from_program_id)
                    if change.from_program_id is not None
                    else None
                ),
                "to_program_id": (
                    str(change.to_program_id)
                    if change.to_program_id is not None
                    else None
                ),
                "decision_reason": change.decision_reason,
            },
            request=request,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _change_error(exc) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(change)
    return change_to_read(db, change)
