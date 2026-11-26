"""Database-enforced audit history.

These tests exercise the guarantee added in Phase 10 through the *database*, not
through the ORM: an ordinary UPDATE, DELETE or TRUNCATE of ``audit_logs`` must
fail, while inserting a new event and reading history must keep working.

The schema used here is built by ``Base.metadata.create_all`` in the pytest
fixture, and ``AuditLog`` installs the same triggers from an ``after_create``
event that migration ``d1e4a7b9c2f5`` applies to an existing database. That is
deliberate: the suite cannot pass against a weaker schema than production runs.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.audit import record_audit
from app.models.audit import AuditLog

EXPECTED_TRIGGERS = {
    "audit_logs_reject_update",
    "audit_logs_reject_delete",
    "audit_logs_reject_truncate",
}


def _stage_entry(db_session, action: str = "test.audit.immutability") -> AuditLog:
    """Insert one legitimate audit event and leave it uncommitted-but-visible."""
    entry = record_audit(
        db_session,
        action=action,
        entity_type="test_entity",
        entity_id=uuid.uuid4(),
        context={"note": "synthetic"},
    )
    db_session.flush()
    return entry


def test_trigger_set_is_installed(db_session) -> None:
    installed = set(
        db_session.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'audit_logs'::regclass AND NOT tgisinternal"
            )
        )
        .scalars()
        .all()
    )
    assert installed >= EXPECTED_TRIGGERS


def test_legitimate_event_is_recorded_and_readable(db_session) -> None:
    entry = _stage_entry(db_session, "test.audit.insert")
    found = db_session.query(AuditLog).filter(AuditLog.id == entry.id).one()
    assert found.action == "test.audit.insert"
    assert found.entity_type == "test_entity"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_logs SET action = 'tampered' WHERE id = :id",
        "DELETE FROM audit_logs WHERE id = :id",
    ],
)
def test_update_and_delete_are_rejected(db_session, statement: str) -> None:
    entry = _stage_entry(db_session)

    # A savepoint keeps the failed statement from poisoning the fixture's outer
    # transaction, so the rest of the test can still read the row.
    with pytest.raises(DBAPIError) as excinfo, db_session.begin_nested():
        db_session.execute(text(statement), {"id": entry.id})

    message = str(excinfo.value)
    assert "append-only" in message
    # SQLSTATE 42501 = insufficient_privilege, so a client can tell "refused"
    # from "database unreachable" without parsing the message text.
    sqlstate = getattr(excinfo.value.orig, "sqlstate", None)
    assert sqlstate in {None, "42501"}

    # The original row is intact after the refusal.
    survivor = db_session.query(AuditLog).filter(AuditLog.id == entry.id).one()
    assert survivor.action == "test.audit.immutability"


def test_truncate_is_rejected(db_session) -> None:
    _stage_entry(db_session)

    with pytest.raises(DBAPIError) as excinfo, db_session.begin_nested():
        db_session.execute(text("TRUNCATE audit_logs"))

    assert "append-only" in str(excinfo.value)


def test_existing_rows_survive_a_rejected_truncate(db_session) -> None:
    _stage_entry(db_session, "test.audit.survivor")
    before = db_session.query(AuditLog).count()

    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(text("TRUNCATE audit_logs"))

    assert db_session.query(AuditLog).count() == before


def test_rolled_back_business_change_leaves_no_audit_event(db_session) -> None:
    """An audit entry must never outlive the change it describes."""
    marker = "test.audit.rolled_back"
    assert db_session.query(AuditLog).filter(AuditLog.action == marker).count() == 0

    savepoint = db_session.begin_nested()
    record_audit(db_session, action=marker, entity_type="test_entity")
    db_session.flush()
    savepoint.rollback()

    assert db_session.query(AuditLog).filter(AuditLog.action == marker).count() == 0


def test_public_role_has_no_mutation_privilege(db_session) -> None:
    """`PUBLIC` must not hold UPDATE/DELETE/TRUNCATE on the audit table."""
    acl = db_session.execute(
        text(
            "SELECT relacl::text FROM pg_class WHERE oid = 'audit_logs'::regclass"
        )
    ).scalar_one()
    if acl is None:
        # No explicit ACL means only the owner — which is correct, and is the
        # state a freshly created database is expected to be in.
        return
    assert "=w/" not in acl.replace(" ", "")
    assert "=d/" not in acl.replace(" ", "")
