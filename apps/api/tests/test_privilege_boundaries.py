"""Privilege boundaries around account administration.

Management holds ``users.manage_students`` so it can onboard students. The
boundary that matters is that this cannot be turned into staff or administrator
access — not by assigning a role, and not by sending a field the schema does not
recognise.
"""

from __future__ import annotations

import uuid

from app.models.identity import User


def _login(client, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text


def _payload(**overrides):
    body = {
        "email": f"boundary.{uuid.uuid4().hex[:8]}@school.portal",
        "full_name": "Boundary Probe",
        "roles": ["STUDENT"],
    }
    body.update(overrides)
    return body


def test_management_cannot_create_an_admin(client, db_session):
    before = db_session.query(User).count()
    _login(client, "management@school.portal")
    response = client.post("/api/v1/users/", json=_payload(roles=["ADMIN"]))
    assert response.status_code == 403, response.text
    db_session.expire_all()
    assert db_session.query(User).count() == before


def test_management_cannot_grant_staff_roles(client, db_session):
    for role in ("TEACHER", "MANAGEMENT"):
        _login(client, "management@school.portal")
        response = client.post("/api/v1/users/", json=_payload(roles=[role]))
        assert response.status_code == 403, (role, response.text)


def test_unknown_role_field_is_rejected_not_ignored(client, db_session):
    """`role_names` used to be dropped silently and a STUDENT was created."""
    _login(client, "management@school.portal")
    payload = _payload()
    payload["role_names"] = ["ADMIN"]
    response = client.post("/api/v1/users/", json=payload)
    assert response.status_code == 422, response.text
    db_session.expire_all()
    assert (
        db_session.query(User).filter(User.email == payload["email"]).first() is None
    )


def test_management_can_create_a_student_account(client, db_session):
    _login(client, "management@school.portal")
    payload = _payload()
    response = client.post("/api/v1/users/", json=payload)
    assert response.status_code == 201, response.text
    assert [r["name"] for r in response.json()["account"]["roles"]] == ["STUDENT"]


def test_management_cannot_change_an_administrators_roles(client, db_session):
    admin = db_session.query(User).filter(User.email == "admin@school.portal").one()
    _login(client, "management@school.portal")
    response = client.patch(
        f"/api/v1/users/{admin.id}/roles",
        json={"roles": ["ADMIN", "MANAGEMENT"], "reason": "boundary probe"},
    )
    assert response.status_code == 403, response.text


def test_teachers_and_students_cannot_create_accounts(client):
    for email in ("teacher@school.portal", "student@school.portal"):
        _login(client, email)
        response = client.post("/api/v1/users/", json=_payload())
        assert response.status_code == 403, (email, response.text)


def test_admin_can_create_an_admin(client):
    """The boundary must not block the role that owns it."""
    _login(client, "admin@school.portal")
    response = client.post("/api/v1/users/", json=_payload(roles=["ADMIN"]))
    assert response.status_code == 201, response.text
    assert [r["name"] for r in response.json()["account"]["roles"]] == ["ADMIN"]
