"""Database-enforced immutability for ``audit_logs``.

Why a trigger rather than only a grant
--------------------------------------
The audit table is append-only by application convention: nothing in the API
updates or deletes a row. Convention is not a control. It does not stop a
reporting query, a data-fix script, a compromised API process, or a future
endpoint that reuses the ORM session from rewriting history.

Removing ``UPDATE``/``DELETE`` privileges is the right first layer, but it
cannot be the only one here: the PostgreSQL image creates ``POSTGRES_USER`` as
a **superuser**, and a superuser (or the table owner) can always grant the
privilege back. A statement-level trigger, by contrast, fires for the owner and
for a superuser alike, so it protects the table in every configuration this
project actually ships — including the development database, where the
application connects as ``portal`` (a superuser and the table owner).

What is installed
-----------------
* ``audit_logs_reject_mutation()`` — a ``plpgsql`` function that raises
  ``insufficient_privilege`` (SQLSTATE 42501) for any attempt to change or
  remove an existing record.
* ``BEFORE UPDATE`` and ``BEFORE DELETE`` row triggers, and a
  ``BEFORE TRUNCATE`` statement trigger.
* A ``REVOKE`` of ``UPDATE``, ``DELETE``, ``TRUNCATE`` and ``REFERENCES`` from
  ``PUBLIC`` so a database whose grants were widened cannot be emptied by an
  ordinary role either.

``INSERT`` and ``SELECT`` are deliberately untouched: new audit events must
keep working, and authorized readers must keep reading.

Stated limitation
-----------------
A superuser or the owning role can still ``ALTER TABLE ... DISABLE TRIGGER``,
``DROP TRIGGER``, or ``TRUNCATE`` after disabling the trigger. This is not
claimed to be tamper-proof against a database administrator — it is proof
against ordinary application operations, which is what the institutional audit
requirement asks for. Genuine protection against a hostile DBA requires the log
to leave the database (streaming to append-only storage, or WORM retention);
that is an infrastructure decision, recorded in the Phase 10 report.

The same SQL is applied from two places so every environment agrees:

* ``app/models/audit.py`` installs it from a table ``after_create`` event, so
  ``Base.metadata.create_all`` (the pytest fixture) reproduces production's
  guarantee instead of testing a weaker schema;
* the ``d1e4a7b9c2f5`` migration installs it on a database whose tables already
  exist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

TRIGGER_FUNCTION = "audit_logs_reject_mutation"

#: (trigger name, event). TRUNCATE must be a statement-level trigger; PostgreSQL
#: does not support a row-level TRUNCATE trigger.
TRIGGERS: tuple[tuple[str, str], ...] = (
    ("audit_logs_reject_update", "UPDATE"),
    ("audit_logs_reject_delete", "DELETE"),
    ("audit_logs_reject_truncate", "TRUNCATE"),
)

#: ``RAISE EXCEPTION USING`` is used instead of a format string so the statement
#: contains no ``%`` character — the driver treats ``%`` as a placeholder
#: delimiter, and a literal one would have to be escaped at every call site.
_CREATE_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {TRIGGER_FUNCTION}() RETURNS trigger
LANGUAGE plpgsql AS $audit_guard$
BEGIN
    RAISE EXCEPTION USING
        ERRCODE = 'insufficient_privilege',
        MESSAGE = 'audit_logs is append-only: ' || TG_OP || ' is not permitted',
        HINT = 'Record a new audit event instead of changing or removing an existing one.';
END;
$audit_guard$;
"""


def install_statements() -> list[str]:
    """The statements that make ``audit_logs`` append-only.

    Idempotent: the function is replaced, and each trigger is dropped before it
    is recreated, so running this twice is harmless.
    """
    statements = [_CREATE_FUNCTION]
    for name, event in TRIGGERS:
        scope = "STATEMENT" if event == "TRUNCATE" else "ROW"
        statements.append(f"DROP TRIGGER IF EXISTS {name} ON audit_logs;")
        statements.append(
            f"CREATE TRIGGER {name} BEFORE {event} ON audit_logs "
            f"FOR EACH {scope} EXECUTE FUNCTION {TRIGGER_FUNCTION}();"
        )
    statements.append(
        "REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES ON audit_logs FROM PUBLIC;"
    )
    return statements


def uninstall_statements() -> list[str]:
    """Remove the enforcement, for a legitimate schema rollback."""
    statements = [
        f"DROP TRIGGER IF EXISTS {name} ON audit_logs;" for name, _ in TRIGGERS
    ]
    statements.append(f"DROP FUNCTION IF EXISTS {TRIGGER_FUNCTION}();")
    return statements


def install(connection: Connection) -> None:
    """Apply the enforcement to an open connection (PostgreSQL only)."""
    if connection.dialect.name != "postgresql":
        return
    for statement in install_statements():
        connection.exec_driver_sql(statement)


def uninstall(connection: Connection) -> None:
    """Remove the enforcement from an open connection (PostgreSQL only)."""
    if connection.dialect.name != "postgresql":
        return
    for statement in uninstall_statements():
        connection.exec_driver_sql(statement)


__all__ = [
    "TRIGGERS",
    "TRIGGER_FUNCTION",
    "install",
    "install_statements",
    "uninstall",
    "uninstall_statements",
]
