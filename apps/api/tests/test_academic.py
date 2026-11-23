"""Comprehensive academic backend tests."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from app.database.session import SessionLocal
from app.models.academic import (
    ClassSection,
    Enrollment,
    EnrollmentStatus,
)
from app.models.identity import Staff, Student, User
from app.seed_academic import seed_academic

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


@pytest.fixture(scope="module", autouse=True)
def academic_data():
    """Seed the academic structure once, on its own committed session.

    Deliberately *not* seeded inside the per-test ``db_session`` transaction:
    the application seeds on startup (``main.lifespan``) over a *second*
    connection, and when those same rows are already uncommitted in the test's
    transaction that startup insert blocks indefinitely on the uncommitted
    unique row — the suite hangs rather than fails. Committing the seed first,
    the pattern ``test_platform.py`` and ``test_immigration.py`` already use,
    removes the lock. ``seed_academic`` is idempotent, so the startup pass that
    follows (and every later test's startup pass) is a no-op.

    Isolation of test *writes* is unaffected: tests still run inside the
    savepoint transaction from the shared ``db_session`` fixture, so anything
    they create is rolled back.
    """
    db = SessionLocal()
    try:
        seed_academic(db)
    finally:
        db.close()
    yield


def _error_code(resp) -> str:
    """The machine-readable code from the API's structured error envelope.

    Asserting on the code rather than on the message keeps the tests honest
    about the contract the frontend actually consumes: the client localises the
    sentence from the code, so a message-only assertion would pass even if the
    code were missing entirely.
    """
    return resp.json()["error"]["code"]


def _login(client: TestClient, email: str, password: str = "password123") -> dict:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return resp.json()


# ── Structure Tests ──


class TestAcademicStructure:
    """Test major/program/course/period/classroom CRUD."""

    def test_list_majors(self, client):
        _login(client, "admin@school.portal")
        resp = client.get("/api/v1/academics/majors")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) >= 1

    def test_create_major(self, client):
        _login(client, "admin@school.portal")
        resp = client.post(
            "/api/v1/academics/majors",
            json={"code": "NEW", "name": "New Major"},
        )
        assert resp.status_code == 201
        assert resp.json()["code"] == "NEW"

    def test_get_major(self, client):
        _login(client, "admin@school.portal")
        list_resp = client.get("/api/v1/academics/majors")
        major_id = list_resp.json()["items"][0]["id"]
        resp = client.get(f"/api/v1/academics/majors/{major_id}")
        assert resp.status_code == 200

    def test_update_major(self, client):
        _login(client, "admin@school.portal")
        list_resp = client.get("/api/v1/academics/majors")
        major_id = list_resp.json()["items"][0]["id"]
        resp = client.patch(
            f"/api/v1/academics/majors/{major_id}",
            json={"name": "Updated Major"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Major"

    def test_list_programs(self, client):
        _login(client, "admin@school.portal")
        resp = client.get("/api/v1/academics/programs")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1

    def test_create_program(self, client):
        _login(client, "admin@school.portal")
        list_resp = client.get("/api/v1/academics/majors")
        major_id = list_resp.json()["items"][0]["id"]
        resp = client.post(
            "/api/v1/academics/programs",
            json={"major_id": major_id, "code": "NEWP", "name": "New Program"},
        )
        assert resp.status_code == 201

    def test_list_courses(self, client):
        _login(client, "admin@school.portal")
        resp = client.get("/api/v1/academics/courses")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1

    def test_create_course(self, client):
        _login(client, "admin@school.portal")
        list_resp = client.get("/api/v1/academics/programs")
        program_id = list_resp.json()["items"][0]["id"]
        resp = client.post(
            "/api/v1/academics/courses",
            json={"program_id": program_id, "code": "NEWC", "name": "New Course", "credits": 3},
        )
        assert resp.status_code == 201

    def test_list_periods(self, client):
        _login(client, "admin@school.portal")
        resp = client.get("/api/v1/academics/periods")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1

    def test_create_period(self, client):
        _login(client, "admin@school.portal")
        resp = client.post(
            "/api/v1/academics/periods",
            json={
                "name": "Spring 2027",
                "code": "2027-SPR",
                "start_date": "2027-01-10",
                "end_date": "2027-05-15",
            },
        )
        assert resp.status_code == 201

    def test_list_classrooms(self, client):
        _login(client, "admin@school.portal")
        resp = client.get("/api/v1/academics/classrooms")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1

    def test_create_classroom(self, client):
        _login(client, "admin@school.portal")
        resp = client.post(
            "/api/v1/academics/classrooms",
            json={"room_code": "NEW-R1", "name": "New Room", "capacity": 50},
        )
        assert resp.status_code == 201


# ── Relationship Tests ──


class TestAcademicRelationships:
    """Test class section relationships."""

    def test_list_classes(self, client):
        _login(client, "admin@school.portal")
        resp = client.get("/api/v1/academics/classes")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1

    def test_create_class_section(self, client):
        _login(client, "admin@school.portal")
        courses = client.get("/api/v1/academics/courses").json()
        periods = client.get("/api/v1/academics/periods").json()
        resp = client.post(
            "/api/v1/academics/classes",
            json={
                "course_id": courses["items"][0]["id"],
                "academic_period_id": periods["items"][0]["id"],
                "section_code": "NEW",
                "capacity": 30,
            },
        )
        assert resp.status_code == 201

    def test_list_teachers(self, client):
        _login(client, "admin@school.portal")
        classes = client.get("/api/v1/academics/classes").json()
        class_id = classes["items"][0]["id"]
        resp = client.get(f"/api/v1/academics/classes/{class_id}/teachers")
        assert resp.status_code == 200

    def test_assign_teacher(self, client):
        _login(client, "admin@school.portal")
        classes = client.get("/api/v1/academics/classes").json()
        class_id = classes["items"][0]["id"]
        from app.database.session import SessionLocal
        db = SessionLocal()
        staff = db.query(Staff).first()
        staff_id = str(staff.id) if staff else None
        db.close()
        if staff_id:
            resp = client.post(
                f"/api/v1/academics/classes/{class_id}/teachers",
                json={"staff_id": staff_id, "role": "PRIMARY"},
            )
            # 201 if new, 400 if already assigned
            assert resp.status_code in (201, 400)

    def test_list_enrollments(self, client):
        _login(client, "admin@school.portal")
        classes = client.get("/api/v1/academics/classes").json()
        class_id = classes["items"][0]["id"]
        resp = client.get(f"/api/v1/academics/classes/{class_id}/enrollments")
        assert resp.status_code == 200

    def test_enroll_student(self, client):
        _login(client, "admin@school.portal")
        classes = client.get("/api/v1/academics/classes").json()
        # Find a class that's not full
        class_id = None
        for cs in classes["items"]:
            if cs["enrolled_count"] < cs["capacity"]:
                class_id = cs["id"]
                break
        assert class_id is not None, "No available class found"

        # Find a student
        from app.database.session import SessionLocal
        db = SessionLocal()
        student = db.query(Student).first()
        student_id = str(student.id) if student else None
        db.close()

        if student_id:
            resp = client.post(
                f"/api/v1/academics/classes/{class_id}/enrollments",
                json={"student_id": student_id},
            )
            assert resp.status_code in (201, 400)  # 400 if already enrolled


# ── Enrollment Integrity Tests ──


class TestEnrollmentIntegrity:
    """Test enrollment business rules."""

    def test_duplicate_enrollment_rejected(self, client):
        _login(client, "admin@school.portal")
        classes = client.get("/api/v1/academics/classes").json()
        class_id = classes["items"][0]["id"]

        from app.database.session import SessionLocal
        db = SessionLocal()
        enrollment = db.query(Enrollment).filter(
            Enrollment.class_section_id == uuid.UUID(class_id)
        ).first()
        student_id = str(enrollment.student_id) if enrollment else None
        db.close()

        if student_id:
            resp = client.post(
                f"/api/v1/academics/classes/{class_id}/enrollments",
                json={"student_id": student_id},
            )
            assert resp.status_code == 400

    def test_drop_enrollment(self, client):
        _login(client, "admin@school.portal")
        classes = client.get("/api/v1/academics/classes").json()
        class_id = classes["items"][0]["id"]
        enrollments = client.get(f"/api/v1/academics/classes/{class_id}/enrollments").json()
        if len(enrollments) > 0:
            enrollment_id = enrollments[0]["id"]
            resp = client.post(
                f"/api/v1/academics/classes/{class_id}/enrollments/{enrollment_id}/drop",
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "DROPPED"


# ── Timetable Conflict Detection ──


class TestTimetableConflicts:
    """Test timetable conflict detection."""

    def test_list_timetable(self, client):
        _login(client, "admin@school.portal")
        resp = client.get("/api/v1/academics/timetable")
        if resp.status_code != 200:
            print(f"Timetable response: {resp.status_code} {resp.text}")
        assert resp.status_code == 200

    def test_create_valid_timetable(self, client):
        _login(client, "admin@school.portal")
        classes = client.get("/api/v1/academics/classes").json()
        classrooms = client.get("/api/v1/academics/classrooms").json()
        if classes["items"] and classrooms["items"]:
            resp = client.post(
                "/api/v1/academics/timetable",
                json={
                    "class_section_id": classes["items"][0]["id"],
                    "classroom_id": classrooms["items"][0]["id"],
                    "day_of_week": 1,  # Tuesday
                    "start_time": "14:00:00",
                    "end_time": "15:30:00",
                },
            )
            assert resp.status_code == 201

    # The conflict cases below build their own course, sections, rooms and
    # teacher assignment instead of hunting the seed for a pre-existing clash.
    # The earlier versions skipped when the seed happened to lack one and could
    # not distinguish a classroom clash from a teacher clash, because they
    # reused the same room either way.

    def _scenario(self, client, db_session, code: str) -> dict:
        """Two sections, two rooms and one teacher shared by both sections."""
        course = client.post(
            "/api/v1/academics/courses",
            json={"code": f"TC{code}", "name": f"Timetable {code}"},
        ).json()
        period = client.post(
            "/api/v1/academics/periods",
            json={
                "name": f"Period {code}",
                "code": f"TP{code}",
                "start_date": "2030-01-06",
                "end_date": "2030-05-31",
            },
        ).json()
        sections = [
            client.post(
                "/api/v1/academics/classes",
                json={
                    "course_id": course["id"],
                    "academic_period_id": period["id"],
                    "section_code": suffix,
                    "capacity": 30,
                },
            ).json()
            for suffix in ("A", "B")
        ]
        rooms = [
            client.post(
                "/api/v1/academics/classrooms",
                json={"room_code": f"T{code}-{n}", "capacity": 40},
            ).json()
            for n in (1, 2)
        ]
        staff = db_session.query(Staff).first()
        for section in sections:
            client.post(
                f"/api/v1/academics/classes/{section['id']}/teachers",
                json={"staff_id": str(staff.id), "role": "PRIMARY"},
            )
        return {"sections": sections, "rooms": rooms}

    def test_overlapping_same_section_rejected(self, client, db_session):
        """One section cannot be scheduled twice at the same time."""
        _login(client, "admin@school.portal")
        s = self._scenario(client, db_session, "SS")
        payload = {
            "class_section_id": s["sections"][0]["id"],
            "classroom_id": s["rooms"][0]["id"],
            "day_of_week": 0,
            "start_time": "09:00:00",
            "end_time": "10:30:00",
        }
        assert client.post("/api/v1/academics/timetable", json=payload).status_code == 201

        # A second slot for the same section, in a different room.
        clash = {**payload, "classroom_id": s["rooms"][1]["id"]}
        resp = client.post("/api/v1/academics/timetable", json=clash)
        assert resp.status_code == 409
        assert _error_code(resp) == "TIMETABLE_SECTION_CONFLICT"

    def test_overlapping_teacher_rejected(self, client, db_session):
        """One teacher cannot be in two rooms at once."""
        _login(client, "admin@school.portal")
        s = self._scenario(client, db_session, "TT")
        first = {
            "class_section_id": s["sections"][0]["id"],
            "classroom_id": s["rooms"][0]["id"],
            "day_of_week": 0,
            "start_time": "09:00:00",
            "end_time": "10:30:00",
        }
        assert client.post("/api/v1/academics/timetable", json=first).status_code == 201

        # Different section, different room, same teacher, overlapping window.
        resp = client.post(
            "/api/v1/academics/timetable",
            json={**first, "class_section_id": s["sections"][1]["id"],
                  "classroom_id": s["rooms"][1]["id"]},
        )
        assert resp.status_code == 409
        assert _error_code(resp) == "TIMETABLE_TEACHER_CONFLICT"

    def test_overlapping_classroom_rejected(self, client, db_session):
        """One room cannot hold two classes at once."""
        _login(client, "admin@school.portal")
        s = self._scenario(client, db_session, "RR")
        first = {
            "class_section_id": s["sections"][0]["id"],
            "classroom_id": s["rooms"][0]["id"],
            "day_of_week": 2,
            "start_time": "13:00:00",
            "end_time": "14:30:00",
        }
        assert client.post("/api/v1/academics/timetable", json=first).status_code == 201

        resp = client.post(
            "/api/v1/academics/timetable",
            json={**first, "class_section_id": s["sections"][1]["id"]},
        )
        assert resp.status_code == 409
        assert _error_code(resp) == "TIMETABLE_CLASSROOM_CONFLICT"

    def test_back_to_back_slots_allowed(self, client, db_session):
        """Adjacent slots (end == next start) are not an overlap."""
        _login(client, "admin@school.portal")
        s = self._scenario(client, db_session, "BJ")
        shared = {"class_section_id": s["sections"][0]["id"],
                  "classroom_id": s["rooms"][0]["id"], "day_of_week": 3}
        first = client.post(
            "/api/v1/academics/timetable",
            json={**shared, "start_time": "09:00:00", "end_time": "10:00:00"},
        )
        assert first.status_code == 201
        second = client.post(
            "/api/v1/academics/timetable",
            json={**shared, "start_time": "10:00:00", "end_time": "11:00:00"},
        )
        assert second.status_code == 201, second.text

    def test_create_with_invalid_interval_rejected(self, client, db_session):
        """An inverted interval is refused on create too, with the same code.

        It used to surface as a schema-level 422 on create and a coded 409 on
        update, so the client had to handle one rule two ways.
        """
        _login(client, "admin@school.portal")
        s = self._scenario(client, db_session, "II")
        resp = client.post(
            "/api/v1/academics/timetable",
            json={
                "class_section_id": s["sections"][0]["id"],
                "classroom_id": s["rooms"][0]["id"],
                "day_of_week": 0,
                "start_time": "11:00:00",
                "end_time": "10:00:00",
            },
        )
        assert resp.status_code == 409
        assert _error_code(resp) == "TIMETABLE_INVALID_INTERVAL"

    def test_update_to_invalid_interval_rejected(self, client, db_session):
        """A PATCH that inverts the interval is refused.

        The field-level validator cannot see this: supplying only `start_time`
        produces a payload where both times *are* valid on their own.
        """
        _login(client, "admin@school.portal")
        s = self._scenario(client, db_session, "IV")
        entry = client.post(
            "/api/v1/academics/timetable",
            json={"class_section_id": s["sections"][0]["id"],
                  "classroom_id": s["rooms"][0]["id"], "day_of_week": 4,
                  "start_time": "09:00:00", "end_time": "10:00:00"},
        ).json()

        resp = client.patch(
            f"/api/v1/academics/timetable/{entry['id']}",
            json={"start_time": "11:00:00"},
        )
        assert resp.status_code == 409
        assert _error_code(resp) == "TIMETABLE_INVALID_INTERVAL"

    def test_scheduling_into_unavailable_classroom_rejected(self, client, db_session):
        """A room under maintenance cannot host a class."""
        _login(client, "admin@school.portal")
        s = self._scenario(client, db_session, "UM")
        client.patch(
            f"/api/v1/academics/classrooms/{s['rooms'][0]['id']}",
            json={"status": "MAINTENANCE"},
        )
        resp = client.post(
            "/api/v1/academics/timetable",
            json={"class_section_id": s["sections"][0]["id"],
                  "classroom_id": s["rooms"][0]["id"], "day_of_week": 1,
                  "start_time": "09:00:00", "end_time": "10:00:00"},
        )
        assert resp.status_code == 409
        assert _error_code(resp) == "CLASSROOM_NOT_AVAILABLE"

    def test_move_entry_to_another_section(self, client, db_session):
        """Correcting a mis-booked slot moves the entry rather than replacing it."""
        _login(client, "admin@school.portal")
        s = self._scenario(client, db_session, "MV")
        entry = client.post(
            "/api/v1/academics/timetable",
            json={"class_section_id": s["sections"][0]["id"],
                  "classroom_id": s["rooms"][0]["id"], "day_of_week": 1,
                  "start_time": "15:00:00", "end_time": "16:00:00"},
        ).json()

        resp = client.patch(
            f"/api/v1/academics/timetable/{entry['id']}",
            json={"class_section_id": s["sections"][1]["id"],
                  "day_of_week": 3, "classroom_id": s["rooms"][1]["id"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == entry["id"]
        assert resp.json()["class_section_id"] == s["sections"][1]["id"]
        assert resp.json()["day_of_week"] == 3


# ── Teacher Scope Tests ──


class TestTeacherScope:
    """Test teacher scope authorization."""

    def test_teacher_access_own_class(self, client):
        _login(client, "teacher@school.portal")
        resp = client.get("/api/v1/academics/classes")
        assert resp.status_code == 200
        # Teacher should see at least their assigned classes

    def test_student_can_view_classes(self, client):
        """Students with academic.view can list classes (read-only)."""
        _login(client, "student@school.portal")
        resp = client.get("/api/v1/academics/classes")
        assert resp.status_code == 200

    def test_student_own_academic(self, client):
        _login(client, "student@school.portal")
        from app.database.session import SessionLocal
        db = SessionLocal()
        user = db.query(User).filter(User.email == "student@school.portal").first()
        student = db.query(Student).filter(Student.user_id == user.id).first()
        student_id = str(student.id) if student else None
        db.close()

        if student_id:
            resp = client.get(f"/api/v1/academics/students/{student_id}")
            assert resp.status_code == 200

    def test_student_other_denied(self, client):
        _login(client, "student@school.portal")
        from app.database.session import SessionLocal
        db = SessionLocal()
        user = db.query(User).filter(
            User.email == "student@school.portal"
        ).first()
        current = db.query(Student).filter(
            Student.user_id == user.id
        ).first()
        for s in db.query(Student).all():
            if s.id != current.id:
                other_id = str(s.id)
                db.close()
                resp = client.get(f"/api/v1/academics/students/{other_id}")
                assert resp.status_code == 403
                return
        db.close()
        pytest.skip("Only one student in database")

    def test_management_can_read_academics(self, client):
        _login(client, "management@school.portal")
        assert client.get("/api/v1/academics/classes").status_code == 200

    def test_management_can_administer_structure(self, client):
        """Management can set up everything a class section depends on.

        The four permissions asserted here were Admin-only until Stage 8C, which
        left management able to create a class section but unable to create the
        academic period it must belong to.
        """
        _login(client, "management@school.portal")
        resp = client.post(
            "/api/v1/academics/periods",
            json={
                "name": "Mgmt Period",
                "code": "MGT1",
                "start_date": "2031-01-06",
                "end_date": "2031-05-30",
            },
        )
        assert resp.status_code == 201, resp.text

        resp = client.post(
            "/api/v1/academics/classrooms",
            json={"room_code": "MGMT-1", "capacity": 30},
        )
        assert resp.status_code == 201, resp.text

        major_id = client.get("/api/v1/academics/majors").json()["items"][0]["id"]
        resp = client.post(
            "/api/v1/academics/programs",
            json={"major_id": major_id, "code": "MGPR", "name": "Mgmt Program"},
        )
        assert resp.status_code == 201, resp.text

    def test_teacher_denied_structure_administration(self, client):
        """Teaching staff do not configure the academic structure."""
        _login(client, "teacher@school.portal")
        resp = client.post(
            "/api/v1/academics/classrooms",
            json={"room_code": "TCH-1", "capacity": 30},
        )
        assert resp.status_code == 403


# ── Student Academic Access ──


class TestStudentAcademic:
    """Test student academic endpoints."""

    def test_student_academic_overview(self, client):
        _login(client, "student@school.portal")
        from app.database.session import SessionLocal
        db = SessionLocal()
        user = db.query(User).filter(User.email == "student@school.portal").first()
        student = db.query(Student).filter(Student.user_id == user.id).first()
        student_id = str(student.id) if student else None
        db.close()

        if student_id:
            resp = client.get(f"/api/v1/academics/students/{student_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert "enrolled_classes" in data
            assert "timetable" in data

    def test_student_timetable(self, client):
        _login(client, "student@school.portal")
        from app.database.session import SessionLocal
        db = SessionLocal()
        user = db.query(User).filter(User.email == "student@school.portal").first()
        student = db.query(Student).filter(Student.user_id == user.id).first()
        student_id = str(student.id) if student else None
        db.close()

        if student_id:
            resp = client.get(f"/api/v1/academics/students/{student_id}/timetable")
            assert resp.status_code == 200

    def test_student_attendance(self, client):
        _login(client, "student@school.portal")
        from app.database.session import SessionLocal
        db = SessionLocal()
        user = db.query(User).filter(User.email == "student@school.portal").first()
        student = db.query(Student).filter(Student.user_id == user.id).first()
        student_id = str(student.id) if student else None
        db.close()

        if student_id:
            resp = client.get(f"/api/v1/academics/students/{student_id}/attendance")
            assert resp.status_code == 200

    def test_student_grades(self, client):
        _login(client, "student@school.portal")
        from app.database.session import SessionLocal
        db = SessionLocal()
        user = db.query(User).filter(User.email == "student@school.portal").first()
        student = db.query(Student).filter(Student.user_id == user.id).first()
        student_id = str(student.id) if student else None
        db.close()

        if student_id:
            resp = client.get(f"/api/v1/academics/students/{student_id}/grades")
            assert resp.status_code == 200


# ── Attendance Tests ──


class TestAttendance:
    """Test attendance recording."""

    def test_record_attendance(self, client):
        _login(client, "admin@school.portal")
        from app.database.session import SessionLocal
        db = SessionLocal()
        # Find a class section with an enrollment
        enrollment = db.query(Enrollment).filter(
            Enrollment.status == EnrollmentStatus.ENROLLED,
        ).first()
        if enrollment:
            cs_id = str(enrollment.class_section_id)
            student_id = str(enrollment.student_id)
            db.close()
            resp = client.post(
                f"/api/v1/academics/classes/{cs_id}/attendance",
                json={
                    "session_date": "2026-09-20",
                    "records": [
                        {
                            "student_id": student_id,
                            "status": "PRESENT",
                        }
                    ],
                },
            )
            assert resp.status_code in (201, 400)  # 400 if already recorded
        else:
            db.close()

    def test_student_cannot_record_attendance(self, client):
        _login(client, "student@school.portal")
        from app.database.session import SessionLocal
        db = SessionLocal()
        cs = db.query(ClassSection).first()
        db.close()
        if cs:
            resp = client.post(
                f"/api/v1/academics/classes/{cs.id}/attendance",
                json={"session_date": "2026-09-20", "records": []},
            )
            assert resp.status_code == 403


# ── Grade Tests ──


class TestGrades:
    """Test grade recording."""

    def test_list_assessments(self, client):
        _login(client, "admin@school.portal")
        classes = client.get("/api/v1/academics/classes").json()
        if classes["items"]:
            resp = client.get(
                f"/api/v1/academics/classes/{classes['items'][0]['id']}/assessments"
            )
            assert resp.status_code == 200

    def test_create_assessment(self, client):
        _login(client, "admin@school.portal")
        classes = client.get("/api/v1/academics/classes").json()
        if classes["items"]:
            resp = client.post(
                f"/api/v1/academics/classes/{classes['items'][0]['id']}/assessments",
                json={
                    "name": "Quiz 1",
                    "assessment_type": "QUIZ",
                    "max_score": 100.0,
                    "weight": 0.1,
                },
            )
            assert resp.status_code in (201, 400)

    def test_student_cannot_create_assessment(self, client):
        _login(client, "student@school.portal")
        classes = client.get("/api/v1/academics/classes")
        if classes.status_code == 200 and classes.json()["items"]:
            resp = client.post(
                f"/api/v1/academics/classes/{classes.json()['items'][0]['id']}/assessments",
                json={"name": "X", "assessment_type": "QUIZ", "max_score": 100, "weight": 0.1},
            )
            assert resp.status_code == 403


# ── Authorization Tests ──


class TestAcademicAuthorization:
    """Test RBAC for academic endpoints."""

    def test_admin_full_access(self, client):
        _login(client, "admin@school.portal")
        for endpoint in [
            "/api/v1/academics/majors",
            "/api/v1/academics/programs",
            "/api/v1/academics/courses",
            "/api/v1/academics/periods",
            "/api/v1/academics/classrooms",
            "/api/v1/academics/classes",
            "/api/v1/academics/timetable",
        ]:
            resp = client.get(endpoint)
            assert resp.status_code == 200, f"Failed: {endpoint}"

    def test_student_denied_manage(self, client):
        _login(client, "student@school.portal")
        resp = client.post(
            "/api/v1/academics/majors",
            json={"code": "X", "name": "X"},
        )
        assert resp.status_code == 403

    def test_unauthenticated_denied(self, client):
        resp = client.get("/api/v1/academics/majors")
        assert resp.status_code == 401
