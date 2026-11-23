"""Phase 3 placement, earlier-intake authorization and history."""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.service import hash_password
from app.models.academic import (
    AcademicPeriod,
    Assessment,
    AssessmentType,
    AttendanceRecord,
    AttendanceStatus,
    ClassSection,
    ClassSectionProgramOffering,
    Course,
    Enrollment,
    EnrollmentStatus,
    Major,
    Program,
    ProgramOffering,
    TimetableEntry,
)
from app.models.admission import AcademicAdmission, AcademicPlacement
from app.models.audit import AuditLog
from app.models.identity import Permission, Role, Student, User

API = "/api/v1"


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
        email=f"{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123") if password else "not-used",
        full_name=f"Placement {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"PL-{tag}-{uuid.uuid4().hex[:6]}",
        first_name="Placement",
        last_name=tag,
    )
    db.add(student)
    db.flush()
    return student


def _mk_scenario(db, tag: str) -> dict:
    major = Major(code=f"PM-{tag}", name=f"Placement Major {tag}")
    db.add(major)
    db.flush()
    program = Program(
        major_id=major.id,
        code=f"PP-{tag}",
        name=f"Placement Program {tag}",
    )
    db.add(program)
    db.flush()

    periods = {}
    for key, start, end in (
        ("earlier", date(2031, 9, 1), date(2031, 12, 20)),
        ("admission", date(2032, 9, 1), date(2032, 12, 20)),
        ("later", date(2033, 2, 1), date(2033, 6, 30)),
    ):
        period = AcademicPeriod(
            code=f"P-{tag}-{key[:2]}",
            name=f"Placement intake {tag} {key}",
            start_date=start,
            end_date=end,
            status="PLANNED",
        )
        db.add(period)
        db.flush()
        periods[key] = period

    offerings = {}
    for key in ("admission", "same", "earlier", "later"):
        period = periods["admission"] if key in {"admission", "same"} else periods[key]
        offering = ProgramOffering(
            academic_period_id=period.id,
            program_id=program.id,
            source_id=f"{tag}-{key}",
            source_key=f"placement-{tag}-{key}",
            name=f"Placement offering {tag} {key}",
        )
        db.add(offering)
        db.flush()
        offerings[key] = offering

    source_only = ProgramOffering(
        academic_period_id=periods["earlier"].id,
        program_id=None,
        source_id=f"{tag}-source",
        source_key=f"placement-{tag}-source",
        name=f"Source only {tag}",
    )
    db.add(source_only)
    db.flush()

    course = Course(code=f"PC-{tag}", name=f"Placement Course {tag}")
    db.add(course)
    db.flush()
    sections = {}
    for key in ("admission", "same", "earlier", "later"):
        section = ClassSection(
            course_id=course.id,
            academic_period_id=(
                periods["admission"] if key in {"admission", "same"} else periods[key]
            ).id,
            section_code=key[:4].upper(),
            capacity=30,
            status="ACTIVE",
        )
        db.add(section)
        db.flush()
        sections[key] = section
        db.add(
            ClassSectionProgramOffering(
                class_section_id=section.id,
                program_offering_id=offerings[key].id,
            )
        )

    # A genuinely shared teaching section, linked to two placements.
    shared = ClassSection(
        course_id=course.id,
        academic_period_id=periods["later"].id,
        section_code="SHRD",
        capacity=30,
        status="ACTIVE",
    )
    db.add(shared)
    db.flush()
    db.add_all(
        [
            ClassSectionProgramOffering(
                class_section_id=shared.id,
                program_offering_id=offerings["later"].id,
            ),
            ClassSectionProgramOffering(
                class_section_id=shared.id,
                program_offering_id=offerings["admission"].id,
            ),
        ]
    )
    sections["shared"] = shared

    for index, section in enumerate(
        [
            sections["admission"],
            sections["same"],
            sections["earlier"],
            sections["later"],
            sections["shared"],
        ]
    ):
        db.add(
            TimetableEntry(
                class_section_id=section.id,
                day_of_week=index,
                start_time=time(9, 0),
                end_time=time(10, 0),
            )
        )

    db.commit()
    return {
        "major": major,
        "program": program,
        "periods": periods,
        "offerings": offerings,
        "source_only": source_only,
        "course": course,
        "sections": sections,
        "shared": shared,
    }


def _create_admission(client, student_id, period_id, offering_id, status="ACTIVE"):
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


def _placement(
    client,
    student_id,
    admission_id,
    offering_id,
    *,
    reason=None,
    effective_from=None,
):
    payload = {
        "admission_id": str(admission_id),
        "program_offering_id": str(offering_id),
        "effective_from": effective_from or "2032-09-01",
    }
    if reason is not None:
        payload["reason"] = reason
    return client.post(f"{API}/students/{student_id}/placements", json=payload)


@pytest.fixture(autouse=True)
def admission_writes(monkeypatch):
    from app.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", True)


def test_same_and_later_placement_supersede_without_rewriting_admission(
    client, db_session
):
    _login(client)
    tag = uuid.uuid4().hex[:7]
    scenario = _mk_scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    admission = _create_admission(
        client,
        student.id,
        scenario["periods"]["admission"].id,
        scenario["offerings"]["admission"].id,
    )
    original_pointer = db_session.get(Student, student.id).original_admission_id

    first = _placement(
        client,
        student.id,
        admission["id"],
        scenario["offerings"]["same"].id,
    )
    assert first.status_code == 201, first.text
    first_body = first.json()
    assert first_body["is_earlier_intake_placement"] is False
    assert first_body["authorized_by_id"] is None
    assert first_body["admission_intake_id"] == str(
        scenario["periods"]["admission"].id
    )
    assert first_body["placement_intake_id"] == str(
        scenario["periods"]["admission"].id
    )

    db_session.expire_all()
    stored = db_session.get(AcademicAdmission, uuid.UUID(admission["id"]))
    assert str(stored.admission_intake_id) == str(scenario["periods"]["admission"].id)
    assert str(stored.admitted_program_id) == str(scenario["program"].id)
    assert str(stored.admitted_program_offering_id) == str(
        scenario["offerings"]["admission"].id
    )
    assert db_session.get(Student, student.id).original_admission_id == original_pointer

    second = _placement(
        client,
        student.id,
        admission["id"],
        scenario["offerings"]["later"].id,
    )
    assert second.status_code == 201, second.text

    history = client.get(f"{API}/students/{student.id}/placements")
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["total"] == 2
    assert sum(1 for item in body["items"] if item["is_current"]) == 1
    current = next(item for item in body["items"] if item["is_current"])
    assert current["program_offering_id"] == str(scenario["offerings"]["later"].id)
    previous = next(item for item in body["items"] if not item["is_current"])
    assert previous["ended_at"] is not None
    assert previous["program_offering_id"] == str(scenario["offerings"]["same"].id)

    placement_audits = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action.in_(
                [
                    "academic.placement.created",
                    "academic.placement.superseded",
                    "academic.placement.earlier_intake_authorized",
                ]
            )
        )
        .all()
    )
    student_audits = [
        row
        for row in placement_audits
        if row.context["student_id"] == str(student.id)
    ]
    actions = [row.action for row in student_audits]
    assert actions.count("academic.placement.created") == 2
    assert actions.count("academic.placement.superseded") == 1
    assert actions.count("academic.placement.earlier_intake_authorized") == 0
    superseded_audit = next(
        row
        for row in student_audits
        if row.action == "academic.placement.superseded"
    )
    assert superseded_audit.entity_id == uuid.UUID(previous["id"])
    assert superseded_audit.context["new_placement_id"] == current["id"]


def test_admin_and_management_authorize_earlier_placement_with_reason(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    scenario = _mk_scenario(db_session, tag)
    admin_student = _mk_student(db_session, f"{tag}-admin")
    manager_student = _mk_student(db_session, f"{tag}-manager")
    db_session.commit()

    for student, email in (
        (admin_student, "admin@school.portal"),
        (manager_student, "management@school.portal"),
    ):
        _login(client, email)
        admission = _create_admission(
            client,
            student.id,
            scenario["periods"]["admission"].id,
            scenario["offerings"]["admission"].id,
        )
        missing = _placement(
            client,
            student.id,
            admission["id"],
            scenario["offerings"]["earlier"].id,
        )
        assert missing.status_code == 422, missing.text
        assert _error_code(missing) == "EARLIER_INTAKE_REASON_REQUIRED"

        placed = _placement(
            client,
            student.id,
            admission["id"],
            scenario["offerings"]["earlier"].id,
            reason="Approved catch-up teaching placement",
        )
        assert placed.status_code == 201, placed.text
        body = placed.json()
        assert body["is_earlier_intake_placement"] is True
        assert body["authorization_reason"] == "Approved catch-up teaching placement"
        assert body["authorized_by_name"] == (
            "Admin User" if email.startswith("admin") else "Management User"
        )

        db_session.expire_all()
        stored_admission = db_session.get(
            AcademicAdmission, uuid.UUID(admission["id"])
        )
        assert stored_admission.admission_intake_id == (
            scenario["periods"]["admission"].id
        )
        assert stored_admission.admitted_program_id == scenario["program"].id
        assert stored_admission.admitted_program_offering_id == (
            scenario["offerings"]["admission"].id
        )

        audits = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.action.in_(
                    [
                        "academic.placement.created",
                        "academic.placement.superseded",
                        "academic.placement.earlier_intake_authorized",
                    ]
                )
            )
            .all()
        )
        student_audits = [
            row for row in audits if row.context["student_id"] == str(student.id)
        ]
        actions = [row.action for row in student_audits]
        assert actions.count("academic.placement.created") == 1
        assert actions.count("academic.placement.superseded") == 0
        assert actions.count("academic.placement.earlier_intake_authorized") == 1
        created = next(
            row for row in student_audits if row.action == "academic.placement.created"
        )
        assert created.context["is_earlier_intake_placement"] is True
        assert created.entity_id == uuid.UUID(body["id"])
        audit = next(
            row
            for row in student_audits
            if row.action == "academic.placement.earlier_intake_authorized"
        )
        assert audit.context["placement_reason"] == (
            "Approved catch-up teaching placement"
        )
        assert audit.context["authorized_by_id"] == str(
            db_session.get(User, uuid.UUID(body["authorized_by_id"])).id
        )
        assert audit.context["admission_intake_id"] == str(
            scenario["periods"]["admission"].id
        )
        assert audit.context["placement_intake_id"] == str(
            scenario["periods"]["earlier"].id
        )
        actor = (
            db_session.query(User).filter(User.email == email).one()
        )
        assert audit.actor_id == actor.id
        assert audit.actor_email == email
        assert audit.entity_id == uuid.UUID(body["id"])


def test_manage_permission_without_authorization_cannot_place_earlier(
    client, db_session
):
    """The earlier-intake gate is separate from the placement-management gate."""
    tag = uuid.uuid4().hex[:7]
    scenario = _mk_scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client,
        student.id,
        scenario["periods"]["admission"].id,
        scenario["offerings"]["admission"].id,
    )

    role = db_session.query(Role).filter(Role.name == "MANAGEMENT").one()
    permission = (
        db_session.query(Permission)
        .filter(Permission.codename == "academic.authorize_placement")
        .one()
    )
    role.permissions.remove(permission)
    db_session.commit()
    db_session.expire_all()

    _login(client, "management@school.portal")
    refused = _placement(
        client,
        student.id,
        admission["id"],
        scenario["offerings"]["earlier"].id,
        reason="Should not be accepted without the authorization permission",
    )
    assert refused.status_code == 403, refused.text
    assert _error_code(refused) == "EARLIER_INTAKE_NOT_AUTHORIZED"


def test_earlier_supersession_writes_one_audit_per_distinct_event(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    scenario = _mk_scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client,
        student.id,
        scenario["periods"]["admission"].id,
        scenario["offerings"]["admission"].id,
    )
    first = _placement(
        client,
        student.id,
        admission["id"],
        scenario["offerings"]["same"].id,
    )
    assert first.status_code == 201, first.text
    earlier = _placement(
        client,
        student.id,
        admission["id"],
        scenario["offerings"]["earlier"].id,
        reason="Approved earlier-intake teaching placement",
    )
    assert earlier.status_code == 201, earlier.text

    db_session.expire_all()
    audits = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action.in_(
                [
                    "academic.placement.created",
                    "academic.placement.superseded",
                    "academic.placement.earlier_intake_authorized",
                ]
            )
        )
        .all()
    )
    student_audits = [
        row for row in audits if row.context["student_id"] == str(student.id)
    ]
    actions = [row.action for row in student_audits]
    assert actions.count("academic.placement.created") == 2
    assert actions.count("academic.placement.superseded") == 1
    assert actions.count("academic.placement.earlier_intake_authorized") == 1
    assert len({(row.action, row.entity_id) for row in student_audits}) == 4

    superseded = next(
        row
        for row in student_audits
        if row.action == "academic.placement.superseded"
    )
    assert superseded.entity_id == uuid.UUID(first.json()["id"])
    assert superseded.context["new_placement_id"] == earlier.json()["id"]

    authorized = next(
        row
        for row in student_audits
        if row.action == "academic.placement.earlier_intake_authorized"
    )
    assert authorized.entity_id == uuid.UUID(earlier.json()["id"])
    assert authorized.context["placement_reason"] == (
        "Approved earlier-intake teaching placement"
    )
    assert authorized.context["authorized_by_id"] is not None

    # The existing audit endpoint must be able to select each action and its
    # affected placement; the UI filter uses the same action values.
    for action, entity_id in (
        ("academic.placement.created", earlier.json()["id"]),
        ("academic.placement.superseded", first.json()["id"]),
        ("academic.placement.earlier_intake_authorized", earlier.json()["id"]),
    ):
        response = client.get(
            f"{API}/audit",
            params={"action": action, "entity_id": entity_id},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["action"] == action
        assert body["items"][0]["entity_id"] == entity_id


def test_pending_source_only_and_unauthorized_roles_are_refused(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    scenario = _mk_scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    pending = _create_admission(
        client,
        student.id,
        scenario["periods"]["admission"].id,
        scenario["offerings"]["admission"].id,
        status="PENDING",
    )
    refused = _placement(
        client,
        student.id,
        pending["id"],
        scenario["offerings"]["same"].id,
    )
    assert refused.status_code == 409, refused.text
    assert _error_code(refused) == "PLACEMENT_REQUIRES_ADMITTED_EPISODE"

    source_student = _mk_student(db_session, f"{tag}-source")
    db_session.commit()
    active = _create_admission(
        client,
        source_student.id,
        scenario["periods"]["admission"].id,
        scenario["offerings"]["admission"].id,
    )
    source_only = _placement(
        client,
        source_student.id,
        active["id"],
        scenario["source_only"].id,
    )
    assert source_only.status_code == 409
    assert _error_code(source_only) == "PROGRAM_OFFERING_NOT_MAPPED"

    teacher_admission = _create_admission(
        client,
        _mk_student(db_session, f"{tag}-teacher").id,
        scenario["periods"]["admission"].id,
        scenario["offerings"]["admission"].id,
    )
    _login(client, "teacher@school.portal")
    teacher = _placement(
        client,
        teacher_admission["student_id"],
        teacher_admission["id"],
        scenario["offerings"]["same"].id,
    )
    assert teacher.status_code == 403

    student_user = _mk_student(db_session, f"{tag}-student", password=True)
    db_session.commit()
    _login(client, db_session.get(User, student_user.user_id).email)
    as_student = _placement(
        client,
        student_user.id,
        teacher_admission["id"],
        scenario["offerings"]["same"].id,
    )
    assert as_student.status_code == 403
    view = client.get(f"{API}/students/{student_user.id}/placements")
    assert view.status_code == 403


def test_database_constraints_reject_unauthorized_earlier_and_cross_intake(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    scenario = _mk_scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()
    _login(client)
    admission = _create_admission(
        client,
        student.id,
        scenario["periods"]["admission"].id,
        scenario["offerings"]["admission"].id,
    )
    db_session.expire_all()
    student_row = db_session.get(Student, student.id)

    unauthorized = AcademicPlacement(
        student_id=student_row.id,
        admission_id=uuid.UUID(admission["id"]),
        academic_period_id=scenario["periods"]["earlier"].id,
        program_offering_id=scenario["offerings"]["earlier"].id,
        is_earlier_intake_placement=True,
        effective_from=date(2032, 9, 1),
        created_by_id=student_row.user_id,
    )
    db_session.add(unauthorized)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    student_row = db_session.get(Student, student.id)
    cross_intake = AcademicPlacement(
        student_id=student_row.id,
        admission_id=uuid.UUID(admission["id"]),
        academic_period_id=scenario["periods"]["later"].id,
        program_offering_id=scenario["offerings"]["same"].id,
        is_earlier_intake_placement=False,
        effective_from=date(2033, 2, 1),
        created_by_id=student_row.user_id,
    )
    db_session.add(cross_intake)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_historical_academic_records_survive_placement_and_views_follow_period(
    client, db_session
):
    tag = uuid.uuid4().hex[:7]
    scenario = _mk_scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()

    _login(client)
    admission = _create_admission(
        client,
        student.id,
        scenario["periods"]["admission"].id,
        scenario["offerings"]["admission"].id,
    )

    section = scenario["sections"]["admission"]
    enrollment = Enrollment(
        student_id=student.id,
        class_section_id=section.id,
        status=EnrollmentStatus.ENROLLED,
    )
    attendance = AttendanceRecord(
        student_id=student.id,
        class_section_id=section.id,
        session_date=date(2032, 9, 5),
        status=AttendanceStatus.PRESENT,
        recorded_by=student.user_id,
    )
    assessment = Assessment(
        class_section_id=section.id,
        name="Placement history assessment",
        assessment_type=AssessmentType.QUIZ,
        max_score=100,
    )
    db_session.add_all([enrollment, attendance, assessment])
    db_session.flush()
    from app.models.academic import Grade

    grade = Grade(
        assessment_id=assessment.id,
        student_id=student.id,
        score=87.5,
        letter_grade="A",
        recorded_by=student.user_id,
    )
    timetable = TimetableEntry(
        class_section_id=section.id,
        day_of_week=0,
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    db_session.add_all([grade, timetable])
    db_session.commit()
    before = (
        enrollment.status,
        attendance.status,
        attendance.session_date,
        grade.score,
        grade.letter_grade,
        timetable.start_time,
        timetable.end_time,
    )

    placed = _placement(
        client,
        student.id,
        admission["id"],
        scenario["offerings"]["later"].id,
    )
    assert placed.status_code == 201, placed.text

    db_session.expire_all()
    assert (
        db_session.get(Enrollment, enrollment.id).status,
        db_session.get(AttendanceRecord, attendance.id).status,
        db_session.get(AttendanceRecord, attendance.id).session_date,
        db_session.get(Grade, grade.id).score,
        db_session.get(Grade, grade.id).letter_grade,
        db_session.get(TimetableEntry, timetable.id).start_time,
        db_session.get(TimetableEntry, timetable.id).end_time,
    ) == before

    # The historical period still resolves through the real enrollment even
    # though the current placement has moved to a later intake.
    historical = client.get(
        f"{API}/academics/students/{student.id}/timetable"
        f"?period_id={scenario['periods']['admission'].id}"
    )
    assert historical.status_code == 200, historical.text
    assert {
        item["class_section_id"] for item in historical.json()["items"]
    } == {str(section.id)}

    current = client.get(
        f"{API}/academics/students/{student.id}/timetable"
        f"?period_id={scenario['periods']['later'].id}"
    )
    assert current.status_code == 200, current.text
    assert {
        item["class_section_id"] for item in current.json()["items"]
    } == {
        str(scenario["sections"]["later"].id),
        str(scenario["shared"].id),
    }
    assert len(
        [
            item
            for item in current.json()["items"]
            if item["class_section_id"] == str(scenario["shared"].id)
        ]
    ) == 1

    overview = client.get(
        f"{API}/academics/students/{student.id}"
        f"?period_id={scenario['periods']['later'].id}"
    )
    assert overview.status_code == 200, overview.text
    assert overview.json()["program_offering"]["id"] == str(
        scenario["offerings"]["later"].id
    )


def test_audit_failure_rolls_back_placement_and_projection(
    client, db_session, monkeypatch
):
    tag = uuid.uuid4().hex[:7]
    scenario = _mk_scenario(db_session, tag)
    student = _mk_student(db_session, tag)
    db_session.commit()
    _login(client)
    admission = _create_admission(
        client,
        student.id,
        scenario["periods"]["admission"].id,
        scenario["offerings"]["admission"].id,
    )
    first = _placement(
        client,
        student.id,
        admission["id"],
        scenario["offerings"]["same"].id,
    )
    assert first.status_code == 201, first.text
    first_id = uuid.UUID(first.json()["id"])
    db_session.expire_all()
    prior = db_session.get(AcademicPlacement, first_id)
    assert prior is not None and prior.ended_at is None
    original_offering = prior.program_offering_id

    import app.routers.placements as placement_router

    real_record_audit = placement_router.record_audit

    def fail_audit(*args, **kwargs):
        if kwargs.get("action") == "academic.placement.earlier_intake_authorized":
            raise RuntimeError("audit unavailable")
        return real_record_audit(*args, **kwargs)

    monkeypatch.setattr(placement_router, "record_audit", fail_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        _placement(
            client,
            student.id,
            admission["id"],
            scenario["offerings"]["earlier"].id,
            reason="This earlier placement must roll back with its audit failure",
        )

    db_session.expire_all()
    placements = (
        db_session.query(AcademicPlacement)
        .filter(AcademicPlacement.student_id == student.id)
        .all()
    )
    assert len(placements) == 1
    assert placements[0].id == first_id
    assert placements[0].ended_at is None
    assert placements[0].program_offering_id == original_offering

    audits = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action.in_(
                [
                    "academic.placement.created",
                    "academic.placement.superseded",
                    "academic.placement.earlier_intake_authorized",
                ]
            )
        )
        .all()
    )
    student_audits = [
        row for row in audits if row.context["student_id"] == str(student.id)
    ]
    assert [row.action for row in student_audits] == ["academic.placement.created"]
