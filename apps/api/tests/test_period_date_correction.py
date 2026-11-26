"""Phase 5: controlled intake date correction.

All records are synthetic and live inside the test transaction, except the
concurrency test, which uses two independent sessions against the dedicated
test database. No existing admission, placement, academic or immigration row is
moved by a correction.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, time
from queue import Queue

import pytest

from app.auth.service import hash_password
from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.models.academic import (
    AcademicPeriod,
    Assessment,
    AssessmentType,
    AttendanceRecord,
    AttendanceStatus,
    ClassSection,
    Course,
    Enrollment,
    Grade,
    Major,
    Program,
    ProgramOffering,
    TimetableEntry,
)
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionChange,
    AcademicPeriodDateCorrection,
    AcademicPlacement,
)
from app.models.audit import AuditLog
from app.models.identity import Student, User
from app.routers import academic as academic_router
from app.schemas.academic import AcademicPeriodDateCorrectionCreate
from app.services import period_correction as svc

API = "/api/v1"

# Fixtures created by the helpers below represent state that already exists
# before the request under test, so they are committed — not merely flushed.
# The client fixture runs the application inside a savepoint of the outer test
# transaction; an endpoint that correctly rolls back after a refused correction
# (403/404/422) rolls back to that savepoint, and anything the test had only
# flushed would disappear with it. Committing releases a savepoint without
# leaving the outer transaction, so teardown still removes every row.


@pytest.fixture(autouse=True)
def phase_five_flag(monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMISSION_DATE_CORRECTION_ENABLED", True)


def _login(client, email: str = "admin@school.portal") -> None:
    response = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200, response.text


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def _mk_student(db, tag: str) -> Student:
    user = User(
        email=f"phase5-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"phase5-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Phase Five {tag}",
        is_active=True,
    )
    db.add(user)
    db.commit()
    student = Student(
        user_id=user.id,
        student_id=f"P5-{tag}-{uuid.uuid4().hex[:6]}",
        first_name="Phase",
        last_name=tag,
    )
    db.add(student)
    db.commit()
    return student


def _mk_period(
    db,
    tag: str,
    *,
    start: date = date(2033, 9, 1),
    end: date = date(2033, 12, 20),
    status: str = "ACTIVE",
    period_id: uuid.UUID | None = None,
) -> AcademicPeriod:
    period = AcademicPeriod(
        id=period_id,
        code=f"P5-{uuid.uuid4().hex[:12]}",
        name=f"Phase Five Intake {tag}",
        start_date=start,
        end_date=end,
        status=status,
    )
    db.add(period)
    db.commit()
    return period


def _mk_program(db, tag: str) -> Program:
    major = Major(code=f"M5-{uuid.uuid4().hex[:12]}", name=f"Phase Five Major {tag}")
    db.add(major)
    db.commit()
    program = Program(
        major_id=major.id,
        code=f"PP-{uuid.uuid4().hex[:12]}",
        name=f"Phase Five Program {tag}",
    )
    db.add(program)
    db.commit()
    return program


def _mk_offering(db, tag: str, period: AcademicPeriod, program: Program) -> ProgramOffering:
    offering = ProgramOffering(
        academic_period_id=period.id,
        program_id=program.id,
        source_id=f"p5-{tag}-{uuid.uuid4().hex[:6]}",
        source_key=f"phase5-{tag}-{uuid.uuid4().hex[:8]}",
        name=f"Phase Five Offering {tag}",
    )
    db.add(offering)
    db.commit()
    return offering


def _mk_admission(
    db,
    student: Student,
    period: AcademicPeriod,
    offering: ProgramOffering,
    program: Program,
    *,
    actor: User,
    status: str = "PENDING",
) -> AcademicAdmission:
    now = datetime.now()
    admission = AcademicAdmission(
        student_id=student.id,
        admission_intake_id=period.id,
        admitted_program_id=program.id,
        admitted_program_offering_id=offering.id,
        current_program_id=program.id,
        status=status,
        initial_status=status,
        record_origin="NEW_ADMISSION",
        verification_status="VERIFIED",
        verified_at=now,
        activated_at=now if status in ("ADMITTED", "ACTIVE") else None,
        ended_at=now if status in ("COMPLETED", "WITHDRAWN", "CANCELLED") else None,
        created_by_id=actor.id,
    )
    db.add(admission)
    db.commit()
    return admission


def _mk_section(
    db, tag: str, period: AcademicPeriod, program: Program
) -> ClassSection:
    course = Course(
        program_id=program.id,
        code=f"C5-{uuid.uuid4().hex[:12]}",
        name=f"Phase Five Course {tag}",
    )
    db.add(course)
    db.commit()
    section = ClassSection(
        course_id=course.id,
        academic_period_id=period.id,
        section_code=f"0{uuid.uuid4().hex[:2]}",
        capacity=30,
    )
    db.add(section)
    db.commit()
    return section


def _valid_body(start: str = "2033-09-10", end: str = "2033-12-15"):
    return {
        "new_start_date": start,
        "new_end_date": end,
        "reason": "Registrar confirmed the official dates were transcribed incorrectly.",
    }


def test_correction_requires_reason_permission_and_a_valid_range(client, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMISSION_DATE_CORRECTION_ENABLED", False)
    _login(client)
    period = _mk_period(db_session, "flag")
    disabled = client.post(
        f"{API}/academics/periods/{period.id}/date-correction", json=_valid_body()
    )
    assert disabled.status_code == 403
    assert _error_code(disabled) == "PERIOD_CORRECTION_DISABLED"

    monkeypatch.setattr(get_settings(), "ADMISSION_DATE_CORRECTION_ENABLED", True)

    missing_reason = client.post(
        f"{API}/academics/periods/{period.id}/date-correction",
        json={"new_start_date": "2033-09-10", "new_end_date": "2033-12-15"},
    )
    assert missing_reason.status_code == 422
    assert _error_code(missing_reason) == "PERIOD_CORRECTION_REASON_REQUIRED"

    inverted = client.post(
        f"{API}/academics/periods/{period.id}/date-correction",
        json={
            "new_start_date": "2033-12-15",
            "new_end_date": "2033-09-10",
            "reason": "Registrar confirmed the official dates were transcribed incorrectly.",
        },
    )
    assert inverted.status_code == 422
    assert _error_code(inverted) == "INTAKE_DATES_INVALID"

    for email in ("teacher@school.portal", "student@school.portal"):
        _login(client, email)
        forbidden = client.post(
            f"{API}/academics/periods/{period.id}/date-correction",
            json=_valid_body(),
        )
        assert forbidden.status_code == 403, email

    _login(client, "management@school.portal")
    management = client.post(
        f"{API}/academics/periods/{period.id}/date-correction", json=_valid_body()
    )
    assert management.status_code == 201, management.text


def test_completed_intake_requires_admin_while_planned_allows_management(
    client, db_session
):
    _login(client, "management@school.portal")
    completed = _mk_period(db_session, "completed", status="COMPLETED")
    refused = client.post(
        f"{API}/academics/periods/{completed.id}/date-correction",
        json=_valid_body(),
    )
    assert refused.status_code == 403
    assert _error_code(refused) == "PERIOD_CORRECTION_COMPLETED_REQUIRES_ADMIN"
    db_session.expire_all()
    assert db_session.get(AcademicPeriod, completed.id).start_date == date(2033, 9, 1)
    assert (
        db_session.query(AcademicPeriodDateCorrection)
        .filter(AcademicPeriodDateCorrection.academic_period_id == completed.id)
        .count()
        == 0
    )
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "academic.period.dates_corrected",
            AuditLog.entity_id == completed.id,
        )
        .count()
        == 0
    )

    planned = _mk_period(
        db_session,
        "planned",
        status="PLANNED",
        start=date(2040, 9, 1),
        end=date(2040, 12, 20),
    )
    allowed = client.post(
        f"{API}/academics/periods/{planned.id}/date-correction",
        json=_valid_body(start="2040-09-10", end="2040-12-15"),
    )
    assert allowed.status_code == 201, allowed.text

    active = _mk_period(
        db_session,
        "active",
        status="ACTIVE",
        start=date(2041, 9, 1),
        end=date(2041, 12, 20),
    )
    active_allowed = client.post(
        f"{API}/academics/periods/{active.id}/date-correction",
        json=_valid_body(start="2041-09-10", end="2041-12-15"),
    )
    assert active_allowed.status_code == 201, active_allowed.text

    _login(client, "admin@school.portal")
    admin_allowed = client.post(
        f"{API}/academics/periods/{completed.id}/date-correction",
        json=_valid_body(),
    )
    assert admin_allowed.status_code == 201, admin_allowed.text


def test_management_superuser_without_admin_cannot_correct_completed(
    client, db_session
):
    management = (
        db_session.query(User).filter(User.email == "management@school.portal").one()
    )
    management.is_superuser = True
    db_session.commit()
    _login(client, "management@school.portal")

    completed = _mk_period(db_session, "superuser-completed", status="COMPLETED")
    before_start = completed.start_date
    before_end = completed.end_date
    refused = client.post(
        f"{API}/academics/periods/{completed.id}/date-correction",
        json=_valid_body(),
    )
    assert refused.status_code == 403
    assert _error_code(refused) == "PERIOD_CORRECTION_COMPLETED_REQUIRES_ADMIN"

    db_session.expire_all()
    stored = db_session.get(AcademicPeriod, completed.id)
    assert stored.start_date == before_start
    assert stored.end_date == before_end
    assert (
        db_session.query(AcademicPeriodDateCorrection)
        .filter(AcademicPeriodDateCorrection.academic_period_id == completed.id)
        .count()
        == 0
    )
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "academic.period.dates_corrected",
            AuditLog.entity_id == completed.id,
        )
        .count()
        == 0
    )


def test_success_writes_one_history_row_and_one_audit_without_moving_records(
    client, db_session
):
    admin = db_session.query(User).filter(User.email == "admin@school.portal").one()
    management = (
        db_session.query(User).filter(User.email == "management@school.portal").one()
    )
    _login(client)

    _mk_period(
        db_session, "earlier", start=date(2033, 1, 10), end=date(2033, 5, 20)
    )
    period = _mk_period(db_session, "target")
    _mk_period(
        db_session, "later", start=date(2034, 2, 1), end=date(2034, 6, 20)
    )
    program = _mk_program(db_session, "target")
    offering = _mk_offering(db_session, "target", period, program)
    student = _mk_student(db_session, "success")
    admission = _mk_admission(
        db_session, student, period, offering, program, actor=admin
    )
    student.original_admission_id = admission.id
    placement = AcademicPlacement(
        student_id=student.id,
        admission_id=admission.id,
        academic_period_id=period.id,
        program_offering_id=offering.id,
        is_earlier_intake_placement=False,
        effective_from=date(2033, 9, 1),
        created_by_id=admin.id,
    )
    db_session.add(placement)
    db_session.commit()

    change = AcademicAdmissionChange(
        admission_id=admission.id,
        change_type="PROGRAM_CHANGE",
        from_program_id=program.id,
        to_program_id=_mk_program(db_session, "changed").id,
        requested_by_id=management.id,
        status="APPROVED",
        reviewed_by_id=admin.id,
        reviewed_at=datetime.now(),
    )
    db_session.add(change)

    section = _mk_section(db_session, "success", period, program)
    enrollment = Enrollment(
        student_id=student.id,
        class_section_id=section.id,
        enrolled_at=datetime(2033, 9, 12, 10, 0),
    )
    attendance = AttendanceRecord(
        student_id=student.id,
        class_section_id=section.id,
        session_date=date(2033, 10, 5),
        status=AttendanceStatus.PRESENT,
        recorded_by=admin.id,
    )
    assessment = Assessment(
        class_section_id=section.id,
        name="Phase Five assessment",
        assessment_type=AssessmentType.ASSIGNMENT,
        due_date=date(2033, 11, 1),
    )
    timetable = TimetableEntry(
        class_section_id=section.id,
        day_of_week=0,
        start_time=time(9, 0),
        end_time=time(10, 0),
    )
    db_session.add_all([enrollment, attendance, assessment, timetable])
    db_session.commit()

    before = {
        "admission_intake_id": admission.admission_intake_id,
        "admitted_program_id": admission.admitted_program_id,
        "placement_period_id": placement.academic_period_id,
        "placement_flag": placement.is_earlier_intake_placement,
        "student_pointer": student.original_admission_id,
        "change_status": change.status,
        "enrollment_at": enrollment.enrolled_at.replace(tzinfo=None),
        "attendance_date": attendance.session_date,
        "assessment_due": assessment.due_date,
        "timetable_start": timetable.start_time,
        "section_period": section.academic_period_id,
    }

    response = client.post(
        f"{API}/academics/periods/{period.id}/date-correction", json=_valid_body()
    )
    assert response.status_code == 201, response.text
    assert response.json()["previous_start_date"] == "2033-09-01"
    assert response.json()["new_start_date"] == "2033-09-10"

    db_session.expire_all()
    stored = db_session.get(AcademicPeriod, period.id)
    assert stored.start_date == date(2033, 9, 10)
    assert stored.end_date == date(2033, 12, 15)
    assert (
        db_session.query(AcademicPeriodDateCorrection)
        .filter(AcademicPeriodDateCorrection.academic_period_id == period.id)
        .count()
        == 1
    )
    audits = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.action == "academic.period.dates_corrected",
            AuditLog.entity_id == period.id,
        )
        .all()
    )
    assert len(audits) == 1
    assert audits[0].context["previous_start_date"] == "2033-09-01"
    assert audits[0].context["new_start_date"] == "2033-09-10"

    db_session.expire_all()
    assert db_session.get(AcademicAdmission, admission.id).admission_intake_id == before[
        "admission_intake_id"
    ]
    assert db_session.get(AcademicAdmission, admission.id).admitted_program_id == before[
        "admitted_program_id"
    ]
    stored_placement = db_session.get(AcademicPlacement, placement.id)
    assert stored_placement.academic_period_id == before["placement_period_id"]
    assert stored_placement.is_earlier_intake_placement == before["placement_flag"]
    assert db_session.get(Student, student.id).original_admission_id == before[
        "student_pointer"
    ]
    assert db_session.get(AcademicAdmissionChange, change.id).status == before[
        "change_status"
    ]
    assert db_session.get(Enrollment, enrollment.id).enrolled_at.replace(
        tzinfo=None
    ) == before["enrollment_at"]
    assert db_session.get(AttendanceRecord, attendance.id).session_date == before[
        "attendance_date"
    ]
    assert db_session.get(Assessment, assessment.id).due_date == before["assessment_due"]
    assert db_session.get(TimetableEntry, timetable.id).start_time == before[
        "timetable_start"
    ]
    assert db_session.get(ClassSection, section.id).academic_period_id == before[
        "section_period"
    ]

    history = client.get(f"{API}/academics/periods/{period.id}/date-corrections")
    assert history.status_code == 200, history.text
    assert len(history.json()) == 1
    assert history.json()[0]["actor_name"] == "Admin User"

    # The reversal is a new correction, using the old dates recorded above.
    reversed_response = client.post(
        f"{API}/academics/periods/{period.id}/date-correction",
        json={
            "new_start_date": "2033-09-01",
            "new_end_date": "2033-12-20",
            "reason": "The original dates were confirmed as correct after review.",
        },
    )
    assert reversed_response.status_code == 201, reversed_response.text
    db_session.expire_all()
    assert db_session.get(AcademicPeriod, period.id).start_date == date(2033, 9, 1)
    assert (
        db_session.query(AcademicPeriodDateCorrection)
        .filter(AcademicPeriodDateCorrection.academic_period_id == period.id)
        .count()
        == 2
    )


def test_successful_correction_does_not_change_grade_rows(client, db_session):
    admin = db_session.query(User).filter(User.email == "admin@school.portal").one()
    _login(client)
    period = _mk_period(db_session, "grade-preservation")
    program = _mk_program(db_session, "grade-preservation")
    student = _mk_student(db_session, "grade-preservation")
    section = _mk_section(db_session, "grade-preservation", period, program)
    assessment = Assessment(
        class_section_id=section.id,
        name="Grade preservation assessment",
        assessment_type=AssessmentType.MIDTERM,
        max_score=100,
        due_date=date(2033, 10, 10),
    )
    db_session.add(assessment)
    db_session.commit()
    grade = Grade(
        assessment_id=assessment.id,
        student_id=student.id,
        score=87.5,
        letter_grade="A",
        recorded_by=admin.id,
        note="Synthetic grade preserved across date correction.",
    )
    db_session.add(grade)
    db_session.commit()
    before = {
        "id": grade.id,
        "assessment_id": grade.assessment_id,
        "student_id": grade.student_id,
        "score": grade.score,
        "letter_grade": grade.letter_grade,
        "recorded_by": grade.recorded_by,
        "note": grade.note,
        "created_at": grade.created_at.replace(tzinfo=None),
        "updated_at": grade.updated_at.replace(tzinfo=None),
    }

    response = client.post(
        f"{API}/academics/periods/{period.id}/date-correction", json=_valid_body()
    )
    assert response.status_code == 201, response.text

    db_session.expire_all()
    stored = db_session.get(Grade, before["id"])
    assert stored is not None
    assert stored.assessment_id == before["assessment_id"]
    assert stored.student_id == before["student_id"]
    assert stored.score == before["score"]
    assert stored.letter_grade == before["letter_grade"]
    assert stored.recorded_by == before["recorded_by"]
    assert stored.note == before["note"]
    assert stored.created_at.replace(tzinfo=None) == before["created_at"]
    assert stored.updated_at.replace(tzinfo=None) == before["updated_at"]


@pytest.mark.parametrize("kind", ["enrollment", "attendance", "assessment", "timetable"])
def test_academic_record_outside_corrected_term_is_refused(
    client, db_session, kind
):
    admin = db_session.query(User).filter(User.email == "admin@school.portal").one()
    _login(client)
    period = _mk_period(db_session, f"conflict-{kind}")
    _mk_period(
        db_session, f"before-{kind}", start=date(2032, 1, 1), end=date(2032, 5, 1)
    )
    _mk_period(
        db_session, f"after-{kind}", start=date(2034, 1, 1), end=date(2034, 5, 1)
    )
    program = _mk_program(db_session, f"conflict-{kind}")
    student = _mk_student(db_session, f"conflict-{kind}")
    section = _mk_section(db_session, f"conflict-{kind}", period, program)

    if kind == "enrollment":
        db_session.add(
            Enrollment(
                student_id=student.id,
                class_section_id=section.id,
                enrolled_at=datetime(2033, 9, 1, 10, 0),
            )
        )
    elif kind == "attendance":
        db_session.add(
            AttendanceRecord(
                student_id=student.id,
                class_section_id=section.id,
                session_date=date(2033, 9, 1),
                status=AttendanceStatus.PRESENT,
                recorded_by=admin.id,
            )
        )
    elif kind == "assessment":
        db_session.add(
            Assessment(
                class_section_id=section.id,
                name="Outside term",
                assessment_type=AssessmentType.QUIZ,
                due_date=date(2033, 9, 1),
            )
        )
    else:
        db_session.add(
            TimetableEntry(
                class_section_id=section.id,
                day_of_week=0,
                start_time=time(9, 0),
                end_time=time(10, 0),
            )
        )
    db_session.commit()

    body = _valid_body()
    if kind == "timetable":
        body = {
            "new_start_date": "2033-09-06",
            "new_end_date": "2033-09-06",
            "reason": "Registrar confirmed the official dates were transcribed incorrectly.",
        }

    response = client.post(
        f"{API}/academics/periods/{period.id}/date-correction", json=body
    )
    assert response.status_code == 409
    assert _error_code(response) == "PERIOD_DATES_CONFLICT_WITH_ACADEMIC_RECORD"
    db_session.expire_all()
    assert db_session.get(AcademicPeriod, period.id).start_date == date(2033, 9, 1)
    assert (
        db_session.query(AcademicPeriodDateCorrection)
        .filter(AcademicPeriodDateCorrection.academic_period_id == period.id)
        .count()
        == 0
    )


@pytest.mark.parametrize("direction", ["before-predecessor", "after-successor"])
def test_correction_cannot_reorder_intakes(client, db_session, direction):
    _login(client)
    _mk_period(
        db_session, f"prev-{direction}", start=date(2033, 1, 1), end=date(2033, 4, 1)
    )
    period = _mk_period(db_session, f"target-{direction}")
    _mk_period(
        db_session, f"next-{direction}", start=date(2034, 1, 1), end=date(2034, 4, 1)
    )
    body = _valid_body()
    if direction == "before-predecessor":
        body = _valid_body(start="2032-12-01", end="2033-03-01")
    else:
        body = _valid_body(start="2034-02-01", end="2034-05-01")

    response = client.post(
        f"{API}/academics/periods/{period.id}/date-correction", json=body
    )
    assert response.status_code == 409
    assert _error_code(response) == "PERIOD_CORRECTION_REORDERS_ADMISSION_HISTORY"


def test_correction_cannot_move_before_a_students_verified_admission(
    client, db_session
):
    admin = db_session.query(User).filter(User.email == "admin@school.portal").one()
    _login(client)
    _mk_period(
        db_session, "verified-prev", start=date(2039, 1, 1), end=date(2039, 5, 1)
    )
    # Same start date, target before sibling by id: global ordering alone would
    # not catch moving the target earlier, so the per-student rule must.
    target = _mk_period(
        db_session,
        "verified-target",
        start=date(2040, 9, 1),
        end=date(2040, 12, 20),
        period_id=uuid.UUID(int=1),
    )
    sibling = _mk_period(
        db_session,
        "verified-sibling",
        start=date(2040, 9, 1),
        end=date(2041, 1, 20),
        period_id=uuid.UUID(int=2),
    )
    program = _mk_program(db_session, "verified-order")
    student = _mk_student(db_session, "verified-order")
    target_admission = _mk_admission(
        db_session,
        student,
        target,
        _mk_offering(db_session, "verified-target", target, program),
        program,
        actor=admin,
    )
    _mk_admission(
        db_session,
        student,
        sibling,
        _mk_offering(db_session, "verified-sibling", sibling, program),
        program,
        actor=admin,
    )

    response = client.post(
        f"{API}/academics/periods/{target.id}/date-correction",
        json=_valid_body(start="2040-08-15", end="2040-12-20"),
    )
    assert response.status_code == 409
    assert _error_code(response) == "PERIOD_CORRECTION_REORDERS_ADMISSION_HISTORY"
    db_session.expire_all()
    assert db_session.get(AcademicPeriod, target.id).start_date == date(2040, 9, 1)
    assert db_session.get(AcademicAdmission, target_admission.id).admission_intake_id == target.id


def test_placement_reflagging_refuses_unauthorized_then_accepts_authorized(
    client, db_session
):
    admin = db_session.query(User).filter(User.email == "admin@school.portal").one()
    _login(client)
    # Same start date as the admission intake, with the placement intake sorted
    # before it. Moving the placement intake earlier does not cross a period
    # boundary, but it does change the earlier-intake relationship.
    target = _mk_period(
        db_session,
        "placement-target",
        start=date(2033, 9, 1),
        end=date(2033, 12, 20),
        period_id=uuid.UUID(int=1),
    )
    admission_period = _mk_period(
        db_session,
        "placement-admission",
        start=date(2033, 9, 1),
        end=date(2034, 1, 20),
        period_id=uuid.UUID(int=2),
    )
    program = _mk_program(db_session, "placement")
    target_offering = _mk_offering(db_session, "placement-target", target, program)
    admission_offering = _mk_offering(
        db_session, "placement-admission", admission_period, program
    )
    student = _mk_student(db_session, "placement")
    admission = _mk_admission(
        db_session,
        student,
        admission_period,
        admission_offering,
        program,
        actor=admin,
    )
    placement = AcademicPlacement(
        student_id=student.id,
        admission_id=admission.id,
        academic_period_id=target.id,
        program_offering_id=target_offering.id,
        is_earlier_intake_placement=False,
        effective_from=date(2033, 9, 1),
        created_by_id=admin.id,
    )
    db_session.add(placement)
    db_session.commit()

    body = _valid_body(start="2033-08-15", end="2033-12-20")
    refused = client.post(
        f"{API}/academics/periods/{target.id}/date-correction", json=body
    )
    assert refused.status_code == 409
    assert _error_code(refused) == "PERIOD_CORRECTION_REQUIRES_PLACEMENT_AUTHORIZATION"

    db_session.expire_all()
    placement = db_session.get(AcademicPlacement, placement.id)
    placement.authorized_by_id = admin.id
    placement.authorization_reason = "Approved by the international office."
    db_session.commit()

    allowed = client.post(
        f"{API}/academics/periods/{target.id}/date-correction", json=body
    )
    assert allowed.status_code == 201, allowed.text
    db_session.expire_all()
    stored = db_session.get(AcademicPlacement, placement.id)
    assert stored.is_earlier_intake_placement is True
    assert stored.authorized_by_id == admin.id
    assert stored.academic_period_id == target.id

    # Moving back to the original date stops the placement being earlier; the
    # authorization record is retained rather than stripped.
    reversed_correction = client.post(
        f"{API}/academics/periods/{target.id}/date-correction",
        json=_valid_body(start="2033-09-01", end="2033-12-20"),
    )
    assert reversed_correction.status_code == 201, reversed_correction.text
    db_session.expire_all()
    restored = db_session.get(AcademicPlacement, placement.id)
    assert restored.is_earlier_intake_placement is False
    assert restored.authorized_by_id == admin.id
    assert restored.authorization_reason == "Approved by the international office."
    assert restored.academic_period_id == target.id


def test_patch_date_edits_are_refused_once_dependants_exist(client, db_session):
    _login(client)
    period = _mk_period(db_session, "patch-dependant")
    program = _mk_program(db_session, "patch-dependant")
    _mk_offering(db_session, "patch-dependant", period, program)

    refused = client.patch(
        f"{API}/academics/periods/{period.id}",
        json={"start_date": "2033-09-10"},
    )
    assert refused.status_code == 409
    assert _error_code(refused) == "USE_PERIOD_DATE_CORRECTION"

    renamed = client.patch(
        f"{API}/academics/periods/{period.id}",
        json={"name": "Phase Five renamed intake"},
    )
    assert renamed.status_code == 200, renamed.text

    completed = _mk_period(db_session, "patch-completed", status="COMPLETED")
    completed_refused = client.patch(
        f"{API}/academics/periods/{completed.id}",
        json={"start_date": "2033-09-10"},
    )
    assert completed_refused.status_code == 409
    assert _error_code(completed_refused) == "USE_PERIOD_DATE_CORRECTION"

    free = _mk_period(db_session, "patch-free")
    edited = client.patch(
        f"{API}/academics/periods/{free.id}",
        json={"start_date": "2033-09-10", "end_date": "2033-12-15"},
    )
    assert edited.status_code == 200, edited.text
    db_session.expire_all()
    assert db_session.get(AcademicPeriod, free.id).start_date == date(2033, 9, 10)


def test_audit_failure_rolls_back_dates_and_history(client, db_session, monkeypatch):
    _login(client)
    period = _mk_period(db_session, "audit-failure")

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(academic_router, "record_audit", fail_audit)
    with pytest.raises(RuntimeError):
        client.post(
            f"{API}/academics/periods/{period.id}/date-correction",
            json=_valid_body(),
        )

    db_session.expire_all()
    assert db_session.get(AcademicPeriod, period.id).start_date == date(2033, 9, 1)
    assert (
        db_session.query(AcademicPeriodDateCorrection)
        .filter(AcademicPeriodDateCorrection.academic_period_id == period.id)
        .count()
        == 0
    )


def test_concurrent_identical_corrections_produce_one_success():
    setup = SessionLocal()
    period = None
    try:
        admin = setup.query(User).filter(User.email == "admin@school.portal").one()
        period = _mk_period(setup, "concurrent")
        setup.commit()
        period_id = period.id
        actor_id = admin.id
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    results: Queue[tuple[str, str]] = Queue()

    def attempt():
        worker = SessionLocal()
        try:
            actor = worker.get(User, actor_id)
            data = AcademicPeriodDateCorrectionCreate(
                new_start_date=date(2033, 9, 10),
                new_end_date=date(2033, 12, 15),
                reason="Registrar confirmed the official dates were transcribed incorrectly.",
            )
            barrier.wait(timeout=10)
            svc.correct_period_dates(worker, period_id, data, actor=actor)
            worker.commit()
            results.put(("ok", ""))
        except Exception as exc:  # noqa: BLE001 - collected for assertion
            results.put(("error", str(exc)))
        finally:
            worker.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    outcomes = [results.get_nowait() for _ in range(2)]
    assert sum(1 for kind, _ in outcomes if kind == "ok") == 1, outcomes
    assert any(
        "same as the current dates" in message
        for kind, message in outcomes
        if kind == "error"
    ), outcomes

    cleanup = SessionLocal()
    try:
        cleanup.query(AcademicPeriodDateCorrection).filter(
            AcademicPeriodDateCorrection.academic_period_id == period_id
        ).delete(synchronize_session=False)
        cleanup.query(AcademicPeriod).filter(AcademicPeriod.id == period_id).delete(
            synchronize_session=False
        )
        cleanup.commit()
    finally:
        cleanup.close()
