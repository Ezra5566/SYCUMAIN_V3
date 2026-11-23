"""Academic admission episodes, placements, changes and verification history.

Phase 0 of the academic admission architecture. These tables are additive: no
existing academic, timetable or student record is read or rewritten by this
module. Lifecycle rules that cannot be expressed as constraints are enforced by
triggers created in the accompanying Alembic revision.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base

# --- Enums ---


class AcademicAdmissionStatus(enum.StrEnum):
    """Lifecycle of one admission episode."""

    PENDING = "PENDING"
    ADMITTED = "ADMITTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class AdmissionRecordOrigin(enum.StrEnum):
    """Whether an episode was created normally or reconstructed for a student."""

    NEW_ADMISSION = "NEW_ADMISSION"
    MIGRATED = "MIGRATED"


class AdmissionVerificationStatus(enum.StrEnum):
    """Trust state of a reconstructed admission."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    REVOKED = "REVOKED"


class AdmissionConfirmationState(enum.StrEnum):
    """State of one migration-confirmation slot."""

    NONE = "NONE"
    CONFIRMED = "CONFIRMED"
    REVOKED = "REVOKED"


class AdmissionChangeType(enum.StrEnum):
    PROGRAM_CHANGE = "PROGRAM_CHANGE"
    PLACEMENT_CHANGE = "PLACEMENT_CHANGE"
    EARLIER_INTAKE_PLACEMENT = "EARLIER_INTAKE_PLACEMENT"
    WITHDRAWAL = "WITHDRAWAL"
    STATUS_CORRECTION = "STATUS_CORRECTION"


class AdmissionChangeStatus(enum.StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class AdmissionVerificationSlot(enum.StrEnum):
    MANAGEMENT = "MANAGEMENT"
    ADMIN = "ADMIN"


class AdmissionVerificationAction(enum.StrEnum):
    CONFIRM = "CONFIRM"
    REVOKE = "REVOKE"


class AdmissionEvidenceType(enum.StrEnum):
    ADMISSION_LETTER = "ADMISSION_LETTER"
    ENROLMENT_RECORD = "ENROLMENT_RECORD"
    REGISTER_EXTRACT = "REGISTER_EXTRACT"
    OTHER = "OTHER"


# --- Models ---


class AcademicAdmission(Base):
    """One admission episode for a student.

    ``admitted_program_id`` and ``admitted_program_offering_id`` are the
    historical record of admission and are immutable once verified. A later
    approved programme change updates ``current_program_id`` only.
    """

    __tablename__ = "academic_admissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
    )
    admission_intake_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_periods.id", ondelete="RESTRICT"),
        nullable=False,
    )
    admitted_program_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="RESTRICT"), nullable=True
    )
    admitted_program_offering_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("program_offerings.id", ondelete="RESTRICT"), nullable=False
    )
    current_program_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="RESTRICT"), nullable=True
    )
    current_program_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AcademicAdmissionStatus.PENDING
    )
    initial_status: Mapped[str] = mapped_column(String(20), nullable=False)
    record_origin: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AdmissionRecordOrigin.NEW_ADMISSION
    )
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AdmissionVerificationStatus.UNVERIFIED
    )

    management_confirmation_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AdmissionConfirmationState.NONE
    )
    management_confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    management_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    management_revoked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    management_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    management_revocation_reason: Mapped[str | None] = mapped_column(Text)

    admin_confirmation_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AdmissionConfirmationState.NONE
    )
    admin_confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    admin_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_revoked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    admin_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_revocation_reason: Mapped[str | None] = mapped_column(Text)

    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(Text)

    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["admission_intake_id", "admitted_program_offering_id"],
            ["program_offerings.academic_period_id", "program_offerings.id"],
            name="fk_admission_offering_in_intake",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('PENDING','ADMITTED','ACTIVE','COMPLETED','WITHDRAWN','CANCELLED')",
            name="ck_admission_status",
        ),
        CheckConstraint(
            "record_origin IN ('NEW_ADMISSION','MIGRATED')", name="ck_record_origin"
        ),
        CheckConstraint(
            "verification_status IN ('UNVERIFIED','VERIFIED','DISPUTED','REVOKED')",
            name="ck_admission_verification_status",
        ),
        CheckConstraint(
            "management_confirmation_state IN ('NONE','CONFIRMED','REVOKED')",
            name="ck_admission_mgmt_state",
        ),
        CheckConstraint(
            "admin_confirmation_state IN ('NONE','CONFIRMED','REVOKED')",
            name="ck_admission_admin_state",
        ),
        CheckConstraint(
            "status <> 'ACTIVE' OR activated_at IS NOT NULL",
            name="ck_admission_active_has_activation",
        ),
        CheckConstraint(
            "(status IN ('COMPLETED','WITHDRAWN','CANCELLED')) = (ended_at IS NOT NULL)",
            name="ck_admission_terminal_has_end",
        ),
        CheckConstraint(
            "status NOT IN ('WITHDRAWN','CANCELLED') OR end_reason IS NOT NULL",
            name="ck_admission_end_reason",
        ),
        CheckConstraint(
            "(management_confirmation_state = 'REVOKED') = (management_revoked_at IS NOT NULL)",
            name="ck_mgmt_revoked_fields",
        ),
        CheckConstraint(
            "(admin_confirmation_state = 'REVOKED') = (admin_revoked_at IS NOT NULL)",
            name="ck_admin_revoked_fields",
        ),
        CheckConstraint(
            "management_confirmation_state <> 'CONFIRMED' OR management_confirmed_at IS NOT NULL",
            name="ck_mgmt_confirmed_has_actor",
        ),
        CheckConstraint(
            "admin_confirmation_state <> 'CONFIRMED' OR admin_confirmed_at IS NOT NULL",
            name="ck_admin_confirmed_has_actor",
        ),
        CheckConstraint(
            "verification_status <> 'VERIFIED' OR record_origin = 'NEW_ADMISSION' "
            "OR (management_confirmation_state = 'CONFIRMED' "
            "AND admin_confirmation_state = 'CONFIRMED')",
            name="ck_verified_requires_both",
        ),
        CheckConstraint(
            "record_origin = 'MIGRATED' OR verification_status = 'VERIFIED'",
            name="ck_origin_status",
        ),
        CheckConstraint(
            "verification_status <> 'REVOKED' "
            "OR management_confirmation_state = 'REVOKED' "
            "OR admin_confirmation_state = 'REVOKED'",
            name="ck_revoked_requires_slot",
        ),
        Index("ix_academic_admissions_student_id", "student_id"),
        Index("ix_academic_admissions_admission_intake_id", "admission_intake_id"),
        Index("ix_admission_intake_status", "admission_intake_id", "status"),
        Index(
            "uq_academic_admission_one_active",
            "student_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index(
            "uq_academic_admission_student_intake_live",
            "student_id",
            "admission_intake_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING','ADMITTED','ACTIVE')"),
        ),
    )


class AcademicAdmissionStatusHistory(Base):
    """Append-only lifecycle record; one row per admission status event."""

    __tablename__ = "academic_admission_status_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_admissions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    is_correction: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    corrected_from_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status <> to_status",
            name="ck_status_history_distinct",
        ),
        Index("ix_admission_status_history_admission_id", "admission_id"),
    )


class AcademicPlacement(Base):
    """A student's placement into an intake's programme offering.

    ``is_earlier_intake_placement`` records whether the placement intake starts
    before the admission intake; the CHECK makes authorization mandatory in that
    case.
    """

    __tablename__ = "academic_placements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
    )
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_admissions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    academic_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_periods.id", ondelete="RESTRICT"),
        nullable=False,
    )
    program_offering_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("program_offerings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_earlier_intake_placement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    authorized_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    authorization_reason: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["academic_period_id", "program_offering_id"],
            ["program_offerings.academic_period_id", "program_offerings.id"],
            name="fk_placement_offering_in_period",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "NOT is_earlier_intake_placement OR "
            "(authorized_by_id IS NOT NULL AND authorization_reason IS NOT NULL)",
            name="ck_placement_earlier_authorized",
        ),
        CheckConstraint(
            "authorization_reason IS NULL OR length(btrim(authorization_reason)) > 0",
            name="ck_placement_reason_not_blank",
        ),
        Index("ix_academic_placements_student_id", "student_id"),
        Index("ix_academic_placements_admission_id", "admission_id"),
        Index(
            "uq_academic_placement_current",
            "student_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )


class AcademicAdmissionChange(Base):
    """Request, approval and history of a change within one admission episode."""

    __tablename__ = "academic_admission_changes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_admissions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    from_program_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="RESTRICT")
    )
    to_program_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="RESTRICT")
    )
    from_program_offering_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("program_offerings.id", ondelete="RESTRICT")
    )
    to_program_offering_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("program_offerings.id", ondelete="RESTRICT")
    )
    target_period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_periods.id", ondelete="RESTRICT")
    )
    proposed_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    current_data_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AdmissionChangeStatus.PENDING,
        server_default=AdmissionChangeStatus.PENDING,
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "change_type IN ('PROGRAM_CHANGE','PLACEMENT_CHANGE',"
            "'EARLIER_INTAKE_PLACEMENT','WITHDRAWAL','STATUS_CORRECTION')",
            name="ck_admission_change_type",
        ),
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','CANCELLED')",
            name="ck_admission_change_status",
        ),
        CheckConstraint(
            "change_type <> 'PROGRAM_CHANGE' OR (to_program_id IS NOT NULL "
            "AND (from_program_id IS NULL OR to_program_id <> from_program_id))",
            name="ck_program_change_target",
        ),
        CheckConstraint(
            "(status IN ('APPROVED','REJECTED')) = "
            "(reviewed_by_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_change_review_pair",
        ),
        CheckConstraint(
            "reviewed_by_id IS NULL OR reviewed_by_id <> requested_by_id",
            name="ck_no_self_approval",
        ),
        Index("ix_academic_admission_changes_admission_id", "admission_id"),
        Index(
            "uq_admission_change_one_pending",
            "admission_id",
            "change_type",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )


class AcademicAdmissionVerificationAct(Base):
    """Append-only confirmation or revocation of a migration slot."""

    __tablename__ = "academic_admission_verification_acts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_admissions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    slot: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    acted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    candidate_intake_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_periods.id", ondelete="RESTRICT"),
        nullable=False,
    )
    candidate_program_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="RESTRICT")
    )
    evidence_type: Mapped[str | None] = mapped_column(String(30))
    evidence_reference: Mapped[str | None] = mapped_column(Text)
    evidence_note: Mapped[str | None] = mapped_column(Text)
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    resulting_verification_status: Mapped[str | None] = mapped_column(String(20))

    __table_args__ = (
        CheckConstraint(
            "slot IN ('MANAGEMENT','ADMIN')", name="ck_verification_act_slot"
        ),
        CheckConstraint(
            "action IN ('CONFIRM','REVOKE')", name="ck_verification_act_action"
        ),
        CheckConstraint(
            "evidence_type IS NULL OR evidence_type IN "
            "('ADMISSION_LETTER','ENROLMENT_RECORD','REGISTER_EXTRACT','OTHER')",
            name="ck_verification_act_evidence",
        ),
        Index("ix_academic_admission_verification_acts_admission_id", "admission_id"),
    )


class AcademicPeriodDateCorrection(Base):
    """Audited correction of an intake's official dates."""

    __tablename__ = "academic_period_date_corrections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    academic_period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_periods.id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    previous_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    new_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    new_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    placements_reflagged: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    admissions_rechecked: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        Index(
            "ix_academic_period_date_corrections_period_id", "academic_period_id"
        ),
    )


class StudentOriginalAdmissionHistory(Base):
    """Audited replacement of the original-admission pointer."""

    __tablename__ = "student_original_admission_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_admission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_admissions.id", ondelete="RESTRICT"),
    )
    new_admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_admissions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_student_original_admission_history_student_id", "student_id"),
    )


__all__ = [
    "AcademicAdmission",
    "AcademicAdmissionStatus",
    "AcademicAdmissionStatusHistory",
    "AcademicAdmissionChange",
    "AcademicAdmissionVerificationAct",
    "AcademicPlacement",
    "AcademicPeriodDateCorrection",
    "StudentOriginalAdmissionHistory",
    "AdmissionRecordOrigin",
    "AdmissionVerificationStatus",
    "AdmissionConfirmationState",
    "AdmissionChangeType",
    "AdmissionChangeStatus",
    "AdmissionVerificationSlot",
    "AdmissionVerificationAction",
    "AdmissionEvidenceType",
]
