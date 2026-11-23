"""Phase 3 (corrected): student-level attendance from stored absences.

These tests pin the model the institution approved.

* The unit is a student and an admission episode. There is no section or session
  in the calculation, and a teacher's assignment only decides *who they may
  record for* — never what the student's total is.
* Only absences are stored. A working day with no absence is a day attended, so
  reading attendance never creates a row.
* A date counts only if the calendar says it is a working day (Monday–Friday by
  default, minus holidays and closures, plus exceptional working days), it is on
  or after the approved commencement, and it is inside the intake's instructional
  period.
* One current absence per student/episode/date; a correction supersedes and keeps
  the previous record, and both halves commit with their audit entry or not at all.
* The percentage is derived: ``(eligible − absences) / eligible × 100``. It is
  never stored and never invented — with no eligible day yet, it is ``null``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from app.auth.service import hash_password
from app.models.academic import (
    AcademicPeriod,
    ClassSection,
    Course,
    Enrollment,
    TeacherAssignment,
)
from app.models.admission import AcademicAdmission
from app.models.attendance import AttendanceCommencement
from app.models.attendance_absence import AttendanceAbsence
from app.models.audit import AuditLog
from app.models.identity import Role, Staff, Student, User
from app.services import absence as svc

API = "/api/v1/attendance"
CALENDAR = "/api/v1/academics/calendar/days"
LOGIN = "/api/v1/auth/login"

ADMIN = "admin@school.portal"
MANAGEMENT = "management@school.portal"
TEACHER = "teacher@school.portal"

#: Two full weeks: Monday 2024-03-04 … Friday 2024-03-15 = 10 working days.
#: The window is entirely in the past, so a calculation "through today" covers
#: the whole instructional period regardless of when the suite runs.
INTAKE_START = date(2024, 3, 4)
INTAKE_END = date(2024, 3, 15)
COMMENCEMENT = date(2024, 3, 4)
ACTIVATED_AT = datetime(2024, 3, 4, 8, 0)
FIRST_WEEK_DAYS = 10

REASON = "Student was absent from scheduled instruction."
CORRECTION_REASON = "The register shows the absence belonged on the following day."


# ── Fixtures ───────────────────────────────────────────────────────────────


def _login(client, email: str) -> None:
    response = client.post(LOGIN, json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text


def _mk_intake(
    db, tag: str, *, start: date = INTAKE_START, end: date = INTAKE_END
) -> AcademicPeriod:
    intake = AcademicPeriod(
        code=f"P3{uuid.uuid4().hex[:10]}",
        name=f"Phase 3 intake {tag}",
        start_date=start,
        end_date=end,
        status="ACTIVE",
    )
    db.add(intake)
    db.flush()
    return intake


def _mk_offering(db, intake: AcademicPeriod, tag: str):
    from app.models.academic import ProgramOffering

    offering = ProgramOffering(
        academic_period_id=intake.id,
        source_id=f"P3-{tag}-{uuid.uuid4().hex[:6]}",
        source_key=f"p3-offering-{tag}-{uuid.uuid4().hex[:8]}",
        name=f"Phase 3 offering {tag}",
    )
    db.add(offering)
    db.flush()
    return offering


def _mk_student(db, tag: str, *, with_user: bool = False) -> Student:
    user = User(
        email=f"p3-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"p3-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Phase3 {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    if with_user:
        student_role = db.query(Role).filter(Role.name == "STUDENT").first()
        assert student_role is not None
        user.roles.append(student_role)
    student = Student(
        user_id=user.id,
        student_id=f"P3-{tag.upper()}-{uuid.uuid4().hex[:6]}",
        first_name="Phase3",
        last_name=tag,
        status="ACTIVE",
    )
    db.add(student)
    db.flush()
    return student


def _mk_episode(
    db,
    student: Student,
    intake: AcademicPeriod,
    offering,
    *,
    status: str = "ACTIVE",
    activated_at: datetime | None = ACTIVATED_AT,
    ended_at: datetime | None = None,
) -> AcademicAdmission:
    actor = db.query(User).filter(User.email == ADMIN).first()
    assert actor is not None
    episode = AcademicAdmission(
        student_id=student.id,
        admission_intake_id=intake.id,
        admitted_program_offering_id=offering.id,
        status=status,
        initial_status=status,
        record_origin="NEW_ADMISSION",
        verification_status="VERIFIED",
        activated_at=activated_at,
        ended_at=ended_at,
        created_by_id=actor.id,
    )
    db.add(episode)
    db.flush()
    return episode


def _commence(db, student: Student, episode: AcademicAdmission, day: date = COMMENCEMENT):
    actor = db.query(User).filter(User.email == ADMIN).first()
    assert actor is not None
    row = AttendanceCommencement(
        admission_id=episode.id,
        student_id=student.id,
        commencement_date=day,
        commencement_type="SCHEDULED",
        reason="Confirmed against the enrolment register for this intake.",
        suggested_date=day,
        approved_by_id=actor.id,
    )
    db.add(row)
    db.flush()
    return row


def _scenario(db, tag: str, *, commencement: date | None = COMMENCEMENT):
    intake = _mk_intake(db, tag)
    offering = _mk_offering(db, intake, tag)
    student = _mk_student(db, tag)
    episode = _mk_episode(db, student, intake, offering)
    if commencement is not None:
        _commence(db, student, episode, commencement)
    return student, episode, intake, offering


def _record(
    client,
    student: Student,
    episode: AcademicAdmission,
    day: date,
    reason: str = REASON,
):
    return client.post(
        f"{API}/students/{student.id}/absences",
        json={
            "admission_id": str(episode.id),
            "absence_date": day.isoformat(),
            "reason": reason,
        },
    )


def _correct(client, student: Student, absence_id: str, day: date, reason: str):
    return client.post(
        f"{API}/students/{student.id}/absences/{absence_id}/corrections",
        json={"absence_date": day.isoformat(), "reason": reason},
    )


def _declare(client, day: date, day_type: str, title: str):
    response = client.post(
        CALENDAR,
        json={
            "calendar_date": day.isoformat(),
            "day_type": day_type,
            "title": title,
            "reason": "Declared by the registrar for the whole university.",
        },
    )
    assert response.status_code == 201, response.text
    return response


def _teacher_staff(db) -> Staff:
    user = db.query(User).filter(User.email == TEACHER).first()
    assert user is not None
    staff = db.query(Staff).filter(Staff.user_id == user.id).first()
    assert staff is not None
    return staff


def _mk_section(db, intake: AcademicPeriod, tag: str) -> ClassSection:
    course = Course(
        code=f"P3-{uuid.uuid4().hex[:6]}", name=f"Phase 3 course {tag}"
    )
    db.add(course)
    db.flush()
    section = ClassSection(
        course_id=course.id,
        academic_period_id=intake.id,
        section_code="A",
        status="ACTIVE",
    )
    db.add(section)
    db.flush()
    return section


def _enroll(db, student: Student, section: ClassSection) -> Enrollment:
    enrollment = Enrollment(
        student_id=student.id,
        class_section_id=section.id,
        status="ENROLLED",
    )
    db.add(enrollment)
    db.flush()
    return enrollment


# ── A. Working-day calculation ─────────────────────────────────────────────


class TestWorkingDays:
    def test_default_week_counts_as_ten_working_days(self, client, db_session):
        student, _episode, _intake, _offering = _scenario(db_session, "weekdays")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = client.get(f"{API}/students/{student.id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["eligible_days"] == FIRST_WEEK_DAYS
        assert body["absence_count"] == 0
        assert body["percentage"] == 100.0
        assert body["eligible"] is True

    def test_a_holiday_is_excluded(self, client, db_session):
        student, _episode, _intake, _offering = _scenario(db_session, "holiday")
        db_session.commit()

        _login(client, ADMIN)
        _declare(client, date(2024, 3, 5), "HOLIDAY", "University holiday")

        _login(client, MANAGEMENT)
        body = client.get(f"{API}/students/{student.id}").json()
        assert body["eligible_days"] == FIRST_WEEK_DAYS - 1
        assert body["percentage"] == 100.0

    def test_a_closure_is_excluded(self, client, db_session):
        student, _episode, _intake, _offering = _scenario(db_session, "closure")
        db_session.commit()

        _login(client, ADMIN)
        _declare(client, date(2024, 3, 6), "CLOSURE", "Campus closure")

        _login(client, MANAGEMENT)
        body = client.get(f"{API}/students/{student.id}").json()
        assert body["eligible_days"] == FIRST_WEEK_DAYS - 1

    def test_an_exceptional_working_day_adds_a_saturday(self, client, db_session):
        student, _episode, _intake, _offering = _scenario(db_session, "exceptional")
        db_session.commit()

        _login(client, ADMIN)
        _declare(client, date(2024, 3, 9), "EXCEPTIONAL_WORKING", "Make-up day")

        _login(client, MANAGEMENT)
        body = client.get(f"{API}/students/{student.id}").json()
        assert body["eligible_days"] == FIRST_WEEK_DAYS + 1

    def test_long_ranges_are_counted_across_resolver_chunks(self, db_session):
        start = date(2023, 1, 2)
        end = date(2024, 3, 15)  # 439 days, beyond the resolver's 366-day bound
        expected = sum(
            1
            for offset in range((end - start).days + 1)
            if (start + timedelta(days=offset)).weekday() < 5
        )
        assert svc.count_working_days(db_session, start, end) == expected

    def test_an_empty_window_has_no_percentage(self, db_session):
        student, episode, intake, _offering = _scenario(
            db_session, "empty-window", commencement=None
        )

        # Commencing after the instructional period ends leaves no eligible day.
        later = _commence(
            db_session, student, episode, intake.end_date + timedelta(days=30)
        )
        calc = svc.calculate(
            db_session,
            episode=episode,
            period=intake,
            commencement=later.commencement_date,
            today=intake.end_date + timedelta(days=60),
        )
        assert calc["eligible_days"] == 0
        assert calc["percentage"] is None


# ── B. Recording rules ─────────────────────────────────────────────────────


class TestRecording:
    def test_a_weekend_absence_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "weekend")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, episode, date(2024, 3, 9))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "ABSENCE_NON_WORKING_DAY"

        db_session.expire_all()
        assert db_session.query(AttendanceAbsence).count() == 0

    def test_a_holiday_absence_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "holiday-record")
        db_session.commit()

        _login(client, ADMIN)
        _declare(client, date(2024, 3, 5), "HOLIDAY", "University holiday")

        _login(client, MANAGEMENT)
        response = _record(client, student, episode, date(2024, 3, 5))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "ABSENCE_NON_WORKING_DAY"

    def test_an_exceptional_working_day_can_be_recorded(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "exceptional-rec")
        db_session.commit()

        _login(client, ADMIN)
        _declare(client, date(2024, 3, 9), "EXCEPTIONAL_WORKING", "Make-up day")

        _login(client, MANAGEMENT)
        response = _record(client, student, episode, date(2024, 3, 9))
        assert response.status_code == 201, response.text
        assert response.json()["absence"]["absence_date"] == "2024-03-09"
        assert response.json()["calculation"]["eligible_days"] == FIRST_WEEK_DAYS + 1

    def test_an_absence_reduces_the_percentage(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "reduce")
        db_session.commit()

        _login(client, MANAGEMENT)
        first = _record(client, student, episode, date(2024, 3, 4))
        assert first.status_code == 201, first.text
        assert first.json()["calculation"]["absence_count"] == 1
        assert first.json()["calculation"]["percentage"] == 90.0

        second = _record(client, student, episode, date(2024, 3, 5))
        assert second.status_code == 201, second.text
        assert second.json()["calculation"]["absence_count"] == 2
        assert second.json()["calculation"]["percentage"] == 80.0

    def test_a_duplicate_absence_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "duplicate")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, episode, date(2024, 3, 4)).status_code == 201

        duplicate = _record(client, student, episode, date(2024, 3, 4))
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"]["code"] == "ABSENCE_ALREADY_RECORDED"

        db_session.expire_all()
        assert (
            db_session.query(AttendanceAbsence)
            .filter(AttendanceAbsence.admission_id == episode.id)
            .count()
            == 1
        )

    def test_an_empty_reason_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "no-reason")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, episode, date(2024, 3, 4), reason="   ")
        assert response.status_code == 422, response.text

    def test_a_future_absence_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "future")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(
            client, student, episode, date.today() + timedelta(days=1)
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "ABSENCE_IN_FUTURE"

    def test_a_date_before_the_commencement_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(
            db_session, "before-start", commencement=date(2024, 3, 6)
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, episode, date(2024, 3, 4))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "ABSENCE_BEFORE_COMMENCEMENT"

    def test_a_date_outside_the_instructional_period_is_refused(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "outside")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, episode, date(2024, 3, 29))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "ABSENCE_OUTSIDE_PERIOD"

    def test_an_episode_without_a_commencement_cannot_record(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(
            db_session, "no-commencement", commencement=None
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, episode, date(2024, 3, 4))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "ABSENCE_NO_COMMENCEMENT"

        detail = client.get(f"{API}/students/{student.id}").json()
        assert detail["eligible"] is False
        assert detail["ineligible_reason"] == "NO_COMMENCEMENT"
        assert detail["percentage"] is None

    def test_a_terminal_episode_cannot_record(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "terminal")
        episode.status = "COMPLETED"
        episode.ended_at = datetime(2024, 3, 8, 12, 0)
        db_session.flush()
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, episode, date(2024, 3, 4))
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ABSENCE_ADMISSION_NOT_ACTIVE"

        detail = client.get(f"{API}/students/{student.id}").json()
        assert detail["eligible"] is False
        assert detail["ineligible_reason"] == "NO_ACTIVE_ADMISSION"

    def test_an_episode_of_another_student_is_not_found(self, client, db_session):
        first, _first_episode, _i, _o = _scenario(db_session, "owner-a")
        _second, second_episode, _i2, _o2 = _scenario(db_session, "owner-b")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, first, second_episode, date(2024, 3, 4))
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "ABSENCE_ADMISSION_NOT_FOUND"


# ── C. Episode separation ──────────────────────────────────────────────────


class TestEpisodes:
    def test_absences_do_not_carry_between_episodes(self, client, db_session):
        first_student, first_episode, _i, _o = _scenario(db_session, "sep-one")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, first_student, first_episode, date(2024, 3, 4)).status_code == 201

        first_episode.status = "COMPLETED"
        first_episode.ended_at = datetime(2024, 3, 15, 12, 0)
        db_session.flush()

        later_intake = _mk_intake(
            db_session,
            "sep-two",
            start=date(2025, 1, 6),
            end=date(2025, 1, 17),
        )
        later_offering = _mk_offering(db_session, later_intake, "sep-two")
        later_episode = _mk_episode(
            db_session,
            first_student,
            later_intake,
            later_offering,
            activated_at=datetime(2025, 1, 6, 8, 0),
        )
        _commence(db_session, first_student, later_episode, date(2025, 1, 6))
        db_session.commit()

        body = client.get(f"{API}/students/{first_student.id}").json()
        assert body["admission_id"] == str(later_episode.id)
        assert body["absence_count"] == 0
        assert body["percentage"] == 100.0
        assert body["absences"] == []

        # The same date may be recorded again in a different episode: uniqueness
        # is per student, per episode, per date.
        assert (
            _record(client, first_student, later_episode, date(2025, 1, 6)).status_code
            == 201
        )

        db_session.expire_all()
        assert (
            db_session.query(AttendanceAbsence)
            .filter(AttendanceAbsence.student_id == first_student.id)
            .count()
            == 2
        )


# ── D. Correction and audit ────────────────────────────────────────────────


class TestCorrection:
    def test_correction_supersedes_and_preserves_the_previous_record(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "correct")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 4))
        assert created.status_code == 201, created.text
        original_id = created.json()["absence"]["id"]

        corrected = _correct(
            client, student, original_id, date(2024, 3, 5), CORRECTION_REASON
        )
        assert corrected.status_code == 201, corrected.text
        body = corrected.json()
        assert body["absence"]["supersedes_id"] == original_id
        assert body["absence"]["absence_date"] == "2024-03-05"
        assert body["calculation"]["absence_count"] == 1

        detail = client.get(f"{API}/students/{student.id}").json()
        assert len(detail["absences"]) == 2
        superseded = next(
            row for row in detail["absences"] if row["id"] == original_id
        )
        assert superseded["superseded_at"] is not None
        assert superseded["absence_date"] == "2024-03-04"
        assert superseded["reason"] == REASON

        db_session.expire_all()
        stored = (
            db_session.query(AttendanceAbsence)
            .filter(AttendanceAbsence.id == uuid.UUID(original_id))
            .first()
        )
        assert stored is not None and stored.superseded_at is not None

        entries = (
            db_session.query(AuditLog)
            .filter(AuditLog.entity_type == "attendance_absence")
            .order_by(AuditLog.created_at)
            .all()
        )
        assert [entry.action for entry in entries] == [
            "attendance.absence.recorded",
            "attendance.absence.corrected",
        ]
        correction = entries[-1]
        assert correction.context["previous_absence_date"] == "2024-03-04"
        assert correction.context["absence_date"] == "2024-03-05"
        assert correction.context["previous_reason"] == REASON
        assert correction.context["reason"] == CORRECTION_REASON
        assert correction.actor_id is not None

    def test_a_correction_requires_a_substantive_reason(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "correct-reason")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 4))
        absence_id = created.json()["absence"]["id"]

        response = _correct(client, student, absence_id, date(2024, 3, 5), "typo")
        assert response.status_code == 422, response.text
        assert (
            response.json()["error"]["code"] == "ABSENCE_CORRECTION_REASON_REQUIRED"
        )

    def test_an_unchanged_correction_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "unchanged")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 4))
        absence_id = created.json()["absence"]["id"]

        response = _correct(
            client, student, absence_id, date(2024, 3, 4), REASON
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "ABSENCE_UNCHANGED"

    def test_a_correction_onto_another_current_absence_is_refused(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "clash")
        db_session.commit()

        _login(client, MANAGEMENT)
        first = _record(client, student, episode, date(2024, 3, 4))
        second = _record(client, student, episode, date(2024, 3, 5))
        assert second.status_code == 201

        response = _correct(
            client,
            student,
            first.json()["absence"]["id"],
            date(2024, 3, 5),
            CORRECTION_REASON,
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ABSENCE_ALREADY_RECORDED"

    def test_a_superseded_record_cannot_be_corrected_again(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "double-correct")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 4))
        original_id = created.json()["absence"]["id"]
        assert (
            _correct(
                client, student, original_id, date(2024, 3, 5), CORRECTION_REASON
            ).status_code
            == 201
        )

        response = _correct(
            client, student, original_id, date(2024, 3, 6), CORRECTION_REASON
        )
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "ABSENCE_NOT_FOUND"

    def test_an_audit_failure_rolls_back_the_record(
        self, client, db_session, monkeypatch
    ):
        student, episode, _intake, _offering = _scenario(db_session, "rollback-record")
        db_session.commit()

        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        monkeypatch.setattr("app.services.absence.record_audit", _explode)

        _login(client, MANAGEMENT)
        with pytest.raises(RuntimeError):
            _record(client, student, episode, date(2024, 3, 4))

        db_session.expire_all()
        assert (
            db_session.query(AttendanceAbsence)
            .filter(AttendanceAbsence.admission_id == episode.id)
            .count()
            == 0
        )

    def test_an_audit_failure_rolls_back_a_correction(
        self, client, db_session, monkeypatch
    ):
        student, episode, _intake, _offering = _scenario(db_session, "rollback-correct")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 4))
        absence_id = uuid.UUID(created.json()["absence"]["id"])

        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        monkeypatch.setattr("app.services.absence.record_audit", _explode)

        with pytest.raises(RuntimeError):
            _correct(
                client, student, str(absence_id), date(2024, 3, 5), CORRECTION_REASON
            )

        db_session.expire_all()
        rows = (
            db_session.query(AttendanceAbsence)
            .filter(AttendanceAbsence.admission_id == episode.id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == absence_id
        assert rows[0].superseded_at is None


# ── E. Who may record ──────────────────────────────────────────────────────


class TestTeacherScope:
    def test_a_teacher_records_only_for_their_own_students(self, client, db_session):
        intake = _mk_intake(db_session, "scope")
        offering = _mk_offering(db_session, intake, "scope")
        mine = _mk_student(db_session, "scope-mine")
        mine_episode = _mk_episode(db_session, mine, intake, offering)
        _commence(db_session, mine, mine_episode)

        other = _mk_student(db_session, "scope-other")
        other_episode = _mk_episode(db_session, other, intake, offering)
        _commence(db_session, other, other_episode)

        section = _mk_section(db_session, intake, "scope")
        _enroll(db_session, mine, section)
        db_session.add(
            TeacherAssignment(
                class_section_id=section.id,
                staff_id=_teacher_staff(db_session).id,
                is_active=True,
            )
        )
        db_session.commit()

        _login(client, TEACHER)
        allowed = _record(client, mine, mine_episode, date(2024, 3, 4))
        assert allowed.status_code == 201, allowed.text
        assert allowed.json()["absence"]["recorded_by_name"] is not None

        denied = _record(client, other, other_episode, date(2024, 3, 4))
        assert denied.status_code == 403, denied.text
        assert denied.json()["error"]["code"] == "ATTENDANCE_STUDENT_OUT_OF_SCOPE"

        # The teacher's list is scoped too: a search for an unrelated student
        # returns nothing rather than their record.
        mine_list = client.get(
            f"{API}/students", params={"search": mine.student_id}
        ).json()
        assert [row["student_number"] for row in mine_list["items"]] == [mine.student_id]

        other_list = client.get(
            f"{API}/students", params={"search": other.student_id}
        ).json()
        assert other_list["items"] == []

        # Once recorded, the absence is part of the student's university-wide
        # total: management sees the same figure the teacher recorded.
        _login(client, MANAGEMENT)
        detail = client.get(f"{API}/students/{mine.id}").json()
        assert detail["absence_count"] == 1
        assert detail["percentage"] == 90.0

    def test_management_can_record_anywhere(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "mgmt-any")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, episode, date(2024, 3, 4)).status_code == 201

    def test_admin_can_record_anywhere(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "admin-any")
        db_session.commit()

        _login(client, ADMIN)
        assert _record(client, student, episode, date(2024, 3, 4)).status_code == 201


# ── F. Student privacy ─────────────────────────────────────────────────────


class TestStudentPrivacy:
    def test_a_student_sees_only_their_own_attendance(self, client, db_session):
        mine = _mk_student(db_session, "self", with_user=True)
        intake = _mk_intake(db_session, "self")
        offering = _mk_offering(db_session, intake, "self")
        my_episode = _mk_episode(db_session, mine, intake, offering)
        _commence(db_session, mine, my_episode)

        other, other_episode, _i2, _o2 = _scenario(db_session, "self-other")
        db_session.commit()

        _login(client, ADMIN)
        assert _record(client, other, other_episode, date(2024, 3, 4)).status_code == 201

        user = db_session.query(User).filter(User.id == mine.user_id).first()
        assert user is not None
        _login(client, user.email)

        mine_body = client.get(f"{API}/me")
        assert mine_body.status_code == 200, mine_body.text
        body = mine_body.json()
        assert body["student_id"] == str(mine.id)
        assert body["episodes"][0]["absence_count"] == 0
        assert body["episodes"][0]["percentage"] == 100.0

        # The staff list and every per-student read are closed to a student.
        assert client.get(f"{API}/students").status_code == 403
        assert client.get(f"{API}/students/{other.id}").status_code == 403
        assert _record(client, other, other_episode, date(2024, 3, 5)).status_code == 403

    def test_anonymous_is_unauthenticated(self, client):
        assert client.get(f"{API}/me").status_code == 401
        assert client.get(f"{API}/students").status_code == 401

    def test_the_permission_is_granted_to_the_right_roles(self, db_session):
        def permissions(role_name: str) -> set[str]:
            role = db_session.query(Role).filter(Role.name == role_name).first()
            assert role is not None
            return {permission.codename for permission in role.permissions}

        assert "attendance.record_absence" in permissions("ADMIN")
        assert "attendance.record_absence" in permissions("MANAGEMENT")
        assert "attendance.record_absence" in permissions("TEACHER")
        assert "attendance.record_absence" not in permissions("STUDENT")
        # The class-register permission stays retired from the teacher role.
        assert "attendance.record_class" not in permissions("TEACHER")


# ── G. Reads do not write ──────────────────────────────────────────────────


class TestReadsArePure:
    def test_listing_students_creates_no_attendance_rows(self, client, db_session):
        student, _episode, _intake, _offering = _scenario(db_session, "pure")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = client.get(f"{API}/students", params={"search": student.student_id})
        assert response.status_code == 200, response.text
        assert [row["student_number"] for row in response.json()["items"]] == [
            student.student_id
        ]

        db_session.expire_all()
        assert db_session.query(AttendanceAbsence).count() == 0
