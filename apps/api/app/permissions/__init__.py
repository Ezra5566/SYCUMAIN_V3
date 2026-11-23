"""Permissions package — centralized authorization infrastructure.

Only one scope policy is exported. There is no permissive fallback module: an
unknown role resolves to "no students", and every object-scope question goes
through `app.permissions.scope`.
"""

from app.permissions.checks import (
    check_permission,
    get_user_permissions,
    has_permission,
    require_permission,
)
from app.permissions.constants import ALL_PERMISSIONS, ROLE_PERMISSIONS
from app.permissions.scope import (
    accessible_student_ids,
    can_access_student,
    can_manage_student_records,
    can_view_housing,
    can_view_immigration,
    role_names,
)

__all__ = [
    "ALL_PERMISSIONS",
    "ROLE_PERMISSIONS",
    "accessible_student_ids",
    "can_access_student",
    "can_manage_student_records",
    "can_view_housing",
    "can_view_immigration",
    "check_permission",
    "get_user_permissions",
    "has_permission",
    "require_permission",
    "role_names",
]
