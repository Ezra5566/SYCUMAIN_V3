"""Examination schemas.

Two response shapes on purpose:

* the **staff** shape carries eligible students, recorded results, recorder
  names and correction history;
* the **student** shape carries the schedule and — only once the examination is
  published — the student's own score.

They are separate models rather than one model with optional fields, so an
unpublished result cannot leak into a student response by forgetting a flag.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID at runtime
from datetime import date, datetime, time  # noqa: TC003
from typing import Literal  # noqa: TC003

from pydantic import BaseModel, Field

from app.models.academic import AssessmentType

#: Score ceiling bound, matching the ``NUMERIC(6,2)`` column. This is a storage
#: limit, not an institutional pass mark or grading scale.
MAX_SCORE = 9999.99

MIN_REASON_LENGTH = 10

ExaminationTypeLiteral = AssessmentType


class ExaminationSectionRead(BaseModel):
    """One teaching section sitting an examination."""

    class_section_id: uuid.UUID
    section_code: str | None = None
    label: str
    course_code: str | None = None
    course_name: str | None = None
    academic_period_name: str | None = None
    #: Programme offerings this section serves. A shared section may serve
    #: more than one, which is exactly why the examination's own offering is
    #: validated against this list.
    offerings: list[str] = Field(default_factory=list)
    eligible_count: int = 0


class ExaminationRead(BaseModel):
    id: uuid.UUID
    title: str
    examination_type: str
    course_id: uuid.UUID
    course_code: str | None = None
    course_name: str | None = None
    academic_period_id: uuid.UUID
    academic_period_name: str | None = None
    program_offering_id: uuid.UUID | None = None
    program_offering_name: str | None = None

    exam_date: date
    start_time: time
    end_time: time
    location: str | None = None
    instructions: str | None = None
    max_score: float | None = None
    #: SCHEDULED | CANCELLED
    status: str
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None

    published_at: datetime | None = None
    published_by_name: str | None = None

    sections: list[ExaminationSectionRead] = Field(default_factory=list)
    section_count: int = 0
    eligible_count: int = 0
    result_count: int = 0

    created_at: datetime


class ExaminationList(BaseModel):
    items: list[ExaminationRead]
    total: int
    page: int
    page_size: int


class ExaminationCreate(BaseModel):
    """Create a scheduled examination.

    ``section_ids`` is required and non-empty: an examination that belongs to no
    teaching section has nobody eligible to sit it, so it would be a schedule
    with no meaning.
    """

    title: str = Field(..., min_length=1, max_length=200)
    examination_type: ExaminationTypeLiteral
    course_id: uuid.UUID
    academic_period_id: uuid.UUID
    program_offering_id: uuid.UUID | None = None
    exam_date: date
    start_time: time
    end_time: time
    location: str | None = Field(None, max_length=200)
    instructions: str | None = Field(None, max_length=4000)
    max_score: float | None = Field(None, gt=0, le=MAX_SCORE)
    section_ids: list[uuid.UUID] = Field(..., min_length=1)


class ExaminationUpdate(BaseModel):
    """Reschedule or correct an examination. Every field is optional."""

    title: str | None = Field(None, min_length=1, max_length=200)
    examination_type: ExaminationTypeLiteral | None = None
    course_id: uuid.UUID | None = None
    academic_period_id: uuid.UUID | None = None
    program_offering_id: uuid.UUID | None = None
    exam_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(None, max_length=200)
    instructions: str | None = Field(None, max_length=4000)
    max_score: float | None = Field(None, gt=0, le=MAX_SCORE)
    section_ids: list[uuid.UUID] | None = Field(None, min_length=1)


class ExaminationCancel(BaseModel):
    reason: str = Field(..., min_length=MIN_REASON_LENGTH, max_length=500)


class EligibleStudentRead(BaseModel):
    student_id: uuid.UUID
    student_number: str
    student_name: str
    #: The offering of the student's current placement, when one exists.
    program_offering_name: str | None = None
    section_labels: list[str] = Field(default_factory=list)
    #: True once a live result exists for this examination.
    has_result: bool = False


class ExaminationResultRead(BaseModel):
    id: uuid.UUID
    examination_id: uuid.UUID
    student_id: uuid.UUID
    student_number: str | None = None
    student_name: str | None = None
    score: float
    letter_grade: str | None = None
    note: str | None = None
    recorded_by_id: uuid.UUID
    recorded_by_name: str | None = None
    recorded_at: datetime
    supersedes_id: uuid.UUID | None = None
    superseded_at: datetime | None = None
    correction_reason: str | None = None
    is_current: bool = True


class ExaminationDetail(BaseModel):
    """Staff view: the schedule plus who may sit it and what has been recorded."""

    examination: ExaminationRead
    eligible_students: list[EligibleStudentRead]
    results: list[ExaminationResultRead]


class ResultCreate(BaseModel):
    student_id: uuid.UUID
    score: float = Field(..., ge=0, le=MAX_SCORE)
    letter_grade: str | None = Field(None, max_length=5)
    note: str | None = Field(None, max_length=500)


class ResultCorrect(BaseModel):
    """Supersede a result. The previous score stays readable."""

    score: float = Field(..., ge=0, le=MAX_SCORE)
    letter_grade: str | None = Field(None, max_length=5)
    note: str | None = Field(None, max_length=500)
    #: A correction without a reason is indistinguishable from an error.
    reason: str = Field(..., min_length=MIN_REASON_LENGTH, max_length=500)


class ResultSaveResponse(BaseModel):
    result: ExaminationResultRead
    result_count: int


class PublicationResponse(BaseModel):
    examination: ExaminationRead
    published_count: int


# ── Student shape ──


class StudentResultRead(BaseModel):
    """A student's own published result. Only ever built for published exams."""

    score: float
    letter_grade: str | None = None
    note: str | None = None
    published_at: datetime


class StudentExaminationRead(BaseModel):
    id: uuid.UUID
    title: str
    examination_type: str
    course_code: str | None = None
    course_name: str | None = None
    exam_date: date
    start_time: time
    end_time: time
    location: str | None = None
    instructions: str | None = None
    status: str
    section_labels: list[str] = Field(default_factory=list)
    #: True when the examination has a schedule that has already passed.
    is_past: bool = False
    results_published: bool = False
    #: NULL while unpublished — the field does not exist in a student response
    #: until the institution publishes.
    result: StudentResultRead | None = None


class StudentExaminationList(BaseModel):
    items: list[StudentExaminationRead]
    total: int
    upcoming_count: int
    past_count: int


# ── Dashboards ──


class ExaminationDashboardCounts(BaseModel):
    """Real figures computed in SQL. No sample data and no estimates."""

    total: int = 0
    upcoming: int = 0
    completed: int = 0
    cancelled: int = 0
    published: int = 0
    unpublished_results: int = 0
    eligible_students: int = 0
    results_recorded: int = 0


class ExaminationDashboard(BaseModel):
    counts: ExaminationDashboardCounts
    #: The next examinations this role may see, already scoped and capped.
    upcoming: list[ExaminationRead] = Field(default_factory=list)
    #: Teacher/Admin/Management only.
    recent: list[ExaminationRead] = Field(default_factory=list)
    #: Student only.
    results: list[StudentExaminationRead] = Field(default_factory=list)


class ConflictDetail(BaseModel):
    """A detected scheduling conflict, described in identifiers only."""

    kind: Literal["STUDENT", "LOCATION"]
    examination_id: uuid.UUID
    message: str
