"""Academic intakes as real periods, and timetable reconciliation.

The institution thinks in intake names; V2 must not. These tests pin the
mapping: an intake is an ``AcademicPeriod`` with intake-specific offerings, a
future intake cannot be activated, re-planning is idempotent, and the timetable
reconciliation reports structural problems without writing anything.
"""

from __future__ import annotations

import uuid
from datetime import date, time

INTAKES = [
    {
        "code": "2025-FALL",
        "name": "Fall 2025",
        "start_date": "2025-09-01",
        "end_date": "2025-12-20",
        "status": "PLANNED",
        "offerings": [{"source_id": "cs-2025f", "name": "Computer Science"}],
    },
    {
        "code": "2026-SPRING",
        "name": "Spring 2026",
        "start_date": "2026-02-01",
        "end_date": "2026-06-15",
        "status": "PLANNED",
        "offerings": [{"source_id": "cs-2026s", "name": "Computer Science"}],
    },
    {
        "code": "2026-FALL-X",
        "name": "Fall 2026",
        "start_date": "2026-09-01",
        "end_date": "2026-12-20",
        "status": "ACTIVE",
        "offerings": [{"source_id": "cs-2026f", "name": "Computer Science"}],
    },
    {
        "code": "2027-SPRING",
        "name": "Spring 2027",
        "start_date": "2027-02-01",
        "end_date": "2027-06-15",
        "status": "PLANNED",
        "offerings": [{"source_id": "cs-2027s", "name": "Computer Science"}],
    },
]


def _login(client, email: str = "admin@school.portal", password: str = "password123"):
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text


def _plan(client, intakes):
    return client.post("/api/v1/academics/intakes/plan", json={"intakes": intakes})


class TestIntakePlanning:
    def test_four_intakes_are_planned_once(self, client, db_session):
        from app.models.academic import AcademicPeriod, ProgramOffering

        _login(client)
        first = _plan(client, INTAKES)
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["created"] == 4
        assert body["conflicts"] == 0

        second = _plan(client, INTAKES).json()
        assert second["created"] == 0
        assert second["existing"] == 4

        codes = {item["code"] for item in INTAKES}
        periods = (
            db_session.query(AcademicPeriod)
            .filter(AcademicPeriod.code.in_(codes))
            .all()
        )
        assert len(periods) == 4
        offerings = (
            db_session.query(ProgramOffering)
            .filter(ProgramOffering.source_key.like("intake:%"))
            .count()
        )
        assert offerings >= 4

        # 2027 Spring exists as an upcoming intake, not a started one.
        spring_2027 = next(period for period in periods if period.code == "2027-SPRING")
        assert spring_2027.status == "PLANNED"

    def test_future_intake_cannot_be_active(self, client):
        _login(client)
        payload = [
            {
                "code": "2099-FALL",
                "name": "Fall 2099",
                "start_date": "2099-09-01",
                "end_date": "2099-12-20",
                "status": "ACTIVE",
            }
        ]
        response = _plan(client, payload)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "FUTURE_INTAKE_CANNOT_BE_ACTIVE"

    def test_changed_dates_are_a_conflict_not_an_overwrite(self, client, db_session):
        from app.models.academic import AcademicPeriod

        _login(client)
        assert _plan(client, INTAKES).status_code == 200

        changed = [dict(INTAKES[0], start_date="2025-09-15")]
        body = _plan(client, changed).json()
        assert body["conflicts"] == 1
        assert body["intakes"][0]["status"] == "CONFLICT"
        assert body["intakes"][0]["fields"] == ["start_date"]

        db_session.expire_all()
        period = (
            db_session.query(AcademicPeriod)
            .filter(AcademicPeriod.code == "2025-FALL")
            .first()
        )
        assert period.start_date == date(2025, 9, 1)

    def test_teacher_cannot_plan_intakes(self, client):
        _login(client, "teacher@school.portal")
        assert _plan(client, INTAKES).status_code == 403


def _fixture(db_session):
    """One intake with two linked sections, two slots and a duplicate."""
    from app.models.academic import (
        AcademicPeriod,
        AcademicPeriodStatus,
        Classroom,
        ClassroomStatus,
        ClassSection,
        ClassSectionProgramOffering,
        Course,
        ProgramOffering,
        TimetableEntry,
    )
    from app.models.identity import Staff

    suffix = uuid.uuid4().hex[:8]
    period = AcademicPeriod(
        code=f"REC-{suffix}",
        name="Reconciliation fixture",
        start_date=date(2030, 9, 1),
        end_date=date(2030, 12, 20),
        status=AcademicPeriodStatus.PLANNED,
    )
    db_session.add(period)
    db_session.flush()

    offering = ProgramOffering(
        academic_period_id=period.id,
        source_id=f"off-{suffix}",
        source_key=f"test:offering:{suffix}",
        name="Fixture programme",
    )
    course = Course(code=f"RC-{suffix}", name="Reconciliation Course")
    room = Classroom(room_code=f"RC-{suffix}", status=ClassroomStatus.AVAILABLE)
    db_session.add_all([offering, course, room])
    db_session.flush()

    section = ClassSection(
        course_id=course.id,
        academic_period_id=period.id,
        section_code="A",
    )
    other = ClassSection(
        course_id=course.id,
        academic_period_id=period.id,
        section_code="B",
    )
    unlinked = ClassSection(
        course_id=course.id,
        academic_period_id=period.id,
        section_code="C",
    )
    db_session.add_all([section, other, unlinked])
    db_session.flush()

    db_session.add_all(
        [
            ClassSectionProgramOffering(
                class_section_id=section.id, program_offering_id=offering.id
            ),
            ClassSectionProgramOffering(
                class_section_id=other.id, program_offering_id=offering.id
            ),
        ]
    )

    staff = db_session.query(Staff).first()
    if staff is not None:
        from app.models.academic import TeacherAssignment

        db_session.add(
            TeacherAssignment(class_section_id=section.id, staff_id=staff.id)
        )

    base = TimetableEntry(
        class_section_id=section.id,
        classroom_id=room.id,
        day_of_week=0,
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    overlapping_room = TimetableEntry(
        class_section_id=other.id,
        classroom_id=room.id,
        day_of_week=0,
        start_time=time(9, 30),
        end_time=time(10, 30),
    )
    duplicate = TimetableEntry(
        class_section_id=section.id,
        classroom_id=None,
        day_of_week=0,
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    invalid = TimetableEntry(
        class_section_id=other.id,
        classroom_id=None,
        day_of_week=1,
        start_time=time(11, 0),
        end_time=time(9, 0),
    )
    db_session.add_all([base, overlapping_room, duplicate, invalid])
    db_session.commit()
    return period, section, other, unlinked


class TestTimetableReconciliation:
    def test_findings_are_reported_without_writing(self, client, db_session):
        from app.models.academic import TimetableEntry

        _login(client)
        period, _section, _other, _unlinked = _fixture(db_session)

        before = db_session.query(TimetableEntry).count()
        response = client.get(
            "/api/v1/academics/timetable/reconciliation",
            params={"period_id": str(period.id)},
        )
        assert response.status_code == 200, response.text
        body = response.json()

        codes = {finding["code"] for finding in body["findings"]}
        assert "TIMETABLE_INVALID_INTERVAL" in codes
        assert "TIMETABLE_DUPLICATE_SLOT" in codes
        assert "TIMETABLE_ROOM_DOUBLE_BOOKED" in codes
        assert "SECTION_WITHOUT_OFFERING" in codes
        assert "SECTION_WITHOUT_TIMETABLE" in codes
        assert body["status"] == "BLOCKING"
        assert body["destructive_actions"] is False

        db_session.expire_all()
        assert db_session.query(TimetableEntry).count() == before

    def test_scoped_report_ignores_other_intakes(self, client, db_session):
        from app.models.academic import AcademicPeriod

        _login(client)
        _fixture(db_session)
        other_period = (
            db_session.query(AcademicPeriod)
            .filter(AcademicPeriod.code == "2026-FALL")
            .first()
        )
        assert other_period is not None
        body = client.get(
            "/api/v1/academics/timetable/reconciliation",
            params={"period_id": str(other_period.id)},
        ).json()
        assert body["scope"]["period_codes"] == ["2026-FALL"]
        codes = {finding["code"] for finding in body["findings"]}
        assert "TIMETABLE_ROOM_DOUBLE_BOOKED" not in codes

    def test_teacher_cannot_read_the_reconciliation_report(self, client):
        _login(client, "teacher@school.portal")
        response = client.get("/api/v1/academics/timetable/reconciliation")
        assert response.status_code == 403


def _onboard_student(client, db_session, *, number: str | None = None):
    """Create a student through the real onboarding workflow and sign in."""
    from app.models.identity import Student

    number = number or f"SCOPE-{uuid.uuid4().hex[:8].upper()}"
    email = f"{number.lower()}@example.com"
    response = client.post(
        "/api/v1/students/onboard",
        json={
            "student_id": number,
            "first_name": "Scope",
            "last_name": "Tester",
            "email": email,
        },
    )
    assert response.status_code == 201, response.text
    password = response.json()["temporary_password"]
    db_session.expire_all()
    student = db_session.query(Student).filter(Student.student_id == number).first()

    # An onboarded account must retire its temporary password before the
    # portal opens; do that so the test can exercise the student's own view.
    _login(client, email, password)
    changed = client.post(
        "/api/v1/auth/password/change",
        json={
            "current_password": password,
            "new_password": "ScopeStudent1!Pass",
        },
    )
    assert changed.status_code == 200, changed.text
    return student, email, "ScopeStudent1!Pass"


def _make_placement(db_session, student, period, offering):
    """A minimal live admission + placement, as the migration would create."""

    from app.models.admission import AcademicAdmission, AcademicPlacement
    from app.models.identity import User

    actor = db_session.query(User).filter(User.email == "admin@school.portal").first()
    admission = AcademicAdmission(
        student_id=student.id,
        admission_intake_id=period.id,
        admitted_program_id=offering.program_id,
        admitted_program_offering_id=offering.id,
        status="ADMITTED",
        initial_status="ADMITTED",
        record_origin="MIGRATED",
        created_by_id=actor.id,
    )
    db_session.add(admission)
    db_session.flush()
    placement = AcademicPlacement(
        student_id=student.id,
        admission_id=admission.id,
        academic_period_id=period.id,
        program_offering_id=offering.id,
        effective_from=period.start_date,
        created_by_id=actor.id,
    )
    db_session.add(placement)
    db_session.commit()
    return admission, placement


class TestIntakeScoping:
    def test_cross_intake_enrollment_is_reported(self, client, db_session):
        from app.models.academic import Enrollment

        _login(client)
        period, section, _other, _unlinked = _fixture(db_session)
        student, _email, _password = _onboard_student(client, db_session)

        # Give the student a placement in a different intake.
        home_period = __import__("app.models.academic", fromlist=["AcademicPeriod"]).AcademicPeriod(
            code=f"HOME-{uuid.uuid4().hex[:6]}",
            name="Home intake",
            start_date=date(2027, 2, 1),
            end_date=date(2027, 6, 15),
            status="PLANNED",
        )
        db_session.add(home_period)
        db_session.flush()
        from app.models.academic import ProgramOffering

        home_offering = ProgramOffering(
            academic_period_id=home_period.id,
            source_id=f"home-{uuid.uuid4().hex[:6]}",
            source_key=f"test:home:{uuid.uuid4().hex}",
            name="Home programme",
        )
        db_session.add(home_offering)
        db_session.commit()
        _make_placement(db_session, student, home_period, home_offering)

        # An enrollment in the fixture intake is the anomaly.
        db_session.add(Enrollment(student_id=student.id, class_section_id=section.id))
        db_session.commit()

        _login(client)
        body = client.get(
            "/api/v1/academics/timetable/reconciliation",
            params={"period_id": str(period.id)},
        ).json()
        codes = {finding["code"] for finding in body["findings"]}
        assert "CROSS_INTAKE_ENROLLMENT" in codes

    def test_student_timetable_follows_enrollment_and_period(self, client, db_session):
        from app.models.academic import Enrollment

        _login(client)
        period, section, other, _unlinked = _fixture(db_session)
        student, email, password = _onboard_student(client, db_session)

        _login(client, email, password)
        before_response = client.get(
            f"/api/v1/academics/students/{student.id}/timetable",
            params={"period_id": str(period.id)},
        )
        assert before_response.status_code == 200, before_response.text
        assert before_response.json()["items"] == []

        _login(client)
        db_session.add(Enrollment(student_id=student.id, class_section_id=section.id))
        db_session.commit()

        _login(client, email, password)
        visible = client.get(
            f"/api/v1/academics/students/{student.id}/timetable",
            params={"period_id": str(period.id)},
        ).json()
        assert visible["items"]
        assert {item["class_section_id"] for item in visible["items"]} == {str(section.id)}

        # A different section of the same intake that they are not enrolled in
        # must not appear, even though it exists in the same period.
        assert str(other.id) not in {item["class_section_id"] for item in visible["items"]}

    def test_student_cannot_read_another_students_timetable(self, client, db_session):
        _login(client)
        first, _email, _password = _onboard_student(client, db_session)
        _login(client)
        second, email_two, password_two = _onboard_student(client, db_session)

        _login(client, email_two, password_two)
        response = client.get(f"/api/v1/academics/students/{first.id}/timetable")
        assert response.status_code == 403

    def test_teacher_sees_only_assigned_sections(self, client, db_session):
        from app.models.academic import TeacherAssignment
        from app.models.identity import Staff, User

        _login(client)
        period, section, other, _unlinked = _fixture(db_session)

        teacher_user = (
            db_session.query(User).filter(User.email == "teacher@school.portal").first()
        )
        staff = db_session.query(Staff).filter(Staff.user_id == teacher_user.id).first()
        if staff is None:
            staff = Staff(
                user_id=teacher_user.id, first_name="Tess", last_name="Teacher"
            )
            db_session.add(staff)
            db_session.flush()
        db_session.add(TeacherAssignment(class_section_id=section.id, staff_id=staff.id))
        db_session.commit()

        _login(client, "teacher@school.portal")
        body = client.get(
            "/api/v1/academics/timetable", params={"period_id": str(period.id)}
        ).json()
        section_ids = {item["class_section_id"] for item in body["items"]}
        assert section_ids == {str(section.id)}
        assert str(other.id) not in section_ids
