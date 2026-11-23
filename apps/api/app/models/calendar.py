"""University working-day calendar.

The working week is a *rule*, not a table: Monday to Friday are working days and
Saturday/Sunday are not. Only explicitly declared exceptions are stored, so the
calendar never contains a generated future date, and a date with no row always
resolves from its weekday.

A voided exception keeps its row. Voiding restores the weekday calculation while
the declaration, its reason, the actor and the void reason stay inspectable.

A vacation is not a single declaration but a *range*: the institution records
winter or summer vacation once, and each date in it is materialised as a
``VACATION`` exception owned by that range. The range is the parent record, so
the dates it produced can be listed, extended, shortened and cancelled together
without a second calendar engine. A date the institution corrects individually
afterwards is *detached* from its range: it keeps the range reference for
provenance, but range cancellation never touches it again.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
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


class CalendarDayType(enum.StrEnum):
    """How a date is classified once the calendar is resolved.

    ``WORKING`` and ``WEEKEND`` are *derived* from the weekday; the remaining
    three are the declarations an institution records.
    """

    WORKING = "WORKING"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"
    CLOSURE = "CLOSURE"
    EXCEPTIONAL_WORKING = "EXCEPTIONAL_WORKING"
    #: Declared through a vacation range, never as a single day. It resolves as a
    #: non-working academic day, exactly like a holiday or a closure.
    VACATION = "VACATION"


class CalendarVacationRange(Base):
    """An institution-entered winter or summer vacation, as one parent record.

    The range exists so its dates have an owner. Materialised
    :class:`UniversityCalendarDay` rows point at it, which is what makes
    "cancel this vacation" a single transactional decision instead of a search
    for dates that happen to share a title.

    ``start_date``/``end_date`` are the *current* bounds. Extending or
    shortening the range updates them and audited history records the previous
    values; it never deletes the dates that were removed — those rows are voided
    and stay readable.

    Cancellation is not deletion: the range keeps its bounds and gains who
    cancelled it, when, and why. A cancelled range cannot be cancelled again or
    adjusted, and the dates it did not produce are never touched.
    """

    __tablename__ = "calendar_vacation_ranges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: The institutional justification for the vacation itself.
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    is_cancelled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
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
        CheckConstraint("end_date >= start_date", name="ck_vacation_range_order"),
        CheckConstraint(
            "length(btrim(title)) > 0", name="ck_vacation_range_title"
        ),
        CheckConstraint(
            "length(btrim(reason)) > 0", name="ck_vacation_range_reason"
        ),
        CheckConstraint(
            "(is_cancelled AND cancelled_at IS NOT NULL "
            "AND cancelled_by_id IS NOT NULL "
            "AND length(btrim(coalesce(cancel_reason, ''))) > 0) "
            "OR (NOT is_cancelled AND cancelled_at IS NULL "
            "AND cancelled_by_id IS NULL AND cancel_reason IS NULL)",
            name="ck_vacation_range_cancel_fields",
        ),
    )

    cancelled_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[cancelled_by_id]
    )


class UniversityCalendarDay(Base):
    """An explicit exception to the institution's Monday–Friday working week.

    Only exceptions live here. An ordinary Tuesday has no row, because a row
    would claim the institution had *decided* something that its weekday rule
    already says — and would have to be generated for every future date.
    """

    __tablename__ = "university_calendar_days"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    calendar_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    day_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Why this date differs from the weekday rule. Required, never defaulted:
    # an unexplained exception is indistinguishable from a mistake.
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    is_void: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    void_reason: Mapped[str | None] = mapped_column(Text)

    #: The vacation range that materialised this date, when there was one. It is
    #: provenance and is never cleared, so every date can still name its range
    #: after the range is cancelled.
    calendar_range_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calendar_vacation_ranges.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    #: Set when the date is corrected individually while it belongs to a range.
    #: From that moment it is an independent declaration: range cancellation and
    #: shortening never void it, because the institution edited this date on its
    #: own terms.
    detached_from_range_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
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
        # One *live* declaration per date. The deployment serves a single
        # institution, so the institution is implicit in the date; a second live
        # row for the same day would make the resolved classification ambiguous.
        # Voided rows are excluded so a corrected declaration can be re-issued.
        Index(
            "uq_university_calendar_day_date",
            "calendar_date",
            unique=True,
            postgresql_where=text("is_void = false"),
        ),
        # `WORKING` and `WEEKEND` are resolver defaults, not declarable rows.
        CheckConstraint(
            "day_type IN ('HOLIDAY','CLOSURE','EXCEPTIONAL_WORKING','VACATION')",
            name="ck_calendar_day_type",
        ),
        # Only a date materialised by a range can be detached from one.
        CheckConstraint(
            "detached_from_range_at IS NULL OR calendar_range_id IS NOT NULL",
            name="ck_calendar_day_detached_range",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="ck_calendar_day_title"),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_calendar_day_reason"),
        # The void fields exist together or not at all: a row cannot claim to be
        # void without saying when, by whom and why.
        CheckConstraint(
            "(is_void AND voided_at IS NOT NULL AND voided_by_id IS NOT NULL "
            "AND length(btrim(coalesce(void_reason, ''))) > 0) "
            "OR (NOT is_void AND voided_at IS NULL AND voided_by_id IS NULL "
            "AND void_reason IS NULL)",
            name="ck_calendar_day_void_fields",
        ),
    )

    created_by: Mapped[User] = relationship("User", foreign_keys=[created_by_id])
    voided_by: Mapped[User | None] = relationship("User", foreign_keys=[voided_by_id])
    calendar_range: Mapped[CalendarVacationRange | None] = relationship(
        "CalendarVacationRange", foreign_keys=[calendar_range_id]
    )


__all__ = ["CalendarDayType", "CalendarVacationRange", "UniversityCalendarDay"]
