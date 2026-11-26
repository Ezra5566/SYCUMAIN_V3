"""Seed database with roles, permissions, and test users."""

from sqlalchemy.orm import Session

from app.auth.service import hash_password
from app.models.identity import Permission, Role, Staff, Student, StudentStatus, User
from app.permissions.constants import ALL_PERMISSIONS, ROLE_PERMISSIONS


def seed_roles_and_permissions(db: Session) -> None:
    """Create system roles and permissions if they don't exist."""
    # Seed permissions
    for group, perms in ALL_PERMISSIONS.items():
        for perm_data in perms:
            existing = db.query(Permission).filter(
                Permission.codename == perm_data["codename"]
            ).first()
            if not existing:
                perm = Permission(
                    codename=perm_data["codename"],
                    description=perm_data["description"],
                    group=group,
                )
                db.add(perm)
    db.flush()

    # Seed roles and assign permissions
    for role_name, perm_codenames in ROLE_PERMISSIONS.items():
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            role = Role(name=role_name, description=f"{role_name} role")
            db.add(role)
            db.flush()

        # Assign the exact declared set. Appending alone would leave a
        # permission removed from the policy still attached to an existing
        # role in a deployed database, so the code and the effective
        # permission matrix would silently disagree.
        expected = (
            db.query(Permission)
            .filter(Permission.codename.in_(perm_codenames))
            .all()
        )
        role.permissions = expected

    db.commit()


def seed_test_users(db: Session, *, password: str = "password123") -> None:
    """Create the role accounts for each role if they don't exist.

    These are development-only users for exercising the authentication system.

    ``password`` defaults to the *test fixture* credential, which is what the
    pytest suite signs in with. The application's startup path passes
    ``settings.DEMO_PASSWORD`` instead, so a development installation and the
    login page's account chips agree on one value, while the suite stays
    independent of a value intended for demonstrations.
    """
    default_password = hash_password(password)

    test_users = [
        {
            "email": "admin@school.portal",
            "username": "admin",
            "full_name": "Admin User",
            "role": "ADMIN",
            "is_superuser": True,
            "staff": None,
            "student": None,
        },
        {
            "email": "management@school.portal",
            "username": "management",
            "full_name": "Management User",
            "role": "MANAGEMENT",
            "is_superuser": False,
            "staff": {
                "staff_id": "STF-MGT-001",
                "first_name": "Management",
                "last_name": "User",
                "department": "Administration",
                "title": "Director",
            },
            "student": None,
        },
        {
            "email": "teacher@school.portal",
            "username": "teacher",
            "full_name": "Teacher User",
            "role": "TEACHER",
            "is_superuser": False,
            "staff": {
                "staff_id": "STF-TCH-001",
                "first_name": "Teacher",
                "last_name": "User",
                "department": "Academic",
                "title": "Professor",
            },
            "student": None,
        },
        {
            "email": "student@school.portal",
            "username": "student",
            "full_name": "Student User",
            "role": "STUDENT",
            "is_superuser": False,
            "staff": None,
            "student": {
                "student_id": "STU-001",
                "first_name": "Student",
                "last_name": "User",
                "nationality": "China",
            },
        },
    ]

    for user_data in test_users:
        existing = db.query(User).filter(User.email == user_data["email"]).first()
        if existing:
            continue

        role_name = user_data.pop("role")
        staff_data = user_data.pop("staff")
        student_data = user_data.pop("student")

        user = User(
            email=user_data["email"],
            username=user_data["username"],
            hashed_password=default_password,
            full_name=user_data["full_name"],
            is_active=True,
            is_superuser=user_data["is_superuser"],
        )
        db.add(user)
        db.flush()

        # Assign role
        role = db.query(Role).filter(Role.name == role_name).first()
        if role:
            user.roles.append(role)

        # Create staff record if applicable
        if staff_data:
            staff = Staff(
                user_id=user.id,
                staff_id=staff_data["staff_id"],
                first_name=staff_data["first_name"],
                last_name=staff_data["last_name"],
                department=staff_data.get("department"),
                title=staff_data.get("title"),
            )
            db.add(staff)

        # Create student record if applicable
        if student_data:
            student = Student(
                user_id=user.id,
                student_id=student_data["student_id"],
                first_name=student_data["first_name"],
                last_name=student_data["last_name"],
                nationality=student_data.get("nationality"),
                status=StudentStatus.ACTIVE,
            )
            db.add(student)

    db.commit()
