"""Academic admission architecture, Phase 0: schema, constraints and triggers.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6

Additive only. No existing student, academic or timetable record is read or
rewritten, and no admission history is backfilled. New permissions are seeded by
``seed_roles_and_permissions`` at application startup, not by this revision.

Downgrade refuses while any new table contains rows: the documented rollback for
this phase is to revert the release and leave the additive schema in place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "e2f3a4b5c6d7"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_TABLES = (
    "academic_admissions",
    "academic_admission_status_history",
    "academic_placements",
    "academic_admission_changes",
    "academic_admission_verification_acts",
    "academic_period_date_corrections",
    "student_original_admission_history",
)

TRIGGER_TABLES = (
    "academic_admissions",
    "academic_admission_status_history",
    "academic_placements",
    "academic_admission_changes",
    "academic_admission_verification_acts",
    "academic_period_date_corrections",
    "student_original_admission_history",
)


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _timestamps():
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def upgrade() -> None:
    # The composite foreign keys below need a unique target on the offering.
    op.create_unique_constraint(
        "uq_program_offering_period_id",
        "program_offerings",
        ["academic_period_id", "id"],
    )

    # Official intake dates can be corrected, but never into an inverted range.
    op.create_check_constraint(
        "ck_academic_period_date_order",
        "academic_periods",
        "end_date >= start_date",
    )

    # Nullable, no default, no backfill. Existing students remain unverified.
    op.add_column(
        "students",
        sa.Column("original_admission_id", _uuid(), nullable=True),
    )

    op.create_table(
        "academic_admissions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("admission_intake_id", _uuid(), nullable=False),
        sa.Column("admitted_program_id", _uuid(), nullable=True),
        sa.Column("admitted_program_offering_id", _uuid(), nullable=False),
        sa.Column("current_program_id", _uuid(), nullable=True),
        sa.Column("current_program_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("initial_status", sa.String(length=20), nullable=False),
        sa.Column("record_origin", sa.String(length=20), nullable=False),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column(
            "management_confirmation_state",
            sa.String(length=20),
            nullable=False,
            server_default="NONE",
        ),
        sa.Column("management_confirmed_by_id", _uuid(), nullable=True),
        sa.Column("management_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("management_revoked_by_id", _uuid(), nullable=True),
        sa.Column("management_revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("management_revocation_reason", sa.Text(), nullable=True),
        sa.Column(
            "admin_confirmation_state",
            sa.String(length=20),
            nullable=False,
            server_default="NONE",
        ),
        sa.Column("admin_confirmed_by_id", _uuid(), nullable=True),
        sa.Column("admin_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_revoked_by_id", _uuid(), nullable=True),
        sa.Column("admin_revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_revocation_reason", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", _uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="fk_admission_student", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["admission_intake_id"],
            ["academic_periods.id"],
            name="fk_admission_intake",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["admitted_program_id"],
            ["programs.id"],
            name="fk_admission_admitted_program",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["admitted_program_offering_id"],
            ["program_offerings.id"],
            name="fk_admission_admitted_offering",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_program_id"],
            ["programs.id"],
            name="fk_admission_current_program",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name="fk_admission_created_by", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["management_confirmed_by_id"],
            ["users.id"],
            name="fk_admission_mgmt_confirmed_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["management_revoked_by_id"],
            ["users.id"],
            name="fk_admission_mgmt_revoked_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["admin_confirmed_by_id"],
            ["users.id"],
            name="fk_admission_admin_confirmed_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["admin_revoked_by_id"],
            ["users.id"],
            name="fk_admission_admin_revoked_by",
            ondelete="RESTRICT",
        ),
        # Offering must belong to the admission intake.
        sa.ForeignKeyConstraint(
            ["admission_intake_id", "admitted_program_offering_id"],
            ["program_offerings.academic_period_id", "program_offerings.id"],
            name="fk_admission_offering_in_intake",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('PENDING','ADMITTED','ACTIVE','COMPLETED','WITHDRAWN','CANCELLED')",
            name="ck_admission_status",
        ),
        sa.CheckConstraint(
            "record_origin IN ('NEW_ADMISSION','MIGRATED')", name="ck_record_origin"
        ),
        sa.CheckConstraint(
            "verification_status IN ('UNVERIFIED','VERIFIED','DISPUTED','REVOKED')",
            name="ck_admission_verification_status",
        ),
        sa.CheckConstraint(
            "management_confirmation_state IN ('NONE','CONFIRMED','REVOKED')",
            name="ck_admission_mgmt_state",
        ),
        sa.CheckConstraint(
            "admin_confirmation_state IN ('NONE','CONFIRMED','REVOKED')",
            name="ck_admission_admin_state",
        ),
        sa.CheckConstraint(
            "status <> 'ACTIVE' OR activated_at IS NOT NULL",
            name="ck_admission_active_has_activation",
        ),
        sa.CheckConstraint(
            "(status IN ('COMPLETED','WITHDRAWN','CANCELLED')) = (ended_at IS NOT NULL)",
            name="ck_admission_terminal_has_end",
        ),
        sa.CheckConstraint(
            "status NOT IN ('WITHDRAWN','CANCELLED') OR end_reason IS NOT NULL",
            name="ck_admission_end_reason",
        ),
        sa.CheckConstraint(
            "(management_confirmation_state = 'REVOKED') "
            "= (management_revoked_at IS NOT NULL)",
            name="ck_mgmt_revoked_fields",
        ),
        sa.CheckConstraint(
            "(admin_confirmation_state = 'REVOKED') = (admin_revoked_at IS NOT NULL)",
            name="ck_admin_revoked_fields",
        ),
        sa.CheckConstraint(
            "management_confirmation_state <> 'CONFIRMED' "
            "OR management_confirmed_at IS NOT NULL",
            name="ck_mgmt_confirmed_has_actor",
        ),
        sa.CheckConstraint(
            "admin_confirmation_state <> 'CONFIRMED' OR admin_confirmed_at IS NOT NULL",
            name="ck_admin_confirmed_has_actor",
        ),
        sa.CheckConstraint(
            "verification_status <> 'VERIFIED' OR record_origin = 'NEW_ADMISSION' "
            "OR (management_confirmation_state = 'CONFIRMED' "
            "AND admin_confirmation_state = 'CONFIRMED')",
            name="ck_verified_requires_both",
        ),
        sa.CheckConstraint(
            "record_origin = 'MIGRATED' OR verification_status = 'VERIFIED'",
            name="ck_origin_status",
        ),
        sa.CheckConstraint(
            "verification_status <> 'REVOKED' "
            "OR management_confirmation_state = 'REVOKED' "
            "OR admin_confirmation_state = 'REVOKED'",
            name="ck_revoked_requires_slot",
        ),
    )

    op.create_index(
        "ix_academic_admissions_student_id", "academic_admissions", ["student_id"]
    )
    op.create_index(
        "ix_academic_admissions_admission_intake_id",
        "academic_admissions",
        ["admission_intake_id"],
    )
    op.create_index(
        "ix_admission_intake_status",
        "academic_admissions",
        ["admission_intake_id", "status"],
    )
    op.create_index(
        "uq_academic_admission_one_active",
        "academic_admissions",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "uq_academic_admission_student_intake_live",
        "academic_admissions",
        ["student_id", "admission_intake_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING','ADMITTED','ACTIVE')"),
    )

    op.create_table(
        "academic_admission_status_history",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("admission_id", _uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("actor_id", _uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "is_correction", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("corrected_from_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["admission_id"],
            ["academic_admissions.id"],
            name="fk_status_history_admission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_status_history_actor", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status <> to_status",
            name="ck_status_history_distinct",
        ),
    )
    op.create_index(
        "ix_admission_status_history_admission_id",
        "academic_admission_status_history",
        ["admission_id"],
    )

    op.create_table(
        "academic_placements",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("admission_id", _uuid(), nullable=False),
        sa.Column("academic_period_id", _uuid(), nullable=False),
        sa.Column("program_offering_id", _uuid(), nullable=False),
        sa.Column("is_earlier_intake_placement", sa.Boolean(), nullable=False),
        sa.Column("authorized_by_id", _uuid(), nullable=True),
        sa.Column("authorization_reason", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", _uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="fk_placement_student", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["admission_id"],
            ["academic_admissions.id"],
            name="fk_placement_admission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["academic_period_id"],
            ["academic_periods.id"],
            name="fk_placement_period",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["program_offering_id"],
            ["program_offerings.id"],
            name="fk_placement_offering",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["authorized_by_id"],
            ["users.id"],
            name="fk_placement_authorized_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name="fk_placement_created_by", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["academic_period_id", "program_offering_id"],
            ["program_offerings.academic_period_id", "program_offerings.id"],
            name="fk_placement_offering_in_period",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "NOT is_earlier_intake_placement OR "
            "(authorized_by_id IS NOT NULL AND authorization_reason IS NOT NULL)",
            name="ck_placement_earlier_authorized",
        ),
        sa.CheckConstraint(
            "authorization_reason IS NULL OR length(btrim(authorization_reason)) > 0",
            name="ck_placement_reason_not_blank",
        ),
    )
    op.create_index("ix_academic_placements_student_id", "academic_placements", ["student_id"])
    op.create_index(
        "ix_academic_placements_admission_id", "academic_placements", ["admission_id"]
    )
    op.create_index(
        "uq_academic_placement_current",
        "academic_placements",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    op.create_table(
        "academic_admission_changes",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("admission_id", _uuid(), nullable=False),
        sa.Column("change_type", sa.String(length=40), nullable=False),
        sa.Column("from_program_id", _uuid(), nullable=True),
        sa.Column("to_program_id", _uuid(), nullable=True),
        sa.Column("from_program_offering_id", _uuid(), nullable=True),
        sa.Column("to_program_offering_id", _uuid(), nullable=True),
        sa.Column("target_period_id", _uuid(), nullable=True),
        sa.Column(
            "proposed_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "current_data_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_by_id", _uuid(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="PENDING"
        ),
        sa.Column("reviewed_by_id", _uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["admission_id"],
            ["academic_admissions.id"],
            name="fk_change_admission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_program_id"],
            ["programs.id"],
            name="fk_change_from_program",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_program_id"],
            ["programs.id"],
            name="fk_change_to_program",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_program_offering_id"],
            ["program_offerings.id"],
            name="fk_change_from_offering",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_program_offering_id"],
            ["program_offerings.id"],
            name="fk_change_to_offering",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_period_id"],
            ["academic_periods.id"],
            name="fk_change_target_period",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            name="fk_change_requested_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            name="fk_change_reviewed_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "change_type IN ('PROGRAM_CHANGE','PLACEMENT_CHANGE',"
            "'EARLIER_INTAKE_PLACEMENT','WITHDRAWAL','STATUS_CORRECTION')",
            name="ck_admission_change_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','CANCELLED')",
            name="ck_admission_change_status",
        ),
        sa.CheckConstraint(
            "change_type <> 'PROGRAM_CHANGE' OR (to_program_id IS NOT NULL "
            "AND (from_program_id IS NULL OR to_program_id <> from_program_id))",
            name="ck_program_change_target",
        ),
        sa.CheckConstraint(
            "(status IN ('APPROVED','REJECTED')) = "
            "(reviewed_by_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_change_review_pair",
        ),
        sa.CheckConstraint(
            "reviewed_by_id IS NULL OR reviewed_by_id <> requested_by_id",
            name="ck_no_self_approval",
        ),
    )
    op.create_index(
        "ix_academic_admission_changes_admission_id",
        "academic_admission_changes",
        ["admission_id"],
    )
    op.create_index(
        "uq_admission_change_one_pending",
        "academic_admission_changes",
        ["admission_id", "change_type"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "academic_admission_verification_acts",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("admission_id", _uuid(), nullable=False),
        sa.Column("slot", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("actor_id", _uuid(), nullable=False),
        sa.Column(
            "acted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("candidate_intake_id", _uuid(), nullable=False),
        sa.Column("candidate_program_id", _uuid(), nullable=True),
        sa.Column("evidence_type", sa.String(length=30), nullable=True),
        sa.Column("evidence_reference", sa.Text(), nullable=True),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("resulting_verification_status", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(
            ["admission_id"],
            ["academic_admissions.id"],
            name="fk_verification_act_admission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_verification_act_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_intake_id"],
            ["academic_periods.id"],
            name="fk_verification_act_intake",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_program_id"],
            ["programs.id"],
            name="fk_verification_act_program",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "slot IN ('MANAGEMENT','ADMIN')", name="ck_verification_act_slot"
        ),
        sa.CheckConstraint(
            "action IN ('CONFIRM','REVOKE')", name="ck_verification_act_action"
        ),
        sa.CheckConstraint(
            "evidence_type IS NULL OR evidence_type IN "
            "('ADMISSION_LETTER','ENROLMENT_RECORD','REGISTER_EXTRACT','OTHER')",
            name="ck_verification_act_evidence",
        ),
    )
    op.create_index(
        "ix_academic_admission_verification_acts_admission_id",
        "academic_admission_verification_acts",
        ["admission_id"],
    )

    op.create_table(
        "academic_period_date_corrections",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("academic_period_id", _uuid(), nullable=False),
        sa.Column("previous_start_date", sa.Date(), nullable=False),
        sa.Column("previous_end_date", sa.Date(), nullable=False),
        sa.Column("new_start_date", sa.Date(), nullable=False),
        sa.Column("new_end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", _uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "placements_reflagged",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "admissions_rechecked",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.ForeignKeyConstraint(
            ["academic_period_id"],
            ["academic_periods.id"],
            name="fk_period_correction_period",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_period_correction_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_academic_period_date_corrections_period_id",
        "academic_period_date_corrections",
        ["academic_period_id"],
    )

    op.create_table(
        "student_original_admission_history",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("previous_admission_id", _uuid(), nullable=True),
        sa.Column("new_admission_id", _uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", _uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name="fk_pointer_history_student", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["previous_admission_id"],
            ["academic_admissions.id"],
            name="fk_pointer_history_previous",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["new_admission_id"],
            ["academic_admissions.id"],
            name="fk_pointer_history_new",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_pointer_history_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_student_original_admission_history_student_id",
        "student_original_admission_history",
        ["student_id"],
    )

    op.create_foreign_key(
        "fk_students_original_admission",
        "students",
        "academic_admissions",
        ["original_admission_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_students_original_admission", "students", ["original_admission_id"]
    )
    op.create_index(
        "uq_student_original_admission",
        "students",
        ["original_admission_id"],
        unique=True,
        postgresql_where=sa.text("original_admission_id IS NOT NULL"),
    )

    # --- Trigger functions -------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scu_admission_admitted_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            -- ACTIVE/ACTIVE is already impossible through the partial unique
            -- index; this guards the case an index cannot express:
            -- an ADMITTED episode beside one that is still ACTIVE.
            IF NEW.status = 'ADMITTED' THEN
                IF EXISTS (
                    SELECT 1 FROM academic_admissions a
                     WHERE a.student_id = NEW.student_id
                       AND a.status = 'ACTIVE'
                       AND a.id <> NEW.id
                ) THEN
                    RAISE EXCEPTION
                        'student % already has an active admission', NEW.student_id;
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scu_admission_transition_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            v_actor uuid;
            v_correction boolean;
            v_reason text;
        BEGIN
            v_correction :=
                coalesce(current_setting('scu.admission_correction', true), '') = 'on';

            IF TG_OP = 'INSERT' THEN
                INSERT INTO academic_admission_status_history
                    (id, admission_id, from_status, to_status, actor_id, reason,
                     is_correction, corrected_from_recorded_at, created_at)
                VALUES
                    (gen_random_uuid(), NEW.id, NULL, NEW.status,
                     NEW.created_by_id, NEW.end_reason, v_correction, NULL, now());
                RETURN NULL;
            END IF;

            IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
                RETURN NULL;
            END IF;

            IF NOT v_correction AND NOT (
                   (OLD.status = 'PENDING'
                    AND NEW.status IN ('ADMITTED','ACTIVE','CANCELLED'))
                OR (OLD.status = 'ADMITTED'
                    AND NEW.status IN ('ACTIVE','CANCELLED'))
                OR (OLD.status = 'ACTIVE'
                    AND NEW.status IN ('COMPLETED','WITHDRAWN'))
            ) THEN
                RAISE EXCEPTION 'illegal admission transition % -> %',
                    OLD.status, NEW.status;
            END IF;

            v_actor := coalesce(
                nullif(current_setting('scu.actor_id', true), '')::uuid,
                NEW.created_by_id
            );
            v_reason := coalesce(
                nullif(current_setting('scu.correction_reason', true), ''),
                NEW.end_reason
            );

            INSERT INTO academic_admission_status_history
                (id, admission_id, from_status, to_status, actor_id, reason,
                 is_correction, corrected_from_recorded_at, created_at)
            VALUES
                (gen_random_uuid(), NEW.id, OLD.status, NEW.status,
                 v_actor, v_reason, v_correction,
                 CASE WHEN v_correction THEN OLD.ended_at ELSE NULL END, now());
            RETURN NULL;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scu_admission_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (OLD.verification_status = 'VERIFIED' OR OLD.activated_at IS NOT NULL)
               AND (
                    NEW.admission_intake_id IS DISTINCT FROM OLD.admission_intake_id
                 OR NEW.admitted_program_id IS DISTINCT FROM OLD.admitted_program_id
                 OR NEW.admitted_program_offering_id
                        IS DISTINCT FROM OLD.admitted_program_offering_id
                 OR NEW.initial_status IS DISTINCT FROM OLD.initial_status
               )
            THEN
                RAISE EXCEPTION
                    'verified admission % is immutable', OLD.id;
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scu_forbid_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'deletes are not allowed on %', TG_TABLE_NAME;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scu_original_admission_once()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            v_flag text;
        BEGIN
            IF NEW.original_admission_id IS NULL
               AND OLD.original_admission_id IS NOT NULL THEN
                RAISE EXCEPTION 'the original admission pointer cannot be cleared';
            END IF;

            IF OLD.original_admission_id IS NOT NULL
               AND NEW.original_admission_id IS DISTINCT FROM OLD.original_admission_id THEN
                v_flag := coalesce(
                    current_setting('scu.original_admission_correction', true), '');

                IF v_flag <> 'on' THEN
                    RAISE EXCEPTION
                        'the original admission pointer may only change through the correction workflow';
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM student_original_admission_history h
                     WHERE h.student_id = NEW.id
                       AND h.previous_admission_id = OLD.original_admission_id
                       AND h.new_admission_id = NEW.original_admission_id
                ) THEN
                    RAISE EXCEPTION
                        'pointer correction requires a history row in the same transaction';
                END IF;
            END IF;

            RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scu_period_dates_recheck()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            r record;
            v_earlier boolean;
        BEGIN
            IF NEW.start_date IS NOT DISTINCT FROM OLD.start_date
               AND NEW.end_date IS NOT DISTINCT FROM OLD.end_date THEN
                RETURN NEW;
            END IF;

            FOR r IN
                SELECT p.id,
                       p.authorized_by_id,
                       p.authorization_reason,
                       (NEW.start_date < ap.start_date) AS earlier
                  FROM academic_placements p
                  JOIN academic_admissions a ON a.id = p.admission_id
                  JOIN academic_periods ap ON ap.id = a.admission_intake_id
                 WHERE p.academic_period_id = NEW.id
                   AND p.ended_at IS NULL
            LOOP
                v_earlier := r.earlier;
                IF v_earlier AND (
                    r.authorized_by_id IS NULL
                    OR r.authorization_reason IS NULL
                    OR length(btrim(r.authorization_reason)) = 0
                ) THEN
                    RAISE EXCEPTION
                        'date correction would make placement % an unauthorized earlier-intake placement',
                        r.id;
                END IF;

                UPDATE academic_placements
                   SET is_earlier_intake_placement = v_earlier,
                       updated_at = now()
                 WHERE id = r.id;
            END LOOP;

            RETURN NEW;
        END $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION scu_admission_change_review_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.status IN ('APPROVED','REJECTED')
               AND NEW.status IS DISTINCT FROM OLD.status THEN
                RAISE EXCEPTION
                    'a decided admission change cannot be reviewed again';
            END IF;
            RETURN NEW;
        END $$;
        """
    )

    # --- Triggers ----------------------------------------------------------
    op.execute(
        """
        CREATE TRIGGER trg_admission_admitted_guard
        BEFORE INSERT OR UPDATE ON academic_admissions
        FOR EACH ROW EXECUTE FUNCTION scu_admission_admitted_guard();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admission_transition_guard
        AFTER INSERT OR UPDATE ON academic_admissions
        FOR EACH ROW EXECUTE FUNCTION scu_admission_transition_guard();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admission_immutable
        BEFORE UPDATE ON academic_admissions
        FOR EACH ROW EXECUTE FUNCTION scu_admission_immutable();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admission_change_review_guard
        BEFORE INSERT OR UPDATE ON academic_admission_changes
        FOR EACH ROW EXECUTE FUNCTION scu_admission_change_review_guard();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_period_dates_recheck
        BEFORE UPDATE ON academic_periods
        FOR EACH ROW EXECUTE FUNCTION scu_period_dates_recheck();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_original_admission_once
        BEFORE UPDATE OF original_admission_id ON students
        FOR EACH ROW EXECUTE FUNCTION scu_original_admission_once();
        """
    )

    for table in TRIGGER_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION scu_forbid_delete();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()

    # Refuse to discard records. The documented rollback is to revert the
    # release and keep the additive schema, not to downgrade a populated table.
    populated = []
    for table in NEW_TABLES:
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            populated.append(f"{table}={count}")
    if populated:
        raise RuntimeError(
            "Refusing to downgrade while Phase 0 tables contain rows: "
            + ", ".join(populated)
            + ". Revert the application release instead."
        )

    for table in TRIGGER_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete ON {table}")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_original_admission_once ON students"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_period_dates_recheck ON academic_periods"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admission_change_review_guard ON academic_admission_changes"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admission_immutable ON academic_admissions"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admission_transition_guard ON academic_admissions"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admission_admitted_guard ON academic_admissions"
    )

    for function in (
        "scu_admission_change_review_guard",
        "scu_period_dates_recheck",
        "scu_original_admission_once",
        "scu_forbid_delete",
        "scu_admission_immutable",
        "scu_admission_transition_guard",
        "scu_admission_admitted_guard",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")

    op.drop_index("uq_student_original_admission", table_name="students")
    op.drop_index("ix_students_original_admission", table_name="students")
    op.drop_constraint("fk_students_original_admission", "students", type_="foreignkey")
    op.drop_column("students", "original_admission_id")

    op.drop_table("student_original_admission_history")
    op.drop_table("academic_period_date_corrections")
    op.drop_table("academic_admission_verification_acts")
    op.drop_table("academic_admission_changes")
    op.drop_table("academic_placements")
    op.drop_table("academic_admission_status_history")
    op.drop_table("academic_admissions")

    op.drop_constraint(
        "uq_program_offering_period_id", "program_offerings", type_="unique"
    )
    op.drop_constraint(
        "ck_academic_period_date_order", "academic_periods", type_="check"
    )
