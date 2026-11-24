"""User account administration.

This is the administrative half of the account lifecycle: provisioning,
activating, deactivating, role assignment, and password reset.

Authorization is deliberately tiered so front-office staff can onboard
students without gaining the ability to create or modify staff accounts:

* ``users.view``            — read accounts
* ``users.manage_students`` — full control over STUDENT-only accounts
* ``users.manage``          — full control over every account

Self-service password and session management lives on ``/auth`` instead.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession

from app.audit import record_audit
from app.auth.activation import (
    ActivationError,
    activation_state,
    activation_url,
    issue_activation,
    revoke_activation,
)
from app.auth.dependencies import CurrentUser
from app.config.settings import get_settings
from app.database.session import get_db
from app.models.identity import Role, User
from app.permissions.checks import has_permission
from app.schemas.account import (
    AccountCreate,
    AccountCreatedResponse,
    AccountListResponse,
    AccountResponse,
    AccountRolesUpdate,
    AccountUpdate,
    ActivationIssue,
    ActivationIssueResponse,
    ActivationStateResponse,
    ActiveUpdate,
    PasswordReset,
    SessionInfo,
    SessionListResponse,
)
from app.services.account import (
    ROLE_STUDENT,
    AccountError,
    account_to_response,
    create_account,
    get_account,
    list_accounts,
    list_sessions,
    reset_account_password,
    revoke_sessions,
    set_account_active,
    set_account_roles,
    update_account,
)
from app.services.migration_report import student_account_migration_report

router = APIRouter(prefix="/users", tags=["users"])

PAGE_SIZE_MAX = 100

# The role set a delegated (users.manage_students) administrator may touch.
DELEGATED_ROLES = frozenset({ROLE_STUDENT})


def _forbidden(message: str) -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail={"error": {"code": "FORBIDDEN", "message": message}},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": "NOT_FOUND", "message": "Account not found."}},
    )


def _conflict(message: str) -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_409_CONFLICT,
        detail={"error": {"code": "CONFLICT", "message": message}},
    )


def _require(user: User, permission: str) -> None:
    if not has_permission(user, permission):
        raise _forbidden("You do not have permission to perform this action.")


def _is_privileged_account(user: User) -> bool:
    """True when the account holds any non-student role."""
    return any(role.name not in DELEGATED_ROLES for role in user.roles)


def _assert_can_administer(actor: User, target: User) -> None:
    """Enforce the delegation boundary.

    A holder of ``users.manage`` may administer any account. A holder of only
    ``users.manage_students`` may administer accounts whose roles are entirely
    within the student set — this is what stops a delegated operator from
    resetting an administrator's password and escalating.
    """
    if has_permission(actor, "users.manage"):
        return
    if has_permission(actor, "users.manage_students") and not _is_privileged_account(
        target
    ):
        return
    raise _forbidden("You may only manage student accounts.")


def _assert_can_assign_roles(actor: User, role_names: list[str]) -> None:
    """Stop a delegated operator from minting privileged accounts."""
    if has_permission(actor, "users.manage"):
        return
    requested = {name.strip().upper() for name in role_names}
    if requested <= DELEGATED_ROLES:
        return
    raise _forbidden("You may only assign the STUDENT role.")


def _count_active_holders(db: DBSession, role_name: str, *, excluding: uuid.UUID) -> int:
    """Count other active accounts holding a role."""
    return (
        db.query(User)
        .join(User.roles)
        .filter(
            Role.name == role_name,
            User.is_active.is_(True),
            User.id != excluding,
        )
        .distinct()
        .count()
    )


def _assert_not_last_admin(
    db: DBSession, target: User, *, action: str, losing_admin: bool
) -> None:
    """Prevent locking every administrator out of the system.

    Refuses to deactivate or demote the final active ADMIN account.
    """
    if not losing_admin:
        return
    if _count_active_holders(db, "ADMIN", excluding=target.id) > 0:
        return
    raise _conflict(
        f"Cannot {action}: this is the only active administrator account."
    )


@router.get("/", response_model=AccountListResponse)
def list_user_accounts(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=PAGE_SIZE_MAX),
    search: str | None = Query(None, max_length=200),
    role: str | None = Query(None, max_length=50),
    is_active: bool | None = Query(None),
):
    """List accounts with pagination, search, and role/status filtering."""
    _require(current_user, "users.view")

    # A delegated operator's view is limited to the accounts they can act on.
    if not has_permission(current_user, "users.manage"):
        role = ROLE_STUDENT

    users, total = list_accounts(
        db,
        page=page,
        page_size=page_size,
        search=search,
        role=role,
        is_active=is_active,
    )
    return AccountListResponse(
        items=[AccountResponse(**account_to_response(db, u)) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/",
    response_model=AccountCreatedResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def create_user_account(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    data: AccountCreate,
    request: Request,
):
    """Provision an account.

    When no password is supplied one is generated and returned exactly once.
    """
    _require(current_user, "users.view")
    if not (
        has_permission(current_user, "users.manage")
        or has_permission(current_user, "users.manage_students")
    ):
        raise _forbidden("You do not have permission to create accounts.")

    _assert_can_assign_roles(current_user, data.roles)

    try:
        user, temporary_password = create_account(
            db,
            email=data.email,
            full_name=data.full_name,
            username=data.username,
            roles=data.roles,
            password=data.password,
            must_change_password=data.must_change_password,
            is_active=data.is_active,
            staff_id=data.staff_id,
            department=data.department,
            title=data.title,
        )
    except AccountError as exc:
        raise _conflict(str(exc)) from exc

    record_audit(
        db,
        action="account.created",
        actor=current_user,
        entity_type="user",
        entity_id=user.id,
        context={"roles": [r.name for r in user.roles], "is_active": user.is_active},
        request=request,
    )
    db.commit()
    db.refresh(user)

    return AccountCreatedResponse(
        account=AccountResponse(**account_to_response(db, user)),
        temporary_password=temporary_password,
    )


@router.get("/{user_id}", response_model=AccountResponse)
def get_user_account(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    user_id: uuid.UUID,
):
    """Read a single account."""
    _require(current_user, "users.view")
    user = get_account(db, user_id)
    if user is None:
        raise _not_found()
    _assert_can_administer(current_user, user)
    return AccountResponse(**account_to_response(db, user))


@router.patch("/{user_id}", response_model=AccountResponse)
def update_user_account(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    user_id: uuid.UUID,
    data: AccountUpdate,
    request: Request,
):
    """Update an account's name or email."""
    _require(current_user, "users.view")
    user = get_account(db, user_id)
    if user is None:
        raise _not_found()
    _assert_can_administer(current_user, user)

    try:
        updated = update_account(
            db,
            user,
            full_name=data.full_name,
            email=data.email,
            staff_id=data.staff_id,
            department=data.department,
            title=data.title,
            staff_fields_set=bool(
                {"staff_id", "department", "title"} & data.model_fields_set
            ),
        )
    except AccountError as exc:
        raise _conflict(str(exc)) from exc

    record_audit(
        db,
        action="account.updated",
        actor=current_user,
        entity_type="user",
        entity_id=updated.id,
        context={"fields": sorted(data.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    db.commit()
    db.refresh(updated)
    return AccountResponse(**account_to_response(db, updated))


@router.patch("/{user_id}/roles", response_model=AccountResponse)
def update_user_roles(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    user_id: uuid.UUID,
    data: AccountRolesUpdate,
    request: Request,
):
    """Replace an account's roles.

    Both the *current* roles and the *requested* roles must be within the
    caller's authority, so a delegated operator can neither promote a student
    nor demote a colleague.
    """
    _require(current_user, "users.manage")
    user = get_account(db, user_id)
    if user is None:
        raise _not_found()
    _assert_can_administer(current_user, user)
    _assert_can_assign_roles(current_user, data.roles)

    previous = sorted(r.name for r in user.roles)
    requested = sorted({name.strip().upper() for name in data.roles})
    reason = (data.reason or "").strip()
    if requested != previous and len(reason) < 3:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "ROLE_CHANGE_REASON_REQUIRED",
                    "message": "A reason of at least 3 characters is required for a role change.",
                }
            },
        )

    was_admin = any(r.name == "ADMIN" for r in user.roles)
    _assert_not_last_admin(
        db,
        user,
        action="change roles",
        losing_admin=was_admin and "ADMIN" not in requested,
    )

    try:
        updated = set_account_roles(db, user, data.roles)
    except AccountError as exc:
        # An unknown role name is a bad request, not a server fault.
        raise _conflict(str(exc)) from exc

    # A role change is a privilege change. Existing browser sessions cache the
    # previous identity and permission set, so they must not survive the
    # transition: otherwise a demoted account can keep rendering Management
    # controls until it happens to reload, and a promoted account cannot see
    # its new scope at all. Revoking here also makes the next request prove the
    # new role through a fresh login.
    sessions_revoked = (
        revoke_sessions(db, updated.id) if requested != previous else 0
    )

    record_audit(
        db,
        action="account.roles_changed",
        actor=current_user,
        entity_type="user",
        entity_id=updated.id,
        context={
            "from": previous,
            "to": requested,
            "reason": reason,
            "logins_revoked": sessions_revoked,
        },
        request=request,
    )
    db.commit()
    db.refresh(updated)
    return AccountResponse(**account_to_response(db, updated))


@router.patch("/{user_id}/active", response_model=AccountResponse)
def update_user_active(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    user_id: uuid.UUID,
    data: ActiveUpdate,
    request: Request,
):
    """Activate or deactivate an account, revoking sessions when disabling."""
    _require(current_user, "users.view")
    user = get_account(db, user_id)
    if user is None:
        raise _not_found()
    _assert_can_administer(current_user, user)

    if user.id == current_user.id and not data.is_active:
        raise _conflict("You cannot deactivate your own account.")

    is_admin = any(r.name == "ADMIN" for r in user.roles)
    _assert_not_last_admin(
        db, user, action="deactivate", losing_admin=is_admin and not data.is_active
    )

    revoked = set_account_active(
        db,
        user,
        is_active=data.is_active,
        invalidate_sessions=data.invalidate_sessions,
    )

    # Two explicit calls rather than a conditional expression: the audit
    # vocabulary contract test scans for literal action names, and a computed
    # one would be invisible to it.
    if data.is_active:
        record_audit(
            db,
            action="account.activated",
            actor=current_user,
            entity_type="user",
            entity_id=user.id,
            context={"sessions_revoked": revoked},
            request=request,
        )
    else:
        record_audit(
            db,
            action="account.deactivated",
            actor=current_user,
            entity_type="user",
            entity_id=user.id,
            context={"sessions_revoked": revoked},
            request=request,
        )
    db.commit()
    db.refresh(user)
    return AccountResponse(**account_to_response(db, user))


@router.post("/{user_id}/reset-password")
def reset_user_password(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    user_id: uuid.UUID,
    request: Request,
    data: PasswordReset | None = None,
):
    """Reset an account's password and revoke its sessions.

    Returns the new password when one was generated. The password is never
    stored in plaintext and cannot be read back later.
    """
    _require(current_user, "users.view")
    user = get_account(db, user_id)
    if user is None:
        raise _not_found()
    _assert_can_administer(current_user, user)

    payload = data or PasswordReset()
    password, revoked = reset_account_password(
        db,
        user,
        payload.new_password,
        must_change_password=payload.must_change_password,
    )

    record_audit(
        db,
        action="account.password_reset",
        actor=current_user,
        entity_type="user",
        entity_id=user.id,
        context={"sessions_revoked": revoked, "generated": payload.new_password is None},
        request=request,
    )
    db.commit()

    return {
        "user_id": str(user.id),
        "temporary_password": password,
        "must_change_password": user.must_change_password,
        "sessions_revoked": revoked,
    }


@router.get("/{user_id}/sessions", response_model=SessionListResponse)
def list_user_sessions(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    user_id: uuid.UUID,
):
    """List an account's live sessions. Tokens are never returned."""
    _require(current_user, "users.view")
    user = get_account(db, user_id)
    if user is None:
        raise _not_found()
    _assert_can_administer(current_user, user)

    pairs = list_sessions(db, user_id)
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


@router.post("/{user_id}/sessions/revoke")
def revoke_user_sessions(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    user_id: uuid.UUID,
    request: Request,
):
    """Force an account to sign out everywhere."""
    _require(current_user, "users.view")
    user = get_account(db, user_id)
    if user is None:
        raise _not_found()
    _assert_can_administer(current_user, user)

    revoked = revoke_sessions(db, user_id)

    record_audit(
        db,
        action="account.sessions_revoked",
        actor=current_user,
        entity_type="user",
        entity_id=user.id,
        context={"revoked": revoked},
        request=request,
    )
    db.commit()
    return {"user_id": str(user.id), "sessions_revoked": revoked}


# --- Account activation ----------------------------------------------------


def _activation_error(exc: ActivationError) -> HTTPException:
    return HTTPException(
        status_code=(
            http_status.HTTP_404_NOT_FOUND
            if exc.not_found
            else http_status.HTTP_409_CONFLICT
        ),
        detail={"error": {"code": exc.code, "message": exc.message}},
    )


@router.get("/migration/account-report")
def migration_account_report(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
):
    """Institutional report of provisioned student accounts.

    Contains counts and masked addresses only: no password and no activation
    token can appear in a document that gets exported and forwarded.
    """
    _require(current_user, "users.view")
    return student_account_migration_report(db)


@router.get("/{user_id}/activation", response_model=ActivationStateResponse)
def get_activation_state(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    user_id: uuid.UUID,
):
    """Whether this account still needs activation. Never returns the link."""
    _require(current_user, "users.view")
    user = get_account(db, user_id)
    if user is None:
        raise _not_found()
    _assert_can_administer(current_user, user)
    return ActivationStateResponse(**activation_state(db, user))


@router.post("/{user_id}/activation", response_model=ActivationIssueResponse)
def issue_activation_link(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    user_id: uuid.UUID,
    request: Request,
    data: ActivationIssue | None = None,
):
    """Issue (or re-issue) a single-use activation link for an account.

    Staff-initiated issues require an explicit identity-verification assertion,
    because handing out a working link to the wrong person is the whole risk of
    this flow. The audit entry records that verification, never the token.
    """
    _require(current_user, "users.view")
    user = get_account(db, user_id)
    if user is None:
        raise _not_found()
    _assert_can_administer(current_user, user)

    payload = data or ActivationIssue()
    try:
        record, raw_token = issue_activation(
            db,
            user,
            actor_id=current_user.id,
            reason="ADMIN",
            delivery=payload.delivery,
            identity_verified=payload.identity_verified,
            verification_reference=payload.verification_reference,
            request=request,
        )
    except ActivationError as exc:
        db.rollback()
        raise _activation_error(exc) from exc

    db.commit()
    db.refresh(record)

    return ActivationIssueResponse(
        user_id=user.id,
        state=activation_state(db, user)["state"],
        expires_at=record.expires_at,
        delivery=record.delivery,
        activation_url=(
            activation_url(raw_token)
            if get_settings().ACTIVATION_RETURN_LINK
            else None
        ),
    )


@router.delete("/{user_id}/activation", status_code=204)
def revoke_activation_link(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    user_id: uuid.UUID,
    request: Request,
):
    """Withdraw an unused activation link."""
    _require(current_user, "users.view")
    user = get_account(db, user_id)
    if user is None:
        raise _not_found()
    _assert_can_administer(current_user, user)
    revoke_activation(db, user, actor_id=current_user.id, request=request)
    db.commit()
