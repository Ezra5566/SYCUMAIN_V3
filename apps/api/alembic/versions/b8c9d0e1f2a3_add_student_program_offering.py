"""Link students to a period-specific program offering.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2

The column is nullable on purpose. Existing students keep their historical
enrollment-based timetable until an administrator makes an explicit, audited
assignment; there is no automatic backfill.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column("program_offering_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_students_program_offering",
        "students",
        "program_offerings",
        ["program_offering_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_students_program_offering_id",
        "students",
        ["program_offering_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_students_program_offering_id", table_name="students")
    op.drop_constraint("fk_students_program_offering", "students", type_="foreignkey")
    op.drop_column("students", "program_offering_id")