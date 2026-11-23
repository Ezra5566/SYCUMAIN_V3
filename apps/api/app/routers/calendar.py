"""University working-day calendar endpoints (Phase 1).

Administration is restricted to `attendance.manage_calendar`, which Admin and
Management hold. Teachers record section registers; they do not decide which
days the institution works, and a student never sees the calendar's internal
audit detail because they cannot reach these routes at all.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID annotations at runtime
from datetime import date  # noqa: TC003

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.auth.dependencies import get_db
from app.models.identity import User  # noqa: TC001 - FastAPI dependency
from app.permissions.checks import require_permission
from app.schemas.calendar import (
    CalendarCoverageResponse,
    CalendarExceptionCorrect,
    CalendarExceptionCreate,
    CalendarExceptionListResponse,
    CalendarExceptionResponse,
    CalendarExceptionVoid,
    ResolvedCalendarDayResponse,
    VacationRangeAdjust,
    VacationRangeCancel,
    VacationRangeCreate,
    VacationRangeListResponse,
    VacationRangeResponse,
)
from app.services import calendar as svc

router = APIRouter(prefix="/academics/calendar", tags=["calendar"])

_MANAGE = "attendance.manage_calendar"


def _http_error(exc: svc.CalendarError) -> HTTPException:
    """Map a calendar refusal to the stable API error envelope."""
    return HTTPException(
        status_code=exc.status_code,
        detail={"error": {"code": exc.code, "message": str(exc)}},
    )


# ── Resolution and coverage ──


@router.get("/resolve", response_model=ResolvedCalendarDayResponse)
def resolve_calendar_day(
    day: date,
    _user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> ResolvedCalendarDayResponse:
    """Classify one date: the weekday rule, or a live declaration."""
    try:
        resolved = svc.resolve_date(db, day)
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    return ResolvedCalendarDayResponse.model_validate(resolved)


@router.get("/coverage", response_model=CalendarCoverageResponse)
def calendar_coverage(
    start_date: date,
    end_date: date,
    _user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> CalendarCoverageResponse:
    """Report the default weekday rules, declared exceptions and their result."""
    try:
        coverage = svc.build_coverage(db, start_date, end_date)
    except svc.CalendarError as exc:
        raise _http_error(exc) from None

    return CalendarCoverageResponse(
        **{key: value for key, value in coverage.items() if key not in {"days", "exceptions"}},
        days=[
            ResolvedCalendarDayResponse.model_validate(day) for day in coverage["days"]
        ],
        exceptions=[
            CalendarExceptionResponse.model_validate(exception)
            for exception in coverage["exceptions"]
        ],
    )


# ── Vacation ranges ──


@router.get("/vacation-ranges", response_model=VacationRangeListResponse)
def list_vacation_ranges(
    start_date: date | None = None,
    end_date: date | None = None,
    include_cancelled: bool = False,
    _user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> VacationRangeListResponse:
    """List institution-entered vacations, with the dates each one owns."""
    try:
        ranges = svc.list_vacation_ranges(
            db,
            start_date=start_date,
            end_date=end_date,
            include_cancelled=include_cancelled,
        )
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    items = [svc.vacation_range_to_read(db, range_) for range_ in ranges]
    return VacationRangeListResponse(items=items, total=len(items))


@router.post(
    "/vacation-ranges",
    response_model=VacationRangeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_vacation_range(
    data: VacationRangeCreate,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> VacationRangeResponse:
    """Enter a vacation range. Every date is materialised in one transaction."""
    try:
        range_ = svc.create_vacation_range(db, data, current_user, request=request)
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    return VacationRangeResponse.model_validate(
        svc.vacation_range_to_read(db, range_)
    )


@router.get("/vacation-ranges/{range_id}", response_model=VacationRangeResponse)
def get_vacation_range(
    range_id: uuid.UUID,
    _user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> VacationRangeResponse:
    """Read one vacation range, including a cancelled one, for inspection."""
    try:
        range_ = svc.get_vacation_range(db, range_id)
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    return VacationRangeResponse.model_validate(
        svc.vacation_range_to_read(db, range_)
    )


@router.patch("/vacation-ranges/{range_id}", response_model=VacationRangeResponse)
def adjust_vacation_range(
    range_id: uuid.UUID,
    data: VacationRangeAdjust,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> VacationRangeResponse:
    """Extend or shorten a range; removed dates are voided, never deleted."""
    try:
        range_ = svc.adjust_vacation_range(
            db, data, current_user, range_id=range_id, request=request
        )
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    return VacationRangeResponse.model_validate(
        svc.vacation_range_to_read(db, range_)
    )


@router.post(
    "/vacation-ranges/{range_id}/cancellation",
    response_model=VacationRangeResponse,
)
def cancel_vacation_range(
    range_id: uuid.UUID,
    data: VacationRangeCancel,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> VacationRangeResponse:
    """Cancel a range and void the dates it still owns, transactionally."""
    try:
        range_ = svc.cancel_vacation_range(
            db, data, current_user, range_id=range_id, request=request
        )
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    return VacationRangeResponse.model_validate(
        svc.vacation_range_to_read(db, range_)
    )


# ── Exceptions ──


@router.get("/days", response_model=CalendarExceptionListResponse)
def list_calendar_days(
    start_date: date | None = None,
    end_date: date | None = None,
    include_voided: bool = False,
    _user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> CalendarExceptionListResponse:
    """List declared exceptions. Voided ones are history, not live calendar."""
    try:
        items = svc.list_exceptions(
            db,
            start_date=start_date,
            end_date=end_date,
            include_voided=include_voided,
        )
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    return CalendarExceptionListResponse(items=items, total=len(items))


@router.get("/days/{exception_id}", response_model=CalendarExceptionResponse)
def get_calendar_day(
    exception_id: uuid.UUID,
    _user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> CalendarExceptionResponse:
    """Read one declaration, including a voided one, for inspection."""
    try:
        exception = svc.get_exception(db, exception_id)
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    return CalendarExceptionResponse.model_validate(exception)


@router.post(
    "/days",
    response_model=CalendarExceptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_calendar_day(
    data: CalendarExceptionCreate,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> CalendarExceptionResponse:
    """Declare a holiday, a closure or an exceptional working day."""
    try:
        exception = svc.create_exception(db, data, current_user, request=request)
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    return CalendarExceptionResponse.model_validate(exception)


@router.patch("/days/{exception_id}", response_model=CalendarExceptionResponse)
def correct_calendar_day(
    exception_id: uuid.UUID,
    data: CalendarExceptionCorrect,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> CalendarExceptionResponse:
    """Correct a live declaration; the previous values stay in the audit log."""
    try:
        exception = svc.correct_exception(
            db, data, current_user, exception_id=exception_id, request=request
        )
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    return CalendarExceptionResponse.model_validate(exception)


@router.post("/days/{exception_id}/void", response_model=CalendarExceptionResponse)
def void_calendar_day(
    exception_id: uuid.UUID,
    data: CalendarExceptionVoid,
    request: Request,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: DBSession = Depends(get_db),
) -> CalendarExceptionResponse:
    """Void a declaration. The date falls back to its weekday rule; the row stays."""
    try:
        exception = svc.void_exception(
            db, data, current_user, exception_id=exception_id, request=request
        )
    except svc.CalendarError as exc:
        raise _http_error(exc) from None
    return CalendarExceptionResponse.model_validate(exception)
