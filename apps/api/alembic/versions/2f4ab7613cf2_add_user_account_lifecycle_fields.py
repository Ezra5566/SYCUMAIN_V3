"""add user account lifecycle fields

Adds the two columns the account lifecycle needs:

* ``users.must_change_password`` — set when an administrator issues a temporary
  password, so the account can be prompted to replace it.
* ``users.last_login_at`` — the last successful sign-in, shown to administrators
  and to the account holder in settings.

``must_change_password`` is NOT NULL, so it is added with a server default of
false; without it the ALTER would fail on any table that already holds rows
(every existing deployment).

Revision ID: 2f4ab7613cf2
Revises: 3b303645225a
Create Date: 2026-09-17 10:02:19.530577

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2f4ab7613cf2"
down_revision: Union[str, Sequence[str], None] = "3b303645225a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "must_change_password")
