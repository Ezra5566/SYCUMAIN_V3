"""Authorization regression tests for the single student scope policy.

The extensibility audit found two contradictory implementations: a real,
database-aware rule in `app.permissions.scope`, and an exported `policy.py`
whose teacher branches returned ``True`` ("placeholder — full access for now").
This module pins the surviving rule at both levels — the resolver and the HTTP
endpoints — so a future module cannot re-introduce a permissive default without
a failing test.
"""

from __future__ import annotations

import importlib.util
import uuid
from typing import TYPE_CHECKING

import pytest

import app.permissions as permissions_pkg
from app.database.session import SessionLocal
from app.models.identity import Student, User
from app.permissions import scope
from app.seed_academic import seed_academic

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

API = "/api/v1"


@pytest.fixture(scope="module", autouse=True)
def academic_seed():
    """Class sections, teacher assignments and enrolments the scope needs.

    Committed rather than seeded inside the test transaction: the application
    seeds on startup from a second connection.
    """
    db = SessionLocal()
    try:
        seed_academic(db)
    finally:
        db.close()


def _login(client: TestClient, email: str) -> TestClient:
    resp = client.post(
        f"{API}/auth/login", json={"email": email, "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return client


def _user(db_session, email: str) -> User:
    return db_session.query(User).filter(User.email == email).one()


def _onboard_stranger(client: TestClient) -> str:
    """Create a student with no enrolments, so no teacher can reach them."""
    suffix = uuid.uuid4().hex[:8]
    resp = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": f"SCP{suffix.upper()}",
            "first_name": "Scope",
            "last_name": "Probe",
            "email": f"scope{suffix}@example.com",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["student"]["id"]


# --- The policy surface itself ---


def test_no_second_policy_module_is_importable():
    """The removed placeholder module must not come back under a new name."""
    assert importlib.util.find_spec("app.permissions.policy") is None
    for removed in ("can_view_student", "can_edit_student", "get_accessible_student_ids"):
        assert not hasattr(permissions_pkg, removed), removed


def test_management_roles_are_unrestricted(db_session):
    for email in ("admin@school.portal", "management@school.portal"):
        assert scope.accessible_student_ids(db_session, _user(db_session, email)) is None


def test_teacher_scope_is_their_own_rosters(client, db_session):
    """A teacher sees their roster and nothing else — no blanket access."""
    teacher = _user(db_session, "teacher@school.portal")
    permitted = scope.accessible_student_ids(db_session, teacher)

    assert isinstance(permitted, set)
    assert permitted, "seed assigns the teacher two class sections"

    _login(client, "admin@school.portal")
    stranger_id = uuid.UUID(_onboard_stranger(client))

    assert stranger_id not in permitted
    assert scope.can_access_student(db_session, teacher, stranger_id) is False
    assert scope.can_access_student(db_session, teacher, next(iter(permitted))) is True


def test_student_scope_is_own_record_only(client, db_session):
    student_user = _user(db_session, "student@school.portal")
    own = db_session.query(Student).filter(Student.user_id == student_user.id).one()

    assert scope.accessible_student_ids(db_session, student_user) == {own.id}

    _login(client, "admin@school.portal")
    stranger_id = uuid.UUID(_onboard_stranger(client))
    assert scope.can_access_student(db_session, student_user, stranger_id) is False


def test_unrecognized_role_gets_no_students(db_session):
    """A new role does not inherit access by default."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        email=f"norole-{suffix}@test.com",
        username=f"norole-{suffix}",
        hashed_password="x",
        full_name="No Role",
    )
    db_session.add(user)
    db_session.flush()

    assert scope.accessible_student_ids(db_session, user) == set()
    assert scope.can_access_student(db_session, user, uuid.uuid4()) is False


# --- The HTTP surface ---


def test_teacher_can_read_assigned_but_not_unassigned(client, db_session):
    teacher = _user(db_session, "teacher@school.portal")
    permitted = scope.accessible_student_ids(db_session, teacher)
    assigned = next(iter(permitted))

    _login(client, "admin@school.portal")
    stranger_id = _onboard_stranger(client)

    _login(client, "teacher@school.portal")
    assert client.get(f"{API}/students/{assigned}").status_code == 200

    denied = client.get(f"{API}/students/{stranger_id}")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"


def test_teacher_directory_is_limited_to_their_scope(client, db_session):
    teacher = _user(db_session, "teacher@school.portal")
    permitted = {
        str(student_id) for student_id in scope.accessible_student_ids(db_session, teacher)
    }

    _login(client, "teacher@school.portal")
    resp = client.get(f"{API}/students/?page_size=100")
    assert resp.status_code == 200, resp.text

    returned = {item["id"] for item in resp.json()["items"]}
    assert returned, "the seeded roster is not empty"
    assert returned <= permitted


def test_student_cannot_read_another_students_record(client):
    _login(client, "admin@school.portal")
    stranger_id = _onboard_stranger(client)

    _login(client, "student@school.portal")
    own_id = client.get(f"{API}/students/me").json()["id"]
    assert client.get(f"{API}/students/{own_id}").status_code == 200

    other = client.get(f"{API}/students/{stranger_id}")
    assert other.status_code == 403
    assert other.json()["error"]["code"] == "FORBIDDEN"

    assert client.get(f"{API}/students/").status_code == 403
    assert client.get(f"{API}/documents/students/{stranger_id}/summary").status_code == 404


def test_management_can_read_any_student(client):
    _login(client, "admin@school.portal")
    stranger_id = _onboard_stranger(client)

    _login(client, "management@school.portal")
    assert client.get(f"{API}/students/{stranger_id}").status_code == 200


def test_teacher_cannot_use_management_write_path(client, db_session):
    teacher = _user(db_session, "teacher@school.portal")
    assigned = next(iter(scope.accessible_student_ids(db_session, teacher)))

    _login(client, "teacher@school.portal")
    resp = client.patch(
        f"{API}/students/{assigned}", json={"status": "GRADUATED"}
    )
    assert resp.status_code == 403


def test_sensitive_domains_require_permission_and_scope(db_session):
    """Scope alone is not enough: the domain permission must also be held."""
    teacher = _user(db_session, "teacher@school.portal")
    student_user = _user(db_session, "student@school.portal")
    admin = _user(db_session, "admin@school.portal")
    own = db_session.query(Student).filter(Student.user_id == student_user.id).one()

    for check in (scope.can_view_immigration, scope.can_view_housing):
        assert check(db_session, teacher, own.id) is False
        assert check(db_session, student_user, own.id) is True
        assert check(db_session, admin, own.id) is True
