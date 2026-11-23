"""Attendance commencement records (Phase 2).

Revision ID: c4e6f8a0b2d3
Revises: b3d5e7f9a1c2

Additive only. One new table, plus a delete guard reused from the admission
schema. No existing admission, calendar or attendance row is read, changed or
backfilled: existing episodes deliberately receive no commencement record here,
because a commencement is an institutional approval, not a data migration.

Downgrade refuses while the table holds rows: a commencement is a decision with
an actor and a date, and the documented rollback is to revert the release rather
than discard it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "c4e6f8a0b2d3"
down_revision: str | Sequence[str] | None = "b3d5e7f9a1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "attendance_commencements"


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("admission_id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("commencement_date", sa.Date(), nullable=False),
        sa.Column("commencement_type", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("suggested_date", sa.Date(), nullable=False),
        sa.Column("supersedes_id", _uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", _uuid(), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["admission_id"],
            ["academic_admissions.id"],
            name="fk_commencement_admission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_commencement_student",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            [f"{TABLE}.id"],
            name="fk_commencement_supersedes",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name="fk_commencement_approved_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "commencement_type IN ('SCHEDULED','LATE_JOIN','MANUAL')",
            name="ck_commencement_type",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name="ck_commencement_reason"
        ),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_commencement_supersedes",
        ),
    )

    op.create_index(
        "ix_attendance_commencements_admission_id", TABLE, ["admission_id"]
    )
    op.create_index("ix_attendance_commencements_student_id", TABLE, ["student_id"])
    # One current commencement per episode; superseded rows fall out of the
    # index, which is what allows a correction to coexist with its predecessor.
    op.create_index(
        "uq_attendance_commencement_current",
        TABLE,
        ["admission_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    # A commencement is a decision with an actor; deleting one would erase who
    # made it. The guard function is created by the admission Phase 0 revision.
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
            f"Refusing to downgrade while {TABLE} holds {stored} row(s): a "
            "commencement records who approved it and when. Revert the "
            "application release instead."
        )

    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_delete ON {TABLE}")
    op.drop_index("uq_attendance_commencement_current", table_name=TABLE)
    op.drop_index("ix_attendance_commencements_student_id", table_name=TABLE)
    op.drop_index("ix_attendance_commencements_admission_id", table_name=TABLE)
    op.drop_table(TABLE)
