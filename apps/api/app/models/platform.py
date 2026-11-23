"""Platform models for Stage 7: announcements, support tickets,
notifications, and the general document registry.

Multilingual institutional content (announcements) uses a translation
side-table rather than `title_en` / `title_zh` columns so that new locales
can be added without a schema change.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.identity import Student, User


# --- Announcements ---------------------------------------------------------


class AnnouncementStatus(enum.StrEnum):
    """Lifecycle of an announcement."""

    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class AnnouncementPriority(enum.StrEnum):
    """Editorial priority of an announcement."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class AnnouncementAudienceType(enum.StrEnum):
    """Who an announcement is addressed to.

    The concrete audience is resolved server-side; the frontend never
    decides who may see an announcement.
    """

    ALL = "ALL"
    STUDENTS = "STUDENTS"
    TEACHERS = "TEACHERS"
    STAFF = "STAFF"
    MAJOR = "MAJOR"
    PROGRAM = "PROGRAM"
    CLASS = "CLASS"


class Announcement(Base):
    """An institutional announcement with per-locale translations."""

    __tablename__ = "announcements"
    __table_args__ = (
        Index("ix_announcements_status_published", "status", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # The language the announcement was authored in. Used as the last-resort
    # fallback when no translation exists for the reader's locale.
    default_locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    status: Mapped[AnnouncementStatus] = mapped_column(
        String(20), nullable=False, default=AnnouncementStatus.DRAFT, index=True
    )
    priority: Mapped[AnnouncementPriority] = mapped_column(
        String(20), nullable=False, default=AnnouncementPriority.NORMAL
    )
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Audience targeting
    audience_type: Mapped[AnnouncementAudienceType] = mapped_column(
        String(20),
        nullable=False,
        default=AnnouncementAudienceType.ALL,
        index=True,
    )
    audience_ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    translations: Mapped[list[AnnouncementTranslation]] = relationship(
        back_populates="announcement",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    author: Mapped[User | None] = relationship("User", foreign_keys=[created_by])


class AnnouncementTranslation(Base):
    """Translated title/body for an announcement in one locale."""

    __tablename__ = "announcement_translations"
    __table_args__ = (
        UniqueConstraint(
            "announcement_id", "locale", name="uq_announcement_translation_locale"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("announcements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    locale: Mapped[str] = mapped_column(String(10), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    announcement: Mapped[Announcement] = relationship(back_populates="translations")


# --- Support tickets -------------------------------------------------------


class SupportTicketStatus(enum.StrEnum):
    """Lifecycle of a support ticket."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_FOR_STUDENT = "WAITING_FOR_STUDENT"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class SupportTicketPriority(enum.StrEnum):
    """Priority of a support ticket."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class SupportTicketCategory(enum.StrEnum):
    """Category of a support ticket.

    Kept as a controlled enum so categories cannot drift; additional
    categories can be added in a future migration.
    """

    VISA_IMMIGRATION = "VISA_IMMIGRATION"
    HOUSING = "HOUSING"
    ACADEMIC = "ACADEMIC"
    FINANCE = "FINANCE"
    IT = "IT"
    GENERAL = "GENERAL"


class SupportTicket(Base):
    """A student support request handled by staff."""

    __tablename__ = "support_tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_number: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )

    category: Mapped[SupportTicketCategory] = mapped_column(
        String(30), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[SupportTicketStatus] = mapped_column(
        String(30), nullable=False, default=SupportTicketStatus.OPEN, index=True
    )
    priority: Mapped[SupportTicketPriority] = mapped_column(
        String(20), nullable=False, default=SupportTicketPriority.NORMAL
    )

    resolution_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    student: Mapped[Student] = relationship("Student", foreign_keys=[student_id])
    creator: Mapped[User] = relationship("User", foreign_keys=[created_by])
    assignee: Mapped[User | None] = relationship("User", foreign_keys=[assigned_to])
    messages: Mapped[list[SupportTicketMessage]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="SupportTicketMessage.created_at",
        lazy="selectin",
    )


class SupportTicketMessage(Base):
    """A message on a support ticket.

    `is_internal` messages are staff-only notes and must never be returned
    to the student who created the ticket.
    """

    __tablename__ = "support_ticket_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    ticket: Mapped[SupportTicket] = relationship(back_populates="messages")
    author: Mapped[User] = relationship("User", foreign_keys=[author_id])


# --- Notifications ---------------------------------------------------------


class NotificationType(enum.StrEnum):
    """Machine-readable notification types.

    The frontend maps these to localized text; the backend never sends
    user-facing prose that the frontend has to parse.
    """

    IMMIGRATION_CHANGE_SUBMITTED = "IMMIGRATION_CHANGE_SUBMITTED"
    IMMIGRATION_CHANGE_APPROVED = "IMMIGRATION_CHANGE_APPROVED"
    IMMIGRATION_CHANGE_REJECTED = "IMMIGRATION_CHANGE_REJECTED"
    IMMIGRATION_DOCUMENT_UPLOADED = "IMMIGRATION_DOCUMENT_UPLOADED"
    # Expiry reminders are generated from verified profiles only, at the
    # institution's configured warning windows. They are a different thing from
    # a change-request notification: one describes a document running out, the
    # other describes a workflow step.
    IMMIGRATION_EXPIRY_EXPIRED = "IMMIGRATION_EXPIRY_EXPIRED"
    IMMIGRATION_EXPIRY_URGENT = "IMMIGRATION_EXPIRY_URGENT"
    IMMIGRATION_EXPIRY_EXPIRING_SOON = "IMMIGRATION_EXPIRY_EXPIRING_SOON"
    IMMIGRATION_EXPIRY_RESOLVED = "IMMIGRATION_EXPIRY_RESOLVED"
    HOUSING_ASSIGNMENT_CREATED = "HOUSING_ASSIGNMENT_CREATED"
    HOUSING_ASSIGNMENT_TRANSFERRED = "HOUSING_ASSIGNMENT_TRANSFERRED"
    HOUSING_ASSIGNMENT_ENDED = "HOUSING_ASSIGNMENT_ENDED"
    SUPPORT_TICKET_CREATED = "SUPPORT_TICKET_CREATED"
    SUPPORT_TICKET_REPLIED = "SUPPORT_TICKET_REPLIED"
    SUPPORT_TICKET_STATUS_CHANGED = "SUPPORT_TICKET_STATUS_CHANGED"
    SUPPORT_TICKET_ASSIGNED = "SUPPORT_TICKET_ASSIGNED"
    ANNOUNCEMENT_PUBLISHED = "ANNOUNCEMENT_PUBLISHED"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"


class Notification(Base):
    """A database-backed in-app notification for one recipient."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "read_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    type: Mapped[NotificationType] = mapped_column(String(60), nullable=False, index=True)

    # Structured, locale-independent parameters used to build the localized
    # message on the client (e.g. {"ticket_number": "SUP-0007"}).
    params: Mapped[dict | None] = mapped_column(JSON)

    # Optional in-app link target, relative to the locale root.
    link_url: Mapped[str | None] = mapped_column(String(500))

    # Related entity, for deep linking and deduplication.
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True
    )

    recipient: Mapped[User] = relationship("User", foreign_keys=[user_id])


# --- Documents -------------------------------------------------------------


class DocumentStatus(enum.StrEnum):
    """Lifecycle of a stored document."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class DocumentVisibility(enum.StrEnum):
    """Who may download a document.

    STUDENT_VISIBLE: the owning student and authorized staff.
    STAFF_ONLY: authorized staff only; never returned to students.
    """

    STUDENT_VISIBLE = "STUDENT_VISIBLE"
    STAFF_ONLY = "STAFF_ONLY"


class DocumentReviewStatus(enum.StrEnum):
    """Institutional review state of an uploaded document.

    A document exists as soon as it is uploaded, but "has the office accepted
    this document?" is a separate question. Keeping review state distinct from
    storage lifecycle (``DocumentStatus``) means archiving a document never
    silently erases whether it was approved.
    """

    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REPLACEMENT_REQUIRED = "REPLACEMENT_REQUIRED"


class DocumentScanStatus(enum.StrEnum):
    """Malware-scan state for a document's stored bytes.

    ``LEGACY_UNSCANNED`` is assigned by migration to rows that predate the
    scanner. It is never assigned to a new upload and never satisfies the
    review gate, so historical rows are not silently certified as clean.
    """

    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    LEGACY_UNSCANNED = "LEGACY_UNSCANNED"


#: Controlled vocabulary for ``Document.document_type``.
#:
#: The column is deliberately a free string so a new category never requires a
#: migration, but the portal only *offers* this list. Registered here (rather
#: than hard-coded in the UI) so the API can serve it as configuration.
DOCUMENT_TYPES: tuple[str, ...] = (
    "PASSPORT",
    "VISA",
    "RESIDENCE_PERMIT",
    "STUDENT_ID",
    "ADMISSION",
    "INSURANCE",
    "ACADEMIC",
    "ACCOMMODATION",
    "PHOTO",
    "OTHER",
)


class Document(Base):
    """Registry entry for a file held in private object storage.

    Only metadata lives in PostgreSQL; the bytes live in the configured
    storage backend and are only ever reachable through an authorization
    checked download endpoint.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_student_status", "student_id", "status"),
        Index("ix_documents_student_type", "student_id", "document_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # The student this document belongs to, when applicable. Some documents
    # (e.g. internal forms) belong to the institution rather than a student.
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    document_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Storage location
    storage_provider: Mapped[str] = mapped_column(String(30), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))

    visibility: Mapped[DocumentVisibility] = mapped_column(
        String(20), nullable=False, default=DocumentVisibility.STAFF_ONLY
    )
    status: Mapped[DocumentStatus] = mapped_column(
        String(20), nullable=False, default=DocumentStatus.ACTIVE, index=True
    )

    # --- Institutional review -------------------------------------------
    # Uploaded documents start PENDING; a document manager approves or
    # rejects them. Students only ever see the outcome, never internal notes
    # (see ``DocumentResponse``).
    review_status: Mapped[DocumentReviewStatus] = mapped_column(
        String(20), nullable=False, default=DocumentReviewStatus.PENDING, index=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Student-visible explanation for a rejection. Internal commentary belongs
    # in the audit log, not here.
    review_note: Mapped[str | None] = mapped_column(Text)

    # --- Malware scanning ------------------------------------------------
    # A document cannot enter review until its bytes have been scanned clean.
    # Existing rows are backfilled as LEGACY_UNSCANNED rather than CLEAN.
    scan_status: Mapped[DocumentScanStatus] = mapped_column(
        String(20),
        nullable=False,
        default=DocumentScanStatus.PENDING,
        server_default=DocumentScanStatus.PENDING,
        index=True,
    )
    scan_engine: Mapped[str | None] = mapped_column(String(50))
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Institutional expectations -------------------------------------
    #: Marks a document the institution expects this student to provide. A
    #: required document that has not been uploaded is surfaced as MISSING by
    #: the student document summary rather than as a row in this table.
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: Calendar expiry of the document itself (e.g. a passport or permit),
    #: distinct from any immigration record expiry. Date-only on purpose.
    expires_on: Mapped[date | None] = mapped_column(Date)

    #: Set on the *superseded* row when a document is replaced, pointing at
    #: its successor. History is kept rather than overwritten.
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    student: Mapped[Student | None] = relationship("Student", foreign_keys=[student_id])
    uploader: Mapped[User] = relationship("User", foreign_keys=[uploaded_by])
    reviewer: Mapped[User | None] = relationship("User", foreign_keys=[reviewed_by])
    superseded_by: Mapped[Document | None] = relationship(
        "Document", remote_side="Document.id", foreign_keys=[superseded_by_id]
    )


__all__ = [
    "Announcement",
    "AnnouncementTranslation",
    "AnnouncementStatus",
    "AnnouncementPriority",
    "AnnouncementAudienceType",
    "SupportTicket",
    "SupportTicketMessage",
    "SupportTicketStatus",
    "SupportTicketPriority",
    "SupportTicketCategory",
    "Notification",
    "NotificationType",
    "Document",
    "DocumentStatus",
    "DocumentVisibility",
    "DocumentReviewStatus",
    "DocumentScanStatus",
    "DOCUMENT_TYPES",
]
