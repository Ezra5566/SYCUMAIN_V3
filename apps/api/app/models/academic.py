"""Academic models."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.identity import Staff, Student, User


# --- Enums ---


class AcademicPeriodStatus(enum.StrEnum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClassStatus(enum.StrEnum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClassroomStatus(enum.StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class EnrollmentStatus(enum.StrEnum):
    ENROLLED = "ENROLLED"
    DROPPED = "DROPPED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class TeacherAssignmentRole(enum.StrEnum):
    PRIMARY = "PRIMARY"
    ASSISTANT = "ASSISTANT"
    GUEST = "GUEST"


class AttendanceStatus(enum.StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    EXCUSED = "EXCUSED"


class AssessmentType(enum.StrEnum):
    ASSIGNMENT = "ASSIGNMENT"
    QUIZ = "QUIZ"
    MIDTERM = "MIDTERM"
    FINAL = "FINAL"
    PROJECT = "PROJECT"
    OTHER = "OTHER"


class EntityStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# --- Models ---


class Major(Base):
    """Academic major (e.g., Computer Science, Business Administration)."""

    __tablename__ = "majors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[EntityStatus] = mapped_column(
        String(20), nullable=False, default=EntityStatus.ACTIVE
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    programs: Mapped[list[Program]] = relationship(
        back_populates="major", lazy="selectin"
    )


class Program(Base):
    """Academic program associated with a major."""

    __tablename__ = "programs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    major_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("majors.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    duration_years: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[EntityStatus] = mapped_column(
        String(20), nullable=False, default=EntityStatus.ACTIVE
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    major: Mapped[Major] = relationship(back_populates="programs")
    courses: Mapped[list[Course]] = relationship(
        back_populates="program", lazy="selectin"
    )


class Course(Base):
    """Academic course (e.g., CS101 - Introduction to Programming)."""

    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    program_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id"), nullable=True, index=True
    )
    code: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # The reference source does not carry credits. NULL means "not supplied",
    # never an invented default.
    credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester: Mapped[int | None] = mapped_column(Integer)  # Which semester in the program
    source_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_import_batches.id"), index=True
    )
    status: Mapped[EntityStatus] = mapped_column(
        String(20), nullable=False, default=EntityStatus.ACTIVE
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    program: Mapped[Program | None] = relationship(back_populates="courses")
    classes: Mapped[list[ClassSection]] = relationship(
        back_populates="course", lazy="selectin"
    )


class AcademicPeriod(Base):
    """Academic period / term (e.g., Fall 2026, Spring 2027)."""

    __tablename__ = "academic_periods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    source_timetable_format: Mapped[str | None] = mapped_column(String(20))
    timetable_format_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("timetable_formats.code")
    )
    timetable_format_note: Mapped[str | None] = mapped_column(Text)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_import_batches.id"), index=True
    )
    status: Mapped[AcademicPeriodStatus] = mapped_column(
        String(20), nullable=False, default=AcademicPeriodStatus.PLANNED
    )

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_academic_period_date_order"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    classes: Mapped[list[ClassSection]] = relationship(
        back_populates="academic_period", lazy="selectin"
    )


class Classroom(Base):
    """Classroom / teaching space (separate from dormitory rooms)."""

    __tablename__ = "classrooms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    building: Mapped[str | None] = mapped_column(String(100))
    campus: Mapped[str | None] = mapped_column(String(100))
    room_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_import_batches.id"), index=True
    )
    status: Mapped[ClassroomStatus] = mapped_column(
        String(20), nullable=False, default=ClassroomStatus.AVAILABLE
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    timetable_entries: Mapped[list[TimetableEntry]] = relationship(
        back_populates="classroom", lazy="selectin"
    )


class ClassSection(Base):
    """A class/section offering of a course during an academic period."""

    __tablename__ = "class_sections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    academic_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_periods.id"),
        nullable=False,
        index=True,
    )
    section_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(300))
    source_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enrolled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_import_batches.id"), index=True
    )
    status: Mapped[ClassStatus] = mapped_column(
        String(20), nullable=False, default=ClassStatus.PLANNED
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "course_id", "academic_period_id", "section_code",
            name="uq_class_section_course_period",
        ),
    )

    # Relationships
    course: Mapped[Course] = relationship(back_populates="classes")
    academic_period: Mapped[AcademicPeriod] = relationship(back_populates="classes")
    teacher_assignments: Mapped[list[TeacherAssignment]] = relationship(
        back_populates="class_section", lazy="selectin"
    )
    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="class_section", lazy="selectin"
    )
    timetable_entries: Mapped[list[TimetableEntry]] = relationship(
        back_populates="class_section", lazy="selectin"
    )
    attendance_records: Mapped[list[AttendanceRecord]] = relationship(
        back_populates="class_section", lazy="selectin"
    )
    assessments: Mapped[list[Assessment]] = relationship(
        back_populates="class_section", lazy="selectin"
    )


class TeacherAssignment(Base):
    """Connects teachers (staff) to class sections."""

    __tablename__ = "teacher_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    class_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("class_sections.id"),
        nullable=False,
        index=True,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id"), nullable=False, index=True
    )
    role: Mapped[TeacherAssignmentRole] = mapped_column(
        String(20), nullable=False, default=TeacherAssignmentRole.PRIMARY
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "class_section_id", "staff_id",
            name="uq_teacher_assignment_class_staff",
        ),
    )

    # Relationships
    class_section: Mapped[ClassSection] = relationship(
        back_populates="teacher_assignments"
    )
    staff: Mapped[Staff] = relationship("Staff")


class Enrollment(Base):
    """Student enrollment in a class section."""

    __tablename__ = "enrollments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True
    )
    class_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("class_sections.id"),
        nullable=False,
        index=True,
    )
    status: Mapped[EnrollmentStatus] = mapped_column(
        String(20), nullable=False, default=EnrollmentStatus.ENROLLED
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    dropped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "student_id", "class_section_id",
            name="uq_enrollment_student_class",
        ),
    )

    # Relationships
    class_section: Mapped[ClassSection] = relationship(back_populates="enrollments")
    student: Mapped[Student] = relationship("Student")


class TimetableEntry(Base):
    """Schedule entry for a class section."""

    __tablename__ = "timetable_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    class_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("class_sections.id"),
        nullable=False,
        index=True,
    )
    classroom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classrooms.id"), nullable=True, index=True
    )
    day_of_week: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 0=Monday, 6=Sunday
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_label: Mapped[str | None] = mapped_column(String(12))
    source_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_import_batches.id"), index=True
    )

    # Deleted slots are retained: a past timetable is an academic record, not
    # disposable configuration. Reads exclude them unless explicitly requested.
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    class_section: Mapped[ClassSection] = relationship(
        back_populates="timetable_entries"
    )
    classroom: Mapped[Classroom | None] = relationship(
        back_populates="timetable_entries"
    )
    deleted_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[deleted_by_id]
    )

    __table_args__ = (
        Index(
            "ix_timetable_entries_period_lookup",
            "class_section_id",
            "is_deleted",
        ),
        Index(
            "uq_timetable_live_slot",
            "class_section_id",
            "day_of_week",
            "start_time",
            "end_time",
            "classroom_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
    )


class AttendanceRecord(Base):
    """Student attendance for a class session."""

    __tablename__ = "attendance_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True
    )
    class_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("class_sections.id"),
        nullable=False,
        index=True,
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(
        String(20), nullable=False
    )
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "student_id", "class_section_id", "session_date",
            name="uq_attendance_student_class_date",
        ),
    )

    # Relationships
    class_section: Mapped[ClassSection] = relationship(
        back_populates="attendance_records"
    )
    student: Mapped[Student] = relationship("Student")


class Assessment(Base):
    """An assessment/assignment within a class section."""

    __tablename__ = "assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    class_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("class_sections.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    assessment_type: Mapped[AssessmentType] = mapped_column(
        String(20), nullable=False
    )
    max_score: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    due_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    class_section: Mapped[ClassSection] = relationship(back_populates="assessments")
    grades: Mapped[list[Grade]] = relationship(
        back_populates="assessment", lazy="selectin"
    )


class Grade(Base):
    """Student grade for an assessment."""

    __tablename__ = "grades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessments.id"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    letter_grade: Mapped[str | None] = mapped_column(String(5))
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "student_id",
            name="uq_grade_assessment_student",
        ),
    )

    # Relationships
    assessment: Mapped[Assessment] = relationship(back_populates="grades")
    student: Mapped[Student] = relationship("Student")


class TimetableFormat(Base):
    """A source timetable layout, preserved exactly as supplied."""

    __tablename__ = "timetable_formats"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_description: Mapped[str | None] = mapped_column(Text)
    definition_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    slots: Mapped[list[TimetableSlot]] = relationship(
        back_populates="format", cascade="all, delete-orphan"
    )


class TimetableSlot(Base):
    """An observed format/label pair and its resolved clock interval."""

    __tablename__ = "timetable_slots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    format_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("timetable_formats.code"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(12), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("format_code", "label", name="uq_timetable_slot_format_label"),
    )

    format: Mapped[TimetableFormat] = relationship(back_populates="slots")


class AcademicImportBatch(Base):
    """One staged source import; applying is a separate explicit operation."""

    __tablename__ = "academic_import_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRY_RUN")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    counts_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rows: Mapped[list[AcademicImportRow]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class AcademicImportRow(Base):
    """Per-record staging and audit trail for the academic importer."""

    __tablename__ = "academic_import_rows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_import_batches.id"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(160), nullable=False)
    source_locator: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    previous_data: Mapped[dict | None] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATE")
    error_code: Mapped[str | None] = mapped_column(String(80))
    target_table: Mapped[str | None] = mapped_column(String(60))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "batch_id", "entity_type", "source_key",
            name="uq_academic_import_row_source",
        ),
    )

    batch: Mapped[AcademicImportBatch] = relationship(back_populates="rows")


class ProgramOffering(Base):
    """A period-specific source programme/cohort offering.

    It is deliberately not a ``Program``: the source name may not have a
    canonical parent programme, and inventing one would be false data.
    """

    __tablename__ = "program_offerings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    academic_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_periods.id"), nullable=False, index=True
    )
    program_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id"), nullable=True, index=True
    )
    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(200))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_import_batches.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "academic_period_id", "source_id",
            name="uq_program_offering_period_source",
        ),
        # Target for the composite foreign keys that keep an offering and its
        # intake together on admissions and placements.
        UniqueConstraint(
            "academic_period_id", "id",
            name="uq_program_offering_period_id",
        ),
    )

    academic_period: Mapped[AcademicPeriod] = relationship("AcademicPeriod")
    program: Mapped[Program | None] = relationship("Program")


class ClassSectionProgramOffering(Base):
    """Many-to-many link that makes shared delivery one section, not duplicates."""

    __tablename__ = "class_section_program_offerings"

    class_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("class_sections.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    program_offering_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("program_offerings.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    __table_args__ = (
        Index(
            "ix_class_section_program_offering_offering",
            "program_offering_id",
            "class_section_id",
        ),
    )


class AcademicChangeHistory(Base):
    """Append-only record of changes to grades and assessment definitions.

    Kept deliberately generic for the two academic records that can be edited
    in place. Timetable deletion has its own soft-delete columns, because the
    row itself must remain queryable as a schedule.
    """

    __tablename__ = "academic_change_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    class_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("class_sections.id"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    previous_data: Mapped[str] = mapped_column(Text, nullable=False)
    new_data: Mapped[str] = mapped_column(Text, nullable=False)
    changed_fields: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True
    )
    reason: Mapped[str | None] = mapped_column(String(500))

    class_section: Mapped[ClassSection] = relationship("ClassSection")
    changed_by: Mapped[User | None] = relationship("User", foreign_keys=[changed_by_id])


__all__ = [
    "Major",
    "Program",
    "Course",
    "AcademicPeriod",
    "Classroom",
    "ClassSection",
    "TeacherAssignment",
    "Enrollment",
    "TimetableEntry",
    "TimetableFormat",
    "TimetableSlot",
    "ProgramOffering",
    "ClassSectionProgramOffering",
    "AcademicImportBatch",
    "AcademicImportRow",
    "AttendanceRecord",
    "Assessment",
    "Grade",
    "AcademicPeriodStatus",
    "ClassStatus",
    "ClassroomStatus",
    "EnrollmentStatus",
    "TeacherAssignmentRole",
    "AttendanceStatus",
    "AssessmentType",
    "EntityStatus",
]
