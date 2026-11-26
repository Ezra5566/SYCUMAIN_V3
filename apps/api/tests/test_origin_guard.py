"""Cross-site request protection for unsafe methods (app/core/origin.py).

The suite pins ``CORS_ORIGINS`` to ``http://localhost:3100`` (see conftest), so
that is the trusted origin here. These tests are about the *policy*, not about a
particular endpoint: logout and a role change are used because they are real
state-changing routes that require a session.
"""

from fastapi.testclient import TestClient

from app.auth.dependencies import SESSION_COOKIE_NAME

TRUSTED = "http://localhost:3100"
FOREIGN = "https://evil.example"
REJECTION_CODE = "CSRF_ORIGIN_REJECTED"
ADMIN = "admin@school.portal"


def _login(client: TestClient, origin: str | None = None):
    headers = {"Origin": origin} if origin else {}
    return client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN, "password": "password123"},
        headers=headers,
    )


def test_login_from_trusted_origin_is_allowed(client: TestClient):
    response = _login(client, TRUSTED)

    assert response.status_code == 200
    assert SESSION_COOKIE_NAME in client.cookies


def test_login_from_foreign_origin_is_rejected(client: TestClient):
    response = _login(client, FOREIGN)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == REJECTION_CODE
    # A rejected request must not authenticate as a side effect.
    assert SESSION_COOKIE_NAME not in client.cookies


def test_signed_in_write_from_trusted_origin_succeeds(client: TestClient):
    assert _login(client).status_code == 200

    logout = client.post("/api/v1/auth/logout", headers={"Origin": TRUSTED})

    assert logout.status_code == 200
    # The session was really invalidated, not merely answered.
    assert client.get("/api/v1/auth/me").status_code == 401


def test_foreign_origin_cannot_log_out_a_signed_in_user(client: TestClient):
    """The reported defect: a cross-site page must not end someone's session."""
    assert _login(client).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200

    logout = client.post("/api/v1/auth/logout", headers={"Origin": FOREIGN})

    assert logout.status_code == 403
    assert logout.json()["error"]["code"] == REJECTION_CODE
    # Still signed in: the hostile request changed nothing.
    assert client.get("/api/v1/auth/me").status_code == 200


def test_foreign_origin_cannot_change_a_role(client: TestClient):
    assert _login(client).status_code == 200
    me = client.get("/api/v1/auth/me").json()
    target = me["id"]

    response = client.patch(
        f"/api/v1/users/{target}/roles",
        json={"roles": ["STUDENT"]},
        headers={"Origin": FOREIGN},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == REJECTION_CODE


def test_missing_origin_is_allowed_for_non_browser_clients(client: TestClient):
    """curl, the browser suite and integrations send no Origin; they still work."""
    assert client.get("/api/v1/health").status_code == 200
    assert _login(client).status_code == 200

    logout = client.post("/api/v1/auth/logout")

    assert logout.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_cross_site_fetch_metadata_without_origin_is_rejected(client: TestClient):
    assert _login(client).status_code == 200

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


def test_cross_origin_referer_without_origin_is_rejected(client: TestClient):
    assert _login(client).status_code == 200

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Referer": f"{FOREIGN}/phish"},
    )

    assert response.status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


def test_same_origin_referer_without_origin_is_allowed(client: TestClient):
    assert _login(client).status_code == 200

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Referer": f"{TRUSTED}/en/app"},
    )

    assert logout.status_code == 200


def test_null_origin_is_rejected(client: TestClient):
    """Sandboxed frames and file:// documents send the literal ``null``."""
    response = _login(client, "null")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == REJECTION_CODE


def test_trailing_slash_in_origin_still_matches(client: TestClient):
    response = _login(client, f"{TRUSTED}/")

    assert response.status_code == 200


def test_foreign_origin_is_rejected_before_authentication(client: TestClient):
    """No session at all: the guard answers, not the auth layer."""
    response = client.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000/roles",
        json={"roles": ["STUDENT"]},
        headers={"Origin": FOREIGN},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == REJECTION_CODE


def test_safe_methods_are_not_blocked(client: TestClient):
    """Reads stay readable cross-origin; CORS (not this guard) governs them."""
    response = client.get("/api/v1/health", headers={"Origin": FOREIGN})

    assert response.status_code == 200
