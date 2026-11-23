"""Tests for the controlled housing import.

The rules under test are the ones a wrong import would break in the real world:
an unresolved bed reference, a bed that already has an occupant, a student who
is already housed, an ambiguous date, and a batch that must not be half-applied.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.auth.service import hash_password
from app.models.audit import AuditLog
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
)
from app.models.identity import Student, User

HEADER = "student_id,building,floor,room,bed,start_date\n"


def _login(client, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def structure(db_session):
    """A deterministic building with one bed, independent of seed data."""
    building = Building(name="Test Hall", is_active=True)
    db_session.add(building)
    db_session.flush()

    floor = Floor(building_id=building.id, floor_number=1)
    db_session.add(floor)
    db_session.flush()

    room = Room(floor_id=floor.id, room_number="101", capacity=2)
    db_session.add(room)
    db_session.flush()

    bed_one = Bed(room_id=room.id, bed_number=1)
    bed_two = Bed(room_id=room.id, bed_number=2)
    db_session.add_all([bed_one, bed_two])
    db_session.commit()
    return {"building": building, "floor": floor, "room": room, "beds": [bed_one, bed_two]}


def _second_student(db_session) -> Student:
    """A student the seeded fixtures do not provide."""
    user = User(
        email="import.second@school.portal",
        username="import-second",
        hashed_password=hash_password("password123"),
        full_name="Second Student",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    db_session.flush()
    student = Student(
        user_id=user.id,
        student_id="STU-002",
        first_name="Second",
        last_name="Student",
    )
    db_session.add(student)
    db_session.commit()
    return student


def _upload(client, path: str, body: str, **params):
    return client.post(
        path,
        files={"file": ("housing.csv", body.encode("utf-8"), "text/csv")},
        params=params,
    )


def test_preview_validates_without_writing(client, db_session, structure):
    _login(client, "admin@school.portal")
    body = HEADER + "STU-001,Test Hall,1,101,1,2026-09-01\n"
    response = _upload(client, "/api/v1/housing/import/preview", body)

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["dry_run"] is True
    assert report["valid"] == 1
    assert report["created"] == 0
    assert report["aborted"] is False
    assert report["rows"][0]["status"] == "VALID"
    assert report["rows"][0]["student_name"] == "Student User"
    # Preview is genuinely read-only.
    assert db_session.query(HousingAssignment).count() == 0


def test_apply_creates_assignment_and_records_actor(client, db_session, structure):
    _login(client, "admin@school.portal")
    response = _upload(
        client,
        "/api/v1/housing/import/apply",
        HEADER + "STU-001,Test Hall,1,101,1,2026-09-01\n",
        confirm="true",
        source_reference="Housing sheet 2026-09",
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["created"] == 1
    assert report["rows"][0]["status"] == "CREATED"

    db_session.expire_all()
    assignment = db_session.query(HousingAssignment).one()
    assert assignment.status == HousingAssignmentStatus.ACTIVE
    assert assignment.created_by_id is not None
    assert "Housing sheet 2026-09" in (assignment.notes or "")


def test_apply_requires_explicit_confirmation(client, structure):
    _login(client, "admin@school.portal")
    response = _upload(
        client, "/api/v1/housing/import/apply", HEADER + "STU-001,Test Hall,1,101,1,2026-09-01\n"
    )
    assert response.status_code == 422
    # The API normalizes every HTTP error to a top-level `error` envelope.
    assert response.json()["error"]["code"] == "IMPORT_CONFIRMATION_REQUIRED"


def test_unknown_building_is_reported_and_nothing_is_written(client, db_session, structure):
    _login(client, "admin@school.portal")
    response = _upload(
        client,
        "/api/v1/housing/import/apply",
        HEADER + "STU-001,Nowhere Hall,1,101,1,2026-09-01\n",
        confirm="true",
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["aborted"] is True
    assert report["created"] == 0
    row = report["rows"][0]
    assert row["status"] == "ERROR"
    assert row["code"] == "IMPORT_UNRESOLVED_REFERENCE"
    assert "Unknown building" in row["message"]
    assert db_session.query(HousingAssignment).count() == 0


def test_unknown_room_and_bed_are_distinguished(client, structure):
    _login(client, "admin@school.portal")
    no_room = _upload(
        client, "/api/v1/housing/import/preview", HEADER + "STU-001,Test Hall,1,999,1,2026-09-01\n"
    ).json()
    assert "no room 999" in no_room["rows"][0]["message"]

    no_bed = _upload(
        client, "/api/v1/housing/import/preview", HEADER + "STU-001,Test Hall,1,101,9,2026-09-01\n"
    ).json()
    assert "no bed 9" in no_bed["rows"][0]["message"]


def test_ambiguous_date_is_rejected_not_guessed(client, structure):
    _login(client, "admin@school.portal")
    report = _upload(
        client, "/api/v1/housing/import/preview", HEADER + "STU-001,Test Hall,1,101,1,01/02/2026\n"
    ).json()
    assert report["rows"][0]["code"] == "IMPORT_INVALID_DATE"
    assert report["failed"] == 1


def test_end_before_start_is_rejected(client, structure):
    _login(client, "admin@school.portal")
    body = (
        "student_id,building,floor,room,bed,start_date,end_date\n"
        "STU-001,Test Hall,1,101,1,2026-09-01,2026-08-01\n"
    )
    report = _upload(client, "/api/v1/housing/import/preview", body).json()
    assert report["rows"][0]["code"] == "IMPORT_INVALID_DATE"


def test_unknown_student_is_reported(client, structure):
    _login(client, "admin@school.portal")
    report = _upload(
        client, "/api/v1/housing/import/preview", HEADER + "STU-404,Test Hall,1,101,1,2026-09-01\n"
    ).json()
    assert report["rows"][0]["code"] == "STUDENT_NOT_FOUND"


def test_occupied_bed_is_skipped_not_overwritten(client, db_session, structure):
    student = _second_student(db_session)
    existing = HousingAssignment(
        student_id=student.user_id,
        bed_id=structure["beds"][0].id,
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        status=HousingAssignmentStatus.ACTIVE,
    )
    db_session.add(existing)
    db_session.commit()

    _login(client, "admin@school.portal")
    response = _upload(
        client,
        "/api/v1/housing/import/apply",
        HEADER + "STU-001,Test Hall,1,101,1,2026-09-01\n",
        confirm="true",
    )
    report = response.json()
    assert report["created"] == 0
    assert report["skipped"] == 1
    assert report["rows"][0]["code"] == "BED_OCCUPIED"

    db_session.expire_all()
    assignments = db_session.query(HousingAssignment).all()
    assert len(assignments) == 1
    assert assignments[0].student_id == student.user_id


def test_housed_student_is_skipped(client, db_session, structure):
    student = (
        db_session.query(Student).filter(Student.student_id == "STU-001").one()
    )
    db_session.add(
        HousingAssignment(
            student_id=student.user_id,
            bed_id=structure["beds"][0].id,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            status=HousingAssignmentStatus.ACTIVE,
        )
    )
    db_session.commit()

    _login(client, "admin@school.portal")
    report = _upload(
        client,
        "/api/v1/housing/import/preview",
        HEADER + "STU-001,Test Hall,1,101,2,2026-09-01\n",
    ).json()
    assert report["rows"][0]["code"] == "STUDENT_ALREADY_ASSIGNED"


def test_reimport_is_idempotent(client, db_session, structure):
    _login(client, "admin@school.portal")
    body = HEADER + "STU-001,Test Hall,1,101,1,2026-09-01\n"

    first = _upload(
        client, "/api/v1/housing/import/apply", body, confirm="true"
    ).json()
    assert first["created"] == 1

    second = _upload(
        client, "/api/v1/housing/import/apply", body, confirm="true"
    ).json()
    assert second["created"] == 0
    assert second["skipped"] == 1
    db_session.expire_all()
    assert db_session.query(HousingAssignment).count() == 1


def test_duplicate_rows_inside_the_file_are_skipped(client, structure):
    _login(client, "admin@school.portal")
    body = HEADER + (
        "STU-001,Test Hall,1,101,1,2026-09-01\n"
        "STU-001,Test Hall,1,101,2,2026-09-01\n"
    )
    report = _upload(client, "/api/v1/housing/import/preview", body).json()
    assert report["valid"] == 1
    assert report["skipped"] == 1
    assert report["rows"][1]["code"] == "DUPLICATE_IN_FILE"


def test_one_invalid_row_aborts_the_batch(client, db_session, structure):
    _login(client, "admin@school.portal")
    body = HEADER + (
        "STU-001,Test Hall,1,101,1,2026-09-01\n"
        "STU-404,Test Hall,1,101,2,2026-09-01\n"
    )
    report = _upload(
        client, "/api/v1/housing/import/apply", body, confirm="true"
    ).json()
    assert report["aborted"] is True
    assert report["created"] == 0
    assert db_session.query(HousingAssignment).count() == 0


def test_missing_required_column_is_a_file_error(client, structure):
    _login(client, "admin@school.portal")
    response = _upload(
        client, "/api/v1/housing/import/preview", "student_id,building,floor\nSTU-001,Test Hall,1\n"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IMPORT_MISSING_COLUMNS"


def test_semicolon_and_bom_are_accepted(client, structure):
    _login(client, "admin@school.portal")
    body = (
        "\ufeffstudent number;building;floor;room;bed;check in\n"
        "STU-001;Test Hall;1;101;1;2026-09-01\n"
    )
    response = _upload(client, "/api/v1/housing/import/preview", body)
    assert response.status_code == 200, response.text
    assert response.json()["valid"] == 1


def test_template_matches_the_importer(client):
    _login(client, "admin@school.portal")
    response = client.get("/api/v1/housing/import/template")
    assert response.status_code == 200
    header = response.text.splitlines()[0]
    for column in ("student_id", "building", "floor", "room", "bed", "start_date"):
        assert column in header


def test_import_is_denied_to_students_and_teachers(client, structure):
    body = HEADER + "STU-001,Test Hall,1,101,1,2026-09-01\n"
    for email in ("student@school.portal", "teacher@school.portal"):
        _login(client, email)
        response = _upload(client, "/api/v1/housing/import/apply", body, confirm="true")
        assert response.status_code == 403, (email, response.text)


def test_management_can_preview_and_apply(client, db_session, structure):
    """The housing office is run by Management, not only by administrators."""
    _login(client, "management@school.portal")
    body = HEADER + "STU-001,Test Hall,1,101,1,2026-09-01\n"
    preview = _upload(client, "/api/v1/housing/import/preview", body)
    assert preview.status_code == 200, preview.text
    applied = _upload(
        client, "/api/v1/housing/import/apply", body, confirm="true"
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["created"] == 1


def test_import_is_audited(client, db_session, structure):
    _login(client, "admin@school.portal")
    _upload(
        client,
        "/api/v1/housing/import/apply",
        HEADER + "STU-001,Test Hall,1,101,1,2026-09-01\n",
        confirm="true",
        source_reference="Audit check",
    )

    db_session.expire_all()
    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "housing.import.applied")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert entry is not None
    assert entry.entity_type == "housing_import"
