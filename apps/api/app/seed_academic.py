"""Seed academic data."""

from __future__ import annotations

from datetime import date, time

from sqlalchemy import and_

from app.database.session import SessionLocal  # noqa: TC001
from app.models.academic import (
    AcademicPeriod,
    AcademicPeriodStatus,
    Classroom,
    ClassroomStatus,
    ClassSection,
    ClassStatus,
    Course,
    Enrollment,
    EnrollmentStatus,
    EntityStatus,
    Major,
    Program,
    TeacherAssignment,
    TimetableEntry,
    TimetableFormat,
    TimetableSlot,
)
from app.models.admission import AcademicPlacement
from app.models.identity import Staff, Student, User


def seed_academic(db: SessionLocal) -> None:
    """Seed academic structure."""

    # Reference formats are configuration, not institutional records. They are
    # also seeded by the migration; doing it here keeps create_all-based test
    # databases and fresh development databases equivalent.
    formats = {
        "standard8": (
            "Standard 8-period day",
            "Eight individual periods with break intervals.",
            "Used by 2025 Autumn and 2026 Spring",
        ),
        "block4": (
            "Four-block day",
            "Four two-period blocks.",
            "Used by 2026 Autumn",
        ),
    }
    for code, (name, description, source_description) in formats.items():
        if not db.query(TimetableFormat).filter(TimetableFormat.code == code).first():
            db.add(
                TimetableFormat(
                    code=code,
                    name=name,
                    description=description,
                    source_description=source_description,
                    definition_json={},
                )
            )
    db.flush()
    slots = [
        ("standard8", "1-2", time(8, 20), time(10, 0)),
        ("standard8", "1-4", time(8, 20), time(12, 0)),
        ("standard8", "3-4", time(10, 20), time(12, 0)),
        ("standard8", "5-6", time(13, 30), time(15, 10)),
        ("standard8", "5-8", time(13, 30), time(17, 0)),
        ("standard8", "7", time(15, 20), time(16, 5)),
        ("block4", "1-2", time(8, 20), time(10, 0)),
        ("block4", "1-4", time(8, 20), time(12, 0)),
        ("block4", "5-6", time(13, 30), time(15, 10)),
        ("block4", "5-8", time(13, 30), time(17, 0)),
        ("block4", "7-8", time(15, 20), time(17, 0)),
    ]
    for order, (format_code, label, start, end) in enumerate(slots):
        if not db.query(TimetableSlot).filter(
            TimetableSlot.format_code == format_code,
            TimetableSlot.label == label,
        ).first():
            db.add(
                TimetableSlot(
                    format_code=format_code,
                    label=label,
                    start_time=start,
                    end_time=end,
                    sort_order=order,
                )
            )
    db.flush()

    # ── Majors ──
    majors_data = [
        ("CS", "Computer Science"),
        ("BUS", "Business Administration"),
        ("ENG", "English Language"),
    ]
    major_objs = {}
    for code, name in majors_data:
        existing = db.query(Major).filter(Major.code == code).first()
        if not existing:
            major = Major(code=code, name=name, status=EntityStatus.ACTIVE)
            db.add(major)
            db.flush()
            major_objs[code] = major
        else:
            major_objs[code] = existing

    # ── Programs ──
    programs_data = [
        ("BCS", "Bachelor of Computer Science", "CS", 4),
        ("BBA", "Bachelor of Business Administration", "BUS", 4),
        ("BAL", "Bachelor of Arts in English", "ENG", 4),
    ]
    program_objs = {}
    for code, name, major_code, years in programs_data:
        existing = db.query(Program).filter(Program.code == code).first()
        if not existing:
            program = Program(
                major_id=major_objs[major_code].id,
                code=code,
                name=name,
                duration_years=years,
                status=EntityStatus.ACTIVE,
            )
            db.add(program)
            db.flush()
            program_objs[code] = program
        else:
            program_objs[code] = existing

    # ── Courses ──
    courses_data = [
        ("CS101", "Introduction to Programming", "BCS", 3, 1),
        ("CS201", "Data Structures", "BCS", 3, 2),
        ("CS301", "Operating Systems", "BCS", 3, 3),
        ("BA101", "Principles of Business", "BBA", 3, 1),
        ("BA201", "Marketing Fundamentals", "BBA", 3, 2),
        ("EN101", "English Composition", "BAL", 3, 1),
        ("EN201", "Creative Writing", "BAL", 3, 2),
    ]
    course_objs = {}
    for code, name, prog_code, num_credits, sem in courses_data:
        existing = db.query(Course).filter(Course.code == code).first()
        if not existing:
            course = Course(
                program_id=program_objs[prog_code].id,
                code=code,
                name=name,
                credits=num_credits,
                semester=sem,
                status=EntityStatus.ACTIVE,
            )
            db.add(course)
            db.flush()
            course_objs[code] = course
        else:
            course_objs[code] = existing

    # ── Academic Period ──
    period = db.query(AcademicPeriod).filter(AcademicPeriod.code == "2026-FALL").first()
    if not period:
        period = AcademicPeriod(
            name="Fall 2026",
            code="2026-FALL",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 12, 20),
            status=AcademicPeriodStatus.ACTIVE,
        )
        db.add(period)
        db.flush()

    # ── Classrooms ──
    classrooms_data = [
        ("B18-301", "Building 18, Room 301", 40),
        ("B18-302", "Building 18, Room 302", 35),
        ("B18-401", "Building 18, Room 401", 50),
        ("B19-201", "Building 19, Room 201", 30),
        ("B19-202", "Building 19, Room 202", 45),
    ]
    classroom_objs = {}
    for code, name, cap in classrooms_data:
        existing = db.query(Classroom).filter(Classroom.room_code == code).first()
        if not existing:
            classroom = Classroom(
                building="B" + code.split("-")[0][1:],
                room_code=code,
                name=name,
                capacity=cap,
                status=ClassroomStatus.AVAILABLE,
            )
            db.add(classroom)
            db.flush()
            classroom_objs[code] = classroom
        else:
            classroom_objs[code] = existing

    # ── Class Sections ──
    classes_data = [
        ("CS101", "A", "2026-FALL", 35),
        ("CS101", "B", "2026-FALL", 35),
        ("CS201", "A", "2026-FALL", 30),
        ("BA101", "A", "2026-FALL", 40),
        ("EN101", "A", "2026-FALL", 30),
    ]
    class_objs = {}
    for course_code, sec, period_code, cap in classes_data:
        key = f"{course_code}-{sec}"
        existing = (
            db.query(ClassSection)
            .join(ClassSection.course)
            .join(ClassSection.academic_period)
            .filter(
                and_(
                    Course.code == course_code,
                    ClassSection.section_code == sec,
                    AcademicPeriod.code == period_code,
                )
            )
            .first()
        )
        if not existing:
            cs = ClassSection(
                course_id=course_objs[course_code].id,
                academic_period_id=period.id,
                section_code=sec,
                capacity=cap,
                enrolled_count=0,
                status=ClassStatus.ACTIVE,
            )
            db.add(cs)
            db.flush()
            class_objs[key] = cs
        else:
            class_objs[key] = existing

    # ── Teacher Assignments ──
    # Find the teacher staff record
    teacher_user = db.query(User).filter(User.email == "teacher@school.portal").first()
    if teacher_user:
        staff = db.query(Staff).filter(Staff.user_id == teacher_user.id).first()
        if staff:
            # Assign teacher to CS101-A and BA101-A
            for sec_key in ["CS101-A", "BA101-A"]:
                cs = class_objs.get(sec_key)
                if cs:
                    existing = (
                        db.query(TeacherAssignment)
                        .filter(
                            and_(
                                TeacherAssignment.class_section_id == cs.id,
                                TeacherAssignment.staff_id == staff.id,
                            )
                        )
                        .first()
                    )
                    if not existing:
                        ta = TeacherAssignment(
                            class_section_id=cs.id,
                            staff_id=staff.id,
                            role="PRIMARY",
                            is_active=True,
                        )
                        db.add(ta)
                    elif not existing.is_active:
                        existing.is_active = True

    # ── Enrollments ──
    # Enroll only legacy students in CS101-A and BA101-A. A student with a
    # current placement is authorized from that offering's sections;
    # adding legacy demo enrollments would broaden teacher scope and make the
    # student's timetable depend on unrelated seeded classes.
    # Ordered so a fresh database enrols the same legacy students every time;
    # without it the demo roster (and therefore teacher scope) depended on heap
    # order.
    students = (
        db.query(Student)
        .filter(
            ~db.query(AcademicPlacement.id)
            .filter(
                AcademicPlacement.student_id == Student.id,
                AcademicPlacement.ended_at.is_(None),
            )
            .exists()
        )
        .order_by(Student.student_id)
        .limit(3)
        .all()
    )
    for student in students:
        for sec_key in ["CS101-A", "BA101-A"]:
            cs = class_objs.get(sec_key)
            if cs:
                existing = (
                    db.query(Enrollment)
                    .filter(
                        and_(
                            Enrollment.student_id == student.id,
                            Enrollment.class_section_id == cs.id,
                        )
                    )
                    .first()
                )
                if not existing:
                    enrollment = Enrollment(
                        student_id=student.id,
                        class_section_id=cs.id,
                        status=EnrollmentStatus.ENROLLED,
                    )
                    db.add(enrollment)
                    cs.enrolled_count += 1
                elif existing.status != EnrollmentStatus.ENROLLED:
                    existing.status = EnrollmentStatus.ENROLLED
                    existing.dropped_at = None
                    cs.enrolled_count += 1

    # ── Timetable Entries ──
    # CS101-A: Mon/Wed/Fri 09:00-10:00 in B18-301
    # BA101-A: Tue/Thu 10:00-11:30 in B18-302
    timetable_data = [
        ("CS101-A", "B18-301", 0, time(9, 0), time(10, 0)),   # Monday
        ("CS101-A", "B18-301", 2, time(9, 0), time(10, 0)),   # Wednesday
        ("CS101-A", "B18-301", 4, time(9, 0), time(10, 0)),   # Friday
        ("BA101-A", "B18-302", 1, time(10, 0), time(11, 30)), # Tuesday
        ("BA101-A", "B18-302", 3, time(10, 0), time(11, 30)), # Thursday
    ]
    for sec_key, room_code, dow, start, end in timetable_data:
        cs = class_objs.get(sec_key)
        classroom = classroom_objs.get(room_code)
        if cs and classroom:
            existing = (
                db.query(TimetableEntry)
                .filter(
                    and_(
                        TimetableEntry.class_section_id == cs.id,
                        TimetableEntry.day_of_week == dow,
                        TimetableEntry.start_time == start,
                    )
                )
                .first()
            )
            if not existing:
                entry = TimetableEntry(
                    class_section_id=cs.id,
                    classroom_id=classroom.id,
                    day_of_week=dow,
                    start_time=start,
                    end_time=end,
                )
                db.add(entry)

    db.commit()
