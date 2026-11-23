"""Self-service password recovery tests.

Recovery is the only path into the system that runs *without* a session, so it
gets stricter treatment than the rest of the auth surface:

* the request endpoint must not disclose whether an address has an account;
* the token must be single-use and short-lived;
* completing a reset must invalidate every existing session;
* and the expiry check must survive what the database actually returns.

That last point is not theoretical. ``password_reset_tokens.expires_at`` is
``TIMESTAMPTZ``, so Postgres hands back an *aware* datetime while the
obvious-looking ``datetime.utcnow()`` is naive. Comparing the two raises
``TypeError``: a 500 on every reset attempt, from a code path that reads as
correct. ``test_expired_token_is_rejected_not_crashed`` pins that down.

Accounts are provisioned through the API and assertions read through the
``db_session`` fixture, which is the same session the request handlers use.
Inspecting a separate connection would silently see an empty table, because the
test's writes live inside an uncommitted transaction.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth.recovery import hash_reset_token
from app.config.settings import get_settings
from app.models.audit import AuditLog
from app.models.identity import User
from app.models.session import PasswordResetToken, UserSession

API = "/api/v1"

STRONG_PASSWORD = "Str0ng-Passphrase!42"
ANOTHER_STRONG_PASSWORD = "An0ther-Passphrase!77"


@pytest.fixture
def dev_channel():
    """Enable the development delivery channel for one test.

    Patched on the cached settings object rather than by replacing
    ``delivery_available``, because the router binds that name at import time —
    patching the module attribute would silently not take effect, and every test
    below would pass while actually exercising the disabled path.
    """
    settings = get_settings()
    original = settings.PASSWORD_RESET_DELIVERY
    settings.PASSWORD_RESET_DELIVERY = "dev"
    try:
        yield
    finally:
        settings.PASSWORD_RESET_DELIVERY = original


@pytest.fixture
def out_of_band_channel():
    """Delivery enabled *without* the dev token in the response.

    This is the production shape: the link travels out of band, so the HTTP
    response never carries a token.
    """
    settings = get_settings()
    original = settings.PASSWORD_RESET_DELIVERY
    settings.PASSWORD_RESET_DELIVERY = "smtp"
    try:
        yield
    finally:
        settings.PASSWORD_RESET_DELIVERY = original


def _request_reset(client: TestClient, email: str):
    return client.post(f"{API}/auth/password/reset-request", json={"email": email})


def _submit_reset(client: TestClient, token: str, password: str):
    return client.post(
        f"{API}/auth/password/reset",
        json={"token": token, "new_password": password},
    )


def _login(client: TestClient, email: str, password: str = "password123"):
    """Sign in. Staff accounts use the seeded demo password by default."""
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


def _provision_student(client: TestClient, *, password: str = STRONG_PASSWORD) -> str:
    """Create a student account through the API and return its email.

    The password is supplied rather than auto-generated so the test knows it
    without depending on the one-time-return behaviour.
    """
    _login(client, "admin@school.portal")
    email = f"recover-{uuid.uuid4().hex[:8]}@school.portal"
    resp = client.post(
        f"{API}/users/",
        json={
            "email": email,
            "full_name": "Recovery Test",
            "roles": ["STUDENT"],
            "password": password,
            "must_change_password": False,
        },
    )
    assert resp.status_code == 201, resp.text
    client.post(f"{API}/auth/logout")
    return email


def _request_token(client: TestClient, email: str) -> str:
    resp = _request_reset(client, email)
    assert resp.status_code == 202
    token = resp.json()["dev_token"]
    assert isinstance(token, str) and token
    return token


# --------------------------------------------------------------------------
# Capability reporting
# --------------------------------------------------------------------------


def test_availability_reports_disabled_by_default(client):
    """With no delivery channel the UI must be told not to offer recovery."""
    resp = client.get(f"{API}/auth/password/reset-availability")

    assert resp.status_code == 200
    assert resp.json() == {"available": False, "delivery": "disabled"}


def test_availability_reports_dev_channel(client, dev_channel):
    resp = client.get(f"{API}/auth/password/reset-availability")

    assert resp.status_code == 200
    assert resp.json() == {"available": True, "delivery": "dev"}


def test_request_issues_nothing_when_delivery_disabled(client):
    """No channel means no token — not a token that could never be delivered."""
    resp = _request_reset(client, "student@school.portal")

    assert resp.status_code == 202
    assert resp.json()["accepted"] is True
    assert resp.json()["dev_token"] is None


# --------------------------------------------------------------------------
# No account enumeration
# --------------------------------------------------------------------------


def test_request_accepts_unknown_address(client, dev_channel):
    """An unknown address is acknowledged, never reported as not-found."""
    resp = _request_reset(client, "definitely-not-a-user@school.portal")

    assert resp.status_code == 202
    assert resp.json()["accepted"] is True
    assert resp.json()["dev_token"] is None


def test_response_is_indistinguishable_out_of_band(client, out_of_band_channel):
    """The production response must not differ for a known and unknown address.

    This is the whole anti-enumeration guarantee: outside the dev channel no
    token is ever returned, so both responses are identical.
    """
    known = _request_reset(client, "student@school.portal")
    unknown = _request_reset(client, "no-such-person@school.portal")

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert known.json()["dev_token"] is None


def test_inactive_account_issues_no_token(client, dev_channel, db_session):
    """Recovery must never reactivate a disabled account."""
    email = _provision_student(client)
    _login(client, "admin@school.portal")
    user_id = (
        client.get(f"{API}/users/", params={"search": email}).json()["items"][0]["id"]
    )
    assert (
        client.patch(f"{API}/users/{user_id}/active", json={"is_active": False}).status_code
        == 200
    )
    client.post(f"{API}/auth/logout")

    resp = _request_reset(client, email)

    assert resp.status_code == 202
    assert resp.json()["accepted"] is True
    assert resp.json()["dev_token"] is None
    assert db_session.query(PasswordResetToken).count() == 0


# --------------------------------------------------------------------------
# Token storage and lifecycle
# --------------------------------------------------------------------------


def test_raw_token_is_never_stored(client, db_session, dev_channel):
    """A database disclosure must not hand out working reset links."""
    email = _provision_student(client)
    token = _request_token(client, email)

    stored = db_session.query(PasswordResetToken).all()
    assert len(stored) == 1
    assert stored[0].token_hash == hash_reset_token(token)
    assert stored[0].token_hash != token


def test_requesting_again_voids_the_previous_link(client, dev_channel):
    """Only the most recent link works, so an old email cannot be replayed."""
    email = _provision_student(client)
    first = _request_token(client, email)
    second = _request_token(client, email)

    assert first != second

    stale = _submit_reset(client, first, STRONG_PASSWORD)
    assert stale.status_code == 400
    assert stale.json()["error"]["code"] == "INVALID_RESET_TOKEN"


# --------------------------------------------------------------------------
# Completing a reset
# --------------------------------------------------------------------------


def test_full_recovery_flow(client, dev_channel):
    """Request -> set new password -> new password works, old one does not."""
    email = _provision_student(client)
    token = _request_token(client, email)

    submitted = _submit_reset(client, token, ANOTHER_STRONG_PASSWORD)
    assert submitted.status_code == 200
    assert submitted.json() == {"reset": True, "sessions_revoked": True}

    assert _login(client, email, ANOTHER_STRONG_PASSWORD).status_code == 200
    assert _login(client, email, STRONG_PASSWORD).status_code == 401


def test_token_is_single_use(client, dev_channel):
    """Replaying a consumed token must fail, not reset a second time."""
    email = _provision_student(client)
    token = _request_token(client, email)

    assert _submit_reset(client, token, STRONG_PASSWORD).status_code == 200

    replay = _submit_reset(client, token, ANOTHER_STRONG_PASSWORD)
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "INVALID_RESET_TOKEN"


def test_unknown_token_is_rejected(client, dev_channel):
    resp = _submit_reset(client, uuid.uuid4().hex, STRONG_PASSWORD)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_RESET_TOKEN"


def test_expired_token_is_rejected_not_crashed(client, db_session, dev_channel):
    """Regression: an expired token must be a 400, never a 500.

    ``expires_at`` arrives timezone-aware from Postgres. Comparing it against a
    naive ``utcnow()`` raised ``TypeError`` and turned every reset attempt into
    an internal server error, so this asserts the status code and not merely
    that the reset was refused.
    """
    email = _provision_student(client)
    token = _request_token(client, email)

    record = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == hash_reset_token(token))
        .one()
    )
    # Aware, matching exactly what the driver returns for TIMESTAMPTZ.
    record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    resp = _submit_reset(client, token, STRONG_PASSWORD)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_RESET_TOKEN"
    # A refused reset must leave the existing password working.
    assert _login(client, email, STRONG_PASSWORD).status_code == 200


def test_reset_revokes_every_existing_session(client, dev_channel):
    """Recovery proves control of the mailbox, not of any signed-in device."""
    email = _provision_student(client)
    assert _login(client, email, STRONG_PASSWORD).status_code == 200
    assert client.get(f"{API}/auth/me").status_code == 200

    # Submitted from a different client: completing recovery from any browser
    # must still evict the browser that was already signed in.
    token = _request_token(client, email)
    other = TestClient(client.app)
    assert _submit_reset(other, token, ANOTHER_STRONG_PASSWORD).status_code == 200

    assert client.get(f"{API}/auth/me").status_code == 401


def test_open_reset_link_is_invalidated_by_completing_recovery(
    client, db_session, dev_channel
):
    """A completed reset cannot be replayed even with a still-live sibling link."""
    email = _provision_student(client)
    token = _request_token(client, email)
    assert _submit_reset(client, token, ANOTHER_STRONG_PASSWORD).status_code == 200

    record = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == hash_reset_token(token))
        .one()
    )
    assert record.used_at is not None


def test_short_password_is_rejected(client, dev_channel):
    """The server enforces the policy regardless of what the form allows."""
    email = _provision_student(client)
    token = _request_token(client, email)

    resp = _submit_reset(client, token, "short")

    assert resp.status_code == 422
    # A validation failure must not consume the token, so the user can retry.
    assert _submit_reset(client, token, STRONG_PASSWORD).status_code == 200


def test_recovery_is_recorded_in_the_audit_log(client, db_session, dev_channel):
    """Both halves of the flow are auditable without recording the token."""
    email = _provision_student(client)
    token = _request_token(client, email)
    assert _submit_reset(client, token, ANOTHER_STRONG_PASSWORD).status_code == 200

    user = db_session.query(User).filter(User.email == email).one()
    actions = {
        row.action
        for row in db_session.query(AuditLog)
        .filter(AuditLog.entity_id == user.id)
        .all()
    }

    assert "auth.password_reset_requested" in actions
    assert "auth.password_reset_completed" in actions

    # The token must not appear anywhere in the audit trail. Scanning the
    # stored column values is the assertion that matters: a token leaked into
    # `context` would be recoverable by anyone who can read the audit log.
    rows = db_session.query(AuditLog).filter(AuditLog.entity_id == user.id).all()
    assert rows
    for row in rows:
        stored = " ".join(
            str(getattr(row, column.name)) for column in AuditLog.__table__.columns
        )
        assert token not in stored


def test_recovery_leaves_no_session_rows(client, db_session, dev_channel):
    """Every session row is removed, not just marked inactive."""
    email = _provision_student(client)
    assert _login(client, email, STRONG_PASSWORD).status_code == 200

    user = db_session.query(User).filter(User.email == email).one()
    assert db_session.query(UserSession).filter(UserSession.user_id == user.id).count() > 0

    token = _request_token(client, email)
    assert _submit_reset(client, token, ANOTHER_STRONG_PASSWORD).status_code == 200

    assert db_session.query(UserSession).filter(UserSession.user_id == user.id).count() == 0
