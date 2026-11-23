"""stage 8c document review, photos and password reset

Three independent additions, all required by the operational workflows in
Stage 8C:

* ``password_reset_tokens`` — self-service password recovery. Only the SHA-256
  hash of a token is stored, so a database disclosure cannot be replayed as a
  working reset link.
* ``documents`` review and expectation columns — an uploaded file is not the
  same thing as an accepted one, so review state is tracked separately from the
  storage lifecycle. ``is_required`` / ``expires_on`` let the portal report a
  document as missing or expired without inventing rows for documents that were
  never uploaded. ``superseded_by_id`` keeps replaced documents (a renewed
  passport) as history instead of overwriting them.
* ``students`` profile photo references — replaced ``profile_photo_url``, which
  implied a public URL. Private object storage is read through an
  authorization-checked endpoint instead, so the database holds the object key
  and content type and never a link.

``review_status`` and ``is_required`` are NOT NULL, so both are added with a
server default; without one the ALTER would fail on any deployment that already
holds documents.

Revision ID: b7e4c81a9f02
Revises: 2f4ab7613cf2
Create Date: 2026-09-17 16:41:08.214773

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e4c81a9f02"
down_revision: Union[str, Sequence[str], None] = "2f4ab7613cf2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- Self-service password recovery ---------------------------------
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_password_reset_tokens_token_hash"),
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_password_reset_tokens_user_id"),
        "password_reset_tokens",
        ["user_id"],
        unique=False,
    )

    # --- Document review and institutional expectations -----------------
    # Existing documents predate review, so they are backfilled as PENDING:
    # claiming they were approved would be a false statement about history.
    op.add_column(
        "documents",
        sa.Column(
            "review_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
    )
    op.add_column(
        "documents", sa.Column("reviewed_by", sa.UUID(), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("documents", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "is_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("documents", sa.Column("expires_on", sa.Date(), nullable=True))
    op.add_column(
        "documents", sa.Column("superseded_by_id", sa.UUID(), nullable=True)
    )
    op.create_index(
        op.f("ix_documents_review_status"),
        "documents",
        ["review_status"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_documents_reviewed_by_users",
        "documents",
        "users",
        ["reviewed_by"],
        ["id"],
    )
    # Self-referential: a replaced document points at its successor. No cascade,
    # because deleting the successor must not silently erase the superseded row.
    op.create_foreign_key(
        "fk_documents_superseded_by_id_documents",
        "documents",
        "documents",
        ["superseded_by_id"],
        ["id"],
    )

    # --- Profile photo references ---------------------------------------
    # ``profile_photo_url`` was never populated by any code path: it described a
    # public link the system deliberately does not create. Replaced outright
    # rather than migrated, since there is nothing to carry across.
    op.drop_column("students", "profile_photo_url")
    op.add_column(
        "students",
        sa.Column("profile_photo_object_key", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column("profile_photo_content_type", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column(
            "profile_photo_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("students", "profile_photo_updated_at")
    op.drop_column("students", "profile_photo_content_type")
    op.drop_column("students", "profile_photo_object_key")
    op.add_column(
        "students", sa.Column("profile_photo_url", sa.String(length=500), nullable=True)
    )

    op.drop_constraint(
        "fk_documents_superseded_by_id_documents", "documents", type_="foreignkey"
    )
    op.drop_constraint("fk_documents_reviewed_by_users", "documents", type_="foreignkey")
    op.drop_index(op.f("ix_documents_review_status"), table_name="documents")
    op.drop_column("documents", "superseded_by_id")
    op.drop_column("documents", "expires_on")
    op.drop_column("documents", "is_required")
    op.drop_column("documents", "review_note")
    op.drop_column("documents", "reviewed_at")
    op.drop_column("documents", "reviewed_by")
    op.drop_column("documents", "review_status")

    op.drop_index(
        op.f("ix_password_reset_tokens_user_id"), table_name="password_reset_tokens"
    )
    op.drop_index(
        op.f("ix_password_reset_tokens_token_hash"), table_name="password_reset_tokens"
    )
    op.drop_table("password_reset_tokens")
