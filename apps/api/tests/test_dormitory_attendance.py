"""Dormitory attendance: a separate domain from academic attendance.

These tests pin the institutional rules.

* Physical presence is handled outside the system, so only absences are stored.
  There is no ``PRESENT`` row and no daily sheet.
* Every calendar day counts. A weekend, a declared university holiday or a
  vacation is not an exception here — the academic calendar is never consulted.
* Eligibility comes from the housing assignment's effective dates, not from the
  student's current status and not from their latest assignment. A former
  resident keeps their history; a returning resident starts a new set.
* One current absence per student/stay/date; a correction supersedes and keeps
  the previous points, date and reason.
* Points are administrative: entered per absence, accumulated for display, and
  never turned into a fine, a threshold or a sanction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.auth.service import hash_password
from app.models.audit import AuditLog
from app.models.calendar import UniversityCalendarDay
from app.models.dormitory_absence import DormitoryAbsence
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    Room,
)
from app.models.identity import Role, Student, User

API = "/api/v1/dormitory"
LOGIN = "/api/v1/auth/login"

ADMIN = "admin@school.portal"
MANAGEMENT = "management@school.portal"
TEACHER = "teacher@school.portal"

REASON = "Resident did not return to the dormitory before curfew."
CORRECTION_REASON = "The duty log shows the absence belonged to the previous night."

TODAY = date.today()


def _day(offset: int) -> date:
    return TODAY + timedelta(days=offset)


def _stamp(day: date, hour: int = 8) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)


def _last_saturday() -> date:
    """The most recent Saturday strictly before today."""
    return TODAY - timedelta(days=((TODAY.weekday() - 5) % 7) or 7)


# ── Fixtures ───────────────────────────────────────────────────────────────


def _login(client, email: str) -> None:
    response = client.post(LOGIN, json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text


def _mk_student(db, tag: str, *, with_user: bool = False) -> Student:
    user = User(
        email=f"dorm-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"dorm-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Dorm {tag}",
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
        student_id=f"DORM-{tag.upper()}-{uuid.uuid4().hex[:6]}",
        first_name="Dorm",
        last_name=tag,
        status="ACTIVE",
    )
    db.add(student)
    db.flush()
    return student


def _mk_bed(db, tag: str) -> Bed:
    suffix = uuid.uuid4().hex[:8]
    building = Building(name=f"Dorm {tag} {suffix}")
    db.add(building)
    db.flush()
    floor = Floor(building_id=building.id, floor_number=1)
    db.add(floor)
    db.flush()
    room = Room(floor_id=floor.id, room_number="101", capacity=1)
    db.add(room)
    db.flush()
    bed = Bed(room_id=room.id, bed_number=1)
    db.add(bed)
    db.flush()
    return bed


def _assign(
    db,
    student: Student,
    *,
    start: date,
    end: date | None = None,
    status: str = "ACTIVE",
) -> HousingAssignment:
    assignment = HousingAssignment(
        student_id=student.user_id,
        bed_id=_mk_bed(db, student.student_id).id,
        start_date=_stamp(start),
        end_date=_stamp(end) if end else None,
        status=status,
    )
    db.add(assignment)
    db.flush()
    return assignment


def _resident(
    db,
    tag: str,
    *,
    start: date | None = None,
    end: date | None = None,
    status: str = "ACTIVE",
):
    student = _mk_student(db, tag)
    assignment = _assign(
        db, student, start=start or _day(-30), end=end, status=status
    )
    return student, assignment


def _record(
    client,
    student: Student,
    day: date,
    *,
    points: float = 2.0,
    reason: str = REASON,
    assignment_id: str | None = None,
):
    body: dict = {
        "absence_date": day.isoformat(),
        "points": points,
        "reason": reason,
    }
    if assignment_id is not None:
        body["housing_assignment_id"] = assignment_id
    return client.post(f"{API}/students/{student.id}/absences", json=body)


def _correct(
    client,
    student: Student,
    absence_id: str,
    day: date,
    *,
    points: float,
    reason: str = CORRECTION_REASON,
):
    return client.post(
        f"{API}/students/{student.id}/absences/{absence_id}/corrections",
        json={
            "absence_date": day.isoformat(),
            "points": points,
            "reason": reason,
        },
    )


def _declare(db, day: date, day_type: str = "HOLIDAY") -> None:
    """Declare an academic calendar exception, directly in the calendar table.

    The dormitory module must ignore it; writing the row here keeps the test
    focused on that claim rather than on the calendar's own API contract.
    """
    actor = db.query(User).filter(User.email == ADMIN).first()
    assert actor is not None
    db.add(
        UniversityCalendarDay(
            calendar_date=day,
            day_type=day_type,
            title="University holiday",
            reason="Declared by the registrar for the whole university.",
            created_by_id=actor.id,
        )
    )
    db.flush()


# ── A. Every calendar day counts ───────────────────────────────────────────


class TestCalendarIndependence:
    def test_a_weekend_absence_is_recorded(self, client, db_session):
        saturday = _last_saturday()
        student, _assignment = _resident(db_session, "weekend", start=saturday - timedelta(days=14))
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, saturday)
        assert response.status_code == 201, response.text
        assert response.json()["absence"]["absence_date"] == saturday.isoformat()

    def test_a_university_holiday_does_not_block_recording(self, client, db_session):
        holiday = _last_saturday() - timedelta(days=1)
        student, _assignment = _resident(db_session, "holiday", start=holiday - timedelta(days=14))
        _declare(db_session, holiday, "HOLIDAY")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, holiday)
        assert response.status_code == 201, response.text

    def test_a_university_closure_does_not_block_recording(self, client, db_session):
        closure = _last_saturday() - timedelta(days=2)
        student, _assignment = _resident(db_session, "closure", start=closure - timedelta(days=14))
        _declare(db_session, closure, "CLOSURE")
        db_session.commit()

        _login(client, ADMIN)
        assert _record(client, student, closure).status_code == 201

    def test_an_academic_admission_is_not_required(self, client, db_session):
        """Dormitory eligibility is residential, not academic."""
        student, _assignment = _resident(db_session, "no-admission")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, _day(-3)).status_code == 201

    def test_recording_stores_one_absence_and_no_presence_row(self, client, db_session):
        student, _assignment = _resident(db_session, "no-presence")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, _day(-2)).status_code == 201

        db_session.expire_all()
        assert (
            db_session.query(DormitoryAbsence)
            .filter(DormitoryAbsence.student_id == student.id)
            .count()
            == 1
        )


# ── B. Eligibility from the housing assignment ─────────────────────────────


class TestEligibility:
    def test_a_student_without_housing_cannot_record(self, client, db_session):
        student = _mk_student(db_session, "no-room")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, _day(-2))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "DORMITORY_NO_HOUSING_ASSIGNMENT"

        detail = client.get(f"{API}/students/{student.id}").json()
        assert detail["has_assignment"] is False
        assert detail["eligible_today"] is False
        assert detail["ineligible_reason"] == "NO_HOUSING_ASSIGNMENT"
        assert detail["assignments"] == []

    def test_a_date_after_the_assignment_ended_is_refused(self, client, db_session):
        student, _assignment = _resident(
            db_session, "ended", start=_day(-30), end=_day(-20)
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, _day(-10))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "DORMITORY_DATE_OUTSIDE_ASSIGNMENT"

    def test_a_date_before_the_assignment_started_is_refused(self, client, db_session):
        student, _assignment = _resident(db_session, "future-start", start=_day(-1))
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, _day(-5))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "DORMITORY_DATE_OUTSIDE_ASSIGNMENT"

    def test_a_future_date_is_refused(self, client, db_session):
        student, _assignment = _resident(db_session, "future")
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, _day(1))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "DORMITORY_ABSENCE_IN_FUTURE"

    def test_history_survives_after_moving_out(self, client, db_session):
        student, assignment = _resident(db_session, "moved-out")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-5), points=3)
        assert created.status_code == 201, created.text

        # The student moves to an outside apartment: the stay ends.
        assignment.status = "ENDED"
        assignment.end_date = _stamp(_day(-2))
        db_session.flush()
        db_session.commit()

        detail = client.get(f"{API}/students/{student.id}").json()
        assert detail["is_current_resident"] is False
        assert detail["ineligible_reason"] == "ASSIGNMENT_ENDED"
        assert len(detail["absences"]) == 1
        assert detail["absences"][0]["points"] == 3.0
        assert detail["points_total"] == 3.0

        # Recording after the stay ended is refused, but nothing was deleted.
        assert _record(client, student, _day(-1)).status_code == 422

    def test_returning_to_housing_starts_a_new_period(self, client, db_session):
        student, first = _resident(
            db_session, "returns", start=_day(-60), end=_day(-40), status="ENDED"
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, _day(-50), points=2).status_code == 201

        second = _assign(db_session, student, start=_day(-10))
        db_session.commit()

        assert _record(client, student, _day(-5), points=4).status_code == 201

        detail = client.get(f"{API}/students/{student.id}").json()
        assert detail["is_current_resident"] is True
        assert len(detail["assignments"]) == 2
        assert len(detail["absences"]) == 2
        assert detail["points_total"] == 6.0

        by_assignment = {
            row["housing_assignment_id"]: row["points"] for row in detail["absences"]
        }
        assert by_assignment[str(first.id)] == 2.0
        assert by_assignment[str(second.id)] == 4.0

    def test_multiple_assignments_keep_an_ordered_history(self, client, db_session):
        student, first = _resident(
            db_session, "multiple", start=_day(-60), end=_day(-30), status="ENDED"
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, _day(-40)).status_code == 201

        _assign(db_session, student, start=_day(-20))
        db_session.commit()
        assert _record(client, student, _day(-10)).status_code == 201

        detail = client.get(f"{API}/students/{student.id}").json()
        dates = [row["absence_date"] for row in detail["absences"]]
        assert dates == sorted(dates, reverse=True)
        assert [row["start_date"] for row in detail["assignments"]] == sorted(
            [row["start_date"] for row in detail["assignments"]], reverse=True
        )

    def test_a_date_in_the_gap_between_stays_is_refused(self, client, db_session):
        student, _first = _resident(
            db_session, "gap", start=_day(-60), end=_day(-40), status="ENDED"
        )
        _assign(db_session, student, start=_day(-10))
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, _day(-25))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "DORMITORY_DATE_OUTSIDE_ASSIGNMENT"

    def test_a_cancelled_assignment_cannot_carry_an_absence(self, client, db_session):
        student, assignment = _resident(db_session, "cancelled")
        assignment.status = "CANCELLED"
        db_session.flush()
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _record(client, student, _day(-2))
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "DORMITORY_NO_HOUSING_ASSIGNMENT"


# ── C. Duplicates and points ───────────────────────────────────────────────


class TestPointsAndDuplicates:
    def test_a_duplicate_current_absence_is_refused(self, client, db_session):
        student, _assignment = _resident(db_session, "duplicate")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, _day(-3)).status_code == 201

        duplicate = _record(client, student, _day(-3))
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"]["code"] == "DORMITORY_ABSENCE_ALREADY_RECORDED"

        db_session.expire_all()
        assert db_session.query(DormitoryAbsence).count() == 1

    def test_points_accumulate_across_absences(self, client, db_session):
        student, _assignment = _resident(db_session, "accumulate")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, _day(-4), points=1.5).status_code == 201
        second = _record(client, student, _day(-3), points=2.5)
        assert second.status_code == 201, second.text
        assert second.json()["absence_count"] == 2
        assert second.json()["points_total"] == 4.0

        detail = client.get(f"{API}/students/{student.id}").json()
        assert detail["points_total"] == 4.0

    def test_a_correction_preserves_the_previous_points(self, client, db_session):
        student, _assignment = _resident(db_session, "correct-points")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-3), points=2)
        original_id = created.json()["absence"]["id"]

        corrected = _correct(client, student, original_id, _day(-3), points=5)
        assert corrected.status_code == 201, corrected.text
        body = corrected.json()
        assert body["absence"]["supersedes_id"] == original_id
        assert body["absence"]["points"] == 5.0
        assert body["absence_count"] == 1
        assert body["points_total"] == 5.0

        detail = client.get(f"{API}/students/{student.id}").json()
        assert len(detail["absences"]) == 2
        superseded = next(r for r in detail["absences"] if r["id"] == original_id)
        assert superseded["superseded_at"] is not None
        assert superseded["points"] == 2.0
        assert superseded["reason"] == REASON

    def test_a_correction_can_move_the_date(self, client, db_session):
        student, _assignment = _resident(db_session, "correct-date")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-4))
        absence_id = created.json()["absence"]["id"]

        corrected = _correct(client, student, absence_id, _day(-3), points=2)
        assert corrected.status_code == 201, corrected.text
        assert corrected.json()["absence"]["absence_date"] == _day(-3).isoformat()

    def test_a_correction_requires_a_substantive_reason(self, client, db_session):
        student, _assignment = _resident(db_session, "correct-reason")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-3))
        absence_id = created.json()["absence"]["id"]

        response = _correct(
            client, student, absence_id, _day(-3), points=4, reason="typo"
        )
        assert response.status_code == 422, response.text
        assert (
            response.json()["error"]["code"]
            == "DORMITORY_CORRECTION_REASON_REQUIRED"
        )

    def test_an_unchanged_correction_is_refused(self, client, db_session):
        student, _assignment = _resident(db_session, "unchanged")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-3), points=2)
        absence_id = created.json()["absence"]["id"]

        response = _correct(
            client,
            student,
            absence_id,
            _day(-3),
            points=2,
            reason=REASON,
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "DORMITORY_ABSENCE_UNCHANGED"

    def test_a_correction_onto_another_current_absence_is_refused(
        self, client, db_session
    ):
        student, _assignment = _resident(db_session, "correct-clash")
        db_session.commit()

        _login(client, MANAGEMENT)
        first = _record(client, student, _day(-4))
        assert _record(client, student, _day(-3)).status_code == 201

        response = _correct(
            client, student, first.json()["absence"]["id"], _day(-3), points=2
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "DORMITORY_ABSENCE_ALREADY_RECORDED"

    def test_a_negative_point_value_is_refused(self, client, db_session):
        student, _assignment = _resident(db_session, "negative")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, _day(-3), points=-1).status_code == 422


# ── D. Audit and transaction integrity ─────────────────────────────────────


class TestAudit:
    def test_recording_and_correction_are_audited(self, client, db_session):
        student, _assignment = _resident(db_session, "audit")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-3), points=2)
        absence_id = created.json()["absence"]["id"]
        assert _correct(client, student, absence_id, _day(-3), points=5).status_code == 201

        db_session.expire_all()
        entries = (
            db_session.query(AuditLog)
            .filter(AuditLog.entity_type == "dormitory_absence")
            .order_by(AuditLog.created_at)
            .all()
        )
        assert [entry.action for entry in entries] == [
            "dormitory.absence.recorded",
            "dormitory.absence.corrected",
        ]
        correction = entries[-1]
        assert correction.context["previous_points"] == 2.0
        assert correction.context["points"] == 5.0
        assert correction.context["previous_reason"] == REASON
        assert correction.actor_id is not None

    def test_an_audit_failure_rolls_back_the_record(
        self, client, db_session, monkeypatch
    ):
        student, _assignment = _resident(db_session, "rollback-record")
        db_session.commit()

        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        monkeypatch.setattr(
            "app.services.dormitory_attendance.record_audit", _explode
        )

        _login(client, MANAGEMENT)
        with pytest.raises(RuntimeError):
            _record(client, student, _day(-3))

        db_session.expire_all()
        assert (
            db_session.query(DormitoryAbsence)
            .filter(DormitoryAbsence.student_id == student.id)
            .count()
            == 0
        )


# ── E. Authorization ───────────────────────────────────────────────────────


class TestAuthorization:
    def test_management_can_record(self, client, db_session):
        student, _assignment = _resident(db_session, "mgmt")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, _day(-2)).status_code == 201

    def test_admin_can_record(self, client, db_session):
        student, _assignment = _resident(db_session, "admin")
        db_session.commit()

        _login(client, ADMIN)
        assert _record(client, student, _day(-2)).status_code == 201

    def test_a_teacher_has_no_dormitory_access(self, client, db_session):
        student, _assignment = _resident(db_session, "teacher")
        db_session.commit()

        _login(client, TEACHER)
        assert client.get(f"{API}/students").status_code == 403
        assert client.get(f"{API}/students/{student.id}").status_code == 403
        assert _record(client, student, _day(-2)).status_code == 403

    def test_a_student_reads_only_their_own_record(self, client, db_session):
        mine = _mk_student(db_session, "self", with_user=True)
        _assign(db_session, mine, start=_day(-30))
        other, _other_assignment = _resident(db_session, "self-other")
        db_session.commit()

        _login(client, ADMIN)
        assert _record(client, other, _day(-2)).status_code == 201
        assert _record(client, mine, _day(-3), points=1).status_code == 201

        user = db_session.query(User).filter(User.id == mine.user_id).first()
        assert user is not None
        _login(client, user.email)

        body = client.get(f"{API}/me")
        assert body.status_code == 200, body.text
        payload = body.json()
        assert payload["student_id"] == str(mine.id)
        assert len(payload["absences"]) == 1
        assert payload["points_total"] == 1.0

        # No staff surface and no write path is open to a student.
        assert client.get(f"{API}/students").status_code == 403
        assert client.get(f"{API}/students/{other.id}").status_code == 403
        assert _record(client, mine, _day(-1)).status_code == 403

    def test_anonymous_is_unauthenticated(self, client):
        assert client.get(f"{API}/me").status_code == 401
        assert client.get(f"{API}/students").status_code == 401

    def test_the_permissions_are_granted_to_the_right_roles(self, db_session):
        def permissions(role_name: str) -> set[str]:
            role = db_session.query(Role).filter(Role.name == role_name).first()
            assert role is not None
            return {permission.codename for permission in role.permissions}

        assert "attendance.record_dormitory" in permissions("ADMIN")
        assert "attendance.view_dormitory" in permissions("ADMIN")
        assert "attendance.record_dormitory" in permissions("MANAGEMENT")
        assert "attendance.view_dormitory" in permissions("MANAGEMENT")
        assert "attendance.view_dormitory" in permissions("STUDENT")
        assert "attendance.record_dormitory" not in permissions("STUDENT")
        assert "attendance.record_dormitory" not in permissions("TEACHER")
        assert "attendance.view_dormitory" not in permissions("TEACHER")


# ── F. Resident list ───────────────────────────────────────────────────────


class TestResidentList:
    def test_current_and_former_residents_are_distinguished(self, client, db_session):
        current, _a = _resident(db_session, "list-current", start=_day(-30))
        former, _b = _resident(
            db_session, "list-former", start=_day(-90), end=_day(-60), status="ENDED"
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        everyone = client.get(f"{API}/students", params={"page_size": 100}).json()
        numbers = {row["student_number"] for row in everyone["items"]}
        assert current.student_id in numbers
        assert former.student_id in numbers

        current_only = client.get(
            f"{API}/students", params={"residency": "current", "page_size": 100}
        ).json()
        current_numbers = {row["student_number"] for row in current_only["items"]}
        assert current.student_id in current_numbers
        assert former.student_id not in current_numbers

        former_only = client.get(
            f"{API}/students", params={"residency": "former", "page_size": 100}
        ).json()
        former_numbers = {row["student_number"] for row in former_only["items"]}
        assert former.student_id in former_numbers
        assert current.student_id not in former_numbers

    def test_search_matches_the_student_number(self, client, db_session):
        student, _assignment = _resident(db_session, "search")
        db_session.commit()

        _login(client, MANAGEMENT)
        body = client.get(
            f"{API}/students", params={"search": student.student_id}
        ).json()
        assert [row["student_number"] for row in body["items"]] == [student.student_id]

    def test_the_list_shows_the_assignment_and_points(self, client, db_session):
        student, assignment = _resident(db_session, "list-points")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, _day(-3), points=2.5).status_code == 201

        body = client.get(
            f"{API}/students", params={"search": student.student_id}
        ).json()
        row = body["items"][0]
        assert row["housing_assignment_id"] == str(assignment.id)
        assert row["is_current_resident"] is True
        assert row["absence_count"] == 1
        assert row["points_total"] == 2.5
        assert row["room_number"] == "101"


# ── G. Cancellation ────────────────────────────────────────────────────────


CANCELLATION_REASON = "The resident was on an approved overnight study trip."


def _cancel(
    client,
    student: Student,
    absence_id: str,
    *,
    reason: str = CANCELLATION_REASON,
):
    return client.post(
        f"{API}/students/{student.id}/absences/{absence_id}/cancellations",
        json={"reason": reason},
    )


class TestAbsenceCancellation:
    """Cancellation withdraws an absence without deleting or rewriting it."""

    def test_cancellation_keeps_the_record_and_records_who_and_why(
        self, client, db_session
    ):
        student, _assignment = _resident(db_session, "cancel-keep")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-2), points=3).json()["absence"]

        response = _cancel(client, student, created["id"])
        assert response.status_code == 201, response.text
        body = response.json()["absence"]

        # Same row, same original values …
        assert body["id"] == created["id"]
        assert body["points"] == 3.0
        assert body["absence_date"] == _day(-2).isoformat()
        assert body["reason"] == REASON
        # … plus the cancellation facts.
        assert body["cancelled_at"] is not None
        assert body["cancelled_by_name"]
        assert body["cancellation_reason"] == CANCELLATION_REASON
        assert body["is_active"] is False

        db_session.expire_all()
        row = db_session.get(DormitoryAbsence, uuid.UUID(created["id"]))
        assert row is not None
        assert row.cancelled_at is not None
        assert row.cancelled_by_id is not None

    def test_cancelled_absence_stops_counting(self, client, db_session):
        student, _assignment = _resident(db_session, "cancel-points")
        db_session.commit()

        _login(client, MANAGEMENT)
        first = _record(client, student, _day(-5), points=3).json()["absence"]
        assert _record(client, student, _day(-4), points=5).status_code == 201

        before = client.get(f"{API}/students/{student.id}").json()
        assert before["absence_count"] == 2
        assert before["points_total"] == 8.0

        cancelled = _cancel(client, student, first["id"]).json()
        assert cancelled["absence_count"] == 1
        assert cancelled["points_total"] == 5.0

        after = client.get(f"{API}/students/{student.id}").json()
        assert after["absence_count"] == 1
        assert after["points_total"] == 5.0

        row = next(
            item for item in after["assignments"] if item["is_current"]
        )
        assert row["absence_count"] == 1
        assert row["points_total"] == 5.0

        listed = client.get(
            f"{API}/students", params={"search": student.student_id}
        ).json()["items"][0]
        assert listed["absence_count"] == 1
        assert listed["points_total"] == 5.0

    def test_a_half_written_cancellation_is_refused_by_the_database(
        self, client, db_session
    ):
        """A cancellation is all three values or none — enforced in SQL."""
        from sqlalchemy import text  # noqa: PLC0415
        from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

        student, _assignment = _resident(db_session, "cancel-check")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-3), points=1).json()["absence"]

        with pytest.raises(IntegrityError):
            db_session.execute(
                text(
                    "UPDATE dormitory_absences SET cancelled_at = now() "
                    "WHERE id = :id"
                ),
                {"id": created["id"]},
            )
            db_session.flush()
        db_session.rollback()

    def test_cancellation_needs_a_substantive_reason(self, client, db_session):
        student, _assignment = _resident(db_session, "cancel-reason")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-2)).json()["absence"]

        assert _cancel(client, student, created["id"], reason="typo").status_code == 422
        assert _cancel(
            client, student, created["id"], reason="too short"
        ).status_code == 422

    def test_a_cancelled_absence_cannot_be_corrected_or_cancelled_again(
        self, client, db_session
    ):
        student, _assignment = _resident(db_session, "cancel-terminal")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-2)).json()["absence"]
        assert _cancel(client, student, created["id"]).status_code == 201

        assert _cancel(client, student, created["id"]).status_code == 404
        correction = _correct(
            client, student, created["id"], _day(-2), points=4
        )
        assert correction.status_code == 404

    def test_the_date_is_free_again_after_cancellation(self, client, db_session):
        """Cancelling frees the date without resurrecting the old row."""
        student, _assignment = _resident(db_session, "cancel-refill")
        db_session.commit()

        _login(client, MANAGEMENT)
        first = _record(client, student, _day(-2), points=3).json()["absence"]
        assert _cancel(client, student, first["id"]).status_code == 201

        replacement = _record(client, student, _day(-2), points=1)
        assert replacement.status_code == 201, replacement.text
        assert replacement.json()["absence"]["id"] != first["id"]
        assert replacement.json()["absence_count"] == 1
        assert replacement.json()["points_total"] == 1.0

    def test_cancellation_is_audited_with_the_previous_values(
        self, client, db_session
    ):
        student, _assignment = _resident(db_session, "cancel-audit")
        db_session.commit()

        _login(client, ADMIN)
        created = _record(client, student, _day(-2), points=3).json()["absence"]
        assert _cancel(client, student, created["id"]).status_code == 201

        entry = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.action == "dormitory.absence.cancelled",
                AuditLog.entity_id == uuid.UUID(created["id"]),
            )
            .first()
        )
        assert entry is not None
        assert entry.context["points"] == 3.0
        assert entry.context["cancellation_reason"] == CANCELLATION_REASON

    def test_a_student_cannot_cancel(self, client, db_session):
        student = _mk_student(db_session, "cancel-student", with_user=True)
        _assign(db_session, student, start=_day(-30), end=None, status="ACTIVE")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, _day(-2)).json()["absence"]

        _login(client, student.user.email)
        assert _cancel(client, student, created["id"]).status_code == 403


# ── H. Corrections across housing assignments ───────────────────────────────


class TestCrossAssignmentCorrection:
    """A correction may move a record to another stay the student really had."""

    def test_correction_moves_the_record_to_another_stay(
        self, client, db_session
    ):
        student = _mk_student(db_session, "cross")
        transfer = _day(-10)
        first = _assign(
            db_session, student, start=_day(-60), end=transfer, status="ENDED"
        )
        second = _assign(db_session, student, start=transfer, end=None, status="ACTIVE")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(
            client, student, transfer, points=2, assignment_id=str(first.id)
        ).json()["absence"]
        assert created["housing_assignment_id"] == str(first.id)

        response = client.post(
            f"{API}/students/{student.id}/absences/{created['id']}/corrections",
            json={
                "absence_date": transfer.isoformat(),
                "points": 2,
                "reason": CORRECTION_REASON,
                "housing_assignment_id": str(second.id),
            },
        )
        assert response.status_code == 201, response.text
        moved = response.json()["absence"]
        assert moved["housing_assignment_id"] == str(second.id)

        # The original row is preserved against the stay it was filed under.
        db_session.expire_all()
        original = db_session.get(DormitoryAbsence, uuid.UUID(created["id"]))
        assert original is not None
        assert original.housing_assignment_id == first.id
        assert original.superseded_at is not None
        assert replaced_history_length(db_session, student) == 2

    def test_a_stay_that_does_not_cover_the_date_is_refused(
        self, client, db_session
    ):
        student = _mk_student(db_session, "cross-bad")
        transfer = _day(-10)
        first = _assign(
            db_session, student, start=_day(-60), end=transfer, status="ENDED"
        )
        later = _assign(
            db_session, student, start=_day(-3), end=None, status="ACTIVE"
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(
            client, student, _day(-20), points=2, assignment_id=str(first.id)
        ).json()["absence"]

        response = client.post(
            f"{API}/students/{student.id}/absences/{created['id']}/corrections",
            json={
                "absence_date": _day(-20).isoformat(),
                "points": 2,
                "reason": CORRECTION_REASON,
                "housing_assignment_id": str(later.id),
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == (
            "DORMITORY_DATE_OUTSIDE_ASSIGNMENT"
        )

    def test_another_students_stay_is_refused(self, client, db_session):
        mine = _mk_student(db_session, "cross-mine")
        other, other_assignment = _resident(db_session, "cross-other")
        _assign(db_session, mine, start=_day(-30), end=None, status="ACTIVE")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, mine, _day(-2), points=2).json()["absence"]

        response = client.post(
            f"{API}/students/{mine.id}/absences/{created['id']}/corrections",
            json={
                "absence_date": _day(-2).isoformat(),
                "points": 2,
                "reason": CORRECTION_REASON,
                "housing_assignment_id": str(other_assignment.id),
            },
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "DORMITORY_ASSIGNMENT_NOT_FOUND"
        )


def replaced_history_length(db_session, student: Student) -> int:
    """How many rows the student has, current and historical."""
    return (
        db_session.query(DormitoryAbsence)
        .filter(DormitoryAbsence.student_id == student.id)
        .count()
    )
