"""Immigration models: passport, visa, residence permit, documents, change requests."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.identity import Student, User


class ImmigrationDocumentType(enum.StrEnum):
    """Types of immigration documents."""

    PASSPORT = "PASSPORT"
    VISA = "VISA"
    RESIDENCE_PERMIT = "RESIDENCE_PERMIT"
    OTHER = "OTHER"


class ImmigrationChangeRequestStatus(enum.StrEnum):
    """Status of immigration change requests."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


#: The only profile attributes a student submission, import batch or staff
#: correction may write. Everything else (verification, student ownership,
#: timestamps) is controlled by the service, never by request data.
IMMIGRATION_PROFILE_FIELDS = (
    "passport_number",
    "passport_issuing_country",
    "passport_issue_date",
    "passport_expiry_date",
    "passport_name_as_shown",
    "visa_type",
    "visa_number",
    "visa_issue_date",
    "visa_expiry_date",
    "visa_entries",
    "visa_issuing_authority",
    "residence_permit_number",
    "residence_permit_issue_date",
    "residence_permit_expiry_date",
    "residence_permit_issuing_authority",
)


class ImmigrationProfile(Base):
    """Immigration profile for a student.

    Stores passport, visa, and residence permit information.
    Dates are stored as date-only for legal document correctness.
    """

    __tablename__ = "immigration_profiles"
    __table_args__ = (
        UniqueConstraint("student_id", name="uq_immigration_profile_student"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), unique=True, nullable=False, index=True
    )

    # Passport
    passport_number: Mapped[str | None] = mapped_column(String(50))
    passport_issuing_country: Mapped[str | None] = mapped_column(String(100))
    passport_issue_date: Mapped[date | None] = mapped_column(Date)
    passport_expiry_date: Mapped[date | None] = mapped_column(Date)
    passport_name_as_shown: Mapped[str | None] = mapped_column(String(255))

    # Visa
    visa_type: Mapped[str | None] = mapped_column(String(50))
    visa_number: Mapped[str | None] = mapped_column(String(50))
    visa_issue_date: Mapped[date | None] = mapped_column(Date)
    visa_expiry_date: Mapped[date | None] = mapped_column(Date)
    visa_entries: Mapped[str | None] = mapped_column(String(50))  # e.g., "SINGLE", "MULTIPLE"
    visa_issuing_authority: Mapped[str | None] = mapped_column(String(255))

    # Residence Permit
    residence_permit_number: Mapped[str | None] = mapped_column(String(50))
    residence_permit_issue_date: Mapped[date | None] = mapped_column(Date)
    residence_permit_expiry_date: Mapped[date | None] = mapped_column(Date)
    residence_permit_issuing_authority: Mapped[str | None] = mapped_column(String(255))

    # --- Provenance and verification ------------------------------------
    # Imported or student-submitted values are not official merely because
    # they are in this table. Only an authorized staff action marks a profile
    # verified, and an import is refused permission to overwrite one.
    data_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="UNKNOWN", server_default="UNKNOWN"
    )
    verification_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="UNVERIFIED",
        server_default="UNVERIFIED",
        index=True,
    )
    source_reference: Mapped[str | None] = mapped_column(String(500))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    student: Mapped[Student] = relationship("Student", back_populates="immigration_profile")
    documents: Mapped[list[ImmigrationDocument]] = relationship(
        back_populates="immigration_profile", lazy="selectin"
    )
    change_requests: Mapped[list[ImmigrationChangeRequest]] = relationship(
        back_populates="immigration_profile", lazy="selectin"
    )
    versions: Mapped[list[ImmigrationProfileVersion]] = relationship(
        back_populates="profile", order_by="ImmigrationProfileVersion.version_number"
    )


class ImmigrationDocument(Base):
    """Document metadata for immigration files.

    Files are stored in object storage; this table stores metadata only.
    """

    __tablename__ = "immigration_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    immigration_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("immigration_profiles.id"),
        nullable=False,
        index=True,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    document_type: Mapped[ImmigrationDocumentType] = mapped_column(
        String(30), nullable=False
    )
    storage_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column()  # bytes
    notes: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    immigration_profile: Mapped[ImmigrationProfile] = relationship(
        back_populates="documents"
    )
    uploader: Mapped[User] = relationship("User", foreign_keys=[uploaded_by])


class ImmigrationChangeRequest(Base):
    """Student-submitted change request for immigration data.

    Students cannot directly modify official immigration records.
    Changes go through an approval workflow.
    """

    __tablename__ = "immigration_change_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    immigration_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("immigration_profiles.id"),
        nullable=False,
        index=True,
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    # What type of change
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Proposed data as JSON string (flexible for different change types)
    proposed_data: Mapped[str] = mapped_column(Text, nullable=False)

    # Current data snapshot at submission time
    current_data_snapshot: Mapped[str | None] = mapped_column(Text)

    # Status
    status: Mapped[ImmigrationChangeRequestStatus] = mapped_column(
        String(20),
        nullable=False,
        default=ImmigrationChangeRequestStatus.PENDING,
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    # Timestamps
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    immigration_profile: Mapped[ImmigrationProfile] = relationship(
        back_populates="change_requests"
    )
    submitter: Mapped[User] = relationship("User", foreign_keys=[submitted_by])
    reviewer: Mapped[User | None] = relationship("User", foreign_keys=[reviewed_by])


class ImmigrationProfileVersion(Base):
    """Immutable snapshot of an official immigration profile after a change.

    ``previous_data`` and ``new_data`` are JSON objects so a reviewer can see
    exactly what changed without reconstructing it from adjacent rows. The
    profile itself stays a single row and continues to drive expiry/status
    calculations; this table is append-only history.
    """

    __tablename__ = "immigration_profile_versions"
    __table_args__ = (
        UniqueConstraint(
            "immigration_profile_id",
            "version_number",
            name="uq_immigration_profile_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    immigration_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("immigration_profiles.id"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(nullable=False)
    previous_data: Mapped[str | None] = mapped_column(Text)
    new_data: Mapped[str] = mapped_column(Text, nullable=False)
    changed_fields: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True
    )
    change_reason: Mapped[str | None] = mapped_column(String(500))
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("immigration_change_requests.id"),
        nullable=True,
        index=True,
    )

    profile: Mapped[ImmigrationProfile] = relationship(back_populates="versions")
    changed_by: Mapped[User | None] = relationship("User", foreign_keys=[changed_by_id])
    change_request: Mapped[ImmigrationChangeRequest | None] = relationship(
        "ImmigrationChangeRequest", foreign_keys=[change_request_id]
    )


__all__ = [
    "ImmigrationProfile",
    "ImmigrationProfileVersion",
    "ImmigrationDocument",
    "ImmigrationChangeRequest",
    "ImmigrationDocumentType",
    "ImmigrationChangeRequestStatus",
]
