"""Student-level absence records (Phase 3, corrected model).

Attendance is a property of a *student and an admission episode*, not of a
teaching section. The university counts one attendance figure per student, so
this table stores the only fact that can change it: an absence.

Two rules are structural:

* attendance is stored as absences only. There is no ``PRESENT`` row and no
  daily sheet: an eligible working day with no absence is a day the student
  attended. Generating present rows would duplicate the working-day calendar in
  the database and make every count depend on whether a job ran.
* a student has at most one *current* absence per episode per date. A correction
  supersedes the previous row (``superseded_at`` set, ``supersedes_id`` pointing
  back), and the partial unique index covers current rows only, so the original
  date, reason, recorder and timestamp remain readable.

Percentages are never stored. They are derived from this table plus the
university calendar at read time, so a holiday declared later or an absence
corrected here cannot leave a stale figure behind.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.admission import AcademicAdmission
    from app.models.identity import Student, User


class AttendanceAbsence(Base):
    """One absence for one student on one date, current or superseded."""

    __tablename__ = "attendance_absences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: The episode the absence belongs to. Scoping matters: a new episode starts
    #: a new attendance record, and nothing carries over from the previous one.
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_admissions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    absence_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: Why the student was absent. Required: an unexplained absence is not a
    #: record the institution can defend.
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    #: The staff member responsible for the record (the teacher who took it, or
    #: the administrator who entered it).
    recorded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    #: The record this one replaced, when it is a correction.
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_absences.id", ondelete="RESTRICT"),
        nullable=True,
    )
    #: Set when a later correction replaced this record. NULL means current.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Cancellation is not a correction and not a deletion: the record stays
    #: current, keeps its date and reason, is excluded from the calculation, and
    #: carries who cancelled it, when, and why.
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint("length(btrim(reason)) > 0", name="ck_absence_reason"),
        CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_absence_supersedes",
        ),
        # Cancellation is one fact in three parts: either the record was not
        # cancelled and all three are null, or it was and all three are set.
        CheckConstraint(
            "(cancelled_at IS NULL AND cancelled_by_id IS NULL AND cancellation_reason IS NULL)"
            " OR "
            "(cancelled_at IS NOT NULL AND cancelled_by_id IS NOT NULL"
            " AND length(btrim(cancellation_reason)) > 0)",
            name="ck_absence_cancellation",
        ),
        Index("ix_attendance_absences_student_id", "student_id"),
        Index("ix_attendance_absences_admission_id", "admission_id"),
        Index("ix_attendance_absences_date", "absence_date"),
        # One *active* absence per student per episode per date. Superseded and
        # cancelled rows fall out of the index: a correction can sit beside the
        # record it replaced, and a cancelled date can be recorded again.
        Index(
            "uq_attendance_absence_current",
            "student_id",
            "admission_id",
            "absence_date",
            unique=True,
            postgresql_where=text("superseded_at IS NULL AND cancelled_at IS NULL"),
        ),
    )

    student: Mapped[Student] = relationship("Student")
    admission: Mapped[AcademicAdmission] = relationship("AcademicAdmission")
    recorded_by: Mapped[User] = relationship("User", foreign_keys=[recorded_by_id])
    cancelled_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[cancelled_by_id]
    )


__all__ = ["AttendanceAbsence"]
