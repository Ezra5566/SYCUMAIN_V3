"""Examination management.

These tests pin the institutional rules.

* One examination serves several teaching sections; it is never duplicated per
  section, and it has one schedule, one room and one publication decision.
* Eligibility comes from real enrollments. A student in another programme's
  section is not eligible and cannot see the paper or its result.
* A teacher sees and marks only the sections they are assigned to. The service
  recomputes that scope on every request.
* Unpublished results do not exist for students — not hidden behind a flag, but
  absent from the payload.
* A correction supersedes and keeps the previous score, its recorder and the
  reason.
* Nothing is computed: no GPA, no percentage, no pass mark, no letter grade.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import event

from app.auth.service import hash_password
from app.models.academic import (
    AcademicPeriod,
    ClassSection,
    ClassSectionProgramOffering,
    Course,
    Enrollment,
    ProgramOffering,
    TeacherAssignment,
)
from app.models.admission import AcademicAdmission, AcademicPlacement
from app.models.examination import Examination, ExaminationResult
from app.models.identity import Role, Staff, Student, User
from app.permissions.constants import ROLE_PERMISSIONS

API = "/api/v1/examinations"


class TestPagePayloadCost:
    """A page of examinations must cost a constant number of queries per row.

    The payload used to load ``Course``/``AcademicPeriod`` entities per
    examination. Both models carry ``lazy="selectin"`` collections, so every
    entity load pulled that course's sections and each section's enrollments,
    timetable and assessments with it: a 25-row page issued over a thousand
    statements, and concurrent viewers queued for seconds behind the connection
    pool. This test pins the batched shape — the cost of a wider page is a
    constant, not one query per row.
    """

    def test_the_cost_of_a_page_does_not_grow_per_row(self, client, db_session):
        period = _mk_period(db_session, "perf")
        course = _mk_course(db_session, "perf")
        section = _mk_section(db_session, course, period, "A")
        db_session.commit()

        _login(client, MANAGEMENT)
        for index in range(10):
            created = _create(
                client,
                course,
                period,
                [section],
                title=f"Performance {index}",
                location=f"Hall {index}",
            )
            assert created.status_code == 201, created.text

        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        bind = db_session.get_bind()
        event.listen(bind, "before_cursor_execute", record)
        try:
            single = client.get(f"{API}?page=1&page_size=1")
            assert single.status_code == 200, single.text
            one_row = len(statements)
            statements.clear()

            page = client.get(f"{API}?page=1&page_size=10")
            assert page.status_code == 200, page.text
            ten_rows = len(statements)
        finally:
            event.remove(bind, "before_cursor_execute", record)

        assert len(page.json()["items"]) == 10
        # A fixed overhead is fine; a per-row query is not. Nine extra rows may
        # not add more than a handful of statements.
        assert ten_rows - one_row <= 6, (one_row, ten_rows)
LOGIN = "/api/v1/auth/login"

ADMIN = "admin@school.portal"
MANAGEMENT = "management@school.portal"

TODAY = date.today()


def _day(offset: int) -> date:
    return TODAY + timedelta(days=offset)


def _login(client, email: str) -> None:
    response = client.post(LOGIN, json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text


# ── Fixtures ───────────────────────────────────────────────────────────────


def _mk_user(db, *, role_name: str, tag: str) -> User:
    user = User(
        email=f"exam-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"exam-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Exam {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    role = db.query(Role).filter(Role.name == role_name).first()
    assert role is not None
    user.roles.append(role)
    db.flush()
    return user


def _mk_student(db, tag: str) -> Student:
    user = _mk_user(db, role_name="STUDENT", tag=tag)
    student = Student(
        user_id=user.id,
        student_id=f"EX-{tag.upper()}-{uuid.uuid4().hex[:6]}",
        first_name="Exam",
        last_name=tag,
        status="ACTIVE",
    )
    db.add(student)
    db.flush()
    return student


def _mk_teacher(db, tag: str) -> Staff:
    user = _mk_user(db, role_name="TEACHER", tag=tag)
    staff = Staff(
        user_id=user.id,
        staff_id=f"ST-{uuid.uuid4().hex[:8]}",
        first_name="Exam",
        last_name=tag,
        is_active=True,
    )
    db.add(staff)
    db.flush()
    return staff


def _mk_period(db, tag: str) -> AcademicPeriod:
    period = AcademicPeriod(
        name=f"Exam Period {tag}",
        code=f"EP-{uuid.uuid4().hex[:6].upper()}",
        start_date=_day(-30),
        end_date=_day(60),
        status="ACTIVE",
    )
    db.add(period)
    db.flush()
    return period


def _mk_course(db, tag: str) -> Course:
    course = Course(
        code=f"EC-{uuid.uuid4().hex[:6].upper()}",
        name=f"Exam Course {tag}",
        program_id=None,
        credits=None,
    )
    db.add(course)
    db.flush()
    return course


def _mk_section(db, course: Course, period: AcademicPeriod, label: str) -> ClassSection:
    section = ClassSection(
        course_id=course.id,
        academic_period_id=period.id,
        section_code=label,
        status="ACTIVE",
    )
    db.add(section)
    db.flush()
    return section


def _mk_offering(db, period: AcademicPeriod, tag: str) -> ProgramOffering:
    offering = ProgramOffering(
        academic_period_id=period.id,
        source_id=f"OFF-{tag}-{uuid.uuid4().hex[:6]}",
        source_key=f"off-{tag}-{uuid.uuid4().hex[:10]}",
        name=f"Offering {tag}",
    )
    db.add(offering)
    db.flush()
    return offering


def _link(db, section: ClassSection, *offerings: ProgramOffering) -> None:
    for offering in offerings:
        db.add(
            ClassSectionProgramOffering(
                class_section_id=section.id,
                program_offering_id=offering.id,
            )
        )
    db.flush()


def _place(
    db,
    student: Student,
    offering: ProgramOffering,
    *,
    status: str = "ACTIVE",
) -> None:
    """Authoritative admission and placement, shaped like the real workflow."""
    now = datetime.now()
    terminal = status in ("COMPLETED", "WITHDRAWN", "CANCELLED")
    admission = AcademicAdmission(
        student_id=student.id,
        admission_intake_id=offering.academic_period_id,
        admitted_program_id=offering.program_id,
        admitted_program_offering_id=offering.id,
        current_program_id=offering.program_id,
        status=status,
        initial_status=status,
        verification_status="VERIFIED",
        verified_at=now,
        activated_at=now if status == "ACTIVE" else None,
        ended_at=now if terminal else None,
        end_reason="Ended for test" if terminal else None,
        created_by_id=student.user_id,
    )
    db.add(admission)
    db.flush()
    if not terminal:
        db.add(
            AcademicPlacement(
                student_id=student.id,
                admission_id=admission.id,
                academic_period_id=offering.academic_period_id,
                program_offering_id=offering.id,
                effective_from=date.today(),
                created_by_id=student.user_id,
            )
        )
        db.flush()


def _enroll(db, student: Student, section: ClassSection, status: str = "ENROLLED") -> None:
    db.add(
        Enrollment(
            student_id=student.id,
            class_section_id=section.id,
            status=status,
        )
    )
    db.flush()


def _assign_teacher(db, staff: Staff, section: ClassSection) -> None:
    db.add(
        TeacherAssignment(
            class_section_id=section.id, staff_id=staff.id, is_active=True
        )
    )
    db.flush()


def _payload(
    course: Course,
    period: AcademicPeriod,
    sections: list[ClassSection],
    *,
    title: str = "Final examination",
    exam_date: date | None = None,
    start: str = "09:00:00",
    end: str = "11:00:00",
    location: str | None = "Hall A",
    max_score: float | None = 100,
    program_offering_id: uuid.UUID | None = None,
) -> dict:
    body = {
        "title": title,
        "examination_type": "FINAL",
        "course_id": str(course.id),
        "academic_period_id": str(period.id),
        "exam_date": (exam_date or _day(7)).isoformat(),
        "start_time": start,
        "end_time": end,
        "section_ids": [str(section.id) for section in sections],
    }
    if location is not None:
        body["location"] = location
    if max_score is not None:
        body["max_score"] = max_score
    if program_offering_id is not None:
        body["program_offering_id"] = str(program_offering_id)
    return body


def _create(client, course, period, sections, **kwargs):
    return client.post(API, json=_payload(course, period, sections, **kwargs))


# ── A. Scheduling ──────────────────────────────────────────────────────────


class TestExaminationScheduling:
    def test_one_examination_serves_several_sections(self, client, db_session):
        period = _mk_period(db_session, "shared")
        course = _mk_course(db_session, "shared")
        first = _mk_section(db_session, course, period, "A")
        second = _mk_section(db_session, course, period, "B")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _create(client, course, period, [first, second])
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["section_count"] == 2
        assert {section["class_section_id"] for section in body["sections"]} == {
            str(first.id),
            str(second.id),
        }
        # Exactly one examination row: the shared paper was not duplicated.
        assert db_session.query(Examination).count() == 1

    def test_an_examination_without_sections_is_refused(self, client, db_session):
        period = _mk_period(db_session, "nosection")
        course = _mk_course(db_session, "nosection")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = client.post(
            API,
            json={
                **_payload(course, period, []),
                "section_ids": [],
            },
        )
        assert response.status_code == 422

    def test_a_section_from_another_intake_is_refused(self, client, db_session):
        period = _mk_period(db_session, "intake-a")
        other_period = _mk_period(db_session, "intake-b")
        course = _mk_course(db_session, "intake")
        mine = _mk_section(db_session, course, period, "A")
        foreign = _mk_section(db_session, course, other_period, "B")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _create(client, course, period, [mine, foreign])
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "EXAM_SECTION_WRONG_INTAKE"

    def test_a_section_teaching_another_subject_is_refused(self, client, db_session):
        period = _mk_period(db_session, "subject")
        course = _mk_course(db_session, "subject")
        other_course = _mk_course(db_session, "subject-other")
        mine = _mk_section(db_session, course, period, "A")
        foreign = _mk_section(db_session, other_course, period, "B")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _create(client, course, period, [mine, foreign])
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "EXAM_SECTION_WRONG_SUBJECT"

    def test_an_end_time_before_the_start_is_refused(self, client, db_session):
        period = _mk_period(db_session, "timeline")
        course = _mk_course(db_session, "timeline")
        section = _mk_section(db_session, course, period, "A")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _create(
            client, course, period, [section], start="11:00:00", end="09:00:00"
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "EXAM_INVALID_TIME_WINDOW"

    def test_the_same_room_at_an_overlapping_time_is_refused(
        self, client, db_session
    ):
        period = _mk_period(db_session, "room")
        course_a = _mk_course(db_session, "room-a")
        course_b = _mk_course(db_session, "room-b")
        section_a = _mk_section(db_session, course_a, period, "A")
        section_b = _mk_section(db_session, course_b, period, "B")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert (
            _create(client, course_a, period, [section_a], location="Hall A").status_code
            == 201
        )
        clash = _create(
            client,
            course_b,
            period,
            [section_b],
            location="hall a",
            start="10:00:00",
            end="12:00:00",
        )
        assert clash.status_code == 409
        assert clash.json()["error"]["code"] == "EXAM_LOCATION_CONFLICT"

    def test_the_same_room_at_a_disjoint_time_is_allowed(self, client, db_session):
        period = _mk_period(db_session, "room-ok")
        course_a = _mk_course(db_session, "room-ok-a")
        course_b = _mk_course(db_session, "room-ok-b")
        section_a = _mk_section(db_session, course_a, period, "A")
        section_b = _mk_section(db_session, course_b, period, "B")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert (
            _create(client, course_a, period, [section_a], location="Hall A").status_code
            == 201
        )
        response = _create(
            client,
            course_b,
            period,
            [section_b],
            location="Hall A",
            start="11:00:00",
            end="13:00:00",
        )
        assert response.status_code == 201, response.text

    def test_a_student_double_booked_at_an_overlapping_time_is_refused(
        self, client, db_session
    ):
        period = _mk_period(db_session, "student-clash")
        course_a = _mk_course(db_session, "student-clash-a")
        course_b = _mk_course(db_session, "student-clash-b")
        section_a = _mk_section(db_session, course_a, period, "A")
        section_b = _mk_section(db_session, course_b, period, "B")
        student = _mk_student(db_session, "clash")
        _enroll(db_session, student, section_a)
        _enroll(db_session, student, section_b)
        db_session.commit()

        _login(client, MANAGEMENT)
        assert (
            _create(client, course_a, period, [section_a], location="Hall A").status_code
            == 201
        )
        clash = _create(
            client,
            course_b,
            period,
            [section_b],
            location="Hall B",
            start="10:00:00",
            end="12:00:00",
        )
        assert clash.status_code == 409
        assert clash.json()["error"]["code"] == "EXAM_STUDENT_CONFLICT"


# ── B. Eligibility and visibility ──────────────────────────────────────────


class TestEligibility:
    def test_eligible_students_come_from_enrollments(self, client, db_session):
        period = _mk_period(db_session, "elig")
        course = _mk_course(db_session, "elig")
        section = _mk_section(db_session, course, period, "A")
        enrolled = _mk_student(db_session, "enrolled")
        dropped = _mk_student(db_session, "dropped")
        outsider = _mk_student(db_session, "outsider")
        _enroll(db_session, enrolled, section)
        _enroll(db_session, dropped, section, status="DROPPED")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()

        detail = client.get(f"{API}/{created['id']}").json()
        numbers = {row["student_number"] for row in detail["eligible_students"]}
        assert enrolled.student_id in numbers
        assert dropped.student_id not in numbers
        assert outsider.student_id not in numbers
        assert detail["examination"]["eligible_count"] == 1

    def test_a_student_sees_only_examinations_of_their_own_sections(
        self, client, db_session
    ):
        period = _mk_period(db_session, "scope")
        course = _mk_course(db_session, "scope")
        theirs = _mk_section(db_session, course, period, "A")
        other_course = _mk_course(db_session, "scope-other")
        foreign = _mk_section(db_session, other_course, period, "B")
        student = _mk_student(db_session, "scope")
        _enroll(db_session, student, theirs)
        db_session.commit()

        _login(client, MANAGEMENT)
        visible = _create(client, course, period, [theirs], title="Visible paper").json()
        hidden = _create(
            client,
            other_course,
            period,
            [foreign],
            title="Hidden paper",
            location="Hall B",
            start="13:00:00",
            end="15:00:00",
        ).json()

        _login(client, student.user.email)
        mine = client.get(f"{API}/me").json()
        assert [item["id"] for item in mine["items"]] == [visible["id"]]

        # Direct access to the other programme's examination is not found.
        assert client.get(f"{API}/{hidden['id']}").status_code == 404

    def test_a_teacher_sees_only_assigned_sections(self, client, db_session):
        period = _mk_period(db_session, "teacher-scope")
        course = _mk_course(db_session, "teacher-scope")
        mine = _mk_section(db_session, course, period, "A")
        other_course = _mk_course(db_session, "teacher-other")
        other = _mk_section(db_session, other_course, period, "B")
        teacher = _mk_teacher(db_session, "scope")
        _assign_teacher(db_session, teacher, mine)
        db_session.commit()

        _login(client, MANAGEMENT)
        own = _create(client, course, period, [mine], title="My paper").json()
        _create(
            client,
            other_course,
            period,
            [other],
            title="Not my paper",
            location="Hall B",
            start="13:00:00",
            end="15:00:00",
        )

        _login(client, teacher.user.email)
        listing = client.get(API).json()
        assert [item["id"] for item in listing["items"]] == [own["id"]]

    def test_a_teacher_cannot_create_an_examination(self, client, db_session):
        period = _mk_period(db_session, "teacher-create")
        course = _mk_course(db_session, "teacher-create")
        section = _mk_section(db_session, course, period, "A")
        teacher = _mk_teacher(db_session, "create")
        _assign_teacher(db_session, teacher, section)
        db_session.commit()

        _login(client, teacher.user.email)
        assert _create(client, course, period, [section]).status_code == 403


# ── C. Results ─────────────────────────────────────────────────────────────


class TestResults:
    def _setup(self, db_session, tag: str):
        period = _mk_period(db_session, tag)
        course = _mk_course(db_session, tag)
        section = _mk_section(db_session, course, period, "A")
        student = _mk_student(db_session, f"{tag}-student")
        _enroll(db_session, student, section)
        db_session.commit()
        return period, course, section, student

    def test_a_result_can_be_recorded_and_read_back(self, client, db_session):
        period, course, section, student = self._setup(db_session, "record")
        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()

        response = client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 82.5},
        )
        assert response.status_code == 201, response.text
        assert response.json()["result"]["score"] == 82.5
        assert response.json()["result_count"] == 1

        detail = client.get(f"{API}/{created['id']}").json()
        assert detail["examination"]["result_count"] == 1
        assert detail["eligible_students"][0]["has_result"] is True

    def test_an_ineligible_student_is_refused(self, client, db_session):
        period, course, section, _student = self._setup(db_session, "ineligible")
        outsider = _mk_student(db_session, "ineligible-outsider")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        response = client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(outsider.id), "score": 60},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "EXAM_STUDENT_NOT_ELIGIBLE"
        )

    def test_a_score_above_the_stated_maximum_is_refused(self, client, db_session):
        period, course, section, student = self._setup(db_session, "max")
        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section], max_score=50).json()

        response = client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 75},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "EXAM_SCORE_ABOVE_MAXIMUM"

    def test_a_second_live_result_is_refused(self, client, db_session):
        period, course, section, student = self._setup(db_session, "duplicate")
        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        assert (
            client.post(
                f"{API}/{created['id']}/results",
                json={"student_id": str(student.id), "score": 60},
            ).status_code
            == 201
        )
        again = client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 61},
        )
        assert again.status_code == 409
        assert again.json()["error"]["code"] == (
            "EXAM_RESULT_ALREADY_RECORDED"
        )

    def test_a_correction_supersedes_and_keeps_the_previous_score(
        self, client, db_session
    ):
        period, course, section, student = self._setup(db_session, "correct")
        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        original = client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 60},
        ).json()["result"]

        corrected = client.post(
            f"{API}/{created['id']}/results/{original['id']}/corrections",
            json={
                "score": 72,
                "reason": "The marker transposed two digits on the answer sheet.",
            },
        )
        assert corrected.status_code == 201, corrected.text
        body = corrected.json()
        assert body["result"]["score"] == 72
        assert body["result"]["supersedes_id"] == original["id"]

        detail = client.get(f"{API}/{created['id']}").json()
        history = {row["id"]: row for row in detail["results"]}
        assert history[original["id"]]["score"] == 60
        assert history[original["id"]]["is_current"] is False
        assert history[body["result"]["id"]]["is_current"] is True

        db_session.expire_all()
        assert db_session.query(ExaminationResult).count() == 2

    def test_a_correction_needs_a_reason(self, client, db_session):
        period, course, section, student = self._setup(db_session, "correct-reason")
        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        original = client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 60},
        ).json()["result"]

        response = client.post(
            f"{API}/{created['id']}/results/{original['id']}/corrections",
            json={"score": 72, "reason": "oops"},
        )
        assert response.status_code == 422

    def test_a_teacher_records_only_for_their_own_sections(self, client, db_session):
        period = _mk_period(db_session, "teacher-results")
        mine_course = _mk_course(db_session, "teacher-results-a")
        other_course = _mk_course(db_session, "teacher-results-b")
        mine = _mk_section(db_session, mine_course, period, "A")
        other = _mk_section(db_session, other_course, period, "B")
        mine_student = _mk_student(db_session, "teacher-mine")
        other_student = _mk_student(db_session, "teacher-other")
        _enroll(db_session, mine_student, mine)
        _enroll(db_session, other_student, other)
        teacher = _mk_teacher(db_session, "results")
        _assign_teacher(db_session, teacher, mine)
        db_session.commit()

        _login(client, MANAGEMENT)
        my_exam = _create(client, mine_course, period, [mine]).json()
        other_exam = _create(
            client,
            other_course,
            period,
            [other],
            location="Hall B",
            start="13:00:00",
            end="15:00:00",
        ).json()

        _login(client, teacher.user.email)
        allowed = client.post(
            f"{API}/{my_exam['id']}/results",
            json={"student_id": str(mine_student.id), "score": 70},
        )
        assert allowed.status_code == 201, allowed.text

        refused = client.post(
            f"{API}/{other_exam['id']}/results",
            json={"student_id": str(other_student.id), "score": 70},
        )
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "EXAM_FORBIDDEN"

    def test_a_teacher_cannot_publish(self, client, db_session):
        period, course, section, student = self._setup(db_session, "teacher-publish")
        teacher = _mk_teacher(db_session, "publish")
        _assign_teacher(db_session, teacher, section)
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 70},
        )

        _login(client, teacher.user.email)
        assert client.post(f"{API}/{created['id']}/publication").status_code == 403


# ── D. Publication ─────────────────────────────────────────────────────────


class TestPublication:
    def _setup(self, db_session, tag: str):
        period = _mk_period(db_session, tag)
        course = _mk_course(db_session, tag)
        section = _mk_section(db_session, course, period, "A")
        student = _mk_student(db_session, f"{tag}-student")
        _enroll(db_session, student, section)
        db_session.commit()
        return period, course, section, student

    def test_a_student_sees_the_schedule_but_no_result_before_publication(
        self, client, db_session
    ):
        period, course, section, student = self._setup(db_session, "prepublish")
        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 91},
        )

        _login(client, student.user.email)
        mine = client.get(f"{API}/me").json()
        assert mine["total"] == 1
        item = mine["items"][0]
        assert item["results_published"] is False
        assert item["result"] is None
        assert "score" not in str(item.get("result"))

        # The examination detail endpoint is not a student surface at all.
        assert client.get(f"{API}/{created['id']}").status_code == 404

    def test_publication_releases_the_result(self, client, db_session):
        period, course, section, student = self._setup(db_session, "publish")
        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 91, "letter_grade": "A"},
        )

        published = client.post(f"{API}/{created['id']}/publication")
        assert published.status_code == 200, published.text
        assert published.json()["published_count"] == 1

        _login(client, student.user.email)
        item = client.get(f"{API}/me").json()["items"][0]
        assert item["results_published"] is True
        assert item["result"]["score"] == 91
        assert item["result"]["letter_grade"] == "A"

    def test_publishing_twice_is_refused(self, client, db_session):
        period, course, section, student = self._setup(db_session, "republish")
        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 70},
        )
        assert client.post(f"{API}/{created['id']}/publication").status_code == 200
        again = client.post(f"{API}/{created['id']}/publication")
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "EXAM_ALREADY_PUBLISHED"

    def test_a_cancelled_examination_cannot_be_published(self, client, db_session):
        period, course, section, student = self._setup(db_session, "cancel-publish")
        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 70},
        )
        cancel = client.post(
            f"{API}/{created['id']}/cancellation",
            json={"reason": "The venue was declared structurally unsafe."},
        )
        assert cancel.status_code == 200, cancel.text

        response = client.post(f"{API}/{created['id']}/publication")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "EXAM_CANCELLED"

    def test_cancellation_keeps_the_record_and_blocks_new_results(
        self, client, db_session
    ):
        period, course, section, student = self._setup(db_session, "cancel-keep")
        _login(client, ADMIN)
        created = _create(client, course, period, [section]).json()

        cancel = client.post(
            f"{API}/{created['id']}/cancellation",
            json={"reason": "The examination was postponed to the next term."},
        )
        assert cancel.status_code == 200
        body = cancel.json()
        assert body["status"] == "CANCELLED"
        assert body["cancellation_reason"]
        assert body["section_count"] == 1

        blocked = client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 70},
        )
        assert blocked.status_code == 422


# ── E. Dashboard and permissions ───────────────────────────────────────────


class TestDashboardAndPermissions:
    def test_the_dashboard_reports_real_counts(self, client, db_session):
        period = _mk_period(db_session, "dash")
        course = _mk_course(db_session, "dash")
        section = _mk_section(db_session, course, period, "A")
        student = _mk_student(db_session, "dash-student")
        _enroll(db_session, student, section)
        db_session.commit()

        _login(client, MANAGEMENT)
        upcoming = _create(client, course, period, [section], title="Upcoming").json()
        _create(
            client,
            course,
            period,
            [section],
            title="Past",
            exam_date=_day(-5),
            location="Hall B",
            start="13:00:00",
            end="15:00:00",
        )
        client.post(
            f"{API}/{upcoming['id']}/results",
            json={"student_id": str(student.id), "score": 70},
        )

        body = client.get(f"{API}/dashboard").json()
        assert body["counts"]["total"] == 2
        assert body["counts"]["upcoming"] == 1
        assert body["counts"]["results_recorded"] == 1
        assert body["counts"]["eligible_students"] == 1
        assert [row["title"] for row in body["upcoming"]] == ["Upcoming"]

    def test_students_and_teachers_hold_the_expected_permissions(self):
        student = set(ROLE_PERMISSIONS["STUDENT"])
        teacher = set(ROLE_PERMISSIONS["TEACHER"])
        management = set(ROLE_PERMISSIONS["MANAGEMENT"])

        assert "exams.view" in student
        assert "exams.manage" not in student
        assert "exams.record_results" not in student
        assert "exams.publish" not in student

        assert {"exams.view", "exams.record_results"} <= teacher
        assert "exams.manage" not in teacher
        assert "exams.publish" not in teacher

        assert {"exams.view", "exams.manage", "exams.record_results", "exams.publish"} <= management


# ── F. Academic integration ────────────────────────────────────────────────


class TestAcademicIntegration:
    """The examination must hang off the real academic record, not a name match.

    A section belongs to a subject and an intake, and may serve one or more
    programme offerings. A student's placement says which offering they are in
    now. These tests pin the two joins that make eligibility real rather than
    "everyone enrolled anywhere in this subject".
    """

    def test_a_section_outside_the_examinations_offering_is_refused(
        self, client, db_session
    ):
        period = _mk_period(db_session, "offscope")
        course = _mk_course(db_session, "offscope")
        inside = _mk_section(db_session, course, period, "A")
        outside = _mk_section(db_session, course, period, "B")
        offering_a = _mk_offering(db_session, period, "A")
        offering_b = _mk_offering(db_session, period, "B")
        _link(db_session, inside, offering_a)
        _link(db_session, outside, offering_b)
        db_session.commit()

        _login(client, MANAGEMENT)
        refused = _create(
            client,
            course,
            period,
            [outside],
            program_offering_id=offering_a.id,
        )
        assert refused.status_code == 422
        assert (
            refused.json()["error"]["code"]
            == "EXAM_SECTION_OFFERING_MISMATCH"
        )

        accepted = _create(
            client,
            course,
            period,
            [inside],
            program_offering_id=offering_a.id,
        )
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["sections"][0]["offerings"] == [offering_a.name]

    def test_changing_the_offering_revalidates_existing_sections(
        self, client, db_session
    ):
        period = _mk_period(db_session, "offmove")
        course = _mk_course(db_session, "offmove")
        section = _mk_section(db_session, course, period, "A")
        offering_a = _mk_offering(db_session, period, "A")
        offering_b = _mk_offering(db_session, period, "B")
        _link(db_session, section, offering_a)
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _create(
            client, course, period, [section], program_offering_id=offering_a.id
        ).json()

        moved = client.patch(
            f"{API}/{created['id']}",
            json={"program_offering_id": str(offering_b.id)},
        )
        assert moved.status_code == 422
        assert moved.json()["error"]["code"] == "EXAM_SECTION_OFFERING_MISMATCH"

    def test_a_student_placed_in_another_offering_is_not_eligible(
        self, client, db_session
    ):
        period = _mk_period(db_session, "moved")
        course = _mk_course(db_session, "moved")
        section = _mk_section(db_session, course, period, "A")
        # A second section of the same subject that does serve the student's
        # new offering. It exists so a mis-correlated query, which searches
        # every enrollment instead of this one, would wrongly find a match and
        # count the student as eligible for section A.
        other = _mk_section(db_session, course, period, "B")
        offering_a = _mk_offering(db_session, period, "A")
        offering_b = _mk_offering(db_session, period, "B")
        _link(db_session, section, offering_a)
        _link(db_session, other, offering_b)
        student = _mk_student(db_session, "moved")
        # Both enrollment rows still say ENROLLED, but the student has since
        # been placed in offering B: the academic record wins.
        _enroll(db_session, student, section)
        _enroll(db_session, student, other)
        _place(db_session, student, offering_b)
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        assert created["eligible_count"] == 0

        current = _create(
            client,
            course,
            period,
            [other],
            title="Current cohort",
            location="Hall C",
            start="13:00:00",
            end="15:00:00",
        ).json()
        assert current["eligible_count"] == 1

        detail = client.get(f"{API}/{created['id']}").json()
        assert detail["eligible_students"] == []

        refused = client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 60},
        )
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "EXAM_STUDENT_NOT_ELIGIBLE"

    def test_a_shared_section_includes_students_from_every_offering_it_serves(
        self, client, db_session
    ):
        period = _mk_period(db_session, "shared")
        course = _mk_course(db_session, "shared")
        shared = _mk_section(db_session, course, period, "SHARED")
        offering_a = _mk_offering(db_session, period, "A")
        offering_b = _mk_offering(db_session, period, "B")
        _link(db_session, shared, offering_a, offering_b)
        student_a = _mk_student(db_session, "shared-a")
        student_b = _mk_student(db_session, "shared-b")
        _enroll(db_session, student_a, shared)
        _enroll(db_session, student_b, shared)
        _place(db_session, student_a, offering_a)
        _place(db_session, student_b, offering_b)
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _create(client, course, period, [shared]).json()
        assert created["eligible_count"] == 2
        detail = client.get(f"{API}/{created['id']}").json()
        offerings = {
            row["student_number"]: row["program_offering_name"]
            for row in detail["eligible_students"]
        }
        assert offerings[student_a.student_id] == offering_a.name
        assert offerings[student_b.student_id] == offering_b.name

    def test_a_withdrawn_admission_removes_eligibility(self, client, db_session):
        period = _mk_period(db_session, "withdrawn")
        course = _mk_course(db_session, "withdrawn")
        section = _mk_section(db_session, course, period, "A")
        offering = _mk_offering(db_session, period, "W")
        student = _mk_student(db_session, "withdrawn")
        _enroll(db_session, student, section)
        _place(db_session, student, offering, status="WITHDRAWN")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        assert created["eligible_count"] == 0

    def test_a_legacy_student_without_an_admission_remains_eligible(
        self, client, db_session
    ):
        period = _mk_period(db_session, "legacy")
        course = _mk_course(db_session, "legacy")
        section = _mk_section(db_session, course, period, "A")
        student = _mk_student(db_session, "legacy")
        _enroll(db_session, student, section)
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        assert created["eligible_count"] == 1

    def test_a_stale_enrollment_does_not_advertise_an_upcoming_paper(
        self, client, db_session
    ):
        period = _mk_period(db_session, "stale")
        course = _mk_course(db_session, "stale")
        section = _mk_section(db_session, course, period, "A")
        offering_a = _mk_offering(db_session, period, "A")
        offering_b = _mk_offering(db_session, period, "B")
        _link(db_session, section, offering_a)
        student = _mk_student(db_session, "stale")
        _enroll(db_session, student, section)
        db_session.commit()

        _login(client, MANAGEMENT)
        sat = _create(client, course, period, [section], title="Paper sat").json()
        recorded = client.post(
            f"{API}/{sat['id']}/results",
            json={"student_id": str(student.id), "score": 90},
        )
        assert recorded.status_code == 201, recorded.text
        assert client.post(f"{API}/{sat['id']}/publication").status_code == 200

        # The student is placed in another offering, and their enrollment row in
        # the old section is left as it is by the workflow.
        _place(db_session, student, offering_b)
        later = _create(
            client,
            course,
            period,
            [section],
            title="Paper they will not sit",
            location="Hall D",
            start="13:00:00",
            end="15:00:00",
        ).json()
        db_session.commit()

        _login(client, student.user.email)
        items = client.get(f"{API}/me").json()["items"]
        ids = {row["id"] for row in items}
        assert later["id"] not in ids
        # The paper already sat remains in the record with its published mark.
        history = next(row for row in items if row["id"] == sat["id"])
        assert history["result"]["score"] == 90

    def test_a_published_result_survives_a_later_enrollment_change(
        self, client, db_session
    ):
        period = _mk_period(db_session, "history")
        course = _mk_course(db_session, "history")
        section = _mk_section(db_session, course, period, "A")
        student = _mk_student(db_session, "history")
        _enroll(db_session, student, section)
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _create(client, course, period, [section]).json()
        recorded = client.post(
            f"{API}/{created['id']}/results",
            json={"student_id": str(student.id), "score": 88},
        )
        assert recorded.status_code == 201, recorded.text
        published = client.post(f"{API}/{created['id']}/publication")
        assert published.status_code == 200, published.text

        # The student later leaves the section.
        enrollment = (
            db_session.query(Enrollment)
            .filter(
                Enrollment.student_id == student.id,
                Enrollment.class_section_id == section.id,
            )
            .one()
        )
        enrollment.status = "DROPPED"
        enrollment.dropped_at = datetime.now()
        db_session.commit()

        _login(client, student.user.email)
        body = client.get(f"{API}/me").json()
        assert [row["id"] for row in body["items"]] == [created["id"]]
        assert body["items"][0]["result"]["score"] == 88
