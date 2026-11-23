"""add auth rate-limit counters

Fixed-window counters for login and password recovery. Database-backed so the
limit is shared by every API worker and survives a restart; see
``app/core/ratelimit.py`` for why that matters.

The primary key is the whole counter identity, which is also what the atomic
upsert conflicts on: one row per (scope, hashed key, window). ``window_start``
is indexed separately for the cleanup job, which deletes closed windows.

Revision ID: c1d2e3f4a5b6
Revises: 8a41c9d2e7b5
Create Date: 2026-11-10 17:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "8a41c9d2e7b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_limits",
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("scope", "key_hash", "window_start"),
    )
    op.create_index(
        "ix_auth_rate_limits_window_start",
        "auth_rate_limits",
        ["window_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limits_window_start", table_name="auth_rate_limits")
    op.drop_table("auth_rate_limits")
