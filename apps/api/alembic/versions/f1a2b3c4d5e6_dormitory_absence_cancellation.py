"""Dormitory attendance: explicit absence cancellation.

Revision ID: f1a2b3c4d5e6
Revises: e5b2c8d4f7a1

A correction says "this record was wrong". A cancellation says "this absence
should not count at all". They are different institutional acts, so cancellation
gets its own columns rather than being expressed as a correction to zero points:

* the row is never deleted and never rewritten — the previous points, date and
  reason stay readable;
* who cancelled it, when, and why are stored together, and the check constraint
  refuses a half-written cancellation;
* a record is superseded *or* cancelled, never both;
* the partial unique index now ignores cancelled rows as well as superseded
  ones, so cancelling an absence frees the date for a correct record while the
  cancelled row remains in the history.

No existing row is modified. Existing absences are neither cancelled nor
superseded by this migration.

Downgrade refuses while any cancelled absence exists: dropping the columns would
erase the only evidence of who cancelled what and why.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e5b2c8d4f7a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "dormitory_absences"
INDEX = "uq_dormitory_absence_current"

ACTIVE_PREDICATE = "superseded_at IS NULL AND cancelled_at IS NULL"
PREVIOUS_PREDICATE = "superseded_at IS NULL"


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    op.add_column(TABLE, sa.Column("cancelled_by_id", _uuid()))
    op.add_column(TABLE, sa.Column("cancellation_reason", sa.Text()))

    op.create_foreign_key(
        "fk_dormitory_absence_cancelled_by",
        TABLE,
        "users",
        ["cancelled_by_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_check_constraint(
        "ck_dormitory_absence_cancellation",
        TABLE,
        "(cancelled_at IS NULL AND cancelled_by_id IS NULL "
        "AND cancellation_reason IS NULL) "
        "OR (cancelled_at IS NOT NULL AND cancelled_by_id IS NOT NULL "
        "AND length(btrim(cancellation_reason)) >= 10)",
    )
    op.create_check_constraint(
        "ck_dormitory_absence_terminal_state",
        TABLE,
        "superseded_at IS NULL OR cancelled_at IS NULL",
    )

    op.drop_index(INDEX, table_name=TABLE)
    op.create_index(
        INDEX,
        TABLE,
        ["student_id", "housing_assignment_id", "absence_date"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_PREDICATE),
    )


def downgrade() -> None:
    bind = op.get_bind()
    cancelled = bind.execute(
        sa.text(f"SELECT count(*) FROM {TABLE} WHERE cancelled_at IS NOT NULL")
    ).scalar_one()
    if cancelled:
        raise RuntimeError(
            "Refusing to downgrade while cancelled dormitory absences exist "
            f"({cancelled} row(s)): dropping these columns would erase who "
            "cancelled them and why. Revert the application release instead."
        )

    op.drop_index(INDEX, table_name=TABLE)
    op.create_index(
        INDEX,
        TABLE,
        ["student_id", "housing_assignment_id", "absence_date"],
        unique=True,
        postgresql_where=sa.text(PREVIOUS_PREDICATE),
    )

    op.drop_constraint(
        "ck_dormitory_absence_terminal_state", TABLE, type_="check"
    )
    op.drop_constraint("ck_dormitory_absence_cancellation", TABLE, type_="check")
    op.drop_constraint(
        "fk_dormitory_absence_cancelled_by", TABLE, type_="foreignkey"
    )

    op.drop_column(TABLE, "cancellation_reason")
    op.drop_column(TABLE, "cancelled_by_id")
    op.drop_column(TABLE, "cancelled_at")
