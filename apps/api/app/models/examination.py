"""Examinations: scheduling, participating sections and per-student results.

Why this is not another ``Assessment``
--------------------------------------
An ``Assessment`` is a component of one section's grade record: it belongs to a
single ``class_section_id``, carries a weight, and is used to build a course
mark. An examination is an institutional event: it is scheduled at a time and a
place, it may be sat by several teaching sections at once, and its results are
published to students as a separate act.

The two therefore share a vocabulary but not a row. This module reuses the
existing ``AssessmentType`` values (MIDTERM, FINAL, QUIZ, …) so staff see one set
of examination kinds, and it stores results in the same shape as ``Grade``
(score, optional letter grade, recorder, note) so there is no second grading
system to reconcile. What it does **not** do is compute anything: no GPA, no
percentage, no pass mark, no letter-grade derivation, no credits. The institution
has not published those rules, so nothing here invents them.

One examination, many sections
------------------------------
``examination_sections`` is the participation table. A shared exam is created
once and linked to every section that sits it — never duplicated per section —
which is what makes "the Biology 101 final" a single event with one schedule,
one room and one publication date.

Student visibility
------------------
A result exists before it is published. ``Examination.published_at`` is the gate:
until it is set, no student-facing query returns a score, a letter grade or a
result identifier. Enforcing that in the service rather than in the UI is what
makes the rule real.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal  # noqa: TC003 - SQLAlchemy resolves the annotation
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
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
    from app.models.academic import AcademicPeriod, ClassSection, Course, ProgramOffering
    from app.models.identity import Student, User


class ExaminationStatus(enum.StrEnum):
    """Lifecycle of a scheduled examination.

    ``CANCELLED`` is a state, not a deletion: a cancelled examination stays in
    the record with its schedule and any results already recorded, because
    "this exam was called off" is itself information a student and an auditor
    need.
    """

    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class Examination(Base):
    """One scheduled examination, possibly sat by several teaching sections."""

    __tablename__ = "examinations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Reuses the existing assessment vocabulary so there is one list of exam
    #: kinds in the institution, not a second one.
    examination_type: Mapped[str] = mapped_column(String(20), nullable=False)

    #: The subject and the intake it belongs to. Both are mandatory: an exam
    #: with no course or no period cannot be scoped to a real cohort.
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    academic_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_periods.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: Optional programme offering. When set, it narrows the exam to one
    #: offering; when omitted the participating sections define the scope.
    program_offering_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("program_offerings.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    exam_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    instructions: Mapped[str | None] = mapped_column(Text)

    #: The score ceiling, supplied by staff. NULL means "not stated" — never an
    #: invented 100, because a ceiling that nobody chose would silently reject
    #: or accept the wrong scores.
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExaminationStatus.SCHEDULED.value
    )
    #: A cancellation is recorded, not deleted: the schedule, its participants
    #: and any results already entered stay readable, with who called it off
    #: and why.
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))

    #: The publication gate. While this is NULL no student query returns a
    #: result, a score or a letter grade for this examination.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )

    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
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
        CheckConstraint(
            "end_time > start_time", name="ck_examination_time_order"
        ),
        CheckConstraint(
            "max_score IS NULL OR max_score > 0", name="ck_examination_max_score"
        ),
        CheckConstraint(
            "status IN ('SCHEDULED', 'CANCELLED')", name="ck_examination_status"
        ),
        # A cancelled examination always says who cancelled it and why; a
        # scheduled one never carries leftover cancellation data.
        CheckConstraint(
            "(status = 'CANCELLED' AND cancelled_at IS NOT NULL "
            "AND cancelled_by_id IS NOT NULL AND cancellation_reason IS NOT NULL) "
            "OR (status <> 'CANCELLED' AND cancelled_at IS NULL "
            "AND cancelled_by_id IS NULL AND cancellation_reason IS NULL)",
            name="ck_examination_cancellation",
        ),
        CheckConstraint(
            "(published_at IS NULL AND published_by_id IS NULL) "
            "OR (published_at IS NOT NULL AND published_by_id IS NOT NULL)",
            name="ck_examination_publication",
        ),
        Index("ix_examinations_period_date", "academic_period_id", "exam_date"),
    )

    course: Mapped[Course] = relationship("Course")
    academic_period: Mapped[AcademicPeriod] = relationship("AcademicPeriod")
    program_offering: Mapped[ProgramOffering | None] = relationship("ProgramOffering")
    created_by: Mapped[User] = relationship("User", foreign_keys=[created_by_id])
    published_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[published_by_id]
    )
    cancelled_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[cancelled_by_id]
    )

    sections: Mapped[list[ExaminationSection]] = relationship(
        back_populates="examination",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    results: Mapped[list[ExaminationResult]] = relationship(
        back_populates="examination", lazy="selectin"
    )


class ExaminationSection(Base):
    """A teaching section sitting an examination.

    This is the join that makes a shared examination one event instead of one
    event per section. It is also the source of truth for student eligibility:
    a student may sit (and be given a result for) the exam only if they are
    enrolled in one of these sections.
    """

    __tablename__ = "examination_sections"

    examination_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("examinations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    class_section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("class_sections.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "examination_id",
            "class_section_id",
            name="uq_examination_section",
        ),
    )

    examination: Mapped[Examination] = relationship(back_populates="sections")
    class_section: Mapped[ClassSection] = relationship("ClassSection")


class ExaminationResult(Base):
    """One student's result for one examination.

    Shaped like ``Grade`` on purpose: a numeric score, an optional letter grade
    the institution supplied, the recorder and a note. A correction supersedes
    rather than overwrites, so the previous score and its author stay readable —
    the same contract the academic and dormitory records already use.
    """

    __tablename__ = "examination_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    examination_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("examinations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    #: Only what staff entered. No scale is applied and no letter is derived.
    letter_grade: Mapped[str | None] = mapped_column(String(5))
    note: Mapped[str | None] = mapped_column(String(500))

    recorded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("examination_results.id", ondelete="RESTRICT"),
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Why the previous result was replaced. A correction without a reason is
    #: indistinguishable from an error.
    correction_reason: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint("score >= 0", name="ck_examination_result_score"),
        CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_examination_result_supersedes",
        ),
        # One live result per student per examination. Superseded rows fall out
        # of the index so the correction chain can grow beside them.
        Index(
            "uq_examination_result_current",
            "examination_id",
            "student_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    examination: Mapped[Examination] = relationship(back_populates="results")
    student: Mapped[Student] = relationship("Student")
    recorded_by: Mapped[User] = relationship(
        "User", foreign_keys=[recorded_by_id]
    )


__all__ = [
    "Examination",
    "ExaminationResult",
    "ExaminationSection",
    "ExaminationStatus",
]
