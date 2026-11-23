"""The single authoritative student scope policy.

Every endpoint that answers "may this user see this student's record?" resolves
the answer here. There is deliberately no second policy module: an earlier
`policy.py` duplicated this rule with teacher access left as a placeholder that
returned ``True``, which is a permissive default waiting to be imported by a new
module. It has been removed, and ``tests/test_authorization_scope.py`` fails if
such a module reappears.

Rule summary:

* ADMIN, MANAGEMENT — unrestricted.
* TEACHER — only students enrolled in a class section they are assigned to.
* STUDENT — only their own record.
* Anything else — denied.

Scope and permission are separate questions and both must be asked: this module
decides *which* students, the caller's permission check decides *whether* the
endpoint may be used at all. A role with no recognized name resolves to an empty
set, so an unknown or newly invented role inherits no access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.identity import Staff, Student, User
from app.permissions.checks import has_permission

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session as DBSession

MANAGEMENT_ROLES = {"ADMIN", "MANAGEMENT"}


def role_names(user: User) -> set[str]:
    """Role names held by `user`."""
    return {role.name for role in user.roles}


def get_student_for_user(db: DBSession, user: User) -> Student | None:
    """The student record owned by `user`, if the account is a student."""
    return db.query(Student).filter(Student.user_id == user.id).first()


def get_staff_for_user(db: DBSession, user: User) -> Staff | None:
    """The staff record owned by `user`, if the account is staff."""
    return db.query(Staff).filter(Staff.user_id == user.id).first()


def _teacher_student_ids(db: DBSession, user: User) -> set[uuid.UUID]:
    """Student IDs reachable through the teacher's own class assignments.

    Imported lazily: the academic service imports this module, and a module
    level import would create a cycle.
    """
    from app.services.academic import teacher_student_ids  # noqa: PLC0415

    return teacher_student_ids(db, user)


def accessible_student_ids(db: DBSession, user: User) -> set[uuid.UUID] | None:
    """Student IDs `user` may see.

    Returns:
        ``None`` when access is unrestricted (management), otherwise the exact
        set of permitted student IDs — possibly empty, which means "none".
    """
    roles = role_names(user)

    if MANAGEMENT_ROLES & roles:
        return None

    if "TEACHER" in roles:
        return _teacher_student_ids(db, user)

    if "STUDENT" in roles:
        student = get_student_for_user(db, user)
        return {student.id} if student is not None else set()

    return set()


def can_access_student(db: DBSession, user: User, student_id: uuid.UUID) -> bool:
    """Whether `user` may read `student_id`'s record."""
    permitted = accessible_student_ids(db, user)
    if permitted is None:
        return (
            db.query(Student.id).filter(Student.id == student_id).first() is not None
        )
    return student_id in permitted


def can_view_immigration(db: DBSession, user: User, student_id: uuid.UUID) -> bool:
    """Whether `user` may read `student_id`'s immigration record.

    Teachers hold no immigration permission, so the scope alone is not enough.
    """
    return has_permission(user, "immigration.view") and can_access_student(
        db, user, student_id
    )


def can_view_housing(db: DBSession, user: User, student_id: uuid.UUID) -> bool:
    """Whether `user` may read `student_id`'s housing assignment."""
    return has_permission(user, "housing.view") and can_access_student(
        db, user, student_id
    )


def can_manage_student_records(user: User) -> bool:
    """Whether `user` may change authoritative student data (not self-service)."""
    return bool(MANAGEMENT_ROLES & role_names(user))


__all__ = [
    "accessible_student_ids",
    "can_access_student",
    "can_manage_student_records",
    "can_view_housing",
    "can_view_immigration",
    "get_staff_for_user",
    "get_student_for_user",
    "role_names",
]
