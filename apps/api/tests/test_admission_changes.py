"""Phase 4 programme-change workflow: same episode, one approver, no rewrite.

All data is synthetic. The tests create their own student, intakes, programmes
and offerings so they never depend on demo records or historical admissions.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date

import pytest
from sqlalchemy import text

from app.auth.service import hash_password
from app.config.settings import get_settings
from app.models.academic import AcademicPeriod, Major, Program, ProgramOffering
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionChange,
    AcademicAdmissionStatusHistory,
    AcademicPlacement,
)
from app.models.audit import AuditLog
from app.models.identity import Student, User
from app.schemas.admission import (
    AdmissionChangeCreate,
    AdmissionChangeReview,
    AdmissionCreate,
)
from app.services.admission import create_admission
from app.services.admission_change import (
    request_admission_change,
    review_admission_change,
)
from app.services.student_academic import student_academic_snapshot
from tests.conftest import TestSessionLocal

API = "/api/v1"


@pytest.fixture(autouse=True)
def phase_four_flags(monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", True)
    monkeypatch.setattr(get_settings(), "ADMISSION_CHANGE_REQUESTS_ENABLED", True)
    monkeypatch.setattr(get_settings(), "ADMISSION_CORRECTIONS_ENABLED", True)


def _login(client, email: str = "admin@school.portal") -> None:
    response = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200, response.text


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def _mk_student(db, tag: str, *, password: bool = False) -> Student:
    user = User(
        email=f"phase4-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"phase4-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123") if password else "not-used",
        full_name=f"Phase Four {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"P4-{tag}-{uuid.uuid4().hex[:6]}",
        first_name="Phase",
        last_name=tag,
    )
    db.add(student)
    db.flush()
    return student


def _mk_program(db, tag: str) -> Program:
    major = Major(code=f"M4-{tag}", name=f"Phase Four Major {tag}")
    db.add(major)
    db.flush()
    program = Program(
        major_id=major.id,
        code=f"P4PR-{tag}",
        name=f"Phase Four Program {tag}",
    )
    db.add(program)
    db.flush()
    return program


def _mk_period(db, tag: str, start: date, end: date) -> AcademicPeriod:
    period = AcademicPeriod(
        code=f"P4-{tag}",
        name=f"Phase Four Intake {tag}",
        start_date=start,
        end_date=end,
        status="ACTIVE",
    )
    db.add(period)
    db.flush()
    return period


def _mk_offering(
    db, tag: str, period: AcademicPeriod, program: Program
) -> ProgramOffering:
    offering = ProgramOffering(
        academic_period_id=period.id,
        program_id=program.id,
        source_id=f"p4-{tag}",
        source_key=f"phase4-{tag}-{uuid.uuid4().hex[:8]}",
        name=f"Phase Four Offering {tag}",
    )
    db.add(offering)
    db.flush()
    return offering


def _scenario(db, tag: str) -> dict:
    p1 = _mk_program(db, f"{tag}-one")
    p2 = _mk_program(db, f"{tag}-two")
    p3 = _mk_program(db, f"{tag}-three")
    intake = _mk_period(db, f"{tag}-intake", date(2032, 9, 1), date(2032, 12, 20))
    later = _mk_period(db, f"{tag}-later", date(2033, 2, 1), date(2033, 6, 30))
    earlier = _mk_period(
        db, f"{tag}-earlier", date(2031, 9, 1), date(2031, 12, 20)
    )
    return {
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "intake": intake,
        "later": later,
        "earlier": earlier,
        "o1": _mk_offering(db, f"{tag}-o1", intake, p1),
        "o2": _mk_offering(db, f"{tag}-o2", intake, p2),
        "o3": _mk_offering(db, f"{tag}-o3", intake, p3),
        "later_o1": _mk_offering(db, f"{tag}-lo1", later, p1),
        "later_o2": _mk_offering(db, f"{tag}-lo2", later, p2),
        "earlier_o1": _mk_offering(db, f"{tag}-eo1", earlier, p1),
    }


def _create_admission(
    client, student_id, period_id, offering_id, status: str = "ACTIVE"
):
    response = client.post(
        f"{API}/students/{student_id}/admissions",
        json={
            "admission_intake_id": str(period_id),
            "program_offering_id": str(offering_id),
            "initial_status": status,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _request_change(
    client,
    student_id,
    admission_id,
    *,
    to_program_id=None,
    to_offering_id=None,
    change_type="PROGRAM_CHANGE",
    reason=None,
    proposed_data=None,
):
    payload = {"change_type": change_type}
    if to_program_id is not None:
        payload["to_program_id"] = str(to_program_id)
    if to_offering_id is not None:
        payload["to_program_offering_id"] = str(to_offering_id)
    if reason is not None:
        payload["reason"] = reason
    if proposed_data is not None:
        payload["proposed_data"] = proposed_data
    return client.post(
        f"{API}/students/{student_id}/admissions/{admission_id}/changes",
        json=payload,
    )


def _review(client, change_id, decision="APPROVE", reason=None):
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return client.post(
        f"{API}/academic/admission-changes/{change_id}/review", json=payload
    )


def test_management_approves_programme_change_with_offering_atomically(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )

    requested = _request_change(
        client,
        student.id,
        admission["id"],
        to_program_id=data["p2"].id,
        to_offering_id=data["o2"].id,
        reason="Approved same-intake programme transfer",
    )
    assert requested.status_code == 201, requested.text
    requested_body = requested.json()
    assert requested_body["status"] == "PENDING"
    assert requested_body["from_program_id"] == str(data["p1"].id)
    assert requested_body["to_program_id"] == str(data["p2"].id)

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert stored.current_program_id == data["p1"].id
    assert (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == student.id)
        .count()
        == 0
    )

    _login(client, "management@school.portal")
    reviewed = _review(client, requested_body["id"])
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["status"] == "APPROVED"
    assert body["reviewed_by_name"] == "Management User"

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert stored.status == "ACTIVE"
    assert stored.admitted_program_id == data["p1"].id
    assert stored.admitted_program_offering_id == data["o1"].id
    assert stored.current_program_id == data["p2"].id
    assert stored.current_program_changed_at is not None

    placement = (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == student.id)
        .one()
    )
    assert placement.program_offering_id == data["o2"].id
    assert placement.ended_at is None
    assert placement.admission_id == uuid.UUID(admission["id"])

    assert (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.student_id == student.id)
        .count()
        == 1
    )

    audits = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(requested_body["id"]))
        .order_by(AuditLog.created_at)
        .all()
    )
    assert [row.action for row in audits] == [
        "academic.admission.change_requested",
        "academic.admission.change_approved",
    ]


def test_admin_alone_can_approve_and_no_second_approval_state_exists(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client, "management@school.portal")
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    requested = _request_change(
        client, student.id, admission["id"], to_program_id=data["p2"].id
    )
    assert requested.status_code == 201, requested.text

    _login(client, "admin@school.portal")
    reviewed = _review(client, requested.json()["id"])
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["status"] == "APPROVED"
    assert body["reviewed_by_name"] == "Admin User"
    assert "second_approval" not in body
    assert "approval_state" not in body


def test_only_one_pending_programme_change_per_admission(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    first = _request_change(
        client, student.id, admission["id"], to_program_id=data["p2"].id
    )
    assert first.status_code == 201, first.text

    second = _request_change(
        client, student.id, admission["id"], to_program_id=data["p3"].id
    )
    assert second.status_code == 409, second.text
    assert _error_code(second) == "CHANGE_REQUEST_PENDING_EXISTS"


def test_invalid_programme_targets_are_refused_without_state_change(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )

    same = _request_change(
        client, student.id, admission["id"], to_program_id=data["p1"].id
    )
    assert same.status_code == 422
    assert _error_code(same) == "PROGRAM_CHANGE_SAME_PROGRAM"

    wrong_offering = _request_change(
        client,
        student.id,
        admission["id"],
        to_program_id=data["p3"].id,
        to_offering_id=data["o2"].id,
    )
    assert wrong_offering.status_code == 422
    assert _error_code(wrong_offering) == "PROGRAM_CHANGE_OFFERING_MISMATCH"

    other_intake = _request_change(
        client,
        student.id,
        admission["id"],
        to_program_id=data["p2"].id,
        to_offering_id=data["later_o2"].id,
    )
    assert other_intake.status_code == 422
    assert _error_code(other_intake) == "PROGRAM_CHANGE_OFFERING_INTAKE_MISMATCH"

    missing = _request_change(client, student.id, admission["id"])
    assert missing.status_code == 422
    assert _error_code(missing) == "PROGRAM_CHANGE_TARGET_REQUIRED"

    db_session.expire_all()
    assert (
        db_session.query(AcademicAdmissionChange)
        .filter(AcademicAdmissionChange.admission_id == uuid.UUID(admission["id"]))
        .count()
        == 0
    )
    stored = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert stored.current_program_id == data["p1"].id


def test_self_approval_is_refused(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    requested = _request_change(
        client, student.id, admission["id"], to_program_id=data["p2"].id
    )
    assert requested.status_code == 201, requested.text

    refused = _review(client, requested.json()["id"])
    assert refused.status_code == 403, refused.text
    assert _error_code(refused) == "SELF_APPROVAL_FORBIDDEN"

    db_session.expire_all()
    stored = db_session.get(
        AcademicAdmissionChange, uuid.UUID(requested.json()["id"])
    )
    assert stored.status == "PENDING"
    admission_row = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert admission_row.current_program_id == data["p1"].id


def test_teacher_and_student_cannot_review(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    requested = _request_change(
        client, student.id, admission["id"], to_program_id=data["p2"].id
    )
    assert requested.status_code == 201
    change_id = requested.json()["id"]

    for email in ("teacher@school.portal", "student@school.portal"):
        _login(client, email)
        refused = _review(client, change_id)
        assert refused.status_code == 403, (email, refused.text)


def test_programme_change_on_pending_episode_keeps_it_pending(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    active = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    pending = _create_admission(
        client, student.id, data["later"].id, data["later_o1"].id, "PENDING"
    )
    pending_with_offering = _request_change(
        client,
        student.id,
        pending["id"],
        to_program_id=data["p2"].id,
        to_offering_id=data["later_o2"].id,
    )
    assert pending_with_offering.status_code == 409
    assert _error_code(pending_with_offering) == "PLACEMENT_REQUIRES_ADMITTED_EPISODE"

    requested = _request_change(
        client, student.id, pending["id"], to_program_id=data["p2"].id
    )
    assert requested.status_code == 201, requested.text

    _login(client, "management@school.portal")
    approved = _review(client, requested.json()["id"])
    assert approved.status_code == 200, approved.text

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(pending["id"]))
    assert stored.status == "PENDING"
    assert stored.current_program_id == data["p2"].id
    assert stored.admitted_program_id == data["p1"].id

    # A pending episode does not drive the live academic view.
    live = student_academic_snapshot(db_session, student.id)
    assert live.program_id == data["p1"].id
    assert live.offering_id == data["o1"].id

    active_row = db_session.get(AcademicAdmission, uuid.UUID(active["id"]))
    assert active_row.current_program_id == data["p1"].id


def test_second_episode_same_intake_different_programme_is_refused(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    _create_admission(client, student.id, data["intake"].id, data["o1"].id)

    refused = client.post(
        f"{API}/students/{student.id}/admissions",
        json={
            "admission_intake_id": str(data["intake"].id),
            "program_offering_id": str(data["o2"].id),
            "initial_status": "PENDING",
        },
    )
    assert refused.status_code == 409, refused.text
    assert _error_code(refused) == "PROGRAM_CHANGE_NOT_NEW_ADMISSION"


def test_after_terminal_admission_a_new_episode_is_allowed_and_history_survives(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    first = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    change = _request_change(
        client, student.id, first["id"], to_program_id=data["p2"].id
    )
    assert change.status_code == 201
    _login(client, "management@school.portal")
    assert _review(client, change.json()["id"]).status_code == 200

    _login(client)
    completed = client.post(
        f"{API}/students/{student.id}/admissions/{first['id']}/status",
        json={"status": "COMPLETED"},
    )
    assert completed.status_code == 200, completed.text

    second = _create_admission(
        client, student.id, data["later"].id, data["later_o2"].id, "ACTIVE"
    )
    assert second["admitted_program_id"] == str(data["p2"].id)

    db_session.expire_all()
    old = db_session.get(AcademicAdmission, uuid.UUID(first["id"]))
    assert old.status == "COMPLETED"
    assert old.admitted_program_id == data["p1"].id
    assert old.current_program_id == data["p2"].id
    assert (
        db_session.query(AcademicAdmissionChange)
        .filter(AcademicAdmissionChange.admission_id == old.id)
        .count()
        == 1
    )
    assert (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.student_id == student.id)
        .count()
        == 2
    )


def test_earlier_intake_placement_creates_no_episode_or_programme_change(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    placed = client.post(
        f"{API}/students/{student.id}/placements",
        json={
            "admission_id": admission["id"],
            "program_offering_id": str(data["earlier_o1"].id),
            "effective_from": "2032-09-01",
            "reason": "Approved catch-up teaching placement",
        },
    )
    assert placed.status_code == 201, placed.text
    assert placed.json()["is_earlier_intake_placement"] is True

    db_session.expire_all()
    assert (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.student_id == student.id)
        .count()
        == 1
    )
    assert (
        db_session.query(AcademicAdmissionChange)
        .filter(AcademicAdmissionChange.admission_id == uuid.UUID(admission["id"]))
        .count()
        == 0
    )


def test_approved_history_reconstructs_admitted_then_two_changes(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    first = _request_change(
        client, student.id, admission["id"], to_program_id=data["p2"].id
    )
    assert first.status_code == 201
    _login(client, "management@school.portal")
    assert _review(client, first.json()["id"]).status_code == 200

    _login(client)
    second = _request_change(
        client, student.id, admission["id"], to_program_id=data["p3"].id
    )
    assert second.status_code == 201, second.text
    _login(client, "management@school.portal")
    assert _review(client, second.json()["id"]).status_code == 200

    _login(client)
    history = client.get(f"{API}/students/{student.id}/admission-changes")
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["total"] == 2
    ordered = sorted(body["items"], key=lambda item: item["requested_at"])
    assert [row["to_program_id"] for row in ordered] == [
        str(data["p2"].id),
        str(data["p3"].id),
    ]

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert stored.admitted_program_id == data["p1"].id
    assert stored.current_program_id == data["p3"].id


def test_audit_failure_rolls_back_programme_approval(
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
    requested = _request_change(
        client,
        student.id,
        admission["id"],
        to_program_id=data["p2"].id,
        to_offering_id=data["o2"].id,
    )
    assert requested.status_code == 201

    import app.routers.admission_changes as change_router

    real_record_audit = change_router.record_audit

    def fail_audit(*args, **kwargs):
        if kwargs.get("action") == "academic.admission.change_approved":
            raise RuntimeError("audit unavailable")
        return real_record_audit(*args, **kwargs)

    monkeypatch.setattr(change_router, "record_audit", fail_audit)

    _login(client, "management@school.portal")
    with pytest.raises(RuntimeError, match="audit unavailable"):
        _review(client, requested.json()["id"])

    db_session.expire_all()
    stored_change = db_session.get(
        AcademicAdmissionChange, uuid.UUID(requested.json()["id"])
    )
    assert stored_change.status == "PENDING"
    assert stored_change.reviewed_at is None
    stored = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert stored.current_program_id == data["p1"].id
    assert (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == student.id)
        .count()
        == 0
    )


def test_student_self_service_creates_pending_request_not_a_direct_write(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag, password=True)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    student_user = db_session.get(User, student.user_id)

    _login(client, student_user.email)
    own_admissions = client.get(f"{API}/students/me/admission-episodes")
    assert own_admissions.status_code == 200, own_admissions.text
    assert own_admissions.json()["items"][0]["id"] == admission["id"]

    # The legacy self-service body is retired outright. The dedicated request
    # endpoint below is the only supported programme-change path.
    major_only = client.post(
        f"{API}/students/me/academic", json={"major_id": str(data["p2"].major_id)}
    )
    assert major_only.status_code == 409, major_only.text
    assert _error_code(major_only) == "PLACEMENT_DIRECT_WRITE_RETIRED"
    assert client.get(f"{API}/students/me/admission-changes").json()["total"] == 0

    requested = client.post(
        f"{API}/students/me/admission-changes",
        json={
            "change_type": "PROGRAM_CHANGE",
            "to_program_id": str(data["p2"].id),
            "reason": "Student requests the other programme",
        },
    )
    assert requested.status_code == 201, requested.text
    assert requested.json()["status"] == "PENDING"
    assert requested.json()["requested_by_id"] == str(student.user_id)

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert stored.current_program_id == data["p1"].id
    assert student_academic_snapshot(db_session, student.id).program_id == data["p1"].id

    own_changes = client.get(f"{API}/students/me/admission-changes")
    assert own_changes.status_code == 200, own_changes.text
    assert own_changes.json()["total"] == 1
    assert own_changes.json()["items"][0]["status"] == "PENDING"

    _login(client, "management@school.portal")
    approved = _review(client, requested.json()["id"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"


def test_placement_change_creates_no_episode_and_leaves_programme_history(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    requested = _request_change(
        client,
        student.id,
        admission["id"],
        change_type="PLACEMENT_CHANGE",
        to_offering_id=data["o2"].id,
        reason="Approved move to the other same-intake offering",
    )
    assert requested.status_code == 201, requested.text
    _login(client, "management@school.portal")
    assert _review(client, requested.json()["id"]).status_code == 200

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert stored.admitted_program_id == data["p1"].id
    assert stored.current_program_id == data["p1"].id
    assert (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.student_id == student.id)
        .count()
        == 1
    )
    placement = (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == student.id)
        .one()
    )
    assert placement.program_offering_id == data["o2"].id


def test_requested_earlier_intake_placement_uses_the_same_episode(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client, student.id, data["intake"].id, data["o1"].id
    )
    requested = _request_change(
        client,
        student.id,
        admission["id"],
        change_type="EARLIER_INTAKE_PLACEMENT",
        to_offering_id=data["earlier_o1"].id,
        reason="Approved catch-up teaching placement",
    )
    assert requested.status_code == 201, requested.text
    _login(client, "management@school.portal")
    assert _review(client, requested.json()["id"]).status_code == 200

    db_session.expire_all()
    assert (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.student_id == student.id)
        .count()
        == 1
    )
    placement = (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == student.id)
        .one()
    )
    assert placement.program_offering_id == data["earlier_o1"].id
    assert placement.is_earlier_intake_placement is True
    assert placement.authorization_reason == "Approved catch-up teaching placement"


def test_withdrawal_and_status_correction_are_episode_decisions(client, db_session):
    tag = uuid.uuid4().hex[:7]
    data = _scenario(db_session, tag)
    withdrawn_student = _mk_student(db_session, f"{tag}-withdraw")
    corrected_student = _mk_student(db_session, f"{tag}-correct")
    db_session.commit()

    _login(client)
    active = _create_admission(
        client,
        withdrawn_student.id,
        data["intake"].id,
        data["o1"].id,
    )
    withdrawal = _request_change(
        client,
        withdrawn_student.id,
        active["id"],
        change_type="WITHDRAWAL",
        reason="Student confirmed withdrawal",
    )
    assert withdrawal.status_code == 201, withdrawal.text
    _login(client, "management@school.portal")
    assert _review(client, withdrawal.json()["id"]).status_code == 200

    _login(client)
    pending = _create_admission(
        client,
        corrected_student.id,
        data["later"].id,
        data["later_o1"].id,
        "PENDING",
    )
    correction = _request_change(
        client,
        corrected_student.id,
        pending["id"],
        change_type="STATUS_CORRECTION",
        proposed_data={"status": "ADMITTED"},
        reason="Correcting the recorded admission decision",
    )
    assert correction.status_code == 201, correction.text
    _login(client, "management@school.portal")
    assert _review(client, correction.json()["id"]).status_code == 200

    db_session.expire_all()
    withdrawn = db_session.get(AcademicAdmission, uuid.UUID(active["id"]))
    corrected = db_session.get(AcademicAdmission, uuid.UUID(pending["id"]))
    assert withdrawn.status == "WITHDRAWN"
    assert corrected.status == "ADMITTED"
    assert (
        db_session.query(AcademicAdmission)
        .filter(
            AcademicAdmission.student_id.in_(
                [withdrawn_student.id, corrected_student.id]
            )
        )
        .count()
        == 2
    )


def test_concurrent_review_yields_exactly_one_decision():
    """Two real sessions race on one request; the row lock serialises them."""
    tag = uuid.uuid4().hex[:7]
    setup = TestSessionLocal()
    try:
        data = _scenario(setup, tag)
        student = _mk_student(setup, tag)
        requester = User(
            email=f"phase4-requester-{tag}@test.local",
            username=f"phase4-requester-{tag}",
            hashed_password="not-used",
            full_name="Phase Four Requester",
            is_active=True,
        )
        admin = setup.query(User).filter(User.email == "admin@school.portal").one()
        manager = (
            setup.query(User).filter(User.email == "management@school.portal").one()
        )
        setup.add(requester)
        setup.flush()
        admission = create_admission(
            setup,
            student,
            AdmissionCreate(
                admission_intake_id=data["intake"].id,
                program_offering_id=data["o1"].id,
                initial_status="ACTIVE",
            ),
            requester,
        )
        change = request_admission_change(
            setup,
            student,
            admission.id,
            AdmissionChangeCreate(
                change_type="PROGRAM_CHANGE", to_program_id=data["p2"].id
            ),
            requester,
        )
        setup.commit()
        change_id = change.id
        admission_id = admission.id
        student_id = student.id
        student_user_id = student.user_id
        requester_id = requester.id
        program_ids = [data["p1"].id, data["p2"].id, data["p3"].id]
        offering_ids = [
            data[key].id
            for key in ("o1", "o2", "o3", "later_o1", "later_o2", "earlier_o1")
        ]
        period_ids = [data["intake"].id, data["later"].id, data["earlier"].id]
        major_ids = [
            data["p1"].major_id,
            data["p2"].major_id,
            data["p3"].major_id,
        ]
        actor_ids = [admin.id, manager.id]
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker(actor_id):
        db = TestSessionLocal()
        try:
            actor = db.get(User, actor_id)
            barrier.wait(timeout=10)
            review_admission_change(
                db,
                change_id,
                AdmissionChangeReview(decision="APPROVE"),
                actor,
                can_authorize_earlier=True,
            )
            db.commit()
            outcomes.append("APPROVED")
        except ValueError as exc:
            db.rollback()
            outcomes.append(str(exc))
        except Exception as exc:  # pragma: no cover - diagnostic
            db.rollback()
            outcomes.append(type(exc).__name__)
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(actor_id,)) for actor_id in actor_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    try:
        assert sorted(outcomes) == ["APPROVED", "CHANGE_ALREADY_REVIEWED"]
    finally:
        # This test uses independent sessions, so its committed rows are not
        # covered by the fixture's savepoint rollback. Remove them explicitly
        # so later tests never see a synthetic student or offering.
        cleanup = TestSessionLocal()
        try:
            # A migration-created immutability trigger refuses clearing the
            # pointer. This test owns committed rows outside the fixture
            # savepoint, so disable the trigger only for this cleanup and
            # restore it before committing. create_all-based test schemas have
            # no trigger, so only alter it when it exists.
            has_pointer_trigger = bool(
                cleanup.execute(
                    text(
                        "SELECT 1 FROM pg_trigger t JOIN pg_class c "
                        "ON c.oid = t.tgrelid WHERE c.relname = 'students' "
                        "AND t.tgname = 'trg_original_admission_once'"
                    )
                ).scalar()
            )
            if has_pointer_trigger:
                cleanup.execute(
                    text(
                        "ALTER TABLE students DISABLE TRIGGER "
                        "trg_original_admission_once"
                    )
                )
            cleanup.query(AcademicAdmissionChange).filter(
                AcademicAdmissionChange.admission_id == admission_id
            ).delete(synchronize_session=False)
            cleanup.query(AcademicPlacement).filter(
                AcademicPlacement.student_id == student_id
            ).delete(synchronize_session=False)
            cleanup.query(AcademicAdmissionStatusHistory).filter(
                AcademicAdmissionStatusHistory.admission_id.in_(
                    cleanup.query(AcademicAdmission.id).filter(
                        AcademicAdmission.student_id == student_id
                    )
                )
            ).delete(synchronize_session=False)
            # ``students.original_admission_id`` and the episode's student FK
            # form a cycle; break the student pointer before deleting either.
            cleanup.query(Student).filter(Student.id == student_id).update(
                {Student.original_admission_id: None}, synchronize_session=False
            )
            cleanup.query(AcademicAdmission).filter(
                AcademicAdmission.student_id == student_id
            ).delete(synchronize_session=False)
            cleanup.query(Student).filter(Student.id == student_id).delete(
                synchronize_session=False
            )
            cleanup.query(User).filter(
                User.id.in_([requester_id, student_user_id])
            ).delete(synchronize_session=False)
            cleanup.query(ProgramOffering).filter(
                ProgramOffering.id.in_(offering_ids)
            ).delete(synchronize_session=False)
            cleanup.query(AcademicPeriod).filter(
                AcademicPeriod.id.in_(period_ids)
            ).delete(synchronize_session=False)
            cleanup.query(Program).filter(Program.id.in_(program_ids)).delete(
                synchronize_session=False
            )
            cleanup.query(Major).filter(Major.id.in_(major_ids)).delete(
                synchronize_session=False
            )
            if has_pointer_trigger:
                cleanup.execute(
                    text(
                        "ALTER TABLE students ENABLE TRIGGER "
                        "trg_original_admission_once"
                    )
                )
            cleanup.commit()
        finally:
            cleanup.close()
