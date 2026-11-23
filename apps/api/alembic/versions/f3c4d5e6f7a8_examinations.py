"""Examination management: scheduled examinations, participating sections, results.

Revision ID: f3c4d5e6f7a8
Revises: f2b3c4d5e6f7

Three tables:

* ``examinations`` — the event: subject, intake, optional programme offering,
  date, start/end time, location, instructions, score ceiling, cancellation
  state and the publication gate.
* ``examination_sections`` — which teaching sections sit it. One examination
  serves several sections; the alternative (one examination per section) would
  turn a single institutional event into duplicated schedules, rooms and
  publication dates that immediately drift apart.
* ``examination_results`` — the per-student record, shaped like ``grades`` and
  superseded rather than overwritten on correction.

Integrity is enforced in the database, not only in the service:

* ``ck_examination_time_order`` refuses an exam that ends before it starts.
* ``uq_examination_result_current`` makes a second live result for the same
  student and examination impossible under concurrency; superseded rows are
  outside the index so the correction chain survives.
* ``ck_examination_publication`` refuses a publication timestamp without a
  publisher, so "published" can never mean "someone set a flag".

Nothing is backfilled, and no existing assessment, grade, section or enrollment
row is read or rewritten. Existing ``assessments`` remain the section-level
grade components they always were.

Downgrade refuses while any examination exists: schedules and results are
institutional records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "f3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "f2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "examinations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("examination_type", sa.String(length=20), nullable=False),
        sa.Column("course_id", _uuid(), nullable=False),
        sa.Column("academic_period_id", _uuid(), nullable=False),
        sa.Column("program_offering_id", _uuid(), nullable=True),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("max_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="SCHEDULED"
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", _uuid(), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=500), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_id", _uuid(), nullable=True),
        sa.Column("created_by_id", _uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["course_id"], ["courses.id"],
            name="fk_examination_course", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["academic_period_id"], ["academic_periods.id"],
            name="fk_examination_period", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["program_offering_id"], ["program_offerings.id"],
            name="fk_examination_offering", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_id"], ["users.id"],
            name="fk_examination_published_by", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by_id"], ["users.id"],
            name="fk_examination_cancelled_by", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            name="fk_examination_created_by", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("end_time > start_time", name="ck_examination_time_order"),
        sa.CheckConstraint(
            "max_score IS NULL OR max_score > 0", name="ck_examination_max_score"
        ),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'CANCELLED')", name="ck_examination_status"
        ),
        sa.CheckConstraint(
            "(status = 'CANCELLED' AND cancelled_at IS NOT NULL "
            "AND cancelled_by_id IS NOT NULL AND cancellation_reason IS NOT NULL) "
            "OR (status <> 'CANCELLED' AND cancelled_at IS NULL "
            "AND cancelled_by_id IS NULL AND cancellation_reason IS NULL)",
            name="ck_examination_cancellation",
        ),
        sa.CheckConstraint(
            "(published_at IS NULL AND published_by_id IS NULL) "
            "OR (published_at IS NOT NULL AND published_by_id IS NOT NULL)",
            name="ck_examination_publication",
        ),
    )
    op.create_index("ix_examinations_course_id", "examinations", ["course_id"])
    op.create_index(
        "ix_examinations_academic_period_id", "examinations", ["academic_period_id"]
    )
    op.create_index(
        "ix_examinations_program_offering_id", "examinations", ["program_offering_id"]
    )
    op.create_index("ix_examinations_exam_date", "examinations", ["exam_date"])
    op.create_index(
        "ix_examinations_period_date", "examinations", ["academic_period_id", "exam_date"]
    )

    op.create_table(
        "examination_sections",
        sa.Column("examination_id", _uuid(), nullable=False),
        sa.Column("class_section_id", _uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["examination_id"], ["examinations.id"],
            name="fk_examination_section_exam", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["class_section_id"], ["class_sections.id"],
            name="fk_examination_section_class", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("examination_id", "class_section_id"),
        sa.UniqueConstraint(
            "examination_id", "class_section_id", name="uq_examination_section"
        ),
    )
    op.create_index(
        "ix_examination_sections_class_section_id",
        "examination_sections",
        ["class_section_id"],
    )

    op.create_table(
        "examination_results",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("examination_id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("letter_grade", sa.String(length=5), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("recorded_by_id", _uuid(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("supersedes_id", _uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correction_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["examination_id"], ["examinations.id"],
            name="fk_examination_result_exam", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"],
            name="fk_examination_result_student", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"], ["users.id"],
            name="fk_examination_result_recorded_by", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["examination_results.id"],
            name="fk_examination_result_supersedes", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("score >= 0", name="ck_examination_result_score"),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_examination_result_supersedes",
        ),
    )
    op.create_index(
        "ix_examination_results_examination_id", "examination_results", ["examination_id"]
    )
    op.create_index(
        "ix_examination_results_student_id", "examination_results", ["student_id"]
    )
    op.create_index(
        "uq_examination_result_current",
        "examination_results",
        ["examination_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT count(*) FROM examinations")).scalar_one()
    if rows:
        raise RuntimeError(
            "Refusing to downgrade while examinations exist "
            f"({rows} examination(s)): schedules, participants and results are "
            "institutional records. Revert the application release instead."
        )

    op.drop_index("uq_examination_result_current", table_name="examination_results")
    op.drop_index(
        "ix_examination_results_student_id", table_name="examination_results"
    )
    op.drop_index(
        "ix_examination_results_examination_id", table_name="examination_results"
    )
    op.drop_table("examination_results")

    op.drop_index(
        "ix_examination_sections_class_section_id", table_name="examination_sections"
    )
    op.drop_table("examination_sections")

    op.drop_index("ix_examinations_period_date", table_name="examinations")
    op.drop_index("ix_examinations_exam_date", table_name="examinations")
    op.drop_index("ix_examinations_program_offering_id", table_name="examinations")
    op.drop_index("ix_examinations_academic_period_id", table_name="examinations")
    op.drop_index("ix_examinations_course_id", table_name="examinations")
    op.drop_table("examinations")
