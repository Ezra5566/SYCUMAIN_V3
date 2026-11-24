"""Authentication service with password hashing and session management."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from passlib.context import CryptContext
from sqlalchemy.orm import Session as DBSession

from app.config.settings import get_settings
from app.models.identity import Student, StudentStatus, User
from app.models.session import UserSession

settings = get_settings()

# Student record statuses that permit portal access. Everything else —
# suspended, withdrawn, graduated, inactive — must not be able to sign in.
# This is the single definition of that rule; both the login path and the
# session path consult it, so an administrative status change takes effect on
# the next request rather than whenever the session happens to expire.
ACCESS_PERMITTING_STUDENT_STATUSES = frozenset({StudentStatus.ACTIVE})

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

#: Marker stored for accounts that have not established a password yet. It is
#: not a valid bcrypt hash, so verification can never succeed.
UNUSABLE_PASSWORD_HASH = "!"


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash.

    An account provisioned for activation carries the unusable marker instead
    of a hash; no input may satisfy it, and bcrypt must never be asked to try.
    """
    if not hashed_password or hashed_password == UNUSABLE_PASSWORD_HASH:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        # A malformed stored hash is a data fault, not a valid credential.
        return False


def hash_token(token: str) -> str:
    """Hash a session token using SHA-256 for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_session_token() -> str:
    """Generate a cryptographically secure session token."""
    return secrets.token_urlsafe(32)


def create_session(
    db: DBSession,
    user: User,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, UserSession]:
    """Create a new session for a user.

    Returns:
        Tuple of (raw_token, session_record)
    """
    raw_token = generate_session_token()
    token_hash_value = hash_token(raw_token)

    expires_at = datetime.now(UTC) + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)

    session = UserSession(
        token_hash=token_hash_value,
        user_id=user.id,
        expires_at=expires_at,
        user_agent=user_agent[:500] if user_agent else None,
        ip_address=ip_address,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return raw_token, session


def get_session_by_token(db: DBSession, raw_token: str) -> UserSession | None:
    """Look up a session by its raw token."""
    token_hash_value = hash_token(raw_token)
    session = (
        db.query(UserSession)
        .filter(UserSession.token_hash == token_hash_value)
        .first()
    )
    if session and session.expires_at > datetime.now(UTC):
        # Update last accessed time
        session.last_accessed_at = datetime.now(UTC)
        db.commit()
        return session
    return None


def student_record_permits_access(db: DBSession, user: User) -> bool:
    """Whether the user's linked student record allows portal access.

    Staff accounts have no student record and are unaffected. For a student,
    the institutional status is authoritative: an archived, suspended or
    withdrawn student is refused even though their account row remains active.

    Expressed as a targeted existence query rather than ``user.student`` so the
    check costs one indexed lookup and never loads a student row that would
    then sit in the identity map.
    """
    blocked = (
        db.query(Student.id)
        .filter(
            Student.user_id == user.id,
            Student.status.notin_(
                [str(s) for s in ACCESS_PERMITTING_STUDENT_STATUSES]
            ),
        )
        .first()
    )
    return blocked is None


def get_user_from_session(db: DBSession, raw_token: str) -> User | None:
    """Get the user associated with a valid session.

    A live cookie is not by itself sufficient: the account must be enabled and
    any linked student record must still permit access.
    """
    session = get_session_by_token(db, raw_token)
    if session:
        user = db.query(User).filter(User.id == session.user_id).first()
        if user and user.is_active and student_record_permits_access(db, user):
            return user
    return None


def invalidate_session(db: DBSession, raw_token: str) -> bool:
    """Invalidate a session (logout)."""
    token_hash_value = hash_token(raw_token)
    session = (
        db.query(UserSession)
        .filter(UserSession.token_hash == token_hash_value)
        .first()
    )
    if session:
        db.delete(session)
        db.commit()
        return True
    return False


def invalidate_all_user_sessions(db: DBSession, user_id: uuid.UUID) -> int:
    """Invalidate all sessions for a user. Returns count of invalidated sessions."""
    count = db.query(UserSession).filter(UserSession.user_id == user_id).delete()
    db.commit()
    return count


def cleanup_expired_sessions(db: DBSession) -> int:
    """Remove expired sessions. Returns count of removed sessions."""
    count = db.query(UserSession).filter(
        UserSession.expires_at < datetime.now(UTC)
    ).delete()
    db.commit()
    return count
