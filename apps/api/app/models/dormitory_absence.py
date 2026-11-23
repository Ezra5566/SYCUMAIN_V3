"""Dormitory attendance: absences recorded against an institutional housing stay.

This is a separate domain from academic attendance and shares none of its rules.

* Academic attendance is derived from *university working days* between an
  approved commencement and today; a weekend, holiday or vacation is not a day
  a student can be absent from class.
* Dormitory attendance runs on **every calendar day**. A resident is resident on
  a Saturday, a public holiday and in the winter vacation. The university
  calendar is therefore never consulted here — an exception declared for
  teaching must not silently change a residential record.

Two structural rules mirror the academic table, for the same reasons:

* only absences are stored. Physical presence is managed outside the system, so
  there is no ``PRESENT`` row and no nightly job whose failure would rewrite
  history. A day inside a residency with no absence is a day the student was in.
* a correction supersedes rather than overwrites. ``superseded_at`` marks the
  replaced row and ``supersedes_id`` points back at it, so the previous date,
  points, reason and recorder stay readable.

The link to ``housing_assignments`` is the eligibility record: an absence is
only valid inside the assignment that made the student eligible that day. It is
``RESTRICT`` in both directions — a student or a stay cannot be deleted while an
absence refers to it, and nothing cascades.

Points are administrative only. There is no default, no threshold and no
consequence computed from them: the institution has not published a penalty
scale, so the column stores what Management entered and nothing derives from it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal  # noqa: TC003 - SQLAlchemy resolves the annotation
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.housing import HousingAssignment
    from app.models.identity import Student, User


class DormitoryAbsence(Base):
    """One dormitory absence for one student on one date, current or superseded."""

    __tablename__ = "dormitory_absences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: The student *record*, matching the academic absence table. The housing
    #: assignment references the user id instead, so the database trigger is
    #: what proves the two describe the same person.
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: The stay that made the student eligible on this date. Retained forever:
    #: a student who moves out keeps the absences recorded while resident, and a
    #: student who returns accumulates a second, separate set.
    housing_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("housing_assignments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    absence_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: Points are entered by Management per absence. No default exists because
    #: the institution has not published a scale, and a default would become an
    #: unannounced policy the moment someone forgot to override it.
    points: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

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
        ForeignKey("dormitory_absences.id", ondelete="RESTRICT"),
        nullable=True,
    )
    #: Set when a later correction replaced this record. NULL means current.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Cancellation is a *different* act from correction: a corrected record was
    #: wrong, a cancelled one should not count at all. The row is never deleted
    #: and never rewritten — the three columns below are written once, together,
    #: and the absence stops contributing to every total from that moment.
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
        CheckConstraint("length(btrim(reason)) > 0", name="ck_dormitory_absence_reason"),
        CheckConstraint("points >= 0", name="ck_dormitory_absence_points"),
        CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_dormitory_absence_supersedes",
        ),
        # A cancellation is all three values or none of them. A half-written
        # cancellation would be a record nobody can explain later.
        CheckConstraint(
            "(cancelled_at IS NULL AND cancelled_by_id IS NULL "
            "AND cancellation_reason IS NULL) "
            "OR (cancelled_at IS NOT NULL AND cancelled_by_id IS NOT NULL "
            "AND length(btrim(cancellation_reason)) >= 10)",
            name="ck_dormitory_absence_cancellation",
        ),
        # A record is superseded by a correction or cancelled outright, never
        # both: the two are alternative terminal states.
        CheckConstraint(
            "superseded_at IS NULL OR cancelled_at IS NULL",
            name="ck_dormitory_absence_terminal_state",
        ),
        Index("ix_dormitory_absences_student_id", "student_id"),
        Index("ix_dormitory_absences_assignment_id", "housing_assignment_id"),
        Index("ix_dormitory_absences_date", "absence_date"),
        # One *active* absence per student per stay per date. Superseded and
        # cancelled rows fall out of the index: a correction can sit beside the
        # record it replaced, and cancelling an absence frees the date so a
        # correct one can be recorded without resurrecting the old row.
        Index(
            "uq_dormitory_absence_current",
            "student_id",
            "housing_assignment_id",
            "absence_date",
            unique=True,
            postgresql_where=text("superseded_at IS NULL AND cancelled_at IS NULL"),
        ),
    )

    student: Mapped[Student] = relationship("Student")
    housing_assignment: Mapped[HousingAssignment] = relationship("HousingAssignment")
    recorded_by: Mapped[User] = relationship("User", foreign_keys=[recorded_by_id])
    cancelled_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[cancelled_by_id]
    )


__all__ = ["DormitoryAbsence"]
