"""SCU timetable reference schema and staged import support.

Revision ID: a7b8c9d0e1f2
Revises: 9a1f2b3c4d5e

This revision is additive to existing academic data. It deliberately does not
create periods, courses, sections or timetable entries. Those are created only
by the staged importer after its dry-run checks and explicit period mapping.
"""

from __future__ import annotations

import json
import uuid
from datetime import time
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "9a1f2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # --- Format references -------------------------------------------------
    op.create_table(
        "timetable_formats",
        sa.Column("code", sa.String(length=20), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_description", sa.Text(), nullable=True),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "timetable_slots",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "format_code",
            sa.String(length=20),
            sa.ForeignKey("timetable_formats.code"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=12), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("format_code", "label", name="uq_timetable_slot_format_label"),
    )
    op.create_index(
        "ix_timetable_slots_format_code", "timetable_slots", ["format_code"]
    )

    # --- Import staging ----------------------------------------------------
    op.create_table(
        "academic_import_batches",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRY_RUN"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("created_by_id", _uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_academic_import_batches_source_sha256",
        "academic_import_batches",
        ["source_sha256"],
    )

    op.create_table(
        "academic_import_rows",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "batch_id",
            _uuid(),
            sa.ForeignKey("academic_import_batches.id"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("source_key", sa.String(length=160), nullable=False),
        sa.Column("source_locator", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("previous_data", sa.JSON(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False, server_default="CREATE"),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("target_table", sa.String(length=60), nullable=True),
        sa.Column("target_id", _uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "batch_id", "entity_type", "source_key", name="uq_academic_import_row_source"
        ),
    )
    op.create_index(
        "ix_academic_import_rows_batch_id", "academic_import_rows", ["batch_id"]
    )
    op.create_index(
        "ix_academic_import_rows_entity_type", "academic_import_rows", ["entity_type"]
    )

    # --- Period-specific offerings and shared delivery ---------------------
    op.create_table(
        "program_offerings",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "academic_period_id",
            _uuid(),
            sa.ForeignKey("academic_periods.id"),
            nullable=False,
        ),
        sa.Column("program_id", _uuid(), sa.ForeignKey("programs.id"), nullable=True),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("source_key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_zh", sa.String(length=200), nullable=True),
        sa.Column(
            "import_batch_id",
            _uuid(),
            sa.ForeignKey("academic_import_batches.id"),
            nullable=True,
        ),
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
        sa.UniqueConstraint(
            "academic_period_id", "source_id", name="uq_program_offering_period_source"
        ),
    )
    op.create_index(
        "ix_program_offerings_academic_period_id",
        "program_offerings",
        ["academic_period_id"],
    )
    op.create_index(
        "ix_program_offerings_program_id", "program_offerings", ["program_id"]
    )
    op.create_index(
        "ix_program_offerings_source_key",
        "program_offerings",
        ["source_key"],
        unique=True,
    )
    op.create_index(
        "ix_program_offerings_import_batch_id",
        "program_offerings",
        ["import_batch_id"],
    )

    op.create_table(
        "class_section_program_offerings",
        sa.Column(
            "class_section_id",
            _uuid(),
            sa.ForeignKey("class_sections.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "program_offering_id",
            _uuid(),
            sa.ForeignKey("program_offerings.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_class_section_program_offering_offering",
        "class_section_program_offerings",
        ["program_offering_id", "class_section_id"],
    )

    # --- Existing tables: provenance and unknown-value columns -------------
    op.add_column("academic_periods", sa.Column("name_zh", sa.String(length=200)))
    op.add_column("academic_periods", sa.Column("source_key", sa.String(length=160)))
    op.add_column(
        "academic_periods", sa.Column("source_timetable_format", sa.String(length=20))
    )
    op.add_column(
        "academic_periods", sa.Column("timetable_format_code", sa.String(length=20))
    )
    op.add_column("academic_periods", sa.Column("timetable_format_note", sa.Text()))
    op.add_column("academic_periods", sa.Column("import_batch_id", _uuid()))
    op.create_foreign_key(
        "fk_academic_periods_timetable_format",
        "academic_periods",
        "timetable_formats",
        ["timetable_format_code"],
        ["code"],
    )
    op.create_foreign_key(
        "fk_academic_periods_import_batch",
        "academic_periods",
        "academic_import_batches",
        ["import_batch_id"],
        ["id"],
    )
    op.create_index(
        "ix_academic_periods_source_key",
        "academic_periods",
        ["source_key"],
        unique=True,
    )
    op.create_index(
        "ix_academic_periods_import_batch_id",
        "academic_periods",
        ["import_batch_id"],
    )

    op.add_column("courses", sa.Column("name_zh", sa.String(length=200)))
    op.add_column("courses", sa.Column("source_key", sa.String(length=160)))
    op.add_column("courses", sa.Column("import_batch_id", _uuid()))
    op.create_foreign_key(
        "fk_courses_import_batch",
        "courses",
        "academic_import_batches",
        ["import_batch_id"],
        ["id"],
    )
    op.create_index("ix_courses_source_key", "courses", ["source_key"], unique=True)
    op.create_index("ix_courses_import_batch_id", "courses", ["import_batch_id"])
    op.alter_column("courses", "code", existing_type=sa.String(length=20), nullable=True)
    op.alter_column("courses", "credits", existing_type=sa.Integer(), nullable=True)

    op.add_column("classrooms", sa.Column("campus", sa.String(length=100)))
    op.add_column("classrooms", sa.Column("source_key", sa.String(length=160)))
    op.add_column("classrooms", sa.Column("import_batch_id", _uuid()))
    op.create_foreign_key(
        "fk_classrooms_import_batch",
        "classrooms",
        "academic_import_batches",
        ["import_batch_id"],
        ["id"],
    )
    op.create_index(
        "ix_classrooms_source_key", "classrooms", ["source_key"], unique=True
    )
    op.create_index("ix_classrooms_import_batch_id", "classrooms", ["import_batch_id"])
    op.alter_column(
        "classrooms", "capacity", existing_type=sa.Integer(), nullable=True
    )

    op.add_column("class_sections", sa.Column("source_label", sa.String(length=300)))
    op.add_column("class_sections", sa.Column("source_key", sa.String(length=160)))
    op.add_column("class_sections", sa.Column("import_batch_id", _uuid()))
    op.create_foreign_key(
        "fk_class_sections_import_batch",
        "class_sections",
        "academic_import_batches",
        ["import_batch_id"],
        ["id"],
    )
    op.create_index(
        "ix_class_sections_source_key", "class_sections", ["source_key"], unique=True
    )
    op.create_index(
        "ix_class_sections_import_batch_id", "class_sections", ["import_batch_id"]
    )
    op.alter_column(
        "class_sections",
        "section_code",
        existing_type=sa.String(length=20),
        nullable=True,
    )
    op.alter_column(
        "class_sections", "capacity", existing_type=sa.Integer(), nullable=True
    )

    op.add_column("timetable_entries", sa.Column("slot_label", sa.String(length=12)))
    op.add_column("timetable_entries", sa.Column("source_key", sa.String(length=160)))
    op.add_column("timetable_entries", sa.Column("import_batch_id", _uuid()))
    op.create_foreign_key(
        "fk_timetable_entries_import_batch",
        "timetable_entries",
        "academic_import_batches",
        ["import_batch_id"],
        ["id"],
    )
    op.create_index(
        "ix_timetable_entries_source_key",
        "timetable_entries",
        ["source_key"],
        unique=True,
    )
    op.create_index(
        "ix_timetable_entries_import_batch_id",
        "timetable_entries",
        ["import_batch_id"],
    )
    op.create_index(
        "ix_timetable_entries_period_lookup",
        "timetable_entries",
        ["class_section_id", "is_deleted"],
    )
    op.create_index(
        "uq_timetable_live_slot",
        "timetable_entries",
        ["class_section_id", "day_of_week", "start_time", "end_time", "classroom_id"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )

    # --- Reference seed ----------------------------------------------------
    formats = sa.table(
        "timetable_formats",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("source_description", sa.Text),
        sa.column("definition_json", sa.JSON),
    )
    op.bulk_insert(
        formats,
        [
            {
                "code": "standard8",
                "name": "Standard 8-period day",
                "description": "Eight individual periods with break intervals.",
                "source_description": "Used by 2025 Autumn and 2026 Spring",
                "definition_json": {
                    "slots": [
                        {"session": 1, "time": "8:20-9:05", "period": "morning"},
                        {"session": 2, "time": "9:15-10:00", "period": "morning"},
                        {"session": 3, "time": "10:20-11:05", "period": "morning"},
                        {"session": 4, "time": "11:15-12:00", "period": "morning"},
                        {"session": 5, "time": "13:30-14:15", "period": "afternoon"},
                        {"session": 6, "time": "14:25-15:10", "period": "afternoon"},
                        {"session": 7, "time": "15:20-16:05", "period": "afternoon"},
                        {"session": 8, "time": "16:15-17:00", "period": "afternoon"},
                    ]
                },
            },
            {
                "code": "block4",
                "name": "Four-block day",
                "description": "Four two-period blocks.",
                "source_description": "Used by 2026 Autumn",
                "definition_json": {
                    "slots": [
                        {"session": "1-2", "time": "8:20-10:00", "period": "morning"},
                        {"session": "3-4", "time": "10:20-12:00", "period": "morning"},
                        {"session": "5-6", "time": "13:30-15:10", "period": "afternoon"},
                        {"session": "7-8", "time": "15:20-17:00", "period": "afternoon"},
                    ]
                },
            },
        ],
    )

    slots = sa.table(
        "timetable_slots",
        sa.column("id", _uuid()),
        sa.column("format_code", sa.String),
        sa.column("label", sa.String),
        sa.column("start_time", sa.Time),
        sa.column("end_time", sa.Time),
        sa.column("sort_order", sa.Integer),
    )
    slot_rows = [
        ("standard8", "1-2", time(8, 20), time(10, 0)),
        ("standard8", "1-4", time(8, 20), time(12, 0)),
        ("standard8", "3-4", time(10, 20), time(12, 0)),
        ("standard8", "5-6", time(13, 30), time(15, 10)),
        ("standard8", "5-8", time(13, 30), time(17, 0)),
        ("standard8", "7", time(15, 20), time(16, 5)),
        ("block4", "1-2", time(8, 20), time(10, 0)),
        ("block4", "1-4", time(8, 20), time(12, 0)),
        ("block4", "5-6", time(13, 30), time(15, 10)),
        ("block4", "5-8", time(13, 30), time(17, 0)),
        ("block4", "7-8", time(15, 20), time(17, 0)),
    ]
    op.bulk_insert(
        slots,
        [
            {
                "id": uuid.uuid4(),
                "format_code": format_code,
                "label": label,
                "start_time": start,
                "end_time": end,
                "sort_order": index,
            }
            for index, (format_code, label, start, end) in enumerate(slot_rows)
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    applied = bind.execute(
        sa.text(
            "SELECT count(*) FROM academic_import_batches WHERE status = 'APPLIED'"
        )
    ).scalar_one()
    if applied:
        raise RuntimeError(
            "Refusing to downgrade while an applied academic import batch exists. "
            "Roll it back explicitly first."
        )

    op.drop_index("uq_timetable_live_slot", table_name="timetable_entries")
    op.drop_index("ix_timetable_entries_period_lookup", table_name="timetable_entries")
    op.drop_index("ix_timetable_entries_import_batch_id", table_name="timetable_entries")
    op.drop_index("ix_timetable_entries_source_key", table_name="timetable_entries")
    op.drop_constraint(
        "fk_timetable_entries_import_batch", "timetable_entries", type_="foreignkey"
    )
    op.drop_column("timetable_entries", "import_batch_id")
    op.drop_column("timetable_entries", "source_key")
    op.drop_column("timetable_entries", "slot_label")

    op.drop_index("ix_class_sections_import_batch_id", table_name="class_sections")
    op.drop_index("ix_class_sections_source_key", table_name="class_sections")
    op.drop_constraint(
        "fk_class_sections_import_batch", "class_sections", type_="foreignkey"
    )
    op.drop_column("class_sections", "import_batch_id")
    op.drop_column("class_sections", "source_key")
    op.drop_column("class_sections", "source_label")

    op.drop_index("ix_classrooms_import_batch_id", table_name="classrooms")
    op.drop_index("ix_classrooms_source_key", table_name="classrooms")
    op.drop_constraint("fk_classrooms_import_batch", "classrooms", type_="foreignkey")
    op.drop_column("classrooms", "import_batch_id")
    op.drop_column("classrooms", "source_key")
    op.drop_column("classrooms", "campus")

    op.drop_index("ix_courses_import_batch_id", table_name="courses")
    op.drop_index("ix_courses_source_key", table_name="courses")
    op.drop_constraint("fk_courses_import_batch", "courses", type_="foreignkey")
    op.drop_column("courses", "import_batch_id")
    op.drop_column("courses", "source_key")
    op.drop_column("courses", "name_zh")

    op.drop_index("ix_academic_periods_import_batch_id", table_name="academic_periods")
    op.drop_index("ix_academic_periods_source_key", table_name="academic_periods")
    op.drop_constraint(
        "fk_academic_periods_import_batch", "academic_periods", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_academic_periods_timetable_format", "academic_periods", type_="foreignkey"
    )
    op.drop_column("academic_periods", "import_batch_id")
    op.drop_column("academic_periods", "timetable_format_note")
    op.drop_column("academic_periods", "timetable_format_code")
    op.drop_column("academic_periods", "source_timetable_format")
    op.drop_column("academic_periods", "source_key")
    op.drop_column("academic_periods", "name_zh")

    op.drop_table("class_section_program_offerings")
    op.drop_index("ix_program_offerings_import_batch_id", table_name="program_offerings")
    op.drop_index("ix_program_offerings_source_key", table_name="program_offerings")
    op.drop_index("ix_program_offerings_program_id", table_name="program_offerings")
    op.drop_index(
        "ix_program_offerings_academic_period_id", table_name="program_offerings"
    )
    op.drop_table("program_offerings")
    op.drop_table("academic_import_rows")
    op.drop_table("academic_import_batches")
    op.drop_table("timetable_slots")
    op.drop_table("timetable_formats")
