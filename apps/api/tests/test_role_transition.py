"""Teacher -> Management -> Teacher regression coverage.

The transition must preserve staff identity and teaching assignments, but it
must not preserve the old browser privilege set. These tests exercise the real
database state, session invalidation, student scope and authorization
boundaries in sequence.
"""

from __future__ import annotations

import uuid

from app.models.academic import TeacherAssignment
from app.models.identity import Staff, User

API = "/api/v1"


def _login(client, email: str) -> None:
    response = client.post(
        f"{API}/auth/login", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text


def _logout(client) -> None:
    client.post(f"{API}/auth/logout")


def _teacher_state(db_session) -> dict:
    user = (
        db_session.query(User)
        .filter(User.email == "teacher@school.portal")
        .one()
    )
    staff = db_session.query(Staff).filter(Staff.user_id == user.id).one()
    assignments = (
        db_session.query(TeacherAssignment)
        .filter(TeacherAssignment.staff_id == staff.id)
        .order_by(TeacherAssignment.class_section_id)
        .all()
    )
    return {
        "roles": sorted(role.name for role in user.roles),
        "staff_id": staff.id,
        "staff_active": staff.is_active,
        "assignments": [
            (assignment.class_section_id, assignment.is_active, assignment.role)
            for assignment in assignments
        ],
    }


def _student_ids(client) -> list[str]:
    response = client.get(f"{API}/students/?page_size=100")
    assert response.status_code == 200, response.text
    return sorted(item["id"] for item in response.json()["items"])


def _change_roles(client, user_id, roles: list[str], reason: str) -> None:
    response = client.patch(
        f"{API}/users/{user_id}/roles",
        json={"roles": roles, "reason": reason},
    )
    assert response.status_code == 200, response.text


def test_teacher_management_teacher_restores_scope_without_stale_session(
    client, db_session
):
    _login(client, "admin@school.portal")
    teacher = (
        db_session.query(User)
        .filter(User.email == "teacher@school.portal")
        .one()
    )
    before = _teacher_state(db_session)

    # A student who is deliberately outside the teacher's class roster.
    suffix = uuid.uuid4().hex[:10]
    outsider_response = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": f"RT-{suffix}",
            "first_name": "Role",
            "last_name": suffix,
            "email": f"role-transition-{suffix}@test.local",
        },
    )
    assert outsider_response.status_code == 201, outsider_response.text
    outsider_id = outsider_response.json()["student"]["id"]

    _login(client, "teacher@school.portal")
    teacher_cookie = client.cookies.get("session_token")
    assert teacher_cookie
    baseline_students = _student_ids(client)
    assert baseline_students
    assert outsider_id not in baseline_students
    assert client.get(f"{API}/students/{baseline_students[0]}").status_code == 200
    assert client.get(f"{API}/students/{outsider_id}").status_code == 403

    # Teacher -> Management.
    _login(client, "admin@school.portal")
    _change_roles(client, teacher.id, ["MANAGEMENT"], "Role transition probe")
    db_session.expire_all()
    management_state = _teacher_state(db_session)
    assert management_state["roles"] == ["MANAGEMENT"]
    assert management_state["staff_id"] == before["staff_id"]
    assert management_state["staff_active"] is True
    assert management_state["assignments"] == before["assignments"]

    # The teacher's pre-transition browser session is no longer trusted.
    client.cookies.clear()
    client.cookies.set("session_token", teacher_cookie)
    assert client.get(f"{API}/auth/me").status_code == 401

    client.cookies.clear()
    _login(client, "teacher@school.portal")
    me = client.get(f"{API}/auth/me").json()
    assert [role["name"] for role in me["roles"]] == ["MANAGEMENT"]
    management_students = _student_ids(client)
    assert outsider_id in management_students
    assert client.get(f"{API}/students/{outsider_id}").status_code == 200
    assert client.get(f"{API}/users/").status_code == 200
    management_cookie = client.cookies.get("session_token")

    # Management -> Teacher.
    _login(client, "admin@school.portal")
    _change_roles(client, teacher.id, ["TEACHER"], "Return to teaching")
    db_session.expire_all()
    after = _teacher_state(db_session)
    assert after["roles"] == ["TEACHER"]
    assert after["staff_id"] == before["staff_id"]
    assert after["staff_active"] is True
    assert after["assignments"] == before["assignments"]

    client.cookies.clear()
    client.cookies.set("session_token", management_cookie)
    assert client.get(f"{API}/auth/me").status_code == 401

    client.cookies.clear()
    _login(client, "teacher@school.portal")
    me = client.get(f"{API}/auth/me").json()
    assert [role["name"] for role in me["roles"]] == ["TEACHER"]
    assert _student_ids(client) == baseline_students
    assert client.get(f"{API}/students/{baseline_students[0]}").status_code == 200
    assert client.get(f"{API}/students/{outsider_id}").status_code == 403
    assert client.get(f"{API}/users/").status_code == 403

    # An inactive staff record must not regain the teacher scope just because
    # the account still carries the TEACHER role.
    staff = db_session.query(Staff).filter(Staff.id == before["staff_id"]).one()
    staff.is_active = False
    db_session.commit()
    assert _student_ids(client) == []
    assert client.get(f"{API}/students/{baseline_students[0]}").status_code == 403
    staff.is_active = True
    db_session.commit()

    # Both transitions remain audited, and each records the session revocation.
    _login(client, "admin@school.portal")
    audit = client.get(
        f"{API}/audit",
        params={"action": "account.roles_changed", "entity_id": teacher.id},
    )
    assert audit.status_code == 200
    entries = [
        item
        for item in audit.json()["items"]
        if item["entity_id"] == str(teacher.id)
    ]
    assert len(entries) >= 2
    assert entries[0]["context"]["from"] == ["MANAGEMENT"]
    assert entries[0]["context"]["to"] == ["TEACHER"]
    assert entries[0]["context"]["logins_revoked"] >= 1
    assert entries[1]["context"]["from"] == ["TEACHER"]
    assert entries[1]["context"]["to"] == ["MANAGEMENT"]
