"""Academic Pydantic schemas for API request/response validation."""

from __future__ import annotations

import uuid  # noqa: TC003
from datetime import date, datetime, time  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.academic import (  # noqa: TC001
    AcademicPeriodStatus,
    AssessmentType,
    AttendanceStatus,
    ClassroomStatus,
    ClassStatus,
    EnrollmentStatus,
    EntityStatus,
    TeacherAssignmentRole,
)

# --- Major ---


class MajorCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    status: EntityStatus = EntityStatus.ACTIVE


class MajorUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    status: EntityStatus | None = None


class MajorResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    status: EntityStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Program ---


class ProgramCreate(BaseModel):
    major_id: uuid.UUID
    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    duration_years: int | None = None
    status: EntityStatus = EntityStatus.ACTIVE


class ProgramUpdate(BaseModel):
    major_id: uuid.UUID | None = None
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    duration_years: int | None = None
    status: EntityStatus | None = None


class ProgramResponse(BaseModel):
    id: uuid.UUID
    major_id: uuid.UUID
    major_name: str | None = None
    code: str
    name: str
    description: str | None = None
    duration_years: int | None = None
    status: EntityStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Course ---


class CourseCreate(BaseModel):
    program_id: uuid.UUID | None = None
    code: str | None = Field(None, min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=200)
    name_zh: str | None = Field(None, max_length=200)
    description: str | None = None
    # NULL means the source did not supply a value. Do not invent a default.
    credits: int | None = Field(None, ge=0, le=20)
    semester: int | None = None
    status: EntityStatus = EntityStatus.ACTIVE


class CourseUpdate(BaseModel):
    program_id: uuid.UUID | None = None
    name: str | None = Field(None, min_length=1, max_length=200)
    name_zh: str | None = Field(None, max_length=200)
    description: str | None = None
    credits: int | None = Field(None, ge=0, le=20)
    semester: int | None = None
    status: EntityStatus | None = None


class CourseResponse(BaseModel):
    id: uuid.UUID
    program_id: uuid.UUID | None = None
    program_name: str | None = None
    code: str | None = None
    name: str
    name_zh: str | None = None
    description: str | None = None
    credits: int | None = None
    semester: int | None = None
    source_key: str | None = None
    status: EntityStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Academic Period ---


class AcademicPeriodCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    code: str = Field(..., min_length=1, max_length=20)
    start_date: date
    end_date: date
    status: AcademicPeriodStatus = AcademicPeriodStatus.PLANNED

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: date, info) -> date:
        if "start_date" in info.data and v < info.data["start_date"]:
            raise ValueError("end_date must not precede start_date")
        return v


class AcademicPeriodUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    status: AcademicPeriodStatus | None = None


class AcademicPeriodResponse(BaseModel):
    id: uuid.UUID
    name: str
    name_zh: str | None = None
    code: str
    start_date: date
    end_date: date
    source_key: str | None = None
    source_timetable_format: str | None = None
    timetable_format_code: str | None = None
    timetable_format_note: str | None = None
    status: AcademicPeriodStatus
    # UI affordances. Dependants make an ordinary date edit unsafe; the flag
    # makes the correction dialog disappear when the phase is rolled back.
    has_dependants: bool = False
    date_correction_enabled: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AcademicPeriodDateCorrectionCreate(BaseModel):
    """A controlled correction; both dates and a substantial reason.

    Fields are optional here so the service can answer with a stable error
    code rather than Pydantic's field-array response. The service enforces all
    three requirements before any write.
    """

    new_start_date: date | None = None
    new_end_date: date | None = None
    reason: str | None = None
    evidence_reference: str | None = Field(None, max_length=500)


class AcademicPeriodDateCorrectionResponse(BaseModel):
    id: uuid.UUID
    academic_period_id: uuid.UUID
    previous_start_date: date
    previous_end_date: date
    new_start_date: date
    new_end_date: date
    reason: str
    actor_id: uuid.UUID
    actor_name: str | None = None
    created_at: datetime
    placements_reflagged: int
    admissions_rechecked: int

    model_config = {"from_attributes": True}


# --- Classroom ---


class ClassroomCreate(BaseModel):
    building: str | None = Field(None, max_length=100)
    campus: str | None = Field(None, max_length=100)
    room_code: str = Field(..., min_length=1, max_length=20)
    name: str | None = Field(None, max_length=200)
    capacity: int | None = Field(None, ge=1, le=500)
    status: ClassroomStatus = ClassroomStatus.AVAILABLE


class ClassroomUpdate(BaseModel):
    room_code: str | None = Field(None, min_length=1, max_length=20)
    building: str | None = None
    campus: str | None = None
    name: str | None = None
    capacity: int | None = Field(None, ge=1, le=500)
    status: ClassroomStatus | None = None


class ClassroomResponse(BaseModel):
    id: uuid.UUID
    building: str | None = None
    campus: str | None = None
    room_code: str
    name: str | None = None
    capacity: int | None = None
    source_key: str | None = None
    status: ClassroomStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Class Section ---


class ClassSectionCreate(BaseModel):
    course_id: uuid.UUID
    academic_period_id: uuid.UUID
    section_code: str | None = Field(None, min_length=1, max_length=20)
    source_label: str | None = Field(None, max_length=300)
    capacity: int | None = Field(None, ge=1, le=500)
    status: ClassStatus = ClassStatus.PLANNED


class ClassSectionUpdate(BaseModel):
    """Editable attributes of an offering.

    The course, period and section code are included because correcting a
    mis-scheduled section is an ordinary office task; the service layer guards
    the cases where changing them would strand a roster or a schedule.
    """

    course_id: uuid.UUID | None = None
    academic_period_id: uuid.UUID | None = None
    section_code: str | None = Field(None, min_length=1, max_length=20)
    capacity: int | None = Field(None, ge=1, le=500)
    status: ClassStatus | None = None


class TeacherInfo(BaseModel):
    id: uuid.UUID
    staff_id: str | None = None
    first_name: str
    last_name: str
    role: TeacherAssignmentRole

    model_config = {"from_attributes": True}


class ProgramOfferingSummary(BaseModel):
    id: uuid.UUID
    source_id: str
    name: str
    name_zh: str | None = None
    program_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class ClassSectionResponse(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    course_code: str | None = None
    course_name: str | None = None
    academic_period_id: uuid.UUID
    academic_period_name: str | None = None
    section_code: str | None = None
    source_label: str | None = None
    capacity: int | None = None
    enrolled_count: int
    status: ClassStatus
    teachers: list[TeacherInfo] = []
    program_offerings: list[ProgramOfferingSummary] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClassSectionBrief(BaseModel):
    id: uuid.UUID
    course_code: str | None = None
    course_name: str | None = None
    section_code: str | None = None
    source_label: str | None = None
    academic_period_id: uuid.UUID | None = None
    academic_period_name: str | None = None
    enrolled_count: int
    capacity: int | None = None
    status: ClassStatus
    program_offerings: list[ProgramOfferingSummary] = []

    model_config = {"from_attributes": True}


# --- Teacher Assignment ---


class TeacherAssignmentCreate(BaseModel):
    staff_id: uuid.UUID
    role: TeacherAssignmentRole = TeacherAssignmentRole.PRIMARY


class TeachableStaff(BaseModel):
    """A staff member who can be assigned to a class section.

    Served so the assignment picker offers real people instead of asking a
    clerk to paste a UUID. Intentionally minimal: name, staff number and the
    account email, with no HR or personal data.
    """

    staff_id: uuid.UUID
    staff_number: str | None = None
    first_name: str
    last_name: str
    email: str | None = None
    roles: list[str] = []


class TeachableStaffListResponse(BaseModel):
    items: list[TeachableStaff]
    total: int


class TeacherAssignmentResponse(BaseModel):
    id: uuid.UUID
    class_section_id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str | None = None
    role: TeacherAssignmentRole
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Enrollment ---


class EnrollmentCreate(BaseModel):
    student_id: uuid.UUID


class EnrollmentUpdate(BaseModel):
    status: EnrollmentStatus


class EnrollmentResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str | None = None
    student_number: str | None = None
    class_section_id: uuid.UUID
    status: EnrollmentStatus
    enrolled_at: datetime
    dropped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Timetable ---


class TimetableEntryCreate(BaseModel):
    """A new schedule slot.

    The interval its two times form is *not* validated here. It is checked in
    the service instead, so that an inverted interval produces the same stable
    ``TIMETABLE_INVALID_INTERVAL`` 409 whether it arrives on create or on a
    partial update. A field validator on create alone would answer the two
    halves of one rule differently — a JSON-array 422 the client can only
    render as generic "check your input", and a coded error it can name.
    """

    class_section_id: uuid.UUID
    classroom_id: uuid.UUID | None = None
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    start_time: time
    end_time: time


class TimetableEntryUpdate(BaseModel):
    """Editable attributes of a schedule slot.

    ``class_section_id`` is settable so a slot mistakenly booked against the
    wrong section can be corrected instead of deleted and recreated, which
    would break any reference to its id.
    """

    class_section_id: uuid.UUID | None = None
    classroom_id: uuid.UUID | None = None
    day_of_week: int | None = Field(None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None


class ProgramOfferingCreate(BaseModel):
    academic_period_id: uuid.UUID
    source_id: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)
    name_zh: str | None = Field(None, max_length=200)
    program_id: uuid.UUID | None = None


class ProgramOfferingUpdate(BaseModel):
    """Editable offering metadata. The source identifier is immutable."""

    name: str | None = Field(None, min_length=1, max_length=200)
    name_zh: str | None = Field(None, max_length=200)
    program_id: uuid.UUID | None = None


class SectionProgramOfferingUpdate(BaseModel):
    """The complete set of offerings a canonical section serves."""

    program_offering_ids: list[uuid.UUID] = Field(default_factory=list)


class ProgramOfferingResponse(ProgramOfferingSummary):
    academic_period_id: uuid.UUID
    program_name: str | None = None
    #: False for source-only or closed offerings. The API refuses these in
    #: placement writes; this flag lets a picker omit them rather than letting
    #: a clerk discover the rule only after submitting.
    selectable: bool = False
    unavailable_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class TimetableEntryResponse(BaseModel):
    id: uuid.UUID
    class_section_id: uuid.UUID
    course_code: str | None = None
    course_name: str | None = None
    section_code: str | None = None
    source_label: str | None = None
    classroom_id: uuid.UUID | None = None
    classroom_name: str | None = None
    day_of_week: int
    start_time: time
    end_time: time
    slot_label: str | None = None
    academic_period_id: uuid.UUID | None = None
    period_code: str | None = None
    format_code: str | None = None
    program_offerings: list[ProgramOfferingSummary] = []
    teacher_names: list[str] = []
    is_deleted: bool = False
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Attendance ---


class AttendanceRecordCreate(BaseModel):
    student_id: uuid.UUID
    class_section_id: uuid.UUID | None = None
    session_date: date | None = None
    status: AttendanceStatus
    note: str | None = Field(None, max_length=500)


class AttendanceRecordUpdate(BaseModel):
    status: AttendanceStatus | None = None
    note: str | None = Field(None, max_length=500)


class AttendanceRecordResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str | None = None
    class_section_id: uuid.UUID
    session_date: date
    status: AttendanceStatus
    recorded_by: uuid.UUID
    note: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AttendanceBulkCreate(BaseModel):
    class_section_id: uuid.UUID | None = None
    session_date: date
    records: list[AttendanceRecordCreate]


# --- Assessment ---


class AssessmentCreate(BaseModel):
    class_section_id: uuid.UUID | None = None
    name: str = Field(..., min_length=1, max_length=200)
    assessment_type: AssessmentType
    max_score: float = Field(default=100.0, gt=0)
    weight: float = Field(default=1.0, ge=0)
    due_date: date | None = None


class AssessmentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    assessment_type: AssessmentType | None = None
    max_score: float | None = Field(None, gt=0)
    weight: float | None = Field(None, ge=0)
    due_date: date | None = None


class AssessmentResponse(BaseModel):
    id: uuid.UUID
    class_section_id: uuid.UUID
    name: str
    assessment_type: AssessmentType
    max_score: float
    weight: float
    due_date: date | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Grade ---


class GradeCreate(BaseModel):
    assessment_id: uuid.UUID
    student_id: uuid.UUID
    score: float = Field(..., ge=0)
    letter_grade: str | None = Field(None, max_length=5)
    note: str | None = Field(None, max_length=500)


class GradeUpdate(BaseModel):
    score: float | None = Field(None, ge=0)
    letter_grade: str | None = Field(None, max_length=5)
    note: str | None = Field(None, max_length=500)


class GradeResponse(BaseModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    assessment_name: str | None = None
    student_id: uuid.UUID
    student_name: str | None = None
    score: float
    letter_grade: str | None = None
    recorded_by: uuid.UUID
    note: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Student Academic Overview ---


class AcademicChangeHistoryResponse(BaseModel):
    """Previous and new values for an edited assessment or grade."""

    id: uuid.UUID
    class_section_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    previous_data: dict
    new_data: dict
    changed_fields: list[str] = []
    changed_by_id: uuid.UUID | None = None
    changed_by_name: str | None = None
    changed_at: datetime
    reason: str | None = None


class StudentAcademicOverview(BaseModel):
    student_id: uuid.UUID
    student_name: str
    major: MajorResponse | None = None
    program: ProgramResponse | None = None
    program_offering: ProgramOfferingSummary | None = None
    current_period: AcademicPeriodResponse | None = None
    selected_period: AcademicPeriodResponse | None = None
    is_current: bool = True
    enrolled_classes: list[ClassSectionBrief] = []
    timetable: list[TimetableEntryResponse] = []


# --- Pagination ---


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class MajorListResponse(BaseModel):
    items: list[MajorResponse]
    meta: PaginationMeta


class ProgramListResponse(BaseModel):
    items: list[ProgramResponse]
    meta: PaginationMeta


class CourseListResponse(BaseModel):
    items: list[CourseResponse]
    meta: PaginationMeta


class ClassSectionListResponse(BaseModel):
    items: list[ClassSectionResponse]
    meta: PaginationMeta


class ClassroomListResponse(BaseModel):
    items: list[ClassroomResponse]
    meta: PaginationMeta


class AcademicPeriodListResponse(BaseModel):
    items: list[AcademicPeriodResponse]
    meta: PaginationMeta


class ProgramOfferingListResponse(BaseModel):
    items: list[ProgramOfferingResponse]
    meta: PaginationMeta


# --- Source intake catalog ---
#
# The accepted timetable map is a read-only reference asset, not an academic
# record. These responses expose its source identifiers and the state of the
# persisted mappings without creating periods or offerings for unresolved
# intakes.


class SourceIntakeSubjectResponse(BaseModel):
    name: str
    rows: int
    section_key: str
    delivery: str
    shared_with: list[str] = []
    held: bool = False


class SourceIntakeSectionResponse(BaseModel):
    source_key: str
    course: str
    offerings: list[str] = []
    session_count: int
    shared: bool = False
    held: bool = False
    mapping_state: str
    mapped_class_section_id: uuid.UUID | None = None
    imported_session_count: int | None = None
    timetable_verified: bool | None = None


class SourceIntakeOfferingResponse(BaseModel):
    source_id: str
    name: str
    name_zh: str | None = None
    schedule_rows: int
    mapping_state: str
    program_offering_id: uuid.UUID | None = None
    subject_count: int
    mapped_subject_count: int | None = None
    mapped_section_count: int | None = None
    assigned_student_count: int | None = None
    shared_section_count: int = 0
    held_section_count: int = 0
    held: bool = False
    subjects: list[SourceIntakeSubjectResponse] = []


class SourceIntakeResponse(BaseModel):
    source_id: str
    name: str
    name_zh: str | None = None
    source_identified: bool
    period: AcademicPeriodResponse | None = None
    period_configured: bool
    timetable_imported: bool
    ready: bool
    active: bool
    readiness_state: str
    readiness_reason_codes: list[str] = []
    offering_count: int
    mapped_offering_count: int | None = None
    subject_count: int
    section_count: int
    mapped_section_count: int | None = None
    shared_section_count: int
    held_section_count: int
    source_session_count: int
    mapped_timetable_session_count: int | None = None
    verified_source_session_count: int | None = None
    offerings: list[SourceIntakeOfferingResponse] = []
    sections: list[SourceIntakeSectionResponse] = []


class SourceIntakeListResponse(BaseModel):
    source: str
    source_sha256: str
    catalog_sha256: str
    counts: dict[str, int]
    items: list[SourceIntakeResponse]


class TimetableListResponse(BaseModel):
    items: list[TimetableEntryResponse]
    meta: PaginationMeta | None = None


class IntakeOfferingPlan(BaseModel):
    """One intake-specific programme offering to create if absent."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)
    program_code: str | None = Field(default=None, max_length=20)


class IntakePlanItem(BaseModel):
    """One academic intake to plan.

    ``status`` may not be ACTIVE for an intake whose start date is in the
    future; a prepared intake is PLANNED until the institution opens it.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=2, max_length=20)
    name: str = Field(..., min_length=1, max_length=100)
    start_date: date
    end_date: date
    status: str = Field(default="PLANNED", max_length=20)
    offerings: list[IntakeOfferingPlan] = Field(default_factory=list)


class IntakePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intakes: list[IntakePlanItem] = Field(..., min_length=1, max_length=20)
