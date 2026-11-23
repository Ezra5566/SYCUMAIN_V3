"""Tests for database connection and identity models."""

import uuid

from sqlalchemy import text

from app.models.identity import (
    Permission,
    Role,
    Staff,
    Student,
    User,
)


def test_database_connection(db_session):
    """Test that the database connection works."""
    result = db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


def test_roles_exist(db_session):
    """Test that the four system roles exist after seeding."""
    from app.seed import seed_roles_and_permissions
    seed_roles_and_permissions(db_session)

    roles = db_session.query(Role).all()
    role_names = {r.name for r in roles}
    assert "ADMIN" in role_names
    assert "MANAGEMENT" in role_names
    assert "TEACHER" in role_names
    assert "STUDENT" in role_names
    assert len(roles) == 4


def test_permissions_exist(db_session):
    """Test that foundation permissions were seeded."""
    from app.seed import seed_roles_and_permissions
    seed_roles_and_permissions(db_session)

    permissions = db_session.query(Permission).all()
    assert len(permissions) > 0

    codenames = {p.codename for p in permissions}
    # Check some key permissions exist
    assert "student.view" in codenames
    assert "student.create" in codenames
    assert "users.manage" in codenames
    assert "permissions.manage" in codenames


def test_role_permission_associations(db_session):
    """Test that roles have correct permissions assigned."""
    from app.seed import seed_roles_and_permissions
    seed_roles_and_permissions(db_session)

    admin = db_session.query(Role).filter(Role.name == "ADMIN").first()
    assert admin is not None
    # Admin should have all permissions
    assert len(admin.permissions) > 10

    student = db_session.query(Role).filter(Role.name == "STUDENT").first()
    assert student is not None
    # Student should have fewer permissions than admin
    assert len(student.permissions) < len(admin.permissions)


def test_user_student_relationship(db_session):
    """Test that a user can be associated with a student record."""
    # Use unique values to avoid conflicts with seeded data
    unique_id = str(uuid.uuid4())[:8]
    user = User(
        email=f"test-student-{unique_id}@example.com",
        username=f"teststudent{unique_id}",
        hashed_password="hashed_password_placeholder",
        full_name="Test Student User",
    )
    db_session.add(user)
    db_session.flush()

    student = Student(
        user_id=user.id,
        student_id=f"STU-TEST-{unique_id}",
        first_name="Test",
        last_name="Student",
    )
    db_session.add(student)
    db_session.commit()

    # Verify relationship
    assert student.user_id == user.id
    assert user.student is not None
    assert user.student.student_id == f"STU-TEST-{unique_id}"


def test_user_staff_relationship(db_session):
    """Test that a user can be associated with a staff record."""
    unique_id = str(uuid.uuid4())[:8]
    user = User(
        email=f"staff-{unique_id}@example.com",
        username=f"staffuser{unique_id}",
        hashed_password="hashed_password_placeholder",
        full_name="Staff User",
    )
    db_session.add(user)
    db_session.flush()

    staff = Staff(
        user_id=user.id,
        staff_id=f"STF-{unique_id}",
        first_name="Staff",
        last_name="Member",
    )
    db_session.add(staff)
    db_session.commit()

    # Verify relationship
    assert staff.user_id == user.id
    assert user.staff is not None
    assert user.staff.staff_id == f"STF-{unique_id}"


def test_user_role_association(db_session):
    """Test that a user can be assigned roles."""
    from app.seed import seed_roles_and_permissions
    seed_roles_and_permissions(db_session)

    unique_id = str(uuid.uuid4())[:8]
    user = User(
        email=f"roleuser-{unique_id}@example.com",
        username=f"roleuser{unique_id}",
        hashed_password="hashed_password_placeholder",
        full_name="Role User",
    )
    db_session.add(user)
    db_session.flush()

    student_role = db_session.query(Role).filter(Role.name == "STUDENT").first()
    user.roles.append(student_role)
    db_session.commit()

    # Verify
    assert student_role in user.roles
    role_names = {r.name for r in user.roles}
    assert "STUDENT" in role_names
