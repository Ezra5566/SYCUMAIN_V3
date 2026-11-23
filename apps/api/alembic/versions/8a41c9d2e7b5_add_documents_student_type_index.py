"""add the documents (student_id, document_type) index

The ``Document`` model declares this composite index for the student document
summary (one student's documents filtered by type), but no migration ever
created it. ``alembic check`` reported the drift, which means the query was
being answered by a scan on the deployed schema and that autogenerate could no
longer be trusted as a source of truth.

Revision ID: 8a41c9d2e7b5
Revises: b7e4c81a9f02
Create Date: 2026-11-10 16:20:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a41c9d2e7b5"
down_revision: str | Sequence[str] | None = "b7e4c81a9f02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_documents_student_type",
        "documents",
        ["student_id", "document_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_documents_student_type", table_name="documents")
