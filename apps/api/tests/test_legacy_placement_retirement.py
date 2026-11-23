"""Phase 8a/8b: legacy direct-placement retirement.

The direct-write routes still refuse with the stable retirement code. The
underlying compatibility columns are gone in Phase 8b, so every assertion is
made against admissions, placements, status history and audit rows.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect

from app.config.settings import get_settings
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionStatusHistory,
    AcademicPlacement,
)
from app.models.audit import AuditLog
from app.models.identity import Student, User

API = "/api/v1"


@pytest.fixture(autouse=True)
def _admissions_enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", True)


def _login(client, email: str = "admin@school.portal", password: str = "password123") -> None:
    response = client.post(
        f"{API}/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text


def _login_onboarded_student(client, created: dict) -> None:
    """Sign in as a newly onboarded student and clear the temporary password."""
    temporary = created["temporary_password"]
    _login(client, created["account"]["email"], temporary)
    changed = client.post(
        f"{API}/auth/password/change",
        json={
            "current_password": temporary,
            "new_password": "Phase8a-Student-Pass-123!",
        },
    )
    assert changed.status_code == 200, changed.text


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _academics(client) -> dict:
    program = client.get(f"{API}/academics/programs").json()["items"][0]
    tag = _tag()
    other_program = client.post(
        f"{API}/academics/programs",
        json={
            "major_id": program["major_id"],
            "code": f"P8A-{tag}",
            "name": f"Phase 8a programme {tag}",
        },
    )
    assert other_program.status_code == 201, other_program.text
    other_program = other_program.json()

    period = client.post(
        f"{API}/academics/periods",
        json={
            "name": f"Phase 8a intake {tag}",
            "code": f"P8A-{tag}",
            "start_date": "2036-09-01",
            "end_date": "2036-12-20",
            "status": "ACTIVE",
        },
    )
    assert period.status_code == 201, period.text
    period = period.json()

    offerings = {}
    for key, selected_program in (("admitted", program), ("other", other_program)):
        offering = client.post(
            f"{API}/academics/program-offerings",
            json={
                "academic_period_id": period["id"],
                "source_id": f"p8a-{tag}-{key}",
                "name": f"Phase 8a offering {tag} {key}",
                "program_id": selected_program["id"],
            },
        )
        assert offering.status_code == 201, offering.text
        offerings[key] = offering.json()

    return {
        "program": program,
        "other_program": other_program,
        "period": period,
        "offering": offerings["admitted"],
        "other_offering": offerings["other"],
    }


def _onboard(
    client,
    tag: str,
    *,
    offering_id: str | None = None,
    **extra,
) -> dict:
    payload = {
        "student_id": f"P8A-{tag.upper()}",
        "first_name": "Phase",
        "last_name": tag,
        "email": f"p8a-{tag}@example.com",
        **extra,
    }
    if offering_id is not None:
        payload["program_offering_id"] = offering_id
        payload.setdefault("initial_admission_status", "ACTIVE")
    response = client.post(f"{API}/students/onboard", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _snapshot(db_session, student_id: uuid.UUID, *, include_audits: bool = True) -> dict:
    db_session.expire_all()
    admission = (
        db_session.query(AcademicAdmission)
        .filter(AcademicAdmission.student_id == student_id)
        .order_by(AcademicAdmission.created_at.desc())
        .first()
    )
    snapshot = {
        "admission": (
            (
                admission.id,
                admission.status,
                admission.admitted_program_id,
                admission.admitted_program_offering_id,
                admission.current_program_id,
            )
            if admission is not None
            else None
        ),
        "placements": [
            (
                row.id,
                row.program_offering_id,
                row.academic_period_id,
                row.ended_at,
            )
            for row in db_session.query(AcademicPlacement)
            .filter(AcademicPlacement.student_id == student_id)
            .order_by(AcademicPlacement.id)
            .all()
        ],
        "history_rows": (
            db_session.query(AcademicAdmissionStatusHistory)
            .filter(
                AcademicAdmissionStatusHistory.admission_id == admission.id
            )
            .count()
            if admission is not None
            else 0
        ),
    }
    if include_audits:
        snapshot["audits"] = db_session.query(AuditLog).count()
    return snapshot


def _assert_unchanged(
    db_session,
    student_id: uuid.UUID,
    before: dict,
    *,
    include_audits: bool = True,
) -> None:
    assert _snapshot(db_session, student_id, include_audits=include_audits) == before


def test_profile_placement_fields_are_retired_without_side_effects(
    client, db_session
):
    """Scenario 76: a profile PATCH cannot rewrite placement and applies nothing."""
    _login(client)
    academic = _academics(client)
    tag = _tag()
    created = _onboard(client, tag, offering_id=academic["offering"]["id"])
    student_id = uuid.UUID(created["student"]["id"])
    before = _snapshot(db_session, student_id)
    original_phone = db_session.get(Student, student_id).phone

    payloads = (
        {"major_id": academic["other_program"]["major_id"]},
        {"program_id": academic["other_program"]["id"]},
        {"program_offering_id": academic["other_offering"]["id"]},
        {"phone": "+86 555 0199", "program_id": academic["other_program"]["id"]},
        {
            "phone": "+86 555 0199",
            "program_offering_id": academic["other_offering"]["id"],
        },
    )
    for payload in payloads:
        refused = client.patch(f"{API}/students/{student_id}", json=payload)
        assert refused.status_code == 409, refused.text
        assert _error_code(refused) == "PLACEMENT_DIRECT_WRITE_RETIRED"
        _assert_unchanged(db_session, student_id, before)

    # The whole request was refused, including the ordinary field bundled with
    # the placement field: there is no half-applied profile update.
    assert db_session.get(Student, student_id).phone == original_phone


def test_program_offering_endpoint_is_retired_without_side_effects(
    client, db_session
):
    """Scenario 77: the legacy offering endpoint changes nothing."""
    _login(client)
    academic = _academics(client)
    tag = _tag()
    created = _onboard(client, tag, offering_id=academic["offering"]["id"])
    student_id = uuid.UUID(created["student"]["id"])
    before = _snapshot(db_session, student_id)

    refused = client.patch(
        f"{API}/students/{student_id}/program-offering",
        json={
            "program_offering_id": academic["other_offering"]["id"],
            "reason": "Direct reassignment attempt",
        },
    )
    assert refused.status_code == 409, refused.text
    assert _error_code(refused) == "PLACEMENT_DIRECT_WRITE_RETIRED"
    _assert_unchanged(db_session, student_id, before)


def test_self_service_selection_is_retired_for_every_legacy_field(
    client, db_session, monkeypatch
):
    """Scenario 78: no legacy body becomes a request, even with P4 enabled."""
    monkeypatch.setattr(get_settings(), "ADMISSION_CHANGE_REQUESTS_ENABLED", True)
    _login(client)
    academic = _academics(client)
    tag = _tag()
    created = _onboard(client, tag, offering_id=academic["offering"]["id"])
    student_id = uuid.UUID(created["student"]["id"])

    _login_onboarded_student(client, created)
    before = _snapshot(db_session, student_id, include_audits=False)
    before_requests = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "academic.admission.change_requested")
        .count()
    )
    payloads = (
        {"major_id": academic["other_program"]["major_id"]},
        {
            "major_id": academic["other_program"]["major_id"],
            "program_id": academic["other_program"]["id"],
        },
        {"program_offering_id": academic["other_offering"]["id"]},
    )
    for payload in payloads:
        refused = client.post(f"{API}/students/me/academic", json=payload)
        assert refused.status_code == 409, refused.text
        assert _error_code(refused) == "PLACEMENT_DIRECT_WRITE_RETIRED"
        _assert_unchanged(db_session, student_id, before, include_audits=False)

    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "academic.admission.change_requested")
        .count()
        == before_requests
    )
    pending = client.get(f"{API}/students/me/admission-changes")
    assert pending.status_code == 200, pending.text
    assert pending.json()["total"] == 0


def test_self_service_without_a_live_episode_also_refuses_legacy_fields(
    client, monkeypatch
):
    """The retirement decision does not depend on a live episode."""
    monkeypatch.setattr(get_settings(), "ADMISSION_CHANGE_REQUESTS_ENABLED", True)
    _login(client)
    academic = _academics(client)
    tag = _tag()
    created = _onboard(client, tag)

    _login_onboarded_student(client, created)
    refused = client.post(
        f"{API}/students/me/academic",
        json={"major_id": academic["other_program"]["major_id"]},
    )
    assert refused.status_code == 409, refused.text
    assert _error_code(refused) == "PLACEMENT_DIRECT_WRITE_RETIRED"


def test_self_service_is_retired_when_requests_are_disabled(client, monkeypatch):
    """P4 off cannot reopen a direct write."""
    monkeypatch.setattr(get_settings(), "ADMISSION_CHANGE_REQUESTS_ENABLED", False)
    _login(client)
    academic = _academics(client)
    tag = _tag()
    created = _onboard(client, tag, offering_id=academic["offering"]["id"])

    _login_onboarded_student(client, created)
    refused = client.post(
        f"{API}/students/me/academic",
        json={"major_id": academic["other_program"]["major_id"]},
    )
    assert refused.status_code == 409, refused.text
    assert _error_code(refused) == "PLACEMENT_DIRECT_WRITE_RETIRED"


def test_onboarding_without_an_offering_cannot_write_a_placement(client, db_session):
    """A major/program pair has no intake, so it cannot become history."""
    _login(client)
    academic = _academics(client)
    tag = _tag()

    for extra in (
        {"major_id": academic["other_program"]["major_id"]},
        {"program_id": academic["other_program"]["id"]},
    ):
        payload = {
            "student_id": f"P8A-{tag}-{next(iter(extra))}".upper(),
            "first_name": "No",
            "last_name": "Offering",
            "email": f"no-offering-{tag}-{next(iter(extra))}@example.com",
            **extra,
        }
        refused = client.post(f"{API}/students/onboard", json=payload)
        assert refused.status_code == 409, refused.text
        assert _error_code(refused) == "PLACEMENT_DIRECT_WRITE_RETIRED"
        assert (
            db_session.query(Student)
            .filter(Student.student_id == payload["student_id"])
            .first()
            is None
        )


def test_onboarding_refuses_an_offering_when_admission_writes_are_off(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", False)
    _login(client)
    academic = _academics(client)
    tag = _tag()
    payload = {
        "student_id": f"P8A-{tag}".upper(),
        "first_name": "Disabled",
        "last_name": tag,
        "email": f"disabled-{tag}@example.com",
        "program_offering_id": academic["offering"]["id"],
        "initial_admission_status": "ACTIVE",
    }

    refused = client.post(f"{API}/students/onboard", json=payload)
    assert refused.status_code == 409, refused.text
    assert _error_code(refused) == "ADMISSIONS_WRITE_DISABLED"
    assert (
        db_session.query(Student)
        .filter(Student.student_id == payload["student_id"])
        .first()
        is None
    )
    assert (
        db_session.query(User)
        .filter(User.email == payload["email"].lower())
        .first()
        is None
    )


def test_retirement_does_not_weaken_endpoint_authorization(client):
    """A student still receives 403, not the retirement code."""
    _login(client)
    academic = _academics(client)
    tag = _tag()
    created = _onboard(client, tag, offering_id=academic["offering"]["id"])
    student_id = created["student"]["id"]

    _login_onboarded_student(client, created)
    profile = client.patch(
        f"{API}/students/{student_id}", json={"phone": "+86 555 0111"}
    )
    assert profile.status_code == 403, profile.text

    offering = client.patch(
        f"{API}/students/{student_id}/program-offering",
        json={"program_offering_id": academic["other_offering"]["id"]},
    )
    assert offering.status_code == 403, offering.text


def test_student_table_has_no_legacy_projection_columns(db_session):
    """The removed columns are absent from the model and the database table."""
    for field in ("major_id", "program_id", "program_offering_id"):
        assert not hasattr(Student, field)
    columns = {
        column["name"]
        for column in inspect(db_session.get_bind()).get_columns("students")
    }
    assert not ({"major_id", "program_id", "program_offering_id"} & columns)


def test_read_view_derives_programme_from_admission_and_offering_from_placement(
    client, db_session
):
    """A current placement change is visible without rewriting Student."""
    _login(client)
    academic = _academics(client)
    tag = _tag()
    created = _onboard(client, tag, offering_id=academic["offering"]["id"])
    student_id = uuid.UUID(created["student"]["id"])

    initial = client.get(f"{API}/students/{student_id}").json()
    assert initial["program_offering_id"] == academic["offering"]["id"]
    assert initial["program_id"] == academic["program"]["id"]

    placement = (
        db_session.query(AcademicPlacement)
        .filter(
            AcademicPlacement.student_id == student_id,
            AcademicPlacement.ended_at.is_(None),
        )
        .one()
    )
    placement.program_offering_id = uuid.UUID(academic["other_offering"]["id"])
    db_session.flush()

    current = client.get(f"{API}/students/{student_id}").json()
    assert current["program_offering_id"] == academic["other_offering"]["id"]
    # The programme still comes from the effective admission, not the offering.
    assert current["program_id"] == academic["program"]["id"]

    listed = client.get(
        f"{API}/students/",
        params={"program_id": academic["program"]["id"], "page_size": 100},
    )
    assert listed.status_code == 200, listed.text
    assert str(student_id) in {item["id"] for item in listed.json()["items"]}
