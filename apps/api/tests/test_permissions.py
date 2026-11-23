"""Tests for the permissions and authorization layer."""

import uuid

from app.models.identity import Role, User
from app.permissions.checks import get_user_permissions, has_permission
from app.seed import seed_roles_and_permissions


def test_has_permission_admin(db_session):
    """Test that admin users have all permissions."""
    seed_roles_and_permissions(db_session)

    # Use existing admin user from seed or create unique one
    unique_id = str(uuid.uuid4())[:8]
    user = User(
        email=f"admin-perm-{unique_id}@test.com",
        username=f"adminperm{unique_id}",
        hashed_password="hashed",
        full_name="Admin User",
    )
    db_session.add(user)
    db_session.flush()

    admin_role = db_session.query(Role).filter(Role.name == "ADMIN").first()
    user.roles.append(admin_role)
    db_session.commit()

    assert has_permission(user, "student.view")
    assert has_permission(user, "student.create")
    assert has_permission(user, "users.manage")
    assert has_permission(user, "permissions.manage")


def test_has_permission_student(db_session):
    """Test that students have limited permissions."""
    seed_roles_and_permissions(db_session)

    unique_id = str(uuid.uuid4())[:8]
    user = User(
        email=f"student-perm-{unique_id}@test.com",
        username=f"studentperm{unique_id}",
        hashed_password="hashed",
        full_name="Student User",
    )
    db_session.add(user)
    db_session.flush()

    student_role = db_session.query(Role).filter(Role.name == "STUDENT").first()
    user.roles.append(student_role)
    db_session.commit()

    assert has_permission(user, "student.view")
    assert has_permission(user, "documents.view")
    # Students should NOT have admin permissions
    assert not has_permission(user, "users.manage")
    assert not has_permission(user, "permissions.manage")


def test_get_user_permissions(db_session):
    """Test that get_user_permissions returns all permissions across roles."""
    seed_roles_and_permissions(db_session)

    unique_id = str(uuid.uuid4())[:8]
    user = User(
        email=f"multi-{unique_id}@test.com",
        username=f"multirole{unique_id}",
        hashed_password="hashed",
        full_name="Multi Role User",
    )
    db_session.add(user)
    db_session.flush()

    teacher_role = db_session.query(Role).filter(Role.name == "TEACHER").first()
    user.roles.append(teacher_role)
    db_session.commit()

    perms = get_user_permissions(user)
    assert "student.view" in perms
    assert "academic.view" in perms
    assert isinstance(perms, set)


def test_unauthenticated_access_rejected(client):
    """Test that unauthenticated access returns 401."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "UNAUTHORIZED"
