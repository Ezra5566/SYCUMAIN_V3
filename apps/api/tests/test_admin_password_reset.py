"""Admin-assisted password recovery (the V1-style institutional process).

Phase 7 fixed two gaps in this workflow. Both are pinned here:

* a temporary password issued at the counter is **time-limited**, not merely
  forced-to-change; and
* the backend enforces administrator authorization, so a teacher or student
  cannot reset an account even by calling the endpoint directly.

The rest of the flow already existed and must keep working: the password is
returned once and never stored in plaintext, every existing session is revoked,
the account is trapped behind the change-password screen until it complies, and
the audit trail records who did what without recording either credential.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.auth.dependencies import SESSION_COOKIE_NAME
from app.models.audit import AuditLog
from app.models.identity import User
from app.models.session import UserSession

API = "/api/v1"
TEMPORARY = None  # populated by the reset call, never by the test
STRONG = "Adm1n-Reset-Passphrase!42"


def _login(client: TestClient, email: str, password: str = "password123"):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


def _logout(client: TestClient):
    client.post(f"{API}/auth/logout")


def _provision_student(client: TestClient, *, password: str = STRONG) -> tuple[str, str]:
    """Create a student account through the administrative endpoint."""
    assert _login(client, "admin@school.portal").status_code == 200
    email = f"reset-{uuid.uuid4().hex[:8]}@school.portal"
    created = client.post(
        f"{API}/users/",
        json={
            "email": email,
            "full_name": "Reset Subject",
            "roles": ["STUDENT"],
            "password": password,
            "must_change_password": False,
        },
    )
    assert created.status_code == 201, created.text
    _logout(client)
    return email, created.json()["account"]["id"]


def _reset_as_admin(client: TestClient, user_id: str) -> dict:
    assert _login(client, "admin@school.portal").status_code == 200
    response = client.post(f"{API}/users/{user_id}/reset-password", json={})
    assert response.status_code == 200, response.text
    _logout(client)
    return response.json()


def test_temporary_password_is_time_limited_and_reported_once(client):
    """The issued credential has a deadline the administrator can communicate."""
    _, user_id = _provision_student(client)

    result = _reset_as_admin(client, user_id)

    assert result["must_change_password"] is True
    assert isinstance(result["temporary_password"], str) and result["temporary_password"]
    assert result["temporary_password_expires_at"] is not None

    deadline = datetime.fromisoformat(result["temporary_password_expires_at"])
    remaining = deadline - datetime.now(UTC)
    # Default policy is 72 hours; allow generous slack for clock skew.
    assert timedelta(hours=71) < remaining <= timedelta(hours=73)


def test_temporary_password_is_never_stored_in_plaintext(client, db_session):
    email, user_id = _provision_student(client)
    temporary = _reset_as_admin(client, user_id)["temporary_password"]

    user = db_session.query(User).filter(User.id == uuid.UUID(user_id)).one()
    assert temporary not in (user.hashed_password or "")
    assert user.temporary_password_expires_at is not None


def test_reset_revokes_existing_sessions(client):
    email, user_id = _provision_student(client)
    assert _login(client, email, STRONG).status_code == 200
    assert client.get(f"{API}/auth/me").status_code == 200

    _reset_as_admin(client, user_id)

    # The live browser session for that account is gone, not merely flagged.
    assert client.get(f"{API}/auth/me").status_code == 401


def test_reset_leaves_no_session_rows(client, db_session):
    email, user_id = _provision_student(client)
    assert _login(client, email, STRONG).status_code == 200

    user_uuid = uuid.UUID(user_id)
    assert (
        db_session.query(UserSession).filter(UserSession.user_id == user_uuid).count()
        > 0
    )

    _reset_as_admin(client, user_id)

    assert (
        db_session.query(UserSession).filter(UserSession.user_id == user_uuid).count()
        == 0
    )


def test_temporary_password_cannot_be_used_for_anything_but_the_change(client):
    """A temporary credential is single-use *in effect*: the server blocks work."""
    email, user_id = _provision_student(client)
    temporary = _reset_as_admin(client, user_id)["temporary_password"]

    signed_in = _login(client, email, temporary)
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["must_change_password"] is True

    blocked = client.get(f"{API}/students/me")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    # Everything needed to finish the change, and logout, still works.
    assert client.get(f"{API}/auth/me").status_code == 200

    changed = client.post(
        f"{API}/auth/password/change",
        json={"current_password": temporary, "new_password": "N3w-Passphrase!8842"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["must_change_password"] is False

    # Once replaced, the temporary credential is dead and the new one works.
    assert _login(client, email, temporary).status_code == 401
    assert _login(client, email, "N3w-Passphrase!8842").status_code == 200


def test_expired_temporary_password_is_refused_with_a_specific_code(
    client, db_session
):
    email, user_id = _provision_student(client)
    temporary = _reset_as_admin(client, user_id)["temporary_password"]

    user = db_session.query(User).filter(User.id == uuid.UUID(user_id)).one()
    user.temporary_password_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    response = _login(client, email, temporary)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TEMPORARY_PASSWORD_EXPIRED"
    # No session may be created for an expired credential.
    assert SESSION_COOKIE_NAME not in response.cookies
    assert client.get(f"{API}/auth/me").status_code == 401

    actions = {
        row.context.get("reason")
        for row in db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(user_id))
        .all()
        if row.action == "auth.login_failed"
    }
    assert "temporary_password_expired" in actions


def test_a_new_reset_extends_the_deadline(client, db_session):
    """Re-issuing is the supported recovery from an expired credential."""
    email, user_id = _provision_student(client)
    _reset_as_admin(client, user_id)

    user = db_session.query(User).filter(User.id == uuid.UUID(user_id)).one()
    user.temporary_password_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    second = _reset_as_admin(client, user_id)

    assert second["temporary_password_expires_at"] is not None
    deadline = datetime.fromisoformat(second["temporary_password_expires_at"])
    assert deadline > datetime.now(UTC)
    assert _login(client, email, second["temporary_password"]).status_code == 200


def test_teacher_cannot_reset_an_account(client):
    email, user_id = _provision_student(client)
    assert _login(client, "teacher@school.portal").status_code == 200

    response = client.post(f"{API}/users/{user_id}/reset-password", json={})

    assert response.status_code == 403
    # The existing password still works.
    assert _login(client, email, STRONG).status_code == 200


def test_student_cannot_reset_an_account(client):
    email, user_id = _provision_student(client)
    assert _login(client, email, STRONG).status_code == 200

    response = client.post(f"{API}/users/{user_id}/reset-password", json={})

    assert response.status_code == 403


def test_delegated_administrator_cannot_reset_an_administrator(client, db_session):
    """`users.manage_students` must not reach a privileged account."""
    admin = db_session.query(User).filter(User.email == "admin@school.portal").one()
    assert _login(client, "management@school.portal").status_code == 200

    response = client.post(f"{API}/users/{admin.id}/reset-password", json={})

    assert response.status_code == 403


def test_audit_records_the_reset_without_credential_material(client, db_session):
    email, user_id = _provision_student(client)
    temporary = _reset_as_admin(client, user_id)

    user_uuid = uuid.UUID(user_id)
    rows = db_session.query(AuditLog).filter(AuditLog.entity_id == user_uuid).all()
    actions = {row.action for row in rows}

    assert "account.password_reset" in actions
    actor_ids = {row.actor_id for row in rows if row.action == "account.password_reset"}
    admin = db_session.query(User).filter(User.email == "admin@school.portal").one()
    assert actor_ids == {admin.id}

    for row in rows:
        stored = " ".join(
            str(getattr(row, column.name)) for column in AuditLog.__table__.columns
        )
        assert temporary["temporary_password"] not in stored
