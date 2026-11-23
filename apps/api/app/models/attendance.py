"""Attendance commencement records.

A commencement is the date from which a student's attendance is expected to
count, and it belongs to exactly one admission episode. Two consequences follow,
and both are structural rather than procedural:

* a programme change inside the same episode never touches it, because the row
  is keyed by ``admission_id``;
* a new episode cannot inherit it, because a commencement row only ever refers
  to the episode it was approved for.

Corrections supersede rather than update. The superseded row keeps its date,
type, reason, actor and timestamp, so the history of a commencement is the list
of rows for its episode, newest first.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.identity import User


class AttendanceCommencementType(enum.StrEnum):
    """How the approved date relates to the suggested date.

    ``SCHEDULED`` confirms the computed suggestion as-is; ``LATE_JOIN`` records a
    later arrival; ``MANUAL`` records a date the institution established by
    other means.
    """

    SCHEDULED = "SCHEDULED"
    LATE_JOIN = "LATE_JOIN"
    MANUAL = "MANUAL"


class AttendanceCommencement(Base):
    """One approved (or superseded) commencement for one admission episode."""

    __tablename__ = "attendance_commencements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_admissions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
    )

    commencement_date: Mapped[date] = mapped_column(Date, nullable=False)
    commencement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    #: The suggestion the approver confirmed. Stored so the approval can be read
    #: later without recomputing from dates that may since have been corrected.
    suggested_date: Mapped[date] = mapped_column(Date, nullable=False)

    #: The record this one replaced, when it is a correction.
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_commencements.id", ondelete="RESTRICT"),
        nullable=True,
    )
    #: Set when a later correction replaced this record. NULL means current.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    approved_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "commencement_type IN ('SCHEDULED','LATE_JOIN','MANUAL')",
            name="ck_commencement_type",
        ),
        CheckConstraint(
            "length(btrim(reason)) > 0", name="ck_commencement_reason"
        ),
        CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_commencement_supersedes",
        ),
        Index("ix_attendance_commencements_admission_id", "admission_id"),
        Index("ix_attendance_commencements_student_id", "student_id"),
        # One *current* commencement per admission episode. Superseded rows fall
        # out of the index, which is what makes supersession possible at all.
        Index(
            "uq_attendance_commencement_current",
            "admission_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    approved_by: Mapped[User] = relationship("User", foreign_keys=[approved_by_id])


__all__ = ["AttendanceCommencement", "AttendanceCommencementType"]
