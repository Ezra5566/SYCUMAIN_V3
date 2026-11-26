"""Academic business logic: enrollment, timetable conflicts, teacher scope, student timetable."""

from __future__ import annotations

import json
import math
import uuid  # noqa: TC003
from datetime import UTC, date, datetime, time  # noqa: TC003
from typing import Any

from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import record_audit
from app.config.settings import get_settings
from app.models.academic import (
    AcademicChangeHistory,
    AcademicPeriod,
    AcademicPeriodStatus,
    Assessment,
    AttendanceRecord,
    AttendanceStatus,
    Classroom,
    ClassroomStatus,
    ClassSection,
    ClassSectionProgramOffering,
    ClassStatus,
    Course,
    Enrollment,
    EnrollmentStatus,
    EntityStatus,
    Grade,
    Major,
    Program,
    ProgramOffering,
    TeacherAssignment,
    TimetableEntry,
)
from app.models.identity import Staff, Student, User
from app.schemas.academic import (
    AcademicChangeHistoryResponse,
    AcademicPeriodCreate,
    AcademicPeriodListResponse,
    AcademicPeriodResponse,
    AcademicPeriodUpdate,
    AssessmentCreate,
    AssessmentResponse,
    AssessmentUpdate,
    AttendanceBulkCreate,
    AttendanceRecordCreate,
    AttendanceRecordResponse,
    ClassroomCreate,
    ClassroomListResponse,
    ClassroomResponse,
    ClassroomUpdate,
    ClassSectionBrief,
    ClassSectionCreate,
    ClassSectionListResponse,
    ClassSectionResponse,
    ClassSectionUpdate,
    CourseCreate,
    CourseListResponse,
    CourseResponse,
    CourseUpdate,
    EnrollmentCreate,
    EnrollmentResponse,
    GradeCreate,
    GradeResponse,
    GradeUpdate,
    InstitutionalTimetableIssue,
    InstitutionalTimetableReadiness,
    InstitutionalTimetableResponse,
    InstitutionalTimetableSection,
    MajorCreate,
    MajorListResponse,
    MajorResponse,
    MajorUpdate,
    PaginationMeta,
    ProgramCreate,
    ProgramListResponse,
    ProgramOfferingCreate,
    ProgramOfferingListResponse,
    ProgramOfferingResponse,
    ProgramOfferingSummary,
    ProgramOfferingUpdate,
    ProgramResponse,
    ProgramUpdate,
    SectionProgramOfferingUpdate,
    StudentAcademicOverview,
    TeachableStaff,
    TeachableStaffListResponse,
    TeacherAssignmentCreate,
    TeacherAssignmentResponse,
    TeacherInfo,
    TimetableEntryCreate,
    TimetableEntryResponse,
    TimetableEntryUpdate,
)
from app.services.student_academic import (
    current_placement,
    student_academic_snapshot,
)


class AcademicRuleError(ValueError):
    """An academic rule violation that maps to a stable API error code.

    Deliberately parallel to ``app.services.housing.HousingRuleError``: routers
    must never decide between 404 and 409 by pattern-matching an exception's
    prose, and the client must be able to render the precise reason in the
    user's own language. Every distinct timetable rule therefore carries its own
    code (a section clash, a room clash and a teacher clash are three different
    sentences to a scheduler) instead of collapsing into one generic conflict.

    Subclasses ``ValueError`` so any handler not yet converted still behaves as
    a generic 409 rather than escaping as a 500.
    """

    def __init__(self, code: str, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.not_found = not_found


# Timetable and teacher-assignment mutations are serialized by one
# transaction-scoped PostgreSQL advisory lock. A check made from two
# independent sessions without this lock can both observe "no conflict" and
# then commit a conflicting pair. The lock is deliberately global for this
# small domain: it is simpler and safer than maintaining per-room/per-teacher
# lock ordering, and timetable writes are low-volume administrative actions.
_TIMETABLE_WRITE_LOCK_KEY = 0x53435554494D4554


def lock_timetable_writes(db: DBSession) -> None:
    """Serialize timetable and teacher-assignment writes in this transaction."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _TIMETABLE_WRITE_LOCK_KEY},
    )


def _json_value(value):
    """JSON-safe representation for change-history snapshots."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (date, time, datetime)):
        return value.isoformat()
    return value


def _record_academic_change(
    db: DBSession,
    *,
    class_section_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    previous: dict,
    new: dict,
    actor_id: uuid.UUID | None,
    reason: str | None = None,
) -> None:
    changed = sorted(field for field in new if previous.get(field) != new.get(field))
    if not changed:
        return
    db.add(
        AcademicChangeHistory(
            class_section_id=class_section_id,
            entity_type=entity_type,
            entity_id=entity_id,
            previous_data=json.dumps(previous),
            new_data=json.dumps(new),
            changed_fields=json.dumps(changed),
            changed_by_id=actor_id,
            reason=reason,
        )
    )


def list_class_record_history(
    db: DBSession,
    class_section_id: uuid.UUID,
    entity_type: str | None = None,
) -> list[AcademicChangeHistoryResponse]:
    """Previous/new values for assessments and grades in a class."""
    query = db.query(AcademicChangeHistory).filter(
        AcademicChangeHistory.class_section_id == class_section_id
    )
    if entity_type:
        query = query.filter(
            AcademicChangeHistory.entity_type == entity_type.upper()
        )
    rows = query.order_by(AcademicChangeHistory.changed_at.desc()).all()
    result = []
    for row in rows:
        actor = (
            db.query(User).filter(User.id == row.changed_by_id).first()
            if row.changed_by_id
            else None
        )
        result.append(
            AcademicChangeHistoryResponse(
                id=row.id,
                class_section_id=row.class_section_id,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                previous_data=json.loads(row.previous_data),
                new_data=json.loads(row.new_data),
                changed_fields=json.loads(row.changed_fields),
                changed_by_id=row.changed_by_id,
                changed_by_name=actor.full_name if actor else None,
                changed_at=row.changed_at,
                reason=row.reason,
            )
        )
    return result


def _paginate(query, page: int, page_size: int) -> PaginationMeta:
    total = query.count()
    total_pages = max(1, math.ceil(total / page_size))
    return PaginationMeta(
        page=page, page_size=page_size, total=total, total_pages=total_pages
    )


# --- Teacher Scope ---


def get_teacher_class_section_ids(
    db: DBSession, staff_id: uuid.UUID
) -> set[uuid.UUID]:
    """Get class section IDs that a teacher is assigned to."""
    assignments = (
        db.query(TeacherAssignment)
        .filter(
            and_(
                TeacherAssignment.staff_id == staff_id,
                TeacherAssignment.is_active.is_(True),
            )
        )
        .all()
    )
    return {a.class_section_id for a in assignments}


def get_staff_for_user(db: DBSession, user: User) -> Staff | None:
    """Get the staff record for a user."""
    return db.query(Staff).filter(Staff.user_id == user.id).first()


def can_access_class_section(
    db: DBSession, user: User, class_section_id: uuid.UUID
) -> bool:
    """Check if a user can access a specific class section.

    Admin/Management: always yes.
    Teacher: only if assigned.
    Student: any section linked to their assigned offering, or their enrolled
    sections when no offering is assigned.
    """
    role_names = {r.name for r in user.roles}
    if "ADMIN" in role_names or "MANAGEMENT" in role_names:
        return True

    if "TEACHER" in role_names:
        staff = get_staff_for_user(db, user)
        if staff is None or not staff.is_active:
            return False
        ids = get_teacher_class_section_ids(db, staff.id)
        return class_section_id in ids

    if "STUDENT" in role_names:
        student = db.query(Student).filter(Student.user_id == user.id).first()
        if student:
            return class_section_id in get_student_visible_class_section_ids(
                db, student.id
            )
        return False

    return False


def get_offering_class_section_ids(
    db: DBSession,
    program_offering_id: uuid.UUID,
    *,
    period_id: uuid.UUID | None = None,
) -> set[uuid.UUID]:
    """Canonical sections linked to one period-specific offering."""
    query = db.query(ClassSectionProgramOffering.class_section_id).filter(
        ClassSectionProgramOffering.program_offering_id == program_offering_id
    )
    if period_id:
        query = query.join(
            ClassSection,
            ClassSection.id == ClassSectionProgramOffering.class_section_id,
        ).filter(ClassSection.academic_period_id == period_id)
    return {row[0] for row in query.all()}


def get_student_visible_class_section_ids(
    db: DBSession,
    student_id: uuid.UUID,
    *,
    period_id: uuid.UUID | None = None,
    statuses: tuple[EnrollmentStatus, ...] | None = None,
) -> set[uuid.UUID]:
    """Sections a student may see, scoped to an assigned offering when present.

    A NULL assignment deliberately falls back to the historical enrollment
    behavior. An assigned student sees the sections linked to that offering;
    sharing a section with another offering does not leak the other offering's
    timetable because the query is still tied to the student's own offering.

    When a historical period is requested, only a placement in that same
    period may scope the read. Otherwise the student's actual enrollments in
    that period remain visible; a later placement must not erase history.
    """
    placement = current_placement(db, student_id)
    if placement is not None:
        offering = db.get(ProgramOffering, placement.program_offering_id)
        if offering is not None and (
            period_id is None or offering.academic_period_id == period_id
        ):
            return get_offering_class_section_ids(
                db, placement.program_offering_id, period_id=period_id
            )
    return get_student_class_section_ids(
        db, student_id, period_id=period_id, statuses=statuses
    )


def get_student_class_section_ids(
    db: DBSession,
    student_id: uuid.UUID,
    *,
    period_id: uuid.UUID | None = None,
    statuses: tuple[EnrollmentStatus, ...] | None = None,
) -> set[uuid.UUID]:
    """Get class section IDs a student is enrolled in.

    The active-period read uses ENROLLED only. Historical reads may pass
    ENROLLED and COMPLETED, but never silently fold in dropped registrations.
    """
    query = db.query(Enrollment).filter(Enrollment.student_id == student_id)
    if statuses:
        query = query.filter(Enrollment.status.in_(statuses))
    else:
        query = query.filter(Enrollment.status == EnrollmentStatus.ENROLLED)
    if period_id:
        query = query.join(ClassSection).filter(
            ClassSection.academic_period_id == period_id
        )
    return {e.class_section_id for e in query.all()}


def resolve_period(
    db: DBSession, period_id: uuid.UUID | None = None
) -> AcademicPeriod | None:
    """Resolve an explicit period or the current active period.

    Returning ``None`` means there is no selected period. Callers must render an
    empty state rather than silently crossing semester boundaries.
    """
    if period_id:
        return db.query(AcademicPeriod).filter(AcademicPeriod.id == period_id).first()
    return (
        db.query(AcademicPeriod)
        .filter(AcademicPeriod.status == AcademicPeriodStatus.ACTIVE)
        .order_by(AcademicPeriod.start_date.desc())
        .first()
    )


def _program_offering_summaries(
    db: DBSession, class_section_id: uuid.UUID
) -> list[ProgramOfferingSummary]:
    offerings = (
        db.query(ProgramOffering)
        .join(
            ClassSectionProgramOffering,
            ClassSectionProgramOffering.program_offering_id == ProgramOffering.id,
        )
        .filter(ClassSectionProgramOffering.class_section_id == class_section_id)
        .order_by(ProgramOffering.name)
        .all()
    )
    return [ProgramOfferingSummary.model_validate(offering) for offering in offerings]


def teacher_student_ids(db: DBSession, user: User) -> set[uuid.UUID]:
    """Student IDs a teacher may legitimately see.

    Derived entirely from active teacher assignments: a teacher sees exactly
    the students enrolled in the class sections they teach, plus students
    enrolled in the sections of any co-teacher on the same class. No broader
    access is granted.
    """
    staff = get_staff_for_user(db, user)
    if staff is None or not staff.is_active:
        return set()

    class_section_ids = get_teacher_class_section_ids(db, staff.id)
    if not class_section_ids:
        return set()

    rows = (
        db.query(Enrollment.student_id)
        .filter(
            and_(
                Enrollment.class_section_id.in_(class_section_ids),
                Enrollment.status == EnrollmentStatus.ENROLLED,
            )
        )
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def teacher_can_access_student(
    db: DBSession, user: User, student_id: uuid.UUID
) -> bool:
    """Whether a teacher is scoped to a specific student."""
    return student_id in teacher_student_ids(db, user)


# --- Major ---


def list_majors(
    db: DBSession, *, page: int = 1, page_size: int = 25, search: str | None = None
) -> MajorListResponse:
    query = db.query(Major)
    if search:
        pat = f"%{search}%"
        query = query.filter(Major.name.ilike(pat) | Major.code.ilike(pat))

    meta = _paginate(query, page, page_size)
    items = (
        query.order_by(Major.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return MajorListResponse(
        items=[MajorResponse.model_validate(m) for m in items], meta=meta
    )


def get_major(db: DBSession, major_id: uuid.UUID) -> Major | None:
    return db.query(Major).filter(Major.id == major_id).first()


def create_major(db: DBSession, data: MajorCreate) -> MajorResponse:
    existing = db.query(Major).filter(Major.code == data.code).first()
    if existing:
        raise ValueError(f"Major with code {data.code} already exists")
    major = Major(**data.model_dump())
    db.add(major)
    db.commit()
    db.refresh(major)
    return MajorResponse.model_validate(major)


def update_major(
    db: DBSession, major: Major, data: MajorUpdate
) -> MajorResponse:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(major, field, value)
    db.commit()
    db.refresh(major)
    return MajorResponse.model_validate(major)


# --- Program ---


def list_programs(
    db: DBSession, *, page: int = 1, page_size: int = 25, search: str | None = None
) -> ProgramListResponse:
    query = db.query(Program)
    if search:
        pat = f"%{search}%"
        query = query.filter(Program.name.ilike(pat) | Program.code.ilike(pat))

    meta = _paginate(query, page, page_size)
    items = (
        query.order_by(Program.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = []
    for p in items:
        resp = ProgramResponse.model_validate(p)
        resp.major_name = p.major.name if p.major else None
        result.append(resp)
    return ProgramListResponse(items=result, meta=meta)


def get_program(db: DBSession, program_id: uuid.UUID) -> Program | None:
    return db.query(Program).filter(Program.id == program_id).first()


def create_program(db: DBSession, data: ProgramCreate) -> ProgramResponse:
    existing = db.query(Program).filter(Program.code == data.code).first()
    if existing:
        raise ValueError(f"Program with code {data.code} already exists")
    if not db.query(Major).filter(Major.id == data.major_id).first():
        raise ValueError("Major not found")
    program = Program(**data.model_dump())
    db.add(program)
    db.commit()
    db.refresh(program)
    resp = ProgramResponse.model_validate(program)
    resp.major_name = program.major.name if program.major else None
    return resp


def update_program(
    db: DBSession, program: Program, data: ProgramUpdate
) -> ProgramResponse:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(program, field, value)
    db.commit()
    db.refresh(program)
    resp = ProgramResponse.model_validate(program)
    resp.major_name = program.major.name if program.major else None
    return resp


# --- Course ---


def list_courses(
    db: DBSession, *, page: int = 1, page_size: int = 25, search: str | None = None
) -> CourseListResponse:
    query = db.query(Course)
    if search:
        pat = f"%{search}%"
        query = query.filter(Course.name.ilike(pat) | Course.code.ilike(pat))

    meta = _paginate(query, page, page_size)
    items = (
        query.order_by(Course.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = []
    for c in items:
        resp = CourseResponse.model_validate(c)
        resp.program_name = c.program.name if c.program else None
        result.append(resp)
    return CourseListResponse(items=result, meta=meta)


def get_course(db: DBSession, course_id: uuid.UUID) -> Course | None:
    return db.query(Course).filter(Course.id == course_id).first()


def create_course(db: DBSession, data: CourseCreate) -> CourseResponse:
    existing = (
        db.query(Course).filter(Course.code == data.code).first()
        if data.code
        else None
    )
    if existing:
        raise ValueError(f"Course with code {data.code} already exists")
    if data.program_id and not db.query(Program).filter(Program.id == data.program_id).first():
        raise ValueError("Program not found")
    course = Course(**data.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    resp = CourseResponse.model_validate(course)
    resp.program_name = course.program.name if course.program else None
    return resp


def update_course(
    db: DBSession, course: Course, data: CourseUpdate
) -> CourseResponse:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    db.commit()
    db.refresh(course)
    resp = CourseResponse.model_validate(course)
    resp.program_name = course.program.name if course.program else None
    return resp


# --- Academic Period ---


def period_response(
    db: DBSession,
    period: AcademicPeriod,
    *,
    has_dependants: bool | None = None,
) -> AcademicPeriodResponse:
    """Attach the two UI affordances the academic-period list needs.

    They are computed here rather than stored: neither is part of the academic
    record, and both must reflect the current deployment and current
    dependants at read time.
    """

    from app.services.period_correction import period_has_dependants

    response = AcademicPeriodResponse.model_validate(period)
    response.date_correction_enabled = (
        get_settings().ADMISSION_DATE_CORRECTION_ENABLED
    )
    response.has_dependants = (
        has_dependants
        if has_dependants is not None
        else period_has_dependants(db, period.id)
    )
    return response


def list_academic_periods(
    db: DBSession, *, page: int = 1, page_size: int = 25
) -> AcademicPeriodListResponse:
    from app.services.period_correction import periods_with_dependants

    query = db.query(AcademicPeriod)
    meta = _paginate(query, page, page_size)
    items = (
        query.order_by(AcademicPeriod.start_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    dependent_ids = periods_with_dependants(db, [period.id for period in items])
    responses = [
        period_response(db, period, has_dependants=period.id in dependent_ids)
        for period in items
    ]
    return AcademicPeriodListResponse(items=responses, meta=meta)


def get_academic_period(db: DBSession, period_id: uuid.UUID) -> AcademicPeriod | None:
    return db.query(AcademicPeriod).filter(AcademicPeriod.id == period_id).first()


def create_academic_period(
    db: DBSession, data: AcademicPeriodCreate
) -> AcademicPeriodResponse:
    existing = db.query(AcademicPeriod).filter(AcademicPeriod.code == data.code).first()
    if existing:
        raise ValueError(f"Period with code {data.code} already exists")
    if data.end_date < data.start_date:
        raise ValueError("end_date must not precede start_date")
    period = AcademicPeriod(**data.model_dump())
    db.add(period)
    db.commit()
    db.refresh(period)
    return period_response(db, period, has_dependants=False)


def update_academic_period(
    db: DBSession, period: AcademicPeriod, data: AcademicPeriodUpdate
) -> AcademicPeriodResponse:
    from app.services.period_correction import period_has_dependants

    changes = data.model_dump(exclude_unset=True)
    next_start = changes.get("start_date", period.start_date)
    next_end = changes.get("end_date", period.end_date)
    if next_start is None or next_end is None:
        raise AcademicRuleError(
            "INTAKE_DATES_REQUIRED",
            "An academic period must keep both its start and end date.",
        )
    if next_end < next_start:
        raise AcademicRuleError(
            "INTAKE_DATES_INVALID", "end_date must not precede start_date"
        )

    dates_changed = (
        next_start != period.start_date or next_end != period.end_date
    )
    if dates_changed and (
        period.status == "COMPLETED" or period_has_dependants(db, period.id)
    ):
        raise AcademicRuleError(
            "USE_PERIOD_DATE_CORRECTION",
            "This intake cannot be date-edited directly. Use the audited "
            "date-correction workflow.",
        )

    for field, value in changes.items():
        setattr(period, field, value)
    db.commit()
    db.refresh(period)
    return period_response(db, period)


# --- Classroom ---


def list_classrooms(
    db: DBSession, *, page: int = 1, page_size: int = 25, search: str | None = None
) -> ClassroomListResponse:
    query = db.query(Classroom)
    if search:
        pat = f"%{search}%"
        query = query.filter(
            Classroom.room_code.ilike(pat)
            | Classroom.name.ilike(pat)
            | Classroom.building.ilike(pat)
        )
    meta = _paginate(query, page, page_size)
    items = (
        query.order_by(Classroom.room_code)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ClassroomListResponse(
        items=[ClassroomResponse.model_validate(c) for c in items], meta=meta
    )


def get_classroom(db: DBSession, classroom_id: uuid.UUID) -> Classroom | None:
    return db.query(Classroom).filter(Classroom.id == classroom_id).first()


def create_classroom(db: DBSession, data: ClassroomCreate) -> ClassroomResponse:
    existing = db.query(Classroom).filter(Classroom.room_code == data.room_code).first()
    if existing:
        raise ValueError(f"Classroom with code {data.room_code} already exists")
    classroom = Classroom(**data.model_dump())
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return ClassroomResponse.model_validate(classroom)


def update_classroom(
    db: DBSession, classroom: Classroom, data: ClassroomUpdate
) -> ClassroomResponse:
    """Edit a room. The room code is the human handle, so it stays unique.

    Capacity is descriptive location information, not an authoritative limit
    on a class section; changing it does not invalidate scheduled classes.
    """
    changes = data.model_dump(exclude_unset=True)

    new_code = changes.get("room_code")
    if new_code and new_code != classroom.room_code:
        clash = (
            db.query(Classroom)
            .filter(Classroom.room_code == new_code, Classroom.id != classroom.id)
            .first()
        )
        if clash:
            raise ValueError(f"Classroom with code {new_code} already exists")

    for field, value in changes.items():
        setattr(classroom, field, value)
    db.commit()
    db.refresh(classroom)
    return ClassroomResponse.model_validate(classroom)


# --- Class Section ---


def _build_class_section_response(
    db: DBSession, cs: ClassSection
) -> ClassSectionResponse:
    resp = ClassSectionResponse(
        id=cs.id,
        course_id=cs.course_id,
        course_code=cs.course.code if cs.course else None,
        course_name=cs.course.name if cs.course else None,
        academic_period_id=cs.academic_period_id,
        academic_period_name=cs.academic_period.name if cs.academic_period else None,
        section_code=cs.section_code,
        source_label=cs.source_label,
        capacity=cs.capacity,
        enrolled_count=cs.enrolled_count,
        status=cs.status,
        program_offerings=_program_offering_summaries(db, cs.id),
        created_at=cs.created_at,
        updated_at=cs.updated_at,
    )
    for ta in cs.teacher_assignments:
        if ta.is_active:
            resp.teachers.append(
                TeacherInfo(
                    id=ta.id,
                    staff_id=ta.staff.staff_id,
                    first_name=ta.staff.first_name,
                    last_name=ta.staff.last_name,
                    role=ta.role,
                )
            )
    return resp


def list_class_sections(
    db: DBSession,
    *,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    course_id: uuid.UUID | None = None,
    period_id: uuid.UUID | None = None,
    program_offering_id: uuid.UUID | None = None,
    visible_class_section_ids: set[uuid.UUID] | None = None,
) -> ClassSectionListResponse:
    query = db.query(ClassSection)
    if search:
        pat = f"%{search}%"
        query = query.join(ClassSection.course, isouter=True).filter(
            ClassSection.section_code.ilike(pat) | Course.code.ilike(pat) | Course.name.ilike(pat)
        )
    if course_id:
        query = query.filter(ClassSection.course_id == course_id)
    if period_id:
        query = query.filter(ClassSection.academic_period_id == period_id)
    if program_offering_id:
        query = query.join(
            ClassSectionProgramOffering,
            ClassSectionProgramOffering.class_section_id == ClassSection.id,
        ).filter(
            ClassSectionProgramOffering.program_offering_id == program_offering_id
        )
    if visible_class_section_ids is not None:
        query = query.filter(ClassSection.id.in_(visible_class_section_ids))

    meta = _paginate(query, page, page_size)
    items = (
        query.order_by(ClassSection.section_code)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ClassSectionListResponse(
        items=[_build_class_section_response(db, cs) for cs in items], meta=meta
    )


def get_class_section(
    db: DBSession, class_section_id: uuid.UUID
) -> ClassSection | None:
    return db.query(ClassSection).filter(ClassSection.id == class_section_id).first()


def create_class_section(
    db: DBSession, data: ClassSectionCreate
) -> ClassSectionResponse:
    existing = None
    if data.section_code:
        existing = (
            db.query(ClassSection)
            .filter(
                and_(
                    ClassSection.course_id == data.course_id,
                    ClassSection.academic_period_id == data.academic_period_id,
                    ClassSection.section_code == data.section_code,
                )
            )
            .first()
        )
    if existing:
        raise ValueError(
            f"Section {data.section_code} already exists for this course and period"
        )
    if not db.query(Course).filter(Course.id == data.course_id).first():
        raise ValueError("Course not found")
    if not db.query(AcademicPeriod).filter(AcademicPeriod.id == data.academic_period_id).first():
        raise ValueError("Academic period not found")

    cs = ClassSection(**data.model_dump())
    db.add(cs)
    db.commit()
    db.refresh(cs)
    return _build_class_section_response(db, cs)


def update_class_section(
    db: DBSession, cs: ClassSection, data: ClassSectionUpdate
) -> ClassSectionResponse:
    """Edit an offering, refusing the edits that would strand real records.

    Two edits are guarded rather than blocked outright:

    * **Capacity** may not fall below the number of students already enrolled —
      that would leave the roster permanently over capacity with no way back.
    * **Course and period** may not change once students are enrolled or a
      schedule exists. Both records reference this row, so moving them would
      silently rewrite a student's completed academic history.
    """
    # Serialize this edit with enrollment (which locks the section) and with
    # timetable writes (which take the scheduling lock).
    locked = (
        db.query(ClassSection)
        .filter(ClassSection.id == cs.id)
        .with_for_update()
        .first()
    )
    if locked is not None:
        cs = locked

    changes = data.model_dump(exclude_unset=True)

    effective_course = changes.get("course_id", cs.course_id)
    effective_period = changes.get("academic_period_id", cs.academic_period_id)
    effective_section = changes.get("section_code", cs.section_code)

    if "course_id" in changes and not db.query(Course).filter(
        Course.id == changes["course_id"]
    ).first():
        raise ValueError("Course not found")

    if "academic_period_id" in changes and not db.query(AcademicPeriod).filter(
        AcademicPeriod.id == changes["academic_period_id"]
    ).first():
        raise ValueError("Academic period not found")

    if "capacity" in changes:
        enrolled = (
            db.query(Enrollment)
            .filter(
                Enrollment.class_section_id == cs.id,
                Enrollment.status == EnrollmentStatus.ENROLLED,
            )
            .count()
        )
        if changes["capacity"] is not None and changes["capacity"] < enrolled:
            raise ValueError(
                f"Capacity {changes['capacity']} is below the {enrolled} "
                "students already enrolled"
            )

    moved = (
        effective_course != cs.course_id or effective_period != cs.academic_period_id
    )
    if moved:
        enrolled = (
            db.query(Enrollment)
            .filter(
                Enrollment.class_section_id == cs.id,
                Enrollment.status == EnrollmentStatus.ENROLLED,
            )
            .count()
        )
        scheduled = (
            db.query(TimetableEntry)
            .filter(TimetableEntry.class_section_id == cs.id)
            .count()
        )
        if enrolled or scheduled:
            raise ValueError(
                "This section already has "
                f"{enrolled} enrollment(s) and {scheduled} timetable "
                "entr(y/ies); remove them before changing its course or period"
            )

    clash = None
    if effective_section:
        clash = (
            db.query(ClassSection)
            .filter(
                and_(
                    ClassSection.course_id == effective_course,
                    ClassSection.academic_period_id == effective_period,
                    ClassSection.section_code == effective_section,
                    ClassSection.id != cs.id,
                )
            )
            .first()
        )
    if clash:
        raise ValueError(
            f"Section {effective_section} already exists for this course and period"
        )

    for field, value in changes.items():
        setattr(cs, field, value)
    db.commit()
    db.refresh(cs)
    return _build_class_section_response(db, cs)


# --- Teacher Assignment ---


def assign_teacher(
    db: DBSession, class_section_id: uuid.UUID, data: TeacherAssignmentCreate
) -> TeacherAssignmentResponse:
    # Assignment is a timetable write: adding a teacher to an already
    # scheduled section can create a clash just as surely as creating the
    # section's timetable slot. Serialize it with all other schedule writes.
    lock_timetable_writes(db)
    cs = db.query(ClassSection).filter(ClassSection.id == class_section_id).first()
    if not cs:
        raise ValueError("Class section not found")

    staff = db.query(Staff).filter(Staff.id == data.staff_id).first()
    if not staff:
        raise ValueError("Staff member not found")
    if not staff.is_active or not staff.user.is_active:
        raise ValueError("Staff member is inactive")

    existing = (
        db.query(TeacherAssignment)
        .filter(
            and_(
                TeacherAssignment.class_section_id == class_section_id,
                TeacherAssignment.staff_id == data.staff_id,
            )
        )
        .first()
    )
    if existing and existing.is_active:
        raise ValueError("Teacher is already assigned to this class section")

    # Check every live slot in the target section against this teacher's other
    # active sections. This is the path that previously let an assignment be
    # created after the timetable, bypassing create_timetable_entry's check.
    for entry in (
        db.query(TimetableEntry)
        .filter(
            TimetableEntry.class_section_id == class_section_id,
            TimetableEntry.is_deleted.is_(False),
        )
        .all()
    ):
        conflict = _timetable_conflict_exists(
            db,
            None,
            [data.staff_id],
            entry.day_of_week,
            entry.start_time,
            entry.end_time,
            academic_period_id=cs.academic_period_id,
        )
        if conflict:
            raise conflict

    if existing:
        existing.is_active = True
        existing.role = data.role
        db.commit()
        db.refresh(existing)
    else:
        ta = TeacherAssignment(
            class_section_id=class_section_id,
            staff_id=data.staff_id,
            role=data.role,
            is_active=True,
        )
        db.add(ta)
        db.commit()
        db.refresh(ta)
        existing = ta

    return TeacherAssignmentResponse(
        id=existing.id,
        class_section_id=existing.class_section_id,
        staff_id=existing.staff_id,
        staff_name=f"{staff.first_name} {staff.last_name}",
        role=existing.role,
        is_active=existing.is_active,
        created_at=existing.created_at,
    )


def remove_teacher(db: DBSession, assignment_id: uuid.UUID) -> None:
    ta = db.query(TeacherAssignment).filter(TeacherAssignment.id == assignment_id).first()
    if not ta:
        raise ValueError("Teacher assignment not found")
    ta.is_active = False
    db.commit()


def list_teachable_staff(
    db: DBSession, *, search: str | None = None
) -> TeachableStaffListResponse:
    """Staff who can be put in front of a class.

    Exists because assignment otherwise asks a clerk to supply a raw UUID with
    no way to discover one. Active staff only — assigning a class to a departed
    teacher is never the intended action.
    """
    query = db.query(Staff).join(User, Staff.user_id == User.id).filter(
        User.is_active.is_(True),
        Staff.is_active.is_(True),
    )
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            Staff.first_name.ilike(pattern)
            | Staff.last_name.ilike(pattern)
            | Staff.staff_id.ilike(pattern)
            | User.email.ilike(pattern)
        )

    staff_members = query.order_by(Staff.last_name, Staff.first_name).all()
    items = [
        TeachableStaff(
            staff_id=staff.id,
            staff_number=staff.staff_id,
            first_name=staff.first_name,
            last_name=staff.last_name,
            email=staff.user.email if staff.user else None,
            roles=[role.name for role in staff.user.roles] if staff.user else [],
        )
        for staff in staff_members
    ]
    return TeachableStaffListResponse(items=items, total=len(items))


def list_teacher_assignments(
    db: DBSession, class_section_id: uuid.UUID
) -> list[TeacherAssignmentResponse]:
    assignments = (
        db.query(TeacherAssignment)
        .filter(TeacherAssignment.class_section_id == class_section_id)
        .all()
    )
    result = []
    for ta in assignments:
        staff = db.query(Staff).filter(Staff.id == ta.staff_id).first()
        result.append(
            TeacherAssignmentResponse(
                id=ta.id,
                class_section_id=ta.class_section_id,
                staff_id=ta.staff_id,
                staff_name=f"{staff.first_name} {staff.last_name}" if staff else None,
                role=ta.role,
                is_active=ta.is_active,
                created_at=ta.created_at,
            )
        )
    return result


# --- Enrollment ---


def _lock_class_section(db: DBSession, class_section_id: uuid.UUID) -> ClassSection | None:
    """Lock the section row so capacity decisions serialize with enrollment."""
    return (
        db.query(ClassSection)
        .filter(ClassSection.id == class_section_id)
        .with_for_update()
        .first()
    )


def _active_enrollment_count(db: DBSession, class_section_id: uuid.UUID) -> int:
    return (
        db.query(func.count(Enrollment.id))
        .filter(
            Enrollment.class_section_id == class_section_id,
            Enrollment.status == EnrollmentStatus.ENROLLED,
        )
        .scalar()
        or 0
    )


def _sync_enrolled_count(db: DBSession, cs: ClassSection) -> int:
    """Make the denormalized counter equal the active roster in this transaction."""
    db.flush()
    count = _active_enrollment_count(db, cs.id)
    cs.enrolled_count = count
    return count


class EnrollmentAuthorizationError(ValueError):
    """A late enrolment was attempted without an authorized decision.

    ``status_code`` distinguishes "you may not do this" (403) from "the request
    is missing the required reason" (400). The route maps it directly, so the
    rule is enforced in one place regardless of which client calls the API.
    """

    def __init__(self, code: str, message: str, *, status_code: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _role_names(user: User | None) -> set[str]:
    if user is None:
        return set()
    return {
        getattr(role, "name", "").upper()
        for role in (getattr(user, "roles", None) or [])
    }


def _late_enrollment_authorization(
    db: DBSession, cs: ClassSection, data: EnrollmentCreate, actor: User | None
) -> tuple[str, str | None, User, datetime] | None:
    """Decide whether this enrolment is late, and require a decision if so.

    An intake is late when its period starts before the current active period,
    or when it is already completed. Joining such a class is an institutional
    exception: only Admin or Management may approve it, the reason is mandatory
    and the approver is stored on the enrolment itself so the record remains
    auditable after the request is gone.
    """
    period = (
        db.query(AcademicPeriod)
        .filter(AcademicPeriod.id == cs.academic_period_id)
        .first()
    )
    active = resolve_period(db)
    if period is None or active is None or period.id == active.id:
        return None
    is_earlier_intake = period.start_date < active.start_date or (
        period.status == AcademicPeriodStatus.COMPLETED
    )
    if not is_earlier_intake:
        return None

    if not ({"ADMIN", "MANAGEMENT"} & _role_names(actor)):
        raise EnrollmentAuthorizationError(
            "EARLIER_INTAKE_NOT_AUTHORIZED",
            "Enrollment in an earlier intake requires admin or management "
            "authorization",
        )
    reason = (data.authorization_reason or "").strip()
    if len(reason) < 10:
        raise EnrollmentAuthorizationError(
            "EARLIER_INTAKE_REASON_REQUIRED",
            "A recorded reason of at least 10 characters is required for a late "
            "enrollment",
            status_code=400,
        )
    if actor is None:
        raise EnrollmentAuthorizationError(
            "EARLIER_INTAKE_NOT_AUTHORIZED",
            "Enrollment in an earlier intake requires admin or management "
            "authorization",
        )
    return reason, (data.authorization_reference or None), actor, datetime.now(UTC)


def _enrollment_response(
    enrollment: Enrollment, student: Student | None
) -> EnrollmentResponse:
    return EnrollmentResponse(
        id=enrollment.id,
        student_id=enrollment.student_id,
        student_name=f"{student.first_name} {student.last_name}" if student else None,
        student_number=student.student_id if student else None,
        class_section_id=enrollment.class_section_id,
        status=enrollment.status,
        enrolled_at=enrollment.enrolled_at,
        dropped_at=enrollment.dropped_at,
        authorization_reason=enrollment.authorization_reason,
        authorization_reference=enrollment.authorization_reference,
        authorized_by_id=enrollment.authorized_by_id,
        authorized_at=enrollment.authorized_at,
        created_at=enrollment.created_at,
        updated_at=enrollment.updated_at,
    )


def enroll_student(
    db: DBSession,
    class_section_id: uuid.UUID,
    data: EnrollmentCreate,
    *,
    actor: User | None = None,
) -> EnrollmentResponse:
    # The section row is the capacity mutex. Without FOR UPDATE two requests
    # can both read the same count, both pass the check, and one increment is
    # lost (or the class is overbooked).
    cs = _lock_class_section(db, class_section_id)
    if not cs:
        raise ValueError("Class section not found")
    if cs.status not in (ClassStatus.PLANNED, ClassStatus.ACTIVE):
        raise ValueError("Cannot enroll in a cancelled or completed class")

    student = db.query(Student).filter(Student.id == data.student_id).first()
    if not student:
        raise ValueError("Student not found")

    # The historical-intake rule is checked before any write, so a rejected
    # attempt leaves no enrolment row and no changed counter behind.
    authorization = _late_enrollment_authorization(db, cs, data, actor)

    existing = (
        db.query(Enrollment)
        .filter(
            and_(
                Enrollment.student_id == data.student_id,
                Enrollment.class_section_id == class_section_id,
            )
        )
        .first()
    )
    active_count = _active_enrollment_count(db, class_section_id)
    if existing:
        if existing.status == EnrollmentStatus.ENROLLED:
            raise ValueError("Student is already enrolled in this class section")
        if cs.capacity is not None and active_count >= cs.capacity:
            raise ValueError("Class section is at full capacity")
        # Re-enrollment keeps the original row, preserving its history.
        existing.status = EnrollmentStatus.ENROLLED
        existing.dropped_at = None
        if authorization:
            reason, reference, approver, approved_at = authorization
            existing.authorization_reason = reason
            existing.authorization_reference = reference
            existing.authorized_by_id = approver.id
            existing.authorized_at = approved_at
        _sync_enrolled_count(db, cs)
        db.commit()
        db.refresh(existing)
        return _enrollment_response(existing, student)

    if cs.capacity is not None and active_count >= cs.capacity:
        raise ValueError("Class section is at full capacity")

    enrollment = Enrollment(
        student_id=data.student_id,
        class_section_id=class_section_id,
        status=EnrollmentStatus.ENROLLED,
    )
    if authorization:
        reason, reference, approver, approved_at = authorization
        enrollment.authorization_reason = reason
        enrollment.authorization_reference = reference
        enrollment.authorized_by_id = approver.id
        enrollment.authorized_at = approved_at
    db.add(enrollment)
    _sync_enrolled_count(db, cs)
    db.commit()
    db.refresh(enrollment)
    return _enrollment_response(enrollment, student)


def drop_enrollment(
    db: DBSession, enrollment_id: uuid.UUID
) -> EnrollmentResponse:
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise ValueError("Enrollment not found")

    # Lock in the same order as enrollment: section, then enrollment row.
    cs = _lock_class_section(db, enrollment.class_section_id)
    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.id == enrollment_id)
        .with_for_update()
        .first()
    )
    if not enrollment:
        raise ValueError("Enrollment not found")
    if enrollment.status != EnrollmentStatus.ENROLLED:
        raise ValueError("Enrollment is not active")

    enrollment.status = EnrollmentStatus.DROPPED
    enrollment.dropped_at = datetime.now(UTC)
    if cs is not None:
        _sync_enrolled_count(db, cs)

    db.commit()
    db.refresh(enrollment)

    student = db.query(Student).filter(Student.id == enrollment.student_id).first()
    return _enrollment_response(enrollment, student)


def list_enrollments(
    db: DBSession, class_section_id: uuid.UUID
) -> list[EnrollmentResponse]:
    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.class_section_id == class_section_id)
        .order_by(Enrollment.enrolled_at)
        .all()
    )
    if not enrollments:
        return []

    # One query for the whole roster. This used to look up each student
    # individually, which cost one round trip per enrolment: a 1,450-student
    # cohort spread over five sections turned one roster request into ~290
    # `SELECT ... FROM students WHERE id = ...` statements. The rows returned
    # here are identical, and the missing-student case still renders `None`
    # for name and number rather than failing.
    students = {
        student.id: student
        for student in db.query(Student)
        .filter(Student.id.in_({e.student_id for e in enrollments}))
        .all()
    }
    result = []
    for e in enrollments:
        student = students.get(e.student_id)
        result.append(
            EnrollmentResponse(
                id=e.id,
                student_id=e.student_id,
                student_name=f"{student.first_name} {student.last_name}" if student else None,
                student_number=student.student_id if student else None,
                class_section_id=e.class_section_id,
                status=e.status,
                enrolled_at=e.enrolled_at,
                dropped_at=e.dropped_at,
                created_at=e.created_at,
                updated_at=e.updated_at,
            )
        )
    return result


# --- Timetable ---


def _timetable_conflict_exists(
    db: DBSession,
    classroom_id: uuid.UUID | None,
    staff_ids: list[uuid.UUID],
    day_of_week: int,
    start_time: time,
    end_time: time,
    exclude_entry_id: uuid.UUID | None = None,
    class_section_id: uuid.UUID | None = None,
    academic_period_id: uuid.UUID | None = None,
) -> AcademicRuleError | None:
    """Check for timetable conflicts. Returns the rule error to raise, or None.

    Three overlaps are rejected, all of them impossible in a real timetable:
    the same section scheduled twice, the same room double-booked, and the same
    teacher in two places at once. Each gets its own code so the client can say
    *which* of the three happened.
    """
    # A section cannot be in two places at the same time.
    if class_section_id:
        query = db.query(TimetableEntry).filter(
            and_(
                TimetableEntry.class_section_id == class_section_id,
                TimetableEntry.is_deleted.is_(False),
                TimetableEntry.day_of_week == day_of_week,
                TimetableEntry.start_time < end_time,
                TimetableEntry.end_time > start_time,
            )
        )
        if exclude_entry_id:
            query = query.filter(TimetableEntry.id != exclude_entry_id)
        if query.first():
            return AcademicRuleError(
                "TIMETABLE_SECTION_CONFLICT",
                "This class section already has a session in that time slot.",
            )

    # Check classroom conflict. Timetable rows in different academic periods
    # are different schedules, even when they share a clock time; the source
    # reference legitimately reuses rooms across terms.
    if classroom_id:
        query = db.query(TimetableEntry).filter(
            and_(
                TimetableEntry.classroom_id == classroom_id,
                TimetableEntry.is_deleted.is_(False),
                TimetableEntry.day_of_week == day_of_week,
                TimetableEntry.start_time < end_time,
                TimetableEntry.end_time > start_time,
            )
        )
        if academic_period_id is not None:
            query = query.join(ClassSection).filter(
                ClassSection.academic_period_id == academic_period_id
            )
        if exclude_entry_id:
            query = query.filter(TimetableEntry.id != exclude_entry_id)
        if query.first():
            return AcademicRuleError(
                "TIMETABLE_CLASSROOM_CONFLICT",
                "That classroom is already booked for another class at that time.",
            )

    # Check teacher conflict
    for staff_id in staff_ids:
        # Find class sections this teacher is assigned to. A ``select()`` rather
        # than ``.subquery()``: SQLAlchemy 2 warns when a Subquery is coerced
        # into IN(), and the coercion is exactly this statement.
        teacher_sections = select(TeacherAssignment.class_section_id).where(
            and_(
                TeacherAssignment.staff_id == staff_id,
                TeacherAssignment.is_active.is_(True),
            )
        )
        query = db.query(TimetableEntry).filter(
            and_(
                TimetableEntry.class_section_id.in_(teacher_sections),
                TimetableEntry.is_deleted.is_(False),
                TimetableEntry.day_of_week == day_of_week,
                TimetableEntry.start_time < end_time,
                TimetableEntry.end_time > start_time,
            )
        )
        if academic_period_id is not None:
            query = query.join(ClassSection).filter(
                ClassSection.academic_period_id == academic_period_id
            )
        if exclude_entry_id:
            query = query.filter(TimetableEntry.id != exclude_entry_id)
        if query.first():
            return AcademicRuleError(
                "TIMETABLE_TEACHER_CONFLICT",
                "That time would put a teacher in two classes at once.",
            )

    return None


def _active_teacher_staff_ids(
    db: DBSession, class_section_id: uuid.UUID
) -> list[uuid.UUID]:
    """Staff currently assigned to a section — the teachers who would clash."""
    assignments = (
        db.query(TeacherAssignment)
        .filter(
            and_(
                TeacherAssignment.class_section_id == class_section_id,
                TeacherAssignment.is_active.is_(True),
            )
        )
        .all()
    )
    return [ta.staff_id for ta in assignments]


def create_timetable_entry(
    db: DBSession, data: TimetableEntryCreate
) -> TimetableEntryResponse:
    if data.start_time >= data.end_time:
        raise AcademicRuleError(
            "TIMETABLE_INVALID_INTERVAL", "end_time must be after start_time"
        )

    lock_timetable_writes(db)
    _validate_timetable_slot(
        db,
        class_section_id=data.class_section_id,
        classroom_id=data.classroom_id,
        day_of_week=data.day_of_week,
        start_time=data.start_time,
        end_time=data.end_time,
    )

    entry = TimetableEntry(**data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _build_timetable_response(db, entry)


def _require_usable_classroom(
    db: DBSession, classroom_id: uuid.UUID | None
) -> Classroom | None:
    """Refuse to schedule into a room that is closed for maintenance."""
    if not classroom_id:
        return None
    classroom = db.query(Classroom).filter(Classroom.id == classroom_id).first()
    if not classroom:
        raise AcademicRuleError(
            "CLASSROOM_NOT_FOUND", "Classroom not found", not_found=True
        )
    if classroom.status != ClassroomStatus.AVAILABLE:
        # The room code is safe to return — it identifies which room to fix. The
        # client localises the sentence around it from the code.
        raise AcademicRuleError(
            "CLASSROOM_NOT_AVAILABLE",
            f"Classroom {classroom.room_code} is {classroom.status}, not available",
        )
    return classroom


def _validate_timetable_slot(
    db: DBSession,
    *,
    class_section_id: uuid.UUID,
    classroom_id: uuid.UUID | None,
    day_of_week: int,
    start_time: time,
    end_time: time,
    exclude_entry_id: uuid.UUID | None = None,
) -> ClassSection:
    """Validate one prospective timetable row against every scheduling rule.

    Shared by the HTTP service and the staged importer so the importer cannot
    create a row the API would reject. Callers that mutate schedule data must
    hold the transaction-scoped timetable lock before calling this function.
    """
    if start_time >= end_time:
        raise AcademicRuleError(
            "TIMETABLE_INVALID_INTERVAL", "end_time must be after start_time"
        )

    cs = db.query(ClassSection).filter(ClassSection.id == class_section_id).first()
    if not cs:
        raise AcademicRuleError(
            "CLASS_SECTION_NOT_FOUND", "Class section not found", not_found=True
        )

    _require_usable_classroom(db, classroom_id)

    staff_ids = _active_teacher_staff_ids(db, class_section_id)
    conflict = _timetable_conflict_exists(
        db,
        classroom_id,
        staff_ids,
        day_of_week,
        start_time,
        end_time,
        exclude_entry_id=exclude_entry_id,
        class_section_id=class_section_id,
        academic_period_id=cs.academic_period_id,
    )
    if conflict:
        raise conflict
    return cs


def update_timetable_entry(
    db: DBSession,
    entry: TimetableEntry,
    data: TimetableEntryUpdate,
    actor_id: uuid.UUID | None = None,
) -> TimetableEntryResponse:
    changes = data.model_dump(exclude_unset=True)

    # Merge first, then validate: a PATCH that supplies only one of the two
    # times still has to produce a valid interval, which the field-level
    # validator cannot see on its own.
    class_section_id = changes.get("class_section_id", entry.class_section_id)
    classroom_id = changes.get("classroom_id", entry.classroom_id)
    day_of_week = changes.get("day_of_week", entry.day_of_week)
    start_time = changes.get("start_time", entry.start_time)
    end_time = changes.get("end_time", entry.end_time)

    lock_timetable_writes(db)
    _validate_timetable_slot(
        db,
        class_section_id=class_section_id,
        classroom_id=classroom_id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        exclude_entry_id=entry.id,
    )

    fields = ("class_section_id", "classroom_id", "day_of_week", "start_time", "end_time")
    previous = {field: _json_value(getattr(entry, field)) for field in fields}
    for field, value in changes.items():
        setattr(entry, field, value)
    new = {field: _json_value(getattr(entry, field)) for field in fields}
    _record_academic_change(
        db,
        class_section_id=entry.class_section_id,
        entity_type="TIMETABLE",
        entity_id=entry.id,
        previous=previous,
        new=new,
        actor_id=actor_id,
    )
    db.commit()
    db.refresh(entry)
    return _build_timetable_response(db, entry)


def delete_timetable_entry(
    db: DBSession, entry_id: uuid.UUID, deleted_by_id: uuid.UUID | None = None
) -> None:
    """Retire a timetable slot without destroying the historical schedule."""
    entry = (
        db.query(TimetableEntry)
        .filter(
            TimetableEntry.id == entry_id,
            TimetableEntry.is_deleted.is_(False),
        )
        .with_for_update()
        .first()
    )
    if not entry:
        raise ValueError("Timetable entry not found")
    entry.is_deleted = True
    entry.deleted_at = datetime.now(UTC)
    entry.deleted_by_id = deleted_by_id
    db.commit()


def _build_timetable_response(
    db: DBSession, entry: TimetableEntry
) -> TimetableEntryResponse:
    teacher_names = []
    for ta in entry.class_section.teacher_assignments:
        if ta.is_active:
            staff = db.query(Staff).filter(Staff.id == ta.staff_id).first()
            if staff:
                teacher_names.append(f"{staff.first_name} {staff.last_name}")

    section = entry.class_section
    period = section.academic_period if section else None
    return TimetableEntryResponse(
        id=entry.id,
        class_section_id=entry.class_section_id,
        course_code=section.course.code if section and section.course else None,
        course_name=section.course.name if section and section.course else None,
        section_code=section.section_code if section else None,
        source_label=section.source_label if section else None,
        classroom_id=entry.classroom_id,
        classroom_name=entry.classroom.room_code if entry.classroom else None,
        day_of_week=entry.day_of_week,
        start_time=entry.start_time,
        end_time=entry.end_time,
        slot_label=entry.slot_label,
        academic_period_id=period.id if period else None,
        period_code=period.code if period else None,
        format_code=period.timetable_format_code if period else None,
        program_offerings=_program_offering_summaries(db, entry.class_section_id),
        teacher_names=teacher_names,
        is_deleted=entry.is_deleted,
        deleted_at=entry.deleted_at,
    )


def list_timetable_entries(
    db: DBSession,
    *,
    period_id: uuid.UUID | None = None,
    class_section_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    program_offering_id: uuid.UUID | None = None,
    visible_class_section_ids: set[uuid.UUID] | None = None,
    include_deleted: bool = False,
) -> list[TimetableEntryResponse]:
    resolved_period = (
        resolve_period(db, period_id)
        if period_id is not None or class_section_id is None
        else None
    )
    if period_id is None and class_section_id is None and resolved_period is None:
        return []
    query = db.query(TimetableEntry).join(
        ClassSection, TimetableEntry.class_section_id == ClassSection.id
    )
    if not include_deleted:
        query = query.filter(TimetableEntry.is_deleted.is_(False))
    if class_section_id:
        query = query.filter(TimetableEntry.class_section_id == class_section_id)
    if resolved_period:
        query = query.filter(ClassSection.academic_period_id == resolved_period.id)
    if course_id:
        query = query.filter(ClassSection.course_id == course_id)
    if program_offering_id:
        query = query.join(
            ClassSectionProgramOffering,
            ClassSectionProgramOffering.class_section_id == ClassSection.id,
        ).filter(
            ClassSectionProgramOffering.program_offering_id == program_offering_id
        )
    if visible_class_section_ids is not None:
        query = query.filter(TimetableEntry.class_section_id.in_(visible_class_section_ids))
    entries = query.order_by(
        TimetableEntry.day_of_week, TimetableEntry.start_time
    ).all()
    return [_build_timetable_response(db, e) for e in entries]


def institutional_timetable(
    db: DBSession,
    *,
    period_id: uuid.UUID | None,
    program_offering_id: uuid.UUID,
    include_diagnostics: bool = False,
) -> InstitutionalTimetableResponse:
    """The shared weekly schedule of one program offering.

    This is the institutional view, not a student's view. It is filtered by the
    selected period and offering only: a viewer who is not enrolled in any of
    the displayed courses still sees every session of that offering. Enrollment
    is never consulted, which is the whole point of the distinction.

    ``include_diagnostics`` gates the internal issue list (sections without
    sessions, rooms or teachers). A student receives the publication-facing
    status and course counts, but not the administrative breakdown.
    """
    period = resolve_period(db, period_id)
    if period is None:
        raise AcademicRuleError(
            "ACADEMIC_PERIOD_NOT_FOUND", "Academic period not found", not_found=True
        )
    offering = (
        db.query(ProgramOffering)
        .filter(
            ProgramOffering.id == program_offering_id,
            ProgramOffering.academic_period_id == period.id,
        )
        .first()
    )
    if offering is None:
        raise AcademicRuleError(
            "PROGRAM_OFFERING_NOT_FOUND",
            "Program offering not found in this academic period",
            not_found=True,
        )

    offerings = (
        db.query(ProgramOffering)
        .filter(ProgramOffering.academic_period_id == period.id)
        .order_by(ProgramOffering.name)
        .all()
    )
    sections = (
        db.query(ClassSection)
        .join(
            ClassSectionProgramOffering,
            ClassSectionProgramOffering.class_section_id == ClassSection.id,
        )
        .filter(
            ClassSectionProgramOffering.program_offering_id == offering.id,
            ClassSection.academic_period_id == period.id,
        )
        .order_by(ClassSection.source_label, ClassSection.section_code)
        .all()
    )
    entries = list_timetable_entries(
        db, period_id=period.id, program_offering_id=offering.id
    )

    sessions_by_section: dict[uuid.UUID, int] = {}
    for entry in entries:
        sessions_by_section[entry.class_section_id] = (
            sessions_by_section.get(entry.class_section_id, 0) + 1
        )

    section_rows: list[InstitutionalTimetableSection] = []
    for section in sections:
        teachers = []
        for assignment in section.teacher_assignments:
            if not assignment.is_active:
                continue
            staff = db.query(Staff).filter(Staff.id == assignment.staff_id).first()
            if staff:
                teachers.append(f"{staff.first_name} {staff.last_name}")
        section_rows.append(
            InstitutionalTimetableSection(
                id=section.id,
                course_code=section.course.code if section.course else None,
                course_name=section.course.name if section.course else None,
                section_code=section.section_code,
                source_label=section.source_label,
                teachers=teachers,
                session_count=sessions_by_section.get(section.id, 0),
            )
        )

    course_ids = {section.course_id for section in sections}
    scheduled_course_ids = {
        section.course_id
        for section in sections
        if sessions_by_section.get(section.id, 0) > 0
    }
    sections_scheduled = sum(
        1 for section in sections if sessions_by_section.get(section.id, 0) > 0
    )
    sections_without_teacher = sum(1 for row in section_rows if not row.teachers)
    entries_without_room = sum(1 for entry in entries if entry.classroom_id is None)

    if not sections:
        status = "INCOMPLETE"
        message_code = "TIMETABLE_NO_SECTIONS"
    elif sections_scheduled == len(sections):
        status = "COMPLETE"
        message_code = None
    elif sections_scheduled:
        status = "INCOMPLETE"
        message_code = "TIMETABLE_PARTIALLY_SCHEDULED"
    else:
        status = "INCOMPLETE"
        message_code = "TIMETABLE_NOT_SCHEDULED"

    issues: list[InstitutionalTimetableIssue] = []
    if include_diagnostics:
        if len(sections) - sections_scheduled:
            issues.append(
                InstitutionalTimetableIssue(
                    code="SECTIONS_WITHOUT_SESSIONS",
                    count=len(sections) - sections_scheduled,
                )
            )
        if sections_without_teacher:
            issues.append(
                InstitutionalTimetableIssue(
                    code="SECTIONS_WITHOUT_TEACHER", count=sections_without_teacher
                )
            )
        if entries_without_room:
            issues.append(
                InstitutionalTimetableIssue(
                    code="SESSIONS_WITHOUT_ROOM", count=entries_without_room
                )
            )
        if period.source_key is None:
            issues.append(
                InstitutionalTimetableIssue(code="PERIOD_NOT_MAPPED_TO_SOURCE", count=1)
            )

    return InstitutionalTimetableResponse(
        period=AcademicPeriodResponse.model_validate(period),
        program_offering=ProgramOfferingSummary.model_validate(offering),
        offerings=[ProgramOfferingSummary.model_validate(o) for o in offerings],
        sections=section_rows,
        entries=entries,
        readiness=InstitutionalTimetableReadiness(
            status=status,
            message_code=message_code,
            courses_total=len(course_ids),
            courses_scheduled=len(scheduled_course_ids),
            sessions=len(entries),
            sections_total=len(sections),
            sections_scheduled=sections_scheduled,
            issues=issues,
        ),
    )


def get_student_timetable(
    db: DBSession, student_id: uuid.UUID, period_id: uuid.UUID | None = None
) -> list[TimetableEntryResponse]:
    """Get one period's timetable for the student's offering or enrollments."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return []

    period = resolve_period(db, period_id)
    if period is None:
        return []
    class_ids = get_student_visible_class_section_ids(
        db, student_id, period_id=period.id, statuses=(EnrollmentStatus.ENROLLED,)
    )
    if not class_ids:
        return []
    # An offering can contain parallel groups for the same subject (the SCU
    # source's CS "Introduction to the Major" Group 1/2 is one). Showing both
    # to a student who is enrolled in one of them is misleading. Once the
    # student has enrollments in this period, they narrow the offering view;
    # before enrolment the offering timetable remains the useful fallback.
    enrolled_ids = get_student_class_section_ids(
        db, student_id, period_id=period.id, statuses=(EnrollmentStatus.ENROLLED,)
    )
    if enrolled_ids:
        class_ids = class_ids & enrolled_ids

    entries = (
        db.query(TimetableEntry)
        .filter(
            TimetableEntry.class_section_id.in_(class_ids),
            TimetableEntry.is_deleted.is_(False),
        )
        .order_by(TimetableEntry.day_of_week, TimetableEntry.start_time)
        .all()
    )
    return [_build_timetable_response(db, e) for e in entries]


# --- Attendance ---


def record_attendance(
    db: DBSession, data: AttendanceRecordCreate, recorded_by: uuid.UUID
) -> AttendanceRecordResponse:
    cs = db.query(ClassSection).filter(ClassSection.id == data.class_section_id).first()
    if not cs:
        raise ValueError("Class section not found")

    student = db.query(Student).filter(Student.id == data.student_id).first()
    if not student:
        raise ValueError("Student not found")

    # Verify enrollment
    enrollment = (
        db.query(Enrollment)
        .filter(
            and_(
                Enrollment.student_id == data.student_id,
                Enrollment.class_section_id == data.class_section_id,
                Enrollment.status == EnrollmentStatus.ENROLLED,
            )
        )
        .first()
    )
    if not enrollment:
        raise ValueError("Student is not enrolled in this class section")

    existing = (
        db.query(AttendanceRecord)
        .filter(
            and_(
                AttendanceRecord.student_id == data.student_id,
                AttendanceRecord.class_section_id == data.class_section_id,
                AttendanceRecord.session_date == data.session_date,
            )
        )
        .first()
    )
    if existing:
        raise ValueError(
            f"Attendance already recorded for this student on {data.session_date}"
        )

    record = AttendanceRecord(
        student_id=data.student_id,
        class_section_id=data.class_section_id,
        session_date=data.session_date,
        status=data.status,
        recorded_by=recorded_by,
        note=data.note,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return AttendanceRecordResponse(
        id=record.id,
        student_id=record.student_id,
        student_name=f"{student.first_name} {student.last_name}",
        class_section_id=record.class_section_id,
        session_date=record.session_date,
        status=record.status,
        recorded_by=record.recorded_by,
        note=record.note,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def bulk_record_attendance(
    db: DBSession,
    data: AttendanceBulkCreate,
    actor: User,
    *,
    request: Any | None = None,
) -> list[AttendanceRecordResponse]:
    """Record one class register as a single all-or-nothing change.

    The previous implementation delegated each row to
    :func:`record_attendance`, which committed on its own. A row rejected in the
    middle of a batch therefore left the rows before it behind, and the only
    trace was an audit entry carrying a count. Now every row and its own audit
    entry are staged on this session and committed once: a bad row, a duplicate
    or a failing audit write rolls the whole batch back.

    The caller supplies the actor so each entry is attributable, and does not
    commit: this function owns the single transaction boundary for the batch.
    """
    cs = db.query(ClassSection).filter(ClassSection.id == data.class_section_id).first()
    if not cs:
        raise ValueError("Class section not found")

    requested_ids = [record_data.student_id for record_data in data.records]
    students = (
        {
            student.id: student
            for student in db.query(Student).filter(Student.id.in_(requested_ids)).all()
        }
        if requested_ids
        else {}
    )
    enrolled_ids = (
        {
            row[0]
            for row in db.query(Enrollment.student_id)
            .filter(
                Enrollment.class_section_id == data.class_section_id,
                Enrollment.status == EnrollmentStatus.ENROLLED,
                Enrollment.student_id.in_(requested_ids),
            )
            .all()
        }
        if requested_ids
        else set()
    )
    already_recorded = (
        {
            row[0]
            for row in db.query(AttendanceRecord.student_id)
            .filter(
                AttendanceRecord.class_section_id == data.class_section_id,
                AttendanceRecord.session_date == data.session_date,
                AttendanceRecord.student_id.in_(requested_ids),
            )
            .all()
        }
        if requested_ids
        else set()
    )

    # Validate the entire payload before writing anything. A row that cannot be
    # recorded is a client error, not a constraint violation discovered halfway
    # through the batch.
    seen: set[uuid.UUID] = set()
    staged: list[tuple[AttendanceRecord, Student]] = []
    for record_data in data.records:
        # Override class_section_id and session_date from parent
        record_data.class_section_id = data.class_section_id
        record_data.session_date = data.session_date

        student = students.get(record_data.student_id)
        if student is None:
            raise ValueError("Student not found")
        if record_data.student_id not in enrolled_ids:
            raise ValueError("Student is not enrolled in this class section")
        if record_data.student_id in seen or record_data.student_id in already_recorded:
            raise ValueError(
                f"Attendance already recorded for this student on {data.session_date}"
            )
        seen.add(record_data.student_id)

        record = AttendanceRecord(
            student_id=record_data.student_id,
            class_section_id=data.class_section_id,
            session_date=data.session_date,
            status=record_data.status,
            recorded_by=actor.id,
            note=record_data.note,
        )
        db.add(record)
        staged.append((record, student))

    try:
        # Flush before auditing: the entry needs the generated id, and a unique
        # breach must surface before any audit row is staged.
        db.flush()
        for record, _student in staged:
            record_audit(
                db,
                action="academic.attendance.updated",
                actor=actor,
                entity_type="attendance_record",
                entity_id=record.id,
                # Identifiers and before/after values only. A create has no
                # previous state, so the previous fields are explicitly null
                # rather than omitted: a reader must not have to infer that.
                context={
                    "student_id": str(record.student_id),
                    "class_section_id": str(record.class_section_id),
                    # Not `session_date`: the audit sanitizer redacts any key
                    # containing "session", which silently blanked the date.
                    "attendance_date": record.session_date.isoformat(),
                    "previous_status": None,
                    "new_status": AttendanceStatus(record.status).value,
                    "previous_note": None,
                    "new_note": record.note,
                },
                request=request,
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        # The unique constraint is authoritative, but only report a duplicate
        # when a duplicate is really what happened.
        duplicate = (
            db.query(AttendanceRecord.id)
            .filter(
                AttendanceRecord.class_section_id == data.class_section_id,
                AttendanceRecord.session_date == data.session_date,
                AttendanceRecord.student_id.in_(requested_ids),
            )
            .first()
        )
        if duplicate is not None:
            raise ValueError(
                f"Attendance already recorded for this student on {data.session_date}"
            ) from None
        raise
    except Exception:
        # The register and its audit trail share one transaction: if the audit
        # write fails, the attendance rows must not survive without it.
        db.rollback()
        raise

    return [
        AttendanceRecordResponse(
            id=record.id,
            student_id=record.student_id,
            student_name=f"{student.first_name} {student.last_name}",
            class_section_id=record.class_section_id,
            session_date=record.session_date,
            status=record.status,
            recorded_by=record.recorded_by,
            note=record.note,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        for record, student in staged
    ]


def list_attendance(
    db: DBSession,
    class_section_id: uuid.UUID,
    session_date: date | None = None,
) -> list[AttendanceRecordResponse]:
    query = db.query(AttendanceRecord).filter(
        AttendanceRecord.class_section_id == class_section_id
    )
    if session_date:
        query = query.filter(AttendanceRecord.session_date == session_date)
    records = query.order_by(AttendanceRecord.session_date).all()
    result = []
    for r in records:
        student = db.query(Student).filter(Student.id == r.student_id).first()
        result.append(
            AttendanceRecordResponse(
                id=r.id,
                student_id=r.student_id,
                student_name=f"{student.first_name} {student.last_name}" if student else None,
                class_section_id=r.class_section_id,
                session_date=r.session_date,
                status=r.status,
                recorded_by=r.recorded_by,
                note=r.note,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return result


def get_student_attendance(
    db: DBSession, student_id: uuid.UUID
) -> list[AttendanceRecordResponse]:
    records = (
        db.query(AttendanceRecord)
        .filter(AttendanceRecord.student_id == student_id)
        .order_by(AttendanceRecord.session_date.desc())
        .all()
    )
    result = []
    for r in records:
        student = db.query(Student).filter(Student.id == r.student_id).first()
        result.append(
            AttendanceRecordResponse(
                id=r.id,
                student_id=r.student_id,
                student_name=f"{student.first_name} {student.last_name}" if student else None,
                class_section_id=r.class_section_id,
                session_date=r.session_date,
                status=r.status,
                recorded_by=r.recorded_by,
                note=r.note,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return result


# --- Assessment ---


def create_assessment(
    db: DBSession, data: AssessmentCreate
) -> AssessmentResponse:
    cs = db.query(ClassSection).filter(ClassSection.id == data.class_section_id).first()
    if not cs:
        raise ValueError("Class section not found")
    assessment = Assessment(**data.model_dump())
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return AssessmentResponse.model_validate(assessment)


def update_assessment(
    db: DBSession,
    assessment: Assessment,
    data: AssessmentUpdate,
    actor_id: uuid.UUID | None = None,
) -> AssessmentResponse:
    """Edit an assessment, preserving the previous definition.

    The row is locked against concurrent grade writes. Lowering ``max_score``
    below an existing score would leave the gradebook internally inconsistent,
    so the edit is refused until those grades are corrected first.
    """
    locked = (
        db.query(Assessment)
        .filter(Assessment.id == assessment.id)
        .with_for_update()
        .first()
    )
    if locked is not None:
        assessment = locked

    changes = data.model_dump(exclude_unset=True)
    new_max = changes.get("max_score", assessment.max_score)
    if new_max is not None:
        too_high = (
            db.query(Grade)
            .filter(
                Grade.assessment_id == assessment.id,
                Grade.score > new_max,
            )
            .first()
        )
        if too_high:
            raise AcademicRuleError(
                "ASSESSMENT_MAX_BELOW_EXISTING_GRADE",
                "The maximum score cannot be lower than an existing grade for "
                "this assessment.",
            )

    fields = ("name", "assessment_type", "max_score", "weight", "due_date")
    previous = {field: _json_value(getattr(assessment, field)) for field in fields}
    for field, value in changes.items():
        setattr(assessment, field, value)
    new = {field: _json_value(getattr(assessment, field)) for field in fields}
    _record_academic_change(
        db,
        class_section_id=assessment.class_section_id,
        entity_type="ASSESSMENT",
        entity_id=assessment.id,
        previous=previous,
        new=new,
        actor_id=actor_id,
    )
    db.commit()
    db.refresh(assessment)
    return AssessmentResponse.model_validate(assessment)


def list_assessments(
    db: DBSession, class_section_id: uuid.UUID
) -> list[AssessmentResponse]:
    assessments = (
        db.query(Assessment)
        .filter(Assessment.class_section_id == class_section_id)
        .order_by(Assessment.due_date)
        .all()
    )
    return [AssessmentResponse.model_validate(a) for a in assessments]


# --- Grade ---


def _require_grade_enrollment(
    db: DBSession, class_section_id: uuid.UUID, student_id: uuid.UUID
) -> None:
    enrollment = (
        db.query(Enrollment.id)
        .filter(
            Enrollment.class_section_id == class_section_id,
            Enrollment.student_id == student_id,
            Enrollment.status == EnrollmentStatus.ENROLLED,
        )
        .first()
    )
    if not enrollment:
        raise AcademicRuleError(
            "GRADE_STUDENT_NOT_ENROLLED",
            "The student does not have an active enrollment in this class section.",
        )


def _require_assessment_in_class(
    assessment: Assessment | None, class_section_id: uuid.UUID
) -> Assessment:
    if assessment is None:
        raise AcademicRuleError(
            "ASSESSMENT_NOT_FOUND", "Assessment not found", not_found=True
        )
    if assessment.class_section_id != class_section_id:
        raise AcademicRuleError(
            "GRADE_ASSESSMENT_CLASS_MISMATCH",
            "The assessment does not belong to this class section.",
        )
    return assessment


def _require_grade_score(assessment: Assessment, score: float) -> None:
    if score < 0 or score > assessment.max_score:
        raise AcademicRuleError(
            "GRADE_SCORE_OUT_OF_BOUNDS",
            f"Score must be between 0 and {assessment.max_score:g}.",
        )


def _lock_assessment(db: DBSession, assessment_id: uuid.UUID) -> Assessment | None:
    """Lock the assessment so a max-score edit and a grade write cannot race."""
    return (
        db.query(Assessment)
        .filter(Assessment.id == assessment_id)
        .with_for_update()
        .first()
    )


def _grade_response(
    grade: Grade, assessment: Assessment | None, student: Student | None
) -> GradeResponse:
    return GradeResponse(
        id=grade.id,
        assessment_id=grade.assessment_id,
        assessment_name=assessment.name if assessment else None,
        student_id=grade.student_id,
        student_name=(
            f"{student.first_name} {student.last_name}" if student else None
        ),
        score=grade.score,
        letter_grade=grade.letter_grade,
        recorded_by=grade.recorded_by,
        note=grade.note,
        created_at=grade.created_at,
        updated_at=grade.updated_at,
    )


def record_grade(
    db: DBSession,
    class_section_id: uuid.UUID,
    data: GradeCreate,
    recorded_by: uuid.UUID,
) -> GradeResponse:
    assessment = _require_assessment_in_class(
        _lock_assessment(db, data.assessment_id), class_section_id
    )

    student = db.query(Student).filter(Student.id == data.student_id).first()
    if not student:
        raise AcademicRuleError("STUDENT_NOT_FOUND", "Student not found", not_found=True)

    _require_grade_enrollment(db, class_section_id, data.student_id)
    _require_grade_score(assessment, data.score)

    existing = (
        db.query(Grade)
        .filter(
            and_(
                Grade.assessment_id == data.assessment_id,
                Grade.student_id == data.student_id,
            )
        )
        .first()
    )
    if existing:
        raise ValueError("Grade already exists for this student and assessment")

    grade = Grade(
        assessment_id=data.assessment_id,
        student_id=data.student_id,
        score=data.score,
        letter_grade=data.letter_grade,
        recorded_by=recorded_by,
        note=data.note,
    )
    db.add(grade)
    db.commit()
    db.refresh(grade)
    return _grade_response(grade, assessment, student)


def update_grade(
    db: DBSession,
    class_section_id: uuid.UUID,
    grade: Grade,
    data: GradeUpdate,
    actor_id: uuid.UUID | None = None,
) -> GradeResponse:
    """Correct a grade while retaining the previous score and note."""
    locked_grade = (
        db.query(Grade).filter(Grade.id == grade.id).with_for_update().first()
    )
    if locked_grade is not None:
        grade = locked_grade

    assessment = _require_assessment_in_class(
        _lock_assessment(db, grade.assessment_id), class_section_id
    )
    _require_grade_enrollment(db, class_section_id, grade.student_id)

    changes = data.model_dump(exclude_unset=True)
    new_score = changes.get("score", grade.score)
    _require_grade_score(assessment, new_score)

    fields = ("score", "letter_grade", "note")
    previous = {field: getattr(grade, field) for field in fields}
    for field, value in changes.items():
        setattr(grade, field, value)
    new = {field: getattr(grade, field) for field in fields}
    _record_academic_change(
        db,
        class_section_id=assessment.class_section_id,
        entity_type="GRADE",
        entity_id=grade.id,
        previous=previous,
        new=new,
        actor_id=actor_id,
    )
    db.commit()
    db.refresh(grade)

    student = db.query(Student).filter(Student.id == grade.student_id).first()
    return _grade_response(grade, assessment, student)


def list_grades_for_class(
    db: DBSession, class_section_id: uuid.UUID
) -> list[GradeResponse]:
    grades = (
        db.query(Grade)
        .join(Assessment)
        .filter(Assessment.class_section_id == class_section_id)
        .all()
    )
    result = []
    for g in grades:
        assessment = db.query(Assessment).filter(Assessment.id == g.assessment_id).first()
        student = db.query(Student).filter(Student.id == g.student_id).first()
        result.append(
            GradeResponse(
                id=g.id,
                assessment_id=g.assessment_id,
                assessment_name=assessment.name if assessment else None,
                student_id=g.student_id,
                student_name=f"{student.first_name} {student.last_name}" if student else None,
                score=g.score,
                letter_grade=g.letter_grade,
                recorded_by=g.recorded_by,
                note=g.note,
                created_at=g.created_at,
                updated_at=g.updated_at,
            )
        )
    return result


def list_grades_for_student(
    db: DBSession, student_id: uuid.UUID
) -> list[GradeResponse]:
    grades = (
        db.query(Grade)
        .filter(Grade.student_id == student_id)
        .all()
    )
    result = []
    for g in grades:
        assessment = db.query(Assessment).filter(Assessment.id == g.assessment_id).first()
        student = db.query(Student).filter(Student.id == g.student_id).first()
        result.append(
            GradeResponse(
                id=g.id,
                assessment_id=g.assessment_id,
                assessment_name=assessment.name if assessment else None,
                student_id=g.student_id,
                student_name=f"{student.first_name} {student.last_name}" if student else None,
                score=g.score,
                letter_grade=g.letter_grade,
                recorded_by=g.recorded_by,
                note=g.note,
                created_at=g.created_at,
                updated_at=g.updated_at,
            )
        )
    return result


# --- Student Academic Overview ---


def get_student_academic_overview(
    db: DBSession, student_id: uuid.UUID, period_id: uuid.UUID | None = None
) -> StudentAcademicOverview | None:
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return None

    academic = student_academic_snapshot(db, student.id)
    major_resp = (
        MajorResponse.model_validate(academic.major) if academic.major else None
    )
    program_resp = None
    if academic.program is not None:
        program_resp = ProgramResponse.model_validate(academic.program)
        program_resp.major_name = (
            academic.program.major.name if academic.program.major else None
        )

    offering_resp = (
        ProgramOfferingSummary.model_validate(academic.offering)
        if academic.offering
        else None
    )

    active_period = resolve_period(db)
    selected_period = resolve_period(db, period_id)
    current_resp = (
        AcademicPeriodResponse.model_validate(active_period)
        if active_period
        else None
    )
    period_resp = (
        AcademicPeriodResponse.model_validate(selected_period)
        if selected_period
        else None
    )
    is_current = bool(active_period and selected_period and active_period.id == selected_period.id)

    enrolled_classes = []
    timetable_entries = []
    if selected_period:
        class_ids = get_student_visible_class_section_ids(
            db,
            student_id,
            period_id=selected_period.id,
            statuses=(
                EnrollmentStatus.ENROLLED,
                EnrollmentStatus.COMPLETED,
            ),
        )
        # The offering view includes every parallel group linked to the
        # offering. Once the student has actual enrollments in this period,
        # their own sections are the authoritative timetable scope.
        enrolled_ids = get_student_class_section_ids(
            db,
            student_id,
            period_id=selected_period.id,
            statuses=(
                EnrollmentStatus.ENROLLED,
                EnrollmentStatus.COMPLETED,
            ),
        )
        if enrolled_ids:
            class_ids = class_ids & enrolled_ids
        for cs_id in class_ids:
            cs = db.query(ClassSection).filter(ClassSection.id == cs_id).first()
            if cs:
                enrolled_classes.append(
                    ClassSectionBrief(
                        id=cs.id,
                        course_code=cs.course.code if cs.course else None,
                        course_name=cs.course.name if cs.course else None,
                        section_code=cs.section_code,
                        source_label=cs.source_label,
                        academic_period_id=cs.academic_period_id,
                        academic_period_name=(
                            cs.academic_period.name if cs.academic_period else None
                        ),
                        enrolled_count=cs.enrolled_count,
                        capacity=cs.capacity,
                        status=cs.status,
                        program_offerings=_program_offering_summaries(db, cs.id),
                    )
                )
                timetable_entries.extend(
                    list_timetable_entries(
                        db,
                        period_id=selected_period.id,
                        class_section_id=cs.id,
                    )
                )

    return StudentAcademicOverview(
        student_id=student.id,
        student_name=f"{student.first_name} {student.last_name}",
        major=major_resp,
        program=program_resp,
        program_offering=offering_resp,
        current_period=current_resp,
        selected_period=period_resp,
        is_current=is_current,
        enrolled_classes=enrolled_classes,
        timetable=timetable_entries,
    )


def list_program_offerings(
    db: DBSession,
    *,
    period_id: uuid.UUID | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> ProgramOfferingListResponse:
    period = resolve_period(db, period_id)
    if period is None:
        return ProgramOfferingListResponse(
            items=[],
            meta=PaginationMeta(page=page, page_size=page_size, total=0, total_pages=1),
        )
    query = db.query(ProgramOffering).filter(
        ProgramOffering.academic_period_id == period.id
    )
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            ProgramOffering.name.ilike(pattern)
            | ProgramOffering.name_zh.ilike(pattern)
            | ProgramOffering.source_id.ilike(pattern)
        )
    meta = _paginate(query, page, page_size)
    offerings = (
        query.order_by(ProgramOffering.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = [_offering_response(offering) for offering in offerings]
    return ProgramOfferingListResponse(items=result, meta=meta)


def get_program_offering(
    db: DBSession, offering_id: uuid.UUID
) -> ProgramOffering | None:
    return db.query(ProgramOffering).filter(ProgramOffering.id == offering_id).first()


def _offering_response(offering: ProgramOffering) -> ProgramOfferingResponse:
    """Expose whether a source offering is a valid student placement.

    The source catalog is evidence, not an authorization list. An offering is
    selectable only when it belongs to an open intake and has a reviewed
    canonical program and major.
    """
    response = ProgramOfferingResponse.model_validate(offering)
    response.program_name = offering.program.name if offering.program else None
    reason: str | None = None
    if offering.academic_period is not None and offering.academic_period.status in {
        AcademicPeriodStatus.CANCELLED,
        AcademicPeriodStatus.COMPLETED,
    }:
        reason = "INTAKE_CLOSED"
    elif offering.program_id is None or offering.program is None:
        reason = "SOURCE_ONLY"
    elif offering.program.status != EntityStatus.ACTIVE:
        reason = "PROGRAM_INACTIVE"
    elif offering.program.major is None or offering.program.major.status != EntityStatus.ACTIVE:
        reason = "MAJOR_INACTIVE"
    response.selectable = reason is None
    response.unavailable_reason = reason
    return response


def create_program_offering(
    db: DBSession, data: ProgramOfferingCreate
) -> ProgramOfferingResponse:
    """Create a manually managed period offering, never an imported mapping."""
    if not db.query(AcademicPeriod).filter(
        AcademicPeriod.id == data.academic_period_id
    ).first():
        raise AcademicRuleError(
            "ACADEMIC_PERIOD_NOT_FOUND", "Academic period not found.", not_found=True
        )
    if data.program_id and not db.query(Program).filter(
        Program.id == data.program_id
    ).first():
        raise AcademicRuleError(
            "PROGRAM_NOT_FOUND", "Canonical program not found.", not_found=True
        )

    source_id = data.source_id.strip()
    existing = (
        db.query(ProgramOffering)
        .filter(
            ProgramOffering.academic_period_id == data.academic_period_id,
            ProgramOffering.source_id == source_id,
        )
        .first()
    )
    if existing:
        raise AcademicRuleError(
            "PROGRAM_OFFERING_EXISTS",
            "That source offering identifier already exists in this intake.",
        )

    offering = ProgramOffering(
        academic_period_id=data.academic_period_id,
        program_id=data.program_id,
        source_id=source_id,
        source_key=f"manual:{data.academic_period_id}:{source_id}",
        name=data.name.strip(),
        name_zh=data.name_zh.strip() if data.name_zh else None,
    )
    db.add(offering)
    db.flush()
    db.refresh(offering)
    return _offering_response(offering)


def update_program_offering(
    db: DBSession, offering: ProgramOffering, data: ProgramOfferingUpdate
) -> ProgramOfferingResponse:
    """Edit names or the reviewed canonical parent; never the source identity."""
    changes = data.model_dump(exclude_unset=True)
    if (
        "program_id" in changes
        and changes["program_id"] is not None
        and not db.query(Program).filter(Program.id == changes["program_id"]).first()
    ):
        raise AcademicRuleError(
            "PROGRAM_NOT_FOUND", "Canonical program not found.", not_found=True
        )
    for field, value in changes.items():
        setattr(offering, field, value)
    db.flush()
    db.refresh(offering)
    return _offering_response(offering)


def set_class_section_program_offerings(
    db: DBSession,
    section: ClassSection,
    data: SectionProgramOfferingUpdate,
) -> ClassSectionResponse:
    """Replace the offering links of one canonical section.

    Every link must belong to the section's own academic period. This is the
    server-side guard that keeps a shared class from being attached to another
    intake merely because its ids were pasted into the wrong dialog.
    """
    requested_ids = list(dict.fromkeys(data.program_offering_ids))
    offerings = []
    if requested_ids:
        offerings = (
            db.query(ProgramOffering)
            .filter(ProgramOffering.id.in_(requested_ids))
            .all()
        )
        by_id = {offering.id: offering for offering in offerings}
        if any(offering_id not in by_id for offering_id in requested_ids):
            raise AcademicRuleError(
                "PROGRAM_OFFERING_NOT_FOUND",
                "One or more program offerings were not found.",
                not_found=True,
            )
        if any(
            by_id[offering_id].academic_period_id != section.academic_period_id
            for offering_id in requested_ids
        ):
            raise AcademicRuleError(
                "PROGRAM_OFFERING_PERIOD_MISMATCH",
                "A section and its program offerings must share one intake.",
            )

    db.query(ClassSectionProgramOffering).filter(
        ClassSectionProgramOffering.class_section_id == section.id
    ).delete(synchronize_session=False)
    for offering_id in requested_ids:
        db.add(
            ClassSectionProgramOffering(
                class_section_id=section.id,
                program_offering_id=offering_id,
            )
        )
    db.flush()
    db.refresh(section)
    return _build_class_section_response(db, section)
