"""User session and credential-recovery models for authentication."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.identity import User


class UserSession(Base):
    """Server-side session record for authentication.

    The raw session token is stored in an HttpOnly cookie.
    This table stores the hashed token for verification and invalidation.
    """

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(50))


class PasswordResetToken(Base):
    """A single-use password reset token.

    Only the SHA-256 hash of the token is stored: a database disclosure must
    not hand an attacker working reset links. Tokens are single-use
    (``used_at``) and expire, and issuing a new one does not extend the life of
    any earlier token.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(String(50))


class AccountActivationToken(Base):
    """A single-use account-activation token for a provisioned account.

    Migration creates student accounts that have never had a password. The only
    credential that reaches the student is this token; it is stored as a
    SHA-256 hash so a database disclosure cannot mint working activation links,
    it expires, and it is spent on first successful use. The raw value exists
    only in the issuing response and whatever channel the office uses to hand
    it over — never in logs, exports or migration reports.
    """

    __tablename__ = "account_activation_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    #: MIGRATION (created with the student record), ADMIN (re-issued at the
    #: counter) or SELF_SERVICE.
    issued_reason: Mapped[str] = mapped_column(String(20), nullable=False, default="ADMIN")
    #: ADMIN_COUNTER, ACADEMIC_EMAIL or DEV. How the raw token was delivered.
    delivery: Mapped[str] = mapped_column(String(20), nullable=False, default="ADMIN_COUNTER")

    #: Set only when a staff member asserted, after inspecting an identity
    #: document, that the person in front of them owns this account.
    identity_verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    identity_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    verification_reference: Mapped[str | None] = mapped_column(String(120))
    ip_address: Mapped[str | None] = mapped_column(String(50))

    user: Mapped[User] = relationship(
        "User", back_populates="activations", foreign_keys=[user_id]
    )

    __table_args__ = (
        # At most one live token per account: re-issuing replaces the old one
        # rather than leaving two working links in circulation.
        Index(
            "uq_account_activation_live",
            "user_id",
            unique=True,
            postgresql_where=text("used_at IS NULL"),
        ),
    )


__all__ = ["UserSession", "PasswordResetToken", "AccountActivationToken"]
