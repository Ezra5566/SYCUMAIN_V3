"""Phase 10: make ``audit_logs`` append-only in the database.

Revision ID: d1e4a7b9c2f5
Revises: c4d7e91b2f68

The Phase 9 assessment found that audit history was append-only only by
application convention: ``audit_logs`` had no immutability trigger, and the
``portal`` role the API connects as holds ``UPDATE`` and ``DELETE`` (and is a
superuser in every environment this project ships). A database that permits an
ordinary application operation to rewrite an audit record cannot be presented
as an institutional audit trail.

This revision installs the enforcement described in
``app/database/audit_immutability.py``:

* ``audit_logs_reject_mutation()`` raises ``insufficient_privilege`` for any
  attempt to change, remove or truncate an existing record;
* ``BEFORE UPDATE``/``BEFORE DELETE`` row triggers and a ``BEFORE TRUNCATE``
  statement trigger call it;
* ``UPDATE``, ``DELETE``, ``TRUNCATE`` and ``REFERENCES`` are revoked from
  ``PUBLIC``.

``INSERT`` and ``SELECT`` are untouched, so legitimate new events and
authorized reads keep working. No existing row is read, rewritten or deleted.

The trigger fires for the table owner and for a superuser, which is what makes
it effective in the development database as well as a hardened production one.
The stated limitation is unchanged: a superuser or the owner can still disable
or drop the trigger. Protection against a hostile database administrator needs
append-only off-host log shipping, which is an infrastructure decision, not
something a migration can supply.

Independent of this revision, ``scripts/provision-db-roles.sh`` provides the
second layer for a production-shaped installation: a non-superuser application
role that owns nothing and is granted only ``SELECT``/``INSERT`` on this table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from alembic import op

from app.database.audit_immutability import install_statements, uninstall_statements

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "d1e4a7b9c2f5"
down_revision: str | Sequence[str] | None = "c4d7e91b2f68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "audit_logs"


def upgrade() -> None:
    for statement in install_statements():
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in uninstall_statements():
        op.execute(sa.text(statement))
