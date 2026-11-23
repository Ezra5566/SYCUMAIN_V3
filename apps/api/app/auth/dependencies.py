"""Authentication dependencies for FastAPI.

Uses database-backed sessions with HttpOnly cookies.

This module also owns the *forced password change* rule. A temporary password
exists to be replaced; until it is, the account may sign in, read its own
identity, manage its sessions, and change the password — nothing else. The rule
lives here rather than in each router because a per-router check is one new
endpoint away from being forgotten.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from app.auth.service import get_user_from_session
from app.database.session import get_db
from app.models.identity import User

SESSION_COOKIE_NAME = "session_token"

#: Paths an account may still reach while ``must_change_password`` is set.
#: Everything needed to finish the change, plus logout so the user is never
#: trapped in a session they cannot leave.
PASSWORD_CHANGE_ALLOWED_PATHS: tuple[str, ...] = (
    "/auth/me",
    "/auth/logout",
    "/auth/password/change",
    "/auth/sessions",
    "/auth/sessions/revoke-others",
    "/auth/password/reset",
    "/auth/password/reset-request",
    "/auth/password/reset-availability",
)


def password_change_path_allowed(path: str) -> bool:
    """Whether ``path`` is reachable before the temporary password is replaced."""
    normalized = path.rstrip("/")
    return any(normalized.endswith(allowed) for allowed in PASSWORD_CHANGE_ALLOWED_PATHS)


def get_current_user(
    request: Request,
    db: Annotated[DBSession, Depends(get_db)],
) -> User:
    """Get the current authenticated user from the session cookie.

    Raises:
        HTTPException: 401 if not authenticated or session is invalid.
    """
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Not authenticated. Please log in.",
                }
            },
            headers={"WWW-Authenticate": "Cookie"},
        )

    user = get_user_from_session(db, raw_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Session expired or invalid. Please log in again.",
                }
            },
            headers={"WWW-Authenticate": "Cookie"},
        )

    return user


def get_current_active_user(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get the current active user, enforcing the temporary-password rule."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "ACCOUNT_DISABLED",
                    "message": "Your account has been disabled.",
                }
            },
        )

    # A client-side prompt is not a control: the same session cookie can call
    # the API directly. The server decides, and the client is told which code
    # to react to.
    if current_user.must_change_password and not password_change_path_allowed(
        request.url.path
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "PASSWORD_CHANGE_REQUIRED",
                    "message": (
                        "You must change your temporary password before using "
                        "the portal."
                    ),
                }
            },
        )

    return current_user


# Type aliases for convenience
CurrentUser = Annotated[User, Depends(get_current_active_user)]
