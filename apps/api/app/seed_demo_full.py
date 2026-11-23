"""Rich demonstration dataset for the SYCUMAIN_V2 clone.

The reference seeder intentionally creates only the four login accounts and a
skeleton catalogue. That leaves most operational screens empty, which makes a
functional check impossible. This module adds one coherent, realistic cohort on
top of those seeds:

* 25 international students (26 including ``STU-001``) with admissions and
  placements in the active period;
* passport/visa/permit profiles spanning valid, expiring and expired states;
* active and ended housing assignments, with dormitory absences (including one
  correction and one cancellation);
* enrollments, a published examination with results and four upcoming ones;
* attendance commencements and absences on the university calendar;
* two vacation ranges and public holidays;
* documents with real PDF bytes, in review states from approved to pending;
* support tickets and in-app notifications for all three staff/student roles.

Everything is created in a single transaction and is idempotent: the presence
of ``STU-101`` means the dataset already exists. It only runs when the
application is configured to seed demonstration data, which production
configuration forbids.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

from app.auth.service import hash_password
from app.models.academic import (
    AcademicPeriod,
    AcademicPeriodStatus,
    ClassSection,
    ClassSectionProgramOffering,
    Course,
    Enrollment,
    EnrollmentStatus,
    Program,
    ProgramOffering,
)
from app.models.admission import AcademicAdmission, AcademicPlacement
from app.models.attendance import AttendanceCommencement
from app.models.attendance_absence import AttendanceAbsence
from app.models.calendar import (
    CalendarDayType,
    CalendarVacationRange,
    UniversityCalendarDay,
)
from app.models.dormitory_absence import DormitoryAbsence
from app.models.examination import (
    Examination,
    ExaminationResult,
    ExaminationSection,
    ExaminationStatus,
)
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
)
from app.models.identity import Role, Student, StudentStatus, User
from app.models.immigration import ImmigrationProfile
from app.models.platform import (
    Document,
    DocumentReviewStatus,
    DocumentScanStatus,
    DocumentStatus,
    DocumentVisibility,
    Notification,
    NotificationType,
    SupportTicket,
    SupportTicketCategory,
    SupportTicketMessage,
    SupportTicketStatus,
)
from app.storage import get_storage

DEMO_PASSWORD = "password123"
ACTIVE_PERIOD_CODE = "2026-FALL"
TERM_START = date(2026, 9, 1)


# --- The cohort -------------------------------------------------------------
# (student number, first, last, gender, nationality, programme, status, city)
STUDENTS: tuple[tuple[str, str, str, str, str, str, StudentStatus, str], ...] = (
    ("STU-101", "Noor", "Al-Sayed", "Female", "Egypt", "BCS", StudentStatus.ACTIVE, "Cairo"),
    ("STU-102", "Mateo", "Alvarez", "Male", "Mexico", "BBA", StudentStatus.ACTIVE, "Guadalajara"),
    ("STU-103", "Anaya", "Sharma", "Female", "India", "BCS", StudentStatus.ACTIVE, "Pune"),
    ("STU-104", "Kwame", "Mensah", "Male", "Ghana", "BBA", StudentStatus.ACTIVE, "Accra"),
    ("STU-105", "Sofia", "Petrova", "Female", "Bulgaria", "BAL", StudentStatus.ACTIVE, "Plovdiv"),
    ("STU-106", "Chen", "Hao", "Male", "China", "BCS", StudentStatus.ACTIVE, "Shenyang"),
    ("STU-107", "Amina", "Yusuf", "Female", "Nigeria", "BBA", StudentStatus.ACTIVE, "Kano"),
    ("STU-108", "Lucas", "Silva", "Male", "Brazil", "BAL", StudentStatus.ACTIVE, "Recife"),
    ("STU-109", "Priya", "Nair", "Female", "India", "BCS", StudentStatus.ACTIVE, "Kochi"),
    ("STU-110", "Omar", "Haddad", "Male", "Jordan", "BBA", StudentStatus.ACTIVE, "Irbid"),
    ("STU-111", "Yuki", "Tanaka", "Female", "Japan", "BAL", StudentStatus.ACTIVE, "Fukuoka"),
    ("STU-112", "Fatima", "Zahra", "Female", "Morocco", "BBA", StudentStatus.GRADUATED, "Rabat"),
    ("STU-113", "Daniel", "Kim", "Male", "South Korea", "BCS", StudentStatus.ACTIVE, "Busan"),
    ("STU-114", "Elena", "Rossi", "Female", "Italy", "BAL", StudentStatus.ACTIVE, "Bologna"),
    ("STU-115", "Ahmed", "Farouk", "Male", "Egypt", "BCS", StudentStatus.ACTIVE, "Alexandria"),
    ("STU-116", "Maria", "Garcia", "Female", "Spain", "BBA", StudentStatus.ACTIVE, "Valencia"),
    ("STU-117", "Ivan", "Volkov", "Male", "Russia", "BCS", StudentStatus.ACTIVE, "Kazan"),
    ("STU-118", "Leila", "Hosseini", "Female", "Iran", "BAL", StudentStatus.ACTIVE, "Shiraz"),
    ("STU-119", "Samuel", "Osei", "Male", "Ghana", "BCS", StudentStatus.ACTIVE, "Kumasi"),
    ("STU-120", "Hana", "Suzuki", "Female", "Japan", "BAL", StudentStatus.ACTIVE, "Kyoto"),
    ("STU-121", "Ali", "Reza", "Male", "Iran", "BBA", StudentStatus.ACTIVE, "Tehran"),
    ("STU-122", "Grace", "Njeri", "Female", "Kenya", "BCS", StudentStatus.WITHDRAWN, "Nairobi"),
    ("STU-123", "Tom", "Becker", "Male", "Germany", "BBA", StudentStatus.INACTIVE, "Leipzig"),
    ("STU-124", "Nia", "Williams", "Female", "Jamaica", "BAL", StudentStatus.ACTIVE, "Kingston"),
    ("STU-125", "Arjun", "Mehta", "Male", "India", "BCS", StudentStatus.SUSPENDED, "Delhi"),
)


def seed_demo_dataset(db: DBSession) -> None:
    """Create the demonstration cohort once. Safe to call on every startup."""
    ensure_program_offering_links(db)
    if db.query(Student).filter(Student.student_id == "STU-101").first():
        return

    admin = db.query(User).filter(User.email == "admin@school.portal").one()
    management = db.query(User).filter(User.email == "management@school.portal").one()
    teacher_user = db.query(User).filter(User.email == "teacher@school.portal").one()
    student_user = db.query(User).filter(User.email == "student@school.portal").one()
    student_role = db.query(Role).filter(Role.name == "STUDENT").one()

    period = (
        db.query(AcademicPeriod)
        .filter(AcademicPeriod.code == ACTIVE_PERIOD_CODE)
        .one_or_none()
        or db.query(AcademicPeriod)
        .filter(AcademicPeriod.status == AcademicPeriodStatus.ACTIVE)
        .first()
    )
    if period is None:
        return

    now = datetime.now(UTC)
    programmes = {p.code: p for p in db.query(Program).all()}
    offerings: dict[str, ProgramOffering] = {}
    for code in ("BCS", "BBA", "BAL"):
        offering = (
            db.query(ProgramOffering)
            .filter(ProgramOffering.source_key == f"seed:{period.code}:{code}")
            .one_or_none()
        )
        if offering is None:
            offering = ProgramOffering(
                academic_period_id=period.id,
                program_id=programmes[code].id,
                source_id=code,
                source_key=f"seed:{period.code}:{code}",
                name=programmes[code].name,
            )
            db.add(offering)
            db.flush()
        offerings[code] = offering

    # --- Existing demonstration student -----------------------------------
    existing = db.query(Student).filter(Student.student_id == "STU-001").one()
    existing.nationality = existing.nationality or "China"
    existing.phone = existing.phone or "+86 138 0000 0001"
    existing.emergency_contact_name = existing.emergency_contact_name or "Wei Zhang"
    existing.emergency_contact_phone = existing.emergency_contact_phone or "+86 138 0000 0002"
    existing.date_of_birth = existing.date_of_birth or datetime(2004, 5, 12, tzinfo=UTC)
    existing.gender = existing.gender or "Other"

    password_hash = hash_password(DEMO_PASSWORD)
    people: list[tuple[Student, str]] = [(existing, "BCS")]

    for number, first, last, gender, nationality, programme, status, _city in STUDENTS:
        username = f"{first}.{last}".lower().replace(" ", "").replace("-", "")
        email = f"{username}@student.school.portal"
        if db.query(User).filter(User.email == email).first():
            email = f"{username}.{number[-3:]}@student.school.portal"
        user = User(
            email=email,
            username=f"{username}{number[-3:]}",
            hashed_password=password_hash,
            full_name=f"{first} {last}",
            is_active=status == StudentStatus.ACTIVE,
            is_superuser=False,
        )
        user.roles.append(student_role)
        db.add(user)
        db.flush()

        birth_offset = timedelta(days=(int(number[-3:]) * 37) % 900)
        student = Student(
            user_id=user.id,
            student_id=number,
            first_name=first,
            last_name=last,
            preferred_name=first,
            date_of_birth=datetime(2003, 1, 1, tzinfo=UTC) + birth_offset,
            gender=gender,
            nationality=nationality,
            phone=f"+86 139 {number[-4:]} {number[-3:]}",
            emergency_contact_name=f"{last} Family",
            emergency_contact_phone=f"+86 137 {number[-4:]} 0000",
            status=status,
        )
        db.add(student)
        db.flush()
        people.append((student, programme))

    # --- Admissions and placements ----------------------------------------
    status_map = {
        StudentStatus.ACTIVE: "ACTIVE",
        StudentStatus.INACTIVE: "ACTIVE",
        StudentStatus.SUSPENDED: "ACTIVE",
        StudentStatus.GRADUATED: "COMPLETED",
        StudentStatus.WITHDRAWN: "WITHDRAWN",
    }
    end_reason = {
        "COMPLETED": "Programme completed; record retained for alumni services.",
        "WITHDRAWN": "Student withdrew; episode closed with an audited end reason.",
    }
    admissions: dict[uuid.UUID, AcademicAdmission] = {}
    for student, programme in people:
        admission_status = status_map[StudentStatus(student.status)]
        ended_at = None
        if admission_status in {"COMPLETED", "WITHDRAWN"}:
            ended_at = datetime(2026, 7, 31, tzinfo=UTC)
        admission = AcademicAdmission(
            student_id=student.id,
            admission_intake_id=period.id,
            admitted_program_id=programmes[programme].id,
            admitted_program_offering_id=offerings[programme].id,
            current_program_id=programmes[programme].id,
            status=admission_status,
            initial_status="ADMITTED",
            record_origin="NEW_ADMISSION",
            verification_status="VERIFIED",
            management_confirmation_state="CONFIRMED",
            management_confirmed_by_id=management.id,
            management_confirmed_at=datetime(2026, 8, 20, tzinfo=UTC),
            admin_confirmation_state="CONFIRMED",
            admin_confirmed_by_id=admin.id,
            admin_confirmed_at=datetime(2026, 8, 21, tzinfo=UTC),
            verified_at=datetime(2026, 8, 21, tzinfo=UTC),
            activated_at=datetime(2026, 9, 1, tzinfo=UTC),
            ended_at=ended_at,
            end_reason=end_reason.get(admission_status),
            created_by_id=admin.id,
        )
        db.add(admission)
        db.flush()
        admissions[student.id] = admission
        student.original_admission_id = admission.id

        if admission_status == "ACTIVE":
            db.add(
                AcademicPlacement(
                    student_id=student.id,
                    admission_id=admission.id,
                    academic_period_id=period.id,
                    program_offering_id=offerings[programme].id,
                    is_earlier_intake_placement=False,
                    effective_from=TERM_START,
                    created_by_id=admin.id,
                )
            )
    db.flush()

    # --- Enrollments in the active period ---------------------------------
    sections = (
        db.query(ClassSection)
        .filter(ClassSection.academic_period_id == period.id)
        .all()
    )
    courses = {c.id: c for c in db.query(Course).all()}
    section_by_course_program: dict[str, list[ClassSection]] = {"BCS": [], "BBA": [], "BAL": []}
    for section in sections:
        course = courses.get(section.course_id)
        if course is None or course.program_id is None:
            continue
        for code, programme in programmes.items():
            if course.program_id == programme.id:
                section_by_course_program[code].append(section)

    for student, programme in people:
        admission = admissions[student.id]
        if admission.status != "ACTIVE":
            continue
        for section in section_by_course_program.get(programme, []):
            exists = (
                db.query(Enrollment)
                .filter(
                    Enrollment.student_id == student.id,
                    Enrollment.class_section_id == section.id,
                )
                .first()
            )
            if exists is None:
                db.add(
                    Enrollment(
                        student_id=student.id,
                        class_section_id=section.id,
                        status=EnrollmentStatus.ENROLLED,
                    )
                )
    db.flush()
    for section in sections:
        section.enrolled_count = (
            db.query(Enrollment)
            .filter(
                Enrollment.class_section_id == section.id,
                Enrollment.status == EnrollmentStatus.ENROLLED,
            )
            .count()
        )

    # --- Housing -----------------------------------------------------------
    beds = (
        db.query(Bed)
        .join(Room, Room.id == Bed.room_id)
        .join(Floor, Floor.id == Room.floor_id)
        .join(Building, Building.id == Floor.building_id)
        .filter(Bed.is_active.is_(True))
        .order_by(Building.name, Floor.floor_number, Room.room_number, Bed.bed_number)
        .limit(30)
        .all()
    )
    active_students = [
        s for s, _ in people if StudentStatus(s.status) == StudentStatus.ACTIVE
    ]
    housing: dict[uuid.UUID, HousingAssignment] = {}
    for index, student in enumerate(active_students[:14]):
        assignment = HousingAssignment(
            student_id=student.user_id,
            bed_id=beds[index].id,
            start_date=datetime(2026, 9, 1, tzinfo=UTC),
            status=HousingAssignmentStatus.ACTIVE,
            notes="Allocated at the start of the autumn semester.",
            created_by_id=admin.id,
        )
        db.add(assignment)
        db.flush()
        housing[student.id] = assignment

    former = [
        s
        for s, _ in people
        if StudentStatus(s.status) in {StudentStatus.GRADUATED, StudentStatus.WITHDRAWN}
    ]
    for index, student in enumerate(former):
        assignment = HousingAssignment(
            student_id=student.user_id,
            bed_id=beds[20 + index].id,
            start_date=datetime(2025, 9, 1, tzinfo=UTC),
            end_date=datetime(2026, 6, 30, tzinfo=UTC),
            status=HousingAssignmentStatus.ENDED,
            notes="Residency ended at the close of the academic year.",
            created_by_id=admin.id,
            ended_by_id=admin.id,
            ended_at=datetime(2026, 6, 30, tzinfo=UTC),
        )
        db.add(assignment)
        db.flush()

    # --- Dormitory attendance ---------------------------------------------
    dated_reasons = [
        (date(2026, 10, 7), Decimal("1.00"), "Did not return by the 23:00 curfew."),
        (date(2026, 10, 21), Decimal("2.00"), "Overnight absence without prior leave."),
        (date(2026, 11, 4), Decimal("1.00"), "Late return recorded by the warden."),
        (date(2026, 11, 18), Decimal("3.00"), "Absent for two consecutive roll calls."),
    ]
    resident_students = [s for s in active_students if s.id in housing]
    for student, (absent_on, points, reason) in zip(
        resident_students[:4], dated_reasons, strict=False
    ):
        db.add(
            DormitoryAbsence(
                student_id=student.id,
                housing_assignment_id=housing[student.id].id,
                absence_date=absent_on,
                points=points,
                reason=reason,
                recorded_by_id=admin.id,
            )
        )
    db.flush()

    if resident_students:
        first = resident_students[0]
        original = DormitoryAbsence(
            student_id=first.id,
            housing_assignment_id=housing[first.id].id,
            absence_date=date(2026, 11, 5),
            points=Decimal("1.00"),
            reason="Curfew breach reported by the night warden.",
            recorded_by_id=admin.id,
        )
        db.add(original)
        db.flush()
        original.superseded_at = now
        db.add(
            DormitoryAbsence(
                student_id=first.id,
                housing_assignment_id=housing[first.id].id,
                absence_date=date(2026, 11, 5),
                points=Decimal("2.00"),
                reason="Corrected after the warden's log was reviewed.",
                recorded_by_id=admin.id,
                supersedes_id=original.id,
            )
        )
    if len(resident_students) > 1:
        second = resident_students[1]
        db.add(
            DormitoryAbsence(
                student_id=second.id,
                housing_assignment_id=housing[second.id].id,
                absence_date=date(2026, 11, 12),
                points=Decimal("2.00"),
                reason="Recorded against the wrong resident after a room transfer.",
                recorded_by_id=admin.id,
                cancelled_at=now,
                cancelled_by_id=admin.id,
                cancellation_reason="Cancelled: the resident was on approved leave.",
            )
        )
    db.flush()

    # --- Immigration profiles ---------------------------------------------
    expiries = [12, 25, 55, 80, 150, 300, 420, 600, -15, 20]
    for index, (student, _) in enumerate(people):
        profile = (
            db.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .one_or_none()
        )
        if profile is None:
            profile = ImmigrationProfile(student_id=student.id)
            db.add(profile)
        offset = expiries[index % len(expiries)]
        expiry = date.today() + timedelta(days=offset)
        profile.passport_number = f"P{student.student_id.replace('-', '')}"
        profile.passport_issuing_country = student.nationality
        profile.passport_issue_date = date.today() - timedelta(days=365 * 5)
        profile.passport_expiry_date = date.today() + timedelta(days=365 * 3)
        profile.passport_name_as_shown = f"{student.first_name} {student.last_name}".upper()
        profile.visa_type = "X1"
        profile.visa_number = f"V{student.student_id.replace('-', '')}"
        profile.visa_issue_date = date.today() - timedelta(days=365)
        profile.visa_expiry_date = expiry
        profile.visa_entries = "MULTIPLE"
        profile.visa_issuing_authority = "Chinese Embassy / Consulate"
        profile.residence_permit_number = f"RP{student.student_id.replace('-', '')}"
        profile.residence_permit_issue_date = date.today() - timedelta(days=180)
        profile.residence_permit_expiry_date = expiry + timedelta(days=120)
        profile.residence_permit_issuing_authority = "Shenyang Public Security Bureau"
        profile.data_source = "STAFF"
        # Leave two profiles deliberately incomplete so the dashboard's
        # "profile incomplete" metric is exercised rather than always zero.
        if index in {7, 18}:
            profile.passport_number = None
            profile.visa_number = None
        else:
            profile.verification_status = "VERIFIED"
            profile.verified_by_id = admin.id
            profile.verified_at = now
    db.flush()

    # --- University calendar and attendance --------------------------------
    ranges = (
        ("Winter vacation", date(2026, 12, 21), date(2027, 1, 8),
         "Institutional winter closure between the autumn and spring semesters."),
        ("Summer vacation", date(2027, 7, 12), date(2027, 8, 20),
         "Annual summer vacation approved by the Academic Committee."),
    )
    for title, start, end, reason in ranges:
        if db.query(CalendarVacationRange).filter(CalendarVacationRange.title == title).first():
            continue
        vacation = CalendarVacationRange(
            start_date=start,
            end_date=end,
            title=title,
            reason=reason,
            created_by_id=admin.id,
        )
        db.add(vacation)
        db.flush()
        current = start
        while current <= end:
            db.add(
                UniversityCalendarDay(
                    calendar_date=current,
                    day_type=CalendarDayType.VACATION,
                    title=title,
                    reason=reason,
                    calendar_range_id=vacation.id,
                    created_by_id=admin.id,
                )
            )
            current += timedelta(days=1)

    holidays = (
        ("National Day", date(2026, 10, 1), date(2026, 10, 3)),
        ("Mid-Autumn Festival", date(2026, 9, 25), date(2026, 9, 25)),
        ("Labour Day", date(2027, 5, 1), date(2027, 5, 1)),
        ("Dragon Boat Festival", date(2027, 6, 9), date(2027, 6, 9)),
    )
    for title, start, end in holidays:
        current = start
        while current <= end:
            exists = (
                db.query(UniversityCalendarDay)
                .filter(
                    UniversityCalendarDay.calendar_date == current,
                    UniversityCalendarDay.is_void.is_(False),
                )
                .first()
            )
            if exists is None:
                db.add(
                    UniversityCalendarDay(
                        calendar_date=current,
                        day_type=CalendarDayType.HOLIDAY,
                        title=title,
                        reason="Public holiday declared by the State Council.",
                        created_by_id=admin.id,
                    )
                )
            current += timedelta(days=1)

    for student, _ in people:
        admission = admissions[student.id]
        if admission.status != "ACTIVE":
            continue
        db.add(
            AttendanceCommencement(
                admission_id=admission.id,
                student_id=student.id,
                commencement_date=TERM_START,
                commencement_type="SCHEDULED",
                reason="Approved from the published semester start date.",
                suggested_date=TERM_START,
                approved_by_id=management.id,
            )
        )
    db.flush()

    absence_days = [
        (date(2026, 10, 6), "Medical appointment at the campus clinic."),
        (date(2026, 10, 20), "Family emergency; leave approved retrospectively."),
        (date(2026, 11, 3), "Travel disruption reported to the office."),
        (date(2026, 11, 17), "Illness; medical certificate supplied."),
    ]
    for student, (absent_on, reason) in zip(
        active_students[:4], absence_days, strict=False
    ):
        db.add(
            AttendanceAbsence(
                student_id=student.id,
                admission_id=admissions[student.id].id,
                absence_date=absent_on,
                reason=reason,
                recorded_by_id=teacher_user.id,
            )
        )
    if active_students:
        first = active_students[0]
        db.add(
            AttendanceAbsence(
                student_id=first.id,
                admission_id=admissions[first.id].id,
                absence_date=date(2026, 11, 10),
                reason="Second recorded absence; documentation pending.",
                recorded_by_id=teacher_user.id,
            )
        )
    db.flush()

    # --- Examinations ------------------------------------------------------
    section_by_code: dict[str, ClassSection] = {}
    for section in sections:
        course = courses.get(section.course_id)
        if course and course.code:
            section_by_code[course.code] = section

    def add_exam(
        *,
        title: str,
        course_code: str,
        exam_date: date,
        start: time,
        end: time,
        kind: str = "FINAL",
        location: str = "Teaching Building A · Room 201",
        max_score: Decimal | None = Decimal("100.00"),
        cancelled: bool = False,
    ) -> Examination:
        course = next(c for c in courses.values() if c.code == course_code)
        exam = Examination(
            title=title,
            examination_type=kind,
            course_id=course.id,
            academic_period_id=period.id,
            exam_date=exam_date,
            start_time=start,
            end_time=end,
            location=location,
            instructions="Bring your student card. No electronic devices permitted.",
            max_score=max_score,
            status=ExaminationStatus.CANCELLED if cancelled else ExaminationStatus.SCHEDULED,
            cancelled_at=now if cancelled else None,
            cancelled_by_id=admin.id if cancelled else None,
            cancellation_reason=(
                "Room unavailable after a facilities notice." if cancelled else None
            ),
            created_by_id=admin.id,
        )
        db.add(exam)
        db.flush()
        for section in sections:
            course_for_section = courses.get(section.course_id)
            if course_for_section and course_for_section.code == course_code:
                db.add(
                    ExaminationSection(
                        examination_id=exam.id,
                        class_section_id=section.id,
                    )
                )
        return exam

    past_exam = add_exam(
        title="CS101 Introduction to Programming · Final Examination",
        course_code="CS101",
        exam_date=date(2026, 10, 15),
        start=time(9, 0),
        end=time(11, 0),
        location="Teaching Building A · Lecture Hall 1",
    )
    add_exam(
        title="CS201 Data Structures · Final Examination",
        course_code="CS201",
        exam_date=date(2026, 12, 14),
        start=time(9, 0),
        end=time(11, 0),
    )
    add_exam(
        title="BA101 Principles of Business · Final Examination",
        course_code="BA101",
        exam_date=date(2026, 12, 15),
        start=time(9, 0),
        end=time(11, 0),
    )
    add_exam(
        title="EN101 English Composition · Final Examination",
        course_code="EN101",
        exam_date=date(2026, 12, 16),
        start=time(13, 30),
        end=time(15, 30),
    )
    add_exam(
        title="CS101 Introduction to Programming · Midterm",
        course_code="CS101",
        exam_date=date(2026, 12, 10),
        start=time(9, 0),
        end=time(10, 30),
        kind="MIDTERM",
        cancelled=True,
    )
    db.flush()

    # Results for the published, completed examination only.
    cs101_sections = [
        s for s in sections
        if courses.get(s.course_id) and courses[s.course_id].code == "CS101"
    ]
    section_ids = [s.id for s in cs101_sections]
    enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.class_section_id.in_(section_ids),
            Enrollment.status == EnrollmentStatus.ENROLLED,
        )
        .all()
    ) if section_ids else []
    seen: set[uuid.UUID] = set()
    for index, enrollment in enumerate(enrolled):
        if enrollment.student_id in seen:
            continue
        seen.add(enrollment.student_id)
        score = Decimal(str(58 + (index * 7) % 41))
        grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D"
        db.add(
            ExaminationResult(
                examination_id=past_exam.id,
                student_id=enrollment.student_id,
                score=score,
                letter_grade=grade,
                note=None,
                recorded_by_id=teacher_user.id,
            )
        )
    past_exam.published_at = now
    past_exam.published_by_id = admin.id
    db.flush()

    # --- Documents ---------------------------------------------------------
    storage = get_storage()
    document_plan = [
        (
            "STU-001",
            "PASSPORT",
            "Passport · identity page",
            DocumentReviewStatus.APPROVED,
            True,
        ),
        (
            "STU-001",
            "VISA",
            "Student visa (X1) · current",
            DocumentReviewStatus.APPROVED,
            True,
        ),
        (
            "STU-001",
            "INSURANCE",
            "Medical insurance certificate",
            DocumentReviewStatus.PENDING,
            True,
        ),
        (
            "STU-001",
            "ADMISSION",
            "Admission letter · Fall 2026",
            DocumentReviewStatus.APPROVED,
            False,
        ),
        (
            "STU-101",
            "PASSPORT",
            "Passport · Noor Al-Sayed",
            DocumentReviewStatus.APPROVED,
            True,
        ),
        (
            "STU-101",
            "VISA",
            "Residence permit application receipt",
            DocumentReviewStatus.UNDER_REVIEW,
            True,
        ),
        (
            "STU-102",
            "PASSPORT",
            "Passport · Mateo Alvarez",
            DocumentReviewStatus.APPROVED,
            True,
        ),
        (
            "STU-102",
            "VISA",
            "Student visa · Mateo Alvarez",
            DocumentReviewStatus.APPROVED,
            True,
        ),
        (
            "STU-103",
            "PASSPORT",
            "Passport · Anaya Sharma",
            DocumentReviewStatus.APPROVED,
            True,
        ),
        (
            "STU-103",
            "VISA",
            "Student visa · Anaya Sharma",
            DocumentReviewStatus.PENDING,
            True,
        ),
        (
            "STU-104",
            "PASSPORT",
            "Passport · Kwame Mensah",
            DocumentReviewStatus.APPROVED,
            True,
        ),
        (
            "STU-105",
            "ACCOMMODATION",
            "Dormitory acceptance form",
            DocumentReviewStatus.APPROVED,
            False,
        ),
        (
            "STU-106",
            "PASSPORT",
            "Passport · Chen Hao",
            DocumentReviewStatus.PENDING,
            True,
        ),
        (
            "STU-107",
            "VISA",
            "Student visa · Amina Yusuf",
            DocumentReviewStatus.UNDER_REVIEW,
            True,
        ),
    ]
    student_by_number = {s.student_id: s for s, _ in people}
    for index, (number, doc_type, title, review, required) in enumerate(document_plan):
        student = student_by_number[number]
        body = _pdf(
            title,
            [
                "Shenyang City University",
                "International Student Office · Demonstration document",
                f"Student: {student.first_name} {student.last_name} ({student.student_id})",
                f"Document type: {doc_type}",
                "This file was generated for the SYCUMAIN_V2 local demonstration.",
            ],
        )
        key = f"seed/{student.student_id}/{uuid.uuid4()}.pdf"
        stored = storage.save(key, body, "application/pdf")
        approved = review in {DocumentReviewStatus.APPROVED, DocumentReviewStatus.REJECTED}
        db.add(
            Document(
                student_id=student.id,
                uploaded_by=admin.id,
                document_type=doc_type,
                title=title,
                description="Demonstration record created with the local seed.",
                storage_provider=stored.provider,
                object_key=stored.key,
                original_filename=f"{doc_type.lower()}-{student.student_id.lower()}.pdf",
                content_type="application/pdf",
                file_size=stored.size,
                checksum_sha256=hashlib.sha256(body).hexdigest(),
                visibility=DocumentVisibility.STUDENT_VISIBLE,
                status=DocumentStatus.ACTIVE,
                review_status=review,
                reviewed_by=admin.id if approved else None,
                reviewed_at=now if approved else None,
                scan_status=DocumentScanStatus.CLEAN,
                scan_engine="dev-clean",
                scanned_at=now,
                is_required=required,
                expires_on=date.today() + timedelta(days=200 + index * 30),
            )
        )

    # --- Support tickets ---------------------------------------------------
    ticket_plan = [
        (
            "STU-101",
            SupportTicketCategory.VISA_IMMIGRATION,
            "HIGH",
            SupportTicketStatus.OPEN,
            "Residence permit renewal appointment",
            (
                "My residence permit expires in three weeks and the online booking "
                "system shows no appointments. Could the office advise on the next step?"
            ),
            (
                "We have requested an earlier slot from the Public Security Bureau. "
                "Please bring your passport and the receipt to the office on Monday."
            ),
        ),
        (
            "STU-102",
            SupportTicketCategory.HOUSING,
            "NORMAL",
            SupportTicketStatus.IN_PROGRESS,
            "Hot water interruption in Building 19",
            (
                "There has been no hot water on the third floor since Friday "
                "evening."
            ),
            (
                "Facilities have been notified and a technician is scheduled for "
                "tomorrow morning."
            ),
        ),
        (
            "STU-103",
            SupportTicketCategory.ACADEMIC,
            "NORMAL",
            SupportTicketStatus.WAITING_FOR_STUDENT,
            "Timetable clash between CS201 and EN101",
            (
                "Two of my classes overlap on Wednesday morning. I would like to "
                "discuss an alternative section."
            ),
            (
                "We can move you to the Thursday EN101 group. Please confirm "
                "whether that works before Friday."
            ),
        ),
    ]
    for index, (
        number,
        category,
        priority,
        status,
        subject,
        description,
        reply,
    ) in enumerate(ticket_plan):
        student = student_by_number[number]
        ticket = SupportTicket(
            ticket_number=f"SUP-20{index + 1:02d}",
            student_id=student.id,
            created_by=student.user_id,
            assigned_to=admin.id,
            category=category,
            subject=subject,
            description=description,
            status=status,
            priority=priority,
        )
        db.add(ticket)
        db.flush()
        db.add(
            SupportTicketMessage(
                ticket_id=ticket.id,
                author_id=student.user_id,
                body=description,
                is_internal=False,
            )
        )
        db.add(
            SupportTicketMessage(
                ticket_id=ticket.id,
                author_id=admin.id,
                body=reply,
                is_internal=False,
            )
        )
        db.add(
            SupportTicketMessage(
                ticket_id=ticket.id,
                author_id=admin.id,
                body="Internal note: verified the student's record before replying.",
                is_internal=True,
            )
        )

    # --- Notifications -----------------------------------------------------
    notification_plan = [
        (
            admin.id,
            NotificationType.SUPPORT_TICKET_CREATED,
            "A new visa renewal ticket needs triage.",
            "/app/support",
        ),
        (
            admin.id,
            NotificationType.DOCUMENT_UPLOADED,
            "Documents are waiting for review.",
            "/app/documents",
        ),
        (
            admin.id,
            NotificationType.IMMIGRATION_EXPIRY_URGENT,
            "Two residence permits expire within 30 days.",
            "/app/immigration",
        ),
        (
            admin.id,
            NotificationType.ANNOUNCEMENT_PUBLISHED,
            "Autumn examination guidance was published.",
            "/app/announcements",
        ),
        (
            student_user.id,
            NotificationType.HOUSING_ASSIGNMENT_CREATED,
            "Your room allocation is confirmed.",
            "/app/profile",
        ),
        (
            student_user.id,
            NotificationType.IMMIGRATION_EXPIRY_URGENT,
            "Your residence permit expires soon.",
            "/app/profile",
        ),
        (
            student_user.id,
            NotificationType.DOCUMENT_UPLOADED,
            "Your insurance certificate is under review.",
            "/app/documents",
        ),
        (
            teacher_user.id,
            NotificationType.ANNOUNCEMENT_PUBLISHED,
            "Examination guidance is available.",
            "/app/announcements",
        ),
        (
            teacher_user.id,
            NotificationType.SUPPORT_TICKET_REPLIED,
            "A student replied to an academic ticket.",
            "/app/support",
        ),
    ]
    for index, (user_id, kind, _message, link) in enumerate(notification_plan):
        db.add(
            Notification(
                user_id=user_id,
                type=kind,
                params={"seed": True, "index": index},
                link_url=link,
                read_at=now if index % 3 == 2 else None,
            )
        )

    db.commit()


def ensure_program_offering_links(db: DBSession) -> None:
    """Link every programme section to that programme's period offering.

    ``get_student_visible_class_section_ids`` scopes an assigned student to the
    sections linked to their offering. Creating offerings without those links
    therefore makes a correctly enrolled student appear to have no classes —
    which is exactly what happened in the first seed run. This repair is
    idempotent and also backfills an existing clone database.
    """
    period = (
        db.query(AcademicPeriod)
        .filter(AcademicPeriod.code == ACTIVE_PERIOD_CODE)
        .one_or_none()
    )
    if period is None:
        return

    offerings = (
        db.query(ProgramOffering)
        .filter(ProgramOffering.academic_period_id == period.id)
        .all()
    )
    for offering in offerings:
        if offering.program_id is None:
            continue
        section_ids = [
            row[0]
            for row in db.query(ClassSection.id)
            .join(Course, Course.id == ClassSection.course_id)
            .filter(
                ClassSection.academic_period_id == period.id,
                Course.program_id == offering.program_id,
            )
            .all()
        ]
        if not section_ids:
            continue
        linked = {
            row[0]
            for row in db.query(ClassSectionProgramOffering.class_section_id)
            .filter(
                ClassSectionProgramOffering.program_offering_id == offering.id,
                ClassSectionProgramOffering.class_section_id.in_(section_ids),
            )
            .all()
        }
        for section_id in section_ids:
            if section_id not in linked:
                db.add(
                    ClassSectionProgramOffering(
                        class_section_id=section_id,
                        program_offering_id=offering.id,
                    )
                )
    db.commit()


# --- Minimal PDF writer -----------------------------------------------------


def _pdf(title: str, lines: list[str]) -> bytes:
    """Return a small, valid single-page PDF without adding a dependency."""

    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    operations = ["BT", "/F1 18 Tf", "72 780 Td", f"({escape(title)}) Tj", "/F1 11 Tf"]
    y = 744
    for line in lines:
        operations.append(f"1 0 0 1 72 {y} Tm")
        operations.append(f"({escape(line)}) Tj")
        y -= 18
    operations.append("ET")
    stream = "\n".join(operations).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)
