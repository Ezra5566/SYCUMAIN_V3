"""Student attendance and absence endpoints (Phase 3, corrected model).

Two audiences, deliberately separated:

* staff read the student list and one student's detail, and record or correct an
  absence — scoped to their assigned sections for teachers;
* a student reads their own figure through ``/me``, and cannot reach the staff
  list at all.

No endpoint generates a daily sheet, a present row, or a percentage: absent
records are written, and everything else is derived on read.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID annotations at runtime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.auth.dependencies import get_db
from app.models.identity import User  # noqa: TC001 - FastAPI dependency
from app.permissions.checks import require_permission
from app.schemas.absence import (
    AbsenceCancel,
    AbsenceCorrect,
    AbsenceCreate,
    AbsenceRecordResult,
    MyAttendance,
    StudentAttendanceDetail,
    StudentAttendanceList,
)
from app.services import absence as svc

router = APIRouter(prefix="/attendance", tags=["attendance-absence"])

_VIEW = "attendance.view"
_RECORD = "attendance.record_absence"


def _http_error(exc: svc.AbsenceError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error": {"code": exc.code, "message": str(exc)}},
    )


@router.get("/students", response_model=StudentAttendanceList)
def list_students(
    search: str | None = Query(None, max_length=200),
    period_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=svc.MAX_PAGE_SIZE),
    current_user: User = Depends(require_permission(_VIEW)),
    db: DBSession = Depends(get_db),
) -> StudentAttendanceList:
    """Active episodes with their current attendance figure."""
    try:
        svc.ensure_staff(current_user)
        return StudentAttendanceList(
            **svc.list_students(
                db,
                current_user,
                search=search,
                period_id=period_id,
                page=page,
                page_size=page_size,
            )
        )
    except svc.AbsenceError as exc:
        raise _http_error(exc) from None


@router.get("/me", response_model=MyAttendance)
def my_attendance(
    current_user: User = Depends(require_permission(_VIEW)),
    db: DBSession = Depends(get_db),
) -> MyAttendance:
    """The signed-in student's own percentage, absence count and history."""
    try:
        return MyAttendance(**svc.my_attendance(db, current_user))
    except svc.AbsenceError as exc:
        raise _http_error(exc) from None


@router.get("/students/{student_id}", response_model=StudentAttendanceDetail)
def student_detail(
    student_id: uuid.UUID,
    current_user: User = Depends(require_permission(_VIEW)),
    db: DBSession = Depends(get_db),
) -> StudentAttendanceDetail:
    """One student: current figure and the full absence history."""
    try:
        svc.ensure_staff(current_user)
        return StudentAttendanceDetail(
            **svc.student_detail(db, current_user, student_id)
        )
    except svc.AbsenceError as exc:
        raise _http_error(exc) from None


@router.post(
    "/students/{student_id}/absences",
    response_model=AbsenceRecordResult,
    status_code=http_status.HTTP_201_CREATED,
)
def record_absence(
    student_id: uuid.UUID,
    data: AbsenceCreate,
    request: Request,
    current_user: User = Depends(require_permission(_RECORD)),
    db: DBSession = Depends(get_db),
) -> AbsenceRecordResult:
    """Record one absence against one admission episode."""
    try:
        svc.ensure_staff(current_user)
        return AbsenceRecordResult(
            **svc.record_absence(
                db, data, current_user, student_id=student_id, request=request
            )
        )
    except svc.AbsenceError as exc:
        raise _http_error(exc) from None


@router.post(
    "/students/{student_id}/absences/{absence_id}/cancellation",
    response_model=AbsenceRecordResult,
    status_code=http_status.HTTP_201_CREATED,
)
def cancel_absence(
    student_id: uuid.UUID,
    absence_id: uuid.UUID,
    data: AbsenceCancel,
    request: Request,
    current_user: User = Depends(require_permission(_RECORD)),
    db: DBSession = Depends(get_db),
) -> AbsenceRecordResult:
    """Cancel an incorrectly recorded absence, keeping the record."""
    try:
        svc.ensure_staff(current_user)
        return AbsenceRecordResult(
            **svc.cancel_absence(
                db,
                data,
                current_user,
                student_id=student_id,
                absence_id=absence_id,
                request=request,
            )
        )
    except svc.AbsenceError as exc:
        raise _http_error(exc) from None


@router.post(
    "/students/{student_id}/absences/{absence_id}/corrections",
    response_model=AbsenceRecordResult,
    status_code=http_status.HTTP_201_CREATED,
)
def correct_absence(
    student_id: uuid.UUID,
    absence_id: uuid.UUID,
    data: AbsenceCorrect,
    request: Request,
    current_user: User = Depends(require_permission(_RECORD)),
    db: DBSession = Depends(get_db),
) -> AbsenceRecordResult:
    """Supersede an absence, keeping the previous record."""
    try:
        svc.ensure_staff(current_user)
        return AbsenceRecordResult(
            **svc.correct_absence(
                db,
                data,
                current_user,
                student_id=student_id,
                absence_id=absence_id,
                request=request,
            )
        )
    except svc.AbsenceError as exc:
        raise _http_error(exc) from None
