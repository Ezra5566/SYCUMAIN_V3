"""Student attendance and absence schemas (Phase 3, corrected model)."""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID at runtime
from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel, Field


class AbsenceCreate(BaseModel):
    """Record an absence against one admission episode.

    The episode is named explicitly: a student may have more than one episode,
    and an absence belongs to exactly one of them.
    """

    admission_id: uuid.UUID
    absence_date: date
    reason: str = Field(..., min_length=1, max_length=500)


class AbsenceCorrect(BaseModel):
    """Supersede an existing absence. A reason is mandatory."""

    absence_date: date
    reason: str = Field(..., min_length=1, max_length=500)


class AbsenceCancel(BaseModel):
    """Cancel an absence without deleting it. A reason is mandatory.

    Cancellation is deliberately a different operation from correction: the
    date was wrong (correction) is not the same claim as the absence should not
    exist at all (cancellation).
    """

    reason: str = Field(..., min_length=1, max_length=500)


class AbsenceRead(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    admission_id: uuid.UUID
    absence_date: date
    reason: str
    recorded_by_id: uuid.UUID
    recorded_by_name: str | None = None
    recorded_at: datetime
    supersedes_id: uuid.UUID | None = None
    superseded_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancelled_by_id: uuid.UUID | None = None
    cancelled_by_name: str | None = None
    cancellation_reason: str | None = None


class AttendanceCalculation(BaseModel):
    """The derived figure for one episode, never stored.

    ``percentage`` is ``null`` when no eligible working day has elapsed yet:
    a commencement in the future has no percentage, and reporting 100% there
    would be a claim the institution has not earned.
    """

    commencement_date: date | None = None
    window_start: date | None = None
    window_end: date | None = None
    calculation_date: date
    eligible_days: int
    absence_count: int
    #: Current absences inside the window whose date the calendar no longer
    #: treats as a working day. Kept in the history, excluded from the figure.
    excluded_absence_count: int = 0
    percentage: float | None = None


class StudentAttendanceRow(BaseModel):
    student_id: uuid.UUID
    student_number: str
    student_name: str
    admission_id: uuid.UUID
    admission_status: str
    period_id: uuid.UUID
    period_name: str
    commencement_date: date | None = None
    eligible: bool
    #: NO_ACTIVE_ADMISSION | NO_COMMENCEMENT | NOT_STARTED | null
    ineligible_reason: str | None = None
    eligible_days: int
    absence_count: int
    excluded_absence_count: int = 0
    percentage: float | None = None


class StudentAttendanceList(BaseModel):
    items: list[StudentAttendanceRow]
    total: int
    page: int
    page_size: int


class StudentAttendanceDetail(StudentAttendanceRow):
    absences: list[AbsenceRead]


class EpisodeAttendance(BaseModel):
    """One episode as the student themselves sees it."""

    admission_id: uuid.UUID
    admission_status: str
    period_name: str
    commencement_date: date | None = None
    eligible: bool
    eligible_days: int
    absence_count: int
    excluded_absence_count: int = 0
    percentage: float | None = None
    absences: list[AbsenceRead]


class MyAttendance(BaseModel):
    student_id: uuid.UUID
    student_number: str
    student_name: str
    episodes: list[EpisodeAttendance]


class AbsenceRecordResult(BaseModel):
    absence: AbsenceRead
    calculation: AttendanceCalculation
