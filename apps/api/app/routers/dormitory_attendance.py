"""Dormitory attendance endpoints.

Separate from the academic attendance router on purpose: the two domains answer
different questions and must not be able to borrow each other's permissions or
calculations.

* Admin and Management read the resident list and one resident's history, and
  record or correct an absence.
* A student reads their own history through ``/me`` and cannot reach the staff
  list at all.
* Teachers hold neither permission, so no dormitory surface is open to them.

No endpoint generates a presence record: absences are written and nothing else
is derived, so the module has no percentage, no daily sheet and no nightly job.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID annotations at runtime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.auth.dependencies import get_db
from app.models.identity import User  # noqa: TC001 - FastAPI dependency
from app.permissions.checks import require_permission
from app.schemas.dormitory_attendance import (
    DormitoryAbsenceCancel,
    DormitoryAbsenceCorrect,
    DormitoryAbsenceCreate,
    DormitoryAbsenceResult,
    DormitoryStudentDetail,
    DormitoryStudentList,
)
from app.services import dormitory_attendance as svc

router = APIRouter(prefix="/dormitory", tags=["dormitory-attendance"])

_VIEW = "attendance.view_dormitory"
_RECORD = "attendance.record_dormitory"


def _http_error(exc: svc.DormitoryError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error": {"code": exc.code, "message": str(exc)}},
    )


@router.get("/students", response_model=DormitoryStudentList)
def list_students(
    search: str | None = Query(None, max_length=200),
    residency: str = Query("all", pattern="^(all|current|former)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=svc.MAX_PAGE_SIZE),
    current_user: User = Depends(require_permission(_VIEW)),
    db: DBSession = Depends(get_db),
) -> DormitoryStudentList:
    """Students with a housing history, with their accumulated absence points."""
    try:
        svc.ensure_staff(current_user)
        return DormitoryStudentList(
            **svc.list_students(
                db,
                search=search,
                residency=residency,
                page=page,
                page_size=page_size,
            )
        )
    except svc.DormitoryError as exc:
        raise _http_error(exc) from None


@router.get("/me", response_model=DormitoryStudentDetail)
def my_dormitory(
    current_user: User = Depends(require_permission(_VIEW)),
    db: DBSession = Depends(get_db),
) -> DormitoryStudentDetail:
    """The signed-in student's own dormitory absences and points."""
    try:
        return DormitoryStudentDetail(**svc.my_dormitory(db, current_user))
    except svc.DormitoryError as exc:
        raise _http_error(exc) from None


@router.get("/students/{student_id}", response_model=DormitoryStudentDetail)
def student_detail(
    student_id: uuid.UUID,
    current_user: User = Depends(require_permission(_VIEW)),
    db: DBSession = Depends(get_db),
) -> DormitoryStudentDetail:
    """One resident: stays, absences, corrections and accumulated points."""
    try:
        svc.ensure_staff(current_user)
        return DormitoryStudentDetail(**svc.student_detail(db, student_id))
    except svc.DormitoryError as exc:
        raise _http_error(exc) from None


@router.post(
    "/students/{student_id}/absences",
    response_model=DormitoryAbsenceResult,
    status_code=http_status.HTTP_201_CREATED,
)
def record_absence(
    student_id: uuid.UUID,
    data: DormitoryAbsenceCreate,
    request: Request,
    current_user: User = Depends(require_permission(_RECORD)),
    db: DBSession = Depends(get_db),
) -> DormitoryAbsenceResult:
    """Record one dormitory absence for a resident."""
    try:
        svc.ensure_staff(current_user)
        return DormitoryAbsenceResult(
            **svc.record_absence(
                db, data, current_user, student_id=student_id, request=request
            )
        )
    except svc.DormitoryError as exc:
        raise _http_error(exc) from None


@router.post(
    "/students/{student_id}/absences/{absence_id}/corrections",
    response_model=DormitoryAbsenceResult,
    status_code=http_status.HTTP_201_CREATED,
)
def correct_absence(
    student_id: uuid.UUID,
    absence_id: uuid.UUID,
    data: DormitoryAbsenceCorrect,
    request: Request,
    current_user: User = Depends(require_permission(_RECORD)),
    db: DBSession = Depends(get_db),
) -> DormitoryAbsenceResult:
    """Supersede an absence, keeping the previous record and its points.

    A correction may name a different housing assignment from the student's own
    history — that is how a record filed against the wrong room after a transfer
    is fixed without deleting the original.
    """
    try:
        svc.ensure_staff(current_user)
        return DormitoryAbsenceResult(
            **svc.correct_absence(
                db,
                data,
                current_user,
                student_id=student_id,
                absence_id=absence_id,
                request=request,
            )
        )
    except svc.DormitoryError as exc:
        raise _http_error(exc) from None


@router.post(
    "/students/{student_id}/absences/{absence_id}/cancellations",
    response_model=DormitoryAbsenceResult,
    status_code=http_status.HTTP_201_CREATED,
)
def cancel_absence(
    student_id: uuid.UUID,
    absence_id: uuid.UUID,
    data: DormitoryAbsenceCancel,
    request: Request,
    current_user: User = Depends(require_permission(_RECORD)),
    db: DBSession = Depends(get_db),
) -> DormitoryAbsenceResult:
    """Withdraw an absence. The record stays; it stops counting."""
    try:
        svc.ensure_staff(current_user)
        return DormitoryAbsenceResult(
            **svc.cancel_absence(
                db,
                data,
                current_user,
                student_id=student_id,
                absence_id=absence_id,
                request=request,
            )
        )
    except svc.DormitoryError as exc:
        raise _http_error(exc) from None
