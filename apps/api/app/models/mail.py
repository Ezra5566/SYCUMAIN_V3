"""Durable outbox for notification email.

Password-reset and activation links are *never* written here: those messages
carry a working credential, so they are sent inline from the request that
issued the token and exist only in transit. This table is for operational
notifications, whose body contains no secret — only a link to sign in.

Why an outbox at all
--------------------
An in-process background task loses a message when the container is replaced,
and sending inside a request makes a mail outage look like a failed admission
change. A row plus an explicit flush command gives three things an institution
needs: delivery survives a restart, retries are bounded and visible, and a
message cannot be sent twice because ``dedupe_key`` is unique.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class EmailOutboxStatus(enum.StrEnum):
    """Lifecycle of one queued message."""

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class EmailOutbox(Base):
    """One queued notification email.

    ``last_error`` holds an exception class or SMTP status — never a message
    body, recipient address or server response that could quote one.
    """

    __tablename__ = "email_outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    #: Stable key that makes enqueueing idempotent. For a notification it is
    #: ``notification:<notification id>``, so re-running a job that produced
    #: the same notification cannot produce a second message.
    dedupe_key: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)

    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    #: Machine-readable reason, e.g. ``notification``. Used for metrics and
    #: log filtering; never a credential.
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    status: Mapped[EmailOutboxStatus] = mapped_column(
        String(20), nullable=False, default=EmailOutboxStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(200))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


__all__ = ["EmailOutbox", "EmailOutboxStatus"]
