"""Pydantic schemas for the Stage 7 platform modules."""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.platform import (
    AnnouncementAudienceType,
    AnnouncementPriority,
    AnnouncementStatus,
    DocumentReviewStatus,
    DocumentScanStatus,
    DocumentStatus,
    DocumentVisibility,
    NotificationType,
    SupportTicketCategory,
    SupportTicketPriority,
    SupportTicketStatus,
)

# --- Announcements ---------------------------------------------------------


class AnnouncementTranslationInput(BaseModel):
    """One locale's title and body."""

    locale: str = Field(min_length=2, max_length=10)
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    summary: str | None = Field(default=None, max_length=500)

    @field_validator("locale")
    @classmethod
    def _normalize_locale(cls, value: str) -> str:
        return value.strip().lower()


class AnnouncementTranslationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: str
    title: str
    body: str
    summary: str | None = None


class AnnouncementCreate(BaseModel):
    default_locale: str = Field(default="en", min_length=2, max_length=10)
    priority: AnnouncementPriority = AnnouncementPriority.NORMAL
    is_pinned: bool = False
    audience_type: AnnouncementAudienceType = AnnouncementAudienceType.ALL
    audience_ref_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    expires_at: datetime | None = None
    translations: list[AnnouncementTranslationInput] = Field(min_length=1)

    @field_validator("default_locale")
    @classmethod
    def _normalize_default_locale(cls, value: str) -> str:
        return value.strip().lower()


class AnnouncementUpdate(BaseModel):
    priority: AnnouncementPriority | None = None
    is_pinned: bool | None = None
    audience_type: AnnouncementAudienceType | None = None
    audience_ref_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    expires_at: datetime | None = None
    default_locale: str | None = None
    translations: list[AnnouncementTranslationInput] | None = None


class AnnouncementResponse(BaseModel):
    """Full announcement for management views."""

    id: uuid.UUID
    status: AnnouncementStatus
    priority: AnnouncementPriority
    is_pinned: bool
    default_locale: str
    audience_type: AnnouncementAudienceType
    audience_ref_id: uuid.UUID | None = None
    audience_label: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    expires_at: datetime | None = None
    author_name: str | None = None
    created_at: datetime
    updated_at: datetime
    translations: list[AnnouncementTranslationResponse] = Field(default_factory=list)
    #: Best translation for the caller's locale, resolved server-side.
    resolved_title: str | None = None
    resolved_body: str | None = None
    resolved_locale: str | None = None


class AnnouncementListItem(BaseModel):
    """Compact announcement for list views, already localized."""

    id: uuid.UUID
    status: AnnouncementStatus
    priority: AnnouncementPriority
    is_pinned: bool
    audience_type: AnnouncementAudienceType
    title: str
    summary: str | None = None
    resolved_locale: str
    published_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    author_name: str | None = None


class AnnouncementListResponse(BaseModel):
    items: list[AnnouncementListItem]
    total: int
    page: int
    page_size: int


class PaginationMeta(BaseModel):
    """Shared pagination envelope fields."""

    total: int
    page: int
    page_size: int


# --- Support tickets -------------------------------------------------------


class SupportTicketCreate(BaseModel):
    category: SupportTicketCategory
    subject: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10, max_length=5000)
    # Staff may open a ticket on behalf of a student.
    student_id: uuid.UUID | None = None


class SupportTicketUpdate(BaseModel):
    status: SupportTicketStatus | None = None
    priority: SupportTicketPriority | None = None
    assigned_to: uuid.UUID | None = None
    resolution_note: str | None = Field(default=None, max_length=5000)


class SupportTicketMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    #: Only honoured for staff; ignored for students.
    is_internal: bool = False


class SupportTicketMessageResponse(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    author_name: str | None = None
    is_internal: bool
    body: str
    created_at: datetime


class SupportTicketResponse(BaseModel):
    id: uuid.UUID
    ticket_number: str
    student_id: uuid.UUID
    student_name: str | None = None
    student_number: str | None = None
    category: SupportTicketCategory
    subject: str
    description: str
    status: SupportTicketStatus
    priority: SupportTicketPriority
    assigned_to: uuid.UUID | None = None
    assignee_name: str | None = None
    resolution_note: str | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    message_count: int = 0
    messages: list[SupportTicketMessageResponse] = Field(default_factory=list)


class SupportTicketListItem(BaseModel):
    id: uuid.UUID
    ticket_number: str
    student_id: uuid.UUID
    student_name: str | None = None
    student_number: str | None = None
    category: SupportTicketCategory
    subject: str
    status: SupportTicketStatus
    priority: SupportTicketPriority
    assignee_name: str | None = None
    created_at: datetime
    updated_at: datetime


class SupportTicketListResponse(BaseModel):
    items: list[SupportTicketListItem]
    total: int
    page: int
    page_size: int


class SupportTicketStatsResponse(BaseModel):
    total: int
    open: int
    in_progress: int
    waiting_for_student: int
    resolved: int
    closed: int
    unassigned: int


# --- Notifications ---------------------------------------------------------


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: NotificationType
    params: dict[str, Any] | None = None
    link_url: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    read_at: datetime | None = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int
    page: int
    page_size: int


# --- Documents -------------------------------------------------------------


class DocumentResponse(BaseModel):
    """Document metadata.

    Deliberately excludes ``object_key`` and every storage internal: clients
    address documents by id through the authorization-checked endpoints only.
    """

    id: uuid.UUID
    student_id: uuid.UUID | None = None
    student_name: str | None = None
    document_type: str
    title: str
    description: str | None = None
    original_filename: str
    content_type: str
    file_size: int
    visibility: DocumentVisibility
    status: DocumentStatus

    review_status: DocumentReviewStatus
    scan_status: DocumentScanStatus
    scan_engine: str | None = None
    scanned_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewer_name: str | None = None
    #: Student-visible explanation attached to a rejection.
    review_note: str | None = None

    is_required: bool = False
    expires_on: date | None = None
    #: Set when this document has been replaced; clients use it to show the
    #: version chain rather than a duplicate row.
    superseded_by_id: uuid.UUID | None = None

    uploaded_by: uuid.UUID | None = None
    uploader_name: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentReviewRequest(BaseModel):
    """Approve or reject an uploaded document."""

    model_config = ConfigDict(extra="forbid")

    decision: DocumentReviewStatus
    #: Required when rejecting, so the student learns what to fix.
    note: str | None = Field(default=None, max_length=2000)


class DocumentExpectationRequest(BaseModel):
    """Set the institutional expectation flags on a document."""

    model_config = ConfigDict(extra="forbid")

    is_required: bool | None = None
    expires_on: date | None = None


class DocumentTypeOption(BaseModel):
    """A selectable document category, served by the API so the UI is not
    the source of truth for the vocabulary."""

    value: str
    label_key: str


class DocumentTypeListResponse(BaseModel):
    items: list[DocumentTypeOption]


class RequiredDocumentStatus(BaseModel):
    """One expected document category and whether the student has supplied it.

    ``MISSING`` is derived, not stored: a required category with no current
    document is missing by definition.
    """

    document_type: str
    #: MISSING | PENDING | APPROVED | REJECTED | REPLACEMENT_REQUIRED |
    #: EXPIRING | EXPIRED
    state: str
    expires_on: date | None = None
    document_id: uuid.UUID | None = None
    title: str | None = None


class StudentDocumentSummary(BaseModel):
    """Per-student document completeness, for the profile Documents tab."""

    student_id: uuid.UUID
    required: list[RequiredDocumentStatus]
    other: list[DocumentResponse]
    missing_count: int
    pending_count: int
    rejected_count: int
    expiring_count: int
    expired_count: int


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int


class DocumentReplaceRequest(BaseModel):
    """Replacement metadata for a document being superseded by a new upload."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    expires_on: date | None = None
    student_visible: bool | None = None


class DocumentDownloadResponse(BaseModel):
    """Either a short-lived direct URL or an application-streamed path."""

    document_id: uuid.UUID
    filename: str
    content_type: str
    expires_in: int | None = None
    url: str | None = None
    stream_path: str | None = None


# --- Audit -----------------------------------------------------------------


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None = None
    actor_email: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    context: dict[str, Any] | None = None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int


__all__ = [
    "AnnouncementCreate",
    "AnnouncementUpdate",
    "AnnouncementResponse",
    "AnnouncementListItem",
    "AnnouncementListResponse",
    "AnnouncementTranslationInput",
    "AnnouncementTranslationResponse",
    "PaginationMeta",
    "SupportTicketCreate",
    "SupportTicketUpdate",
    "SupportTicketMessageCreate",
    "SupportTicketMessageResponse",
    "SupportTicketResponse",
    "SupportTicketListItem",
    "SupportTicketListResponse",
    "SupportTicketStatsResponse",
    "NotificationResponse",
    "NotificationListResponse",
    "DocumentResponse",
    "DocumentListResponse",
    "DocumentDownloadResponse",
    "AuditLogResponse",
    "AuditLogListResponse",
]
