"""Test-harness integrity: the suite must be order-independent.

The application commits inside request handlers. If the test session were bound
to a plain connection, those commits would end the fixture's outer transaction,
its `rollback()` would become a no-op, and rows would survive into every later
test. The suite would then be order-dependent and, worse, a run killed
mid-flight would poison the next run — which is exactly how eight unrelated
tests once failed purely because an earlier run had been interrupted.

These tests pin the property that makes that impossible: anything a test writes,
including a commit performed by the application, is invisible to any other
connection and is discarded when the test ends.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.database.session import SessionLocal, get_db
from app.main import app
from app.models.academic import Major
from app.services import account as account_service

API = "/api/v1"


def _login(client: TestClient, email: str, password: str = "password123"):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


def test_an_application_commit_is_not_visible_to_another_connection(db_session):
    """A commit inside a request must not escape the test's transaction.

    This is the mechanism the whole suite relies on. If it regresses, tests
    start affecting each other and the failures look random.
    """
    unique = uuid.uuid4().hex[:8]
    code = f"ISOLATION-{unique}"

    # Write through the session the application handlers will also use.
    db_session.add(Major(code=code, name=f"Isolation {unique}"))
    db_session.commit()

    # A completely separate connection must not see it.
    other = SessionLocal()
    try:
        found = (
            other.query(Major.id).filter(Major.code == code).first()
        )
        assert found is None, (
            "committed test data leaked into the database — the suite is no "
            "longer isolated and will be order-dependent"
        )
    finally:
        other.close()


def test_api_mutation_does_not_persist_beyond_the_test(client):
    """The same property holds for writes made through the HTTP API."""
    unique = uuid.uuid4().hex[:8]
    student_number = f"STU-ISOLATION-{unique}"

    assert _login(client, "admin@school.portal").status_code == 200
    created = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": student_number,
            "first_name": "Isolation",
            "last_name": "Check",
            "email": f"isolation-{unique}@example.com",
        },
    )
    assert created.status_code == 201

    # It is visible to the request that created it...
    listed = client.get(f"{API}/students/", params={"search": student_number}).json()
    assert listed["meta"]["total"] == 1

    # ...but not to an independent connection.
    other = SessionLocal()
    try:
        count = other.execute(
            text("SELECT count(*) FROM students WHERE student_id = :n"),
            {"n": student_number},
        ).scalar()
        assert count == 0, "an onboarded student leaked out of its test"
    finally:
        other.close()


def test_deactivating_an_account_revokes_sessions(client):
    """Deactivation must not leave a usable session behind.

    Asserted through the API rather than the database so it also proves the
    revocation survives the request that performed it.
    """
    unique = uuid.uuid4().hex[:8]
    email = f"revoke-check-{unique}@example.com"

    assert _login(client, "admin@school.portal").status_code == 200
    created = client.post(
        f"{API}/users/",
        json={"email": email, "full_name": "Revoke Check", "roles": ["STUDENT"]},
    ).json()
    password = created["temporary_password"]
    account_id = created["account"]["id"]

    with TestClient(client.app) as holder:
        assert _login(holder, email, password).status_code == 200
        assert holder.get(f"{API}/auth/me").status_code == 200

        disabled = client.patch(
            f"{API}/users/{account_id}/active", json={"is_active": False}
        )
        assert disabled.status_code == 200

        assert holder.get(f"{API}/auth/me").status_code == 401


def test_account_service_hashing_never_stores_the_plaintext(db_session: DBSession):
    """Shared hashing guarantee, checked at the point of creation."""
    unique = uuid.uuid4().hex[:8]
    password = f"Plaintext-{unique}!Aa1"

    user, generated = account_service.create_account(
        db_session,
        email=f"hash-check-{unique}@example.com",
        full_name="Hash Check",
        roles=["STUDENT"],
        password=password,
    )
    assert generated is None
    assert user.hashed_password != password
    assert password not in user.hashed_password
    assert user.hashed_password.startswith("$2")


def test_login_response_is_free_of_credential_material(client):
    """Regression guard for the response shape of the identity endpoints."""
    assert _login(client, "admin@school.portal").status_code == 200

    for path in (f"{API}/auth/me",):
        payload = client.get(path).text
        assert "hashed_password" not in payload
        assert "$2" not in payload  # no bcrypt digest anywhere in the body


def test_database_override_is_cleared_between_tests():
    """A leaked dependency override would bind later tests to a stale session.

    Checks that the previous test's `client` fixture cleaned up after itself.
    """
    assert get_db not in app.dependency_overrides
