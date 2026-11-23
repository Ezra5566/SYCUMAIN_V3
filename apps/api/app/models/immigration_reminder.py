"""Immigration expiry reminders.

A reminder is an *alert*, not a notification: it records that a specific
document on a specific verified profile reached a specific expiry tier with a
specific expiry date. Notifications are then delivered to recipients from that
alert.

Separating the two is what makes the four rules in this module provable:

* **No duplicates.** ``uq_immigration_reminder_alert`` makes one alert per
  profile, document, tier and expiry date impossible to create twice, no matter
  how often the job runs or how many workers run it.
* **Resolution.** When the underlying condition is corrected — the document is
  renewed, the expiry date is fixed, or the profile is no longer verified — the
  open alert is marked resolved instead of lingering as a permanent warning.
* **History.** Resolved alerts stay. An auditor can see that a student was
  warned about an expiring visa in March and that the warning cleared in April.
* **Provenance.** Only ``verification_status = 'VERIFIED'`` profiles generate
  alerts, so an unverified import or a student's unconfirmed submission can
  never drive an official expiry reminder.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime  # noqa: TC003 - SQLAlchemy resolves annotations
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.identity import Student

#: The document columns a reminder can be about. ``OTHER`` documents have no
#: expiry date in the profile, so they never produce an alert.
REMINDER_DOCUMENT_TYPES = ("PASSPORT", "VISA", "RESIDENCE_PERMIT")

#: The tiers that are worth telling somebody about. ``VALID`` and
#: ``NOT_PROVIDED`` are not alerts.
REMINDER_TIERS = ("EXPIRED", "URGENT", "EXPIRING_SOON")


class ImmigrationReminder(Base):
    """One expiry alert for one document of one verified profile."""

    __tablename__ = "immigration_reminders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    immigration_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("immigration_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: Denormalised so a resident's reminder history can be read without
    #: joining through the profile, and so the row survives a profile change.
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    #: EXPIRED | URGENT | EXPIRING_SOON
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    #: The expiry date that triggered this alert. Stored so renewal can be told
    #: apart from a corrected typo.
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)

    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: CORRECTED | EXPIRY_UPDATED | PROFILE_UNVERIFIED | STUDENT_INACTIVE
    resolution: Mapped[str | None] = mapped_column(String(30))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        # One alert per document, tier and expiry date. Re-running the job, or
        # two workers racing, cannot produce a second reminder for the same
        # condition.
        UniqueConstraint(
            "immigration_profile_id",
            "document_type",
            "tier",
            "expiry_date",
            name="uq_immigration_reminder_alert",
        ),
        Index("ix_immigration_reminders_open", "resolved_at"),
    )

    student: Mapped[Student] = relationship("Student")


__all__ = [
    "ImmigrationReminder",
    "REMINDER_DOCUMENT_TYPES",
    "REMINDER_TIERS",
]
