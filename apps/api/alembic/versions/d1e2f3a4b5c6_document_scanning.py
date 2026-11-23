"""Document malware scanning state.

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4

Existing rows are explicitly marked LEGACY_UNSCANNED. A database default of
CLEAN would silently certify files that were uploaded before a scanner existed,
which is exactly the failure this field is meant to prevent.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str = "c9d0e1f2a3b4"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "scan_status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column(
        "documents",
        sa.Column("scan_engine", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE documents SET scan_status = 'LEGACY_UNSCANNED'")
    op.create_index(
        "ix_documents_scan_status",
        "documents",
        ["scan_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_scan_status", table_name="documents")
    op.drop_column("documents", "scanned_at")
    op.drop_column("documents", "scan_engine")
    op.drop_column("documents", "scan_status")
