"""Before/after history for institutional changes.

Phase 9 found that several important audit events recorded *which* fields were
submitted but not what they were before or after. These tests pin the corrected
behaviour at the API boundary, so a future edit that drops a value is caught
even if the endpoint still returns the right row.

The authoritative record for academic and immigration data lives in the domain
history tables (``academic_change_history``, ``immigration_profile_versions``).
These tests therefore check both: the audit entry is self-contained for the
auditor, and it points at the domain record that holds the full snapshot.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.audit import field_changes, sanitize_value
from app.auth.service import hash_password
from app.models.audit import AuditLog
from app.models.housing import Bed, Building, Floor, Room
from app.models.identity import Role, Student, StudentStatus, User


# ---------------------------------------------------------------------------
# Value serialisation
# ---------------------------------------------------------------------------


def test_field_changes_reports_only_real_changes() -> None:
    changes = field_changes(
        {"a": 1, "b": "same", "c": None},
        {"a": 2, "b": "same", "c": "now set"},
    )
    assert "b" not in changes
    assert changes["a"] == {"previous": 1, "new": 2}
    assert changes["c"] == {"previous": None, "new": "now set"}


def test_field_changes_treats_a_new_or_removed_key_as_null() -> None:
    assert field_changes({}, {"x": 5}) == {"x": {"previous": None, "new": 5}}
    assert field_changes({"x": 5}, {}) == {"x": {"previous": 5, "new": None}}


def test_field_changes_restricts_to_the_named_fields() -> None:
    changes = field_changes(
        {"a": 1, "b": 1}, {"a": 2, "b": 2}, fields=["a"]
    )
    assert set(changes) == {"a"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (3, 3),
        (uuid.UUID("11111111-1111-1111-1111-111111111111"),
         "11111111-1111-1111-1111-111111111111"),
        (StudentStatus.ACTIVE, "ACTIVE"),
        (datetime(2026, 9, 1, 12, 30, tzinfo=UTC), "2026-09-01T12:30:00+00:00"),
    ],
)
def test_values_serialise_comparably(value, expected) -> None:
    assert sanitize_value(value) == expected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client, email: str = "admin@school.portal") -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text


def _mk_student(db, tag: str) -> Student:
    user = User(
        email=f"history-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"history-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"History {tag}",
        is_active=True,
    )
    role = db.query(Role).filter(Role.name == "STUDENT").first()
    if role is not None:
        user.roles.append(role)
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"HX-{tag}-{uuid.uuid4().hex[:6]}",
        first_name="History",
        last_name=tag,
    )
    db.add(student)
    db.flush()
    return student


def _latest(db, action: str, entity_id: uuid.UUID) -> AuditLog:
    return (
        db.query(AuditLog)
        .filter(AuditLog.action == action, AuditLog.entity_id == entity_id)
        .order_by(AuditLog.created_at.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Student records
# ---------------------------------------------------------------------------


def test_student_update_records_previous_and_new_values(client, db_session) -> None:
    _login(client)
    student = _mk_student(db_session, "update")
    student.preferred_name = "Before"
    db_session.flush()

    response = client.patch(
        f"/api/v1/students/{student.id}", json={"preferred_name": "After"}
    )
    assert response.status_code == 200, response.text

    entry = _latest(db_session, "student.updated", student.id)
    assert entry is not None
    assert entry.context["fields"] == ["preferred_name"]
    assert entry.context["changes"]["preferred_name"] == {
        "previous": "Before",
        "new": "After",
    }


def test_student_update_of_several_fields_is_fully_described(
    client, db_session
) -> None:
    _login(client)
    student = _mk_student(db_session, "multi")
    student.phone = "000"
    student.nationality = "Singapore"
    db_session.flush()

    response = client.patch(
        f"/api/v1/students/{student.id}",
        json={"phone": "555-0100", "nationality": "Malaysia"},
    )
    assert response.status_code == 200, response.text

    changes = _latest(db_session, "student.updated", student.id).context["changes"]
    assert changes["phone"] == {"previous": "000", "new": "555-0100"}
    assert changes["nationality"] == {"previous": "Singapore", "new": "Malaysia"}


def test_rejected_student_update_writes_no_audit_event(client, db_session) -> None:
    """A refused change must not leave an audit record claiming it happened."""
    _login(client)
    first = _mk_student(db_session, "clash-a")
    second = _mk_student(db_session, "clash-b")
    before = _latest(db_session, "student.updated", second.id)
    assert before is None

    response = client.patch(
        f"/api/v1/students/{second.id}", json={"student_id": first.student_id}
    )
    assert response.status_code in {400, 409}, response.text
    assert _latest(db_session, "student.updated", second.id) is None


def test_status_change_still_records_from_and_to(client, db_session) -> None:
    _login(client)
    student = _mk_student(db_session, "status")

    response = client.patch(
        f"/api/v1/students/{student.id}/status", json={"status": "SUSPENDED"}
    )
    assert response.status_code == 200, response.text

    entry = _latest(db_session, "student.status_changed", student.id)
    assert entry.context["from"] == "ACTIVE"
    assert entry.context["to"] == "SUSPENDED"


# ---------------------------------------------------------------------------
# Housing
# ---------------------------------------------------------------------------


@pytest.fixture
def housing(db_session):
    building = Building(name=f"History Hall {uuid.uuid4().hex[:6]}", is_active=True)
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, floor_number=1)
    db_session.add(floor)
    db_session.flush()
    room = Room(floor_id=floor.id, room_number="H1", capacity=2)
    db_session.add(room)
    db_session.flush()
    beds = [Bed(room_id=room.id, bed_number=n) for n in (1, 2)]
    db_session.add_all(beds)
    db_session.flush()
    return {"beds": beds}


def test_housing_assignment_update_records_before_and_after(
    client, db_session, housing
) -> None:
    _login(client)
    student = _mk_student(db_session, "housing-update")

    created = client.post(
        "/api/v1/housing/assignments",
        json={
            "student_id": str(student.user_id),
            "bed_id": str(housing["beds"][0].id),
            "start_date": "2026-09-01T00:00:00Z",
            "notes": "Arrived late",
        },
    )
    assert created.status_code == 201, created.text
    assignment_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/housing/assignments/{assignment_id}",
        json={"notes": "Corrected after interview"},
    )
    assert response.status_code == 200, response.text

    entry = _latest(db_session, "housing.assignment.updated", uuid.UUID(assignment_id))
    assert entry.context["changes"]["notes"] == {
        "previous": "Arrived late",
        "new": "Corrected after interview",
    }


def test_housing_transfer_records_the_vacated_bed(
    client, db_session, housing
) -> None:
    _login(client)
    student = _mk_student(db_session, "housing-transfer")
    origin, destination = housing["beds"]

    created = client.post(
        "/api/v1/housing/assignments",
        json={
            "student_id": str(student.user_id),
            "bed_id": str(origin.id),
            "start_date": "2026-09-01T00:00:00Z",
        },
    )
    assert created.status_code == 201, created.text
    assignment_id = created.json()["id"]

    response = client.post(
        f"/api/v1/housing/assignments/{assignment_id}/transfer",
        json={
            "new_bed_id": str(destination.id),
            "transfer_date": "2026-10-01T00:00:00Z",
            "notes": "Room change requested",
        },
    )
    assert response.status_code == 200, response.text
    new_id = uuid.UUID(response.json()["id"])

    entry = _latest(db_session, "housing.assignment.transferred", new_id)
    assert entry.context["previous_bed_id"] == str(origin.id)
    assert entry.context["bed_id"] == str(destination.id)


def test_housing_move_out_records_the_bed_and_the_transition(
    client, db_session, housing
) -> None:
    _login(client)
    student = _mk_student(db_session, "housing-end")

    created = client.post(
        "/api/v1/housing/assignments",
        json={
            "student_id": str(student.user_id),
            "bed_id": str(housing["beds"][0].id),
            "start_date": "2026-09-01T00:00:00Z",
        },
    )
    assert created.status_code == 201, created.text
    assignment_id = created.json()["id"]

    response = client.post(f"/api/v1/housing/assignments/{assignment_id}/end")
    assert response.status_code == 200, response.text

    entry = _latest(db_session, "housing.assignment.ended", uuid.UUID(assignment_id))
    assert entry.context["bed_id"] == str(housing["beds"][0].id)
    assert entry.context["changes"]["status"]["previous"] == "ACTIVE"
    assert entry.context["changes"]["status"]["new"] == "ENDED"


# ---------------------------------------------------------------------------
# Immigration
# ---------------------------------------------------------------------------


def test_immigration_correction_records_an_audit_event_and_a_version(
    client, db_session
) -> None:
    _login(client)
    student = _mk_student(db_session, "immigration")

    response = client.patch(
        f"/api/v1/students/{student.id}/immigration",
        json={
            "passport_number": "P-HISTORY-1",
            "passport_expiry_date": "2030-01-01",
            "change_reason": "Passport replaced at the counter",
        },
    )
    assert response.status_code == 200, response.text

    profile_id = uuid.UUID(response.json()["id"])
    entry = _latest(db_session, "immigration.profile.updated", profile_id)
    assert entry is not None
    assert "passport_number" in entry.context["fields"]
    assert entry.context["reason"] == "Passport replaced at the counter"
    assert entry.context["version_number"] >= 1

    # The identifier itself is never copied into the audit log.
    assert "P-HISTORY-1" not in str(entry.context)
