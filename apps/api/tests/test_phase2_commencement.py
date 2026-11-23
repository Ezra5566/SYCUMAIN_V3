"""Phase 2: attendance commencement.

A commencement is an institutional approval, not a derived fact. These tests pin
the policy the institution confirmed:

* Admin and Management approve independently; teachers and students cannot.
* The suggested date is the first instructional working day on or after
  ``max(intake start, activation date)`` and must be explicitly confirmed — a
  stale confirmation is refused, and a non-working date cannot be approved.
* Late joins must be later than the suggestion and carry an explanation; manual
  commencements must differ from it and carry one too.
* Only ACTIVE episodes can be commenced, one current record per episode, and a
  correction supersedes rather than rewrites.
* An episode that ends and is replaced keeps its own commencement; nothing is
  transferred, reset by a programme change, or recalculated from the calendar.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from app.models.academic import AcademicPeriod, Major, Program, ProgramOffering
from app.models.admission import AcademicAdmission
from app.models.attendance import AttendanceCommencement
from app.models.audit import AuditLog
from app.models.identity import Role, Student, User
from app.services import commencement as svc

API = "/api/v1/attendance"
LOGIN = "/api/v1/auth/login"

ADMIN = "admin@school.portal"
MANAGEMENT = "management@school.portal"
TEACHER = "teacher@school.portal"
STUDENT_ACCOUNT = "student@school.portal"

INTAKE_START = date(2033, 2, 1)
INTAKE_END = date(2033, 6, 30)
ACTIVATED_AT = datetime(2033, 2, 10, 9, 0)
SUGGESTED = date(2033, 2, 10)

REASON = "Confirmed against the enrolment register for this intake."
LATE_REASON = "Visa issued after the intake started; the student joined later."
MANUAL_REASON = "Attendance established by the office from the class register."
CORRECTION_REASON = "The register shows the student started two days earlier."


# ── Fixtures ───────────────────────────────────────────────────────────────


def _login(client, email: str) -> None:
    response = client.post(LOGIN, json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text


def _mk_intake(
    db, tag: str, *, start: date = INTAKE_START, end: date = INTAKE_END
) -> AcademicPeriod:
    intake = AcademicPeriod(
        # `code` is String(20); the tag lives in the name, not here.
        code=f"P2{uuid.uuid4().hex[:10]}",
        name=f"Phase 2 intake {tag}",
        start_date=start,
        end_date=end,
        status="ACTIVE",
    )
    db.add(intake)
    db.flush()
    return intake


def _mk_offering(db, intake: AcademicPeriod, tag: str) -> ProgramOffering:
    offering = ProgramOffering(
        academic_period_id=intake.id,
        source_id=f"SRC-{tag}-{uuid.uuid4().hex[:6]}",
        source_key=f"p2-offering-{tag}-{uuid.uuid4().hex[:8]}",
        name=f"Phase 2 offering {tag}",
    )
    db.add(offering)
    db.flush()
    return offering


def _mk_student(db, tag: str) -> Student:
    from app.auth.service import hash_password

    user = User(
        email=f"p2-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"p2-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Phase2 {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"P2-{tag.upper()}-{uuid.uuid4().hex[:6]}",
        first_name="Phase2",
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
    offering: ProgramOffering,
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
        activated_at=activated_at if status in {"ACTIVE", "COMPLETED", "WITHDRAWN"} else None,
        ended_at=ended_at,
        created_by_id=actor.id,
    )
    db.add(episode)
    db.flush()
    return episode


def _payload(**overrides) -> dict:
    payload = {
        "commencement_date": SUGGESTED.isoformat(),
        "commencement_type": "SCHEDULED",
        "reason": REASON,
        "confirmed_suggested_date": SUGGESTED.isoformat(),
    }
    payload.update(overrides)
    return payload


def _approve(client, student: Student, episode: AcademicAdmission, **overrides):
    return client.post(
        f"{API}/students/{student.id}/admissions/{episode.id}/commencement",
        json=_payload(**overrides),
    )


def _correct(client, student: Student, episode: AcademicAdmission, **overrides):
    return client.post(
        f"{API}/students/{student.id}/admissions/{episode.id}/commencement/corrections",
        json=_payload(**overrides),
    )


def _scenario(db, tag: str):
    intake = _mk_intake(db, tag)
    offering = _mk_offering(db, intake, tag)
    student = _mk_student(db, tag)
    episode = _mk_episode(db, student, intake, offering)
    return student, episode, intake, offering


# ── A. Suggestion and explicit confirmation ────────────────────────────────


class TestSuggestion:
    def test_suggestion_is_the_later_of_intake_start_and_activation(
        self, db_session
    ):
        suggestion = svc.suggest_commencement(
            db_session, intake_start_date=INTAKE_START, activated_at=ACTIVATED_AT
        )
        assert suggestion.suggested_date == SUGGESTED
        assert suggestion.basis == "ACTIVATION"
        assert suggestion.activated_on == SUGGESTED

    def test_activation_before_the_intake_start_uses_the_intake_start(
        self, db_session
    ):
        suggestion = svc.suggest_commencement(
            db_session,
            intake_start_date=INTAKE_START,
            activated_at=datetime(2033, 1, 20, 8, 0),
        )
        assert suggestion.suggested_date == INTAKE_START
        assert suggestion.basis == "INTAKE_START"

    def test_a_sunday_suggestion_moves_to_the_next_working_day(
        self, client, db_session
    ):
        intake = _mk_intake(db_session, "sunday")
        offering = _mk_offering(db_session, intake, "sunday")
        student = _mk_student(db_session, "sunday")
        episode = _mk_episode(
            db_session,
            student,
            intake,
            offering,
            # 2033-02-12 is a Saturday; the following Monday is 2033-02-14.
            activated_at=datetime(2033, 2, 12, 9, 0),
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        body = client.get(
            f"{API}/students/{student.id}/admissions/{episode.id}/commencement"
        ).json()
        assert body["suggested_date"] == "2033-02-14"
        assert body["suggestion_basis"] == "ACTIVATION"

    def test_declared_holiday_and_closure_are_skipped(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "holiday-skip")
        db_session.commit()

        _login(client, ADMIN)
        for day, day_type in ((SUGGESTED, "HOLIDAY"), (SUGGESTED + timedelta(days=1), "CLOSURE")):
            response = client.post(
                "/api/v1/academics/calendar/days",
                json={
                    "calendar_date": day.isoformat(),
                    "day_type": day_type,
                    "title": f"Declared {day_type.lower()}",
                    "reason": "Institutionally declared for this test.",
                },
            )
            assert response.status_code == 201, response.text

        _login(client, MANAGEMENT)
        body = client.get(
            f"{API}/students/{student.id}/admissions/{episode.id}/commencement"
        ).json()
        assert body["suggested_date"] == "2033-02-14"

    def test_an_exceptional_working_day_remains_a_valid_suggestion(
        self, client, db_session
    ):
        intake = _mk_intake(db_session, "exceptional-suggest")
        offering = _mk_offering(db_session, intake, "exceptional-suggest")
        student = _mk_student(db_session, "exceptional-suggest")
        episode = _mk_episode(
            db_session,
            student,
            intake,
            offering,
            activated_at=datetime(2033, 2, 12, 9, 0),
        )
        db_session.commit()

        _login(client, ADMIN)
        response = client.post(
            "/api/v1/academics/calendar/days",
            json={
                "calendar_date": "2033-02-12",
                "day_type": "EXCEPTIONAL_WORKING",
                "title": "Make-up Saturday",
                "reason": "Institutionally declared make-up day.",
            },
        )
        assert response.status_code == 201, response.text

        _login(client, MANAGEMENT)
        body = client.get(
            f"{API}/students/{student.id}/admissions/{episode.id}/commencement"
        ).json()
        assert body["suggested_date"] == "2033-02-12"

    def test_a_non_working_commencement_date_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "weekend-approve")
        db_session.commit()

        _login(client, MANAGEMENT)
        # 2033-02-12 is a Saturday and later than the suggestion, so this is a
        # well-formed late join apart from the calendar rule.
        response = _approve(
            client,
            student,
            episode,
            commencement_date="2033-02-12",
            commencement_type="LATE_JOIN",
            reason=LATE_REASON,
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_NON_WORKING_DAY"

        db_session.expire_all()
        assert db_session.query(AttendanceCommencement).count() == 0

    def test_an_exceptional_working_day_can_be_approved(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "exceptional-approve")
        db_session.commit()

        _login(client, ADMIN)
        response = client.post(
            "/api/v1/academics/calendar/days",
            json={
                "calendar_date": "2033-02-12",
                "day_type": "EXCEPTIONAL_WORKING",
                "title": "Make-up Saturday",
                "reason": "Institutionally declared make-up day.",
            },
        )
        assert response.status_code == 201, response.text

        _login(client, MANAGEMENT)
        response = _approve(
            client,
            student,
            episode,
            commencement_date="2033-02-12",
            commencement_type="LATE_JOIN",
            reason=LATE_REASON,
        )
        assert response.status_code == 201, response.text
        assert response.json()["commencement_date"] == "2033-02-12"

    def test_summary_reports_the_suggestion_without_creating_a_record(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "suggest")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = client.get(
            f"{API}/students/{student.id}/admissions/{episode.id}/commencement"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["suggested_date"] == SUGGESTED.isoformat()
        assert body["suggestion_basis"] == "ACTIVATION"
        assert body["current"] is None
        assert body["history"] == []
        assert body["admission_status"] == "ACTIVE"

        db_session.expire_all()
        assert db_session.query(AttendanceCommencement).count() == 0

    def test_a_stale_confirmation_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "stale")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _approve(
            client,
            student,
            episode,
            confirmed_suggested_date=(SUGGESTED + timedelta(days=3)).isoformat(),
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_SUGGESTION_STALE"

        db_session.expire_all()
        assert db_session.query(AttendanceCommencement).count() == 0

    def test_confirmed_suggestion_creates_a_scheduled_commencement(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "scheduled")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _approve(client, student, episode)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["commencement_date"] == SUGGESTED.isoformat()
        assert body["commencement_type"] == "SCHEDULED"
        assert body["suggested_date"] == SUGGESTED.isoformat()
        assert body["superseded_at"] is None
        assert body["approved_by_name"] == "Management User"


# ── B. Late joins and manual commencements ─────────────────────────────────


class TestLateJoinAndManual:
    def test_late_join_later_than_the_suggestion_is_accepted(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "late")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _approve(
            client,
            student,
            episode,
            commencement_date=(SUGGESTED + timedelta(days=14)).isoformat(),
            commencement_type="LATE_JOIN",
            reason=LATE_REASON,
        )
        assert response.status_code == 201, response.text
        assert response.json()["commencement_type"] == "LATE_JOIN"
        assert response.json()["reason"] == LATE_REASON

    def test_late_join_on_the_suggested_date_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "late-same")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _approve(
            client,
            student,
            episode,
            commencement_type="LATE_JOIN",
            reason=LATE_REASON,
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_TYPE_MISMATCH"

    def test_a_late_join_still_requires_an_explanation(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "late-reason")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _approve(
            client,
            student,
            episode,
            commencement_date=(SUGGESTED + timedelta(days=7)).isoformat(),
            commencement_type="LATE_JOIN",
            reason="late",
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_REASON_REQUIRED"

    def test_manual_commencement_must_differ_from_the_suggestion(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "manual-same")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _approve(
            client, student, episode, commencement_type="MANUAL", reason=MANUAL_REASON
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_TYPE_MISMATCH"

    def test_manual_commencement_records_the_chosen_date(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "manual")
        db_session.commit()

        # 2033-02-14 is the Monday after the suggestion, so it is a working day.
        chosen = SUGGESTED + timedelta(days=4)
        _login(client, MANAGEMENT)
        response = _approve(
            client,
            student,
            episode,
            commencement_date=chosen.isoformat(),
            commencement_type="MANUAL",
            reason=MANUAL_REASON,
        )
        assert response.status_code == 201, response.text
        assert response.json()["commencement_type"] == "MANUAL"
        assert response.json()["commencement_date"] == chosen.isoformat()

    def test_a_scheduled_commencement_cannot_move_the_date(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "sched-move")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _approve(
            client,
            student,
            episode,
            commencement_date=(SUGGESTED + timedelta(days=1)).isoformat(),
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_TYPE_MISMATCH"


# ── C. Date validation ─────────────────────────────────────────────────────


class TestDateValidation:
    def test_a_date_before_the_intake_start_is_refused(self, client, db_session):
        intake = _mk_intake(db_session, "before-intake")
        offering = _mk_offering(db_session, intake, "before-intake")
        student = _mk_student(db_session, "before-intake")
        episode = _mk_episode(db_session, student, intake, offering)
        db_session.commit()

        _login(client, ADMIN)
        response = _approve(
            client,
            student,
            episode,
            commencement_date=(INTAKE_START - timedelta(days=1)).isoformat(),
            commencement_type="MANUAL",
            reason=MANUAL_REASON,
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_DATE_INVALID"

    def test_a_date_before_activation_is_refused(self, client, db_session):
        intake = _mk_intake(db_session, "before-activation")
        offering = _mk_offering(db_session, intake, "before-activation")
        student = _mk_student(db_session, "before-activation")
        episode = _mk_episode(db_session, student, intake, offering)
        db_session.commit()

        _login(client, ADMIN)
        response = _approve(
            client,
            student,
            episode,
            commencement_date=(SUGGESTED - timedelta(days=1)).isoformat(),
            commencement_type="MANUAL",
            reason=MANUAL_REASON,
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_BEFORE_ACTIVATION"


# ── D. Episode state and identity ──────────────────────────────────────────


class TestEpisodeState:
    @pytest.mark.parametrize(
        ("status", "activated_at"),
        [("PENDING", None), ("ADMITTED", None)],
    )
    def test_unactivated_episodes_cannot_commence(
        self, client, db_session, status, activated_at
    ):
        intake = _mk_intake(db_session, f"state-{status.lower()}")
        offering = _mk_offering(db_session, intake, f"state-{status.lower()}")
        student = _mk_student(db_session, f"state-{status.lower()}")
        episode = _mk_episode(
            db_session, student, intake, offering, status=status, activated_at=activated_at
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _approve(
            client,
            student,
            episode,
            confirmed_suggested_date=INTAKE_START.isoformat(),
            commencement_date=INTAKE_START.isoformat(),
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_ADMISSION_NOT_ACTIVE"

        db_session.expire_all()
        assert db_session.query(AttendanceCommencement).count() == 0

    def test_a_completed_episode_cannot_be_commenced(self, client, db_session):
        intake = _mk_intake(db_session, "completed")
        offering = _mk_offering(db_session, intake, "completed")
        student = _mk_student(db_session, "completed")
        episode = _mk_episode(
            db_session,
            student,
            intake,
            offering,
            status="COMPLETED",
            ended_at=datetime(2033, 7, 1, 12, 0),
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _approve(client, student, episode)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_ADMISSION_NOT_ACTIVE"

    def test_an_episode_of_another_student_is_not_found(self, client, db_session):
        first_student, _first_episode, _intake, _offering = _scenario(db_session, "owner-a")
        second_student, second_episode, _i2, _o2 = _scenario(db_session, "owner-b")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = client.post(
            f"{API}/students/{second_student.id}/admissions/{second_episode.id}"
            "/commencement",
            json=_payload(),
        )
        assert response.status_code == 201, response.text

        # The first student's id with the second student's episode is a 404, not
        # a 403: it must not confirm that the episode exists.
        response = client.get(
            f"{API}/students/{first_student.id}/admissions/{second_episode.id}"
            "/commencement"
        )
        assert response.status_code == 404, response.text
        assert (
            response.json()["error"]["code"] == "COMMENCEMENT_ADMISSION_NOT_FOUND"
        )

    def test_one_current_commencement_per_episode(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "duplicate")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _approve(client, student, episode).status_code == 201

        duplicate = _approve(client, student, episode)
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"]["code"] == "COMMENCEMENT_ALREADY_EXISTS"

        db_session.expire_all()
        rows = (
            db_session.query(AttendanceCommencement)
            .filter(AttendanceCommencement.admission_id == episode.id)
            .all()
        )
        assert len(rows) == 1


# ── E. Authorization ───────────────────────────────────────────────────────


class TestCommencementAuthorization:
    def test_management_holds_the_permission_and_teachers_students_do_not(
        self, db_session
    ):
        def permissions(role_name: str) -> set[str]:
            role = db_session.query(Role).filter(Role.name == role_name).first()
            assert role is not None
            return {permission.codename for permission in role.permissions}

        assert "attendance.manage_commencement" in permissions("MANAGEMENT")
        assert "attendance.manage_commencement" in permissions("ADMIN")
        assert "attendance.manage_commencement" not in permissions("TEACHER")
        assert "attendance.manage_commencement" not in permissions("STUDENT")

    @pytest.mark.parametrize("email", [TEACHER, STUDENT_ACCOUNT])
    def test_staff_outside_the_workflow_cannot_approve(
        self, client, db_session, email
    ):
        student, episode, _intake, _offering = _scenario(db_session, f"deny-{email[:3]}")
        db_session.commit()

        _login(client, email)
        assert client.get(f"{API}/commencements").status_code == 403
        assert (
            client.get(
                f"{API}/students/{student.id}/admissions/{episode.id}/commencement"
            ).status_code
            == 403
        )
        assert _approve(client, student, episode).status_code == 403
        assert _correct(client, student, episode).status_code == 403

    def test_anonymous_is_unauthenticated(self, client):
        assert client.get(f"{API}/commencements").status_code == 401

    def test_admin_and_management_can_both_approve(self, client, db_session):
        management_student, management_episode, _i, _o = _scenario(db_session, "mgmt")
        admin_student, admin_episode, _i2, _o2 = _scenario(db_session, "adm")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _approve(client, management_student, management_episode).status_code == 201

        _login(client, ADMIN)
        assert _approve(client, admin_student, admin_episode).status_code == 201


# ── F. Correction and supersession ─────────────────────────────────────────


class TestCorrection:
    def test_correction_supersedes_and_preserves_the_previous_record(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "correct")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _approve(client, student, episode)
        assert created.status_code == 201, created.text
        original_id = created.json()["id"]

        corrected_date = SUGGESTED + timedelta(days=4)
        corrected = _correct(
            client,
            student,
            episode,
            commencement_date=corrected_date.isoformat(),
            commencement_type="LATE_JOIN",
            reason=CORRECTION_REASON,
        )
        assert corrected.status_code == 201, corrected.text
        assert corrected.json()["supersedes_id"] == original_id
        assert corrected.json()["commencement_date"] == corrected_date.isoformat()

        summary = client.get(
            f"{API}/students/{student.id}/admissions/{episode.id}/commencement"
        )
        assert summary.status_code == 200, summary.text
        body = summary.json()
        assert body["current"]["id"] == corrected.json()["id"]
        assert len(body["history"]) == 2
        superseded = next(row for row in body["history"] if row["id"] == original_id)
        assert superseded["superseded_at"] is not None
        assert superseded["commencement_date"] == SUGGESTED.isoformat()

        db_session.expire_all()
        stored = (
            db_session.query(AttendanceCommencement)
            .filter(AttendanceCommencement.id == uuid.UUID(original_id))
            .first()
        )
        assert stored is not None
        assert stored.commencement_date == SUGGESTED
        assert stored.superseded_at is not None

        entries = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.entity_type == "attendance_commencement",
                AuditLog.entity_id.in_(
                    [uuid.UUID(original_id), uuid.UUID(corrected.json()["id"])]
                ),
            )
            .order_by(AuditLog.created_at)
            .all()
        )
        assert [entry.action for entry in entries] == [
            "academic.commencement.approved",
            "academic.commencement.corrected",
        ]
        correction = entries[1]
        assert correction.context["previous_commencement_date"] == SUGGESTED.isoformat()
        assert correction.context["commencement_date"] == corrected_date.isoformat()
        assert correction.context["previous_commencement_id"] == original_id
        assert correction.context["reason"] == CORRECTION_REASON

    def test_an_unchanged_correction_is_refused(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "unchanged")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _approve(client, student, episode).status_code == 201

        response = _correct(client, student, episode)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_UNCHANGED"

        db_session.expire_all()
        assert (
            db_session.query(AttendanceCommencement)
            .filter(AttendanceCommencement.admission_id == episode.id)
            .count()
            == 1
        )

    def test_a_correction_requires_a_current_commencement(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "no-current")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _correct(client, student, episode)
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "COMMENCEMENT_NOT_FOUND"

    def test_the_previous_record_stays_in_the_audit_trail(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "audit-chain")
        db_session.commit()

        _login(client, ADMIN)
        assert _approve(client, student, episode).status_code == 201
        assert (
            _correct(
                client,
                student,
                episode,
                commencement_date=(SUGGESTED + timedelta(days=4)).isoformat(),
                commencement_type="LATE_JOIN",
                reason=LATE_REASON,
            ).status_code
            == 201
        )

        summary = client.get(
            f"{API}/students/{student.id}/admissions/{episode.id}/commencement"
        ).json()
        assert len(summary["history"]) == 2
        assert {row["approved_by_name"] for row in summary["history"]} == {"Admin User"}


# ── G. Episode independence ────────────────────────────────────────────────


class TestEpisodeIndependence:
    def test_a_programme_change_does_not_reset_commencement(self, client, db_session):
        student, episode, _intake, offering = _scenario(db_session, "programme")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _approve(client, student, episode)
        assert created.status_code == 201, created.text

        # An approved programme change updates the episode's current programme.
        major = Major(
            code=f"P2-MJ-{uuid.uuid4().hex[:6]}", name="Phase 2 major"
        )
        db_session.add(major)
        db_session.flush()
        new_program = Program(
            major_id=major.id,
            code=f"P2-PROG-{uuid.uuid4().hex[:6]}",
            name="Phase 2 programme",
        )
        db_session.add(new_program)
        db_session.flush()
        episode.current_program_id = new_program.id
        episode.current_program_changed_at = datetime(2033, 3, 1, 10, 0)
        db_session.commit()

        summary = client.get(
            f"{API}/students/{student.id}/admissions/{episode.id}/commencement"
        ).json()
        assert summary["current"]["id"] == created.json()["id"]
        assert summary["current"]["commencement_date"] == SUGGESTED.isoformat()
        assert len(summary["history"]) == 1

    def test_a_new_episode_gets_its_own_commencement(self, client, db_session):
        student, first_episode, _intake, _offering = _scenario(db_session, "episode-one")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _approve(client, student, first_episode).status_code == 201

        first_episode.status = "COMPLETED"
        first_episode.ended_at = datetime(2033, 6, 30, 12, 0)
        db_session.flush()

        later_intake = _mk_intake(
            db_session,
            "episode-two",
            start=date(2034, 2, 1),
            end=date(2034, 6, 30),
        )
        later_offering = _mk_offering(db_session, later_intake, "episode-two")
        second_episode = _mk_episode(
            db_session,
            student,
            later_intake,
            later_offering,
            activated_at=datetime(2034, 2, 5, 9, 0),
        )
        db_session.commit()

        # Activation is a Sunday, so the suggestion is the following Monday.
        second = _approve(
            client,
            student,
            second_episode,
            commencement_date=date(2034, 2, 6).isoformat(),
            confirmed_suggested_date=date(2034, 2, 6).isoformat(),
        )
        assert second.status_code == 201, second.text

        second_summary = client.get(
            f"{API}/students/{student.id}/admissions/{second_episode.id}/commencement"
        ).json()
        assert len(second_summary["history"]) == 1
        assert second_summary["current"]["commencement_date"] == "2034-02-06"

        first_summary = client.get(
            f"{API}/students/{student.id}/admissions/{first_episode.id}/commencement"
        ).json()
        assert first_summary["current"]["commencement_date"] == SUGGESTED.isoformat()

        db_session.expire_all()
        rows = (
            db_session.query(AttendanceCommencement)
            .filter(AttendanceCommencement.student_id == student.id)
            .all()
        )
        assert {row.admission_id for row in rows} == {
            first_episode.id,
            second_episode.id,
        }

    def test_a_calendar_exception_does_not_move_a_commencement(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "calendar")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _approve(client, student, episode).status_code == 201

        # A closure declared for the same date must not rewrite an approved
        # commencement; the calendar decides which days count, not when a
        # student started.
        closure = client.post(
            "/api/v1/academics/calendar/days",
            json={
                "calendar_date": SUGGESTED.isoformat(),
                "day_type": "CLOSURE",
                "title": "Unexpected closure",
                "reason": "Campus closed following a utility failure.",
            },
        )
        assert closure.status_code == 201, closure.text

        db_session.expire_all()
        rows = (
            db_session.query(AttendanceCommencement)
            .filter(AttendanceCommencement.admission_id == episode.id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].commencement_date == SUGGESTED
        assert rows[0].superseded_at is None


# ── H. Lifecycle integration and listing ───────────────────────────────────


class TestLifecycleIntegration:
    def test_activation_does_not_create_a_commencement(self, client, db_session):
        _student, _episode, _intake, _offering = _scenario(db_session, "no-auto")
        db_session.commit()

        db_session.expire_all()
        assert db_session.query(AttendanceCommencement).count() == 0

    def test_the_queue_lists_active_episodes_without_a_commencement(
        self, client, db_session
    ):
        missing_student, _missing_episode, _i, _o = _scenario(db_session, "queue-missing")
        done_student, done_episode, _i2, _o2 = _scenario(db_session, "queue-done")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _approve(client, done_student, done_episode).status_code == 201

        missing = client.get(f"{API}/commencements", params={"status": "MISSING"})
        assert missing.status_code == 200, missing.text
        numbers = {item["student_number"] for item in missing.json()["items"]}
        assert missing_student.student_id in numbers
        assert done_student.student_id not in numbers

        recorded = client.get(f"{API}/commencements", params={"status": "RECORDED"})
        assert recorded.status_code == 200, recorded.text
        recorded_numbers = {item["student_number"] for item in recorded.json()["items"]}
        assert done_student.student_id in recorded_numbers
        assert missing_student.student_id not in recorded_numbers

    def test_the_queue_can_be_searched_by_student_number(self, client, db_session):
        student, _episode, _i, _o = _scenario(db_session, "queue-search")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = client.get(
            f"{API}/commencements",
            params={"status": "ALL", "search": student.student_id},
        )
        assert response.status_code == 200, response.text
        assert [item["student_number"] for item in response.json()["items"]] == [
            student.student_id
        ]

    def test_an_invalid_queue_status_is_refused(self, client, db_session):
        _scenario(db_session, "queue-invalid")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = client.get(f"{API}/commencements", params={"status": "PENDING"})
        assert response.status_code == 422, response.text


# ── I. Transactions ────────────────────────────────────────────────────────


class TestCommencementTransactions:
    def test_an_audit_failure_rolls_back_the_approval(
        self, client, db_session, monkeypatch
    ):
        student, episode, _intake, _offering = _scenario(db_session, "rollback-approve")
        db_session.commit()

        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        monkeypatch.setattr("app.services.commencement.record_audit", _explode)

        _login(client, MANAGEMENT)
        with pytest.raises(RuntimeError):
            _approve(client, student, episode)

        db_session.expire_all()
        assert (
            db_session.query(AttendanceCommencement)
            .filter(AttendanceCommencement.admission_id == episode.id)
            .count()
            == 0
        )

    def test_an_audit_failure_rolls_back_a_correction(
        self, client, db_session, monkeypatch
    ):
        student, episode, _intake, _offering = _scenario(db_session, "rollback-correct")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _approve(client, student, episode)
        assert created.status_code == 201, created.text
        original_id = uuid.UUID(created.json()["id"])

        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        monkeypatch.setattr("app.services.commencement.record_audit", _explode)

        with pytest.raises(RuntimeError):
            _correct(
                client,
                student,
                episode,
                commencement_date=(SUGGESTED + timedelta(days=1)).isoformat(),
                commencement_type="LATE_JOIN",
                reason=LATE_REASON,
            )

        db_session.expire_all()
        rows = (
            db_session.query(AttendanceCommencement)
            .filter(AttendanceCommencement.admission_id == episode.id)
            .all()
        )
        # Neither half survives: no replacement row, and the original was not
        # marked superseded by a correction that never committed.
        assert len(rows) == 1
        assert rows[0].id == original_id
        assert rows[0].superseded_at is None
