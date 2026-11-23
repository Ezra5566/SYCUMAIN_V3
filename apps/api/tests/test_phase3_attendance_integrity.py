"""Phase 3 integrity corrections: audited cancellation and calendar-aware counts.

Two claims are pinned here.

* A wrongly recorded absence is *cancelled*, not corrected and not deleted. The
  row keeps its date, reason and recorder, gains who cancelled it and why, leaves
  the calculation, and stays visible in the history. The date becomes recordable
  again; a cancelled record cannot be corrected or cancelled twice.
* Attendance is recomputed against the calendar as it stands *now*. A holiday or
  closure declared afterwards removes that day from the eligible days and from
  the countable absences; an exceptional working day keeps an existing absence
  counted. The absence rows themselves are never touched, and nothing is clamped.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.models.attendance_absence import AttendanceAbsence
from app.models.audit import AuditLog
from tests.test_phase3_attendance_absence import (  # noqa: F401 - fixtures/helpers
    ADMIN,
    API,
    CALENDAR,
    CORRECTION_REASON,
    FIRST_WEEK_DAYS,
    MANAGEMENT,
    REASON,
    _correct,
    _declare,
    _login,
    _record,
    _scenario,
)

CANCEL_REASON = "Recorded against the wrong student; withdrawn by the registrar."


def _cancel(client, student, absence_id: str, reason: str = CANCEL_REASON):
    return client.post(
        f"{API}/students/{student.id}/absences/{absence_id}/cancellation",
        json={"reason": reason},
    )


def _status(client, student) -> dict:
    response = client.get(f"{API}/students/{student.id}")
    assert response.status_code == 200, response.text
    return response.json()


# ── A. Cancellation ────────────────────────────────────────────────────────


class TestCancellation:
    def test_cancelling_removes_the_absence_from_the_figure(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "cancel-count")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 5))
        assert created.status_code == 201, created.text
        assert created.json()["calculation"]["percentage"] == 90.0

        cancelled = _cancel(client, student, created.json()["absence"]["id"])
        assert cancelled.status_code == 201, cancelled.text
        body = cancelled.json()
        assert body["absence"]["cancelled_at"] is not None
        assert body["calculation"]["absence_count"] == 0
        assert body["calculation"]["percentage"] == 100.0

        detail = _status(client, student)
        assert detail["absence_count"] == 0
        assert detail["percentage"] == 100.0

    def test_the_cancelled_record_stays_visible_and_unchanged(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "cancel-keep")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 5))
        absence_id = created.json()["absence"]["id"]

        _cancel(client, student, absence_id)
        detail = _status(client, student)
        assert len(detail["absences"]) == 1
        row = detail["absences"][0]
        assert row["id"] == absence_id
        # The original claim is intact; only the cancellation was added.
        assert row["absence_date"] == "2024-03-05"
        assert row["reason"] == REASON
        assert row["recorded_by_name"] == "Management User"
        assert row["cancelled_by_name"] == "Management User"
        assert row["cancellation_reason"] == CANCEL_REASON
        assert row["cancelled_at"] is not None
        assert row["superseded_at"] is None
        assert row["supersedes_id"] is None

    def test_the_cancellation_is_audited(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "cancel-audit")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 5))
        absence_id = created.json()["absence"]["id"]
        assert _cancel(client, student, absence_id).status_code == 201

        db_session.expire_all()
        entries = (
            db_session.query(AuditLog)
            .filter(AuditLog.entity_type == "attendance_absence")
            .order_by(AuditLog.created_at)
            .all()
        )
        assert [entry.action for entry in entries] == [
            "attendance.absence.recorded",
            "attendance.absence.cancelled",
        ]
        audit = entries[-1]
        assert str(audit.entity_id) == absence_id
        assert audit.actor_email == MANAGEMENT
        assert audit.context["absence_date"] == "2024-03-05"
        assert audit.context["recorded_reason"] == REASON
        assert audit.context["reason"] == CANCEL_REASON
        assert audit.context["admission_id"] == str(episode.id)

    def test_a_cancellation_reason_is_required(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "cancel-reason")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 5))
        absence_id = created.json()["absence"]["id"]

        response = _cancel(client, student, absence_id, reason="wrong")
        assert response.status_code == 422, response.text
        assert (
            response.json()["error"]["code"]
            == "ABSENCE_CANCELLATION_REASON_REQUIRED"
        )

        detail = _status(client, student)
        assert detail["absence_count"] == 1
        assert detail["absences"][0]["cancelled_at"] is None

    def test_a_cancelled_absence_cannot_be_cancelled_twice(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "cancel-twice")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 5))
        absence_id = created.json()["absence"]["id"]
        assert _cancel(client, student, absence_id).status_code == 201

        again = _cancel(client, student, absence_id)
        assert again.status_code == 404, again.text
        assert again.json()["error"]["code"] == "ABSENCE_NOT_FOUND"

        detail = _status(client, student)
        assert detail["absences"][0]["cancellation_reason"] == CANCEL_REASON

    def test_a_cancelled_absence_cannot_be_corrected(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "cancel-correct")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 5))
        absence_id = created.json()["absence"]["id"]
        assert _cancel(client, student, absence_id).status_code == 201

        response = _correct(
            client, student, absence_id, date(2024, 3, 6), CORRECTION_REASON
        )
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "ABSENCE_NOT_FOUND"

    def test_a_superseded_absence_cannot_be_cancelled(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "cancel-superseded")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 5))
        original_id = created.json()["absence"]["id"]
        assert (
            _correct(
                client, student, original_id, date(2024, 3, 6), CORRECTION_REASON
            ).status_code
            == 201
        )

        response = _cancel(client, student, original_id)
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "ABSENCE_NOT_FOUND"

    def test_the_date_can_be_recorded_again_after_cancellation(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "cancel-rerecord")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 5))
        absence_id = created.json()["absence"]["id"]

        duplicate = _record(client, student, episode, date(2024, 3, 5))
        assert duplicate.status_code == 409, duplicate.text

        assert _cancel(client, student, absence_id).status_code == 201

        replacement = _record(client, student, episode, date(2024, 3, 5))
        assert replacement.status_code == 201, replacement.text
        assert replacement.json()["calculation"]["absence_count"] == 1
        assert replacement.json()["calculation"]["percentage"] == 90.0

        # Two rows exist: the cancelled original and the active replacement.
        detail = _status(client, student)
        assert len(detail["absences"]) == 2
        assert detail["absence_count"] == 1
        assert sum(1 for row in detail["absences"] if row["cancelled_at"]) == 1

        # And the active replacement still blocks a second active record.
        assert (
            _record(client, student, episode, date(2024, 3, 5)).status_code == 409
        )

    def test_an_audit_failure_rolls_back_the_cancellation(
        self, client, db_session, monkeypatch
    ):
        student, episode, _intake, _offering = _scenario(db_session, "cancel-rollback")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 5))
        absence_id = uuid.UUID(created.json()["absence"]["id"])

        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        monkeypatch.setattr("app.services.absence.record_audit", _explode)

        with pytest.raises(RuntimeError):
            _cancel(client, student, str(absence_id), CANCEL_REASON)

        db_session.expire_all()
        stored = (
            db_session.query(AttendanceAbsence)
            .filter(AttendanceAbsence.id == absence_id)
            .first()
        )
        assert stored is not None
        assert stored.cancelled_at is None
        assert stored.cancelled_by_id is None
        assert stored.cancellation_reason is None

        detail = _status(client, student)
        assert detail["absence_count"] == 1
        assert detail["percentage"] == 90.0


# ── B. Calendar-aware recalculation ────────────────────────────────────────


class TestCalendarReactivity:
    def test_a_holiday_declared_later_excludes_the_absence(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "late-holiday")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, episode, date(2024, 3, 5)).status_code == 201
        assert _status(client, student)["percentage"] == 90.0

        _login(client, ADMIN)
        _declare(client, date(2024, 3, 5), "HOLIDAY", "Retrospective holiday")

        _login(client, MANAGEMENT)
        detail = _status(client, student)
        assert detail["eligible_days"] == FIRST_WEEK_DAYS - 1
        assert detail["absence_count"] == 0
        assert detail["excluded_absence_count"] == 1
        assert detail["percentage"] == 100.0

        # The record itself was not touched: it is history now, not numerator.
        assert len(detail["absences"]) == 1
        assert detail["absences"][0]["absence_date"] == "2024-03-05"
        assert detail["absences"][0]["cancelled_at"] is None

    def test_a_closure_declared_later_excludes_the_absence(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "late-closure")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, episode, date(2024, 3, 6)).status_code == 201

        _login(client, ADMIN)
        _declare(client, date(2024, 3, 6), "CLOSURE", "Retrospective closure")

        _login(client, MANAGEMENT)
        detail = _status(client, student)
        assert detail["eligible_days"] == FIRST_WEEK_DAYS - 1
        assert detail["absence_count"] == 0
        assert detail["excluded_absence_count"] == 1
        assert detail["percentage"] == 100.0

    def test_an_exceptional_working_day_keeps_an_existing_absence_counted(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "exceptional-count")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, episode, date(2024, 3, 8)).status_code == 201

        _login(client, ADMIN)
        _declare(
            client,
            date(2024, 3, 8),
            "EXCEPTIONAL_WORKING",
            "Make-up teaching day",
        )

        _login(client, MANAGEMENT)
        detail = _status(client, student)
        # Friday was working already, and remains working: nothing moves.
        assert detail["eligible_days"] == FIRST_WEEK_DAYS
        assert detail["absence_count"] == 1
        assert detail["excluded_absence_count"] == 0
        assert detail["percentage"] == 90.0

    def test_correcting_the_exception_reinstates_the_absence(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "calendar-correct")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, episode, date(2024, 3, 5)).status_code == 201

        _login(client, ADMIN)
        created = _declare(
            client, date(2024, 3, 5), "HOLIDAY", "Originally declared a holiday"
        )
        exception_id = created.json()["id"]

        excluded = _status(client, student)
        assert excluded["excluded_absence_count"] == 1
        assert excluded["absence_count"] == 0

        corrected = client.patch(
            f"{CALENDAR}/{exception_id}",
            json={
                "day_type": "EXCEPTIONAL_WORKING",
                "change_reason": "The day was taught after all; the calendar was wrong.",
            },
        )
        assert corrected.status_code == 200, corrected.text

        restored = _status(client, student)
        assert restored["eligible_days"] == FIRST_WEEK_DAYS
        assert restored["absence_count"] == 1
        assert restored["excluded_absence_count"] == 0
        assert restored["percentage"] == 90.0
        assert len(restored["absences"]) == 1

    def test_voiding_the_exception_reinstates_the_absence(self, client, db_session):
        student, episode, _intake, _offering = _scenario(db_session, "calendar-void")
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _record(client, student, episode, date(2024, 3, 5)).status_code == 201

        _login(client, ADMIN)
        created = _declare(
            client, date(2024, 3, 5), "HOLIDAY", "Withdrawn holiday declaration"
        )
        exception_id = created.json()["id"]

        assert _status(client, student)["percentage"] == 100.0

        voided = client.post(
            f"{CALENDAR}/{exception_id}/void",
            json={"reason": "The declaration was issued for the wrong date."},
        )
        assert voided.status_code == 200, voided.text

        restored = _status(client, student)
        assert restored["eligible_days"] == FIRST_WEEK_DAYS
        assert restored["absence_count"] == 1
        assert restored["percentage"] == 90.0

    def test_a_cancelled_absence_stays_out_after_a_calendar_correction(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "cancel-calendar")
        db_session.commit()

        _login(client, MANAGEMENT)
        created = _record(client, student, episode, date(2024, 3, 5))
        assert _cancel(client, student, created.json()["absence"]["id"]).status_code == 201

        _login(client, ADMIN)
        _declare(client, date(2024, 3, 5), "HOLIDAY", "Holiday on the same date")

        _login(client, MANAGEMENT)
        detail = _status(client, student)
        assert detail["absence_count"] == 0
        assert detail["excluded_absence_count"] == 0
        assert detail["percentage"] == 100.0
        assert detail["absences"][0]["cancelled_at"] is not None

    def test_arithmetic_is_exact_when_only_some_absences_are_excluded(
        self, client, db_session
    ):
        student, episode, _intake, _offering = _scenario(db_session, "partial-exclude")
        db_session.commit()

        _login(client, MANAGEMENT)
        for day in (date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6)):
            assert _record(client, student, episode, day).status_code == 201

        _login(client, ADMIN)
        _declare(client, date(2024, 3, 5), "HOLIDAY", "One day reclassified")

        _login(client, MANAGEMENT)
        detail = _status(client, student)
        assert detail["eligible_days"] == FIRST_WEEK_DAYS - 1
        assert detail["absence_count"] == 2
        assert detail["excluded_absence_count"] == 1
        # (9 - 2) / 9 × 100, rounded once — not clamped or otherwise adjusted.
        assert detail["percentage"] == 77.8
