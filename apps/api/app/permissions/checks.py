"""Permission checking utilities."""


from app.models.identity import User


def get_user_permissions(user: User) -> set[str]:
    """Get all permission codenames for a user via their roles."""
    permissions: set[str] = set()
    for role in user.roles:
        for perm in role.permissions:
            permissions.add(perm.codename)
    return permissions


def has_permission(user: User, permission_codename: str) -> bool:
    """Check if a user has a specific permission."""
    return permission_codename in get_user_permissions(user)


def check_permission(user: User, permission_codename: str) -> None:
    """Raise PermissionError if user lacks the permission."""
    if not has_permission(user, permission_codename):
        raise PermissionError(
            f"Missing required permission: {permission_codename}"
        )


# Dependency-injection helper for FastAPI
def require_permission(permission_codename: str):
    """Factory that returns a dependency checking a single permission.

    Usage in routes:
        @router.get("/students", dependencies=[Depends(require_permission("student.view"))])
    """
    from fastapi import Depends, HTTPException, status

    from app.auth.dependencies import get_current_active_user

    def _check(current_user: User = Depends(get_current_active_user)):
        if not has_permission(current_user, permission_codename):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "You do not have permission to access this resource.",
                    }
                },
            )
        return current_user

    return _check
