"""Authorization tests for student-scoped housing reads.

`housing.view` is held by students for self-service, so feature access alone
must never decide whether a student may read a particular student record. These
tests cover the object-scope boundary for empty and populated assignments, as
well as staff, teacher and anonymous behavior.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
    RoomStatus,
)
from app.models.identity import Role, Student, StudentStatus, User

API = "/api/v1"
STUDENT_EMAIL = "student@school.portal"
ADMIN_EMAIL = "admin@school.portal"
MANAGEMENT_EMAIL = "management@school.portal"
TEACHER_EMAIL = "teacher@school.portal"


def _login(client, email: str) -> None:
    response = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200, response.text


def _student_for_email(db, email: str = STUDENT_EMAIL) -> Student:
    user = db.query(User).filter(User.email == email).one()
    return db.query(Student).filter(Student.user_id == user.id).one()


def _other_student(db) -> Student:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"housing-auth-{suffix}@example.com",
        username=f"housing-auth-{suffix}",
        hashed_password="not-used",
        full_name="Housing Auth Student",
        is_active=True,
    )
    db.add(user)
    db.flush()

    student_role = db.query(Role).filter(Role.name == "STUDENT").first()
    if student_role:
        user.roles.append(student_role)

    student = Student(
        user_id=user.id,
        student_id=f"STU-AUTH-{suffix}",
        first_name="Other",
        last_name="Student",
        status=StudentStatus.ACTIVE,
    )
    db.add(student)
    db.flush()
    return student


def _bed(db) -> Bed:
    suffix = uuid.uuid4().hex[:8]
    building = Building(name=f"Housing Auth {suffix}")
    db.add(building)
    db.flush()

    floor = Floor(building_id=building.id, floor_number=1)
    db.add(floor)
    db.flush()

    room = Room(
        floor_id=floor.id,
        room_number="101",
        capacity=1,
        status=RoomStatus.AVAILABLE,
        is_active=True,
    )
    db.add(room)
    db.flush()

    bed = Bed(room_id=room.id, bed_number=1, label="A", is_active=True)
    db.add(bed)
    db.flush()
    return bed


def _assign(db, student: Student, bed: Bed) -> HousingAssignment:
    assignment = HousingAssignment(
        student_id=student.user_id,
        bed_id=bed.id,
        start_date=datetime.now(UTC),
        status=HousingAssignmentStatus.ACTIVE,
    )
    db.add(assignment)
    db.flush()
    return assignment


def _error_code(response) -> str | None:
    payload = response.json()
    return payload.get("error", {}).get("code")


def test_student_reads_own_empty_housing(client, db_session):
    me = _student_for_email(db_session)
    _login(client, STUDENT_EMAIL)

    response = client.get(f"{API}/housing/students/{me.id}/housing")

    assert response.status_code == 200
    assert response.json()["has_assignment"] is False
    assert response.json()["assignment"] is None


def test_student_reads_own_populated_housing(client, db_session):
    me = _student_for_email(db_session)
    assignment = _assign(db_session, me, _bed(db_session))
    _login(client, STUDENT_EMAIL)

    response = client.get(f"{API}/housing/students/{me.id}/housing")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_assignment"] is True
    assert payload["assignment"]["id"] == str(assignment.id)
    assert payload["assignment"]["bed_id"] == str(assignment.bed_id)


def test_student_cannot_read_another_students_empty_housing(client, db_session):
    other = _other_student(db_session)
    _login(client, STUDENT_EMAIL)

    response = client.get(f"{API}/housing/students/{other.id}/housing")

    assert response.status_code == 403
    assert _error_code(response) == "FORBIDDEN"
    assert "assignment" not in response.json()


def test_student_cannot_read_another_students_populated_housing(client, db_session):
    other = _other_student(db_session)
    bed = _bed(db_session)
    assignment = _assign(db_session, other, bed)
    _login(client, STUDENT_EMAIL)

    response = client.get(f"{API}/housing/students/{other.id}/housing")

    assert response.status_code == 403
    assert _error_code(response) == "FORBIDDEN"
    assert str(assignment.id) not in response.text
    assert "bed_id" not in response.json()


def test_student_cannot_read_another_students_assignment_or_history(
    client, db_session
):
    other = _other_student(db_session)
    bed = _bed(db_session)
    assignment = _assign(db_session, other, bed)
    _login(client, STUDENT_EMAIL)

    assignment_response = client.get(f"{API}/housing/assignments/{assignment.id}")
    room_history = client.get(f"{API}/housing/rooms/{bed.room_id}/history")
    bed_history = client.get(f"{API}/housing/beds/{bed.id}/history")

    assert assignment_response.status_code == 403
    assert room_history.status_code == 403
    assert bed_history.status_code == 403


@pytest.mark.parametrize("email", [ADMIN_EMAIL, MANAGEMENT_EMAIL])
def test_staff_can_read_empty_and_populated_housing(client, db_session, email):
    other = _other_student(db_session)
    empty_bed = _bed(db_session)
    _login(client, email)

    empty_response = client.get(f"{API}/housing/students/{other.id}/housing")
    assert empty_response.status_code == 200
    assert empty_response.json()["has_assignment"] is False
    assert empty_response.json()["assignment"] is None

    assignment = _assign(db_session, other, empty_bed)
    populated_response = client.get(f"{API}/housing/students/{other.id}/housing")
    assert populated_response.status_code == 200
    assert populated_response.json()["assignment"]["id"] == str(assignment.id)


def test_teacher_is_denied_student_housing(client, db_session):
    other = _other_student(db_session)
    _login(client, TEACHER_EMAIL)

    response = client.get(f"{API}/housing/students/{other.id}/housing")

    assert response.status_code == 403
    assert _error_code(response) == "FORBIDDEN"


def test_unauthenticated_student_housing_is_rejected(client, db_session):
    me = _student_for_email(db_session)

    response = client.get(f"{API}/housing/students/{me.id}/housing")

    assert response.status_code == 401
    assert _error_code(response) == "UNAUTHORIZED"
