"""Phase 1 admission lifecycle and registration integration.

Synthetic data only. Every test creates its own student, intake and offering, so
the suite never depends on seeded academic records or on historical admissions.

The pytest schema is created with ``Base.metadata.create_all``; the Phase 0
migration installs the lifecycle triggers separately. This module installs the
two triggers the service relies on (history writer and ADMITTED-while-ACTIVE
guard) so the tests exercise the same database contract as production.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.config.settings import get_settings
from app.database.session import engine
from app.models.academic import AcademicPeriod, Major, Program, ProgramOffering
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionStatusHistory,
    AcademicPlacement,
)
from app.models.audit import AuditLog
from app.models.identity import Student, User
from app.schemas.admission import AdmissionCreate, AdmissionTransition, PlacementCreate
from app.schemas.student import StudentOnboard
from app.services.admission import create_admission, transition_admission
from app.services.placement import create_placement
from app.services.student import onboard_student
from app.services.student_academic import current_placement, student_academic_snapshot
from tests.conftest import TestSessionLocal

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session as DBSession

API = "/api/v1"

_TRIGGER_STATEMENTS = (
    """
    CREATE OR REPLACE FUNCTION scu_admission_transition_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        v_actor uuid;
        v_correction boolean;
        v_reason text;
    BEGIN
        v_correction :=
            coalesce(current_setting('scu.admission_correction', true), '') = 'on';

        IF TG_OP = 'INSERT' THEN
            INSERT INTO academic_admission_status_history
                (id, admission_id, from_status, to_status, actor_id, reason,
                 is_correction, corrected_from_recorded_at, created_at)
            VALUES
                (gen_random_uuid(), NEW.id, NULL, NEW.status,
                 NEW.created_by_id, NEW.end_reason, v_correction, NULL, now());
            RETURN NULL;
        END IF;

        IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
            RETURN NULL;
        END IF;

        IF NOT v_correction AND NOT (
               (OLD.status = 'PENDING'
                AND NEW.status IN ('ADMITTED','ACTIVE','CANCELLED'))
            OR (OLD.status = 'ADMITTED'
                AND NEW.status IN ('ACTIVE','CANCELLED'))
            OR (OLD.status = 'ACTIVE'
                AND NEW.status IN ('COMPLETED','WITHDRAWN'))
        ) THEN
            RAISE EXCEPTION 'illegal admission transition % -> %',
                OLD.status, NEW.status;
        END IF;

        v_actor := coalesce(
            nullif(current_setting('scu.actor_id', true), '')::uuid,
            NEW.created_by_id
        );
        v_reason := coalesce(
            nullif(current_setting('scu.correction_reason', true), ''),
            NEW.end_reason
        );

        INSERT INTO academic_admission_status_history
            (id, admission_id, from_status, to_status, actor_id, reason,
             is_correction, corrected_from_recorded_at, created_at)
        VALUES
            (gen_random_uuid(), NEW.id, OLD.status, NEW.status,
             v_actor, v_reason, v_correction,
             CASE WHEN v_correction THEN OLD.ended_at ELSE NULL END, now());
        RETURN NULL;
    END $$;
    """,
    "DROP TRIGGER IF EXISTS trg_admission_transition_guard ON academic_admissions",
    """
    CREATE TRIGGER trg_admission_transition_guard
    AFTER INSERT OR UPDATE ON academic_admissions
    FOR EACH ROW EXECUTE FUNCTION scu_admission_transition_guard();
    """,
    """
    CREATE OR REPLACE FUNCTION scu_admission_admitted_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.status = 'ADMITTED' THEN
            IF EXISTS (
                SELECT 1 FROM academic_admissions a
                 WHERE a.student_id = NEW.student_id
                   AND a.status = 'ACTIVE'
                   AND a.id <> NEW.id
            ) THEN
                RAISE EXCEPTION
                    'student % already has an active admission', NEW.student_id;
            END IF;
        END IF;
        RETURN NEW;
    END $$;
    """,
    "DROP TRIGGER IF EXISTS trg_admission_admitted_guard ON academic_admissions",
    """
    CREATE TRIGGER trg_admission_admitted_guard
    BEFORE INSERT OR UPDATE ON academic_admissions
    FOR EACH ROW EXECUTE FUNCTION scu_admission_admitted_guard();
    """,
)


@pytest.fixture(scope="module", autouse=True)
def admission_triggers():
    with engine.begin() as connection:
        for statement in _TRIGGER_STATEMENTS:
            connection.execute(text(statement))


@pytest.fixture(autouse=True)
def admission_writes(monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", True)


def _login(client: TestClient, email: str = "admin@school.portal") -> None:
    response = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200, response.text


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def _mk_academic(
    db: DBSession,
    *,
    tag: str,
    start: date,
    end: date,
) -> tuple[AcademicPeriod, Program, ProgramOffering]:
    major = Major(code=f"M-{tag}", name=f"Major {tag}")
    db.add(major)
    db.flush()
    program = Program(
        major_id=major.id,
        code=f"PR-{tag}",
        name=f"Program {tag}",
    )
    db.add(program)
    db.flush()
    period = AcademicPeriod(
        code=f"P-{tag}",
        name=f"Intake {tag}",
        start_date=start,
        end_date=end,
    )
    db.add(period)
    db.flush()
    offering = ProgramOffering(
        academic_period_id=period.id,
        program_id=program.id,
        source_id=tag,
        source_key=f"source-{tag}",
        name=f"Offering {tag}",
    )
    db.add(offering)
    db.flush()
    return period, program, offering


def _mk_student(db: DBSession, *, tag: str) -> Student:
    user = User(
        email=f"admission-{tag}@test.local",
        username=f"admission-{tag}",
        hashed_password="not-used",
        full_name=f"Admission {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"ADM-{tag}",
        first_name="Admission",
        last_name=tag,
    )
    db.add(student)
    db.flush()
    return student


def _create(
    client: TestClient,
    student_id,
    intake_id,
    offering_id,
    status: str = "ACTIVE",
):
    return client.post(
        f"{API}/students/{student_id}/admissions",
        json={
            "admission_intake_id": str(intake_id),
            "program_offering_id": str(offering_id),
            "initial_status": status,
        },
    )


def _transition(client: TestClient, student_id, admission_id, status: str, reason=None):
    payload = {"status": status}
    if reason is not None:
        payload["reason"] = reason
    return client.post(
        f"{API}/students/{student_id}/admissions/{admission_id}/status",
        json=payload,
    )


def _place(
    client: TestClient,
    student_id,
    admission_id,
    offering_id,
    *,
    effective_from: date = date(2032, 9, 1),
):
    return client.post(
        f"{API}/students/{student_id}/placements",
        json={
            "admission_id": str(admission_id),
            "program_offering_id": str(offering_id),
            "effective_from": effective_from.isoformat(),
        },
    )


def test_first_active_admission_sets_pointer_projection_history_and_audit(
    client: TestClient, db_session: DBSession
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    period, program, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )

    response = _create(client, student.id, period.id, offering.id, "ACTIVE")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["initial_status"] == "ACTIVE"
    assert body["record_origin"] == "NEW_ADMISSION"
    assert body["verification_status"] == "VERIFIED"
    assert body["activated_at"] is not None
    assert body["verified_at"] is not None
    assert body["admitted_program_id"] == str(program.id)

    db_session.expire_all()
    stored = db_session.get(Student, student.id)
    assert stored.original_admission_id == uuid.UUID(body["id"])
    live = student_academic_snapshot(db_session, student.id)
    assert live.program_id == program.id
    assert live.offering_id == offering.id
    assert live.major_id == program.major_id

    history = (
        db_session.query(AcademicAdmissionStatusHistory)
        .filter(AcademicAdmissionStatusHistory.admission_id == uuid.UUID(body["id"]))
        .all()
    )
    assert len(history) == 1
    assert history[0].from_status is None
    assert history[0].to_status == "ACTIVE"

    audits = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "admission.created",
            AuditLog.entity_id == uuid.UUID(body["id"]),
        )
        .all()
    )
    assert len(audits) == 1


def test_future_admission_is_pending_while_another_is_active(
    client: TestClient, db_session: DBSession
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    first_period, _, first_offering = _mk_academic(
        db_session, tag=f"{tag}a", start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    next_period, _, next_offering = _mk_academic(
        db_session, tag=f"{tag}b", start=date(2033, 2, 1), end=date(2033, 6, 30)
    )

    active = _create(client, student.id, first_period.id, first_offering.id, "ACTIVE")
    assert active.status_code == 201, active.text

    pending = _create(client, student.id, next_period.id, next_offering.id, "PENDING")
    assert pending.status_code == 201, pending.text
    assert pending.json()["status"] == "PENDING"

    db_session.expire_all()
    live = student_academic_snapshot(db_session, student.id)
    assert live.offering_id == first_offering.id

    for refused_status in ("ADMITTED", "ACTIVE"):
        refused = _create(client, student.id, next_period.id, next_offering.id, refused_status)
        # One live episode per intake already exists; the lifecycle refusal is
        # the more specific ADMISSION_MUST_BE_PENDING check.
        assert refused.status_code == 409, refused.text
        assert _error_code(refused) in {
            "ADMISSION_MUST_BE_PENDING",
            "ADMISSION_INTAKE_ALREADY_LIVE",
        }

    admission_id = pending.json()["id"]
    refused_activation = _transition(client, student.id, admission_id, "ACTIVE")
    assert refused_activation.status_code == 409
    assert _error_code(refused_activation) == "ADMISSION_ALREADY_ACTIVE"

    ended = _transition(client, student.id, active.json()["id"], "COMPLETED")
    assert ended.status_code == 200, ended.text
    assert ended.json()["ended_at"] is not None

    activated = _transition(client, student.id, admission_id, "ACTIVE")
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "ACTIVE"

    db_session.expire_all()
    actives = (
        db_session.query(AcademicAdmission)
        .filter(
            AcademicAdmission.student_id == student.id,
            AcademicAdmission.status == "ACTIVE",
        )
        .all()
    )
    assert len(actives) == 1
    assert actives[0].id == uuid.UUID(admission_id)


def test_pending_to_admitted_is_refused_while_another_is_active(
    client: TestClient, db_session: DBSession
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    first_period, _, first_offering = _mk_academic(
        db_session, tag=f"{tag}a", start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    next_period, _, next_offering = _mk_academic(
        db_session, tag=f"{tag}b", start=date(2033, 2, 1), end=date(2033, 6, 30)
    )

    assert (
        _create(client, student.id, first_period.id, first_offering.id, "ACTIVE").status_code == 201
    )
    pending = _create(client, student.id, next_period.id, next_offering.id, "PENDING")
    assert pending.status_code == 201

    refused = _transition(client, student.id, pending.json()["id"], "ADMITTED")
    assert refused.status_code == 409
    assert _error_code(refused) == "ADMISSION_MUST_BE_PENDING"

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(pending.json()["id"]))
    assert stored.status == "PENDING"


def test_earlier_intake_is_refused_while_active(client: TestClient, db_session: DBSession):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    active_period, _, active_offering = _mk_academic(
        db_session, tag=f"{tag}a", start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    earlier_period, _, earlier_offering = _mk_academic(
        db_session, tag=f"{tag}b", start=date(2031, 9, 1), end=date(2031, 12, 20)
    )

    assert (
        _create(client, student.id, active_period.id, active_offering.id, "ACTIVE").status_code
        == 201
    )

    refused = _create(client, student.id, earlier_period.id, earlier_offering.id, "PENDING")
    assert refused.status_code == 409
    assert _error_code(refused) == "ADMISSION_INTAKE_PRECEDES_ACTIVE_EPISODE"


def test_duplicate_live_episode_for_one_intake_is_refused(
    client: TestClient, db_session: DBSession
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    period, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )

    assert _create(client, student.id, period.id, offering.id, "ACTIVE").status_code == 201
    refused = _create(client, student.id, period.id, offering.id, "PENDING")
    assert refused.status_code == 409
    assert _error_code(refused) == "ADMISSION_INTAKE_ALREADY_LIVE"


def test_transition_rules_and_reason_requirements(client: TestClient, db_session: DBSession):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    period, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )

    pending = _create(client, student.id, period.id, offering.id, "PENDING")
    assert pending.status_code == 201, pending.text

    skipped = _transition(client, student.id, pending.json()["id"], "COMPLETED")
    assert skipped.status_code == 409
    assert _error_code(skipped) == "ADMISSION_TRANSITION_NOT_ALLOWED"

    no_reason = _transition(client, student.id, pending.json()["id"], "CANCELLED")
    assert no_reason.status_code == 422
    assert _error_code(no_reason) == "ADMISSION_REASON_REQUIRED"

    admitted = _transition(client, student.id, pending.json()["id"], "ADMITTED")
    assert admitted.status_code == 200, admitted.text

    activated = _transition(client, student.id, pending.json()["id"], "ACTIVE")
    assert activated.status_code == 200, activated.text
    assert activated.json()["activated_at"] is not None

    withdrawn = _transition(
        client, student.id, pending.json()["id"], "WITHDRAWN", "Student withdrew"
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["ended_at"] is not None
    assert withdrawn.json()["end_reason"] == "Student withdrew"

    terminal = _transition(client, student.id, pending.json()["id"], "ACTIVE")
    assert terminal.status_code == 409
    assert _error_code(terminal) == "ADMISSION_TERMINAL"

    db_session.expire_all()
    history = (
        db_session.query(AcademicAdmissionStatusHistory)
        .filter(AcademicAdmissionStatusHistory.admission_id == uuid.UUID(pending.json()["id"]))
        .order_by(AcademicAdmissionStatusHistory.created_at)
        .all()
    )
    assert [row.to_status for row in history] == [
        "PENDING",
        "ADMITTED",
        "ACTIVE",
        "WITHDRAWN",
    ]


def test_permissions_and_write_flag(client: TestClient, db_session: DBSession, monkeypatch):
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    period, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )

    _login(client, "teacher@school.portal")
    teacher = _create(client, student.id, period.id, offering.id, "PENDING")
    assert teacher.status_code == 403
    assert client.get(f"{API}/students/{student.id}/admissions").status_code == 403

    _login(client, "student@school.portal")
    self_service = _create(client, student.id, period.id, offering.id, "PENDING")
    assert self_service.status_code == 403

    _login(client, "management@school.portal")
    allowed = _create(client, student.id, period.id, offering.id, "PENDING")
    assert allowed.status_code == 201, allowed.text

    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", False)
    _login(client, "admin@school.portal")
    disabled = _create(client, student.id, period.id, offering.id, "ACTIVE")
    assert disabled.status_code == 409
    assert _error_code(disabled) == "ADMISSIONS_WRITE_DISABLED"


def test_onboarding_records_episode_and_rolls_back_on_refusal(
    client: TestClient, db_session: DBSession
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    period, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    other_period, _, _ = _mk_academic(
        db_session, tag=f"{tag}-other", start=date(2033, 2, 1), end=date(2033, 6, 30)
    )

    created = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": f"ONB-{tag}",
            "first_name": "Onboard",
            "last_name": tag,
            "email": f"onboard-{tag}@example.com",
            "program_offering_id": str(offering.id),
            "admission_intake_id": str(period.id),
            "initial_admission_status": "ACTIVE",
        },
    )
    assert created.status_code == 201, created.text
    student_id = created.json()["student"]["id"]
    assert created.json()["student"]["program_offering_id"] == str(offering.id)

    episodes = (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.student_id == uuid.UUID(student_id))
        .all()
    )
    assert len(episodes) == 1
    assert episodes[0].status == "ACTIVE"
    assert episodes[0].activated_at is not None

    placements = (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == uuid.UUID(student_id))
        .all()
    )
    assert len(placements) == 1
    assert placements[0].admission_id == episodes[0].id
    assert placements[0].program_offering_id == offering.id
    assert placements[0].ended_at is None
    assert placements[0].is_earlier_intake_placement is False

    admin = db_session.query(User).filter(User.email == "admin@school.portal").one()
    audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "admission.created",
            AuditLog.entity_id == episodes[0].id,
        )
        .one()
    )
    assert audit.actor_id == admin.id
    assert audit.context["onboarding"] is True
    placement_audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "academic.placement.created",
            AuditLog.entity_id == placements[0].id,
        )
        .one()
    )
    assert placement_audit.actor_id == admin.id
    assert placement_audit.context["onboarding"] is True

    refused = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": f"BAD-{tag}",
            "first_name": "Bad",
            "last_name": tag,
            "email": f"bad-{tag}@example.com",
            "program_offering_id": str(offering.id),
            "admission_intake_id": str(other_period.id),
            "initial_admission_status": "ACTIVE",
        },
    )
    assert refused.status_code == 422, refused.text
    assert _error_code(refused) == "ADMISSION_OFFERING_INTAKE_MISMATCH"
    assert db_session.query(Student).filter(Student.student_id == f"BAD-{tag}").first() is None
    assert db_session.query(User).filter(User.email == f"bad-{tag}@example.com").first() is None


def test_onboarding_requires_explicit_admitted_or_active_status(
    client: TestClient, db_session: DBSession
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    period, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )

    base_payload = {
        "first_name": "Status",
        "last_name": tag,
        "program_offering_id": str(offering.id),
        "admission_intake_id": str(period.id),
    }
    omitted = client.post(
        f"{API}/students/onboard",
        json={
            **base_payload,
            "student_id": f"NOSTATUS-{tag}",
            "email": f"nostatus-{tag}@example.com",
        },
    )
    assert omitted.status_code == 422, omitted.text
    assert _error_code(omitted) == "VALIDATION_ERROR"

    pending = client.post(
        f"{API}/students/onboard",
        json={
            **base_payload,
            "student_id": f"PENDING-{tag}",
            "email": f"pending-{tag}@example.com",
            "initial_admission_status": "PENDING",
        },
    )
    assert pending.status_code == 422, pending.text
    assert _error_code(pending) == "VALIDATION_ERROR"

    for student_number, email in (
        (f"NOSTATUS-{tag}", f"nostatus-{tag}@example.com"),
        (f"PENDING-{tag}", f"pending-{tag}@example.com"),
    ):
        assert (
            db_session.query(Student).filter(Student.student_id == student_number).first() is None
        )
        assert db_session.query(User).filter(User.email == email).first() is None


def test_onboarding_accepts_explicit_admitted_status(client: TestClient, db_session: DBSession):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    period, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )

    created = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": f"ADMITTED-{tag}",
            "first_name": "Admitted",
            "last_name": tag,
            "email": f"admitted-{tag}@example.com",
            "program_offering_id": str(offering.id),
            "admission_intake_id": str(period.id),
            "initial_admission_status": "ADMITTED",
        },
    )
    assert created.status_code == 201, created.text
    student_id = uuid.UUID(created.json()["student"]["id"])

    episode = (
        db_session.query(AcademicAdmission).filter(AcademicAdmission.student_id == student_id).one()
    )
    assert episode.status == "ADMITTED"
    assert episode.initial_status == "ADMITTED"
    assert episode.activated_at is None


def test_onboarding_audit_failure_rolls_back_registration(db_session: DBSession, monkeypatch):
    tag = uuid.uuid4().hex[:8]
    period, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    actor = db_session.query(User).filter(User.email == "admin@school.portal").one()
    data = StudentOnboard(
        student_id=f"AUDITFAIL-{tag}",
        first_name="Audit",
        last_name=tag,
        email=f"auditfail-{tag}@example.com",
        program_offering_id=offering.id,
        admission_intake_id=period.id,
        initial_admission_status="ACTIVE",
    )

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("app.services.student.record_audit", fail_audit)

    with pytest.raises(RuntimeError):
        onboard_student(db_session, data, actor=actor)

    assert (
        db_session.query(Student).filter(Student.student_id == f"AUDITFAIL-{tag}").first() is None
    )
    assert (
        db_session.query(User).filter(User.email == f"auditfail-{tag}@example.com").first() is None
    )
    assert (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.admission_intake_id == period.id)
        .first()
        is None
    )


def test_flag_off_onboarding_refuses_an_offering(
    client: TestClient, db_session: DBSession, monkeypatch
):
    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", False)
    _login(client)
    tag = uuid.uuid4().hex[:8]
    _, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )

    created = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": f"LEG-{tag}",
            "first_name": "Legacy",
            "last_name": tag,
            "email": f"legacy-{tag}@example.com",
            "program_offering_id": str(offering.id),
            "initial_admission_status": "ACTIVE",
        },
    )
    assert created.status_code == 409, created.text
    assert created.json()["error"]["code"] == "ADMISSIONS_WRITE_DISABLED"
    assert (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.admission_intake_id == offering.academic_period_id)
        .count()
        == 0
    )


def test_database_refuses_raw_second_active_and_admitted_while_active(
    client: TestClient, db_session: DBSession
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    first_period, _, first_offering = _mk_academic(
        db_session, tag=f"{tag}a", start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    next_period, _, next_offering = _mk_academic(
        db_session, tag=f"{tag}b", start=date(2033, 2, 1), end=date(2033, 6, 30)
    )

    assert (
        _create(client, student.id, first_period.id, first_offering.id, "ACTIVE").status_code == 201
    )
    pending = _create(client, student.id, next_period.id, next_offering.id, "PENDING")
    assert pending.status_code == 201
    pending_id = uuid.UUID(pending.json()["id"])

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            text(
                "UPDATE academic_admissions "
                "SET status = 'ACTIVE', activated_at = now() WHERE id = :id"
            ),
            {"id": pending_id},
        )

    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            text("UPDATE academic_admissions SET status = 'ADMITTED' WHERE id = :id"),
            {"id": pending_id},
        )

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, pending_id)
    assert stored is not None
    assert stored.status == "PENDING"


@pytest.mark.parametrize("target_status", ["COMPLETED", "WITHDRAWN"])
def test_terminal_transition_closes_the_associated_placement(
    client: TestClient, db_session: DBSession, target_status: str
):
    """Both terminal paths close only the episode's own current placement."""
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    period, program, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    admission = _create(client, student.id, period.id, offering.id, "ACTIVE")
    assert admission.status_code == 201, admission.text
    admission_body = admission.json()
    placement = _place(client, student.id, admission_body["id"], offering.id)
    assert placement.status_code == 201, placement.text
    placement_id = uuid.UUID(placement.json()["id"])

    transition = _transition(
        client,
        student.id,
        admission_body["id"],
        target_status,
        "Student ended the episode" if target_status == "WITHDRAWN" else None,
    )
    assert transition.status_code == 200, transition.text

    db_session.expire_all()
    episode = db_session.get(AcademicAdmission, uuid.UUID(admission_body["id"]))
    stored_placement = db_session.get(AcademicPlacement, placement_id)
    assert episode is not None and episode.status == target_status
    assert episode.ended_at is not None
    assert stored_placement is not None
    assert stored_placement.ended_at is not None
    assert stored_placement.ended_at == episode.ended_at
    assert stored_placement.admission_id == episode.id
    assert stored_placement.program_offering_id == offering.id
    assert current_placement(db_session, student.id) is None

    snapshot = student_academic_snapshot(db_session, student.id)
    assert snapshot.placement is None
    assert snapshot.offering_id is None
    assert snapshot.program_id == program.id

    history = (
        db_session.query(AcademicAdmissionStatusHistory)
        .filter(AcademicAdmissionStatusHistory.admission_id == episode.id)
        .all()
    )
    assert target_status in [row.to_status for row in history]
    audits = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "admission.status_changed",
            AuditLog.entity_id == episode.id,
        )
        .all()
    )
    assert len(audits) == 1


def test_terminal_closure_preserves_placement_history(
    client: TestClient, db_session: DBSession
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    period, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    admission = _create(client, student.id, period.id, offering.id, "ACTIVE")
    assert admission.status_code == 201, admission.text
    admission_id = uuid.UUID(admission.json()["id"])
    placement = _place(client, student.id, admission_id, offering.id)
    assert placement.status_code == 201, placement.text
    placement_id = uuid.UUID(placement.json()["id"])

    db_session.expire_all()
    before = db_session.get(AcademicPlacement, placement_id)
    assert before is not None
    original = {
        "student_id": before.student_id,
        "admission_id": before.admission_id,
        "academic_period_id": before.academic_period_id,
        "program_offering_id": before.program_offering_id,
        "effective_from": before.effective_from,
        "created_by_id": before.created_by_id,
    }

    transition = _transition(client, student.id, admission_id, "COMPLETED")
    assert transition.status_code == 200, transition.text

    db_session.expire_all()
    after = db_session.get(AcademicPlacement, placement_id)
    assert after is not None
    assert after.ended_at is not None
    for field, value in original.items():
        assert getattr(after, field) == value

    history = client.get(f"{API}/students/{student.id}/placements")
    assert history.status_code == 200, history.text
    payload = history.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(placement_id)
    assert payload["items"][0]["is_current"] is False
    assert payload["items"][0]["ended_at"] is not None


def test_audit_failure_rolls_back_admission_and_placement_closure(
    client: TestClient, db_session: DBSession, monkeypatch
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    period, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    admission = _create(client, student.id, period.id, offering.id, "ACTIVE")
    assert admission.status_code == 201, admission.text
    admission_id = uuid.UUID(admission.json()["id"])
    placement = _place(client, student.id, admission_id, offering.id)
    assert placement.status_code == 201, placement.text
    placement_id = uuid.UUID(placement.json()["id"])

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("app.routers.students.record_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        _transition(client, student.id, admission_id, "COMPLETED")

    db_session.expire_all()
    episode = db_session.get(AcademicAdmission, admission_id)
    stored_placement = db_session.get(AcademicPlacement, placement_id)
    assert episode is not None and episode.status == "ACTIVE"
    assert episode.ended_at is None
    assert stored_placement is not None and stored_placement.ended_at is None
    history = (
        db_session.query(AcademicAdmissionStatusHistory)
        .filter(AcademicAdmissionStatusHistory.admission_id == admission_id)
        .all()
    )
    assert [row.to_status for row in history] == ["ACTIVE"]
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "admission.status_changed",
            AuditLog.entity_id == admission_id,
        )
        .count()
        == 0
    )


def test_subsequent_admission_can_create_a_new_placement(
    client: TestClient, db_session: DBSession
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    first_period, _, first_offering = _mk_academic(
        db_session, tag=f"{tag}a", start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    second_period, _, second_offering = _mk_academic(
        db_session, tag=f"{tag}b", start=date(2033, 2, 1), end=date(2033, 6, 30)
    )
    first = _create(client, student.id, first_period.id, first_offering.id, "ACTIVE")
    assert first.status_code == 201, first.text
    first_admission_id = uuid.UUID(first.json()["id"])
    first_placement = _place(
        client, student.id, first_admission_id, first_offering.id
    )
    assert first_placement.status_code == 201, first_placement.text
    first_placement_id = uuid.UUID(first_placement.json()["id"])
    assert (
        _transition(client, student.id, first_admission_id, "COMPLETED").status_code
        == 200
    )

    second = _create(client, student.id, second_period.id, second_offering.id, "ACTIVE")
    assert second.status_code == 201, second.text
    second_admission_id = uuid.UUID(second.json()["id"])
    second_placement = _place(
        client,
        student.id,
        second_admission_id,
        second_offering.id,
        effective_from=date(2033, 2, 1),
    )
    assert second_placement.status_code == 201, second_placement.text
    second_placement_id = uuid.UUID(second_placement.json()["id"])

    db_session.expire_all()
    assert db_session.get(AcademicPlacement, first_placement_id).ended_at is not None
    current = current_placement(db_session, student.id)
    assert current is not None
    assert current.id == second_placement_id
    assert current.admission_id == second_admission_id
    snapshot = student_academic_snapshot(db_session, student.id)
    assert snapshot.placement is not None
    assert snapshot.offering_id == second_offering.id


def test_corrected_live_episode_does_not_inherit_a_terminal_placement(
    client: TestClient, db_session: DBSession, monkeypatch
):
    monkeypatch.setattr(get_settings(), "ADMISSION_CORRECTIONS_ENABLED", True)
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    first_period, _, first_offering = _mk_academic(
        db_session, tag=f"{tag}a", start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    second_period, _, second_offering = _mk_academic(
        db_session, tag=f"{tag}b", start=date(2033, 2, 1), end=date(2033, 6, 30)
    )
    first = _create(client, student.id, first_period.id, first_offering.id, "ACTIVE")
    assert first.status_code == 201, first.text
    first_admission_id = uuid.UUID(first.json()["id"])
    first_placement = _place(
        client, student.id, first_admission_id, first_offering.id
    )
    assert first_placement.status_code == 201, first_placement.text
    assert (
        _transition(client, student.id, first_admission_id, "COMPLETED").status_code
        == 200
    )

    second = _create(client, student.id, second_period.id, second_offering.id, "ACTIVE")
    assert second.status_code == 201, second.text
    second_admission_id = uuid.UUID(second.json()["id"])
    second_placement = _place(
        client,
        student.id,
        second_admission_id,
        second_offering.id,
        effective_from=date(2033, 2, 1),
    )
    assert second_placement.status_code == 201, second_placement.text
    second_placement_id = uuid.UUID(second_placement.json()["id"])
    withdrawn = _transition(
        client,
        student.id,
        second_admission_id,
        "WITHDRAWN",
        "Student withdrew from the later episode",
    )
    assert withdrawn.status_code == 200, withdrawn.text

    # Simulate a legacy open row on a terminal episode. The read model must
    # still ignore it rather than letting the newer terminated episode supply
    # the current offering after the older admission is corrected back to ACTIVE.
    db_session.expire_all()
    stale = db_session.get(AcademicPlacement, second_placement_id)
    stale.ended_at = None
    db_session.commit()

    corrected = client.post(
        f"{API}/students/{student.id}/admissions/{first_admission_id}/corrections/status",
        json={"target_status": "ACTIVE", "reason": "Recorded completion was mistaken"},
    )
    assert corrected.status_code == 200, corrected.text

    db_session.expire_all()
    assert current_placement(db_session, student.id) is None
    snapshot = student_academic_snapshot(db_session, student.id)
    assert snapshot.placement is None
    assert snapshot.offering_id == first_offering.id
    assert snapshot.offering_id != second_offering.id


def test_repeated_terminal_transitions_do_not_corrupt_placement_history(
    client: TestClient, db_session: DBSession
):
    _login(client)
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    period, _, offering = _mk_academic(
        db_session, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
    )
    admission = _create(client, student.id, period.id, offering.id, "ACTIVE")
    assert admission.status_code == 201, admission.text
    admission_id = uuid.UUID(admission.json()["id"])
    placement = _place(client, student.id, admission_id, offering.id)
    assert placement.status_code == 201, placement.text
    placement_id = uuid.UUID(placement.json()["id"])
    assert _transition(client, student.id, admission_id, "COMPLETED").status_code == 200

    db_session.expire_all()
    ended_at = db_session.get(AcademicPlacement, placement_id).ended_at
    assert ended_at is not None

    repeated = _transition(client, student.id, admission_id, "COMPLETED")
    assert repeated.status_code == 409
    assert _error_code(repeated) == "ADMISSION_TERMINAL"
    repeated_other = _transition(
        client, student.id, admission_id, "WITHDRAWN", "A second terminal event"
    )
    assert repeated_other.status_code == 409
    assert _error_code(repeated_other) == "ADMISSION_TERMINAL"

    db_session.expire_all()
    placements = (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == student.id)
        .all()
    )
    assert len(placements) == 1
    assert placements[0].id == placement_id
    assert placements[0].ended_at == ended_at
    history = (
        db_session.query(AcademicAdmissionStatusHistory)
        .filter(AcademicAdmissionStatusHistory.admission_id == admission_id)
        .all()
    )
    assert [row.to_status for row in history].count("COMPLETED") == 1
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "admission.status_changed",
            AuditLog.entity_id == admission_id,
        )
        .count()
        == 1
    )


def test_concurrent_placement_and_terminal_transition_leave_no_open_placement():
    """A placement write racing a termination still ends with no open row."""
    tag = uuid.uuid4().hex[:8]
    setup = TestSessionLocal()
    try:
        student = _mk_student(setup, tag=tag)
        period, program, offering = _mk_academic(
            setup, tag=tag, start=date(2032, 9, 1), end=date(2032, 12, 20)
        )
        replacement = ProgramOffering(
            academic_period_id=period.id,
            program_id=program.id,
            source_id=f"{tag}-replacement",
            source_key=f"source-{tag}-replacement",
            name=f"Replacement offering {tag}",
        )
        setup.add(replacement)
        setup.flush()
        actor = setup.query(User).filter(User.email == "admin@school.portal").one()
        admission = create_admission(
            setup,
            student,
            AdmissionCreate(
                admission_intake_id=period.id,
                program_offering_id=offering.id,
                initial_status="ACTIVE",
            ),
            actor,
        )
        first_placement = create_placement(
            setup,
            student,
            PlacementCreate(
                admission_id=admission.id,
                program_offering_id=offering.id,
                effective_from=date(2032, 9, 1),
            ),
            actor,
            can_authorize_earlier=False,
        )[0]
        student_id = student.id
        user_id = student.user_id
        actor_id = actor.id
        admission_id = admission.id
        period_id = period.id
        offering_id = offering.id
        replacement_id = replacement.id
        program_id = program.id
        major_id = program.major_id
        first_placement_id = first_placement.id
        setup.commit()
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def transition_worker():
        db = TestSessionLocal()
        try:
            barrier.wait(timeout=10)
            transition_admission(
                db,
                db.get(Student, student_id),
                admission_id,
                AdmissionTransition(status="COMPLETED"),
                db.get(User, actor_id),
            )
            db.commit()
            outcomes.append("COMPLETED")
        except ValueError as exc:
            db.rollback()
            outcomes.append(str(exc))
        except Exception as exc:  # pragma: no cover - diagnostic
            db.rollback()
            outcomes.append(type(exc).__name__)
        finally:
            db.close()

    def placement_worker():
        db = TestSessionLocal()
        try:
            barrier.wait(timeout=10)
            create_placement(
                db,
                db.get(Student, student_id),
                PlacementCreate(
                    admission_id=admission_id,
                    program_offering_id=replacement_id,
                    effective_from=date(2032, 9, 1),
                ),
                db.get(User, actor_id),
                can_authorize_earlier=False,
            )
            db.commit()
            outcomes.append("PLACEMENT_CREATED")
        except ValueError as exc:
            db.rollback()
            outcomes.append(str(exc))
        except Exception as exc:  # pragma: no cover - diagnostic
            db.rollback()
            outcomes.append(type(exc).__name__)
        finally:
            db.close()

    threads = [
        threading.Thread(target=transition_worker),
        threading.Thread(target=placement_worker),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert "COMPLETED" in outcomes, outcomes
    assert set(outcomes) <= {
        "COMPLETED",
        "PLACEMENT_CREATED",
        "PLACEMENT_REQUIRES_ADMITTED_EPISODE",
    }, outcomes

    check = TestSessionLocal()
    try:
        episode = check.get(AcademicAdmission, admission_id)
        placements = (
            check.query(AcademicPlacement)
            .filter(AcademicPlacement.student_id == student_id)
            .all()
        )
        assert episode is not None and episode.status == "COMPLETED"
        assert placements
        assert all(row.admission_id == admission_id for row in placements)
        assert all(row.ended_at is not None for row in placements)
        assert first_placement_id in {row.id for row in placements}
    finally:
        check.close()

    cleanup = TestSessionLocal()
    disabled_trigger = False
    try:
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
                text("ALTER TABLE students DISABLE TRIGGER trg_original_admission_once")
            )
            disabled_trigger = True
        cleanup.execute(
            text("UPDATE students SET original_admission_id = NULL WHERE id = :id"),
            {"id": student_id},
        )
        cleanup.query(AcademicAdmissionStatusHistory).filter(
            AcademicAdmissionStatusHistory.admission_id == admission_id
        ).delete(synchronize_session=False)
        cleanup.query(AcademicPlacement).filter(
            AcademicPlacement.student_id == student_id
        ).delete(synchronize_session=False)
        cleanup.query(AcademicAdmission).filter(
            AcademicAdmission.id == admission_id
        ).delete(synchronize_session=False)
        cleanup.query(Student).filter(Student.id == student_id).delete(
            synchronize_session=False
        )
        cleanup.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        cleanup.query(ProgramOffering).filter(
            ProgramOffering.id.in_([offering_id, replacement_id])
        ).delete(synchronize_session=False)
        cleanup.query(Program).filter(Program.id == program_id).delete(
            synchronize_session=False
        )
        cleanup.query(Major).filter(Major.id == major_id).delete(
            synchronize_session=False
        )
        cleanup.query(AcademicPeriod).filter(AcademicPeriod.id == period_id).delete(
            synchronize_session=False
        )
        cleanup.commit()
    except Exception:
        cleanup.rollback()
        raise
    finally:
        if disabled_trigger:
            cleanup.execute(
                text("ALTER TABLE students ENABLE TRIGGER trg_original_admission_once")
            )
            cleanup.commit()
        cleanup.close()
