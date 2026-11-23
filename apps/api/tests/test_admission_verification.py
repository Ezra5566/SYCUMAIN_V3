"""Phase 2 migration verification against synthetic students.

These tests exercise the database contract, not only the service: the
append-only acts table, slot-state checks, the original-admission trigger and
the audit trail all participate.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config.settings import get_settings
from app.database.session import engine
from app.models.academic import AcademicPeriod, Major, Program, ProgramOffering
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionVerificationAct,
    StudentOriginalAdmissionHistory,
)
from app.models.audit import AuditLog
from app.models.identity import Student, User
from app.services import admission_verification

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session as DBSession

API = "/api/v1"

_TRIGGER_STATEMENTS = (
    """
    CREATE OR REPLACE FUNCTION scu_admission_transition_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            INSERT INTO academic_admission_status_history
                (id, admission_id, from_status, to_status, actor_id, reason,
                 is_correction, corrected_from_recorded_at, created_at)
            VALUES
                (gen_random_uuid(), NEW.id, NULL, NEW.status,
                 NEW.created_by_id, NEW.end_reason, false, NULL, now());
            RETURN NULL;
        END IF;

        IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
            RETURN NULL;
        END IF;

        INSERT INTO academic_admission_status_history
            (id, admission_id, from_status, to_status, actor_id, reason,
             is_correction, corrected_from_recorded_at, created_at)
        VALUES
            (gen_random_uuid(), NEW.id, OLD.status, NEW.status,
             NEW.created_by_id, NEW.end_reason, false, NULL, now());
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
    """
    CREATE OR REPLACE FUNCTION scu_original_admission_once()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        v_flag text;
    BEGIN
        IF NEW.original_admission_id IS NULL
           AND OLD.original_admission_id IS NOT NULL THEN
            RAISE EXCEPTION 'the original admission pointer cannot be cleared';
        END IF;

        IF OLD.original_admission_id IS NOT NULL
           AND NEW.original_admission_id IS DISTINCT FROM OLD.original_admission_id THEN
            v_flag := coalesce(
                current_setting('scu.original_admission_correction', true), '');

            IF v_flag <> 'on' THEN
                RAISE EXCEPTION
                    'pointer changes require the correction workflow';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM student_original_admission_history h
                 WHERE h.student_id = NEW.id
                   AND h.previous_admission_id = OLD.original_admission_id
                   AND h.new_admission_id = NEW.original_admission_id
            ) THEN
                RAISE EXCEPTION
                    'pointer correction requires a history row in the same transaction';
            END IF;
        END IF;

        RETURN NEW;
    END $$;
    """,
    "DROP TRIGGER IF EXISTS trg_original_admission_once ON students",
    """
    CREATE TRIGGER trg_original_admission_once
    BEFORE UPDATE OF original_admission_id ON students
    FOR EACH ROW EXECUTE FUNCTION scu_original_admission_once();
    """,
)


@pytest.fixture(scope="module", autouse=True)
def verification_triggers():
    with engine.begin() as connection:
        for statement in _TRIGGER_STATEMENTS:
            connection.execute(text(statement))


@pytest.fixture(autouse=True)
def phase_two_flags(monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", True)
    monkeypatch.setattr(get_settings(), "ADMISSION_MIGRATION_CONSOLE_ENABLED", True)
    monkeypatch.setattr(get_settings(), "ADMISSION_CORRECTIONS_ENABLED", True)


def _login(client: TestClient, email: str) -> None:
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
) -> tuple[AcademicPeriod, ProgramOffering]:
    major = Major(code=f"M-{tag}", name=f"Major {tag}")
    db.add(major)
    db.flush()
    program = Program(major_id=major.id, code=f"PR-{tag}", name=f"Program {tag}")
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
    return period, offering


def _mk_student(db: DBSession, *, tag: str) -> Student:
    user = User(
        email=f"migration-{tag}@test.local",
        username=f"migration-{tag}",
        hashed_password="not-used",
        full_name=f"Migration {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"MIG-{tag}",
        first_name="Migration",
        last_name=tag,
    )
    db.add(student)
    db.flush()
    return student


def _candidate(client: TestClient, student_id, intake_id, offering_id):
    return client.post(
        f"{API}/students/{student_id}/admissions/migrated",
        json={
            "admission_intake_id": str(intake_id),
            "program_offering_id": str(offering_id),
        },
    )


def _confirm(client: TestClient, student_id, admission_id, slot: str, reference="MIG-1"):
    return client.post(
        f"{API}/students/{student_id}/admissions/{admission_id}/confirm/{slot}",
        json={
            "evidence_type": "ADMISSION_LETTER",
            "evidence_reference": reference,
            "evidence_note": "Synthetic evidence",
        },
    )


def _revoke(client: TestClient, student_id, admission_id, slot: str, reason="Evidence invalid"):
    return client.post(
        f"{API}/students/{student_id}/admissions/{admission_id}/confirm/{slot}/revoke",
        json={"reason": reason},
    )


def _acts(client: TestClient, student_id, admission_id):
    response = client.get(
        f"{API}/students/{student_id}/admissions/{admission_id}/verification-acts"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _fresh_student(db: DBSession, student_id):
    db.expire_all()
    return db.get(Student, student_id)


def _make_candidate(
    client: TestClient,
    db: DBSession,
    *,
    tag: str,
    start=date(2027, 9, 1),
    end=date(2028, 1, 31),
) -> tuple[Student, AcademicPeriod, ProgramOffering, dict]:
    student = _mk_student(db, tag=tag)
    period, offering = _mk_academic(db, tag=tag, start=start, end=end)
    db.commit()
    _login(client, "management@school.portal")
    response = _candidate(client, student.id, period.id, offering.id)
    assert response.status_code == 201, response.text
    return student, period, offering, response.json()


def test_management_confirmation_alone_is_not_authoritative(
    client: TestClient, db_session: DBSession
):
    student, _, _, body = _make_candidate(
        client, db_session, tag=uuid.uuid4().hex[:8]
    )

    response = _confirm(client, student.id, body["id"], "MANAGEMENT")

    assert response.status_code == 200, response.text
    assert response.json()["verification_status"] == "UNVERIFIED"
    assert response.json()["management_confirmation_state"] == "CONFIRMED"
    assert response.json()["admin_confirmation_state"] == "NONE"
    assert _fresh_student(db_session, student.id).original_admission_id is None
    assert len(_acts(client, student.id, body["id"])) == 1


def test_admin_confirmation_alone_is_not_authoritative(
    client: TestClient, db_session: DBSession
):
    student, _, _, body = _make_candidate(
        client, db_session, tag=uuid.uuid4().hex[:8]
    )
    _login(client, "admin@school.portal")

    response = _confirm(client, student.id, body["id"], "ADMIN")

    assert response.status_code == 200, response.text
    assert response.json()["verification_status"] == "UNVERIFIED"
    assert response.json()["admin_confirmation_state"] == "CONFIRMED"
    assert response.json()["management_confirmation_state"] == "NONE"
    assert _fresh_student(db_session, student.id).original_admission_id is None


def test_both_confirmations_verify_and_set_pointer_once(
    client: TestClient, db_session: DBSession
):
    tag = uuid.uuid4().hex[:8]
    student, _, _, body = _make_candidate(client, db_session, tag=tag)

    first = _confirm(client, student.id, body["id"], "MANAGEMENT")
    assert first.status_code == 200, first.text
    _login(client, "admin@school.portal")
    second = _confirm(client, student.id, body["id"], "ADMIN")

    assert second.status_code == 200, second.text
    verified = second.json()
    assert verified["verification_status"] == "VERIFIED"
    assert verified["verified_at"] is not None
    assert verified["management_confirmed_by_id"] != verified["admin_confirmed_by_id"]
    stored = _fresh_student(db_session, student.id)
    assert stored.original_admission_id == uuid.UUID(body["id"])

    acts = _acts(client, student.id, body["id"])
    assert [act["slot"] for act in acts] == ["MANAGEMENT", "ADMIN"]
    assert all(act["action"] == "CONFIRM" for act in acts)
    assert all(act["actor_name"] for act in acts)
    assert all(act["candidate_intake_name"] for act in acts)
    assert all(act["candidate_program_name"] for act in acts)

    audits = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == uuid.UUID(body["id"]))
        .all()
    )
    actions = {entry.action for entry in audits}
    assert "academic.admission.migration.management_confirmed" in actions
    assert "academic.admission.migration.admin_confirmed" in actions
    assert "academic.admission.migration.verified" in actions
    pointer_audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "academic.admission.migration.pointer_set",
            AuditLog.entity_id == student.id,
        )
        .one()
    )
    assert pointer_audit.context["admission_id"] == body["id"]


def test_duplicate_slot_confirmation_is_rejected(
    client: TestClient, db_session: DBSession
):
    student, _, _, body = _make_candidate(
        client, db_session, tag=uuid.uuid4().hex[:8]
    )
    assert _confirm(client, student.id, body["id"], "MANAGEMENT").status_code == 200

    duplicate = _confirm(client, student.id, body["id"], "MANAGEMENT")

    assert duplicate.status_code == 409
    assert _error_code(duplicate) == "SLOT_ALREADY_CONFIRMED"
    assert len(_acts(client, student.id, body["id"])) == 1


def test_unauthorized_roles_and_wrong_slot_are_refused(
    client: TestClient, db_session: DBSession
):
    student, _, _, body = _make_candidate(
        client, db_session, tag=uuid.uuid4().hex[:8]
    )

    _login(client, "teacher@school.portal")
    teacher = _confirm(client, student.id, body["id"], "MANAGEMENT")
    assert teacher.status_code == 403

    _login(client, "student@school.portal")
    learner = _confirm(client, student.id, body["id"], "MANAGEMENT")
    assert learner.status_code == 403

    _login(client, "management@school.portal")
    wrong_slot = _confirm(client, student.id, body["id"], "ADMIN")
    assert wrong_slot.status_code == 403
    assert wrong_slot.json()["error"]["code"] == "FORBIDDEN"
    assert len(_acts(client, student.id, body["id"])) == 0


def test_same_actor_cannot_fill_both_slots(
    client: TestClient, db_session: DBSession
):
    student, _, _, body = _make_candidate(
        client, db_session, tag=uuid.uuid4().hex[:8]
    )
    _login(client, "admin@school.portal")

    first = _confirm(client, student.id, body["id"], "MANAGEMENT")
    assert first.status_code == 200, first.text
    second = _confirm(client, student.id, body["id"], "ADMIN")

    assert second.status_code == 403
    assert _error_code(second) == "CONFIRMATION_ACTOR_MUST_DIFFER"
    assert len(_acts(client, student.id, body["id"])) == 1
    assert _fresh_student(db_session, student.id).original_admission_id is None


def test_revocation_retains_confirmation_history_and_pointer(
    client: TestClient, db_session: DBSession
):
    student, _, _, body = _make_candidate(
        client, db_session, tag=uuid.uuid4().hex[:8]
    )
    assert _confirm(client, student.id, body["id"], "MANAGEMENT").status_code == 200
    _login(client, "admin@school.portal")
    verified = _confirm(client, student.id, body["id"], "ADMIN")
    assert verified.status_code == 200, verified.text
    pointer = _fresh_student(db_session, student.id).original_admission_id
    verified_at = verified.json()["verified_at"]
    admin_actor = verified.json()["admin_confirmed_by_id"]

    revoked = _revoke(client, student.id, body["id"], "ADMIN", "Letter withdrawn")

    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["verification_status"] == "REVOKED"
    assert revoked.json()["admin_confirmation_state"] == "REVOKED"
    assert revoked.json()["admin_confirmed_by_id"] == admin_actor
    assert revoked.json()["verified_at"] == verified_at
    stored = _fresh_student(db_session, student.id)
    assert stored.original_admission_id == pointer

    acts = _acts(client, student.id, body["id"])
    assert len(acts) == 3
    assert acts[1]["action"] == "CONFIRM"
    assert acts[2]["action"] == "REVOKE"
    assert acts[2]["revocation_reason"] == "Letter withdrawn"
    assert acts[2]["resulting_verification_status"] == "REVOKED"

    reconfirmed = _confirm(client, student.id, body["id"], "ADMIN")
    assert reconfirmed.status_code == 200, reconfirmed.text
    assert reconfirmed.json()["verification_status"] == "VERIFIED"
    assert len(_acts(client, student.id, body["id"])) == 4
    assert _fresh_student(db_session, student.id).original_admission_id == pointer

    blank = _revoke(client, student.id, body["id"], "ADMIN", "   ")
    assert blank.status_code == 422
    assert _error_code(blank) == "REVOCATION_REASON_REQUIRED"


def test_mismatched_confirmations_dispute_and_do_not_set_pointer(
    client: TestClient, db_session: DBSession
):
    tag = uuid.uuid4().hex[:8]
    student, _, _, body = _make_candidate(client, db_session, tag=tag)
    assert _confirm(client, student.id, body["id"], "MANAGEMENT").status_code == 200

    second_period, second_offering = _mk_academic(
        db_session,
        tag=f"{tag}-alt",
        start=date(2026, 9, 1),
        end=date(2027, 1, 31),
    )
    db_session.commit()
    _login(client, "admin@school.portal")
    changed = client.patch(
        f"{API}/students/{student.id}/admissions/{body['id']}/migrated",
        json={
            "admission_intake_id": str(second_period.id),
            "program_offering_id": str(second_offering.id),
        },
    )
    assert changed.status_code == 200, changed.text

    disputed = _confirm(client, student.id, body["id"], "ADMIN")

    assert disputed.status_code == 200, disputed.text
    assert disputed.json()["verification_status"] == "DISPUTED"
    assert _fresh_student(db_session, student.id).original_admission_id is None
    acts = _acts(client, student.id, body["id"])
    assert len(acts) == 2
    assert acts[0]["candidate_intake_id"] != acts[1]["candidate_intake_id"]
    audits = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "academic.admission.migration.disputed",
            AuditLog.entity_id == uuid.UUID(body["id"]),
        )
        .all()
    )
    assert len(audits) == 1

    # A dispute is resolved deliberately: revoke one slot, correct the
    # candidate to the other slot's snapshot, then confirm it again.
    _login(client, "management@school.portal")
    revoked = _revoke(
        client, student.id, body["id"], "MANAGEMENT", "Correcting candidate"
    )
    assert revoked.status_code == 200, revoked.text
    _login(client, "admin@school.portal")
    corrected = client.patch(
        f"{API}/students/{student.id}/admissions/{body['id']}/migrated",
        json={
            "admission_intake_id": str(second_period.id),
            "program_offering_id": str(second_offering.id),
        },
    )
    assert corrected.status_code == 200, corrected.text
    _login(client, "management@school.portal")
    resolved = _confirm(client, student.id, body["id"], "MANAGEMENT")
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["verification_status"] == "VERIFIED"
    assert _fresh_student(db_session, student.id).original_admission_id == uuid.UUID(
        body["id"]
    )
    assert len(_acts(client, student.id, body["id"])) == 4


def test_earlier_verified_admission_refuses_to_move_pointer(
    client: TestClient, db_session: DBSession
):
    tag = uuid.uuid4().hex[:8]
    student, _, _, later_body = _make_candidate(
        client,
        db_session,
        tag=tag,
        start=date(2028, 9, 1),
        end=date(2029, 1, 31),
    )
    assert _confirm(client, student.id, later_body["id"], "MANAGEMENT").status_code == 200
    _login(client, "admin@school.portal")
    assert _confirm(client, student.id, later_body["id"], "ADMIN").status_code == 200
    fixed_pointer = _fresh_student(db_session, student.id).original_admission_id

    earlier_period, earlier_offering = _mk_academic(
        db_session,
        tag=f"{tag}-e",
        start=date(2027, 9, 1),
        end=date(2028, 1, 31),
    )
    db_session.commit()
    earlier = _candidate(client, student.id, earlier_period.id, earlier_offering.id)
    assert earlier.status_code == 201, earlier.text
    earlier_id = earlier.json()["id"]
    _login(client, "management@school.portal")
    assert _confirm(client, student.id, earlier_id, "MANAGEMENT").status_code == 200
    _login(client, "admin@school.portal")
    conflict = _confirm(client, student.id, earlier_id, "ADMIN")

    assert conflict.status_code == 409
    assert _error_code(conflict) == "ORIGINAL_ADMISSION_ORDER_CONFLICT"
    assert _fresh_student(db_session, student.id).original_admission_id == fixed_pointer
    db_session.expire_all()
    earlier_stored = db_session.get(AcademicAdmission, uuid.UUID(earlier_id))
    assert earlier_stored.verification_status == "VERIFIED"


def test_pointer_correction_is_admin_only_and_requires_verified_target(
    client: TestClient, db_session: DBSession
):
    tag = uuid.uuid4().hex[:8]
    student, _, _, first_body = _make_candidate(client, db_session, tag=tag)
    assert _confirm(client, student.id, first_body["id"], "MANAGEMENT").status_code == 200
    _login(client, "admin@school.portal")
    assert _confirm(client, student.id, first_body["id"], "ADMIN").status_code == 200

    later_period, later_offering = _mk_academic(
        db_session,
        tag=f"{tag}-later",
        start=date(2028, 2, 1),
        end=date(2028, 6, 30),
    )
    db_session.commit()
    later = _candidate(client, student.id, later_period.id, later_offering.id)
    assert later.status_code == 201, later.text
    later_id = later.json()["id"]
    _login(client, "management@school.portal")
    assert _confirm(client, student.id, later_id, "MANAGEMENT").status_code == 200
    _login(client, "admin@school.portal")
    assert _confirm(client, student.id, later_id, "ADMIN").status_code == 200

    # The pointer is set once; later verification does not move it.
    assert (
        _fresh_student(db_session, student.id).original_admission_id
        == uuid.UUID(first_body["id"])
    )

    _login(client, "management@school.portal")
    forbidden = client.post(
        f"{API}/students/{student.id}/original-admission/correction",
        json={"new_admission_id": later_id, "reason": "Wrong original intake"},
    )
    assert forbidden.status_code == 403

    _login(client, "admin@school.portal")
    corrected = client.post(
        f"{API}/students/{student.id}/original-admission/correction",
        json={
            "new_admission_id": later_id,
            "reason": "Register proves later intake",
            "evidence_reference": "REG-2028",
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["previous_admission_id"] == first_body["id"]
    stored = _fresh_student(db_session, student.id)
    assert stored.original_admission_id == uuid.UUID(later_id)
    history = (
        db_session.query(StudentOriginalAdmissionHistory)
        .filter(StudentOriginalAdmissionHistory.student_id == student.id)
        .all()
    )
    assert len(history) == 1
    assert history[0].new_admission_id == uuid.UUID(later_id)

    unverified_period, unverified_offering = _mk_academic(
        db_session,
        tag=f"{tag}-u",
        start=date(2029, 2, 1),
        end=date(2029, 6, 30),
    )
    db_session.commit()
    unverified = _candidate(
        client, student.id, unverified_period.id, unverified_offering.id
    )
    assert unverified.status_code == 201, unverified.text
    refused = client.post(
        f"{API}/students/{student.id}/original-admission/correction",
        json={
            "new_admission_id": unverified.json()["id"],
            "reason": "Should not be accepted",
        },
    )
    assert refused.status_code == 409
    assert _error_code(refused) == "POINTER_TARGET_NOT_VERIFIED"

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE students SET original_admission_id = NULL WHERE id = :id"),
            {"id": student.id},
        )
    db_session.rollback()


def test_queue_filters_permissions_and_outstanding_slots(
    client: TestClient, db_session: DBSession, monkeypatch
):
    tags = [uuid.uuid4().hex[:8] for _ in range(4)]

    # UNVERIFIED
    unverified_student, _, _, unverified_body = _make_candidate(
        client, db_session, tag=f"u{tags[0]}"
    )

    # VERIFIED
    verified_student, _, _, verified_body = _make_candidate(
        client, db_session, tag=f"v{tags[1]}"
    )
    assert (
        _confirm(client, verified_student.id, verified_body["id"], "MANAGEMENT").status_code
        == 200
    )
    _login(client, "admin@school.portal")
    assert (
        _confirm(client, verified_student.id, verified_body["id"], "ADMIN").status_code
        == 200
    )

    # REVOKED
    revoked_student, _, _, revoked_body = _make_candidate(
        client, db_session, tag=f"r{tags[2]}"
    )
    assert _confirm(client, revoked_student.id, revoked_body["id"], "MANAGEMENT").status_code == 200
    _login(client, "admin@school.portal")
    assert _confirm(client, revoked_student.id, revoked_body["id"], "ADMIN").status_code == 200
    assert _revoke(client, revoked_student.id, revoked_body["id"], "ADMIN").status_code == 200

    # DISPUTED
    disputed_tag = f"d{tags[3]}"
    disputed_student, _, _, disputed_body = _make_candidate(
        client, db_session, tag=disputed_tag
    )
    assert (
        _confirm(client, disputed_student.id, disputed_body["id"], "MANAGEMENT").status_code
        == 200
    )
    other_period, other_offering = _mk_academic(
        db_session,
        tag=f"{disputed_tag}x",
        start=date(2026, 2, 1),
        end=date(2026, 6, 30),
    )
    db_session.commit()
    _login(client, "admin@school.portal")
    changed = client.patch(
        f"{API}/students/{disputed_student.id}/admissions/{disputed_body['id']}/migrated",
        json={
            "admission_intake_id": str(other_period.id),
            "program_offering_id": str(other_offering.id),
        },
    )
    assert changed.status_code == 200, changed.text
    assert _confirm(client, disputed_student.id, disputed_body["id"], "ADMIN").status_code == 200

    _login(client, "management@school.portal")
    queue = client.get(f"{API}/admission-verification/queue")
    assert queue.status_code == 200, queue.text
    assert queue.json()["total"] == 4
    by_status = {item["verification_status"]: item for item in queue.json()["items"]}
    assert set(by_status) == {"UNVERIFIED", "VERIFIED", "REVOKED", "DISPUTED"}
    assert by_status["UNVERIFIED"]["outstanding_slots"] == ["MANAGEMENT", "ADMIN"]
    assert by_status["VERIFIED"]["outstanding_slots"] == []
    assert by_status["VERIFIED"]["is_original_admission"] is True
    assert by_status["REVOKED"]["outstanding_slots"] == ["ADMIN"]
    assert by_status["DISPUTED"]["outstanding_slots"] == []

    for status in ("UNVERIFIED", "VERIFIED", "REVOKED", "DISPUTED"):
        filtered = client.get(
            f"{API}/admission-verification/queue",
            params={"verification_status": status},
        )
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["verification_status"] == status

    paged = client.get(
        f"{API}/admission-verification/queue", params={"page": 1, "page_size": 2}
    )
    assert paged.status_code == 200
    assert len(paged.json()["items"]) == 2
    assert paged.json()["total"] == 4

    search = client.get(
        f"{API}/admission-verification/queue",
        params={"search": unverified_student.student_id},
    )
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["student_number"] == unverified_student.student_id
    assert search.json()["items"][0]["admission_id"] == unverified_body["id"]

    _login(client, "teacher@school.portal")
    denied = client.get(f"{API}/admission-verification/queue")
    assert denied.status_code == 403

    _login(client, "admin@school.portal")
    monkeypatch.setattr(
        get_settings(), "ADMISSION_MIGRATION_CONSOLE_ENABLED", False
    )
    disabled = client.get(f"{API}/admission-verification/queue")
    assert disabled.status_code == 403
    assert _error_code(disabled) == "MIGRATION_CONSOLE_DISABLED"


def test_verification_audit_failure_rolls_back_act_and_slot(
    client: TestClient, db_session: DBSession, monkeypatch
):
    tag = uuid.uuid4().hex[:8]
    student = _mk_student(db_session, tag=tag)
    period, offering = _mk_academic(
        db_session, tag=tag, start=date(2027, 9, 1), end=date(2028, 1, 31)
    )
    management = (
        db_session.query(User).filter(User.email == "management@school.portal").one()
    )
    db_session.commit()

    body = admission_verification.create_migrated_candidate(
        db_session,
        student,
        admission_verification.MigratedAdmissionCreate(
            admission_intake_id=period.id,
            program_offering_id=offering.id,
        ),
        management,
    )
    db_session.commit()

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(admission_verification, "record_audit", fail_audit)
    with pytest.raises(RuntimeError):
        admission_verification.confirm_slot(
            db_session,
            student,
            body.id,
            admission_verification.AdmissionVerificationSlot.MANAGEMENT,
            admission_verification.VerificationConfirm(
                evidence_type="ADMISSION_LETTER",
                evidence_reference="MIG-ROLLBACK",
            ),
            management,
        )

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, body.id)
    assert stored.management_confirmation_state == "NONE"
    assert stored.verification_status == "UNVERIFIED"
    assert (
        db_session.query(AcademicAdmissionVerificationAct)
        .filter(AcademicAdmissionVerificationAct.admission_id == body.id)
        .count()
        == 0
    )
    assert db_session.get(Student, student.id).original_admission_id is None
