"""Add the university working-day calendar (Phase 1).

Revision ID: b3d5e7f9a1c2
Revises: f8a1b2c3d4e5

Additive only: one new table for explicitly declared calendar exceptions. No
existing row is read, rewritten or backfilled, no attendance session is created
and no official holiday is invented here.

Only exceptions are stored. Ordinary working days follow the Monday–Friday rule
and have no row, so the calendar never contains generated future dates.

Downgrade refuses while the table holds rows: a declared institutional calendar
is a record, and the documented rollback is to revert the release rather than
discard it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "b3d5e7f9a1c2"
down_revision: str | Sequence[str] | None = "f8a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "university_calendar_days"


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("day_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "is_void",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_id", _uuid(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", _uuid(), nullable=False),
        sa.Column("updated_by_id", _uuid(), nullable=True),
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
            ["created_by_id"], ["users.id"], name="fk_calendar_day_created_by"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["users.id"], name="fk_calendar_day_updated_by"
        ),
        sa.ForeignKeyConstraint(
            ["voided_by_id"], ["users.id"], name="fk_calendar_day_voided_by"
        ),
        sa.PrimaryKeyConstraint("id"),
        # WORKING and WEEKEND are derived from the weekday and are not
        # declarable: storing them would duplicate the rule.
        sa.CheckConstraint(
            "day_type IN ('HOLIDAY','CLOSURE','EXCEPTIONAL_WORKING')",
            name="ck_calendar_day_type",
        ),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_calendar_day_title"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_calendar_day_reason"),
        sa.CheckConstraint(
            "(is_void AND voided_at IS NOT NULL AND voided_by_id IS NOT NULL "
            "AND length(btrim(coalesce(void_reason, ''))) > 0) "
            "OR (NOT is_void AND voided_at IS NULL AND voided_by_id IS NULL "
            "AND void_reason IS NULL)",
            name="ck_calendar_day_void_fields",
        ),
    )

    op.create_index(
        "ix_university_calendar_days_calendar_date", TABLE, ["calendar_date"]
    )
    op.create_index("ix_university_calendar_days_is_void", TABLE, ["is_void"])
    # One live declaration per date; a voided row no longer reserves the date,
    # so a corrected declaration can be issued for the same day.
    op.create_index(
        "uq_university_calendar_day_date",
        TABLE,
        ["calendar_date"],
        unique=True,
        postgresql_where=sa.text("is_void = false"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    stored = bind.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    if stored:
        raise RuntimeError(
            f"Refusing to downgrade while {TABLE} holds {stored} row(s): a "
            "declared institutional calendar is a record. Revert the "
            "application release instead."
        )

    op.drop_index("uq_university_calendar_day_date", table_name=TABLE)
    op.drop_index("ix_university_calendar_days_is_void", table_name=TABLE)
    op.drop_index("ix_university_calendar_days_calendar_date", table_name=TABLE)
    op.drop_table(TABLE)
