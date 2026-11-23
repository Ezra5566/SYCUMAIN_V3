"""Read-only source intake catalog tests.

The catalog is an audit view, not a write API. These tests import one accepted
source intake inside the test savepoint, then verify that unresolved intakes stay
source-only and that readiness is independent of the period's active status.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

import pytest

from app.auth.service import hash_password
from app.database.session import SessionLocal
from app.models.academic import (
    AcademicPeriod,
    AcademicPeriodStatus,
    ClassSectionProgramOffering,
    ProgramOffering,
)
from app.models.admission import AcademicAdmission, AcademicPlacement
from app.models.identity import Student, User
from app.seed_academic import seed_academic
from app.services.academic_import import DEFAULT_SOURCE, apply_import, prepare_import

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


@pytest.fixture(scope="module", autouse=True)
def academic_structure():
    db = SessionLocal()
    try:
        seed_academic(db)
    finally:
        db.close()
    yield


def _login(client: TestClient, email: str = "admin@school.portal") -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200, response.text


def _intake(payload: dict, source_id: str) -> dict:
    return next(item for item in payload["items"] if item["source_id"] == source_id)


@pytest.fixture
def imported_fall(client: TestClient, db_session):
    _login(client)
    fall = (
        db_session.query(AcademicPeriod)
        .filter(AcademicPeriod.code == "2026-FALL")
        .one()
    )
    report = prepare_import(db_session, DEFAULT_SOURCE)
    apply_import(
        db_session,
        report["batch_id"],
        period_map={"2026-autumn": fall.id},
    )
    return fall


def test_catalog_exposes_all_three_intakes_and_source_only_data(client):
    _login(client)
    response = client.get("/api/v1/academics/source-intakes")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["source_sha256"]
    assert len(payload["catalog_sha256"]) == 64
    assert payload["counts"]["offerings"] == 15
    assert [item["source_id"] for item in payload["items"]] == [
        "2026-autumn",
        "2026-spring",
        "2025-autumn",
    ]

    autumn = _intake(payload, "2026-autumn")
    assert autumn["source_identified"] is True
    assert autumn["period_configured"] is False
    assert autumn["active"] is False
    assert autumn["ready"] is False
    assert autumn["timetable_imported"] is False
    assert autumn["mapped_offering_count"] is None
    assert autumn["mapped_section_count"] is None
    assert autumn["mapped_timetable_session_count"] is None
    assert autumn["source_session_count"] == 14
    assert autumn["offering_count"] == 6
    assert all(offering["mapping_state"] == "SOURCE_ONLY" for offering in autumn["offerings"])
    assert all(
        offering["program_offering_id"] is None
        and offering["assigned_student_count"] is None
        and offering["mapped_section_count"] is None
        for offering in autumn["offerings"]
    )

    spring = _intake(payload, "2026-spring")
    assert spring["readiness_state"] == "PENDING"
    assert spring["readiness_reason_codes"] == ["PERIOD_NOT_CONFIGURED"]

    autumn_2025 = _intake(payload, "2025-autumn")
    assert autumn_2025["held_section_count"] == 2
    assert autumn_2025["shared_section_count"] == 2
    assert any(section["held"] for section in autumn_2025["sections"])
    assert any(offering["held"] for offering in autumn_2025["offerings"])
    assert any(
        subject["held"]
        for offering in autumn_2025["offerings"]
        for subject in offering["subjects"]
    )


def test_imported_intake_matches_period_offerings_sections_and_sessions(
    client, imported_fall, db_session
):
    _login(client)
    response = client.get("/api/v1/academics/source-intakes")
    assert response.status_code == 200, response.text
    autumn = _intake(response.json(), "2026-autumn")

    assert autumn["period_configured"] is True
    assert autumn["period"]["id"] == str(imported_fall.id)
    assert autumn["period"]["code"] == "2026-FALL"
    assert autumn["active"] is True
    assert autumn["timetable_imported"] is True
    assert autumn["ready"] is True
    assert autumn["readiness_state"] == "READY"
    assert autumn["readiness_reason_codes"] == []
    assert autumn["mapped_offering_count"] == 6
    assert autumn["mapped_section_count"] == 9
    assert autumn["verified_source_session_count"] == 14
    assert autumn["mapped_timetable_session_count"] == 14
    assert all(
        offering["program_offering_id"] is not None
        and offering["assigned_student_count"] == 0
        and offering["mapped_section_count"] is not None
        for offering in autumn["offerings"]
    )
    assert all(
        section["mapping_state"] == "MAPPED"
        and section["mapped_class_section_id"] is not None
        and section["timetable_verified"] is True
        for section in autumn["sections"]
    )

    ai = next(
        offering for offering in autumn["offerings"] if offering["source_id"] == "ai-2026a"
    )
    student = db_session.query(Student).first()
    assert student is not None
    offering = db_session.get(ProgramOffering, uuid.UUID(ai["program_offering_id"]))
    assert offering is not None
    now = datetime.now()
    admission = AcademicAdmission(
        student_id=student.id,
        admission_intake_id=offering.academic_period_id,
        admitted_program_id=offering.program_id,
        admitted_program_offering_id=offering.id,
        current_program_id=offering.program_id,
        status="ACTIVE",
        initial_status="ACTIVE",
        verification_status="VERIFIED",
        verified_at=now,
        activated_at=now,
        created_by_id=student.user_id,
    )
    db_session.add(admission)
    db_session.flush()
    db_session.add(
        AcademicPlacement(
            student_id=student.id,
            admission_id=admission.id,
            academic_period_id=offering.academic_period_id,
            program_offering_id=offering.id,
            effective_from=date.today(),
            created_by_id=student.user_id,
        )
    )
    db_session.flush()

    refreshed = _intake(client.get("/api/v1/academics/source-intakes").json(), "2026-autumn")
    refreshed_ai = next(
        offering
        for offering in refreshed["offerings"]
        if offering["source_id"] == "ai-2026a"
    )
    assert refreshed_ai["assigned_student_count"] == 1


def test_configured_planned_intake_is_neither_ready_nor_active(client, db_session):
    period = AcademicPeriod(
        name="Test Spring 2026",
        code=f"TEST-SPRING-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 2, 1),
        end_date=date(2026, 7, 1),
        source_key="ref:v1:period:2026-spring",
        status=AcademicPeriodStatus.PLANNED,
    )
    db_session.add(period)
    db_session.flush()

    _login(client)
    spring = _intake(client.get("/api/v1/academics/source-intakes").json(), "2026-spring")
    assert spring["period_configured"] is True
    assert spring["period"]["id"] == str(period.id)
    assert spring["active"] is False
    assert spring["timetable_imported"] is False
    assert spring["ready"] is False
    assert spring["readiness_state"] == "PENDING"
    assert "TIMETABLE_NOT_IMPORTED" in spring["readiness_reason_codes"]


def test_offering_from_another_period_is_not_matched(client, db_session):
    period = AcademicPeriod(
        name="Test Spring 2026",
        code=f"TEST-SPRING-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 2, 1),
        end_date=date(2026, 7, 1),
        source_key="ref:v1:period:2026-spring",
        status=AcademicPeriodStatus.PLANNED,
    )
    fall = (
        db_session.query(AcademicPeriod)
        .filter(AcademicPeriod.code == "2026-FALL")
        .one()
    )
    db_session.add(period)
    db_session.flush()
    db_session.add(
        ProgramOffering(
            academic_period_id=fall.id,
            source_id="ai-2026s",
            source_key="ref:v1:offering:ai-2026s",
            name="Wrong-period offering",
        )
    )
    db_session.flush()

    _login(client)
    spring = _intake(client.get("/api/v1/academics/source-intakes").json(), "2026-spring")
    assert spring["mapped_offering_count"] == 0
    ai = next(
        offering for offering in spring["offerings"] if offering["source_id"] == "ai-2026s"
    )
    assert ai["program_offering_id"] is None
    assert ai["mapping_state"] == "SOURCE_ONLY"


def test_missing_source_link_makes_ready_false_while_imported_stays_true(
    client, imported_fall, db_session
):
    _login(client)
    before = _intake(client.get("/api/v1/academics/source-intakes").json(), "2026-autumn")
    ai = next(
        offering for offering in before["offerings"] if offering["source_id"] == "ai-2026a"
    )
    link = (
        db_session.query(ClassSectionProgramOffering)
        .filter(
            ClassSectionProgramOffering.program_offering_id
            == uuid.UUID(ai["program_offering_id"])
        )
        .first()
    )
    assert link is not None
    db_session.delete(link)
    db_session.flush()

    after = _intake(client.get("/api/v1/academics/source-intakes").json(), "2026-autumn")
    assert after["timetable_imported"] is True
    assert after["ready"] is False
    assert after["active"] is True
    assert "SECTION_OFFERING_LINK_INCOMPLETE" in after["readiness_reason_codes"]


def test_source_intakes_require_permission(client, db_session):
    assert client.get("/api/v1/academics/source-intakes").status_code == 401

    user = User(
        email=f"no-academic-{uuid.uuid4().hex[:8]}@test.local",
        username=f"no-academic-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name="No Academic Access",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    _login(client, user.email)
    response = client.get("/api/v1/academics/source-intakes")
    assert response.status_code == 403
