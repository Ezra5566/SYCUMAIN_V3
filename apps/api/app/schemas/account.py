"""Account (user) schemas for the administrative account lifecycle.

Passwords never appear in any response model. The only exception is the
one-time temporary password returned when an administrator provisions an
account — the caller must hand it to the account holder and cannot retrieve
it again.
"""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Deliberately permissive: the local part allows the characters the campus
# actually uses, and the domain must have a dot. Full RFC 5322 validation
# belongs to the mail layer, not the onboarding form.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

# bcrypt silently truncates beyond 72 bytes, so cap the input we accept.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 72


def validate_password_strength(value: str) -> str:
    """Shared password policy used by account creation and password changes."""
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
        )
    if len(value) > PASSWORD_MAX_LENGTH:
        raise ValueError(
            f"Password must be at most {PASSWORD_MAX_LENGTH} characters."
        )
    if value.strip() != value:
        raise ValueError("Password must not begin or end with whitespace.")
    classes = sum(
        (
            any(c.islower() for c in value),
            any(c.isupper() for c in value),
            any(c.isdigit() for c in value),
            any(not c.isalnum() for c in value),
        )
    )
    if classes < 3:
        raise ValueError(
            "Password must combine at least three of: lowercase, uppercase, "
            "digits, symbols."
        )
    return value


class AccountCreate(BaseModel):
    """Provision a new user account."""

    email: str = Field(..., max_length=255)
    full_name: str = Field(..., min_length=1, max_length=255)
    username: str | None = Field(None, max_length=100)
    roles: list[str] = Field(default_factory=lambda: ["STUDENT"])
    # When omitted a strong temporary password is generated and returned once.
    password: str | None = None
    must_change_password: bool = True
    is_active: bool = True

    # Staff profile fields. They are ignored for student-only accounts, and
    # staff_id may be omitted because no official SCU identifier is assumed.
    staff_id: str | None = Field(None, max_length=50)
    department: str | None = Field(None, max_length=100)
    title: str | None = Field(None, max_length=100)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            raise ValueError("A valid email address is required.")
        return normalized

    @field_validator("password")
    @classmethod
    def _valid_password(cls, value: str | None) -> str | None:
        return None if value is None else validate_password_strength(value)

    @field_validator("roles")
    @classmethod
    def _valid_roles(cls, value: list[str]) -> list[str]:
        cleaned = [r.strip().upper() for r in value if r.strip()]
        if not cleaned:
            raise ValueError("At least one role is required.")
        return cleaned


class AccountUpdate(BaseModel):
    """Partial update of an account. Role changes are deliberately separate."""

    full_name: str | None = Field(None, min_length=1, max_length=255)
    email: str | None = Field(None, max_length=255)
    staff_id: str | None = Field(None, max_length=50)
    department: str | None = Field(None, max_length=100)
    title: str | None = Field(None, max_length=100)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            raise ValueError("A valid email address is required.")
        return normalized


class AccountRolesUpdate(BaseModel):
    """Replace the role set of an account.

    ``reason`` is validated by the router only when the role set actually
    changes, so a caller without permission still receives 403 rather than a
    request-validation error that leaks the endpoint contract.
    """

    roles: list[str] = Field(..., min_length=1)
    reason: str | None = Field(None, max_length=500)

    @field_validator("roles")
    @classmethod
    def _valid_roles(cls, value: list[str]) -> list[str]:
        cleaned = [r.strip().upper() for r in value if r.strip()]
        if not cleaned:
            raise ValueError("At least one role is required.")
        return cleaned


class PasswordChange(BaseModel):
    """Self-service password change; requires the current password."""

    current_password: str = Field(..., min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(..., max_length=PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _valid_password(cls, value: str) -> str:
        return validate_password_strength(value)


class PasswordRecoveryAvailability(BaseModel):
    """Whether self-service recovery can actually work right now.

    Reported so the login screen can hide the flow when no delivery channel is
    configured, instead of offering a link that silently does nothing.
    """

    available: bool
    delivery: str


class PasswordResetRequest(BaseModel):
    """Ask for a reset link."""

    email: str = Field(..., max_length=255)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            raise ValueError("A valid email address is required.")
        return normalized


class PasswordResetRequestResponse(BaseModel):
    """Acknowledgment of a reset request.

    Always reports ``accepted`` so the endpoint cannot be used to discover
    whether an address has an account.

    ``dev_token`` is populated only when the development delivery channel is
    enabled, which is never the case in production.
    """

    accepted: bool
    dev_token: str | None = None
    expires_in_minutes: int | None = None


class PasswordResetSubmit(BaseModel):
    """Complete a reset with a token from the delivery channel."""

    token: str = Field(..., min_length=16, max_length=512)
    new_password: str = Field(..., max_length=PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _valid_password(cls, value: str) -> str:
        return validate_password_strength(value)


class PasswordResetCompletedResponse(BaseModel):
    """Confirmation only. Never echoes the password or the token."""

    reset: bool
    sessions_revoked: bool


class PasswordReset(BaseModel):
    """Administrative password reset. Omit `new_password` to auto-generate."""

    new_password: str | None = None
    must_change_password: bool = True
    invalidate_sessions: bool = True

    @field_validator("new_password")
    @classmethod
    def _valid_password(cls, value: str | None) -> str | None:
        return None if value is None else validate_password_strength(value)


class ActiveUpdate(BaseModel):
    """Activate or deactivate an account."""

    is_active: bool
    # Deactivating revokes sessions by default: leaving a disabled account with
    # a live cookie would be an authorization hole, not a convenience.
    invalidate_sessions: bool = True


# --- Responses ---


class AccountRoleInfo(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class AccountResponse(BaseModel):
    """Safe account representation. Never includes password material."""

    id: uuid.UUID
    email: str
    username: str
    full_name: str
    is_active: bool
    is_superuser: bool
    must_change_password: bool
    roles: list[AccountRoleInfo] = []
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Present only when the account is linked to a student record.
    student_id: uuid.UUID | None = None
    student_number: str | None = None
    has_staff_record: bool = False
    staff_record_id: uuid.UUID | None = None
    staff_id: str | None = None
    staff_department: str | None = None
    staff_title: str | None = None

    model_config = {"from_attributes": True}


class AccountCreatedResponse(BaseModel):
    """Result of provisioning an account.

    `temporary_password` is returned exactly once, at creation. It is not
    stored in plaintext and cannot be retrieved afterwards.
    """

    account: AccountResponse
    temporary_password: str | None = None


class AccountListResponse(BaseModel):
    items: list[AccountResponse]
    total: int
    page: int
    page_size: int


class SessionInfo(BaseModel):
    """One active login session, described without exposing its token."""

    id: uuid.UUID
    created_at: datetime
    last_accessed_at: datetime | None = None
    expires_at: datetime
    user_agent: str | None = None
    ip_address: str | None = None
    is_current: bool = False


class SessionListResponse(BaseModel):
    items: list[SessionInfo]
    total: int


class PasswordChangeResponse(BaseModel):
    """Confirmation only. Never echoes a password or session token."""

    changed: bool
    sessions_revoked: int
    must_change_password: bool
