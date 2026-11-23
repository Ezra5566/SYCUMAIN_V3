"""Drop the legacy Student academic-placement projections.

Revision ID: f8a1b2c3d4e5
Revises: e2f3a4b5c6d7

The three columns were compatibility mirrors. Admission episodes, academic
placements and approved programme changes are now the source of truth.

The downgrade recreates the columns EMPTY. The original values are not
recoverable from this migration; restoring them requires the pre-drop backup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "f8a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL drops each column's indexes and table constraints with the
    # column. No other table or history row is touched.
    op.drop_column("students", "program_offering_id")
    op.drop_column("students", "program_id")
    op.drop_column("students", "major_id")


def downgrade() -> None:
    # Non-restorative: the columns are recreated nullable and empty. Recovering
    # their former values requires restoring the pre-drop backup.
    op.add_column(
        "students",
        sa.Column("major_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column("program_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column("program_offering_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        None,
        "students",
        "majors",
        ["major_id"],
        ["id"],
    )
    op.create_foreign_key(
        None,
        "students",
        "programs",
        ["program_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_students_program_offering",
        "students",
        "program_offerings",
        ["program_offering_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_students_major_id", "students", ["major_id"])
    op.create_index("ix_students_program_id", "students", ["program_id"])
    op.create_index(
        "ix_students_program_offering_id", "students", ["program_offering_id"]
    )
