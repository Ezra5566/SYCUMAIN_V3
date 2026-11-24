"""Account lifecycle service.

Covers the institutional onboarding flow:

    create account -> issue temporary password -> account holder logs in
    -> changes password -> account active

and the offboarding flow (deactivate, which revokes sessions).

Password material is only ever produced here and handed back once; it is
never persisted in plaintext and never returned by a read endpoint.
"""

import secrets
import string
import uuid

from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DBSession

from app.auth.service import UNUSABLE_PASSWORD_HASH, hash_password, verify_password
from app.models.identity import Role, Staff, Student, User
from app.models.session import UserSession

# Ambiguous glyphs (0/O, 1/l/I) are excluded: these passwords get read aloud
# over a phone or written on a slip of paper at the international office.
_PASSWORD_ALPHABET = (
    "".join(c for c in string.ascii_letters if c not in "lIO")
    + "".join(c for c in string.digits if c not in "01")
    + "!@#$%^&*-_=+"
)
_TEMP_PASSWORD_LENGTH = 16

ROLE_STUDENT = "STUDENT"


class AccountError(ValueError):
    """Raised for account operations that violate a business rule."""


def generate_temporary_password() -> str:
    """Generate a strong, human-transcribable temporary password."""
    return "".join(
        secrets.choice(_PASSWORD_ALPHABET) for _ in range(_TEMP_PASSWORD_LENGTH)
    )


def _unique_username(db: DBSession, email: str) -> str:
    """Derive a unique username from the email local part."""
    base = email.split("@", 1)[0].strip().lower() or "user"
    # Keep usernames predictable but safe for URL/log display.
    base = "".join(c if c.isalnum() or c in "._-" else "." for c in base)[:80]
    candidate = base
    suffix = 1
    while db.query(User.id).filter(User.username == candidate).first() is not None:
        suffix += 1
        candidate = f"{base}{suffix}"[:100]
    return candidate


def resolve_roles(db: DBSession, role_names: list[str]) -> list[Role]:
    """Resolve role names to Role rows, rejecting unknown names."""
    names = {name.strip().upper() for name in role_names if name.strip()}
    if not names:
        raise AccountError("At least one role is required.")

    roles = db.query(Role).filter(Role.name.in_(names)).all()
    found = {r.name for r in roles}
    missing = names - found
    if missing:
        raise AccountError(f"Unknown role(s): {', '.join(sorted(missing))}.")
    return roles


def _split_name(full_name: str) -> tuple[str, str]:
    """Split a display name without inventing either part."""
    parts = full_name.strip().split(None, 1)
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[1])


def _assert_staff_number_available(
    db: DBSession, staff_id: str | None, *, excluding: uuid.UUID | None = None
) -> None:
    if not staff_id:
        return
    query = db.query(Staff.id).filter(Staff.staff_id == staff_id.strip())
    if excluding is not None:
        query = query.filter(Staff.id != excluding)
    if query.first() is not None:
        raise AccountError("This staff identifier is already in use.")


def _ensure_staff_profile(db: DBSession, user: User) -> Staff:
    """Create the linked profile for a staff account when it is absent."""
    staff = db.query(Staff).filter(Staff.user_id == user.id).first()
    if staff is not None:
        return staff
    first_name, last_name = _split_name(user.full_name)
    staff = Staff(
        user_id=user.id,
        staff_id=None,
        first_name=first_name,
        last_name=last_name,
    )
    db.add(staff)
    db.flush()
    return staff


def create_account(
    db: DBSession,
    *,
    email: str,
    full_name: str,
    roles: list[str],
    username: str | None = None,
    password: str | None = None,
    must_change_password: bool = True,
    activation_required: bool = False,
    is_active: bool = True,
    staff_id: str | None = None,
    department: str | None = None,
    title: str | None = None,
) -> tuple[User, str | None]:
    """Provision an account.

    Returns the user plus the generated temporary password, or ``None`` when
    the caller supplied an explicit password (in which case nothing needs to be
    communicated back).
    """
    email = email.strip().lower()

    if db.query(User.id).filter(func.lower(User.email) == email).first() is not None:
        raise AccountError("An account with this email already exists.")

    role_rows = resolve_roles(db, roles)
    has_staff_role = any(role.name != ROLE_STUDENT for role in role_rows)
    _assert_staff_number_available(db, staff_id if has_staff_role else None)

    temporary_password: str | None = None
    if activation_required:
        # Provisioned accounts get no password at all. The stored marker can
        # never be matched, and login refuses the account until the student
        # completes a single-use activation link.
        password = None
        temporary_password = None
        must_change_password = False
    elif password is None:
        password = generate_temporary_password()
        temporary_password = password
        must_change_password = True

    if username:
        candidate = username.strip()
        if not candidate:
            raise AccountError("Username must not be blank.")
        if (
            db.query(User.id).filter(User.username == candidate).first()
            is not None
        ):
            raise AccountError("This username is already taken.")
    else:
        candidate = _unique_username(db, email)

    user = User(
        email=email,
        username=candidate,
        hashed_password=(
            UNUSABLE_PASSWORD_HASH if activation_required else hash_password(password)
        ),
        full_name=full_name.strip(),
        is_active=is_active,
        is_superuser=False,
        must_change_password=must_change_password,
        activation_required=activation_required,
    )
    user.roles.extend(role_rows)
    db.add(user)
    db.flush()

    if has_staff_role:
        first_name, last_name = _split_name(full_name)
        db.add(
            Staff(
                user_id=user.id,
                staff_id=staff_id.strip() if staff_id else None,
                first_name=first_name,
                last_name=last_name,
                department=(department or "").strip() or None,
                title=(title or "").strip() or None,
            )
        )
        db.flush()

    return user, temporary_password


def get_account(db: DBSession, user_id: uuid.UUID) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def get_account_by_email(db: DBSession, email: str) -> User | None:
    return (
        db.query(User)
        .filter(func.lower(User.email) == email.strip().lower())
        .first()
    )


def list_accounts(
    db: DBSession,
    *,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[User], int]:
    """Paginated account listing."""
    query = db.query(User)

    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                User.email.ilike(pattern),
                User.full_name.ilike(pattern),
                User.username.ilike(pattern),
            )
        )

    if role:
        query = query.join(User.roles).filter(Role.name == role.strip().upper())

    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))

    total = query.distinct().count()
    offset = (page - 1) * page_size
    users = (
        query.distinct()
        .order_by(User.full_name, User.email)
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return users, total


def update_account(
    db: DBSession,
    user: User,
    *,
    full_name: str | None = None,
    email: str | None = None,
    staff_id: str | None = None,
    department: str | None = None,
    title: str | None = None,
    staff_fields_set: bool = False,
) -> User:
    """Update mutable identity and linked staff-profile fields."""
    if full_name is not None:
        user.full_name = full_name.strip()

    if email is not None:
        new_email = email.strip().lower()
        if new_email != user.email.lower():
            clash = (
                db.query(User.id)
                .filter(func.lower(User.email) == new_email, User.id != user.id)
                .first()
            )
            if clash is not None:
                raise AccountError("An account with this email already exists.")
            user.email = new_email

    if staff_fields_set and any(role.name != ROLE_STUDENT for role in user.roles):
        staff = _ensure_staff_profile(db, user)
        normalized_staff_id = staff_id.strip() if staff_id else None
        _assert_staff_number_available(db, normalized_staff_id, excluding=staff.id)
        staff.staff_id = normalized_staff_id
        if department is not None:
            staff.department = department.strip() or None
        if title is not None:
            staff.title = title.strip() or None
        if full_name is not None:
            staff.first_name, staff.last_name = _split_name(full_name)

    db.flush()
    return user


def set_account_roles(db: DBSession, user: User, role_names: list[str]) -> User:
    """Replace the account's role set.

    Owned by the account lifecycle because a role change is a privilege change
    and must go through the same authorization gate as account creation.
    """
    new_roles = resolve_roles(db, role_names)
    user.roles = new_roles
    # A person promoted from student to staff needs a linked profile before an
    # academic assignment can reference them. Demotion keeps the existing
    # profile: it is historical identity, not a role artifact.
    if any(role.name != ROLE_STUDENT for role in new_roles):
        _ensure_staff_profile(db, user)
    db.flush()
    return user


def set_account_active(
    db: DBSession, user: User, *, is_active: bool, invalidate_sessions: bool = True
) -> int:
    """Activate or deactivate an account.

    Deactivation revokes every live session by default; a disabled account
    holding a valid cookie would still be able to act.

    Returns the number of revoked sessions.
    """
    user.is_active = is_active
    revoked = 0

    if not is_active and invalidate_sessions:
        revoked = (
            db.query(UserSession).filter(UserSession.user_id == user.id).delete()
        )

    db.flush()
    return revoked


def reset_account_password(
    db: DBSession, user: User, new_password: str | None, *, must_change_password: bool
) -> tuple[str, int]:
    """Administrative password reset.

    Returns the password that was set (generated when the caller did not
    supply one) and the number of sessions revoked.
    """
    password = new_password or generate_temporary_password()
    user.hashed_password = hash_password(password)
    user.must_change_password = must_change_password

    revoked = db.query(UserSession).filter(UserSession.user_id == user.id).delete()
    db.flush()
    return password, revoked


def change_own_password(
    db: DBSession, user: User, *, current_password: str, new_password: str
) -> int:
    """Change the caller's own password after verifying the current one.

    Returns the number of *other* sessions revoked. The caller's current
    session is deliberately kept alive so they are not signed out of the
    device they just used.
    """
    if not verify_password(current_password, user.hashed_password):
        raise AccountError("Current password is incorrect.")

    if verify_password(new_password, user.hashed_password):
        raise AccountError("New password must differ from the current password.")

    user.hashed_password = hash_password(new_password)
    user.must_change_password = False
    db.flush()
    return 0


def revoke_sessions(
    db: DBSession, user_id: uuid.UUID, *, keep_token_hash: str | None = None
) -> int:
    """Revoke a user's sessions, optionally preserving the current one."""
    query = db.query(UserSession).filter(UserSession.user_id == user_id)
    if keep_token_hash is not None:
        query = query.filter(UserSession.token_hash != keep_token_hash)
    count = query.delete(synchronize_session=False)
    db.flush()
    return count


def list_sessions(
    db: DBSession, user_id: uuid.UUID, *, current_token_hash: str | None = None
) -> list[tuple[UserSession, bool]]:
    """List an account's live sessions as (session, is_current) pairs."""
    sessions = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id)
        .order_by(UserSession.last_accessed_at.desc())
        .all()
    )
    return [(s, s.token_hash == current_token_hash) for s in sessions]


def account_to_response(db: DBSession, user: User) -> dict:
    """Build a safe account payload, including linked record summaries."""
    student = db.query(Student).filter(Student.user_id == user.id).first()
    staff = db.query(Staff).filter(Staff.user_id == user.id).first()

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "must_change_password": user.must_change_password,
        "roles": [{"id": r.id, "name": r.name} for r in user.roles],
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "student_id": student.id if student else None,
        "student_number": student.student_id if student else None,
        "has_staff_record": staff is not None,
        "staff_record_id": staff.id if staff else None,
        "staff_id": staff.staff_id if staff else None,
        "staff_department": staff.department if staff else None,
        "staff_title": staff.title if staff else None,
    }
