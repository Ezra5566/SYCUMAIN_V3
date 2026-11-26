"""late enrollment authorization

Revision ID: f3b7c2d9e6a1
Revises: d1e4a7b9c2f5
Create Date: 2026-11-26 06:20:00.000000

A section in an intake earlier than the current active period can only be
joined with an Admin/Management authorization. These four nullable columns are
the record of that decision. Existing enrolments keep NULL, which is the honest
state: they were made under the rules in force when they were created, and
back-filling an approver would invent one.

The revision is additive only. It creates no rows, drops nothing and does not
touch any other table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3b7c2d9e6a1"
down_revision: str | Sequence[str] | None = "d1e4a7b9c2f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("enrollments", sa.Column("authorization_reason", sa.Text(), nullable=True))
    op.add_column(
        "enrollments",
        sa.Column("authorization_reference", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "enrollments",
        sa.Column("authorized_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "enrollments",
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_enrollment_authorized_by",
        "enrollments",
        "users",
        ["authorized_by_id"],
        ["id"],
    )
    op.create_index(
        "ix_enrollments_authorized_by_id",
        "enrollments",
        ["authorized_by_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_enrollments_authorized_by_id", table_name="enrollments")
    op.drop_constraint("fk_enrollment_authorized_by", "enrollments", type_="foreignkey")
    op.drop_column("enrollments", "authorized_at")
    op.drop_column("enrollments", "authorized_by_id")
    op.drop_column("enrollments", "authorization_reference")
    op.drop_column("enrollments", "authorization_reason")
