"""Provisioned accounts: activation tokens instead of temporary passwords

Revision ID: a7c1e9b25d40
Revises: f3c4d5e6f7a8
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c1e9b25d40"
down_revision: str | Sequence[str] | None = "f3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "activation_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_users_activation_required", "users", ["activation_required"], unique=False
    )

    op.create_table(
        "account_activation_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("issued_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "issued_reason", sa.String(length=20), nullable=False, server_default="ADMIN"
        ),
        sa.Column(
            "delivery",
            sa.String(length=20),
            nullable=False,
            server_default="ADMIN_COUNTER",
        ),
        sa.Column("identity_verified_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "identity_verified_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("verification_reference", sa.String(length=120), nullable=True),
        sa.Column("ip_address", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issued_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["identity_verified_by_id"], ["users.id"]),
    )
    op.create_index(
        "ix_account_activation_tokens_token_hash",
        "account_activation_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_account_activation_tokens_user_id",
        "account_activation_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_account_activation_live",
        "account_activation_tokens",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_account_activation_live", table_name="account_activation_tokens")
    op.drop_index(
        "ix_account_activation_tokens_user_id", table_name="account_activation_tokens"
    )
    op.drop_index(
        "ix_account_activation_tokens_token_hash", table_name="account_activation_tokens"
    )
    op.drop_table("account_activation_tokens")
    op.drop_index("ix_users_activation_required", table_name="users")
    op.drop_column("users", "activated_at")
    op.drop_column("users", "activation_required")
