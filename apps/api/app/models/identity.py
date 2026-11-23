"""Identity models: users, roles, permissions, students, staff."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.immigration import ImmigrationProfile


class StudentStatus(enum.StrEnum):
    """Student enrollment status."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"
    SUSPENDED = "SUSPENDED"


# Association tables
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True),
    Column(
        "permission_id",
        UUID(as_uuid=True),
        ForeignKey("permissions.id"),
        primary_key=True,
    ),
)


class User(Base):
    """System user account."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Set when an administrator issues a temporary password. The account can
    # authenticate but is expected to replace the password; the flag lets the
    # frontend prompt for that without blocking the login itself.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )
    student: Mapped[Student | None] = relationship(back_populates="user", uselist=False)
    staff: Mapped[Staff | None] = relationship(back_populates="user", uselist=False)


class Role(Base):
    """System role (ADMIN, MANAGEMENT, TEACHER, STUDENT)."""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    users: Mapped[list[User]] = relationship(
        secondary=user_roles, back_populates="roles", lazy="selectin"
    )
    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, back_populates="roles", lazy="selectin"
    )


class Permission(Base):
    """Granular permission (e.g. student.view, visa.edit)."""

    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    codename: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    group: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions, back_populates="permissions", lazy="selectin"
    )


class Student(Base):
    """Student record linked to a user account.

    This is the central business entity for the portal.
    Future modules (Immigration, Housing, Academic, Documents)
    will reference students via their user_id.
    """

    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    student_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    # Identity
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(100))
    date_of_birth: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gender: Mapped[str | None] = mapped_column(String(20))
    nationality: Mapped[str | None] = mapped_column(String(100))

    # Profile photo. The bytes live in private object storage and are served
    # only through an authorization-checked endpoint; PostgreSQL holds the
    # object reference and content type, never the image data itself.
    profile_photo_object_key: Mapped[str | None] = mapped_column(String(500))
    profile_photo_content_type: Mapped[str | None] = mapped_column(String(100))
    profile_photo_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Contact
    phone: Mapped[str | None] = mapped_column(String(50))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(255))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(50))

    # The admission of record used as the immigration cohort basis. Set by the
    # migration-verification workflow (or at creation for a new admission) and
    # replaceable only by the audited correction path; never inferred.
    original_admission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "academic_admissions.id",
            use_alter=True,
            name="fk_students_original_admission",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    # Status
    status: Mapped[StudentStatus] = mapped_column(
        String(20), nullable=False, default=StudentStatus.ACTIVE, index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_students_original_admission", "original_admission_id"),
        Index(
            "uq_student_original_admission",
            "original_admission_id",
            unique=True,
            postgresql_where=text("original_admission_id IS NOT NULL"),
        ),
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="student")
    immigration_profile: Mapped[ImmigrationProfile | None] = relationship(
        "ImmigrationProfile", back_populates="student", uselist=False
    )


class Staff(Base):
    """Staff record linked to a user account (management or teacher)."""

    __tablename__ = "staff"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    # Optional: SCU has not supplied an official staff-number format. NULL is
    # a real state and must not be filled with an invented identifier.
    staff_id: Mapped[str | None] = mapped_column(
        String(50), unique=True, nullable=True, index=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(100))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="staff")


# Re-export association tables for Alembic autogenerate
__all__ = [
    "User",
    "Role",
    "Permission",
    "Student",
    "Staff",
    "StudentStatus",
    "user_roles",
    "role_permissions",
]
