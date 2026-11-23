"""extend student model with status and additional fields

Revision ID: cfe639bbeb30
Revises: bec267d6f0fe
Create Date: 2026-09-15 19:21:52.001840

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cfe639bbeb30'
down_revision: Union[str, Sequence[str], None] = 'bec267d6f0fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new nullable columns first
    op.add_column('students', sa.Column('preferred_name', sa.String(length=100), nullable=True))
    op.add_column('students', sa.Column('gender', sa.String(length=20), nullable=True))
    op.add_column('students', sa.Column('profile_photo_url', sa.String(length=500), nullable=True))

    # Add status as nullable first
    op.add_column('students', sa.Column('status', sa.String(length=20), nullable=True))

    # Update existing rows to set status based on is_active
    op.execute("UPDATE students SET status = 'ACTIVE' WHERE is_active = true")
    op.execute("UPDATE students SET status = 'INACTIVE' WHERE is_active = false")
    op.execute("UPDATE students SET status = 'ACTIVE' WHERE status IS NULL")

    # Now make status NOT NULL
    op.alter_column('students', 'status', nullable=False)

    # Create index
    op.create_index(op.f('ix_students_status'), 'students', ['status'], unique=False)

    # Drop is_active column
    op.drop_column('students', 'is_active')


def downgrade() -> None:
    """Downgrade schema."""
    # Add back is_active column
    op.add_column('students', sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False))

    # Update is_active based on status
    op.execute("UPDATE students SET is_active = true WHERE status = 'ACTIVE'")
    op.execute("UPDATE students SET is_active = false WHERE status != 'ACTIVE'")

    # Drop status and related columns
    op.drop_index(op.f('ix_students_status'), table_name='students')
    op.drop_column('students', 'status')
    op.drop_column('students', 'profile_photo_url')
    op.drop_column('students', 'gender')
    op.drop_column('students', 'preferred_name')
