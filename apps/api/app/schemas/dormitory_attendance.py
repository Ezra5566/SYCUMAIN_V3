"""Dormitory attendance schemas.

Deliberately narrower than the academic attendance schemas: there is no
percentage, no eligible-day count and no commencement, because dormitory
attendance is not a ratio over a working-day calendar. What a resident has is a
list of absences, the points attached to them, and the housing stay each one
belongs to.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID at runtime
from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel, Field

#: Points are entered per absence by Management. The bound only rejects values
#: the column cannot store; it is not an institutional scale.
MAX_POINTS = 9999.99


class DormitoryAbsenceCreate(BaseModel):
    """Record a dormitory absence.

    ``housing_assignment_id`` is optional: when omitted the server resolves the
    stay that covers the date, which is the only assignment an absence may
    legitimately belong to.
    """

    absence_date: date
    points: float = Field(..., ge=0, le=MAX_POINTS)
    reason: str = Field(..., min_length=1, max_length=500)
    housing_assignment_id: uuid.UUID | None = None


class DormitoryAbsenceCorrect(BaseModel):
    """Supersede an existing absence. The previous row is kept.

    ``reason`` is both the corrected record's reason and the justification for
    the change, matching the academic correction contract: a correction always
    states why it was made.
    """

    absence_date: date
    points: float = Field(..., ge=0, le=MAX_POINTS)
    reason: str = Field(..., min_length=1, max_length=500)
    housing_assignment_id: uuid.UUID | None = None


class DormitoryAbsenceCancel(BaseModel):
    """Cancel an absence. The record stays, but stops counting.

    Cancellation is deliberately not a correction to zero points: a zero-point
    absence still says the student was absent, which is a different claim from
    "this absence should not exist". The reason is mandatory and at least ten
    characters, matching the correction contract.
    """

    reason: str = Field(..., min_length=10, max_length=500)


class DormitoryAssignmentRead(BaseModel):
    """One institutional housing stay, as attendance reads it."""

    id: uuid.UUID
    building_name: str | None = None
    floor_number: int | None = None
    room_number: str | None = None
    bed_label: str | None = None
    bed_number: int | None = None
    start_date: date
    end_date: date | None = None
    status: str
    is_current: bool
    absence_count: int
    points_total: float


class DormitoryAbsenceRead(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    housing_assignment_id: uuid.UUID
    absence_date: date
    points: float
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
    #: True when this row contributes to the accumulated figure. A superseded
    #: or cancelled row is history and counts for nothing.
    is_active: bool = True


class DormitoryStudentRow(BaseModel):
    student_id: uuid.UUID
    student_number: str
    student_name: str
    housing_assignment_id: uuid.UUID
    building_name: str | None = None
    floor_number: int | None = None
    room_number: str | None = None
    bed_label: str | None = None
    bed_number: int | None = None
    assignment_start_date: date
    assignment_end_date: date | None = None
    assignment_status: str
    is_current_resident: bool
    eligible_today: bool
    #: NO_HOUSING_ASSIGNMENT | ASSIGNMENT_NOT_STARTED | ASSIGNMENT_ENDED |
    #: BETWEEN_ASSIGNMENTS | null
    ineligible_reason: str | None = None
    absence_count: int
    points_total: float


class DormitoryStudentList(BaseModel):
    items: list[DormitoryStudentRow]
    total: int
    page: int
    page_size: int


class DormitoryStudentDetail(BaseModel):
    student_id: uuid.UUID
    student_number: str
    student_name: str
    has_assignment: bool
    is_current_resident: bool
    eligible_today: bool
    ineligible_reason: str | None = None
    current_assignment: DormitoryAssignmentRead | None = None
    assignments: list[DormitoryAssignmentRead]
    absences: list[DormitoryAbsenceRead]
    #: Current absences only. Superseded rows are history and are not counted.
    absence_count: int
    points_total: float


class DormitoryAbsenceResult(BaseModel):
    absence: DormitoryAbsenceRead
    absence_count: int
    points_total: float
