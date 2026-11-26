"""Institutional timetable, source-import workflow and late-enrolment rules.

The three subjects are deliberately in one module because they describe one
chain: catalogue → operational period/offering → shared schedule → enrolment.
Each test still runs in the shared savepoint transaction, so nothing here leaks
into another test or into the development database.
"""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING

import pytest

from app.database.session import SessionLocal
from app.models.academic import (
    AcademicPeriod,
    AcademicPeriodStatus,
    ClassSection,
    ClassSectionProgramOffering,
    ClassStatus,
    Course,
    Enrollment,
    Program,
    ProgramOffering,
    TimetableEntry,
)
from app.models.identity import Student
from app.seed_academic import seed_academic

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


@pytest.fixture(scope="module", autouse=True)
def academic_data():
    db = SessionLocal()
    try:
        seed_academic(db)
    finally:
        db.close()
    yield


def _login(client: TestClient, email: str, password: str = "password123") -> dict:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _error_code(resp) -> str:
    return resp.json()["error"]["code"]


def _fall(db) -> AcademicPeriod:
    return db.query(AcademicPeriod).filter(AcademicPeriod.code == "2026-FALL").one()


def _bcs_offering(db) -> ProgramOffering:
    """The BCS offering for the active period, created when the seed has none.

    ``seed_academic`` seeds the curriculum but not offerings (those belong to an
    admission intake), so a timetable test has to establish the operational
    record it is about. It is created inside the test transaction and disappears
    with it.
    """
    program = db.query(Program).filter(Program.code == "BCS").one()
    period = _fall(db)
    offering = (
        db.query(ProgramOffering)
        .filter(
            ProgramOffering.academic_period_id == period.id,
            ProgramOffering.program_id == program.id,
        )
        .first()
    )
    if offering is None:
        offering = ProgramOffering(
            academic_period_id=period.id,
            program_id=program.id,
            source_id="test-bcs-2026f",
            source_key="test:offering:bcs:2026f",
            name=program.name,
        )
        db.add(offering)
        db.flush()
    return offering


def _student(db, number: str = "STU-001") -> Student:
    return db.query(Student).filter(Student.student_id == number).one()


def _add_section(
    db, *, section_code: str, course_code: str = "CS201", scheduled: bool = True
) -> ClassSection:
    """A section of the BCS offering, optionally with one scheduled session."""
    offering = _bcs_offering(db)
    course = db.query(Course).filter(Course.code == course_code).one()
    section = ClassSection(
        course_id=course.id,
        academic_period_id=_fall(db).id,
        section_code=section_code,
        source_label=f"{course_code} [{section_code}]",
        capacity=None,
        enrolled_count=0,
        status=ClassStatus.ACTIVE,
    )
    db.add(section)
    db.flush()
    db.add(
        ClassSectionProgramOffering(
            class_section_id=section.id,
            program_offering_id=offering.id,
        )
    )
    if scheduled:
        db.add(
            TimetableEntry(
                class_section_id=section.id,
                classroom_id=None,
                day_of_week=2,
                start_time=time(14, 0),
                end_time=time(15, 30),
                slot_label="7",
            )
        )
    db.commit()
    return section


class TestInstitutionalTimetable:
    def test_student_sees_the_whole_offering_not_only_enrolments(
        self, client, db_session
    ):
        section = _add_section(db_session, section_code="SHARED")
        enrolled = (
            db_session.query(Enrollment.class_section_id)
            .filter(Enrollment.student_id == _student(db_session).id)
            .all()
        )
        assert section.id not in {row[0] for row in enrolled}

        _login(client, "student@school.portal")
        offering = _bcs_offering(db_session)
        resp = client.get(
            f"/api/v1/academics/institutional-timetable?program_offering_id={offering.id}"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["period"]["code"] == "2026-FALL"
        assert data["program_offering"]["id"] == str(offering.id)

        entry_sections = {entry["class_section_id"] for entry in data["entries"]}
        assert str(section.id) in entry_sections
        # The un-enrolled session proves this is the offering's schedule, not
        # the viewer's personal one.
        assert len(data["entries"]) >= 1
        # A student never receives the administrative issue breakdown.
        assert data["readiness"]["issues"] == []
        assert data["readiness"]["status"] in {"COMPLETE", "INCOMPLETE"}

    def test_teacher_can_browse_the_shared_schedule(self, client, db_session):
        _login(client, "teacher@school.portal")
        _add_section(db_session, section_code="TEACHERVIEW")
        offering = _bcs_offering(db_session)
        resp = client.get(
            f"/api/v1/academics/institutional-timetable?program_offering_id={offering.id}"
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["readiness"]["courses_total"] >= 1

    def test_staff_receive_diagnostics(self, client, db_session):
        _login(client, "admin@school.portal")
        _add_section(db_session, section_code="NOSESSION", scheduled=False)
        offering = _bcs_offering(db_session)
        resp = client.get(
            f"/api/v1/academics/institutional-timetable?program_offering_id={offering.id}"
        )
        assert resp.status_code == 200, resp.text
        issues = {issue["code"] for issue in resp.json()["readiness"]["issues"]}
        # The seeded offering has three sections but only one is scheduled.
        assert "SECTIONS_WITHOUT_SESSIONS" in issues

    def test_unknown_offering_is_not_found(self, client):
        _login(client, "student@school.portal")
        resp = client.get(
            "/api/v1/academics/institutional-timetable"
            "?program_offering_id=00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code == 404
        assert _error_code(resp) == "PROGRAM_OFFERING_NOT_FOUND"

    def test_student_cannot_write_timetable(self, client, db_session):
        _login(client, "student@school.portal")
        resp = client.post(
            "/api/v1/academics/timetable",
            json={
                "class_section_id": str(
                    _add_section(db_session, section_code="WRITE").id
                ),
                "day_of_week": 4,
                "start_time": "09:00",
                "end_time": "10:00",
            },
        )
        assert resp.status_code == 403


class TestSourceImportWorkflow:
    def test_only_staff_may_preview(self, client):
        for email in ("student@school.portal", "teacher@school.portal"):
            _login(client, email)
            resp = client.post("/api/v1/academics/imports/preview")
            assert resp.status_code == 403, f"{email} was allowed to preview"
            client.post("/api/v1/auth/logout")

    def test_preview_apply_browse_and_rollback(self, client, db_session):
        fall = _fall(db_session)
        _login(client, "admin@school.portal")

        preview = client.post("/api/v1/academics/imports/preview")
        assert preview.status_code == 200, preview.text
        staged = preview.json()
        assert staged["status"] == "READY"
        assert staged["counts"]["sections"] == 33
        assert {period["source_id"] for period in staged["periods"]} == {
            "2026-autumn",
            "2025-autumn",
            "2026-spring",
        }
        # Staging writes no academic rows.
        assert (
            db_session.query(ClassSection)
            .filter(ClassSection.source_key.like("ref:v1:section:%"))
            .count()
            == 0
        )

        unconfirmed = client.post(
            f"/api/v1/academics/imports/{staged['batch_id']}/apply",
            json={"confirm": False, "period_map": {"2026-autumn": str(fall.id)}},
        )
        assert unconfirmed.status_code == 400
        assert _error_code(unconfirmed) == "IMPORT_CONFIRMATION_REQUIRED"

        applied = client.post(
            f"/api/v1/academics/imports/{staged['batch_id']}/apply",
            json={"confirm": True, "period_map": {"2026-autumn": str(fall.id)}},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["status"] == "APPLIED"
        db_session.expire_all()
        assert _fall(db_session).source_key == "ref:v1:period:2026-autumn"

        offering = (
            db_session.query(ProgramOffering)
            .filter(ProgramOffering.academic_period_id == fall.id)
            .filter(ProgramOffering.source_key.like("ref:v1:offering:%"))
            .first()
        )
        assert offering is not None
        shared = client.get(
            f"/api/v1/academics/institutional-timetable"
            f"?program_offering_id={offering.id}"
        )
        assert shared.status_code == 200, shared.text
        assert shared.json()["readiness"]["sessions"] > 0

        # The same source cannot be staged into a second batch while applied.
        second = client.post("/api/v1/academics/imports/preview")
        assert second.status_code == 200, second.text
        assert second.json()["already_applied"] is True
        assert second.json()["batch_id"] == staged["batch_id"]

        rolled_back = client.post(
            f"/api/v1/academics/imports/{staged['batch_id']}/rollback"
        )
        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["status"] == "ROLLED_BACK"
        db_session.expire_all()
        assert _fall(db_session).source_key is None
        assert (
            db_session.query(ClassSection)
            .filter(ClassSection.source_key.like("ref:v1:section:%"))
            .count()
            == 0
        )

    def test_management_may_preview(self, client):
        _login(client, "management@school.portal")
        resp = client.post("/api/v1/academics/imports/preview")
        assert resp.status_code == 200, resp.text


class TestLateEnrollmentAuthorization:
    @pytest.fixture
    def earlier_section(self, db_session):
        period = AcademicPeriod(
            name="2025 Autumn",
            code="TEST-2025A",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 1, 15),
            status=AcademicPeriodStatus.COMPLETED,
        )
        db_session.add(period)
        db_session.flush()
        course = db_session.query(Course).filter(Course.code == "CS101").one()
        section = ClassSection(
            course_id=course.id,
            academic_period_id=period.id,
            section_code="LATE",
            source_label="CS101 [late]",
            capacity=None,
            enrolled_count=0,
            status=ClassStatus.ACTIVE,
        )
        db_session.add(section)
        db_session.commit()
        return section

    def test_reason_is_required(self, client, db_session, earlier_section):
        _login(client, "admin@school.portal")
        resp = client.post(
            f"/api/v1/academics/classes/{earlier_section.id}/enrollments",
            json={"student_id": str(_student(db_session).id)},
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "EARLIER_INTAKE_REASON_REQUIRED"

    def test_short_reason_is_rejected(self, client, db_session, earlier_section):
        _login(client, "admin@school.portal")
        resp = client.post(
            f"/api/v1/academics/classes/{earlier_section.id}/enrollments",
            json={
                "student_id": str(_student(db_session).id),
                "authorization_reason": "ok",
            },
        )
        assert resp.status_code == 400
        assert _error_code(resp) == "EARLIER_INTAKE_REASON_REQUIRED"

    def test_authorized_enrolment_records_the_decision(
        self, client, db_session, earlier_section
    ):
        _login(client, "management@school.portal")
        student = _student(db_session)
        resp = client.post(
            f"/api/v1/academics/classes/{earlier_section.id}/enrollments",
            json={
                "student_id": str(student.id),
                "authorization_reason": "Admitted late; approved by the registrar",
                "authorization_reference": "REG-2026-0042",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["authorization_reason"] == (
            "Admitted late; approved by the registrar"
        )
        assert body["authorization_reference"] == "REG-2026-0042"
        assert body["authorized_by_id"] is not None
        assert body["authorized_at"] is not None

        stored = (
            db_session.query(Enrollment)
            .filter(Enrollment.id == body["id"])
            .one()
        )
        assert stored.authorized_by_id is not None

    def test_teacher_cannot_enrol_at_all(self, client, db_session, earlier_section):
        _login(client, "teacher@school.portal")
        resp = client.post(
            f"/api/v1/academics/classes/{earlier_section.id}/enrollments",
            json={
                "student_id": str(_student(db_session).id),
                "authorization_reason": "A sufficiently long reason for the rule",
            },
        )
        assert resp.status_code == 403

    def test_current_intake_needs_no_authorization(self, client, db_session):
        _login(client, "admin@school.portal")
        section = _add_section(db_session, section_code="CURRENT")
        resp = client.post(
            f"/api/v1/academics/classes/{section.id}/enrollments",
            json={"student_id": str(_student(db_session).id)},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["authorization_reason"] is None
