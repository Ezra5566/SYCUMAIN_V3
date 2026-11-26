"""Align the immigration reminders index name with the model.

Revision ID: b8d2f4a61c93
Revises: a7c1e9b25d40

``immigration_reminders.immigration_profile_id`` is declared ``index=True`` in
the model, so SQLAlchemy derives the index name from the table and column:
``ix_immigration_reminders_immigration_profile_id``. The original migration
(f2b3c4d5e6f7) created the same index on the same column under the shorter name
``ix_immigration_reminders_profile_id``, which left ``alembic check`` reporting
a drop plus a create for what is one identical index.

This revision renames the index. It is a metadata-only operation: no row is
read, rewritten or reordered, no constraint changes, and the index definition
(btree on ``immigration_profile_id``) is unchanged. It is safe to run against a
live table and takes a brief lock on that table's metadata only.

The rename is idempotent in the sense that it is skipped if the target name
already exists (for example on a database that was repaired by hand), so a
second run or a resynchronised environment does not fail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "b8d2f4a61c93"
down_revision: str | Sequence[str] | None = "a7c1e9b25d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "immigration_reminders"
OLD_NAME = "ix_immigration_reminders_profile_id"
NEW_NAME = "ix_immigration_reminders_immigration_profile_id"


def _index_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    names = _index_names()
    if OLD_NAME in names and NEW_NAME not in names:
        op.execute(sa.text(f"ALTER INDEX {OLD_NAME} RENAME TO {NEW_NAME}"))


def downgrade() -> None:
    names = _index_names()
    if NEW_NAME in names and OLD_NAME not in names:
        op.execute(sa.text(f"ALTER INDEX {NEW_NAME} RENAME TO {OLD_NAME}"))
