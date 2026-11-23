"""University calendar request/response schemas (Phase 1)."""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID at runtime
from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel, Field

from app.models.calendar import CalendarDayType  # noqa: TC001

# --- Exception writes ---


class CalendarExceptionCreate(BaseModel):
    """Declare one date as an exception to the weekday rule."""

    calendar_date: date
    # The full enum is accepted so the service can answer with a stable error
    # code for a derived value; a raw string still fails at the API boundary.
    day_type: CalendarDayType
    title: str = Field(..., min_length=1, max_length=200)
    reason: str = Field(..., min_length=1)


class CalendarExceptionCorrect(BaseModel):
    """Correct a live declaration, with a reason for the change itself."""

    day_type: CalendarDayType | None = None
    title: str | None = Field(None, min_length=1, max_length=200)
    reason: str | None = None
    change_reason: str = Field(..., min_length=1)


class CalendarExceptionVoid(BaseModel):
    reason: str = Field(..., min_length=1)


# --- Vacation ranges ---


class VacationRangeCreate(BaseModel):
    """An institution-entered vacation, materialised date by date."""

    start_date: date
    end_date: date
    title: str = Field(..., min_length=1, max_length=200)
    reason: str = Field(..., min_length=1)


class VacationRangeAdjust(BaseModel):
    """Extend or shorten a range; omitted bounds keep their current value."""

    start_date: date | None = None
    end_date: date | None = None
    change_reason: str = Field(..., min_length=1)


class VacationRangeCancel(BaseModel):
    reason: str = Field(..., min_length=1)


# --- Reads ---


class CalendarExceptionResponse(BaseModel):
    id: uuid.UUID
    calendar_date: date
    day_type: CalendarDayType
    title: str
    reason: str
    is_void: bool
    #: The vacation range that materialised this date, when there was one.
    calendar_range_id: uuid.UUID | None = None
    #: Set when the date was corrected individually and left its range.
    detached_from_range_at: datetime | None = None
    voided_at: datetime | None = None
    voided_by_id: uuid.UUID | None = None
    void_reason: str | None = None
    created_by_id: uuid.UUID
    updated_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CalendarExceptionListResponse(BaseModel):
    items: list[CalendarExceptionResponse]
    total: int


class VacationRangeResponse(BaseModel):
    """A range and the dates it currently owns."""

    id: uuid.UUID
    start_date: date
    end_date: date
    title: str
    reason: str
    is_cancelled: bool
    cancelled_at: datetime | None = None
    cancelled_by_id: uuid.UUID | None = None
    cancel_reason: str | None = None
    created_by_id: uuid.UUID
    updated_by_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    #: Live dates still governed by the range.
    dates: list[date]
    #: Live dates corrected individually, which cancellation leaves alone.
    detached_dates: list[date]
    #: Dates a shortening or cancellation voided; history, not live calendar.
    voided_date_count: int

    model_config = {"from_attributes": True}


class VacationRangeListResponse(BaseModel):
    items: list[VacationRangeResponse]
    total: int


class ResolvedCalendarDayResponse(BaseModel):
    """One date's classification, and where it came from."""

    calendar_date: date
    day_type: CalendarDayType
    is_working: bool
    # DEFAULT: derived from the weekday. EXCEPTION: a live declaration.
    source: str
    exception_id: uuid.UUID | None = None
    title: str | None = None

    model_config = {"from_attributes": True}


class CalendarCoverageResponse(BaseModel):
    """Coverage of a date range: the rule, the declarations and the result."""

    start_date: date
    end_date: date
    weekday_defaults: dict[str, str]
    total_days: int
    default_working_days: int
    default_non_working_days: int
    working_days: int
    non_working_days: int
    holidays: list[date]
    closures: list[date]
    exceptional_working_days: list[date]
    vacations: list[date]
    exceptions: list[CalendarExceptionResponse]
    voided_exception_count: int
    days: list[ResolvedCalendarDayResponse]
