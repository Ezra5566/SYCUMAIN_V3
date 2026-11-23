"""Audited absence cancellation (Phase 3 integrity corrections).

Revision ID: f9d2e4a6b8c1
Revises: e7b9c1d3f5a0

Cancellation is not deletion: the row keeps its date, reason, recorder and
timestamp, gains who cancelled it, when, and why, and stops counting toward
attendance. No row is removed here or by the application.

The partial unique index changes shape. It previously admitted one *current*
absence per student/episode/date; a cancelled record is still current, so it must
also leave the index or the same date could never be recorded again after a
mistake was cancelled. The index now covers active rows only.

Downgrade refuses while the table holds rows, for the same reason the previous
revision does: an absence records who recorded it and why, and the documented
rollback is to revert the release rather than discard an academic record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "f9d2e4a6b8c1"
down_revision: str | Sequence[str] | None = "e7b9c1d3f5a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "attendance_absences"
INDEX = "uq_attendance_absence_current"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    op.add_column(TABLE, sa.Column("cancelled_by_id", sa.UUID(as_uuid=True)))
    op.add_column(TABLE, sa.Column("cancellation_reason", sa.Text()))
    op.create_foreign_key(
        "fk_absence_cancelled_by",
        TABLE,
        "users",
        ["cancelled_by_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_absence_cancellation",
        TABLE,
        "(cancelled_at IS NULL AND cancelled_by_id IS NULL AND cancellation_reason IS NULL)"
        " OR "
        "(cancelled_at IS NOT NULL AND cancelled_by_id IS NOT NULL"
        " AND length(btrim(cancellation_reason)) > 0)",
    )

    # Rebuild the index with the new predicate. Dropping and recreating it in the
    # same transaction means no window exists in which two active absences for
    # one date could be inserted.
    op.drop_index(INDEX, table_name=TABLE)
    op.create_index(
        INDEX,
        TABLE,
        ["student_id", "admission_id", "absence_date"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL AND cancelled_at IS NULL"),
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

    # The old predicate covers every row, which is only safe on an empty table.
    op.drop_index(INDEX, table_name=TABLE)
    op.create_index(
        INDEX,
        TABLE,
        ["student_id", "admission_id", "absence_date"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.drop_constraint("ck_absence_cancellation", TABLE, type_="check")
    op.drop_constraint("fk_absence_cancelled_by", TABLE, type_="foreignkey")
    op.drop_column(TABLE, "cancellation_reason")
    op.drop_column(TABLE, "cancelled_by_id")
    op.drop_column(TABLE, "cancelled_at")
