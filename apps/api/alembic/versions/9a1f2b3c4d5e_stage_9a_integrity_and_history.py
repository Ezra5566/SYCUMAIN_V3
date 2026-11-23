"""Stage 9A: data integrity and historical records.

Revision ID: 9a1f2b3c4d5e
Revises: c1d2e3f4a5b6
"""

from __future__ import annotations

import json
import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "9a1f2b3c4d5e"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None

PROFILE_FIELDS = (
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


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    bind = op.get_bind()

    # Fail closed rather than silently changing history if a database already
    # holds duplicate active assignments.
    duplicate_beds = bind.execute(
        sa.text(
            "SELECT bed_id, count(*) FROM housing_assignments "
            "WHERE status = 'ACTIVE' GROUP BY bed_id HAVING count(*) > 1"
        )
    ).fetchall()
    duplicate_students = bind.execute(
        sa.text(
            "SELECT student_id, count(*) FROM housing_assignments "
            "WHERE status = 'ACTIVE' GROUP BY student_id HAVING count(*) > 1"
        )
    ).fetchall()
    if duplicate_beds or duplicate_students:
        raise RuntimeError(
            "Cannot add active-assignment unique indexes: duplicate active "
            f"bed assignments={duplicate_beds}, student assignments={duplicate_students}. "
            "Resolve these records explicitly before upgrading."
        )

    # --- Housing responsibility -------------------------------------------------
    op.add_column("housing_assignments", sa.Column("created_by_id", _uuid(), nullable=True))
    op.add_column("housing_assignments", sa.Column("ended_by_id", _uuid(), nullable=True))
    op.add_column(
        "housing_assignments",
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_housing_created_by", "housing_assignments", "users", ["created_by_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_housing_ended_by", "housing_assignments", "users", ["ended_by_id"], ["id"]
    )
    op.create_index(
        "ix_housing_assignments_created_by_id",
        "housing_assignments",
        ["created_by_id"],
    )
    op.create_index(
        "ix_housing_assignments_ended_by_id",
        "housing_assignments",
        ["ended_by_id"],
    )
    op.create_index(
        "uq_housing_assignment_active_bed",
        "housing_assignments",
        ["bed_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "uq_housing_assignment_active_student",
        "housing_assignments",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    # --- Immigration history ----------------------------------------------------
    op.create_table(
        "immigration_profile_versions",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "immigration_profile_id",
            _uuid(),
            sa.ForeignKey("immigration_profiles.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("previous_data", sa.Text(), nullable=True),
        sa.Column("new_data", sa.Text(), nullable=False),
        sa.Column("changed_fields", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("changed_by_id", _uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("change_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "change_request_id",
            _uuid(),
            sa.ForeignKey("immigration_change_requests.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "immigration_profile_id",
            "version_number",
            name="uq_immigration_profile_version",
        ),
    )
    op.create_index(
        "ix_immigration_profile_versions_immigration_profile_id",
        "immigration_profile_versions",
        ["immigration_profile_id"],
    )
    op.create_index(
        "ix_immigration_profile_versions_changed_by_id",
        "immigration_profile_versions",
        ["changed_by_id"],
    )
    op.create_index(
        "ix_immigration_profile_versions_changed_at",
        "immigration_profile_versions",
        ["changed_at"],
    )
    op.create_index(
        "ix_immigration_profile_versions_change_request_id",
        "immigration_profile_versions",
        ["change_request_id"],
    )

    # Existing official records become version 1 so a later edit always has a
    # retrievable "before" state. This is a snapshot, not a data rewrite.
    profiles = bind.execute(
        sa.text(
            "SELECT id, "
            + ", ".join(PROFILE_FIELDS)
            + " FROM immigration_profiles"
        )
    ).mappings()
    insert_version = sa.text(
        "INSERT INTO immigration_profile_versions "
        "(id, immigration_profile_id, version_number, previous_data, new_data, "
        " changed_fields, changed_by_id, changed_at, change_reason, change_request_id) "
        "VALUES (:id, :profile_id, 1, NULL, :new_data, :changed_fields, NULL, now(), "
        "        :reason, NULL)"
    )
    for profile in profiles:
        data = {
            field: profile[field].isoformat()
            if isinstance(profile[field], date)
            else profile[field]
            for field in PROFILE_FIELDS
        }
        bind.execute(
            insert_version,
            {
                "id": uuid.uuid4(),
                "profile_id": profile["id"],
                "new_data": json.dumps(data),
                "changed_fields": json.dumps(sorted(PROFILE_FIELDS)),
                "reason": "Baseline snapshot before version tracking",
            },
        )

    # --- Academic history -------------------------------------------------------
    op.add_column(
        "timetable_entries",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "timetable_entries",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("timetable_entries", sa.Column("deleted_by_id", _uuid(), nullable=True))
    op.create_foreign_key(
        "fk_timetable_deleted_by",
        "timetable_entries",
        "users",
        ["deleted_by_id"],
        ["id"],
    )
    op.create_index(
        "ix_timetable_entries_is_deleted", "timetable_entries", ["is_deleted"]
    )

    op.create_table(
        "academic_change_history",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "class_section_id",
            _uuid(),
            sa.ForeignKey("class_sections.id"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("previous_data", sa.Text(), nullable=False),
        sa.Column("new_data", sa.Text(), nullable=False),
        sa.Column("changed_fields", sa.Text(), nullable=False),
        sa.Column("changed_by_id", _uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reason", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_academic_change_history_class_section_id",
        "academic_change_history",
        ["class_section_id"],
    )
    op.create_index(
        "ix_academic_change_history_entity_type",
        "academic_change_history",
        ["entity_type"],
    )
    op.create_index(
        "ix_academic_change_history_entity_id",
        "academic_change_history",
        ["entity_id"],
    )
    op.create_index(
        "ix_academic_change_history_changed_at",
        "academic_change_history",
        ["changed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_academic_change_history_changed_at", table_name="academic_change_history"
    )
    op.drop_index(
        "ix_academic_change_history_entity_id", table_name="academic_change_history"
    )
    op.drop_index(
        "ix_academic_change_history_entity_type", table_name="academic_change_history"
    )
    op.drop_index(
        "ix_academic_change_history_class_section_id",
        table_name="academic_change_history",
    )
    op.drop_table("academic_change_history")

    op.drop_index("ix_timetable_entries_is_deleted", table_name="timetable_entries")
    op.drop_constraint(
        "fk_timetable_deleted_by", "timetable_entries", type_="foreignkey"
    )
    op.drop_column("timetable_entries", "deleted_by_id")
    op.drop_column("timetable_entries", "deleted_at")
    op.drop_column("timetable_entries", "is_deleted")

    op.drop_index(
        "ix_immigration_profile_versions_change_request_id",
        table_name="immigration_profile_versions",
    )
    op.drop_index(
        "ix_immigration_profile_versions_changed_at",
        table_name="immigration_profile_versions",
    )
    op.drop_index(
        "ix_immigration_profile_versions_changed_by_id",
        table_name="immigration_profile_versions",
    )
    op.drop_index(
        "ix_immigration_profile_versions_immigration_profile_id",
        table_name="immigration_profile_versions",
    )
    op.drop_table("immigration_profile_versions")

    op.drop_index(
        "uq_housing_assignment_active_student", table_name="housing_assignments"
    )
    op.drop_index("uq_housing_assignment_active_bed", table_name="housing_assignments")
    op.drop_index(
        "ix_housing_assignments_ended_by_id", table_name="housing_assignments"
    )
    op.drop_index(
        "ix_housing_assignments_created_by_id", table_name="housing_assignments"
    )
    op.drop_constraint("fk_housing_ended_by", "housing_assignments", type_="foreignkey")
    op.drop_constraint(
        "fk_housing_created_by", "housing_assignments", type_="foreignkey"
    )
    op.drop_column("housing_assignments", "ended_at")
    op.drop_column("housing_assignments", "ended_by_id")
    op.drop_column("housing_assignments", "created_by_id")
