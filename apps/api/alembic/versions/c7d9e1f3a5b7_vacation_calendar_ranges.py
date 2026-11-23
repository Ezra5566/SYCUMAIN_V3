"""Institution-entered vacation ranges and the VACATION day type.

Revision ID: c7d9e1f3a5b7
Revises: f9d2e4a6b8c1

A vacation is a range, not a loose declaration: the parent row records who
entered it, its bounds and why, and each date is materialised as a ``VACATION``
calendar day pointing at it. That is what makes "cancel this vacation" one
transactional decision.

No vacation date is invented or backfilled here. No existing calendar row is
read or rewritten; the only change to ``university_calendar_days`` is the widened
day-type constraint plus two nullable columns.

``detached_from_range_at`` marks a date the institution corrected individually
after the range created it. Range cancellation and shortening skip detached
dates, so an explicit correction is never undone automatically.

Downgrade refuses while any vacation range or ``VACATION`` day exists: both are
institutional records, and the documented rollback is to revert the release
rather than discard them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "c7d9e1f3a5b7"
down_revision: str | Sequence[str] | None = "f9d2e4a6b8c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RANGES = "calendar_vacation_ranges"
DAYS = "university_calendar_days"

OLD_TYPES = "'HOLIDAY','CLOSURE','EXCEPTIONAL_WORKING'"
NEW_TYPES = "'HOLIDAY','CLOSURE','EXCEPTIONAL_WORKING','VACATION'"


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        RANGES,
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "is_cancelled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_id", _uuid(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
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
            ["cancelled_by_id"], ["users.id"], name="fk_vacation_range_cancelled_by"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name="fk_vacation_range_created_by"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["users.id"], name="fk_vacation_range_updated_by"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("end_date >= start_date", name="ck_vacation_range_order"),
        sa.CheckConstraint(
            "length(btrim(title)) > 0", name="ck_vacation_range_title"
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name="ck_vacation_range_reason"
        ),
        sa.CheckConstraint(
            "(is_cancelled AND cancelled_at IS NOT NULL "
            "AND cancelled_by_id IS NOT NULL "
            "AND length(btrim(coalesce(cancel_reason, ''))) > 0) "
            "OR (NOT is_cancelled AND cancelled_at IS NULL "
            "AND cancelled_by_id IS NULL AND cancel_reason IS NULL)",
            name="ck_vacation_range_cancel_fields",
        ),
    )

    op.create_index(f"ix_{RANGES}_start_date", RANGES, ["start_date"])
    op.create_index(f"ix_{RANGES}_end_date", RANGES, ["end_date"])
    op.create_index(f"ix_{RANGES}_is_cancelled", RANGES, ["is_cancelled"])

    op.add_column(DAYS, sa.Column("calendar_range_id", _uuid(), nullable=True))
    op.add_column(
        DAYS,
        sa.Column("detached_from_range_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_calendar_day_vacation_range",
        DAYS,
        RANGES,
        ["calendar_range_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        f"ix_{DAYS}_calendar_range_id", DAYS, ["calendar_range_id"]
    )
    op.create_check_constraint(
        "ck_calendar_day_detached_range",
        DAYS,
        "detached_from_range_at IS NULL OR calendar_range_id IS NOT NULL",
    )

    # VACATION is only declarable through a range, but it is still a stored
    # day type: the database must accept the rows the range materialises.
    op.drop_constraint("ck_calendar_day_type", DAYS, type_="check")
    op.create_check_constraint(
        "ck_calendar_day_type", DAYS, f"day_type IN ({NEW_TYPES})"
    )


def downgrade() -> None:
    bind = op.get_bind()
    vacation_days = bind.execute(
        sa.text(f"SELECT count(*) FROM {DAYS} WHERE day_type = 'VACATION'")
    ).scalar_one()
    ranges = bind.execute(sa.text(f"SELECT count(*) FROM {RANGES}")).scalar_one()
    if vacation_days or ranges:
        raise RuntimeError(
            "Refusing to downgrade while vacation calendar records exist "
            f"({ranges} range(s), {vacation_days} vacation day(s)): a vacation "
            "is an institutional record. Revert the application release instead."
        )

    op.drop_constraint("ck_calendar_day_type", DAYS, type_="check")
    op.create_check_constraint(
        "ck_calendar_day_type", DAYS, f"day_type IN ({OLD_TYPES})"
    )

    op.drop_constraint("ck_calendar_day_detached_range", DAYS, type_="check")
    op.drop_index(f"ix_{DAYS}_calendar_range_id", table_name=DAYS)
    op.drop_constraint("fk_calendar_day_vacation_range", DAYS, type_="foreignkey")
    op.drop_column(DAYS, "detached_from_range_at")
    op.drop_column(DAYS, "calendar_range_id")

    op.drop_index(f"ix_{RANGES}_is_cancelled", table_name=RANGES)
    op.drop_index(f"ix_{RANGES}_end_date", table_name=RANGES)
    op.drop_index(f"ix_{RANGES}_start_date", table_name=RANGES)
    op.drop_table(RANGES)
