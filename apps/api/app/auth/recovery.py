"""Self-service password recovery.

The flow is: request a reset → receive a single-use token → set a new password.

Security properties, and why each one is here:

* **No account enumeration.** The request endpoint answers identically whether
  or not the address exists, so it cannot be used to discover who has an
  account.
* **Only a hash is stored.** A database disclosure must not hand an attacker
  working reset links, so the raw token exists only in transit and in the
  response to the person who requested it.
* **Single use, short lived.** A token is consumed on first successful use and
  expires on a timer; requesting a new one invalidates outstanding ones.
* **Sessions are revoked on reset.** If the account was compromised, the
  attacker's existing session must not survive the recovery.

Delivery is pluggable and defaults to *disabled*. A reset flow that silently
accepts requests and never delivers anything would be exactly the "fake forgot
password button" this system is meant to avoid, so when delivery is disabled
the capability endpoint tells the UI to hide the flow entirely instead of
pretending it works.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.audit import record_audit
from app.auth.service import hash_password
from app.config.settings import get_settings
from app.models.identity import User
from app.models.session import PasswordResetToken, UserSession

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession


class RecoveryError(ValueError):
    """Raised when a reset cannot be completed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def delivery_available() -> bool:
    """Whether a reset link can actually reach the user."""
    return get_settings().PASSWORD_RESET_DELIVERY != "disabled"


def generate_reset_token() -> str:
    """Return a new high-entropy reset token (URL-safe)."""
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    """Hash a reset token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def request_password_reset(
    db: DBSession,
    *,
    email: str,
    ip_address: str | None = None,
    request=None,
) -> tuple[User | None, str | None]:
    """Issue a reset token for `email`.

    Returns ``(user, raw_token)``. ``raw_token`` is populated only when an
    eligible account exists *and* a delivery mechanism is available; the caller
    must not vary its response based on whether it is ``None``.

    An inactive account is treated exactly like an unknown address: recovering
    a password must never reactivate a disabled account.
    """
    if not delivery_available():
        return (None, None)

    normalized = email.strip().lower()
    user = db.query(User).filter(User.email == normalized).first()

    if user is None or not user.is_active:
        return (None, None)

    # Any token issued earlier is now void: only the most recent link works.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).delete(synchronize_session=False)

    raw_token = generate_reset_token()
    expires_at = datetime.now(UTC) + timedelta(
        minutes=get_settings().PASSWORD_RESET_EXPIRE_MINUTES
    )

    db.add(
        PasswordResetToken(
            token_hash=hash_reset_token(raw_token),
            user_id=user.id,
            expires_at=expires_at,
            ip_address=ip_address,
        )
    )

    # The token itself is never logged — only that a reset was requested.
    record_audit(
        db,
        action="auth.password_reset_requested",
        actor=user,
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    db.commit()

    return (user, raw_token)


def consume_reset_token(
    db: DBSession,
    *,
    token: str,
    new_password: str,
    request=None,
) -> User:
    """Set a new password using a valid reset token.

    Raises:
        RecoveryError: ``invalid_token`` when the token is unknown, already
            used, or expired. All three look identical to the caller on
            purpose — distinguishing them would help an attacker probe.
    """
    token_hash = hash_reset_token(token)

    record = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .first()
    )

    # `datetime.now(UTC)` rather than the deprecated naive `utcnow()`: these
    # columns are TIMESTAMPTZ, so Postgres hands back an *aware* datetime and a
    # naive comparison raises TypeError.
    now = datetime.now(UTC)

    if record is None or record.used_at is not None or record.expires_at < now:
        raise RecoveryError("invalid_token")

    user = db.query(User).filter(User.id == record.user_id).first()
    if user is None or not user.is_active:
        raise RecoveryError("invalid_token")

    user.hashed_password = hash_password(new_password)
    # A recovered password is chosen by the account owner, so the
    # "must replace this temporary password" prompt no longer applies.
    user.must_change_password = False

    record.used_at = now

    # Revoke every live session: completing recovery proves control of the
    # mailbox, not of whoever was already signed in.
    db.query(UserSession).filter(UserSession.user_id == user.id).delete(
        synchronize_session=False
    )

    record_audit(
        db,
        action="auth.password_reset_completed",
        actor=user,
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    db.commit()
    db.refresh(user)
    return user


def purge_expired_reset_tokens(db: DBSession, *, now: datetime | None = None) -> int:
    """Delete spent or expired tokens. Housekeeping, not authorization."""
    cutoff = now or datetime.now(UTC)
    deleted = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.expires_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


__all__ = [
    "RecoveryError",
    "consume_reset_token",
    "delivery_available",
    "generate_reset_token",
    "hash_reset_token",
    "purge_expired_reset_tokens",
    "request_password_reset",
]
