"""Phase 6: immigration cohort attribution from the original admission.

All records are synthetic and live inside the test transaction. The tests
exercise the original-admission pointer, trust buckets, pagination, export and
the replacement-independence of placement rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from app.auth.service import hash_password
from app.config.settings import get_settings
from app.models.academic import (
    AcademicPeriod,
    Major,
    Program,
    ProgramOffering,
)
from app.models.admission import AcademicAdmission, AcademicPlacement
from app.models.identity import Student, User
from app.models.immigration import ImmigrationProfile

API = "/api/v1"


@pytest.fixture(autouse=True)
def phase_six_pointer(monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMISSION_COHORT_SOURCE", "POINTER")


def _login(client, email: str = "management@school.portal") -> None:
    response = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200, response.text


def _mk_period(db, name: str, start: date) -> AcademicPeriod:
    period = AcademicPeriod(
        code=f"P6-{uuid.uuid4().hex[:12]}",
        name=name,
        start_date=start,
        end_date=start + timedelta(days=100),
        status="ACTIVE",
    )
    db.add(period)
    db.flush()
    return period


def _mk_program(db) -> Program:
    major = Major(code=f"M6-{uuid.uuid4().hex[:10]}", name="Phase Six Major")
    db.add(major)
    db.flush()
    program = Program(
        major_id=major.id,
        code=f"P6-{uuid.uuid4().hex[:10]}",
        name="Phase Six Program",
    )
    db.add(program)
    db.flush()
    return program


def _mk_offering(db, period: AcademicPeriod, program: Program) -> ProgramOffering:
    offering = ProgramOffering(
        academic_period_id=period.id,
        program_id=program.id,
        source_id=f"p6-{uuid.uuid4().hex[:10]}",
        source_key=f"phase6-{uuid.uuid4().hex[:12]}",
        name=f"Offering {period.name}",
    )
    db.add(offering)
    db.flush()
    return offering


def _mk_student(db, tag: str) -> Student:
    user = User(
        email=f"phase6-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"phase6-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Phase Six {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"P6-{tag}-{uuid.uuid4().hex[:6]}",
        first_name="Phase",
        last_name=f"Six {tag}",
        status="ACTIVE",
    )
    db.add(student)
    db.flush()
    db.add(
        ImmigrationProfile(
            student_id=student.id,
            passport_expiry_date=date.today() + timedelta(days=200),
            visa_expiry_date=date.today() + timedelta(days=200),
            residence_permit_expiry_date=date.today() + timedelta(days=200),
            data_source="ADMIN",
            verification_status="VERIFIED",
        )
    )
    db.flush()
    return student


def _mk_admission(
    db,
    student: Student,
    period: AcademicPeriod,
    offering: ProgramOffering,
    program: Program,
    *,
    actor: User,
    verification_status: str = "VERIFIED",
    record_origin: str = "NEW_ADMISSION",
    status: str = "PENDING",
    management_confirmed_by: User | None = None,
    management_confirmed_at: datetime | None = None,
    management_revoked_by: User | None = None,
    management_revoked_at: datetime | None = None,
    management_revocation_reason: str | None = None,
    admin_confirmed_by: User | None = None,
    admin_confirmed_at: datetime | None = None,
) -> AcademicAdmission:
    now = datetime.now()
    terminal = status in {"COMPLETED", "WITHDRAWN", "CANCELLED"}
    management_state = (
        "REVOKED"
        if management_revoked_at is not None
        else "CONFIRMED"
        if management_confirmed_at is not None
        else "NONE"
    )
    admin_state = "CONFIRMED" if admin_confirmed_at is not None else "NONE"
    admission = AcademicAdmission(
        student_id=student.id,
        admission_intake_id=period.id,
        admitted_program_id=program.id,
        admitted_program_offering_id=offering.id,
        current_program_id=program.id,
        status=status,
        initial_status=status,
        record_origin=record_origin,
        verification_status=verification_status,
        management_confirmation_state=management_state,
        management_confirmed_by_id=(
            management_confirmed_by.id if management_confirmed_by else None
        ),
        management_confirmed_at=management_confirmed_at,
        management_revoked_by_id=(
            management_revoked_by.id if management_revoked_by else None
        ),
        management_revoked_at=management_revoked_at,
        management_revocation_reason=management_revocation_reason,
        admin_confirmation_state=admin_state,
        admin_confirmed_by_id=admin_confirmed_by.id if admin_confirmed_by else None,
        admin_confirmed_at=admin_confirmed_at,
        verified_at=now if verification_status == "VERIFIED" else None,
        activated_at=now if status == "ACTIVE" else None,
        ended_at=now if terminal else None,
        end_reason=(
            "Phase 6 synthetic closure" if status in {"WITHDRAWN", "CANCELLED"} else None
        ),
        created_by_id=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(admission)
    db.flush()
    return admission


def _mk_placement(
    db,
    student: Student,
    admission: AcademicAdmission,
    period: AcademicPeriod,
    offering: ProgramOffering,
    *,
    actor: User,
    earlier: bool = False,
) -> AcademicPlacement:
    placement = AcademicPlacement(
        student_id=student.id,
        admission_id=admission.id,
        academic_period_id=period.id,
        program_offering_id=offering.id,
        is_earlier_intake_placement=earlier,
        authorized_by_id=actor.id if earlier else None,
        authorization_reason="Phase 6 synthetic authorization" if earlier else None,
        effective_from=period.start_date,
        created_by_id=actor.id,
    )
    db.add(placement)
    db.flush()
    return placement


def _world(db):
    """One verified student admitted to Spring 2026, with catalogue rows."""
    admin = db.query(User).filter(User.email == "admin@school.portal").one()
    management = db.query(User).filter(
        User.email == "management@school.portal"
    ).one()
    spring = _mk_period(db, "Spring 2026", date(2026, 1, 15))
    autumn_2025 = _mk_period(db, "Autumn 2025", date(2025, 9, 1))
    autumn_2026 = _mk_period(db, "Autumn 2026", date(2026, 9, 1))
    programme = _mk_program(db)
    spring_offering = _mk_offering(db, spring, programme)
    earlier_offering = _mk_offering(db, autumn_2025, programme)
    later_offering = _mk_offering(db, autumn_2026, programme)
    student = _mk_student(db, "cohort")
    admission = _mk_admission(
        db, student, spring, spring_offering, programme, actor=admin
    )
    student.original_admission_id = admission.id
    db.flush()
    return {
        "admin": admin,
        "management": management,
        "spring": spring,
        "autumn_2025": autumn_2025,
        "autumn_2026": autumn_2026,
        "programme": programme,
        "spring_offering": spring_offering,
        "earlier_offering": earlier_offering,
        "later_offering": later_offering,
        "student": student,
        "admission": admission,
    }


def _overview(client, **params):
    response = client.get(f"{API}/immigration/overview", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _find_item(body, student_id: str):
    return next(item for item in body["items"] if item["student_id"] == student_id)


def test_backward_and_forward_placement_keep_spring_2026_cohort(client, db_session):
    world = _world(db_session)
    _login(client)
    _mk_placement(
        db_session,
        world["student"],
        world["admission"],
        world["autumn_2025"],
        world["earlier_offering"],
        actor=world["admin"],
        earlier=True,
    )
    backward = _find_item(_overview(client), str(world["student"].id))
    assert backward["original_admission_intake_id"] == str(world["spring"].id)
    assert backward["placement_intake_id"] == str(world["autumn_2025"].id)

    placement = (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == world["student"].id)
        .one()
    )
    placement.academic_period_id = world["autumn_2026"].id
    placement.program_offering_id = world["later_offering"].id
    placement.is_earlier_intake_placement = False
    placement.authorized_by_id = None
    placement.authorization_reason = None
    db_session.flush()

    forward = _find_item(_overview(client), str(world["student"].id))
    assert forward["original_admission_intake_id"] == str(world["spring"].id)
    assert forward["placement_intake_id"] == str(world["autumn_2026"].id)


def test_programme_change_and_later_admission_do_not_move_pointer(client, db_session):
    world = _world(db_session)
    _login(client)
    changed_programme = _mk_program(db_session)
    world["admission"].current_program_id = changed_programme.id
    later = _mk_admission(
        db_session,
        world["student"],
        world["autumn_2026"],
        world["later_offering"],
        changed_programme,
        actor=world["admin"],
        status="COMPLETED",
    )
    db_session.flush()
    db_session.refresh(world["student"])
    assert world["student"].original_admission_id == world["admission"].id
    assert later.id != world["student"].original_admission_id

    item = _find_item(_overview(client), str(world["student"].id))
    assert item["original_admission_intake_id"] == str(world["spring"].id)


def test_intake_filter_uses_original_intake_only(client, db_session):
    spring_world = _world(db_session)
    autumn = spring_world["autumn_2026"]
    student_b = _mk_student(db_session, "autumn")
    admission_b = _mk_admission(
        db_session,
        student_b,
        autumn,
        spring_world["later_offering"],
        spring_world["programme"],
        actor=spring_world["admin"],
    )
    student_b.original_admission_id = admission_b.id
    db_session.flush()

    _login(client)
    body = _overview(client, intake_id=str(spring_world["spring"].id))
    ids = {item["student_id"] for item in body["items"]}
    assert str(spring_world["student"].id) in ids
    assert str(student_b.id) not in ids
    assert all(
        item["original_admission_intake_id"] == str(spring_world["spring"].id)
        for item in body["items"]
    )


def test_trust_buckets_are_explicit_and_reconcile(client, db_session):
    world = _world(db_session)
    db_session.flush()
    actor = world["admin"]
    unverified = _mk_student(db_session, "unverified")
    unverified_admission = _mk_admission(
        db_session,
        unverified,
        world["spring"],
        world["spring_offering"],
        world["programme"],
        actor=actor,
        verification_status="UNVERIFIED",
        record_origin="MIGRATED",
    )
    unverified.original_admission_id = unverified_admission.id

    revoked = _mk_student(db_session, "revoked")
    revoked_admission = _mk_admission(
        db_session,
        revoked,
        world["spring"],
        world["spring_offering"],
        world["programme"],
        actor=actor,
        verification_status="REVOKED",
        record_origin="MIGRATED",
        management_confirmed_by=world["management"],
        management_confirmed_at=datetime.now(),
        management_revoked_by=actor,
        management_revoked_at=datetime.now(),
        management_revocation_reason="Register contradicts the admission letter.",
    )
    revoked.original_admission_id = revoked_admission.id

    disputed = _mk_student(db_session, "disputed")
    disputed_admission = _mk_admission(
        db_session,
        disputed,
        world["spring"],
        world["spring_offering"],
        world["programme"],
        actor=actor,
        verification_status="DISPUTED",
        record_origin="MIGRATED",
    )
    disputed.original_admission_id = disputed_admission.id
    # A student with no pointer is intentionally left as NO_ADMISSION.
    no_admission = _mk_student(db_session, "no-pointer")
    db_session.flush()

    _login(client)
    body = _overview(client)
    cohorts = {row["intake_id"]: row["count"] for row in body["cohorts"]}
    assert cohorts[str(world["spring"].id)] == 1
    assert body["untrusted"]["unverified"] >= 1
    assert body["untrusted"]["revoked"] >= 1
    assert body["untrusted"]["disputed"] >= 1
    assert body["untrusted"]["no_admission"] >= 2  # seeded student + synthetic
    assert body["untrusted"]["total"] == (
        body["untrusted"]["unverified"]
        + body["untrusted"]["revoked"]
        + body["untrusted"]["disputed"]
        + body["untrusted"]["no_admission"]
    )
    assert sum(cohorts.values()) + body["untrusted"]["total"] == body[
        "total_students"
    ]

    names = {item["student_id"] for item in body["items"]}
    assert str(unverified.id) in names
    assert str(revoked.id) in names
    assert str(disputed.id) in names
    assert str(no_admission.id) in names
    for item in body["items"]:
        if item["student_id"] in {
            str(unverified.id),
            str(revoked.id),
            str(disputed.id),
            str(no_admission.id),
        }:
            assert item["original_admission_intake_id"] is None


def test_revoked_student_returns_last_confirmer_and_revocation(client, db_session):
    world = _world(db_session)
    revoked = _mk_student(db_session, "revoked-detail")
    admission = _mk_admission(
        db_session,
        revoked,
        world["spring"],
        world["spring_offering"],
        world["programme"],
        actor=world["admin"],
        verification_status="REVOKED",
        record_origin="MIGRATED",
        management_confirmed_by=world["management"],
        management_confirmed_at=datetime(2026, 2, 1, 10, 0),
        management_revoked_by=world["admin"],
        management_revoked_at=datetime(2026, 2, 2, 11, 0),
        management_revocation_reason="Register contradicts the admission letter.",
        admin_confirmed_by=world["admin"],
        admin_confirmed_at=datetime(2026, 2, 1, 12, 0),
    )
    revoked.original_admission_id = admission.id
    db_session.flush()

    _login(client)
    response = client.get(f"{API}/students/{revoked.id}/immigration/cohort")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verification_status"] == "REVOKED"
    assert body["last_confirmer_name"] == world["admin"].full_name
    assert body["last_confirmed_at"] is not None
    assert body["revoked_by_name"] == world["admin"].full_name
    assert body["revocation_reason"] == "Register contradicts the admission letter."
    assert body["original_admission_intake_id"] == str(world["spring"].id)


def test_export_carries_trust_and_empty_cohort_for_untrusted(client, db_session):
    world = _world(db_session)
    untrusted = _mk_student(db_session, "export-untrusted")
    admission = _mk_admission(
        db_session,
        untrusted,
        world["spring"],
        world["spring_offering"],
        world["programme"],
        actor=world["admin"],
        verification_status="UNVERIFIED",
        record_origin="MIGRATED",
    )
    untrusted.original_admission_id = admission.id
    db_session.flush()

    _login(client)
    response = client.get(f"{API}/immigration/overview/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.splitlines()
    assert "verification_status" in lines[0]
    verified_row = next(
        line for line in lines if str(world["student"].student_id) in line
    )
    untrusted_row = next(line for line in lines if str(untrusted.student_id) in line)
    assert "Spring 2026" in verified_row
    assert "VERIFIED" in verified_row
    assert "UNVERIFIED" in untrusted_row
    # student_number,name,cohort,trust — cohort must be empty for untrusted.
    assert untrusted_row.split(",")[2] == ""


def test_report_expiry_rollup_uses_the_same_named_cohort_basis(client, db_session):
    world = _world(db_session)
    untrusted = _mk_student(db_session, "report-untrusted")
    admission = _mk_admission(
        db_session,
        untrusted,
        world["spring"],
        world["spring_offering"],
        world["programme"],
        actor=world["admin"],
        verification_status="UNVERIFIED",
        record_origin="MIGRATED",
    )
    untrusted.original_admission_id = admission.id
    profile = (
        db_session.query(ImmigrationProfile)
        .filter(ImmigrationProfile.student_id == untrusted.id)
        .one()
    )
    profile.passport_expiry_date = date.today() - timedelta(days=1)
    profile.visa_expiry_date = date.today() - timedelta(days=1)
    profile.residence_permit_expiry_date = date.today() - timedelta(days=1)
    db_session.flush()

    _login(client)
    response = client.get(f"{API}/reports/immigration")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expired"] == 0  # the untrusted expired profile is excluded
    assert body["in_named_cohorts"] == 1
    assert body["untrusted_students"] >= 2
    assert any(
        item["label"] == "Spring 2026" and item["count"] == 1
        for item in body["by_original_intake"]
    )


def test_removing_placements_does_not_change_cohort_output(client, db_session):
    world = _world(db_session)
    _mk_placement(
        db_session,
        world["student"],
        world["admission"],
        world["autumn_2025"],
        world["earlier_offering"],
        actor=world["admin"],
        earlier=True,
    )
    _login(client)
    before = _overview(client, intake_id=str(world["spring"].id))
    db_session.query(AcademicPlacement).delete()
    db_session.flush()
    after = _overview(client, intake_id=str(world["spring"].id))

    assert after["cohorts"] == before["cohorts"]
    assert after["untrusted"] == before["untrusted"]
    for key in ("student_id", "original_admission_intake_id", "verification_status"):
        assert [item[key] for item in after["items"]] == [
            item[key] for item in before["items"]
        ]


def test_overview_paging_is_stable(client, db_session):
    world = _world(db_session)
    actor = world["admin"]
    page_students = []
    for index in range(2):
        student = _mk_student(db_session, f"page-{index}")
        admission = _mk_admission(
            db_session,
            student,
            world["spring"],
            world["spring_offering"],
            world["programme"],
            actor=actor,
        )
        student.original_admission_id = admission.id
        page_students.append(student)
    db_session.flush()
    _login(client)

    first = _overview(
        client, intake_id=str(world["spring"].id), page=1, page_size=2
    )
    second = _overview(
        client, intake_id=str(world["spring"].id), page=2, page_size=2
    )
    assert first["total"] == 3
    assert first["total_pages"] == 2
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    first_ids = {item["student_id"] for item in first["items"]}
    second_ids = {item["student_id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == {
        str(world["student"].id),
        *[str(student.id) for student in page_students],
    }


def test_legacy_switch_preserves_population_without_changing_pointer(
    client, db_session, monkeypatch
):
    world = _world(db_session)
    db_session.flush()
    pointer_before = world["student"].original_admission_id
    monkeypatch.setattr(get_settings(), "ADMISSION_COHORT_SOURCE", "LEGACY")
    _login(client)
    body = _overview(client)
    assert body["cohorts"] == []
    assert body["untrusted"]["total"] == 0
    item = _find_item(body, str(world["student"].id))
    assert item["original_admission_intake_id"] is None
    db_session.refresh(world["student"])
    assert world["student"].original_admission_id == pointer_before
