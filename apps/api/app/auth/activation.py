"""Account activation for provisioned (migrated) accounts.

A migrated student account starts with **no password at all**. The stored hash
is a marker no bcrypt verification can satisfy, so there is no credential to
leak, export or read aloud at a counter. The only thing that can turn the
account into a usable one is a single-use activation token that the student
exchanges for a password they choose themselves.

Security properties, and why each one is here:

* **High-entropy, single-use, short-lived.** ``secrets.token_urlsafe(32)`` is
  stored only as a SHA-256 hash; the token is spent on first successful use and
  expires after ``ACTIVATION_EXPIRE_HOURS``.
* **One live token per account.** Re-issuing deletes the previous unused token,
  so a lost link cannot be used alongside the replacement.
* **Identity verified before issue.** A staff-initiated re-issue requires an
  explicit identity-verification assertion (document inspected), recorded in
  the audit trail. Migration-created tokens carry the import batch as their
  verification basis, not a person's assertion.
* **Never in logs, reports or exports.** The raw token is returned exactly once
  by the issuing call. Audit entries record that a link was issued, for which
  account, and how — never the token.
* **Activation revokes sessions.** An account that is being activated must not
  keep a session created before it had a password.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.audit import record_audit
from app.auth.service import UNUSABLE_PASSWORD_HASH, hash_password
from app.config.settings import get_settings
from app.models.session import AccountActivationToken, UserSession

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session as DBSession

    from app.models.identity import User

#: Token states surfaced to a person holding a link.
STATE_VALID = "VALID"
STATE_USED = "USED"
STATE_EXPIRED = "EXPIRED"
STATE_UNKNOWN = "UNKNOWN"


class ActivationError(ValueError):
    """Raised when activation cannot be issued or completed."""

    def __init__(self, code: str, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.not_found = not_found


def hash_activation_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_activation_token() -> str:
    """Return a new high-entropy activation token (URL-safe)."""
    return secrets.token_urlsafe(32)


def activation_url(raw_token: str) -> str:
    base = get_settings().ACTIVATION_LINK_BASE.rstrip("/")
    return f"{base}/activate?token={raw_token}"


def _now() -> datetime:
    return datetime.now(UTC)


def mask_email(email: str) -> str:
    """Show enough of the address to recognise it, not enough to harvest it."""
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"


def issue_activation(
    db: DBSession,
    user: User,
    *,
    actor_id: uuid.UUID | None = None,
    reason: str = "ADMIN",
    delivery: str = "ADMIN_COUNTER",
    identity_verified: bool = False,
    verification_reference: str | None = None,
    request=None,
    audit: bool = True,
) -> tuple[AccountActivationToken, str]:
    """Issue (or re-issue) the single activation token for an account.

    Returns ``(record, raw_token)``. The raw token must be delivered to the
    account holder and never stored or logged by the caller.

    Raises:
        ActivationError: when the account is inactive, when a staff-initiated
            issue lacks an identity-verification assertion, or when the account
            is a student whose record does not permit portal access.
    """
    if not user.is_active:
        raise ActivationError(
            "ACCOUNT_DISABLED", "A disabled account cannot be activated."
        )

    if reason != "MIGRATION" and not identity_verified:
        raise ActivationError(
            "IDENTITY_VERIFICATION_REQUIRED",
            "Confirm the person's identity document before issuing an activation link.",
        )

    student = user.student
    if student is not None and student.status != "ACTIVE":
        raise ActivationError(
            "STUDENT_RECORD_INACTIVE",
            "The student record is not active, so the account cannot be activated.",
        )

    # Only one link may work at a time.
    db.query(AccountActivationToken).filter(
        AccountActivationToken.user_id == user.id,
        AccountActivationToken.used_at.is_(None),
    ).delete(synchronize_session=False)

    raw_token = generate_activation_token()
    record = AccountActivationToken(
        token_hash=hash_activation_token(raw_token),
        user_id=user.id,
        expires_at=_now() + timedelta(hours=get_settings().ACTIVATION_EXPIRE_HOURS),
        issued_by_id=actor_id,
        issued_reason=reason,
        delivery=delivery,
        identity_verified_by_id=actor_id if identity_verified else None,
        identity_verified_at=_now() if identity_verified else None,
        verification_reference=(verification_reference or None),
    )

    # Until the student completes activation the account has no usable
    # password. Re-issuing on an already active account therefore invalidates
    # the old password on purpose: the link is the way back in.
    user.activation_required = True
    user.hashed_password = UNUSABLE_PASSWORD_HASH
    user.must_change_password = False
    user.temporary_password_expires_at = None
    user.activated_at = None

    db.add(record)
    db.flush()

    if audit:
        record_audit(
            db,
            action="account.activation_issued",
            actor_id=actor_id,
            entity_type="user",
            entity_id=user.id,
            context={
                "reason": reason,
                "delivery": delivery,
                "identity_verified": identity_verified,
                "expires_at": record.expires_at.isoformat(),
            },
            request=request,
        )
    return record, raw_token


def activation_state(db: DBSession, user: User) -> dict[str, object]:
    """Report whether an account still needs activation. Never returns a token."""
    record = (
        db.query(AccountActivationToken)
        .filter(AccountActivationToken.user_id == user.id)
        .order_by(AccountActivationToken.created_at.desc())
        .first()
    )

    if not user.activation_required:
        state = "ACTIVATED"
    elif record is None:
        state = "NONE"
    elif record.used_at is not None:
        state = "USED"
    elif record.expires_at <= _now():
        state = "EXPIRED"
    else:
        state = "PENDING"

    return {
        "user_id": user.id,
        "state": state,
        "activation_required": user.activation_required,
        "activated_at": user.activated_at,
        "expires_at": record.expires_at if record else None,
        "issued_at": record.created_at if record else None,
        "delivery": record.delivery if record else None,
    }


def preview_activation(db: DBSession, token: str) -> dict[str, object]:
    """Describe a token without consuming it.

    Unknown, used and expired tokens are distinguishable to the holder of the
    link (they need to know whether to ask for a new one) but reveal nothing
    about accounts they do not already hold a token for.
    """
    record = (
        db.query(AccountActivationToken)
        .filter(AccountActivationToken.token_hash == hash_activation_token(token))
        .first()
    )
    if record is None:
        return {"state": STATE_UNKNOWN, "email_masked": None, "expires_at": None}
    if record.used_at is not None:
        return {"state": STATE_USED, "email_masked": None, "expires_at": record.expires_at}
    if record.expires_at <= _now():
        return {
            "state": STATE_EXPIRED,
            "email_masked": None,
            "expires_at": record.expires_at,
        }
    return {
        "state": STATE_VALID,
        "email_masked": mask_email(record.user.email),
        "expires_at": record.expires_at,
    }


def consume_activation(
    db: DBSession,
    *,
    token: str,
    password: str,
    request=None,
) -> User:
    """Set the account's own password and spend the token.

    Raises:
        ActivationError: invalid, used or expired token — all reported with the
            same code, because distinguishing them for an attacker adds nothing.
    """
    record = (
        db.query(AccountActivationToken)
        .filter(AccountActivationToken.token_hash == hash_activation_token(token))
        .with_for_update()
        .first()
    )
    now = _now()

    if record is None or record.used_at is not None or record.expires_at <= now:
        raise ActivationError(
            "INVALID_ACTIVATION_TOKEN",
            "This activation link is invalid or has expired. Request a new one.",
            not_found=True,
        )

    user = record.user
    if user is None or not user.is_active:
        raise ActivationError(
            "INVALID_ACTIVATION_TOKEN",
            "This activation link is invalid or has expired. Request a new one.",
            not_found=True,
        )

    user.hashed_password = hash_password(password)
    user.activation_required = False
    user.must_change_password = False
    user.temporary_password_expires_at = None
    user.activated_at = now
    record.used_at = now

    # Nothing signed in before the account had a password may survive it.
    db.query(UserSession).filter(UserSession.user_id == user.id).delete(
        synchronize_session=False
    )

    record_audit(
        db,
        action="account.activation_completed",
        actor=user,
        entity_type="user",
        entity_id=user.id,
        context={"delivery": record.delivery},
        request=request,
    )
    return user


def revoke_activation(
    db: DBSession,
    user: User,
    *,
    actor_id: uuid.UUID | None = None,
    request=None,
) -> int:
    """Delete any unused activation link for an account."""
    removed = (
        db.query(AccountActivationToken)
        .filter(
            AccountActivationToken.user_id == user.id,
            AccountActivationToken.used_at.is_(None),
        )
        .delete(synchronize_session=False)
    )
    if removed:
        record_audit(
            db,
            action="account.activation_revoked",
            actor_id=actor_id,
            entity_type="user",
            entity_id=user.id,
            request=request,
        )
    return removed


def purge_expired_activations(db: DBSession, *, now: datetime | None = None) -> int:
    """Housekeeping: drop spent or expired tokens. Not an authorization step."""
    cutoff = now or _now()
    deleted = (
        db.query(AccountActivationToken)
        .filter(AccountActivationToken.expires_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


__all__ = [
    "UNUSABLE_PASSWORD_HASH",
    "ActivationError",
    "activation_state",
    "activation_url",
    "consume_activation",
    "generate_activation_token",
    "hash_activation_token",
    "issue_activation",
    "mask_email",
    "preview_activation",
    "purge_expired_activations",
    "revoke_activation",
]
