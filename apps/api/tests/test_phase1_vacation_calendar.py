"""Vacation calendar ranges: the VACATION day type and its parent records.

These tests pin the extension the institution authorized:

* A vacation is a *range*. Creating one materialises a ``VACATION`` date per day,
  atomically, with the parent row as their identity.
* Every date resolves as a non-working academic day, so attendance denominators
  shrink and commencement suggestions skip it.
* No vacation ever overrides an existing holiday, closure, exceptional working
  day or another vacation: a conflict aborts the whole request.
* Shortening and extension keep history — removed dates are voided, not deleted,
  and extension does not recreate the dates that were already there.
* A date corrected individually is detached from its range; cancelling the
  vacation leaves it exactly as the institution set it.
* Cancellation records the actor, the timestamp and the reason, transactionally,
  and never deletes a row.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.auth.service import hash_password
from app.models.academic import AcademicPeriod, ProgramOffering
from app.models.admission import AcademicAdmission
from app.models.attendance import AttendanceCommencement
from app.models.audit import AuditLog
from app.models.calendar import CalendarVacationRange, UniversityCalendarDay
from app.models.identity import Student, User
from app.schemas.calendar import (
    VacationRangeAdjust,
    VacationRangeCancel,
    VacationRangeCreate,
)
from app.services import calendar as svc

CALENDAR = "/api/v1/academics/calendar"
RANGES = f"{CALENDAR}/vacation-ranges"
DAYS = f"{CALENDAR}/days"
ATTENDANCE = "/api/v1/attendance"
LOGIN = "/api/v1/auth/login"

ADMIN = "admin@school.portal"
MANAGEMENT = "management@school.portal"
TEACHER = "teacher@school.portal"
STUDENT_ACCOUNT = "student@school.portal"

REASON = "Winter vacation approved by the university council."
CHANGE_REASON = "The vacation was extended by a week after the council review."
VOID_REASON = "The vacation was withdrawn by the university council."
TITLE = "Winter vacation"

#: 2035-01-01 is a Monday. Weekdays: 01-01 … 01-05, weekend 01-06/01-07.
WEEK_START = date(2035, 1, 1)


def _day(offset: int) -> date:
    return WEEK_START + timedelta(days=offset)


def _login(client, email: str) -> None:
    response = client.post(LOGIN, json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text


def _create_range(
    client,
    *,
    start: date = WEEK_START,
    end: date = _day(4),
    title: str = TITLE,
    reason: str = REASON,
):
    return client.post(
        RANGES,
        json={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "title": title,
            "reason": reason,
        },
    )


def _declare(client, day: date, day_type: str) -> None:
    response = client.post(
        DAYS,
        json={
            "calendar_date": day.isoformat(),
            "day_type": day_type,
            "title": f"Declared {day_type.lower()}",
            "reason": "Declared by the registrar for the whole university.",
        },
    )
    assert response.status_code == 201, response.text


def _days_in(client, start: date, end: date, *, include_voided: bool = False):
    response = client.get(
        DAYS,
        params={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "include_voided": include_voided,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _range_days(db, range_id: uuid.UUID) -> list[UniversityCalendarDay]:
    return (
        db.query(UniversityCalendarDay)
        .filter(UniversityCalendarDay.calendar_range_id == range_id)
        .order_by(UniversityCalendarDay.calendar_date)
        .all()
    )


def _range_entries(db, range_id: str) -> list[AuditLog]:
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == "calendar_vacation_range",
            AuditLog.entity_id == uuid.UUID(range_id),
        )
        .order_by(AuditLog.created_at)
        .all()
    )


# ── A. Resolution ──────────────────────────────────────────────────────────


class TestVacationResolution:
    def test_every_materialised_date_resolves_as_a_non_working_day(
        self, client, db_session
    ):
        _login(client, ADMIN)
        created = _create_range(client)
        assert created.status_code == 201, created.text

        for offset in range(5):
            resolved = svc.resolve_date(db_session, _day(offset))
            assert resolved.day_type.value == "VACATION"
            assert resolved.is_working is False
            assert resolved.source == "EXCEPTION"
            assert resolved.exception_id is not None

    def test_vacation_does_not_exist_until_the_institution_enters_it(
        self, client, db_session
    ):
        before = svc.resolve_date(db_session, _day(0))
        assert before.day_type.value == "WORKING"
        assert before.source == "DEFAULT"

    def test_coverage_reports_vacation_dates_and_days(self, client):
        _login(client, MANAGEMENT)
        assert _create_range(client).status_code == 201

        response = client.get(
            f"{CALENDAR}/coverage",
            params={
                "start_date": WEEK_START.isoformat(),
                "end_date": _day(6).isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        coverage = response.json()

        assert coverage["vacations"] == [_day(offset).isoformat() for offset in range(5)]
        assert coverage["total_days"] == 7
        assert coverage["default_working_days"] == 5
        # All five working days were withdrawn by the vacation.
        assert coverage["working_days"] == 0
        assert coverage["non_working_days"] == 7


# ── B. Range identity and atomic creation ──────────────────────────────────


class TestRangeCreation:
    def test_creation_materialises_one_date_per_day_owned_by_the_range(
        self, client, db_session
    ):
        _login(client, ADMIN)
        created = _create_range(client, end=_day(9))
        assert created.status_code == 201, created.text
        body = created.json()

        range_id = uuid.UUID(body["id"])
        range_row = db_session.query(CalendarVacationRange).filter_by(id=range_id).one()
        assert range_row.start_date == WEEK_START
        assert range_row.end_date == _day(9)
        assert range_row.is_cancelled is False

        rows = _range_days(db_session, range_id)
        assert [row.calendar_date for row in rows] == [_day(i) for i in range(10)]
        assert {row.day_type for row in rows} == {"VACATION"}
        assert all(row.is_void is False for row in rows)
        assert body["dates"] == [_day(i).isoformat() for i in range(10)]
        assert body["detached_dates"] == []
        assert body["voided_date_count"] == 0

    def test_identity_survives_reading_the_range_back(self, client, db_session):
        _login(client, MANAGEMENT)
        created = _create_range(client).json()

        fetched = client.get(f"{RANGES}/{created['id']}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["id"] == created["id"]
        assert fetched.json()["dates"] == created["dates"]

        listed = client.get(
            RANGES,
            params={
                "start_date": WEEK_START.isoformat(),
                "end_date": _day(4).isoformat(),
            },
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["id"] == created["id"]

    def test_creation_is_atomic(self, client, db_session):
        _login(client, ADMIN)
        assert _create_range(client).status_code == 201

        db_session.expire_all()
        assert db_session.query(CalendarVacationRange).count() == 1
        assert db_session.query(UniversityCalendarDay).count() == 5

        audit = _range_entries(db_session, str(
            db_session.query(CalendarVacationRange).one().id
        ))
        assert [entry.action for entry in audit] == [
            "academic.calendar.vacation_range_created"
        ]
        assert audit[0].context["day_count"] == 5
        assert audit[0].context["start_date"] == WEEK_START.isoformat()

    def test_creation_without_a_reason_or_title_is_refused(self, client, db_session):
        _login(client, ADMIN)
        no_reason = _create_range(client, reason="  why  ")
        assert no_reason.status_code == 422, no_reason.text
        assert no_reason.json()["error"]["code"] == "CALENDAR_REASON_REQUIRED"

        no_title = client.post(
            RANGES,
            json={
                "start_date": WEEK_START.isoformat(),
                "end_date": _day(4).isoformat(),
                "title": "   ",
                "reason": REASON,
            },
        )
        assert no_title.status_code == 422, no_title.text
        assert no_title.json()["error"]["code"] == "CALENDAR_TITLE_REQUIRED"

        db_session.expire_all()
        assert db_session.query(CalendarVacationRange).count() == 0
        assert db_session.query(UniversityCalendarDay).count() == 0

    def test_reversed_and_oversized_ranges_are_refused(self, client, db_session):
        _login(client, ADMIN)

        reversed_range = _create_range(client, start=_day(4), end=WEEK_START)
        assert reversed_range.status_code == 422, reversed_range.text
        assert reversed_range.json()["error"]["code"] == "CALENDAR_RANGE_INVALID"

        oversized = _create_range(
            client, start=WEEK_START, end=WEEK_START + timedelta(days=svc.MAX_RANGE_DAYS)
        )
        assert oversized.status_code == 422, oversized.text
        assert oversized.json()["error"]["code"] == "CALENDAR_RANGE_TOO_LARGE"

        db_session.expire_all()
        assert db_session.query(CalendarVacationRange).count() == 0
        assert db_session.query(UniversityCalendarDay).count() == 0

    def test_a_single_day_vacation_is_rejected_in_favour_of_a_range(self, client):
        _login(client, ADMIN)
        response = client.post(
            DAYS,
            json={
                "calendar_date": WEEK_START.isoformat(),
                "day_type": "VACATION",
                "title": TITLE,
                "reason": REASON,
            },
        )
        assert response.status_code == 422, response.text
        assert (
            response.json()["error"]["code"] == "CALENDAR_VACATION_REQUIRES_RANGE"
        )


# ── C. Conflicts ───────────────────────────────────────────────────────────


class TestRangeConflicts:
    @pytest.mark.parametrize("day_type", ["HOLIDAY", "CLOSURE", "EXCEPTIONAL_WORKING"])
    def test_every_exception_type_blocks_the_range(self, client, db_session, day_type):
        _login(client, ADMIN)
        _declare(client, _day(2), day_type)

        response = _create_range(client)
        assert response.status_code == 409, response.text
        assert (
            response.json()["error"]["code"] == "CALENDAR_VACATION_RANGE_CONFLICT"
        )
        assert _day(2).isoformat() in response.json()["error"]["message"]

        db_session.expire_all()
        assert db_session.query(CalendarVacationRange).count() == 0
        # The refused range materialised nothing: only the declared exception is
        # in the calendar.
        assert db_session.query(UniversityCalendarDay).count() == 1

    def test_overlapping_vacation_is_refused(self, client, db_session):
        _login(client, ADMIN)
        assert _create_range(client, end=_day(4)).status_code == 201

        response = _create_range(client, start=_day(4), end=_day(6))
        assert response.status_code == 409, response.text
        assert (
            response.json()["error"]["code"] == "CALENDAR_VACATION_RANGE_OVERLAP"
        )

        db_session.expire_all()
        assert db_session.query(CalendarVacationRange).count() == 1
        assert db_session.query(UniversityCalendarDay).count() == 5

    def test_a_declaration_inside_an_existing_vacation_is_refused(self, client):
        _login(client, ADMIN)
        assert _create_range(client).status_code == 201

        response = client.post(
            DAYS,
            json={
                "calendar_date": _day(2).isoformat(),
                "day_type": "HOLIDAY",
                "title": "National holiday",
                "reason": "Declared after the vacation was entered.",
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CALENDAR_DAY_CONFLICT"


# ── D. Shortening, extension and history ───────────────────────────────────


class TestRangeAdjustment:
    def test_shortening_voids_removed_dates_and_keeps_them_readable(
        self, client, db_session
    ):
        _login(client, ADMIN)
        created = _create_range(client, end=_day(9)).json()

        response = client.patch(
            f"{RANGES}/{created['id']}",
            json={"end_date": _day(4).isoformat(), "change_reason": CHANGE_REASON},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["end_date"] == _day(4).isoformat()
        assert body["dates"] == [_day(i).isoformat() for i in range(5)]
        assert body["voided_date_count"] == 5

        # The removed dates are history, not live calendar: they fall back to
        # the weekday rule (including the weekend at offsets 5 and 6).
        for offset in range(5, 10):
            resolved = svc.resolve_date(db_session, _day(offset))
            assert resolved.source == "DEFAULT"
            assert resolved.day_type is svc.default_day_type(_day(offset))

        history = _days_in(client, WEEK_START, _day(9), include_voided=True)
        assert len(history) == 10
        assert {row["is_void"] for row in history} == {True, False}
        voided = [row for row in history if row["is_void"]]
        assert len(voided) == 5
        assert {row["void_reason"] for row in voided} == {CHANGE_REASON}
        assert all(row["calendar_range_id"] == created["id"] for row in voided)

        entries = _range_entries(db_session, created["id"])
        assert [entry.action for entry in entries][-1] == (
            "academic.calendar.vacation_range_adjusted"
        )
        assert entries[-1].context["previous_end_date"] == _day(9).isoformat()
        assert entries[-1].context["voided_count"] == 5
        assert entries[-1].context["change_reason"] == CHANGE_REASON

    def test_extension_adds_dates_without_recreating_existing_ones(
        self, client, db_session
    ):
        _login(client, ADMIN)
        created = _create_range(client, end=_day(4)).json()
        original = {
            row["calendar_date"]: row["id"]
            for row in _days_in(client, WEEK_START, _day(4))
        }

        response = client.patch(
            f"{RANGES}/{created['id']}",
            json={"end_date": _day(7).isoformat(), "change_reason": CHANGE_REASON},
        )
        assert response.status_code == 200, response.text
        assert response.json()["dates"] == [_day(i).isoformat() for i in range(8)]

        after = {
            row["calendar_date"]: row["id"]
            for row in _days_in(client, WEEK_START, _day(7))
        }
        for day, exception_id in original.items():
            assert after[day] == exception_id, "extension must not recreate a date"

        for offset in range(5, 8):
            resolved = svc.resolve_date(db_session, _day(offset))
            assert resolved.day_type.value == "VACATION"
            assert resolved.is_working is False

    def test_an_extension_into_an_existing_exception_is_refused(
        self, client, db_session
    ):
        _login(client, ADMIN)
        created = _create_range(client).json()
        _declare(client, _day(5), "CLOSURE")

        response = client.patch(
            f"{RANGES}/{created['id']}",
            json={"end_date": _day(6).isoformat(), "change_reason": CHANGE_REASON},
        )
        assert response.status_code == 409, response.text
        assert (
            response.json()["error"]["code"] == "CALENDAR_VACATION_RANGE_CONFLICT"
        )

        db_session.expire_all()
        range_row = db_session.query(CalendarVacationRange).one()
        assert range_row.end_date == _day(4)
        assert len(_range_days(db_session, range_row.id)) == 5

    def test_an_unchanged_adjustment_is_refused(self, client):
        _login(client, ADMIN)
        created = _create_range(client).json()
        response = client.patch(
            f"{RANGES}/{created['id']}",
            json={"end_date": _day(4).isoformat(), "change_reason": CHANGE_REASON},
        )
        assert response.status_code == 422, response.text
        assert (
            response.json()["error"]["code"] == "CALENDAR_VACATION_RANGE_UNCHANGED"
        )


# ── E. Cancellation and detached dates ─────────────────────────────────────


class TestCancellation:
    def test_cancellation_voids_the_dates_and_keeps_the_records(
        self, client, db_session
    ):
        _login(client, ADMIN)
        created = _create_range(client).json()

        response = client.post(
            f"{RANGES}/{created['id']}/cancellation", json={"reason": VOID_REASON}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["is_cancelled"] is True
        assert body["cancelled_at"] is not None
        assert body["cancelled_by_id"] is not None
        assert body["cancel_reason"] == VOID_REASON
        assert body["dates"] == []
        assert body["voided_date_count"] == 5

        db_session.expire_all()
        rows = _range_days(db_session, uuid.UUID(created["id"]))
        assert len(rows) == 5
        assert all(row.is_void for row in rows)
        assert {row.void_reason for row in rows} == {VOID_REASON}
        assert all(row.voided_by_id is not None for row in rows)

        for offset in range(5):
            resolved = svc.resolve_date(db_session, _day(offset))
            assert resolved.source == "DEFAULT"

        entries = _range_entries(db_session, created["id"])
        assert [entry.action for entry in entries] == [
            "academic.calendar.vacation_range_created",
            "academic.calendar.vacation_range_cancelled",
        ]
        assert entries[-1].context["cancelled_count"] == 5
        assert entries[-1].context["reason"] == VOID_REASON

    def test_cancellation_requires_a_reason_and_cannot_repeat(self, client):
        _login(client, ADMIN)
        created = _create_range(client).json()

        no_reason = client.post(
            f"{RANGES}/{created['id']}/cancellation", json={"reason": "no"}
        )
        assert no_reason.status_code == 422, no_reason.text
        assert no_reason.json()["error"]["code"] == "CALENDAR_REASON_REQUIRED"

        assert (
            client.post(
                f"{RANGES}/{created['id']}/cancellation", json={"reason": VOID_REASON}
            ).status_code
            == 200
        )
        again = client.post(
            f"{RANGES}/{created['id']}/cancellation", json={"reason": VOID_REASON}
        )
        assert again.status_code == 409, again.text
        assert (
            again.json()["error"]["code"]
            == "CALENDAR_VACATION_RANGE_ALREADY_CANCELLED"
        )

    def test_a_cancelled_range_cannot_be_adjusted(self, client):
        _login(client, ADMIN)
        created = _create_range(client).json()
        assert (
            client.post(
                f"{RANGES}/{created['id']}/cancellation", json={"reason": VOID_REASON}
            ).status_code
            == 200
        )

        response = client.patch(
            f"{RANGES}/{created['id']}",
            json={"end_date": _day(7).isoformat(), "change_reason": CHANGE_REASON},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CALENDAR_VACATION_RANGE_CANCELLED"

    def test_a_corrected_date_is_preserved_when_the_range_is_cancelled(
        self, client, db_session
    ):
        _login(client, ADMIN)
        created = _create_range(client).json()

        target = next(
            row
            for row in _days_in(client, WEEK_START, _day(4))
            if row["calendar_date"] == _day(2).isoformat()
        )
        corrected = client.patch(
            f"{DAYS}/{target['id']}",
            json={
                "day_type": "EXCEPTIONAL_WORKING",
                "title": "Rescheduled teaching day during vacation",
                "change_reason": "The council declared this date a teaching day.",
            },
        )
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["detached_from_range_at"] is not None
        assert corrected.json()["calendar_range_id"] == created["id"]

        cancelled = client.post(
            f"{RANGES}/{created['id']}/cancellation", json={"reason": VOID_REASON}
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["detached_dates"] == [_day(2).isoformat()]
        assert cancelled.json()["voided_date_count"] == 4

        db_session.expire_all()
        preserved = svc.resolve_date(db_session, _day(2))
        assert preserved.day_type.value == "EXCEPTIONAL_WORKING"
        assert preserved.is_working is True

        # Every other date fell back to the weekday rule.
        for offset in (0, 1, 3, 4):
            assert svc.resolve_date(db_session, _day(offset)).source == "DEFAULT"

    def test_shortening_preserves_a_corrected_date_beyond_the_new_end(
        self, client, db_session
    ):
        _login(client, ADMIN)
        created = _create_range(client, end=_day(9)).json()

        target = next(
            row
            for row in _days_in(client, WEEK_START, _day(9))
            if row["calendar_date"] == _day(7).isoformat()
        )
        assert (
            client.patch(
                f"{DAYS}/{target['id']}",
                json={
                    "day_type": "EXCEPTIONAL_WORKING",
                    "change_reason": "The council declared this teaching day.",
                },
            ).status_code
            == 200
        )

        response = client.patch(
            f"{RANGES}/{created['id']}",
            json={"end_date": _day(4).isoformat(), "change_reason": CHANGE_REASON},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["detached_dates"] == [_day(7).isoformat()]
        assert body["dates"] == [_day(i).isoformat() for i in range(5)]

        db_session.expire_all()
        preserved = svc.resolve_date(db_session, _day(7))
        assert preserved.is_working is True
        assert preserved.day_type.value == "EXCEPTIONAL_WORKING"


# ── F. Audit integrity ─────────────────────────────────────────────────────


class TestRangeAudit:
    def test_an_audit_failure_rolls_back_the_whole_range(
        self, client, db_session, monkeypatch
    ):
        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        monkeypatch.setattr("app.services.calendar.record_audit", _explode)

        _login(client, ADMIN)
        with pytest.raises(RuntimeError):
            _create_range(client)

        db_session.expire_all()
        assert db_session.query(CalendarVacationRange).count() == 0
        assert db_session.query(UniversityCalendarDay).count() == 0


# ── G. Attendance integration ──────────────────────────────────────────────


def _mk_attendance_scenario(db, tag: str):
    """A past intake with two working weeks and one approved commencement."""
    intake = AcademicPeriod(
        code=f"VC{uuid.uuid4().hex[:10]}",
        name=f"Vacation intake {tag}",
        start_date=date(2024, 6, 3),
        end_date=date(2024, 6, 14),
        status="ACTIVE",
    )
    db.add(intake)
    db.flush()
    offering = ProgramOffering(
        academic_period_id=intake.id,
        source_id=f"VC-{tag}-{uuid.uuid4().hex[:6]}",
        source_key=f"vc-offering-{tag}-{uuid.uuid4().hex[:8]}",
        name=f"Vacation offering {tag}",
    )
    db.add(offering)
    db.flush()

    user = User(
        email=f"vc-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"vc-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Vacation {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"VC-{tag.upper()}-{uuid.uuid4().hex[:6]}",
        first_name="Vacation",
        last_name=tag,
        status="ACTIVE",
    )
    db.add(student)
    db.flush()

    actor = db.query(User).filter(User.email == ADMIN).first()
    assert actor is not None
    episode = AcademicAdmission(
        student_id=student.id,
        admission_intake_id=intake.id,
        admitted_program_offering_id=offering.id,
        status="ACTIVE",
        initial_status="ACTIVE",
        record_origin="NEW_ADMISSION",
        verification_status="VERIFIED",
        activated_at=datetime(2024, 6, 3, 8, 0),
        created_by_id=actor.id,
    )
    db.add(episode)
    db.flush()
    db.add(
        AttendanceCommencement(
            admission_id=episode.id,
            student_id=student.id,
            commencement_date=date(2024, 6, 3),
            commencement_type="SCHEDULED",
            reason="Confirmed against the enrolment register for this intake.",
            suggested_date=date(2024, 6, 3),
            approved_by_id=actor.id,
        )
    )
    db.flush()
    return student, episode


class TestAttendanceIntegration:
    def test_vacation_is_excluded_from_the_eligible_day_denominator(
        self, client, db_session
    ):
        student, _episode = _mk_attendance_scenario(db_session, "denominator")
        db_session.commit()

        _login(client, ADMIN)
        response = _create_range(
            client,
            start=date(2024, 6, 5),
            end=date(2024, 6, 7),
            title="Summer vacation",
        )
        assert response.status_code == 201, response.text

        _login(client, MANAGEMENT)
        body = client.get(f"{ATTENDANCE}/students/{student.id}").json()
        # Ten working days in the intake, three of them declared vacation.
        assert body["eligible_days"] == 7
        assert body["absence_count"] == 0
        assert body["percentage"] == 100.0

    def test_an_absence_on_a_vacation_date_is_rejected(self, client, db_session):
        student, episode = _mk_attendance_scenario(db_session, "absence")
        db_session.commit()

        _login(client, ADMIN)
        assert (
            _create_range(
                client,
                start=date(2024, 6, 5),
                end=date(2024, 6, 7),
                title="Summer vacation",
            ).status_code
            == 201
        )

        _login(client, MANAGEMENT)
        rejected = client.post(
            f"{ATTENDANCE}/students/{student.id}/absences",
            json={
                "admission_id": str(episode.id),
                "absence_date": date(2024, 6, 5).isoformat(),
                "reason": "Student was absent from scheduled instruction.",
            },
        )
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["error"]["code"] == "ABSENCE_NON_WORKING_DAY"

        accepted = client.post(
            f"{ATTENDANCE}/students/{student.id}/absences",
            json={
                "admission_id": str(episode.id),
                "absence_date": date(2024, 6, 4).isoformat(),
                "reason": "Student was absent from scheduled instruction.",
            },
        )
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["calculation"]["eligible_days"] == 7
        assert accepted.json()["calculation"]["percentage"] == 85.7


# ── H. Commencement integration ────────────────────────────────────────────


def _mk_commencement_scenario(db, tag: str):
    intake = AcademicPeriod(
        code=f"VCC{uuid.uuid4().hex[:9]}",
        name=f"Vacation commencement intake {tag}",
        start_date=date(2035, 1, 1),
        end_date=date(2035, 3, 31),
        status="ACTIVE",
    )
    db.add(intake)
    db.flush()
    offering = ProgramOffering(
        academic_period_id=intake.id,
        source_id=f"VCC-{tag}-{uuid.uuid4().hex[:6]}",
        source_key=f"vcc-offering-{tag}-{uuid.uuid4().hex[:8]}",
        name=f"Vacation commencement offering {tag}",
    )
    db.add(offering)
    db.flush()

    user = User(
        email=f"vcc-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"vcc-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Vacation commencement {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"VCC-{tag.upper()}-{uuid.uuid4().hex[:6]}",
        first_name="Vacation",
        last_name=tag,
        status="ACTIVE",
    )
    db.add(student)
    db.flush()

    actor = db.query(User).filter(User.email == ADMIN).first()
    assert actor is not None
    episode = AcademicAdmission(
        student_id=student.id,
        admission_intake_id=intake.id,
        admitted_program_offering_id=offering.id,
        status="ACTIVE",
        initial_status="ACTIVE",
        record_origin="NEW_ADMISSION",
        verification_status="VERIFIED",
        activated_at=datetime(2035, 1, 1, 8, 0),
        created_by_id=actor.id,
    )
    db.add(episode)
    db.flush()
    return student, episode


def _commencement_payload(**overrides) -> dict:
    payload = {
        "commencement_date": date(2035, 1, 4).isoformat(),
        "commencement_type": "SCHEDULED",
        "reason": "Confirmed against the enrolment register for this intake.",
        "confirmed_suggested_date": date(2035, 1, 4).isoformat(),
    }
    payload.update(overrides)
    return payload


class TestCommencementIntegration:
    def test_suggestion_skips_vacation_dates(self, client, db_session):
        student, episode = _mk_commencement_scenario(db_session, "suggest")
        db_session.commit()

        _login(client, ADMIN)
        assert (
            _create_range(client, start=WEEK_START, end=_day(2)).status_code == 201
        )

        _login(client, MANAGEMENT)
        body = client.get(
            f"{ATTENDANCE}/students/{student.id}/admissions/{episode.id}/commencement"
        ).json()
        assert body["suggested_date"] == date(2035, 1, 4).isoformat()

    def test_approval_on_a_vacation_date_is_rejected(self, client, db_session):
        student, episode = _mk_commencement_scenario(db_session, "approve")
        db_session.commit()

        _login(client, ADMIN)
        assert (
            _create_range(client, start=WEEK_START, end=_day(2)).status_code == 201
        )

        _login(client, MANAGEMENT)
        response = client.post(
            f"{ATTENDANCE}/students/{student.id}/admissions/{episode.id}/commencement",
            json=_commencement_payload(
                commencement_date=date(2035, 1, 2).isoformat(),
                commencement_type="MANUAL",
            ),
        )
        assert response.status_code == 422, response.text
        assert (
            response.json()["error"]["code"] == "COMMENCEMENT_NON_WORKING_DAY"
        )

    def test_correction_onto_a_vacation_date_is_rejected(self, client, db_session):
        student, episode = _mk_commencement_scenario(db_session, "correct")
        db_session.commit()

        _login(client, ADMIN)
        assert (
            _create_range(client, start=WEEK_START, end=_day(2)).status_code == 201
        )

        _login(client, MANAGEMENT)
        approved = client.post(
            f"{ATTENDANCE}/students/{student.id}/admissions/{episode.id}/commencement",
            json=_commencement_payload(),
        )
        assert approved.status_code == 201, approved.text

        response = client.post(
            f"{ATTENDANCE}/students/{student.id}/admissions/{episode.id}/commencement/corrections",
            json=_commencement_payload(
                commencement_date=date(2035, 1, 2).isoformat(),
                commencement_type="MANUAL",
                reason="The register shows the student started two days earlier.",
            ),
        )
        assert response.status_code == 422, response.text
        assert (
            response.json()["error"]["code"] == "COMMENCEMENT_NON_WORKING_DAY"
        )


# ── I. Authorization ───────────────────────────────────────────────────────


class TestVacationAuthorization:
    def test_teacher_and_student_cannot_enter_or_cancel_a_vacation(self, client):
        _login(client, TEACHER)
        assert _create_range(client).status_code == 403

        _login(client, STUDENT_ACCOUNT)
        assert _create_range(client).status_code == 403
        assert client.get(RANGES).status_code == 403

        assert client.get(RANGES).status_code in {401, 403}


# ── J. Historical date reuse, concurrency and rollback ─────────────────────


class TestHistoricalDateReuse:
    """Voided rows are history, not reservations.

    The unique index on ``calendar_date`` is partial (``is_void = false``), so
    re-issuing a date must never collide with the row that used to occupy it.
    These tests pin every path that relies on that: re-extension after a
    shortening, a fresh range over a cancelled range's dates, and the refusal
    that protects a date the institution corrected on its own terms.
    """

    def test_extension_reissues_dates_voided_by_a_shortening(
        self, client, db_session
    ):
        _login(client, ADMIN)
        created = _create_range(client, end=_day(9)).json()
        original = {
            row["calendar_date"]: row["id"]
            for row in _days_in(client, WEEK_START, _day(9))
        }

        shortened = client.patch(
            f"{RANGES}/{created['id']}",
            json={"end_date": _day(4).isoformat(), "change_reason": CHANGE_REASON},
        )
        assert shortened.status_code == 200, shortened.text

        restored = client.patch(
            f"{RANGES}/{created['id']}",
            json={"end_date": _day(9).isoformat(), "change_reason": CHANGE_REASON},
        )
        assert restored.status_code == 200, restored.text
        body = restored.json()
        assert body["dates"] == [_day(i).isoformat() for i in range(10)]
        assert body["voided_date_count"] == 5

        history = _days_in(client, WEEK_START, _day(9), include_voided=True)
        live = [row for row in history if not row["is_void"]]
        voided = [row for row in history if row["is_void"]]
        assert len(live) == 10
        assert len(voided) == 5
        # Exactly one live declaration per date, and no row was deleted: the
        # voided rows keep their own identity beside the re-issued dates.
        assert len({row["calendar_date"] for row in live}) == 10
        for row in voided:
            assert row["id"] == original[row["calendar_date"]]
        assert {row["calendar_range_id"] for row in live} == {created["id"]}

        for offset in range(5, 10):
            assert (
                svc.resolve_date(db_session, _day(offset)).day_type.value
                == "VACATION"
            )

    def test_a_new_range_reuses_the_dates_of_a_cancelled_range(
        self, client, db_session
    ):
        _login(client, ADMIN)
        first = _create_range(client).json()
        assert (
            client.post(
                f"{RANGES}/{first['id']}/cancellation", json={"reason": VOID_REASON}
            ).status_code
            == 200
        )

        second = _create_range(client)
        assert second.status_code == 201, second.text
        second_body = second.json()
        assert second_body["id"] != first["id"]
        assert second_body["dates"] == [_day(i).isoformat() for i in range(5)]

        history = _days_in(client, WEEK_START, _day(4), include_voided=True)
        assert len(history) == 10
        old = [row for row in history if row["calendar_range_id"] == first["id"]]
        assert len(old) == 5
        assert all(row["is_void"] for row in old)
        assert {row["calendar_range_id"] for row in history if not row["is_void"]} == {
            second_body["id"]
        }

    def test_re_extension_over_a_preserved_detached_date_is_refused(
        self, client, db_session
    ):
        _login(client, ADMIN)
        created = _create_range(client, end=_day(9)).json()

        target = next(
            row
            for row in _days_in(client, WEEK_START, _day(9))
            if row["calendar_date"] == _day(7).isoformat()
        )
        corrected = client.patch(
            f"{DAYS}/{target['id']}",
            json={
                "day_type": "EXCEPTIONAL_WORKING",
                "title": "Council teaching day",
                "change_reason": "The council declared this date a teaching day.",
            },
        )
        assert corrected.status_code == 200, corrected.text

        shortened = client.patch(
            f"{RANGES}/{created['id']}",
            json={"end_date": _day(4).isoformat(), "change_reason": CHANGE_REASON},
        )
        assert shortened.status_code == 200, shortened.text
        assert shortened.json()["detached_dates"] == [_day(7).isoformat()]

        # The preserved date is a live declaration in its own right: extending
        # back over it must be refused, never silently absorbed.
        refused = client.patch(
            f"{RANGES}/{created['id']}",
            json={"end_date": _day(9).isoformat(), "change_reason": CHANGE_REASON},
        )
        assert refused.status_code == 409, refused.text
        assert (
            refused.json()["error"]["code"] == "CALENDAR_VACATION_RANGE_CONFLICT"
        )

        db_session.expire_all()
        preserved = svc.resolve_date(db_session, _day(7))
        assert preserved.day_type.value == "EXCEPTIONAL_WORKING"
        assert preserved.is_working is True
        assert preserved.title == "Council teaching day"

    def test_shortening_after_a_commit_writes_complete_void_fields(
        self, db_session
    ):
        """The void fields must be written in one statement.

        ``create_vacation_range`` commits, which expires ``actor``. Reading
        ``actor.id`` midway through voiding a row would refresh it, and that
        refresh's autoflush would emit a half-voided UPDATE that the void-fields
        constraint rejects — aborting a legitimate shortening.
        """
        actor = db_session.query(User).filter(User.email == ADMIN).one()
        created = svc.create_vacation_range(
            db_session,
            VacationRangeCreate(
                start_date=WEEK_START, end_date=_day(4), title=TITLE, reason=REASON
            ),
            actor,
        )
        adjusted = svc.adjust_vacation_range(
            db_session,
            VacationRangeAdjust(end_date=_day(2), change_reason=CHANGE_REASON),
            actor,
            range_id=created.id,
        )

        rows = _range_days(db_session, adjusted.id)
        voided = [row for row in rows if row.is_void]
        assert len(voided) == 2
        assert all(row.voided_by_id is not None for row in voided)
        assert {row.void_reason for row in voided} == {CHANGE_REASON}

    def test_cancellation_after_a_commit_writes_complete_void_fields(
        self, db_session
    ):
        actor = db_session.query(User).filter(User.email == ADMIN).one()
        created = svc.create_vacation_range(
            db_session,
            VacationRangeCreate(
                start_date=WEEK_START, end_date=_day(4), title=TITLE, reason=REASON
            ),
            actor,
        )
        cancelled = svc.cancel_vacation_range(
            db_session,
            VacationRangeCancel(reason=VOID_REASON),
            actor,
            range_id=created.id,
        )

        rows = _range_days(db_session, cancelled.id)
        assert len(rows) == 5
        assert all(row.is_void for row in rows)
        assert all(row.voided_by_id is not None for row in rows)
        assert {row.void_reason for row in rows} == {VOID_REASON}


class TestRangeOperationRollback:
    def test_an_audit_failure_rolls_back_an_adjustment(
        self, client, db_session, monkeypatch
    ):
        _login(client, ADMIN)
        created = _create_range(client, end=_day(9)).json()

        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        monkeypatch.setattr("app.services.calendar.record_audit", _explode)
        with pytest.raises(RuntimeError):
            client.patch(
                f"{RANGES}/{created['id']}",
                json={"end_date": _day(4).isoformat(), "change_reason": CHANGE_REASON},
            )

        db_session.expire_all()
        range_row = (
            db_session.query(CalendarVacationRange)
            .filter_by(id=uuid.UUID(created["id"]))
            .one()
        )
        assert range_row.end_date == _day(9)
        rows = _range_days(db_session, range_row.id)
        assert len(rows) == 10
        assert all(not row.is_void for row in rows)

    def test_an_audit_failure_rolls_back_a_cancellation(
        self, client, db_session, monkeypatch
    ):
        _login(client, ADMIN)
        created = _create_range(client).json()

        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        monkeypatch.setattr("app.services.calendar.record_audit", _explode)
        with pytest.raises(RuntimeError):
            client.post(
                f"{RANGES}/{created['id']}/cancellation", json={"reason": VOID_REASON}
            )

        db_session.expire_all()
        range_row = (
            db_session.query(CalendarVacationRange)
            .filter_by(id=uuid.UUID(created["id"]))
            .one()
        )
        assert range_row.is_cancelled is False
        assert range_row.cancelled_at is None
        assert range_row.cancel_reason is None
        rows = _range_days(db_session, range_row.id)
        assert len(rows) == 5
        assert all(not row.is_void for row in rows)


class TestConcurrentRangeCreation:
    def test_two_conflicting_creations_leave_one_complete_range(self, db_session):
        """The unique index, not the pre-check, decides a concurrent race."""
        engine = db_session.get_bind().engine
        maker = sessionmaker(bind=engine)
        start, end = date(2042, 8, 4), date(2042, 8, 8)
        barrier = threading.Barrier(2)
        guard = threading.Lock()
        results: list[str] = []

        def attempt(index: int) -> None:
            session = maker()
            try:
                actor = session.query(User).filter(User.email == ADMIN).one()
                barrier.wait(timeout=20)
                try:
                    svc.create_vacation_range(
                        session,
                        VacationRangeCreate(
                            start_date=start,
                            end_date=end,
                            title=f"Concurrent {index}",
                            reason=REASON,
                        ),
                        actor,
                    )
                    with guard:
                        results.append("created")
                except svc.CalendarError as exc:
                    with guard:
                        results.append(exc.code)
                except Exception as exc:  # noqa: BLE001 - reported as a failure
                    with guard:
                        results.append(type(exc).__name__)
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt, args=(index,)) for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        try:
            assert sorted(results) == [
                "CALENDAR_VACATION_RANGE_CONFLICT",
                "created",
            ]

            db_session.expire_all()
            ranges = (
                db_session.query(CalendarVacationRange)
                .filter(CalendarVacationRange.start_date == start)
                .all()
            )
            assert len(ranges) == 1
            days = (
                db_session.query(UniversityCalendarDay)
                .filter(
                    UniversityCalendarDay.calendar_date >= start,
                    UniversityCalendarDay.calendar_date <= end,
                )
                .all()
            )
            assert len(days) == 5
            assert all(not row.is_void for row in days)
        finally:
            # These rows were committed on their own connections, so the test
            # fixture's rollback cannot discard them.
            cleanup = maker()
            try:
                cleanup.query(UniversityCalendarDay).filter(
                    UniversityCalendarDay.calendar_date >= start,
                    UniversityCalendarDay.calendar_date <= end,
                ).delete(synchronize_session=False)
                cleanup.query(CalendarVacationRange).filter(
                    CalendarVacationRange.start_date == start
                ).delete(synchronize_session=False)
                cleanup.commit()
            finally:
                cleanup.close()
