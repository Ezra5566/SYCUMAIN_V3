"""Authentication router with login, logout, and me endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.audit import record_audit
from app.auth.activation import (
    ActivationError,
    consume_activation,
    preview_activation,
)
from app.auth.dependencies import (
    SESSION_COOKIE_NAME,
    CurrentUser,
)
from app.auth.recovery import (
    RecoveryError,
    consume_reset_token,
    delivery_available,
    request_password_reset,
)
from app.auth.service import (
    create_session,
    get_user_from_session,
    hash_token,
    invalidate_session,
    student_record_permits_access,
    verify_password,
)
from app.config.settings import get_settings
from app.core.ratelimit import (
    Limit,
    RateLimitError,
)
from app.core.ratelimit import (
    check as check_rate_limit,
)
from app.core.ratelimit import (
    clear as clear_rate_limit,
)
from app.database.session import get_db
from app.models.identity import User
from app.schemas.account import (
    ActivationComplete,
    ActivationCompletedResponse,
    ActivationPreviewResponse,
    PasswordChange,
    PasswordChangeResponse,
    PasswordRecoveryAvailability,
    PasswordResetCompletedResponse,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    PasswordResetSubmit,
    SessionInfo,
    SessionListResponse,
)
from app.services.account import (
    AccountError,
    change_own_password,
    list_sessions,
    revoke_sessions,
    temporary_password_expired,
)
from app.services.mailer import reset_email_body, send_email

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


# --- Rate limiting ---------------------------------------------------------
# The limits are checked before any credential work, so a caller who has spent
# their allowance cannot learn whether an address exists by timing the response
# or by the message it receives.


def _login_ip_limit() -> Limit:
    return Limit(
        "login:ip",
        settings.RATE_LIMIT_LOGIN_PER_IP,
        settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
    )


def _login_account_limit() -> Limit:
    return Limit(
        "login:account",
        settings.RATE_LIMIT_LOGIN_PER_ACCOUNT,
        settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
    )


def _rate_limited(exc: RateLimitError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": {
                "code": "RATE_LIMITED",
                "message": "Too many attempts. Please wait and try again.",
            }
        },
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


def _enforce_rate_limit(
    db: DBSession,
    request: Request,
    *,
    limits: list[tuple[Limit, str]],
    scope: str,
) -> None:
    """Count an attempt against each limit, or raise 429.

    The audit entry records the *scope* only. Storing the address or email
    would turn a brute-force attempt into a log of the person being attacked.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return

    try:
        for limit, value in limits:
            check_rate_limit(db, limit=limit, value=value)
    except RateLimitError as exc:
        record_audit(
            db,
            action="auth.rate_limited",
            entity_type=None,
            context={"scope": scope},
            request=request,
        )
        db.commit()
        raise _rate_limited(exc) from exc


# --- Request/Response Schemas ---


class LoginRequest(BaseModel):
    """Login request body."""

    email: str
    password: str


class LoginResponse(BaseModel):
    """Login success response."""

    user: "UserResponse"


class UserResponse(BaseModel):
    """Safe user representation (no sensitive fields)."""

    id: uuid.UUID
    email: str
    username: str
    full_name: str
    is_active: bool
    must_change_password: bool = False
    roles: list["RoleResponse"]
    permissions: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleResponse(BaseModel):
    """Role representation."""

    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    """Error response."""

    error: dict


# --- Endpoints ---


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    response: Response,
    request: Request,
    db: Annotated[DBSession, Depends(get_db)],
) -> LoginResponse:
    """Authenticate a user and establish a session.

    On success: sets an HttpOnly session cookie.
    On failure: returns generic error (does not reveal whether account exists).
    """
    client_ip = _client_ip(request) or "unknown"
    account_key = f"{client_ip}:{body.email.strip().lower()}"
    _enforce_rate_limit(
        db,
        request,
        limits=[
            (_login_ip_limit(), client_ip),
            (_login_account_limit(), account_key),
        ],
        scope="login",
    )

    # Find user by email
    user = db.query(User).filter(User.email == body.email).first()


    # A provisioned account has no password at all: it is waiting for its
    # single-use activation link. Answered before any credential comparison,
    # because there is no credential to compare — and because a student who
    # has just been registered needs to be told what to do. This does disclose
    # that an address has a pending account, the same disclosure the password
    # reset endpoint deliberately avoids; it is rate limited and audited.
    if user is not None and user.activation_required:
        record_audit(
            db,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id,
            context={"reason": "activation_required"},
            request=request,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "ACCOUNT_NOT_ACTIVATED",
                    "message": (
                        "This account has not been activated yet. Use the "
                        "activation link issued at registration."
                    ),
                }
            },
        )

    # Verify credentials (constant-time comparison via bcrypt)
    if not user or not verify_password(body.password, user.hashed_password):
        # Record the attempt without recording the submitted address or
        # password: failed logins are exactly where credentials leak into logs.
        record_audit(
            db,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id if user else None,
            context={"reason": "invalid_credentials"},
            request=request,
        )
        db.commit()
        # Generic error - do not reveal whether email exists
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "INVALID_CREDENTIALS",
                    "message": "Invalid email or password.",
                }
            },
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "ACCOUNT_DISABLED",
                    "message": "Your account has been disabled.",
                }
            },
        )

    # An enabled account is still refused when the linked student record is not
    # active (archived, suspended, withdrawn, graduated). Reported separately
    # from ACCOUNT_DISABLED so the office can tell the two apart when a student
    # calls, and recorded against the same event name with a distinguishing
    # reason so the audit vocabulary stays fixed.
    if not student_record_permits_access(db, user):
        record_audit(
            db,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id,
            context={"reason": "student_record_inactive"},
            request=request,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "STUDENT_RECORD_INACTIVE",
                    "message": (
                        "Your student record is not active. "
                        "Please contact the international office."
                    ),
                }
            },
        )

    # A temporary password is time-limited. Checked after the credential is
    # verified, so an expired credential is only reported to whoever holds it,
    # and before a session is created, so it cannot be used for anything at all.
    if temporary_password_expired(user):
        record_audit(
            db,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id,
            context={"reason": "temporary_password_expired"},
            request=request,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "TEMPORARY_PASSWORD_EXPIRED",
                    "message": (
                        "This temporary password has expired. Contact the "
                        "international office for a new one."
                    ),
                }
            },
        )

    # Create session and stamp the successful sign-in time. Both share one
    # commit with the audit entry below. A successful sign-in also resets this
    # caller's counters: a person who mistyped a few times should not carry
    # that history into their next session.
    clear_rate_limit(db, limit=_login_ip_limit(), value=client_ip)
    clear_rate_limit(db, limit=_login_account_limit(), value=account_key)

    raw_token, session = create_session(
        db=db,
        user=user,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    user.last_login_at = datetime.now(UTC)

    # Set HttpOnly cookie
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.SESSION_EXPIRE_MINUTES * 60,
        path="/",
    )

    record_audit(
        db,
        action="auth.login_succeeded",
        actor=user,
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    db.commit()

    # Build response with roles and permissions
    from app.permissions.checks import get_user_permissions

    permissions = sorted(get_user_permissions(user))

    return LoginResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            is_active=user.is_active,
            must_change_password=user.must_change_password,
            roles=[RoleResponse(id=r.id, name=r.name) for r in user.roles],
            permissions=permissions,
            created_at=user.created_at,
        )
    )


@router.post("/logout")
def logout(
    response: Response,
    request: Request,
    db: Annotated[DBSession, Depends(get_db)],
) -> dict:
    """Invalidate the current session (logout)."""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        # Resolve the identity before invalidating so the audit trail records
        # who logged out, not just that a session ended.
        session_user = get_user_from_session(db, raw_token)
        if session_user is not None:
            record_audit(
                db,
                action="auth.logout",
                actor=session_user,
                entity_type="user",
                entity_id=session_user.id,
                request=request,
            )
        invalidate_session(db, raw_token)
        db.commit()

    # Clear the cookie
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )

    return {"message": "Logged out successfully"}


@router.get("/me")
def get_me(
    current_user: CurrentUser,
) -> dict:
    """Get the current authenticated user's identity and permissions."""
    from app.permissions.checks import get_user_permissions

    permissions = sorted(get_user_permissions(current_user))

    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "is_active": current_user.is_active,
        "is_superuser": current_user.is_superuser,
        "must_change_password": current_user.must_change_password,
        "roles": [{"id": str(r.id), "name": r.name} for r in current_user.roles],
        "permissions": permissions,
        "created_at": current_user.created_at.isoformat(),
    }


# --- Self-service password and session management ---


def _current_token_hash(request: Request) -> str | None:
    """Hash of the caller's own session token, used to flag 'this device'."""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    return hash_token(raw_token) if raw_token else None


@router.post("/password/change", response_model=PasswordChangeResponse)
def change_password(
    body: PasswordChange,
    request: Request,
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
) -> PasswordChangeResponse:
    """Change the caller's own password.

    Requires the current password, so a hijacked session alone cannot lock the
    real owner out. The caller's own session survives; every other session is
    revoked, because a password change is how a user responds to suspected
    compromise.
    """
    try:
        change_own_password(
            db,
            current_user,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except AccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "PASSWORD_CHANGE_REJECTED", "message": str(exc)}},
        ) from exc

    revoked = revoke_sessions(
        db, current_user.id, keep_token_hash=_current_token_hash(request)
    )

    record_audit(
        db,
        action="auth.password_changed",
        actor=current_user,
        entity_type="user",
        entity_id=current_user.id,
        context={"sessions_revoked": revoked},
        request=request,
    )
    db.commit()
    db.refresh(current_user)

    return PasswordChangeResponse(
        changed=True,
        sessions_revoked=revoked,
        must_change_password=current_user.must_change_password,
    )


@router.get("/sessions", response_model=SessionListResponse)
def get_own_sessions(
    request: Request,
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
) -> SessionListResponse:
    """List the caller's own active sessions (device, time, IP)."""
    current_hash = _current_token_hash(request)
    pairs = list_sessions(db, current_user.id, current_token_hash=current_hash)
    items = [
        SessionInfo(
            id=session.id,
            created_at=session.created_at,
            last_accessed_at=session.last_accessed_at,
            expires_at=session.expires_at,
            user_agent=session.user_agent,
            ip_address=session.ip_address,
            is_current=is_current,
        )
        for session, is_current in pairs
    ]
    return SessionListResponse(items=items, total=len(items))


@router.post("/sessions/revoke-others")
def revoke_other_sessions(
    request: Request,
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
) -> dict:
    """Sign out every device except this one."""
    revoked = revoke_sessions(
        db, current_user.id, keep_token_hash=_current_token_hash(request)
    )

    record_audit(
        db,
        action="auth.sessions_revoked",
        actor=current_user,
        entity_type="user",
        entity_id=current_user.id,
        context={"revoked": revoked},
        request=request,
    )
    db.commit()
    return {"sessions_revoked": revoked}


# --- Password recovery -----------------------------------------------------
#
# Unauthenticated by necessity: the entire point is that the user cannot sign
# in. Protection comes from the token design (hashed at rest, single use, short
# lived) rather than from a session.


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/password/reset-availability", response_model=PasswordRecoveryAvailability)
def password_reset_availability() -> PasswordRecoveryAvailability:
    """Tell the client whether self-service recovery is usable.

    Without this the login screen would have to assume, and would either hide a
    working feature or offer a dead one.
    """
    settings_value = settings.PASSWORD_RESET_DELIVERY
    return PasswordRecoveryAvailability(
        available=delivery_available(),
        delivery=settings_value,
    )


@router.post(
    "/password/reset-request",
    response_model=PasswordResetRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_reset(
    body: PasswordResetRequest,
    request: Request,
    db: Annotated[DBSession, Depends(get_db)],
) -> PasswordResetRequestResponse:
    """Request a password reset link.

    The response is identical for a known and an unknown address, so this
    endpoint cannot be used to enumerate accounts. Throttling is keyed on the
    (address, submitted email) pair as well as the address, so probing one
    mailbox from many addresses is limited without locking the mailbox itself.
    """
    client_ip = _client_ip(request) or "unknown"
    _enforce_rate_limit(
        db,
        request,
        limits=[
            (
                Limit(
                    "reset-request:ip",
                    settings.RATE_LIMIT_RESET_REQUEST_PER_IP,
                    settings.RATE_LIMIT_RESET_WINDOW_SECONDS,
                ),
                client_ip,
            ),
            (
                Limit(
                    "reset-request:email",
                    settings.RATE_LIMIT_RESET_REQUEST_PER_EMAIL,
                    settings.RATE_LIMIT_RESET_WINDOW_SECONDS,
                ),
                f"{client_ip}:{body.email}",
            ),
        ],
        scope="password_reset_request",
    )

    user, raw_token = request_password_reset(
        db,
        email=body.email,
        ip_address=_client_ip(request),
        request=request,
    )

    # Only the development channel ever sees the token. With SMTP configured
    # the link is mailed inline, from this request, and never stored: the body
    # contains a working credential, so an outbox row would be a second copy of
    # it at rest.
    dev_token = raw_token if settings.PASSWORD_RESET_DELIVERY == "dev" else None
    if raw_token is not None and settings.PASSWORD_RESET_DELIVERY == "smtp":
        link = (
            f"{settings.ACTIVATION_LINK_BASE.rstrip('/')}"
            f"/reset-password?token={raw_token}"
        )
        delivery = send_email(
            to=user.email,
            subject="Reset your Student Portal password",
            body=reset_email_body(link, settings.PASSWORD_RESET_EXPIRE_MINUTES),
            purpose="password_reset",
        )
        if not delivery.sent:
            # Never surfaced to the caller — the response must stay identical
            # for known and unknown addresses — but an operator can see that a
            # reset was issued and not delivered.
            record_audit(
                db,
                action="auth.password_reset_delivery_failed",
                actor=user,
                entity_type="user",
                entity_id=user.id,
                context={"reason": delivery.detail},
                request=request,
            )
            db.commit()

    return PasswordResetRequestResponse(
        accepted=True,
        dev_token=dev_token,
        expires_in_minutes=(
            settings.PASSWORD_RESET_EXPIRE_MINUTES if dev_token else None
        ),
    )


@router.post("/password/reset", response_model=PasswordResetCompletedResponse)
def complete_reset(
    body: PasswordResetSubmit,
    request: Request,
    db: Annotated[DBSession, Depends(get_db)],
) -> PasswordResetCompletedResponse:
    """Set a new password from a reset token.

    On success every existing session is revoked: recovery proves control of
    the mailbox, not of any device that was already signed in.
    """
    _enforce_rate_limit(
        db,
        request,
        limits=[
            (
                Limit(
                    "reset-submit:ip",
                    settings.RATE_LIMIT_RESET_SUBMIT_PER_IP,
                    settings.RATE_LIMIT_RESET_WINDOW_SECONDS,
                ),
                _client_ip(request) or "unknown",
            )
        ],
        scope="password_reset_submit",
    )

    try:
        consume_reset_token(
            db,
            token=body.token,
            new_password=body.new_password,
            request=request,
        )
    except RecoveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_RESET_TOKEN",
                    "message": "This reset link is invalid or has expired. "
                    "Request a new one.",
                }
            },
        ) from exc

    return PasswordResetCompletedResponse(reset=True, sessions_revoked=True)


# --- Account activation ----------------------------------------------------
# A migrated account has no password. These two endpoints are the only way to
# turn a single-use activation link into one. Neither ever returns a password,
# and the token is never logged.


@router.get("/activation/{token}", response_model=ActivationPreviewResponse)
def activation_preview(
    token: str,
    request: Request,
    db: Annotated[DBSession, Depends(get_db)],
) -> ActivationPreviewResponse:
    """Describe an activation link without consuming it."""
    _enforce_rate_limit(
        db,
        request,
        limits=[
            (
                Limit(
                    "activation-preview:ip",
                    settings.RATE_LIMIT_RESET_REQUEST_PER_IP,
                    settings.RATE_LIMIT_RESET_WINDOW_SECONDS,
                ),
                _client_ip(request) or "unknown",
            )
        ],
        scope="activation_preview",
    )
    return ActivationPreviewResponse(**preview_activation(db, token))


@router.post("/activation", response_model=ActivationCompletedResponse)
def complete_activation(
    body: ActivationComplete,
    request: Request,
    db: Annotated[DBSession, Depends(get_db)],
) -> ActivationCompletedResponse:
    """Establish the account's own password from an activation token.

    The token is single-use and expires; completing activation revokes any
    session that existed before the account had a password.
    """
    _enforce_rate_limit(
        db,
        request,
        limits=[
            (
                Limit(
                    "activation:ip",
                    settings.RATE_LIMIT_RESET_SUBMIT_PER_IP,
                    settings.RATE_LIMIT_RESET_WINDOW_SECONDS,
                ),
                _client_ip(request) or "unknown",
            )
        ],
        scope="account_activation",
    )

    try:
        user = consume_activation(
            db,
            token=body.token,
            password=body.new_password,
            request=request,
        )
    except ActivationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if exc.not_found
                else status.HTTP_400_BAD_REQUEST
            ),
            detail={"error": {"code": exc.code, "message": exc.message}},
        ) from exc

    db.commit()
    return ActivationCompletedResponse(activated=True, email=user.email)
