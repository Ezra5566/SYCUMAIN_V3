"""Phase 7 administrative corrections.

The tests use synthetic students and the real PostgreSQL trigger contract: a
correction must append history, retain the prior end state and never become a
back door around the lifecycle guards.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config.settings import get_settings
from app.database.session import engine
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionStatusHistory,
    StudentOriginalAdmissionHistory,
)
from app.models.audit import AuditLog
from app.models.identity import Student, User
from app.services.student_academic import (
    effective_admission,
    latest_effective_admission_subquery,
    student_academic_snapshot,
)
from tests.test_admission_changes import (
    _create_admission,
    _login,
    _mk_student,
    _request_change,
    _review,
    _scenario,
)
from tests.test_admission_lifecycle import _TRIGGER_STATEMENTS as LIFECYCLE_TRIGGERS
from tests.test_admission_verification import (
    _TRIGGER_STATEMENTS as VERIFICATION_TRIGGERS,
)
from tests.test_admission_verification import (
    _acts,
    _confirm,
    _make_candidate,
)

API = "/api/v1"


@pytest.fixture(scope="module", autouse=True)
def correction_triggers():
    """Install the production history/pointer guards for this module.

    The verification module contributes the original-pointer trigger; the
    lifecycle module contributes the strict transition guard. Order matters:
    the lifecycle function must be the final transition implementation.
    """
    with engine.begin() as connection:
        for statement in VERIFICATION_TRIGGERS:
            connection.execute(text(statement))
        for statement in LIFECYCLE_TRIGGERS:
            connection.execute(text(statement))


@pytest.fixture(autouse=True)
def phase_seven_flags(monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", True)
    monkeypatch.setattr(get_settings(), "ADMISSION_CHANGE_REQUESTS_ENABLED", True)
    monkeypatch.setattr(get_settings(), "ADMISSION_CORRECTIONS_ENABLED", True)
    monkeypatch.setattr(get_settings(), "ADMISSION_MIGRATION_CONSOLE_ENABLED", True)


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def _withdraw(client, student_id, admission_id, reason="Recorded in error"):
    response = client.post(
        f"{API}/students/{student_id}/admissions/{admission_id}/status",
        json={"status": "WITHDRAWN", "reason": reason},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _correct_status(client, student_id, admission_id, target, reason):
    return client.post(
        f"{API}/students/{student_id}/admissions/{admission_id}/corrections/status",
        json={"target_status": target, "reason": reason},
    )


def _history(db, admission_id):
    return (
        db.query(AcademicAdmissionStatusHistory)
        .filter(AcademicAdmissionStatusHistory.admission_id == admission_id)
        .order_by(
            AcademicAdmissionStatusHistory.created_at,
            AcademicAdmissionStatusHistory.id,
        )
        .all()
    )


def test_admin_correction_appends_history_and_retains_prior_end(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    withdrawn = _withdraw(client, student.id, admission["id"])
    assert withdrawn["ended_at"] is not None
    prior_ended_at = datetime.fromisoformat(withdrawn["ended_at"].replace("Z", "+00:00"))
    prior_activated_at = withdrawn["activated_at"]
    prior_history = _history(db_session, uuid.UUID(admission["id"]))
    prior_history_ids = [row.id for row in prior_history]

    db_session.commit()
    corrected = _correct_status(
        client,
        student.id,
        admission["id"],
        "ACTIVE",
        "Registrar confirmed the withdrawal was recorded against the wrong student",
    )
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert body["status"] == "ACTIVE"
    assert body["ended_at"] is None
    assert body["activated_at"] == prior_activated_at
    assert body["corrections_enabled"] is True

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert stored.status == "ACTIVE"
    assert stored.ended_at is None
    assert stored.admission_intake_id == data["intake"].id
    assert stored.admitted_program_id == data["p1"].id

    history = _history(db_session, stored.id)
    assert set(prior_history_ids).issubset({row.id for row in history})
    assert len(history) == len(prior_history) + 1
    corrections = [row for row in history if row.is_correction]
    assert len(corrections) == 1
    correction = corrections[0]
    assert correction.from_status == "WITHDRAWN"
    assert correction.to_status == "ACTIVE"
    assert correction.is_correction is True
    assert correction.corrected_from_recorded_at == prior_ended_at
    assert correction.reason.startswith("Registrar confirmed")

    audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "academic.admission.status_corrected",
            AuditLog.entity_id == stored.id,
        )
        .one()
    )
    assert audit.context["previous_status"] == "WITHDRAWN"
    assert audit.context["new_status"] == "ACTIVE"
    assert datetime.fromisoformat(
        audit.context["previous_ended_at"].replace("Z", "+00:00")
    ) == prior_ended_at
    assert audit.context["previous_end_reason"] == withdrawn["end_reason"]


def test_correction_refuses_another_active_episode(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    first = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    pending = _create_admission(
        client, student.id, data["later"].id, data["later_o1"].id, "PENDING"
    )
    _withdraw(client, student.id, first["id"], "Student left the programme")

    activated = client.post(
        f"{API}/students/{student.id}/admissions/{pending['id']}/status",
        json={"status": "ACTIVE"},
    )
    assert activated.status_code == 200, activated.text
    db_session.expire_all()
    history_before = _history(db_session, uuid.UUID(first["id"]))

    refused = _correct_status(
        client,
        student.id,
        first["id"],
        "ACTIVE",
        "Attempt to correct after another episode became active",
    )
    assert refused.status_code == 409
    assert _error_code(refused) == "ADMISSION_ALREADY_ACTIVE"

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(first["id"]))
    assert stored.status == "WITHDRAWN"
    assert stored.ended_at is not None
    assert [row.id for row in _history(db_session, stored.id)] == [
        row.id for row in history_before
    ]


def test_correction_requires_reason_admin_and_feature_flag(
    client, db_session, monkeypatch
):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    _withdraw(client, student.id, admission["id"])

    blank = _correct_status(client, student.id, admission["id"], "ACTIVE", "   ")
    assert blank.status_code == 422
    assert _error_code(blank) == "ADMISSION_CORRECTION_REASON_REQUIRED"

    _login(client, "management@school.portal")
    forbidden = _correct_status(
        client, student.id, admission["id"], "ACTIVE", "Manager tried to correct directly"
    )
    assert forbidden.status_code == 403

    _login(client)
    monkeypatch.setattr(get_settings(), "ADMISSION_CORRECTIONS_ENABLED", False)
    disabled = _correct_status(
        client, student.id, admission["id"], "ACTIVE", "Correction while the flag is off"
    )
    assert disabled.status_code == 403
    assert _error_code(disabled) == "ADMISSION_CORRECTIONS_DISABLED"


def test_management_requests_and_admin_approves_terminal_correction(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client, "management@school.portal")
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    _withdraw(client, student.id, admission["id"], "Recorded as a withdrawal in error")

    requested = _request_change(
        client,
        student.id,
        admission["id"],
        change_type="STATUS_CORRECTION",
        proposed_data={"status": "ACTIVE"},
        reason="Management verified the student never withdrew from the programme",
    )
    assert requested.status_code == 201, requested.text
    assert requested.json()["status"] == "PENDING"
    assert requested.json()["proposed_data"]["status"] == "ACTIVE"

    management_review = _review(client, requested.json()["id"])
    assert management_review.status_code == 403

    _login(client)
    approved = _review(client, requested.json()["id"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert stored.status == "ACTIVE"
    history = _history(db_session, stored.id)
    corrections = [row for row in history if row.is_correction]
    assert len(corrections) == 1
    assert corrections[0].from_status == "WITHDRAWN"
    assert corrections[0].to_status == "ACTIVE"
    audits = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action.in_(
                [
                    "academic.admission.status_corrected",
                    "academic.admission.change_approved",
                ]
            )
        )
        .all()
    )
    assert {entry.action for entry in audits} == {
        "academic.admission.status_corrected",
        "academic.admission.change_approved",
    }


def test_status_correction_request_requires_reason_and_flag(client, db_session, monkeypatch):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client, "management@school.portal")
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    _withdraw(client, student.id, admission["id"])

    blank = _request_change(
        client,
        student.id,
        admission["id"],
        change_type="STATUS_CORRECTION",
        proposed_data={"status": "ACTIVE"},
        reason="   ",
    )
    assert blank.status_code == 422
    assert _error_code(blank) == "CHANGE_REASON_REQUIRED"

    monkeypatch.setattr(get_settings(), "ADMISSION_CORRECTIONS_ENABLED", False)
    disabled = _request_change(
        client,
        student.id,
        admission["id"],
        change_type="STATUS_CORRECTION",
        proposed_data={"status": "ACTIVE"},
        reason="Request while corrections are disabled",
    )
    assert disabled.status_code == 403
    assert _error_code(disabled) == "ADMISSION_CORRECTIONS_DISABLED"


def test_pointer_correction_requires_reason_and_raw_sql_is_refused(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    first = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    _withdraw(client, student.id, first["id"])
    second = _create_admission(
        client, student.id, data["later"].id, data["later_o1"].id
    )

    db_session.expire_all()
    assert db_session.get(Student, student.id).original_admission_id == uuid.UUID(
        first["id"]
    )

    blank = client.post(
        f"{API}/students/{student.id}/original-admission/correction",
        json={"new_admission_id": second["id"], "reason": "  "},
    )
    assert blank.status_code == 422
    assert _error_code(blank) == "POINTER_REASON_REQUIRED"

    corrected = client.post(
        f"{API}/students/{student.id}/original-admission/correction",
        json={
            "new_admission_id": second["id"],
            "reason": "Admission letter shows the later intake is the original",
            "evidence_reference": "LETTER-2033",
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["previous_admission_id"] == first["id"]

    history = (
        db_session.query(StudentOriginalAdmissionHistory)
        .filter(StudentOriginalAdmissionHistory.student_id == student.id)
        .one()
    )
    assert history.previous_admission_id == uuid.UUID(first["id"])
    assert history.new_admission_id == uuid.UUID(second["id"])

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE students SET original_admission_id = :first WHERE id = :id"),
            {"first": uuid.UUID(first["id"]), "id": student.id},
        )
    db_session.rollback()


def test_pointer_correction_is_gated_by_the_rollback_flag(client, db_session, monkeypatch):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    first = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    _withdraw(client, student.id, first["id"])
    second = _create_admission(
        client, student.id, data["later"].id, data["later_o1"].id
    )

    monkeypatch.setattr(get_settings(), "ADMISSION_CORRECTIONS_ENABLED", False)
    disabled = client.post(
        f"{API}/students/{student.id}/original-admission/correction",
        json={
            "new_admission_id": second["id"],
            "reason": "Pointer correction must not run while disabled",
        },
    )
    assert disabled.status_code == 403
    assert _error_code(disabled) == "ADMISSION_CORRECTIONS_DISABLED"


def test_correction_preserves_verification_acts(client, db_session):
    tag = uuid.uuid4().hex[:7]
    student, _, _, body = _make_candidate(client, db_session, tag=tag)
    admission_id = body["id"]

    assert _confirm(client, student.id, admission_id, "MANAGEMENT").status_code == 200
    _login(client)
    assert _confirm(client, student.id, admission_id, "ADMIN").status_code == 200
    before = _acts(client, student.id, admission_id)
    assert len(before) == 2

    cancelled = client.post(
        f"{API}/students/{student.id}/admissions/{admission_id}/status",
        json={"status": "CANCELLED", "reason": "Cancelled in error"},
    )
    assert cancelled.status_code == 200, cancelled.text

    corrected = _correct_status(
        client,
        student.id,
        admission_id,
        "ACTIVE",
        "Management confirmed the cancellation was entered on the wrong record",
    )
    assert corrected.status_code == 200, corrected.text

    after = _acts(client, student.id, admission_id)
    assert [act["id"] for act in after] == [act["id"] for act in before]
    assert [act["action"] for act in after] == ["CONFIRM", "CONFIRM"]


def test_active_correction_outranks_a_newer_terminal_episode(client, db_session):
    """An older reactivated episode remains the programme in force."""
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    first = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    completed = client.post(
        f"{API}/students/{student.id}/admissions/{first['id']}/status",
        json={"status": "COMPLETED"},
    )
    assert completed.status_code == 200, completed.text

    second = _create_admission(
        client, student.id, data["later"].id, data["later_o2"].id
    )
    _withdraw(client, student.id, second["id"], "Newer programme withdrawn")

    corrected = _correct_status(
        client,
        student.id,
        first["id"],
        "ACTIVE",
        "Registrar confirmed the earlier completion was recorded in error",
    )
    assert corrected.status_code == 200, corrected.text

    db_session.expire_all()
    first_id = uuid.UUID(first["id"])
    second_id = uuid.UUID(second["id"])
    active_rows = (
        db_session.query(AcademicAdmission)
        .filter(
            AcademicAdmission.student_id == student.id,
            AcademicAdmission.status == "ACTIVE",
        )
        .all()
    )
    assert [(row.id, row.status) for row in active_rows] == [(first_id, "ACTIVE")]

    selected = effective_admission(db_session, student.id)
    assert selected is not None
    assert selected.id == first_id
    assert selected.current_program_id == data["p1"].id
    assert selected.id != second_id

    effective = latest_effective_admission_subquery(db_session)
    row = (
        db_session.query(effective.c.admission_id, effective.c.program_id)
        .filter(effective.c.student_id == student.id)
        .one()
    )
    assert row.admission_id == first_id
    assert row.program_id == data["p1"].id

    snapshot = student_academic_snapshot(db_session, student.id)
    assert snapshot.admission is not None
    assert snapshot.admission.id == first_id
    assert snapshot.program_id == data["p1"].id

    profile = client.get(f"{API}/students/{student.id}")
    assert profile.status_code == 200, profile.text
    assert profile.json()["program_id"] == str(data["p1"].id)

    listed_p1 = client.get(
        f"{API}/students",
        params={"program_id": str(data["p1"].id), "page_size": 100},
    )
    assert listed_p1.status_code == 200, listed_p1.text
    assert str(student.id) in {item["id"] for item in listed_p1.json()["items"]}

    listed_p2 = client.get(
        f"{API}/students",
        params={"program_id": str(data["p2"].id), "page_size": 100},
    )
    assert listed_p2.status_code == 200, listed_p2.text
    assert str(student.id) not in {item["id"] for item in listed_p2.json()["items"]}

    report = client.get(f"{API}/reports/students")
    assert report.status_code == 200, report.text
    counts = {item["label"]: item["count"] for item in report.json()["by_program"]}
    assert counts.get(data["p1"].name) == 1
    assert counts.get(data["p2"].name, 0) == 0


def test_equal_creation_timestamps_use_the_same_deterministic_order(
    client, db_session
):
    """The resolver, SQL subquery and self-service target agree on ties."""
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag, password=True)
    db_session.commit()

    _login(client)
    first = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id, "PENDING"
    )
    assert (
        client.post(
            f"{API}/students/{student.id}/admissions/{first['id']}/status",
            json={"status": "ADMITTED"},
        ).status_code
        == 200
    )
    second = _create_admission(
        client, student.id, data["later"].id, data["later_o2"].id, "PENDING"
    )
    assert (
        client.post(
            f"{API}/students/{student.id}/admissions/{second['id']}/status",
            json={"status": "ADMITTED"},
        ).status_code
        == 200
    )

    db_session.expire_all()
    first_id = uuid.UUID(first["id"])
    second_id = uuid.UUID(second["id"])
    shared = datetime(2035, 1, 1, tzinfo=UTC)
    first_row = db_session.get(AcademicAdmission, first_id)
    second_row = db_session.get(AcademicAdmission, second_id)
    assert first_row is not None and second_row is not None
    first_row.created_at = shared
    second_row.created_at = shared
    db_session.commit()

    expected_id = max((first_id, second_id), key=lambda value: value.int)
    selected = effective_admission(db_session, student.id)
    assert selected is not None
    assert selected.id == expected_id

    effective = latest_effective_admission_subquery(db_session)
    row = (
        db_session.query(effective.c.admission_id)
        .filter(effective.c.student_id == student.id)
        .one()
    )
    assert row.admission_id == expected_id

    student_user = db_session.get(User, student.user_id)
    assert student_user is not None
    _login(client, student_user.email)
    requested = client.post(
        f"{API}/students/me/admission-changes",
        json={
            "change_type": "PROGRAM_CHANGE",
            "to_program_id": str(data["p3"].id),
        },
    )
    assert requested.status_code == 201, requested.text
    assert requested.json()["admission_id"] == str(expected_id)
