"""Phase 1: the university working-day calendar foundation.

The calendar is a *rule plus exceptions*, never a generated table. These tests
pin both halves: the Monday–Friday default (including the weekend), and the three
declarations an institution can record — holiday, closure and exceptional
working day — plus the effect of correcting and voiding them.

They also pin what must not happen: no row is stored for an ordinary date, a
teacher or student cannot reach the calendar, and a calendar change without its
audit entry is rolled back entirely.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.models.audit import AuditLog
from app.models.calendar import CalendarDayType, UniversityCalendarDay
from app.models.identity import Role, User
from app.permissions.constants import ALL_PERMISSIONS
from app.services import calendar as svc

API = "/api/v1/academics/calendar"
LOGIN = "/api/v1/auth/login"

ADMIN = "admin@school.portal"
MANAGEMENT = "management@school.portal"
TEACHER = "teacher@school.portal"
STUDENT = "student@school.portal"

REASON = "Institution closed for the national public holiday."
CHANGE_REASON = "The closure was announced a day earlier than published."
VOID_REASON = "The closure was cancelled by the university council."


def _login(client, email: str) -> None:
    response = client.post(LOGIN, json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text


def _date_on(weekday: int, *, start: date = date(2033, 1, 3)) -> date:
    """A concrete date with the requested weekday (Monday=0 … Sunday=6)."""
    return start + timedelta(days=(weekday - start.weekday()) % 7)


MONDAY = _date_on(0)
TUESDAY = _date_on(1)
WEDNESDAY = _date_on(2)
THURSDAY = _date_on(3)
FRIDAY = _date_on(4)
SATURDAY = _date_on(5)
SUNDAY = _date_on(6)


def _create(
    client,
    *,
    day: date,
    day_type: str,
    title: str = "Declared exception",
    reason: str = REASON,
):
    return client.post(
        f"{API}/days",
        json={
            "calendar_date": day.isoformat(),
            "day_type": day_type,
            "title": title,
            "reason": reason,
        },
    )


def _role_permissions(db, role_name: str) -> set[str]:
    role = db.query(Role).filter(Role.name == role_name).first()
    assert role is not None, f"role {role_name} is not seeded"
    return {permission.codename for permission in role.permissions}


def _declared_codenames() -> set[str]:
    return {
        permission["codename"]
        for group in ALL_PERMISSIONS.values()
        for permission in group
    }


# ── A. The weekday rule ─────────────────────────────────────────────────────


class TestWeekdayDefaults:
    def test_weekdays_are_working_days(self, db_session):
        resolved = svc.resolve_range(db_session, MONDAY, FRIDAY)

        assert [day.calendar_date for day in resolved] == [
            MONDAY,
            TUESDAY,
            WEDNESDAY,
            THURSDAY,
            FRIDAY,
        ]
        for day in resolved:
            assert day.day_type == CalendarDayType.WORKING
            assert day.is_working is True
            assert day.source == "DEFAULT"
            assert day.exception_id is None

    def test_saturday_and_sunday_are_not_working_days(self, db_session):
        saturday = svc.resolve_date(db_session, SATURDAY)
        sunday = svc.resolve_date(db_session, SUNDAY)

        for day in (saturday, sunday):
            assert day.day_type == CalendarDayType.WEEKEND
            assert day.is_working is False
            assert day.source == "DEFAULT"

    def test_resolving_a_week_stores_nothing(self, db_session):
        """No generated future calendar rows: a default costs no storage."""
        svc.resolve_range(db_session, MONDAY, SUNDAY)

        assert db_session.query(UniversityCalendarDay).count() == 0

    def test_weekday_defaults_report_the_rule_itself(self):
        defaults = svc.weekday_defaults()

        assert defaults["MONDAY"] == "WORKING"
        assert defaults["FRIDAY"] == "WORKING"
        assert defaults["SATURDAY"] == "WEEKEND"
        assert defaults["SUNDAY"] == "WEEKEND"


# ── B. Declared exceptions ─────────────────────────────────────────────────


class TestDeclaredExceptions:
    def test_holiday_excludes_an_ordinary_working_day(self, client, db_session):
        _login(client, ADMIN)
        response = _create(client, day=TUESDAY, day_type="HOLIDAY", title="Public holiday")
        assert response.status_code == 201, response.text

        resolved = svc.resolve_date(db_session, TUESDAY)
        assert resolved.day_type == CalendarDayType.HOLIDAY
        assert resolved.is_working is False
        assert resolved.source == "EXCEPTION"
        assert resolved.exception_id == uuid.UUID(response.json()["id"])

    def test_closure_excludes_the_date(self, client, db_session):
        _login(client, ADMIN)
        response = _create(
            client, day=WEDNESDAY, day_type="CLOSURE", title="Emergency closure"
        )
        assert response.status_code == 201, response.text

        resolved = svc.resolve_date(db_session, WEDNESDAY)
        assert resolved.day_type == CalendarDayType.CLOSURE
        assert resolved.is_working is False

    def test_exceptional_working_day_includes_a_saturday(self, client, db_session):
        _login(client, MANAGEMENT)
        response = _create(
            client,
            day=SATURDAY,
            day_type="EXCEPTIONAL_WORKING",
            title="Rescheduled teaching Saturday",
        )
        assert response.status_code == 201, response.text

        resolved = svc.resolve_date(db_session, SATURDAY)
        assert resolved.day_type == CalendarDayType.EXCEPTIONAL_WORKING
        assert resolved.is_working is True

    def test_voiding_restores_the_weekday_default(self, client, db_session):
        _login(client, ADMIN)
        created = _create(client, day=MONDAY, day_type="HOLIDAY", title="Public holiday")
        assert created.status_code == 201, created.text
        exception_id = created.json()["id"]

        voided = client.post(
            f"{API}/days/{exception_id}/void", json={"reason": VOID_REASON}
        )
        assert voided.status_code == 200, voided.text

        restored = svc.resolve_date(db_session, MONDAY)
        assert restored.day_type == CalendarDayType.WORKING
        assert restored.is_working is True
        assert restored.source == "DEFAULT"
        assert restored.exception_id is None

        # History stays inspectable: voiding is not deletion.
        kept = client.get(f"{API}/days/{exception_id}")
        assert kept.status_code == 200, kept.text
        assert kept.json()["is_void"] is True
        assert kept.json()["void_reason"] == VOID_REASON
        assert kept.json()["voided_by_id"] is not None

    def test_a_voided_date_can_be_declared_again(self, client, db_session):
        _login(client, MANAGEMENT)
        first = _create(client, day=THURSDAY, day_type="CLOSURE", title="Closure")
        assert first.status_code == 201, first.text
        assert (
            client.post(
                f"{API}/days/{first.json()['id']}/void", json={"reason": VOID_REASON}
            ).status_code
            == 200
        )

        second = _create(client, day=THURSDAY, day_type="HOLIDAY", title="Holiday")
        assert second.status_code == 201, second.text

        db_session.expire_all()
        rows = (
            db_session.query(UniversityCalendarDay)
            .filter(UniversityCalendarDay.calendar_date == THURSDAY)
            .all()
        )
        assert len(rows) == 2
        assert {row.is_void for row in rows} == {True, False}

    def test_listing_hides_voided_days_unless_requested(self, client):
        _login(client, ADMIN)
        created = _create(client, day=FRIDAY, day_type="HOLIDAY", title="Holiday")
        assert created.status_code == 201, created.text
        assert (
            client.post(
                f"{API}/days/{created.json()['id']}/void", json={"reason": VOID_REASON}
            ).status_code
            == 200
        )

        live = client.get(
            f"{API}/days",
            params={"start_date": MONDAY.isoformat(), "end_date": SUNDAY.isoformat()},
        )
        assert live.status_code == 200, live.text
        assert live.json()["total"] == 0

        history = client.get(
            f"{API}/days",
            params={
                "start_date": MONDAY.isoformat(),
                "end_date": SUNDAY.isoformat(),
                "include_voided": True,
            },
        )
        assert history.status_code == 200, history.text
        assert history.json()["total"] == 1
        assert history.json()["items"][0]["is_void"] is True


# ── C. Integrity ───────────────────────────────────────────────────────────


class TestCalendarIntegrity:
    def test_duplicate_live_declaration_is_rejected(self, client, db_session):
        _login(client, ADMIN)
        assert _create(client, day=TUESDAY, day_type="HOLIDAY").status_code == 201

        duplicate = _create(client, day=TUESDAY, day_type="CLOSURE")
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"]["code"] == "CALENDAR_DAY_CONFLICT"

        db_session.expire_all()
        assert (
            db_session.query(UniversityCalendarDay)
            .filter(UniversityCalendarDay.calendar_date == TUESDAY)
            .count()
            == 1
        )

    def test_derived_day_types_cannot_be_declared(self, client):
        _login(client, ADMIN)
        for derived in ("WORKING", "WEEKEND"):
            response = _create(client, day=WEDNESDAY, day_type=derived)
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "CALENDAR_DAY_TYPE_NOT_DECLARABLE"

    def test_unknown_day_type_is_refused_at_the_boundary(self, client):
        _login(client, ADMIN)
        response = _create(client, day=WEDNESDAY, day_type="SICK_DAY")
        assert response.status_code == 422, response.text

    def test_a_vacation_is_not_a_single_day_declaration(self, client):
        """A vacation needs a range, so a lone VACATION day is refused.

        Otherwise the date would exist with no parent range, and cancelling the
        vacation would silently leave it behind.
        """
        _login(client, ADMIN)
        response = _create(client, day=WEDNESDAY, day_type="VACATION")
        assert response.status_code == 422, response.text
        assert (
            response.json()["error"]["code"]
            == "CALENDAR_VACATION_REQUIRES_RANGE"
        )

    def test_a_reason_is_required_and_must_explain_something(self, client):
        _login(client, ADMIN)
        response = _create(client, day=WEDNESDAY, day_type="HOLIDAY", reason="  why  ")
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "CALENDAR_REASON_REQUIRED"

    def test_void_requires_a_reason(self, client):
        _login(client, ADMIN)
        created = _create(client, day=WEDNESDAY, day_type="HOLIDAY")
        assert created.status_code == 201

        response = client.post(
            f"{API}/days/{created.json()['id']}/void", json={"reason": "no"}
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "CALENDAR_REASON_REQUIRED"

    def test_a_voided_day_cannot_be_corrected(self, client):
        _login(client, ADMIN)
        created = _create(client, day=WEDNESDAY, day_type="HOLIDAY")
        assert created.status_code == 201
        assert (
            client.post(
                f"{API}/days/{created.json()['id']}/void", json={"reason": VOID_REASON}
            ).status_code
            == 200
        )

        response = client.patch(
            f"{API}/days/{created.json()['id']}",
            json={"title": "Late edit", "change_reason": CHANGE_REASON},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CALENDAR_EXCEPTION_VOIDED"

    def test_unknown_exception_reports_not_found(self, client):
        _login(client, ADMIN)
        response = client.get(f"{API}/days/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CALENDAR_EXCEPTION_NOT_FOUND"


# ── D. Authorization ───────────────────────────────────────────────────────


class TestCalendarAuthorization:
    def test_management_and_admin_hold_calendar_administration(self, db_session):
        for role_name in ("ADMIN", "MANAGEMENT"):
            assert "attendance.manage_calendar" in _role_permissions(db_session, role_name)

    def test_teachers_and_students_do_not(self, db_session):
        assert "attendance.manage_calendar" in _declared_codenames()
        for role_name in ("TEACHER", "STUDENT"):
            assert (
                "attendance.manage_calendar" not in _role_permissions(db_session, role_name)
            )

    def test_teacher_cannot_read_or_write_the_calendar(self, client):
        _login(client, TEACHER)
        assert client.get(f"{API}/days").status_code == 403
        assert (
            client.get(f"{API}/resolve", params={"day": TUESDAY.isoformat()}).status_code
            == 403
        )
        assert _create(client, day=TUESDAY, day_type="HOLIDAY").status_code == 403

    def test_student_cannot_read_or_write_the_calendar(self, client):
        _login(client, STUDENT)
        assert client.get(f"{API}/days").status_code == 403
        assert (
            client.get(
                f"{API}/coverage",
                params={"start_date": MONDAY.isoformat(), "end_date": SUNDAY.isoformat()},
            ).status_code
            == 403
        )
        assert (
            _create(client, day=SATURDAY, day_type="EXCEPTIONAL_WORKING").status_code
            == 403
        )

    def test_anonymous_requests_are_unauthenticated(self, client):
        assert client.get(f"{API}/days").status_code == 401

    def test_management_can_declare_correct_and_void(self, client, db_session):
        _login(client, MANAGEMENT)
        created = _create(client, day=TUESDAY, day_type="HOLIDAY", title="Holiday")
        assert created.status_code == 201, created.text
        exception_id = created.json()["id"]

        management = db_session.query(User).filter(User.email == MANAGEMENT).first()
        assert created.json()["created_by_id"] == str(management.id)

        corrected = client.patch(
            f"{API}/days/{exception_id}",
            json={"title": "National public holiday", "change_reason": CHANGE_REASON},
        )
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["title"] == "National public holiday"
        assert corrected.json()["updated_by_id"] == str(management.id)

        voided = client.post(
            f"{API}/days/{exception_id}/void", json={"reason": VOID_REASON}
        )
        assert voided.status_code == 200, voided.text


# ── E. Audit ───────────────────────────────────────────────────────────────


def _entries(db_session, exception_id: str) -> list[AuditLog]:
    return (
        db_session.query(AuditLog)
        .filter(
            AuditLog.entity_type == "university_calendar_day",
            AuditLog.entity_id == uuid.UUID(exception_id),
        )
        .order_by(AuditLog.created_at)
        .all()
    )


class TestCalendarAudit:
    def test_creation_is_attributed_with_previous_and_new_values(
        self, client, db_session
    ):
        _login(client, MANAGEMENT)
        created = _create(client, day=TUESDAY, day_type="HOLIDAY", title="Holiday")
        assert created.status_code == 201, created.text

        db_session.expire_all()
        entries = _entries(db_session, created.json()["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert entry.action == "academic.calendar.exception_created"

        management = db_session.query(User).filter(User.email == MANAGEMENT).first()
        assert entry.actor_id == management.id
        assert entry.actor_email == MANAGEMENT
        assert entry.created_at is not None
        assert entry.context["calendar_date"] == TUESDAY.isoformat()
        assert entry.context["previous_day_type"] == "WORKING"
        assert entry.context["new_day_type"] == "HOLIDAY"
        assert entry.context["reason"] == REASON

    def test_correction_preserves_the_previous_values(self, client, db_session):
        _login(client, ADMIN)
        created = _create(client, day=TUESDAY, day_type="HOLIDAY", title="Holiday")
        assert created.status_code == 201
        exception_id = created.json()["id"]

        corrected = client.patch(
            f"{API}/days/{exception_id}",
            json={
                "day_type": "CLOSURE",
                "title": "Emergency closure",
                "change_reason": CHANGE_REASON,
            },
        )
        assert corrected.status_code == 200, corrected.text

        db_session.expire_all()
        entries = _entries(db_session, exception_id)
        assert [entry.action for entry in entries] == [
            "academic.calendar.exception_created",
            "academic.calendar.exception_corrected",
        ]

        correction = entries[1]
        assert correction.context["previous_day_type"] == "HOLIDAY"
        assert correction.context["new_day_type"] == "CLOSURE"
        assert correction.context["previous_title"] == "Holiday"
        assert correction.context["new_title"] == "Emergency closure"
        assert correction.context["change_reason"] == CHANGE_REASON

        # The original declaration is not erased from the trail.
        assert entries[0].context["new_day_type"] == "HOLIDAY"

    def test_voiding_records_the_restored_default(self, client, db_session):
        _login(client, ADMIN)
        created = _create(client, day=MONDAY, day_type="HOLIDAY", title="Holiday")
        assert created.status_code == 201
        exception_id = created.json()["id"]
        assert (
            client.post(
                f"{API}/days/{exception_id}/void", json={"reason": VOID_REASON}
            ).status_code
            == 200
        )

        db_session.expire_all()
        entries = _entries(db_session, exception_id)
        assert [entry.action for entry in entries] == [
            "academic.calendar.exception_created",
            "academic.calendar.exception_voided",
        ]
        assert entries[1].context["previous_day_type"] == "HOLIDAY"
        assert entries[1].context["new_day_type"] == "WORKING"
        assert entries[1].context["void_reason"] == VOID_REASON

    def test_audit_failure_rolls_back_the_calendar_change(
        self, client, db_session, monkeypatch
    ):
        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        # The service holds the reference, so patching the module attribute is
        # what the request actually calls.
        monkeypatch.setattr("app.services.calendar.record_audit", _explode)

        _login(client, ADMIN)
        with pytest.raises(RuntimeError):
            _create(client, day=TUESDAY, day_type="HOLIDAY")

        db_session.expire_all()
        assert (
            db_session.query(UniversityCalendarDay)
            .filter(UniversityCalendarDay.calendar_date == TUESDAY)
            .count()
            == 0
        )


# ── F. Coverage report ─────────────────────────────────────────────────────


class TestCalendarCoverage:
    def test_report_states_the_rule_and_its_exceptions(self, client):
        _login(client, MANAGEMENT)
        assert (
            _create(
                client, day=WEDNESDAY, day_type="HOLIDAY", title="Public holiday"
            ).status_code
            == 201
        )
        assert (
            _create(
                client,
                day=SATURDAY,
                day_type="EXCEPTIONAL_WORKING",
                title="Teaching Saturday",
            ).status_code
            == 201
        )

        response = client.get(
            f"{API}/coverage",
            params={"start_date": MONDAY.isoformat(), "end_date": SUNDAY.isoformat()},
        )
        assert response.status_code == 200, response.text
        coverage = response.json()

        assert coverage["weekday_defaults"]["MONDAY"] == "WORKING"
        assert coverage["weekday_defaults"]["SATURDAY"] == "WEEKEND"
        assert coverage["total_days"] == 7
        # Five ordinary working days; the holiday removes one, the declared
        # Saturday adds one back.
        assert coverage["default_working_days"] == 5
        assert coverage["default_non_working_days"] == 2
        assert coverage["working_days"] == 5
        assert coverage["non_working_days"] == 2
        assert coverage["holidays"] == [WEDNESDAY.isoformat()]
        assert coverage["exceptional_working_days"] == [SATURDAY.isoformat()]
        assert coverage["closures"] == []
        assert coverage["voided_exception_count"] == 0
        assert len(coverage["exceptions"]) == 2
        assert len(coverage["days"]) == 7

        by_date = {day["calendar_date"]: day for day in coverage["days"]}
        assert by_date[WEDNESDAY.isoformat()]["day_type"] == "HOLIDAY"
        assert by_date[SATURDAY.isoformat()]["is_working"] is True
        assert by_date[TUESDAY.isoformat()]["source"] == "DEFAULT"

    def test_resolution_endpoint_reports_one_date(self, client):
        _login(client, ADMIN)
        response = client.get(f"{API}/resolve", params={"day": SUNDAY.isoformat()})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["day_type"] == "WEEKEND"
        assert payload["is_working"] is False
        assert payload["source"] == "DEFAULT"

    def test_a_bounded_range_is_enforced(self, client):
        _login(client, ADMIN)
        response = client.get(
            f"{API}/coverage",
            params={
                "start_date": MONDAY.isoformat(),
                "end_date": (MONDAY + timedelta(days=366)).isoformat(),
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "CALENDAR_RANGE_TOO_LARGE"

    def test_an_inverted_range_is_refused(self, client):
        _login(client, ADMIN)
        response = client.get(
            f"{API}/coverage",
            params={"start_date": SUNDAY.isoformat(), "end_date": MONDAY.isoformat()},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "CALENDAR_RANGE_INVALID"
