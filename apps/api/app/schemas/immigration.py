"""Immigration Pydantic schemas for API request/response validation."""

from __future__ import annotations

import uuid  # noqa: TC003
from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.immigration import (  # noqa: TC001
    IMMIGRATION_PROFILE_FIELDS,
    ImmigrationChangeRequestStatus,
    ImmigrationDocumentType,
)

# --- Request Schemas ---


class ImmigrationProfileUpdate(BaseModel):
    """Schema for updating immigration profile (management/admin only)."""

    model_config = ConfigDict(extra="forbid")

    change_reason: str | None = Field(
        None,
        max_length=500,
        description="Why the official record is being corrected; stored in history",
    )
    passport_number: str | None = Field(None, max_length=50)
    passport_issuing_country: str | None = Field(None, max_length=100)
    passport_issue_date: date | None = None
    passport_expiry_date: date | None = None
    passport_name_as_shown: str | None = Field(None, max_length=255)

    visa_type: str | None = Field(None, max_length=50)
    visa_number: str | None = Field(None, max_length=50)
    visa_issue_date: date | None = None
    visa_expiry_date: date | None = None
    visa_entries: str | None = Field(None, max_length=50)
    visa_issuing_authority: str | None = Field(None, max_length=255)

    residence_permit_number: str | None = Field(None, max_length=50)
    residence_permit_issue_date: date | None = None
    residence_permit_expiry_date: date | None = None
    residence_permit_issuing_authority: str | None = Field(None, max_length=255)


class ChangeRequestSubmit(BaseModel):
    """Schema for student-submitted change request."""

    change_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Type of change: PASSPORT, VISA, RESIDENCE_PERMIT",
    )
    proposed_data: dict = Field(
        ..., min_length=1, description="Proposed changes as key-value pairs"
    )

    @field_validator("change_type")
    @classmethod
    def _valid_change_type(cls, value: str) -> str:
        allowed = {"PASSPORT", "VISA", "RESIDENCE_PERMIT"}
        normalized = value.strip().upper()
        if normalized not in allowed:
            raise ValueError("change_type must be PASSPORT, VISA or RESIDENCE_PERMIT")
        return normalized

    @field_validator("proposed_data")
    @classmethod
    def _only_official_fields(cls, value: dict) -> dict:
        """Refuse attempts to write ownership or verification attributes."""
        unknown = sorted(set(value) - set(IMMIGRATION_PROFILE_FIELDS))
        if unknown:
            raise ValueError(f"not editable through a change request: {', '.join(unknown)}")
        return value


class ChangeRequestReview(BaseModel):
    """Schema for management reviewing a change request."""

    rejection_reason: str | None = Field(
        None, max_length=1000, description="Required if rejecting"
    )


class ImmigrationImportRecord(BaseModel):
    """One normalized import row; values use existing profile fields only.

    ``student_id`` is a *reference*, not necessarily a UUID: the student number
    (``STU-123``) is what the registrar's sheet carries and what the student and
    housing importers already use, so a batch can be built from one source file.
    A UUID is still accepted for callers that hold the record id.
    """

    student_id: str = Field(min_length=1, max_length=64)
    values: dict[str, str | None] = Field(min_length=1)


class ImmigrationImportRequest(BaseModel):
    """Normalized import batch, not an SCU spreadsheet format."""

    model_config = ConfigDict(extra="forbid")

    source_reference: str = Field(min_length=1, max_length=500)
    records: list[ImmigrationImportRecord] = Field(min_length=1, max_length=200)


class ImmigrationImportApplyRequest(ImmigrationImportRequest):
    confirm: bool = False


class ImmigrationImportPreviewRecord(BaseModel):
    #: Resolved student record id, or None when the reference did not resolve.
    student_id: uuid.UUID | None = None
    #: The reference exactly as it appeared in the batch.
    student_reference: str | None = None
    student_name: str | None = None
    student_number: str | None = None
    status: str
    current_values: dict[str, str | None] = Field(default_factory=dict)
    proposed_values: dict[str, str] = Field(default_factory=dict)
    applied_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ImmigrationImportPreviewResponse(BaseModel):
    records: list[ImmigrationImportPreviewRecord]
    applyable: int
    conflicts: int
    invalid: int


class ImmigrationImportApplyResponse(ImmigrationImportPreviewResponse):
    applied: int
    skipped: int
    confirmed: bool


# --- Response Schemas ---


class ImmigrationDocumentResponse(BaseModel):
    """Response for an immigration document."""

    id: uuid.UUID
    document_type: ImmigrationDocumentType
    original_filename: str
    content_type: str | None = None
    file_size: int | None = None
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ImmigrationProfileResponse(BaseModel):
    """Response for immigration profile (management/admin view with sensitive fields)."""

    id: uuid.UUID
    student_id: uuid.UUID

    # Passport
    passport_number: str | None = None
    passport_issuing_country: str | None = None
    passport_issue_date: date | None = None
    passport_expiry_date: date | None = None
    passport_name_as_shown: str | None = None

    # Visa
    visa_type: str | None = None
    visa_number: str | None = None
    visa_issue_date: date | None = None
    visa_expiry_date: date | None = None
    visa_entries: str | None = None
    visa_issuing_authority: str | None = None

    # Residence Permit
    residence_permit_number: str | None = None
    residence_permit_issue_date: date | None = None
    residence_permit_expiry_date: date | None = None
    residence_permit_issuing_authority: str | None = None

    # Derived status
    passport_status: str | None = None
    passport_days_remaining: int | None = None
    visa_status: str | None = None
    visa_days_remaining: int | None = None
    residence_permit_status: str | None = None
    residence_permit_days_remaining: int | None = None

    # Documents
    documents: list[ImmigrationDocumentResponse] = []

    # Provenance. Imported or student-submitted data is not official until an
    # authorized reviewer verifies it.
    data_source: str = "UNKNOWN"
    verification_status: str = "UNVERIFIED"
    source_reference: str | None = None
    verified_at: datetime | None = None
    verified_by_id: uuid.UUID | None = None

    # Timestamps
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImmigrationProfileStudentView(BaseModel):
    """Limited immigration profile view for students (hides some sensitive identifiers)."""

    id: uuid.UUID
    student_id: uuid.UUID

    # Passport (partial number shown)
    passport_number: str | None = None
    passport_issuing_country: str | None = None
    passport_issue_date: date | None = None
    passport_expiry_date: date | None = None
    passport_name_as_shown: str | None = None

    # Visa
    visa_type: str | None = None
    visa_number: str | None = None
    visa_issue_date: date | None = None
    visa_expiry_date: date | None = None
    visa_entries: str | None = None
    visa_issuing_authority: str | None = None

    # Residence Permit
    residence_permit_number: str | None = None
    residence_permit_issue_date: date | None = None
    residence_permit_expiry_date: date | None = None
    residence_permit_issuing_authority: str | None = None

    # Derived status
    passport_status: str | None = None
    passport_days_remaining: int | None = None
    visa_status: str | None = None
    visa_days_remaining: int | None = None
    residence_permit_status: str | None = None
    residence_permit_days_remaining: int | None = None

    # Documents (count only, not full metadata for students)
    document_count: int = 0

    # Students are entitled to know whether the office has verified their file.
    verification_status: str = "UNVERIFIED"

    # Timestamps
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImmigrationChangeRequestResponse(BaseModel):
    """Response for an immigration change request."""

    id: uuid.UUID
    immigration_profile_id: uuid.UUID
    student_id: uuid.UUID | None = None
    student_name: str | None = None
    submitted_by: uuid.UUID
    submitter_name: str | None = None
    reviewed_by: uuid.UUID | None = None
    reviewer_name: str | None = None

    change_type: str
    proposed_data: dict
    current_data_snapshot: dict | None = None

    status: ImmigrationChangeRequestStatus
    rejection_reason: str | None = None

    submitted_at: datetime
    reviewed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ImmigrationCohortSummary(BaseModel):
    """One named original-admission cohort in the live overview."""

    intake_id: uuid.UUID
    intake_name: str
    intake_code: str | None = None
    start_date: date | None = None
    count: int = 0


class ImmigrationUntrustedCounts(BaseModel):
    """Active students deliberately excluded from every named cohort."""

    total: int = 0
    unverified: int = 0
    revoked: int = 0
    disputed: int = 0
    no_admission: int = 0


class ImmigrationCohortResponse(BaseModel):
    """Original-admission cohort context for one student."""

    student_id: uuid.UUID
    original_admission_id: uuid.UUID | None = None
    original_admission_intake_id: uuid.UUID | None = None
    original_admission_intake_name: str | None = None
    original_admission_intake_code: str | None = None
    original_admission_intake_start_date: date | None = None
    verification_status: str
    verified_at: datetime | None = None

    management_confirmer_name: str | None = None
    management_confirmed_at: datetime | None = None
    management_revoked_at: datetime | None = None
    management_revocation_reason: str | None = None
    admin_confirmer_name: str | None = None
    admin_confirmed_at: datetime | None = None
    admin_revoked_at: datetime | None = None
    admin_revocation_reason: str | None = None
    last_confirmer_name: str | None = None
    last_confirmed_at: datetime | None = None
    revoked_by_name: str | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None

    placement_intake_id: uuid.UUID | None = None
    placement_intake_name: str | None = None


class ImmigrationOverviewItem(BaseModel):
    """Student summary for immigration dashboard.

    ``original_admission_intake_*`` is the immigration cohort basis. The
    ``placement_intake_*`` fields are academic placement only and never affect
    cohort attribution.
    """

    student_id: uuid.UUID
    student_name: str
    student_number: str

    original_admission_intake_id: uuid.UUID | None = None
    original_admission_intake_name: str | None = None
    original_admission_intake_start_date: date | None = None
    verification_status: str | None = None
    last_verified_at: datetime | None = None
    placement_intake_id: uuid.UUID | None = None
    placement_intake_name: str | None = None

    # Passport
    passport_expiry_date: date | None = None
    passport_status: str | None = None
    passport_days_remaining: int | None = None

    # Visa
    visa_type: str | None = None
    visa_expiry_date: date | None = None
    visa_status: str | None = None
    visa_days_remaining: int | None = None

    # Residence Permit
    residence_permit_expiry_date: date | None = None
    residence_permit_status: str | None = None
    residence_permit_days_remaining: int | None = None

    # Pending requests
    pending_requests_count: int = 0


class CountryStudentCount(BaseModel):
    """Aggregated count for one ISO 3166-1 alpha-2 country."""

    code: str
    count: int


class NationalityDistributionResponse(BaseModel):
    """Aggregate nationality distribution for the immigration map.

    Individual students are never returned. Values that are blank or that do
    not match an ISO country name are reported separately so the map total
    always reconciles with the cohort total.
    """

    total_students: int = 0
    mapped_students: int = 0
    missing_country_count: int = 0
    unmapped_country_count: int = 0
    countries: list[CountryStudentCount] = []


class ImmigrationOverviewResponse(BaseModel):
    """Response for immigration overview dashboard."""

    items: list[ImmigrationOverviewItem]
    total: int
    page: int = 1
    page_size: int = 25
    total_pages: int = 0

    # Summary counts
    total_students: int = 0
    valid_count: int = 0
    expiring_count: int = 0
    # Expiring within the urgent window (<= 30 days). A subset of
    # `expiring_count`, reported separately because it drives the escalation
    # list rather than the general "coming up" list.
    urgent_count: int = 0
    expired_count: int = 0
    no_data_count: int = 0
    pending_requests_count: int = 0

    # Phase 6: named original-intake cohorts and one untrusted aggregate.
    # Under ADMISSION_COHORT_SOURCE=LEGACY these stay empty/zero so the old
    # overview shape is preserved while the additive fields remain readable.
    cohorts: list[ImmigrationCohortSummary] = []
    untrusted: ImmigrationUntrustedCounts = ImmigrationUntrustedCounts()


class ImmigrationProfileVersionResponse(BaseModel):
    """One immutable snapshot in a profile's history."""

    id: uuid.UUID
    immigration_profile_id: uuid.UUID
    version_number: int
    previous_data: dict | None = None
    new_data: dict
    changed_fields: list[str] = []
    changed_by_id: uuid.UUID | None = None
    changed_by_name: str | None = None
    changed_at: datetime
    change_reason: str | None = None
    change_request_id: uuid.UUID | None = None


class ImmigrationDocumentUploadResponse(BaseModel):
    """Response after uploading an immigration document."""

    id: uuid.UUID
    document_type: ImmigrationDocumentType
    original_filename: str
    storage_reference: str
    content_type: str | None = None
    file_size: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
