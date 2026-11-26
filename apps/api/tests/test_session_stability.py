"""Session stability and cookie isolation.

The portal is demonstrated next to the V1 reference installation on the same
host (V1 on :8000, V3 on :8001). Cookies are scoped by host and ignore the
port, so two applications that both call their cookie ``session_token`` share a
single slot: signing in to one silently replaces the other's session. The
symptom is not a clean sign-out — the client still believes it is authenticated
while every request answers 401, until the user signs out and in again.

These tests pin the three properties that prevent it:

1. the cookie is namespaced and does not answer to the other installation's
   name;
2. a live session survives repeated requests (nothing invalidates it as a side
   effect of ordinary navigation), while an expired or revoked one is refused
   with a controlled 401;
3. the ``last_accessed_at`` write is throttled, so request bursts do not queue
   on one row (the behaviour that made requests stall under load).
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.auth.dependencies import SESSION_COOKIE_NAME
from app.auth.service import hash_token
from app.models.session import UserSession

API = "/api/v1"
ADMIN = "admin@school.portal"
PASSWORD = "password123"
#: The name V1 uses. It must never authenticate against this API.
LEGACY_COOKIE_NAME = "session_token"


def _login(client: TestClient) -> str:
    response = client.post(
        f"{API}/auth/login", json={"email": ADMIN, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.cookies[SESSION_COOKIE_NAME]


def _session_for(db, token: str) -> UserSession:
    """Read the session row through the test's own database session.

    The ``client`` fixture binds the application to ``db_session`` inside one
    outer transaction, so a separate connection would not see rows the request
    wrote (and could not change them for the next request to observe).
    """
    db.expire_all()
    return (
        db.query(UserSession)
        .filter(UserSession.token_hash == hash_token(token))
        .one()
    )


def test_login_issues_the_namespaced_cookie_only(client: TestClient) -> None:
    response = client.post(
        f"{API}/auth/login", json={"email": ADMIN, "password": PASSWORD}
    )

    assert response.status_code == 200
    assert SESSION_COOKIE_NAME in response.cookies
    # The previous name must not be issued: a browser that visits the other
    # installation on this host would otherwise overwrite it (and be
    # overwritten in turn).
    assert LEGACY_COOKIE_NAME not in response.cookies


def test_a_foreign_cookie_name_does_not_authenticate(client: TestClient) -> None:
    """Simulates V1's cookie being the only one present in the browser."""
    client.cookies.clear()
    client.cookies.set(LEGACY_COOKIE_NAME, "whatever-v1-issued")

    response = client.get(f"{API}/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Cookie"


def test_a_live_session_survives_repeated_requests(client: TestClient) -> None:
    """Ordinary navigation must never invalidate the session as a side effect."""
    _login(client)

    for _ in range(6):
        response = client.get(f"{API}/auth/me")
        assert response.status_code == 200, response.text
        assert response.json()["email"] == ADMIN


def test_expired_session_answers_a_controlled_401(
    client: TestClient, db_session
) -> None:
    token = _login(client)
    session = _session_for(db_session, token)

    session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    response = client.get(f"{API}/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_logout_invalidates_the_session_server_side(client: TestClient) -> None:
    token = _login(client)

    logout = client.post(f"{API}/auth/logout")
    assert logout.status_code == 200

    # Even if the cookie is replayed (a copied request, another tab that had not
    # reloaded), the session is gone: the row was deleted, not merely cleared
    # from this client's jar.
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, token)

    assert client.get(f"{API}/auth/me").status_code == 401


def test_last_accessed_write_is_throttled(
    client: TestClient, db_session
) -> None:
    """Two requests in the same minute must not both UPDATE the session row."""
    token = _login(client)

    assert client.get(f"{API}/auth/me").status_code == 200
    first = _session_for(db_session, token).last_accessed_at

    assert client.get(f"{API}/auth/me").status_code == 200
    second = _session_for(db_session, token).last_accessed_at

    assert first == second, "a request inside the throttle window rewrote the row"

    # Once the stored value is stale, the next request refreshes it, so the
    # active-sessions screen still reports a meaningful time.
    stale = _session_for(db_session, token)
    stale.last_accessed_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.commit()

    assert client.get(f"{API}/auth/me").status_code == 200
    assert _session_for(db_session, token).last_accessed_at > first
