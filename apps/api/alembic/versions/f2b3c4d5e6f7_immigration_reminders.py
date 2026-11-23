"""Immigration expiry reminders.

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6

One row per alert: a specific document on a specific verified profile reached a
specific expiry tier with a specific expiry date. The unique constraint is the
duplicate guard — running the reconciliation twice, or from two workers at once,
cannot produce a second warning for the same condition.

``resolved_at`` and ``resolution`` record why an alert stopped applying, so a
renewed passport can be told apart from a corrected typo. Rows are never deleted:
the reminder history is the audit trail for "were we warned, and when did it
clear".

No existing profile, document or notification row is read or rewritten.

Downgrade refuses while reminder history exists, because dropping the table would
erase the record of which official warnings were issued.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "f2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "immigration_reminders"


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("immigration_profile_id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("document_type", sa.String(length=30), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["immigration_profile_id"],
            ["immigration_profiles.id"],
            name="fk_immigration_reminder_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_immigration_reminder_student",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "immigration_profile_id",
            "document_type",
            "tier",
            "expiry_date",
            name="uq_immigration_reminder_alert",
        ),
        sa.CheckConstraint(
            "document_type IN ('PASSPORT', 'VISA', 'RESIDENCE_PERMIT')",
            name="ck_immigration_reminder_document_type",
        ),
        sa.CheckConstraint(
            "tier IN ('EXPIRED', 'URGENT', 'EXPIRING_SOON')",
            name="ck_immigration_reminder_tier",
        ),
        sa.CheckConstraint(
            "(resolved_at IS NULL AND resolution IS NULL) "
            "OR (resolved_at IS NOT NULL AND resolution IS NOT NULL)",
            name="ck_immigration_reminder_resolution",
        ),
    )

    op.create_index(
        f"ix_{TABLE}_profile_id", TABLE, ["immigration_profile_id"]
    )
    op.create_index(f"ix_{TABLE}_student_id", TABLE, ["student_id"])
    op.create_index(f"ix_{TABLE}_open", TABLE, ["resolved_at"])


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    if rows:
        raise RuntimeError(
            "Refusing to downgrade while immigration reminder history exists "
            f"({rows} row(s)): these record which official expiry warnings were "
            "issued and when they cleared. Revert the application release "
            "instead."
        )

    op.drop_index(f"ix_{TABLE}_open", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_student_id", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_profile_id", table_name=TABLE)
    op.drop_table(TABLE)
