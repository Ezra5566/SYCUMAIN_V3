"""Period-scoped timetable visibility.

These fixtures are temporary, test-only periods and are rolled back with the
surrounding test transaction. They are not institutional periods and do not
define official semester dates or codes.
"""

from __future__ import annotations

from datetime import date, datetime, time

from app.models.academic import (
    AcademicPeriod,
    AcademicPeriodStatus,
    ClassSection,
    ClassSectionProgramOffering,
    ClassStatus,
    Course,
    ProgramOffering,
    TimetableEntry,
)
from app.models.admission import AcademicAdmission, AcademicPlacement
from app.models.identity import Student, StudentStatus, User
from app.services.academic import get_student_timetable, get_student_visible_class_section_ids


def _student(db, email: str, student_number: str, offering: ProgramOffering) -> Student:
    user = User(
        email=email,
        username=email.split("@")[0],
        hashed_password="not-used-by-this-test",
        full_name=f"Certification {student_number}",
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=student_number,
        first_name="Certification",
        last_name=student_number,
        status=StudentStatus.ACTIVE,
    )
    db.add(student)
    db.flush()
    now = datetime.now()
    admission = AcademicAdmission(
        student_id=student.id,
        admission_intake_id=offering.academic_period_id,
        admitted_program_id=offering.program_id,
        admitted_program_offering_id=offering.id,
        current_program_id=offering.program_id,
        status="ACTIVE",
        initial_status="ACTIVE",
        verification_status="VERIFIED",
        verified_at=now,
        activated_at=now,
        created_by_id=user.id,
    )
    db.add(admission)
    db.flush()
    db.add(
        AcademicPlacement(
            student_id=student.id,
            admission_id=admission.id,
            academic_period_id=offering.academic_period_id,
            program_offering_id=offering.id,
            effective_from=date.today(),
            created_by_id=user.id,
        )
    )
    db.flush()
    return student


def test_student_timetable_is_isolated_by_period_and_offering(db_session):
    period_a = AcademicPeriod(
        name="Certification Test Period A",
        code="CERT-TEST-PERIOD-A",
        start_date=date(2098, 1, 1),
        end_date=date(2098, 5, 1),
        status=AcademicPeriodStatus.PLANNED,
    )
    period_b = AcademicPeriod(
        name="Certification Test Period B",
        code="CERT-TEST-PERIOD-B",
        start_date=date(2098, 6, 1),
        end_date=date(2098, 10, 1),
        status=AcademicPeriodStatus.PLANNED,
    )
    db_session.add_all([period_a, period_b])
    db_session.flush()

    course_shared = Course(
        code="CERT-TEST-SHARED",
        name="Certification Test Shared Course",
        source_key="certification:test:course:shared",
    )
    course_a = Course(
        code="CERT-TEST-A",
        name="Certification Test A Course",
        source_key="certification:test:course:a",
    )
    course_b = Course(
        code="CERT-TEST-B",
        name="Certification Test B Course",
        source_key="certification:test:course:b",
    )
    db_session.add_all([course_shared, course_a, course_b])
    db_session.flush()

    offering_a1 = ProgramOffering(
        academic_period_id=period_a.id,
        source_id="CERT-TEST-A1",
        source_key="certification:test:offering:a1",
        name="Certification Test Offering A1",
    )
    offering_a2 = ProgramOffering(
        academic_period_id=period_a.id,
        source_id="CERT-TEST-A2",
        source_key="certification:test:offering:a2",
        name="Certification Test Offering A2",
    )
    offering_b1 = ProgramOffering(
        academic_period_id=period_b.id,
        source_id="CERT-TEST-B1",
        source_key="certification:test:offering:b1",
        name="Certification Test Offering B1",
    )
    db_session.add_all([offering_a1, offering_a2, offering_b1])
    db_session.flush()

    shared = ClassSection(
        course_id=course_shared.id,
        academic_period_id=period_a.id,
        section_code="CERT-TEST-SHARED",
        capacity=10,
        enrolled_count=0,
        status=ClassStatus.ACTIVE,
        source_label="Certification test shared section",
        source_key="certification:test:section:shared",
    )
    a_only = ClassSection(
        course_id=course_a.id,
        academic_period_id=period_a.id,
        section_code="CERT-TEST-A",
        capacity=10,
        enrolled_count=0,
        status=ClassStatus.ACTIVE,
        source_label="Certification test A section",
        source_key="certification:test:section:a",
    )
    b_only = ClassSection(
        course_id=course_b.id,
        academic_period_id=period_b.id,
        section_code="CERT-TEST-B",
        capacity=10,
        enrolled_count=0,
        status=ClassStatus.ACTIVE,
        source_label="Certification test B section",
        source_key="certification:test:section:b",
    )
    db_session.add_all([shared, a_only, b_only])
    db_session.flush()

    db_session.add_all(
        [
            ClassSectionProgramOffering(
                class_section_id=shared.id,
                program_offering_id=offering_a1.id,
            ),
            ClassSectionProgramOffering(
                class_section_id=shared.id,
                program_offering_id=offering_a2.id,
            ),
            ClassSectionProgramOffering(
                class_section_id=a_only.id,
                program_offering_id=offering_a1.id,
            ),
            ClassSectionProgramOffering(
                class_section_id=b_only.id,
                program_offering_id=offering_b1.id,
            ),
        ]
    )
    db_session.add_all(
        [
            TimetableEntry(
                class_section_id=shared.id,
                day_of_week=0,
                start_time=time(8, 20),
                end_time=time(10, 0),
            ),
            TimetableEntry(
                class_section_id=a_only.id,
                day_of_week=1,
                start_time=time(8, 20),
                end_time=time(10, 0),
            ),
            TimetableEntry(
                class_section_id=b_only.id,
                day_of_week=2,
                start_time=time(8, 20),
                end_time=time(10, 0),
            ),
        ]
    )
    db_session.flush()

    student_a = _student(
        db_session,
        "period.scope.a@example.invalid",
        "CERT-PERIOD-A-001",
        offering_a1,
    )
    student_b = _student(
        db_session,
        "period.scope.b@example.invalid",
        "CERT-PERIOD-B-001",
        offering_b1,
    )

    a_ids = get_student_visible_class_section_ids(
        db_session, student_a.id, period_id=period_a.id
    )
    b_ids = get_student_visible_class_section_ids(
        db_session, student_b.id, period_id=period_b.id
    )

    assert a_ids == {shared.id, a_only.id}
    assert b_ids == {b_only.id}
    assert a_ids.isdisjoint({b_only.id})
    assert b_ids.isdisjoint({shared.id, a_only.id})

    a_sections = {
        entry.section_code
        for entry in get_student_timetable(db_session, student_a.id, period_a.id)
    }
    b_sections = {
        entry.section_code
        for entry in get_student_timetable(db_session, student_b.id, period_b.id)
    }

    assert a_sections == {"CERT-TEST-SHARED", "CERT-TEST-A"}
    assert b_sections == {"CERT-TEST-B"}
    assert get_student_timetable(db_session, student_a.id, period_b.id) == []
    assert get_student_timetable(db_session, student_b.id, period_a.id) == []
