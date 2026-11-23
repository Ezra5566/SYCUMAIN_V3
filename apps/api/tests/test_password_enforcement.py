"""Forced password change, enforced by the server.

A temporary password is issued so an administrator can hand an account over
without knowing the account holder's password. Until it is replaced, the
account must not be able to read announcements, student records, documents or
anything else: a client-side prompt is not a control, because the same session
cookie can call the API directly.

These tests drive the API, not the UI, precisely because the interesting
failure mode is someone bypassing the UI.
"""

import uuid

from fastapi.testclient import TestClient

from app.auth.dependencies import password_change_path_allowed

API = "/api/v1"
STRONG_PASSWORD = "Str0ng-Passphrase!42"


def _login(client: TestClient, email: str, password: str):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


def _provision_with_temporary_password(client: TestClient) -> tuple[str, str]:
    """Create a student account and return its email and temporary password."""
    assert _login(client, "admin@school.portal", "password123").status_code == 200
    email = f"temp-{uuid.uuid4().hex[:8]}@school.portal"
    created = client.post(
        f"{API}/users/",
        json={"email": email, "full_name": "Temporary Credential", "roles": ["STUDENT"]},
    )
    assert created.status_code == 201, created.text
    temporary_password = created.json()["temporary_password"]
    assert temporary_password

    client.post(f"{API}/auth/logout")
    return email, temporary_password


def test_temporary_credentials_cannot_reach_normal_apis(client):
    """The audit finding: announcements and the student record were readable."""
    email, temporary_password = _provision_with_temporary_password(client)

    signed_in = _login(client, email, temporary_password)
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["must_change_password"] is True

    for path in (
        f"{API}/announcements",
        f"{API}/students/me",
        f"{API}/students",
        f"{API}/documents",
        f"{API}/users/",
    ):
        response = client.get(path)
        assert response.status_code == 403, f"{path} was reachable: {response.text}"
        assert response.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_minimum_operations_remain_available(client):
    """The account must be able to inspect itself and finish the change."""
    email, temporary_password = _provision_with_temporary_password(client)
    assert _login(client, email, temporary_password).status_code == 200

    assert client.get(f"{API}/auth/me").status_code == 200
    assert client.get(f"{API}/auth/sessions").status_code == 200

    changed = client.post(
        f"{API}/auth/password/change",
        json={
            "current_password": temporary_password,
            "new_password": STRONG_PASSWORD,
        },
    )
    assert changed.status_code == 200, changed.text


def test_change_lifts_the_restriction_and_retires_the_temporary_password(client):
    email, temporary_password = _provision_with_temporary_password(client)
    assert _login(client, email, temporary_password).status_code == 200

    changed = client.post(
        f"{API}/auth/password/change",
        json={
            "current_password": temporary_password,
            "new_password": STRONG_PASSWORD,
        },
    )
    assert changed.status_code == 200

    # The same session is now a normal session.
    assert client.get(f"{API}/announcements").status_code == 200
    assert client.get(f"{API}/auth/me").json()["must_change_password"] is False

    client.post(f"{API}/auth/logout")

    # The temporary credential is dead; the chosen one works.
    assert _login(client, email, temporary_password).status_code == 401
    relogin = _login(client, email, STRONG_PASSWORD)
    assert relogin.status_code == 200
    assert relogin.json()["user"]["must_change_password"] is False


def test_change_revokes_sessions_that_still_hold_the_temporary_password(client):
    """A second device signed in with the temporary password must be evicted."""
    email, temporary_password = _provision_with_temporary_password(client)

    other_device = TestClient(client.app)
    assert _login(other_device, email, temporary_password).status_code == 200
    assert other_device.get(f"{API}/auth/me").status_code == 200

    assert _login(client, email, temporary_password).status_code == 200
    changed = client.post(
        f"{API}/auth/password/change",
        json={
            "current_password": temporary_password,
            "new_password": STRONG_PASSWORD,
        },
    )
    assert changed.status_code == 200
    assert changed.json()["sessions_revoked"] >= 1

    assert other_device.get(f"{API}/auth/me").status_code == 401


def test_allowed_path_matching_is_exact(client):
    """Prefix matching would turn ``/auth/me`` into every ``/auth/me...`` path."""
    assert password_change_path_allowed("/api/v1/auth/me")
    assert password_change_path_allowed("/api/v1/auth/me/")
    assert password_change_path_allowed("/api/v1/auth/password/change")
    assert password_change_path_allowed("/api/v1/auth/sessions/revoke-others")

    assert not password_change_path_allowed("/api/v1/students/me")
    assert not password_change_path_allowed("/api/v1/auth/me/export")
    assert not password_change_path_allowed("/api/v1/announcements")


def test_restriction_does_not_apply_to_accounts_that_can_already_sign_in(client):
    """Normal staff accounts are unaffected by the control."""
    assert _login(client, "management@school.portal", "password123").status_code == 200
    assert client.get(f"{API}/announcements").status_code == 200
