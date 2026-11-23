"""Examination endpoints.

Authorization is enforced here and in the service, never left to the UI:

* ``exams.manage`` — create, reschedule, cancel. Admin and Management.
* ``exams.record_results`` — record and correct results. Management, plus
  teachers for the sections they are assigned to (checked per examination).
* ``exams.publish`` — publish results to students. Admin and Management only.
* ``exams.view`` — read. A student's read is scoped to their own enrollments,
  and their results exist only once published.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID annotations at runtime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.auth.dependencies import get_db
from app.models.identity import User  # noqa: TC001 - FastAPI dependency
from app.permissions.checks import require_permission
from app.schemas.examination import (
    ExaminationCancel,
    ExaminationCreate,
    ExaminationDashboard,
    ExaminationDetail,
    ExaminationList,
    ExaminationRead,
    ExaminationUpdate,
    PublicationResponse,
    ResultCorrect,
    ResultCreate,
    ResultSaveResponse,
    StudentExaminationList,
)
from app.services import examination as svc

router = APIRouter(prefix="/examinations", tags=["examinations"])

_VIEW = "exams.view"
_MANAGE = "exams.manage"
_RECORD = "exams.record_results"
_PUBLISH = "exams.publish"


def _http_error(exc: svc.ExaminationError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error": {"code": exc.code, "message": str(exc)}},
    )


@router.get("/dashboard", response_model=ExaminationDashboard)
def examination_dashboard(
    current_user: User = Depends(require_permission(_VIEW)),
    db: DBSession = Depends(get_db),
) -> ExaminationDashboard:
    """Role-scoped summary built from real rows."""
    try:
        return ExaminationDashboard(**svc.examination_dashboard(db, current_user))
    except svc.ExaminationError as exc:
        raise _http_error(exc) from None


@router.get("/me", response_model=StudentExaminationList)
def my_examinations(
    current_user: User = Depends(require_permission(_VIEW)),
    db: DBSession = Depends(get_db),
) -> StudentExaminationList:
    """The signed-in student's schedule and published results."""
    try:
        return StudentExaminationList(**svc.student_examinations(db, current_user))
    except svc.ExaminationError as exc:
        raise _http_error(exc) from None


@router.get("", response_model=ExaminationList)
def list_examinations(
    search: str | None = Query(None, max_length=200),
    period_id: uuid.UUID | None = Query(None),
    status_filter: str | None = Query(
        None, alias="status", pattern="^(SCHEDULED|CANCELLED)$"
    ),
    published: str | None = Query(None, pattern="^(published|unpublished)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=svc.MAX_PAGE_SIZE),
    current_user: User = Depends(require_permission(_VIEW)),
    db: DBSession = Depends(get_db),
) -> ExaminationList:
    """Examinations the caller may see, newest schedule first."""
    try:
        return ExaminationList(
            **svc.list_examinations(
                db,
                current_user,
                search=search,
                period_id=period_id,
                status=status_filter,
                published=published,
                page=page,
                page_size=page_size,
            )
        )
    except svc.ExaminationError as exc:
        raise _http_error(exc) from None


@router.post(
    "", response_model=ExaminationRead, status_code=http_status.HTTP_201_CREATED
)
def create_examination(
    data: ExaminationCreate,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> ExaminationRead:
    """Schedule one examination for one or more teaching sections."""
    try:
        return ExaminationRead(
            **svc.create_examination(db, data, current_user, request=request)
        )
    except svc.ExaminationError as exc:
        raise _http_error(exc) from None


@router.get("/{examination_id}", response_model=ExaminationDetail)
def get_examination(
    examination_id: uuid.UUID,
    current_user: User = Depends(require_permission(_VIEW)),
    db: DBSession = Depends(get_db),
) -> ExaminationDetail:
    """Schedule, eligible students and recorded results."""
    try:
        return ExaminationDetail(
            **svc.examination_detail(db, current_user, examination_id)
        )
    except svc.ExaminationError as exc:
        raise _http_error(exc) from None


@router.patch("/{examination_id}", response_model=ExaminationRead)
def update_examination(
    examination_id: uuid.UUID,
    data: ExaminationUpdate,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> ExaminationRead:
    """Reschedule or correct a scheduled examination."""
    try:
        return ExaminationRead(
            **svc.update_examination(
                db, examination_id, data, current_user, request=request
            )
        )
    except svc.ExaminationError as exc:
        raise _http_error(exc) from None


@router.post("/{examination_id}/cancellation", response_model=ExaminationRead)
def cancel_examination(
    examination_id: uuid.UUID,
    data: ExaminationCancel,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> ExaminationRead:
    """Cancel an examination, keeping its schedule and any results."""
    try:
        return ExaminationRead(
            **svc.cancel_examination(
                db, examination_id, data, current_user, request=request
            )
        )
    except svc.ExaminationError as exc:
        raise _http_error(exc) from None


@router.post(
    "/{examination_id}/results",
    response_model=ResultSaveResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def record_result(
    examination_id: uuid.UUID,
    data: ResultCreate,
    request: Request,
    current_user: User = Depends(require_permission(_RECORD)),
    db: DBSession = Depends(get_db),
) -> ResultSaveResponse:
    """Record one student's result for an examination."""
    try:
        return ResultSaveResponse(
            **svc.record_result(
                db, examination_id, data, current_user, request=request
            )
        )
    except svc.ExaminationError as exc:
        raise _http_error(exc) from None


@router.post(
    "/{examination_id}/results/{result_id}/corrections",
    response_model=ResultSaveResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def correct_result(
    examination_id: uuid.UUID,
    result_id: uuid.UUID,
    data: ResultCorrect,
    request: Request,
    current_user: User = Depends(require_permission(_RECORD)),
    db: DBSession = Depends(get_db),
) -> ResultSaveResponse:
    """Supersede a result, keeping the previous score readable."""
    try:
        return ResultSaveResponse(
            **svc.correct_result(
                db, examination_id, result_id, data, current_user, request=request
            )
        )
    except svc.ExaminationError as exc:
        raise _http_error(exc) from None


@router.post("/{examination_id}/publication", response_model=PublicationResponse)
def publish_results(
    examination_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission(_PUBLISH)),
    db: DBSession = Depends(get_db),
) -> PublicationResponse:
    """Publish results. Until this succeeds, no student sees a score."""
    try:
        return PublicationResponse(
            **svc.publish_results(db, examination_id, current_user, request=request)
        )
    except svc.ExaminationError as exc:
        raise _http_error(exc) from None
