"""Student-level attendance absences (Phase 3, corrected model).

Revision ID: e7b9c1d3f5a0
Revises: c4e6f8a0b2d3

Additive only: one table for absence records. No existing row is read, rewritten
or backfilled, and no attendance is generated: a working day without an absence
is a day the student attended.

The earlier class-session draft (``d5f7a9b1c3e8``) was never applied to a
persistent database and is not part of this chain, so there is nothing to convert
or delete here. The legacy ``attendance_records`` table is untouched.

Downgrade refuses while the table holds rows: an absence records who recorded it
and why, and the documented rollback is to revert the release rather than discard
an academic record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "e7b9c1d3f5a0"
down_revision: str | Sequence[str] | None = "c4e6f8a0b2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "attendance_absences"


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("admission_id", _uuid(), nullable=False),
        sa.Column("absence_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recorded_by_id", _uuid(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("supersedes_id", _uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_absence_student",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["admission_id"],
            ["academic_admissions.id"],
            name="fk_absence_admission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            [f"{TABLE}.id"],
            name="fk_absence_supersedes",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"],
            ["users.id"],
            name="fk_absence_recorded_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_absence_reason"),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_absence_supersedes",
        ),
    )

    op.create_index("ix_attendance_absences_student_id", TABLE, ["student_id"])
    op.create_index("ix_attendance_absences_admission_id", TABLE, ["admission_id"])
    op.create_index("ix_attendance_absences_date", TABLE, ["absence_date"])
    # One current absence per student per episode per date; superseded rows fall
    # out of the index, which is what allows a correction to sit beside the
    # record it replaced.
    op.create_index(
        "uq_attendance_absence_current",
        TABLE,
        ["student_id", "admission_id", "absence_date"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    # An absence records who recorded it and why; deleting one would erase that.
    op.execute(
        f"""
        CREATE TRIGGER trg_{TABLE}_no_delete
        BEFORE DELETE ON {TABLE}
        FOR EACH ROW EXECUTE FUNCTION scu_forbid_delete();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    stored = bind.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    if stored:
        raise RuntimeError(
            f"Refusing to downgrade while {TABLE} holds {stored} row(s): an "
            "absence records who recorded it and why. Revert the application "
            "release instead."
        )

    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_delete ON {TABLE}")
    op.drop_index("uq_attendance_absence_current", table_name=TABLE)
    op.drop_index("ix_attendance_absences_date", table_name=TABLE)
    op.drop_index("ix_attendance_absences_admission_id", table_name=TABLE)
    op.drop_index("ix_attendance_absences_student_id", table_name=TABLE)
    op.drop_table(TABLE)
