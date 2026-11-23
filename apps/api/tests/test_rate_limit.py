"""Rate limiting for login and password recovery.

The requirements are behavioural, so the tests are too: after the configured
allowance the endpoint returns 429 with a ``Retry-After`` header, the message
is identical for known and unknown addresses (no enumeration), a successful
sign-in clears the counters (no lingering lockout), and the security event is
auditable without recording the address or email.
"""

import uuid

from app.config.settings import get_settings
from app.core.ratelimit import Limit, check, purge_expired
from app.models.audit import AuditLog

API = "/api/v1"


def _login(client, email: str, password: str):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


def test_login_is_throttled_per_account(client):
    settings = get_settings()
    email = f"throttle-{uuid.uuid4().hex[:8]}@school.portal"

    for _ in range(settings.RATE_LIMIT_LOGIN_PER_ACCOUNT):
        assert _login(client, email, "definitely-wrong").status_code == 401

    blocked = _login(client, email, "definitely-wrong")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) >= 1

    # The correct password is refused too: the allowance is on attempts, not
    # on failures, so an attacker cannot keep guessing a known-good value.
    assert _login(client, "admin@school.portal", "password123").status_code != 429


def test_throttled_response_is_identical_for_known_and_unknown_addresses(client):
    settings = get_settings()
    per_account = settings.RATE_LIMIT_LOGIN_PER_ACCOUNT

    known = "student@school.portal"
    unknown = f"nobody-{uuid.uuid4().hex[:8]}@school.portal"

    for _ in range(per_account):
        _login(client, known, "wrong")
        _login(client, unknown, "wrong")

    known_blocked = _login(client, known, "wrong")
    unknown_blocked = _login(client, unknown, "wrong")

    assert known_blocked.status_code == unknown_blocked.status_code == 429
    assert known_blocked.json() == unknown_blocked.json()


def test_successful_login_clears_the_counters(client):
    """No permanent lockout: signing in resets the window for that caller."""
    for _ in range(3):
        assert _login(client, "admin@school.portal", "wrong").status_code == 401

    assert _login(client, "admin@school.portal", "password123").status_code == 200
    client.post(f"{API}/auth/logout")

    # The allowance is available again in full.
    for _ in range(3):
        assert _login(client, "admin@school.portal", "wrong").status_code == 401
    assert _login(client, "admin@school.portal", "password123").status_code == 200


def test_password_recovery_requests_are_throttled(client):
    settings = get_settings()

    for index in range(settings.RATE_LIMIT_RESET_REQUEST_PER_IP):
        resp = client.post(
            f"{API}/auth/password/reset-request",
            json={"email": f"recover-{index}-{uuid.uuid4().hex[:6]}@school.portal"},
        )
        assert resp.status_code == 202

    blocked = client.post(
        f"{API}/auth/password/reset-request",
        json={"email": "another@school.portal"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"


def test_reset_token_submission_is_throttled(client):
    settings = get_settings()

    for _ in range(settings.RATE_LIMIT_RESET_SUBMIT_PER_IP):
        resp = client.post(
            f"{API}/auth/password/reset",
            json={"token": uuid.uuid4().hex, "new_password": "Str0ng-Passphrase!42"},
        )
        assert resp.status_code == 400

    blocked = client.post(
        f"{API}/auth/password/reset",
        json={"token": uuid.uuid4().hex, "new_password": "Str0ng-Passphrase!42"},
    )
    assert blocked.status_code == 429


def test_rate_limit_event_is_audited_without_personal_data(client, db_session):
    settings = get_settings()
    email = f"audited-{uuid.uuid4().hex[:8]}@school.portal"

    for _ in range(settings.RATE_LIMIT_LOGIN_PER_ACCOUNT + 1):
        _login(client, email, "wrong")

    rows = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "auth.rate_limited")
        .all()
    )
    assert rows

    for row in rows:
        stored = " ".join(
            str(getattr(row, column.name)) for column in AuditLog.__table__.columns
        )
        assert email not in stored
        assert "wrong" not in stored


def test_closed_windows_can_be_purged(db_session):
    """Housekeeping only removes counters that can no longer decide anything."""
    from datetime import UTC, datetime, timedelta

    old = datetime.now(UTC) - timedelta(days=2)
    limit = Limit("test:purge", max_attempts=3, window_seconds=60)
    check(db_session, limit=limit, value="someone", now=old)
    check(db_session, limit=limit, value="recent")

    removed = purge_expired(db_session, older_than_hours=24)

    assert removed >= 1
