"""Phase 7: temporary credential deadlines and the email outbox.

Revision ID: c4d7e91b2f68
Revises: b8d2f4a61c93

Two operational gaps closed without changing existing behaviour:

* ``users.temporary_password_expires_at`` — an administrator-issued temporary
  password already had to be replaced before the portal could be used, but it
  never stopped being a valid *login* credential. A deadline makes it
  time-limited as well as single-use in effect. Existing rows are NULL; a NULL
  deadline is not a bypass, because the forced-change rule still applies.

* ``email_outbox`` — durable queue for operational notification email. Password
  reset and activation links are deliberately **not** stored here: those bodies
  contain working credentials. The unique ``dedupe_key`` is the duplicate guard.

No existing row is read, rewritten or deleted.

Downgrade is safe for the column. Dropping the outbox erases only delivery
history for notification email — no student, document or audit record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "c4d7e91b2f68"
down_revision: str | Sequence[str] | None = "b8d2f4a61c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "temporary_password_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_table(
        "email_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dedupe_key", sa.String(length=150), nullable=False),
        sa.Column("to_email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_email_outbox_purpose", "email_outbox", ["purpose"])
    op.create_index("ix_email_outbox_status", "email_outbox", ["status"])


def downgrade() -> None:
    op.drop_index("ix_email_outbox_status", table_name="email_outbox")
    op.drop_index("ix_email_outbox_purpose", table_name="email_outbox")
    op.drop_table("email_outbox")
    op.drop_column("users", "temporary_password_expires_at")
