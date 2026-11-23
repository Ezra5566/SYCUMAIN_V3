"""Attendance commencement endpoints (Phase 2).

Admin and Management approve a commencement independently; there is no second
approver. Teachers and students cannot read or write these records — a
commencement is an institutional decision about the student, not part of their
own record view, and the endpoints expose approval reasons and actor names.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID annotations at runtime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.auth.dependencies import get_db
from app.models.identity import User  # noqa: TC001 - FastAPI dependency
from app.permissions.checks import require_permission
from app.schemas.commencement import (
    CommencementApprove,
    CommencementCorrect,
    CommencementListResponse,
    CommencementRead,
    CommencementSummary,
)
from app.services import commencement as svc

router = APIRouter(prefix="/attendance", tags=["attendance-commencement"])

_MANAGE = "attendance.manage_commencement"


def _http_error(exc: svc.CommencementError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error": {"code": exc.code, "message": str(exc)}},
    )


def _read(db: DBSession, record) -> CommencementRead:
    names = svc.actor_names(db, [record])
    return CommencementRead.model_validate(svc.record_to_read(record, names))


@router.get("/commencements", response_model=CommencementListResponse)
def list_commencements(
    status: Literal["MISSING", "RECORDED", "ALL"] = Query(
        "MISSING",
        description="Filter by whether the active episode already has a commencement.",
    ),
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    _user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> CommencementListResponse:
    """Active episodes with their suggested date and commencement state."""
    try:
        return CommencementListResponse(
            **svc.list_commencements(
                db, status=status, search=search, page=page, page_size=page_size
            )
        )
    except svc.CommencementError as exc:
        raise _http_error(exc) from None


@router.get(
    "/students/{student_id}/admissions/{admission_id}/commencement",
    response_model=CommencementSummary,
)
def get_commencement(
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    _user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> CommencementSummary:
    """The suggestion, the current commencement and its superseded history."""
    try:
        return CommencementSummary.model_validate(
            svc.get_summary(db, student_id=student_id, admission_id=admission_id)
        )
    except svc.CommencementError as exc:
        raise _http_error(exc) from None


@router.post(
    "/students/{student_id}/admissions/{admission_id}/commencement",
    response_model=CommencementRead,
    status_code=http_status.HTTP_201_CREATED,
)
def approve_commencement(
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    data: CommencementApprove,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> CommencementRead:
    """Approve a commencement date the approver has explicitly confirmed."""
    try:
        record = svc.approve_commencement(
            db,
            data,
            current_user,
            student_id=student_id,
            admission_id=admission_id,
            request=request,
        )
    except svc.CommencementError as exc:
        raise _http_error(exc) from None
    return _read(db, record)


@router.post(
    "/students/{student_id}/admissions/{admission_id}/commencement/corrections",
    response_model=CommencementRead,
    status_code=http_status.HTTP_201_CREATED,
)
def correct_commencement(
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    data: CommencementCorrect,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> CommencementRead:
    """Supersede the current commencement, keeping the previous record."""
    try:
        record = svc.correct_commencement(
            db,
            data,
            current_user,
            student_id=student_id,
            admission_id=admission_id,
            request=request,
        )
    except svc.CommencementError as exc:
        raise _http_error(exc) from None
    return _read(db, record)
