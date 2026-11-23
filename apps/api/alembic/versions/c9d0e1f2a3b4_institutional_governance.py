"""Institutional staff lifecycle and immigration provenance.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3

Two additive changes:

* ``staff.staff_id`` becomes optional. SCU has not supplied an official staff
  identifier format, and requiring one made it impossible to create a staff
  profile until an invented number was typed in.
* immigration profiles record where the current official values came from and
  whether a human has verified them. Existing rows are conservatively
  UNVERIFIED: migration must not turn pre-existing data into verified data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "staff",
        "staff_id",
        existing_type=sa.String(length=50),
        nullable=True,
    )

    op.add_column(
        "immigration_profiles",
        sa.Column(
            "data_source",
            sa.String(length=30),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    op.add_column(
        "immigration_profiles",
        sa.Column(
            "verification_status",
            sa.String(length=20),
            nullable=False,
            server_default="UNVERIFIED",
        ),
    )
    op.add_column(
        "immigration_profiles",
        sa.Column("source_reference", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "immigration_profiles",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "immigration_profiles",
        sa.Column(
            "verified_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_immigration_profiles_verified_by",
        "immigration_profiles",
        "users",
        ["verified_by_id"],
        ["id"],
    )
    op.create_index(
        "ix_immigration_profiles_verification_status",
        "immigration_profiles",
        ["verification_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_immigration_profiles_verification_status",
        table_name="immigration_profiles",
    )
    op.drop_constraint(
        "fk_immigration_profiles_verified_by",
        "immigration_profiles",
        type_="foreignkey",
    )
    op.drop_column("immigration_profiles", "verified_by_id")
    op.drop_column("immigration_profiles", "verified_at")
    op.drop_column("immigration_profiles", "source_reference")
    op.drop_column("immigration_profiles", "verification_status")
    op.drop_column("immigration_profiles", "data_source")

    # The downgrade is intentionally fail-closed: inventing identifiers to
    # satisfy a restored NOT NULL would corrupt the institutional record.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM staff WHERE staff_id IS NULL) THEN
                RAISE EXCEPTION
                    'Cannot downgrade: staff rows without an official identifier exist';
            END IF;
        END $$;
        """
    )
    op.alter_column(
        "staff",
        "staff_id",
        existing_type=sa.String(length=50),
        nullable=False,
    )
