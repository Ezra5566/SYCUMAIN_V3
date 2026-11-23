"""The three importers as one pipeline.

A migration is not three separate uploads: the same person arrives from the
registrar's file, then their bed and their passport arrive from two other
sheets. These tests pin the properties that make that safe — one stable
identifier across all three, no silent replacement of what the institution
already holds, and a batch that either lands complete or not at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit import AuditLog
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
)
from app.models.identity import Student
from app.models.immigration import ImmigrationProfile
from app.services.housing_import import apply_housing_import, parse_rows

STUDENT_HEADER = "student_id,first_name,last_name,email\n"
HOUSING_HEADER = "student_id,building,floor,room,bed,start_date\n"


def _login(client, email: str = "admin@school.portal") -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def structure(db_session):
    building = Building(name="Interop Hall", is_active=True)
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, floor_number=2)
    db_session.add(floor)
    db_session.flush()
    room = Room(floor_id=floor.id, room_number="201", capacity=3)
    db_session.add(room)
    db_session.flush()
    beds = [Bed(room_id=room.id, bed_number=n) for n in (1, 2, 3)]
    db_session.add_all(beds)
    db_session.commit()
    return {"building": building, "floor": floor, "room": room, "beds": beds}


def _import_student(client, number: str, email: str, *, dry_run: bool = False):
    body = STUDENT_HEADER + f"{number},Interop,Student,{email}\n"
    return client.post(
        "/api/v1/students/import",
        files={"file": ("students.csv", body.encode(), "text/csv")},
        params={"dry_run": "true"} if dry_run else {},
    )


def _housing_apply(client, body: str, **params):
    return client.post(
        "/api/v1/housing/import/apply",
        files={"file": ("housing.csv", body.encode(), "text/csv")},
        params={"confirm": "true", **params},
    )


def _immigration(client, path: str, records: list[dict], **extra):
    payload = {"source_reference": "Interop sheet", "records": records, **extra}
    return client.post(f"/api/v1/immigration/import/{path}", json=payload)


# --- Full pipeline -----------------------------------------------------------


def test_student_housing_and_immigration_link_to_the_same_record(
    client, db_session, structure
):
    """One person, three files, one student record."""
    _login(client)

    created = _import_student(client, "STU-900", "interop.900@school.portal")
    assert created.status_code == 200, created.text
    assert created.json()["created"] == 1

    housing = _housing_apply(
        client,
        HOUSING_HEADER + "STU-900,Interop Hall,2,201,1,2026-09-01\n",
        source_reference="Interop sheet",
    )
    assert housing.status_code == 200, housing.text
    assert housing.json()["created"] == 1

    preview = _immigration(
        client,
        "preview",
        [
            {
                "student_id": "STU-900",
                "values": {
                    "passport_number": "P-900",
                    "passport_expiry_date": "2030-01-01",
                },
            }
        ],
    )
    assert preview.status_code == 200, preview.text
    row = preview.json()["records"][0]
    assert row["status"] == "APPLY", row
    assert row["student_number"] == "STU-900"

    applied = _immigration(
        client,
        "apply",
        [
            {
                "student_id": "STU-900",
                "values": {
                    "passport_number": "P-900",
                    "passport_expiry_date": "2030-01-01",
                },
            }
        ],
        confirm=True,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == 1

    db_session.expire_all()
    student = db_session.query(Student).filter(Student.student_id == "STU-900").one()
    assignment = (
        db_session.query(HousingAssignment)
        .filter(HousingAssignment.student_id == student.user_id)
        .one()
    )
    profile = (
        db_session.query(ImmigrationProfile)
        .filter(ImmigrationProfile.student_id == student.id)
        .one()
    )
    assert assignment.status == HousingAssignmentStatus.ACTIVE
    assert profile.passport_number == "P-900"
    # Imported data is never verified data.
    assert profile.verification_status == "UNVERIFIED"
    assert profile.verified_at is None
    assert profile.data_source == "IMPORT"


def test_housing_accepts_a_uuid_free_sheet_by_student_number(client, db_session, structure):
    """The sheet carries student numbers, never internal UUIDs."""
    _login(client)
    _import_student(client, "STU-901", "interop.901@school.portal")
    report = _housing_apply(
        client, HOUSING_HEADER + "STU-901,Interop Hall,2,201,2,2026-09-01\n"
    ).json()
    assert report["created"] == 1


# --- Housing rollback --------------------------------------------------------


def test_housing_batch_rolls_back_completely_when_the_commit_fails(
    client, db_session, structure, monkeypatch
):
    """A conflict between validation and commit must leave no partial batch."""
    _login(client)
    _import_student(client, "STU-902", "interop.902@school.portal")

    rows = parse_rows(
        (HOUSING_HEADER + "STU-902,Interop Hall,2,201,3,2026-09-01\n").encode(),
        max_rows=100,
    )
    admin = (
        db_session.query(Student).filter(Student.student_id == "STU-902").one()
    )

    def failing_commit():
        raise IntegrityError("simulated concurrent assignment", None, Exception())

    monkeypatch.setattr(db_session, "commit", failing_commit)
    report = apply_housing_import(
        db_session, rows, actor_id=admin.user_id, source_reference="rollback check"
    )
    monkeypatch.undo()

    assert report.aborted is True
    assert report.created == 0
    db_session.expire_all()
    assert db_session.query(HousingAssignment).count() == 0
    assert report.rows[0].status == "VALID"  # validated, but never written


def test_housing_applies_several_rows_in_one_batch(client, db_session, structure):
    _login(client)
    _import_student(client, "STU-903", "interop.903@school.portal")
    _import_student(client, "STU-904", "interop.904@school.portal")

    body = HOUSING_HEADER + (
        "STU-903,Interop Hall,2,201,1,2026-09-01\n"
        "STU-904,Interop Hall,2,201,2,2026-09-01\n"
    )
    report = _housing_apply(client, body).json()
    assert report["created"] == 2, report
    db_session.expire_all()
    assert db_session.query(HousingAssignment).count() == 2


def test_housing_audit_records_counts_and_source(client, db_session, structure):
    _login(client)
    _import_student(client, "STU-905", "interop.905@school.portal")
    _housing_apply(
        client,
        HOUSING_HEADER + "STU-905,Interop Hall,2,201,1,2026-09-01\n",
        source_reference="September sheet",
    )

    db_session.expire_all()
    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "housing.import.applied")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert entry is not None
    assert entry.context["created"] == 1
    assert entry.context["source_reference"] == "September sheet"
    assert entry.context["aborted"] is False


# --- Immigration guarantees --------------------------------------------------
#
# These use freshly imported students. The seeded STU-001 already carries a
# VERIFIED profile, which is useful for the "official data wins" case below but
# useless as a blank slate.


def test_immigration_import_never_overwrites_an_existing_value(client, db_session):
    _login(client)
    response = _import_student(client, "STU-908", "interop.908@school.portal")
    assert response.json()["created"] == 1
    student = db_session.query(Student).filter(Student.student_id == "STU-908").one()

    db_session.add(
        ImmigrationProfile(
            student_id=student.id,
            passport_number="OFFICIAL-1",
            verification_status="UNVERIFIED",
        )
    )
    db_session.commit()

    preview = _immigration(
        client, "preview", [{"student_id": "STU-908", "values": {"passport_number": "OTHER"}}]
    ).json()
    row = preview["records"][0]
    assert row["status"] == "CONFLICT"
    assert "passport_number" in row["conflicts"]

    applied = _immigration(
        client,
        "apply",
        [{"student_id": "STU-908", "values": {"passport_number": "OTHER"}}],
        confirm=True,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == 0

    db_session.expire_all()
    profile = (
        db_session.query(ImmigrationProfile)
        .filter(ImmigrationProfile.student_id == student.id)
        .one()
    )
    assert profile.passport_number == "OFFICIAL-1"


def test_verified_official_data_wins_over_an_import(client, db_session):
    """A verified profile is official data; the import must not touch it."""
    _login(client)
    student = db_session.query(Student).filter(Student.student_id == "STU-001").one()
    profile = (
        db_session.query(ImmigrationProfile)
        .filter(ImmigrationProfile.student_id == student.id)
        .one()
    )
    profile.verification_status = "VERIFIED"
    profile.verified_at = datetime.now(UTC)
    db_session.commit()
    official_visa = profile.visa_number

    applied = _immigration(
        client,
        "apply",
        [{"student_id": "STU-001", "values": {"visa_number": "V-CLAIMED"}}],
        confirm=True,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == 0

    db_session.expire_all()
    profile = (
        db_session.query(ImmigrationProfile)
        .filter(ImmigrationProfile.student_id == student.id)
        .one()
    )
    assert profile.visa_number == official_visa
    assert profile.verification_status == "VERIFIED"


def test_immigration_import_fills_blanks_without_verifying(client, db_session):
    _login(client)
    assert _import_student(client, "STU-909", "interop.909@school.portal").json()["created"] == 1
    student = db_session.query(Student).filter(Student.student_id == "STU-909").one()
    assert (
        db_session.query(ImmigrationProfile)
        .filter(ImmigrationProfile.student_id == student.id)
        .first()
        is None
    )

    applied = _immigration(
        client,
        "apply",
        [{"student_id": "STU-909", "values": {"visa_number": "V-77"}}],
        confirm=True,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == 1

    db_session.expire_all()
    profile = (
        db_session.query(ImmigrationProfile)
        .filter(ImmigrationProfile.student_id == student.id)
        .one()
    )
    assert profile.visa_number == "V-77"
    assert profile.verification_status == "UNVERIFIED"
    assert profile.verified_at is None


def test_immigration_reimport_is_idempotent(client, db_session):
    _login(client)
    assert _import_student(client, "STU-910", "interop.910@school.portal").json()["created"] == 1
    record = [{"student_id": "STU-910", "values": {"visa_number": "V-88"}}]
    first = _immigration(client, "apply", record, confirm=True).json()
    second = _immigration(client, "apply", record, confirm=True).json()
    assert first["applied"] == 1
    assert second["applied"] == 0
    assert second["skipped"] == 1


def test_immigration_unknown_student_is_invalid_and_nothing_is_written(client, db_session):
    _login(client)
    before = db_session.query(ImmigrationProfile).count()
    preview = _immigration(
        client, "preview", [{"student_id": "STU-999", "values": {"visa_number": "V-1"}}]
    ).json()
    assert preview["invalid"] == 1
    assert preview["records"][0]["student_id"] is None

    applied = _immigration(
        client,
        "apply",
        [{"student_id": "STU-999", "values": {"visa_number": "V-1"}}],
        confirm=True,
    )
    assert applied.status_code == 400
    db_session.expire_all()
    assert db_session.query(ImmigrationProfile).count() == before


def test_immigration_import_is_denied_without_permission(client):
    for email in ("student@school.portal", "teacher@school.portal"):
        _login(client, email)
        response = _immigration(
            client, "apply", [{"student_id": "STU-001", "values": {"visa_number": "V"}}],
            confirm=True,
        )
        assert response.status_code == 403, (email, response.text)


# --- Student importer: no silent replacement --------------------------------


def test_reimporting_a_student_does_not_modify_the_existing_record(client, db_session):
    _login(client)
    first = _import_student(client, "STU-906", "interop.906@school.portal")
    assert first.json()["created"] == 1

    student = db_session.query(Student).filter(Student.student_id == "STU-906").one()
    student.phone = "+1 555 0100"
    db_session.commit()

    # Same number and email, different name and phone: must be skipped, not
    # applied over the record the institution already owns.
    body = (
        STUDENT_HEADER
        + "STU-906,Changed,Name,interop.906@school.portal\n"
    )
    second = client.post(
        "/api/v1/students/import",
        files={"file": ("students.csv", body.encode(), "text/csv")},
    )
    assert second.status_code == 200, second.text
    assert second.json()["created"] == 0
    assert second.json()["skipped"] == 1

    db_session.expire_all()
    student = db_session.query(Student).filter(Student.student_id == "STU-906").one()
    assert student.first_name == "Interop"
    assert student.phone == "+1 555 0100"


def test_student_dry_run_writes_no_student(client, db_session):
    _login(client)
    response = _import_student(client, "STU-907", "interop.907@school.portal", dry_run=True)
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 0
    db_session.expire_all()
    assert (
        db_session.query(Student).filter(Student.student_id == "STU-907").first() is None
    )
