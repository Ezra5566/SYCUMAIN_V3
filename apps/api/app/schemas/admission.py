"""Admission episode request and response schemas (Phase 1)."""

from __future__ import annotations

import uuid  # noqa: TC003
from datetime import date, datetime  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, Field

from app.models.admission import (  # noqa: TC001
    AcademicAdmissionStatus,
    AdmissionChangeStatus,
    AdmissionChangeType,
    AdmissionConfirmationState,
    AdmissionEvidenceType,
    AdmissionRecordOrigin,
    AdmissionVerificationSlot,
    AdmissionVerificationStatus,
)

InitialAdmissionStatus = Literal["PENDING", "ADMITTED", "ACTIVE"]
TransitionStatus = Literal["ADMITTED", "ACTIVE", "COMPLETED", "WITHDRAWN", "CANCELLED"]


class AdmissionCreate(BaseModel):
    """Record one admission episode.

    The intake and offering are both required: an admission without a
    period-specific cohort offering cannot be placed or audited. The admitted
    programme is derived from the offering, never from the client, so the
    historical record cannot disagree with the delivery record.
    """

    admission_intake_id: uuid.UUID
    program_offering_id: uuid.UUID
    initial_status: InitialAdmissionStatus = "ACTIVE"


class AdmissionTransition(BaseModel):
    """Move an episode through the §2.2 lifecycle."""

    status: TransitionStatus
    reason: str | None = Field(None, max_length=2000)


class AdmissionStatusCorrection(BaseModel):
    """ADMIN-only correction of a mistaken lifecycle status.

    The correction path records its own history row; it is not a way to edit
    the admission's intake, programme or offering.
    """

    target_status: AcademicAdmissionStatus
    reason: str = Field("", max_length=2000)


class MigratedAdmissionCreate(BaseModel):
    """Propose the original admission for an existing student."""

    admission_intake_id: uuid.UUID
    program_offering_id: uuid.UUID


class MigratedAdmissionUpdate(BaseModel):
    """Correct an unverified migrated candidate before both slots confirm."""

    admission_intake_id: uuid.UUID | None = None
    program_offering_id: uuid.UUID | None = None


class VerificationConfirm(BaseModel):
    """One institutional confirmation of a migration candidate."""

    evidence_type: AdmissionEvidenceType
    evidence_reference: str = Field("", max_length=500)
    evidence_note: str | None = Field(None, max_length=2000)


class VerificationRevoke(BaseModel):
    """Revoke one confirmed slot without erasing its act history."""

    reason: str = Field("", max_length=2000)


class VerificationActRead(BaseModel):
    """One append-only confirmation or revocation act."""

    id: uuid.UUID
    admission_id: uuid.UUID
    slot: AdmissionVerificationSlot
    action: str
    actor_id: uuid.UUID
    actor_name: str | None = None
    acted_at: datetime
    candidate_intake_id: uuid.UUID
    candidate_intake_name: str | None = None
    candidate_intake_code: str | None = None
    candidate_program_id: uuid.UUID | None = None
    candidate_program_name: str | None = None
    evidence_type: AdmissionEvidenceType | None = None
    evidence_reference: str | None = None
    evidence_note: str | None = None
    revocation_reason: str | None = None
    resulting_verification_status: AdmissionVerificationStatus | None = None

    model_config = {"from_attributes": True}


class OriginalAdmissionCorrection(BaseModel):
    """ADMIN-only replacement of the original-admission pointer."""

    new_admission_id: uuid.UUID
    reason: str = Field("", max_length=2000)
    evidence_reference: str | None = Field(None, max_length=500)


class OriginalAdmissionCorrectionRead(BaseModel):
    """Result of an audited pointer replacement."""

    student_id: uuid.UUID
    previous_admission_id: uuid.UUID | None = None
    original_admission_id: uuid.UUID


class PlacementCreate(BaseModel):
    """Assign or supersede a student's current academic placement."""

    admission_id: uuid.UUID
    program_offering_id: uuid.UUID
    effective_from: date | None = None
    reason: str | None = Field(None, max_length=2000)


class PlacementRead(BaseModel):
    """One placement, with admission and placement intakes kept separate."""

    id: uuid.UUID
    student_id: uuid.UUID
    admission_id: uuid.UUID

    admission_intake_id: uuid.UUID
    admission_intake_code: str | None = None
    admission_intake_name: str | None = None
    admission_intake_start_date: date | None = None

    placement_intake_id: uuid.UUID
    placement_intake_code: str | None = None
    placement_intake_name: str | None = None
    placement_intake_start_date: date | None = None

    program_id: uuid.UUID | None = None
    program_name: str | None = None
    program_offering_id: uuid.UUID
    program_offering_name: str | None = None

    is_earlier_intake_placement: bool
    authorized_by_id: uuid.UUID | None = None
    authorized_by_name: str | None = None
    authorization_reason: str | None = None
    effective_from: date
    ended_at: datetime | None = None
    is_current: bool = False
    created_by_id: uuid.UUID
    created_by_name: str | None = None
    created_at: datetime


class PlacementListResponse(BaseModel):
    """Placement history, newest first."""

    items: list[PlacementRead]
    total: int


class AdmissionRead(BaseModel):
    """One episode, with admitted and current programme kept separate."""

    id: uuid.UUID
    student_id: uuid.UUID
    status: AcademicAdmissionStatus
    initial_status: AcademicAdmissionStatus
    record_origin: AdmissionRecordOrigin
    verification_status: AdmissionVerificationStatus

    admission_intake_id: uuid.UUID
    admission_intake_code: str | None = None
    admission_intake_name: str | None = None
    admission_intake_start_date: date | None = None
    admission_intake_end_date: date | None = None

    admitted_program_id: uuid.UUID | None = None
    admitted_program_name: str | None = None
    admitted_program_offering_id: uuid.UUID
    admitted_program_offering_name: str | None = None
    current_program_id: uuid.UUID | None = None
    current_program_name: str | None = None

    management_confirmation_state: AdmissionConfirmationState = (
        AdmissionConfirmationState.NONE
    )
    management_confirmed_by_id: uuid.UUID | None = None
    management_confirmed_at: datetime | None = None
    management_revoked_at: datetime | None = None
    admin_confirmation_state: AdmissionConfirmationState = (
        AdmissionConfirmationState.NONE
    )
    admin_confirmed_by_id: uuid.UUID | None = None
    admin_confirmed_at: datetime | None = None
    admin_revoked_at: datetime | None = None

    activated_at: datetime | None = None
    ended_at: datetime | None = None
    end_reason: str | None = None
    verified_at: datetime | None = None
    corrections_enabled: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdmissionListResponse(BaseModel):
    """All episodes for one student, newest first."""

    items: list[AdmissionRead]
    total: int


class AdmissionChangeCreate(BaseModel):
    """Request one controlled change inside an existing admission episode.

    The client may name a target programme, offering and intake, but it never
    supplies the old values, the reviewer or the resulting projection. Those
    are snapshotted and applied by the service from authoritative rows.
    """

    change_type: AdmissionChangeType
    to_program_id: uuid.UUID | None = None
    to_program_offering_id: uuid.UUID | None = None
    target_period_id: uuid.UUID | None = None
    proposed_data: dict = Field(default_factory=dict)
    reason: str | None = Field(None, max_length=2000)


class AdmissionChangeReview(BaseModel):
    """One Admin/Management decision; there is no second-approver state."""

    decision: Literal["APPROVE", "REJECT"]
    reason: str | None = Field(None, max_length=2000)


class AdmissionChangeRead(BaseModel):
    """A request and its decision, with names resolved for the timeline."""

    id: uuid.UUID
    admission_id: uuid.UUID
    student_id: uuid.UUID
    change_type: AdmissionChangeType
    status: AdmissionChangeStatus

    from_program_id: uuid.UUID | None = None
    from_program_name: str | None = None
    to_program_id: uuid.UUID | None = None
    to_program_name: str | None = None
    from_program_offering_id: uuid.UUID | None = None
    from_program_offering_name: str | None = None
    to_program_offering_id: uuid.UUID | None = None
    to_program_offering_name: str | None = None
    target_period_id: uuid.UUID | None = None
    target_period_name: str | None = None

    proposed_data: dict
    current_data_snapshot: dict | None = None
    reason: str | None = None
    requested_by_id: uuid.UUID
    requested_by_name: str | None = None
    requested_at: datetime
    reviewed_by_id: uuid.UUID | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    decision_reason: str | None = None


class AdmissionChangeListResponse(BaseModel):
    """Change history for one episode or one student, newest first."""

    items: list[AdmissionChangeRead]
    total: int


class MigrationQueueItem(BaseModel):
    """One MIGRATED admission row in the staff verification queue."""

    admission_id: uuid.UUID
    student_id: uuid.UUID
    student_number: str
    student_name: str
    admission_status: AcademicAdmissionStatus
    verification_status: AdmissionVerificationStatus

    admission_intake_id: uuid.UUID
    admission_intake_code: str | None = None
    admission_intake_name: str | None = None
    admission_intake_start_date: date | None = None
    admitted_program_id: uuid.UUID | None = None
    admitted_program_name: str | None = None
    admitted_program_offering_id: uuid.UUID
    admitted_program_offering_name: str | None = None

    management_confirmation_state: AdmissionConfirmationState
    management_confirmed_by_id: uuid.UUID | None = None
    management_confirmed_at: datetime | None = None
    management_revoked_at: datetime | None = None
    admin_confirmation_state: AdmissionConfirmationState
    admin_confirmed_by_id: uuid.UUID | None = None
    admin_confirmed_at: datetime | None = None
    admin_revoked_at: datetime | None = None
    outstanding_slots: list[AdmissionVerificationSlot]

    original_admission_id: uuid.UUID | None = None
    is_original_admission: bool = False
    verified_at: datetime | None = None
    corrections_enabled: bool = False
    created_at: datetime


class MigrationQueueResponse(BaseModel):
    """Paginated migration queue."""

    items: list[MigrationQueueItem]
    total: int
    page: int
    page_size: int
