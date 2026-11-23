"""Attendance commencement schemas (Phase 2)."""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID at runtime
from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel, Field

from app.models.attendance import AttendanceCommencementType  # noqa: TC001


class CommencementApprove(BaseModel):
    """Approve a commencement for one admission episode.

    ``confirmed_suggested_date`` is the explicit confirmation: the approver must
    echo the suggestion they reviewed. If the suggestion has changed in the
    meantime (an intake date correction, for example), the request is refused
    rather than silently accepting a stale screen.
    """

    commencement_date: date
    commencement_type: AttendanceCommencementType = AttendanceCommencementType.SCHEDULED
    reason: str = Field(..., min_length=1)
    confirmed_suggested_date: date


class CommencementCorrect(BaseModel):
    """Supersede the current commencement with a corrected one."""

    commencement_date: date
    commencement_type: AttendanceCommencementType = AttendanceCommencementType.SCHEDULED
    reason: str = Field(..., min_length=1)
    confirmed_suggested_date: date


class CommencementRead(BaseModel):
    id: uuid.UUID
    admission_id: uuid.UUID
    student_id: uuid.UUID
    commencement_date: date
    commencement_type: AttendanceCommencementType
    reason: str
    suggested_date: date
    supersedes_id: uuid.UUID | None = None
    superseded_at: datetime | None = None
    approved_by_id: uuid.UUID
    approved_by_name: str | None = None
    approved_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class CommencementSummary(BaseModel):
    """One episode: the suggestion, the current record and the whole history."""

    admission_id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    student_number: str
    admission_status: str
    intake_id: uuid.UUID
    intake_name: str
    intake_start_date: date
    activated_on: date | None = None
    suggested_date: date
    #: INTAKE_START or ACTIVATION — which of the two dates set the suggestion.
    suggestion_basis: str
    current: CommencementRead | None = None
    history: list[CommencementRead]


class CommencementListItem(CommencementSummary):
    pass


class CommencementListResponse(BaseModel):
    items: list[CommencementListItem]
    total: int
    page: int
    page_size: int
