"""Phase 2 integrity remediation tests.

The concurrency cases use independent ``SessionLocal`` connections, not the
savepoint session used by API tests. That is deliberate: a savepoint hides the
row locks from the other worker and would make a race test meaningless.
"""

from __future__ import annotations

import threading
import uuid
from datetime import time
from queue import Queue

import pytest

from app.database.session import SessionLocal
from app.models.academic import (
    AcademicPeriod,
    Classroom,
    ClassSection,
    ClassStatus,
    Course,
    Enrollment,
    EnrollmentStatus,
    Grade,
    TeacherAssignment,
    TimetableEntry,
)
from app.models.audit import AuditLog
from app.models.identity import Role, Staff, Student, StudentStatus, User
from app.models.platform import Notification, NotificationType
from app.schemas.academic import EnrollmentCreate, TeacherAssignmentCreate
from app.seed_academic import seed_academic
from app.services import academic as academic_svc
from app.services.academic_import import (
    DEFAULT_SOURCE,
    apply_import,
    prepare_import,
    room_key,
)

API = "/api/v1"
PASSWORD = "password123"


@pytest.fixture(scope="module", autouse=True)
def academic_seed():
    db = SessionLocal()
    try:
        seed_academic(db)
    finally:
        db.close()
    yield


def _login(client, email: str) -> None:
    response = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def _logout(client) -> None:
    client.post(f"{API}/auth/logout")


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _class_with_teacher(client) -> dict:
    classes = client.get(f"{API}/academics/classes?page_size=100").json()["items"]
    return next(
        item
        for item in classes
        if item["teachers"] and item["enrolled_count"] > 0
    )


def _enrolled_student(client, class_id: str) -> str:
    enrollments = client.get(
        f"{API}/academics/classes/{class_id}/enrollments"
    ).json()
    return next(
        item["student_id"]
        for item in enrollments
        if item["status"] == EnrollmentStatus.ENROLLED.value
    )


def _create_assessment(client, class_id: str, *, max_score: float = 100.0) -> dict:
    response = client.post(
        f"{API}/academics/classes/{class_id}/assessments",
        json={
            "name": f"Integrity {_suffix()}",
            "assessment_type": "QUIZ",
            "max_score": max_score,
            "weight": 0.1,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _new_student(db, suffix: str) -> Student:
    user = User(
        email=f"integrity-{suffix}@test.local",
        username=f"integrity-{suffix}",
        hashed_password="x",
        full_name=f"Integrity {suffix}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"INT-{suffix}",
        first_name="Integrity",
        last_name=suffix,
        status=StudentStatus.ACTIVE,
    )
    db.add(student)
    db.commit()
    return student


def _new_section(
    db,
    *,
    suffix: str,
    capacity: int | None = 1,
) -> ClassSection:
    period = db.query(AcademicPeriod).filter(AcademicPeriod.code == "2026-FALL").one()
    course = db.query(Course).filter(Course.code == "CS101").one()
    section = ClassSection(
        course_id=course.id,
        academic_period_id=period.id,
        section_code=f"IR-{suffix}",
        capacity=capacity,
        enrolled_count=0,
        status=ClassStatus.ACTIVE,
    )
    db.add(section)
    db.commit()
    return section


def _cleanup_section(db, section: ClassSection, students: list[Student]) -> None:
    db.query(TeacherAssignment).filter(
        TeacherAssignment.class_section_id == section.id
    ).delete()
    db.query(TimetableEntry).filter(
        TimetableEntry.class_section_id == section.id
    ).delete()
    db.query(Enrollment).filter(
        Enrollment.class_section_id == section.id
    ).delete()
    db.query(ClassSection).filter(ClassSection.id == section.id).delete()
    for student in students:
        db.query(Student).filter(Student.id == student.id).delete()
        db.query(User).filter(User.id == student.user_id).delete()
    db.commit()


def _new_staff(db, suffix: str, *, active: bool = True) -> Staff:
    user = User(
        email=f"staff-{suffix}@test.local",
        username=f"staff-{suffix}",
        hashed_password="x",
        full_name=f"Staff {suffix}",
        is_active=active,
    )
    db.add(user)
    db.flush()
    staff = Staff(
        user_id=user.id,
        staff_id=f"STF-{suffix}",
        first_name="Staff",
        last_name=suffix,
        is_active=True,
    )
    db.add(staff)
    db.commit()
    return staff


def _cleanup_staff(db, staff: Staff) -> None:
    user_id = staff.user_id
    db.query(Staff).filter(Staff.id == staff.id).delete()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()


# ── Grade authorization, bounds, and audit ──


@pytest.mark.parametrize(
    "email",
    [
        "admin@school.portal",
        "management@school.portal",
        "teacher@school.portal",
    ],
)
def test_authorized_roles_can_record_grade(client, db_session, email):
    _login(client, "admin@school.portal")
    class_room = _class_with_teacher(client)
    assessment = _create_assessment(client, class_room["id"])
    student_id = _enrolled_student(client, class_room["id"])
    _logout(client)

    _login(client, email)
    response = client.post(
        f"{API}/academics/classes/{class_room['id']}/grades",
        json={
            "assessment_id": assessment["id"],
            "student_id": student_id,
            "score": 88,
            "letter_grade": "B+",
        },
    )
    assert response.status_code == 201, response.text
    grade_id = uuid.UUID(response.json()["id"])
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_type == "grade", AuditLog.entity_id == grade_id)
        .one()
    )
    assert audit.action == "academic.grade.updated"


def test_student_cannot_record_or_update_grade(client, db_session):
    _login(client, "admin@school.portal")
    class_room = _class_with_teacher(client)
    assessment = _create_assessment(client, class_room["id"])
    student_id = _enrolled_student(client, class_room["id"])
    grade = client.post(
        f"{API}/academics/classes/{class_room['id']}/grades",
        json={
            "assessment_id": assessment["id"],
            "student_id": student_id,
            "score": 75,
        },
    ).json()
    assert "id" in grade

    _logout(client)
    _login(client, "student@school.portal")
    create = client.post(
        f"{API}/academics/classes/{class_room['id']}/grades",
        json={
            "assessment_id": assessment["id"],
            "student_id": student_id,
            "score": 90,
        },
    )
    assert create.status_code == 403
    update = client.patch(
        f"{API}/academics/classes/{class_room['id']}/grades/{grade['id']}",
        json={"score": 90},
    )
    assert update.status_code == 403


def test_grade_rejects_score_above_assessment_maximum(client, db_session):
    _login(client, "admin@school.portal")
    class_room = _class_with_teacher(client)
    assessment = _create_assessment(client, class_room["id"], max_score=10)
    student_id = _enrolled_student(client, class_room["id"])
    _logout(client)
    _login(client, "teacher@school.portal")

    response = client.post(
        f"{API}/academics/classes/{class_room['id']}/grades",
        json={
            "assessment_id": assessment["id"],
            "student_id": student_id,
            "score": 11,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "GRADE_SCORE_OUT_OF_BOUNDS"
    assert (
        db_session.query(Grade)
        .filter(
            Grade.assessment_id == uuid.UUID(assessment["id"]),
            Grade.student_id == uuid.UUID(student_id),
        )
        .count()
        == 0
    )


def test_grade_requires_active_enrollment_and_matching_class(client, db_session):
    _login(client, "admin@school.portal")
    class_room = _class_with_teacher(client)
    assessment = _create_assessment(client, class_room["id"])
    suffix = _suffix()
    outsider_response = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": f"GRD-{suffix}",
            "first_name": "Grade",
            "last_name": suffix,
            "email": f"grade-{suffix}@test.local",
        },
    )
    assert outsider_response.status_code == 201, outsider_response.text
    outsider = outsider_response.json()["student"]["id"]

    _logout(client)
    _login(client, "teacher@school.portal")
    unenrolled = client.post(
        f"{API}/academics/classes/{class_room['id']}/grades",
        json={
            "assessment_id": assessment["id"],
            "student_id": outsider,
            "score": 50,
        },
    )
    assert unenrolled.status_code == 409
    assert unenrolled.json()["error"]["code"] == "GRADE_STUDENT_NOT_ENROLLED"

    classes = client.get(f"{API}/academics/classes?page_size=100").json()["items"]
    other = next(
        item
        for item in classes
        if item["id"] != class_room["id"]
        and item["teachers"]
        and item["enrolled_count"] > 0
    )
    wrong_class = client.post(
        f"{API}/academics/classes/{other['id']}/grades",
        json={
            "assessment_id": assessment["id"],
            "student_id": _enrolled_student(client, other["id"]),
            "score": 50,
        },
    )
    assert wrong_class.status_code == 409
    assert wrong_class.json()["error"]["code"] == "GRADE_ASSESSMENT_CLASS_MISMATCH"


def test_teacher_cannot_write_grade_outside_assigned_class(client):
    _login(client, "admin@school.portal")
    source = _class_with_teacher(client)
    student_id = _enrolled_student(client, source["id"])
    period = client.get(f"{API}/academics/periods").json()["items"][0]
    course = client.get(f"{API}/academics/courses?page_size=100").json()["items"][0]
    unassigned = client.post(
        f"{API}/academics/classes",
        json={
            "course_id": course["id"],
            "academic_period_id": period["id"],
            "section_code": f"OUT-{_suffix()}",
            "capacity": 30,
        },
    ).json()
    enrolled = client.post(
        f"{API}/academics/classes/{unassigned['id']}/enrollments",
        json={"student_id": student_id},
    )
    assert enrolled.status_code == 201, enrolled.text
    assessment = _create_assessment(client, unassigned["id"])
    assert not unassigned["teachers"]

    _logout(client)
    _login(client, "teacher@school.portal")
    response = client.post(
        f"{API}/academics/classes/{unassigned['id']}/grades",
        json={
            "assessment_id": assessment["id"],
            "student_id": student_id,
            "score": 70,
        },
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "email",
    [
        "admin@school.portal",
        "management@school.portal",
        "teacher@school.portal",
    ],
)
def test_grade_update_is_audited_and_bounded(client, db_session, email):
    _login(client, "admin@school.portal")
    class_room = _class_with_teacher(client)
    assessment = _create_assessment(client, class_room["id"], max_score=100)
    student_id = _enrolled_student(client, class_room["id"])
    grade = client.post(
        f"{API}/academics/classes/{class_room['id']}/grades",
        json={
            "assessment_id": assessment["id"],
            "student_id": student_id,
            "score": 80,
        },
    ).json()

    _logout(client)
    _login(client, email)
    updated = client.patch(
        f"{API}/academics/classes/{class_room['id']}/grades/{grade['id']}",
        json={"score": 90, "note": "Corrected"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["score"] == 90
    audits = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.entity_type == "grade",
            AuditLog.entity_id == uuid.UUID(grade["id"]),
        )
        .order_by(AuditLog.created_at)
        .all()
    )
    assert len(audits) >= 2
    assert audits[-1].action == "academic.grade.updated"

    too_high = client.patch(
        f"{API}/academics/classes/{class_room['id']}/grades/{grade['id']}",
        json={"score": 101},
    )
    assert too_high.status_code == 409
    assert too_high.json()["error"]["code"] == "GRADE_SCORE_OUT_OF_BOUNDS"


def test_lowering_assessment_maximum_below_existing_grade_is_rejected(client):
    _login(client, "admin@school.portal")
    class_room = _class_with_teacher(client)
    assessment = _create_assessment(client, class_room["id"], max_score=100)
    student_id = _enrolled_student(client, class_room["id"])
    created = client.post(
        f"{API}/academics/classes/{class_room['id']}/grades",
        json={
            "assessment_id": assessment["id"],
            "student_id": student_id,
            "score": 80,
        },
    )
    assert created.status_code == 201, created.text

    rejected = client.patch(
        f"{API}/academics/classes/{class_room['id']}/assessments/{assessment['id']}",
        json={"max_score": 70},
    )
    assert rejected.status_code == 409, rejected.text
    assert (
        rejected.json()["error"]["code"]
        == "ASSESSMENT_MAX_BELOW_EXISTING_GRADE"
    )

    allowed = client.patch(
        f"{API}/academics/classes/{class_room['id']}/assessments/{assessment['id']}",
        json={"max_score": 90},
    )
    assert allowed.status_code == 200, allowed.text


# ── Enrollment capacity and concurrency ──


def test_re_enrollment_respects_capacity():
    db = SessionLocal()
    section = None
    students = []
    try:
        suffix = _suffix()
        section = _new_section(db, suffix=suffix, capacity=1)
        first = _new_student(db, f"{suffix}-a")
        second = _new_student(db, f"{suffix}-b")
        students = [first, second]

        academic_svc.enroll_student(
            db, section.id, EnrollmentCreate(student_id=first.id)
        )
        dropped = (
            db.query(Enrollment)
            .filter(
                Enrollment.class_section_id == section.id,
                Enrollment.student_id == first.id,
            )
            .one()
        )
        academic_svc.drop_enrollment(db, dropped.id)
        academic_svc.enroll_student(
            db, section.id, EnrollmentCreate(student_id=second.id)
        )

        with pytest.raises(ValueError, match="full capacity"):
            academic_svc.enroll_student(
                db, section.id, EnrollmentCreate(student_id=first.id)
            )

        active = (
            db.query(Enrollment)
            .filter(
                Enrollment.class_section_id == section.id,
                Enrollment.status == EnrollmentStatus.ENROLLED,
            )
            .count()
        )
        db.refresh(section)
        assert active == 1
        assert section.enrolled_count == 1
    finally:
        if section is not None:
            _cleanup_section(db, section, students)
        db.close()


def test_concurrent_enrollments_never_overbook():
    db = SessionLocal()
    section = None
    students = []
    try:
        suffix = _suffix()
        section = _new_section(db, suffix=suffix, capacity=1)
        first = _new_student(db, f"{suffix}-a")
        second = _new_student(db, f"{suffix}-b")
        students = [first, second]
        barrier = threading.Barrier(2)
        results: Queue[tuple[str, str]] = Queue()

        def attempt(student_id):
            worker = SessionLocal()
            try:
                barrier.wait(timeout=10)
                academic_svc.enroll_student(
                    worker,
                    section.id,
                    EnrollmentCreate(student_id=student_id),
                )
                results.put(("ok", str(student_id)))
            except Exception as exc:  # noqa: BLE001 - collected for assertion
                results.put(("error", str(exc)))
            finally:
                worker.close()

        threads = [
            threading.Thread(target=attempt, args=(student.id,))
            for student in students
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        outcomes = [results.get_nowait() for _ in range(2)]
        assert sum(1 for outcome, _ in outcomes if outcome == "ok") == 1
        assert sum(1 for outcome, _ in outcomes if outcome == "error") == 1

        db.expire_all()
        current = db.query(ClassSection).filter(ClassSection.id == section.id).one()
        active = (
            db.query(Enrollment)
            .filter(
                Enrollment.class_section_id == section.id,
                Enrollment.status == EnrollmentStatus.ENROLLED,
            )
            .count()
        )
        assert active == 1
        assert current.enrolled_count == 1
    finally:
        if section is not None:
            _cleanup_section(db, section, students)
        db.close()


def test_concurrent_enroll_and_drop_leave_consistent_counter():
    db = SessionLocal()
    section = None
    students = []
    try:
        suffix = _suffix()
        section = _new_section(db, suffix=suffix, capacity=1)
        first = _new_student(db, f"{suffix}-a")
        second = _new_student(db, f"{suffix}-b")
        students = [first, second]
        enrolled = academic_svc.enroll_student(
            db, section.id, EnrollmentCreate(student_id=first.id)
        )
        barrier = threading.Barrier(2)
        results: Queue[tuple[str, str]] = Queue()

        def drop():
            worker = SessionLocal()
            try:
                barrier.wait(timeout=10)
                academic_svc.drop_enrollment(worker, enrolled.id)
                results.put(("ok", "drop"))
            except Exception as exc:  # noqa: BLE001
                results.put(("error", str(exc)))
            finally:
                worker.close()

        def enroll():
            worker = SessionLocal()
            try:
                barrier.wait(timeout=10)
                academic_svc.enroll_student(
                    worker,
                    section.id,
                    EnrollmentCreate(student_id=second.id),
                )
                results.put(("ok", "enroll"))
            except Exception as exc:  # noqa: BLE001
                results.put(("error", str(exc)))
            finally:
                worker.close()

        threads = [threading.Thread(target=drop), threading.Thread(target=enroll)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        outcomes = [results.get_nowait() for _ in range(2)]
        assert any(kind == "ok" for kind, _ in outcomes)
        db.expire_all()
        current = db.query(ClassSection).filter(ClassSection.id == section.id).one()
        active = (
            db.query(Enrollment)
            .filter(
                Enrollment.class_section_id == section.id,
                Enrollment.status == EnrollmentStatus.ENROLLED,
            )
            .count()
        )
        assert active <= 1
        assert current.enrolled_count == active
    finally:
        if section is not None:
            _cleanup_section(db, section, students)
        db.close()


# ── Teacher scheduling and timetable capacity ──


def _teacher_scenario(db, suffix: str) -> tuple[Staff, list[ClassSection], Classroom]:
    staff = _new_staff(db, suffix)
    room = Classroom(
        room_code=f"IR-{suffix}",
        capacity=30,
        status="AVAILABLE",
    )
    db.add(room)
    db.flush()
    sections = [
        _new_section(db, suffix=f"{suffix}-{index}", capacity=20)
        for index in (1, 2)
    ]
    for section in sections:
        db.add(
            TimetableEntry(
                class_section_id=section.id,
                classroom_id=room.id,
                day_of_week=0,
                start_time=time(9, 0),
                end_time=time(10, 0),
            )
        )
    db.commit()
    return staff, sections, room


def _cleanup_teacher_scenario(
    db, staff: Staff, sections: list[ClassSection], room: Classroom
) -> None:
    for section in sections:
        _cleanup_section(db, section, [])
    db.query(Classroom).filter(Classroom.id == room.id).delete()
    _cleanup_staff(db, staff)


def test_assign_teacher_rejects_existing_timetable_conflict():
    db = SessionLocal()
    staff = sections = room = None
    try:
        suffix = _suffix()
        staff, sections, room = _teacher_scenario(db, suffix)
        first, second = sections
        academic_svc.assign_teacher(
            db,
            first.id,
            TeacherAssignmentCreate(staff_id=staff.id),
        )

        with pytest.raises(academic_svc.AcademicRuleError) as error:
            academic_svc.assign_teacher(
                db,
                second.id,
                TeacherAssignmentCreate(staff_id=staff.id),
            )
        assert error.value.code == "TIMETABLE_TEACHER_CONFLICT"
    finally:
        if staff is not None:
            _cleanup_teacher_scenario(db, staff, sections, room)
        db.close()


def test_reactivating_teacher_assignment_checks_conflicts():
    db = SessionLocal()
    staff = sections = room = None
    try:
        suffix = _suffix()
        staff, sections, room = _teacher_scenario(db, suffix)
        first, second = sections
        assignment = TeacherAssignment(
            class_section_id=first.id,
            staff_id=staff.id,
            is_active=False,
        )
        db.add(assignment)
        db.commit()
        academic_svc.assign_teacher(
            db,
            second.id,
            TeacherAssignmentCreate(staff_id=staff.id),
        )

        with pytest.raises(academic_svc.AcademicRuleError) as error:
            academic_svc.assign_teacher(
                db,
                first.id,
                TeacherAssignmentCreate(staff_id=staff.id),
            )
        assert error.value.code == "TIMETABLE_TEACHER_CONFLICT"
    finally:
        if staff is not None:
            _cleanup_teacher_scenario(db, staff, sections, room)
        db.close()


def test_concurrent_teacher_assignments_are_serialized():
    db = SessionLocal()
    staff = sections = room = None
    try:
        suffix = _suffix()
        staff, sections, room = _teacher_scenario(db, suffix)
        barrier = threading.Barrier(2)
        results: Queue[tuple[str, str]] = Queue()

        def assign(section_id):
            worker = SessionLocal()
            try:
                barrier.wait(timeout=10)
                academic_svc.assign_teacher(
                    worker,
                    section_id,
                    TeacherAssignmentCreate(staff_id=staff.id),
                )
                results.put(("ok", str(section_id)))
            except Exception as exc:  # noqa: BLE001
                results.put(("error", str(exc)))
            finally:
                worker.close()

        threads = [
            threading.Thread(target=assign, args=(section.id,))
            for section in sections
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        outcomes = [results.get_nowait() for _ in range(2)]
        assert sum(1 for kind, _ in outcomes if kind == "ok") == 1
        assert sum(1 for kind, _ in outcomes if kind == "error") == 1
        db.expire_all()
        active = (
            db.query(TeacherAssignment)
            .filter(
                TeacherAssignment.staff_id == staff.id,
                TeacherAssignment.is_active.is_(True),
            )
            .count()
        )
        assert active == 1
    finally:
        if staff is not None:
            _cleanup_teacher_scenario(db, staff, sections, room)
        db.close()


def test_timetable_allows_section_larger_than_classroom(client):
    _login(client, "admin@school.portal")
    suffix = _suffix()
    room = client.post(
        f"{API}/academics/classrooms",
        json={"room_code": f"CAP-{suffix}", "capacity": 20},
    ).json()
    period = client.get(f"{API}/academics/periods").json()["items"][0]
    course = client.post(
        f"{API}/academics/courses",
        json={"code": f"CAP{suffix}", "name": f"Capacity {suffix}"},
    ).json()
    section = client.post(
        f"{API}/academics/classes",
        json={
            "course_id": course["id"],
            "academic_period_id": period["id"],
            "section_code": "A",
            "capacity": 30,
        },
    ).json()
    response = client.post(
        f"{API}/academics/timetable",
        json={
            "class_section_id": section["id"],
            "classroom_id": room["id"],
            "day_of_week": 0,
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        },
    )
    # Classroom capacity is location information, not an institutional
    # restriction on the number of students a section may carry.
    assert response.status_code == 201, response.text
    assert response.json()["classroom_id"] == room["id"]


def test_classroom_capacity_is_not_a_section_capacity_restriction(client):
    _login(client, "admin@school.portal")
    suffix = _suffix()
    room = client.post(
        f"{API}/academics/classrooms",
        json={"room_code": f"UPD-{suffix}", "capacity": 40},
    ).json()
    period = client.get(f"{API}/academics/periods").json()["items"][0]
    course = client.post(
        f"{API}/academics/courses",
        json={"code": f"UPD{suffix}", "name": f"Update {suffix}"},
    ).json()
    section = client.post(
        f"{API}/academics/classes",
        json={
            "course_id": course["id"],
            "academic_period_id": period["id"],
            "section_code": "A",
            "capacity": 30,
        },
    ).json()
    scheduled = client.post(
        f"{API}/academics/timetable",
        json={
            "class_section_id": section["id"],
            "classroom_id": room["id"],
            "day_of_week": 1,
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        },
    )
    assert scheduled.status_code == 201, scheduled.text

    larger_section = client.patch(
        f"{API}/academics/classes/{section['id']}",
        json={"capacity": 50},
    )
    assert larger_section.status_code == 200, larger_section.text
    assert larger_section.json()["capacity"] == 50

    smaller_room = client.patch(
        f"{API}/academics/classrooms/{room['id']}",
        json={"capacity": 20},
    )
    assert smaller_room.status_code == 200, smaller_room.text
    assert smaller_room.json()["capacity"] == 20

    scheduled_rows = client.get(
        f"{API}/academics/timetable",
        params={"class_section_id": section["id"]},
    )
    assert scheduled_rows.status_code == 200
    assert len(scheduled_rows.json()["items"]) == 1


def test_timetable_update_rejects_conflict(client):
    _login(client, "admin@school.portal")
    suffix = _suffix()
    room = client.post(
        f"{API}/academics/classrooms",
        json={"room_code": f"UPD-T-{suffix}", "capacity": 40},
    ).json()
    period = client.get(f"{API}/academics/periods").json()["items"][0]
    course = client.post(
        f"{API}/academics/courses",
        json={"code": f"UPDT{suffix}", "name": f"Update timetable {suffix}"},
    ).json()
    section = client.post(
        f"{API}/academics/classes",
        json={
            "course_id": course["id"],
            "academic_period_id": period["id"],
            "section_code": "A",
            "capacity": 30,
        },
    ).json()
    first = client.post(
        f"{API}/academics/timetable",
        json={
            "class_section_id": section["id"],
            "classroom_id": room["id"],
            "day_of_week": 0,
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        },
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"{API}/academics/timetable",
        json={
            "class_section_id": section["id"],
            "classroom_id": room["id"],
            "day_of_week": 1,
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        },
    )
    assert second.status_code == 201, second.text

    conflict = client.patch(
        f"{API}/academics/timetable/{second.json()['id']}",
        json={"day_of_week": 0},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "TIMETABLE_SECTION_CONFLICT"


# ── Importer path ──


def test_importer_rejects_conflicting_source_slot(db_session):
    fall = (
        db_session.query(AcademicPeriod)
        .filter(AcademicPeriod.code == "2026-FALL")
        .one()
    )
    course = db_session.query(Course).filter(Course.code == "CS101").one()
    room = Classroom(
        room_code="N107",
        source_key=room_key("N107"),
        capacity=None,
        status="AVAILABLE",
    )
    section = ClassSection(
        course_id=course.id,
        academic_period_id=fall.id,
        section_code=f"IMPORT-{_suffix()}",
        capacity=None,
        status=ClassStatus.ACTIVE,
    )
    db_session.add_all([room, section])
    db_session.flush()
    db_session.add(
        TimetableEntry(
            class_section_id=section.id,
            classroom_id=room.id,
            day_of_week=0,
            start_time=time(13, 30),
            end_time=time(17, 0),
        )
    )
    db_session.commit()

    report = prepare_import(db_session, DEFAULT_SOURCE)
    with pytest.raises(academic_svc.AcademicRuleError) as error:
        apply_import(
            db_session,
            report["batch_id"],
            period_map={"2026-autumn": str(fall.id)},
        )
    assert error.value.code == "TIMETABLE_CLASSROOM_CONFLICT"

    from app.models.academic import AcademicImportBatch

    batch = (
        db_session.query(AcademicImportBatch)
        .filter(AcademicImportBatch.id == uuid.UUID(report["batch_id"]))
        .one()
    )
    assert batch.status == "FAILED"


# ── Support assignment ──


def _create_ticket(client) -> str:
    _login(client, "student@school.portal")
    response = client.post(
        f"{API}/support",
        json={
            "category": "GENERAL",
            "subject": f"Integrity assignment {_suffix()}",
            "description": "Testing support assignment authorization.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_support_assignee_must_be_active_staff_with_support_access(
    client, db_session
):
    ticket_id = _create_ticket(client)
    student_user = (
        db_session.query(User)
        .filter(User.email == "student@school.portal")
        .one()
    )
    teacher_user = (
        db_session.query(User)
        .filter(User.email == "teacher@school.portal")
        .one()
    )
    suffix = _suffix()
    inactive_staff = _new_staff(db_session, f"{suffix}-inactive", active=False)
    no_access_role = Role(name=f"NOACCESS-{suffix}", description="No support access")
    no_access_user = User(
        email=f"noaccess-{suffix}@test.local",
        username=f"noaccess-{suffix}",
        hashed_password="x",
        full_name=f"No Access {suffix}",
        is_active=True,
    )
    db_session.add_all([no_access_role, no_access_user])
    db_session.flush()
    no_access_user.roles.append(no_access_role)
    no_access_staff = Staff(
        user_id=no_access_user.id,
        staff_id=f"STF-NA-{suffix}",
        first_name="No",
        last_name="Access",
        is_active=True,
    )
    db_session.add(no_access_staff)
    db_session.commit()

    _logout(client)
    _login(client, "management@school.portal")

    def assign(user_id) -> object:
        return client.patch(
            f"{API}/support/{ticket_id}",
            json={"assigned_to": str(user_id)},
        )

    assert assign(student_user.id).status_code == 400
    assert assign(inactive_staff.user_id).status_code == 400
    assert assign(no_access_user.id).status_code == 400

    accepted = assign(teacher_user.id)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["assigned_to"] == str(teacher_user.id)
    notification = (
        db_session.query(Notification)
        .filter(
            Notification.user_id == teacher_user.id,
            Notification.type == NotificationType.SUPPORT_TICKET_ASSIGNED,
        )
        .first()
    )
    assert notification is not None
