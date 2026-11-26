"""Academic API endpoints."""

from __future__ import annotations

import uuid  # noqa: TC003

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import field_changes, record_audit
from app.auth.dependencies import (
    get_current_active_user,
    get_db,
)
from app.config.settings import get_settings
from app.models.academic import AcademicPeriod  # noqa: TC001
from app.models.admission import AcademicPeriodDateCorrection  # noqa: TC001
from app.models.identity import User  # noqa: TC001
from app.permissions.checks import has_permission, require_permission
from app.schemas.academic import (
    AcademicChangeHistoryResponse,
    AcademicImportApplyRequest,
    AcademicImportBatchReport,
    AcademicPeriodCreate,
    AcademicPeriodDateCorrectionCreate,
    AcademicPeriodDateCorrectionResponse,
    AcademicPeriodListResponse,
    AcademicPeriodResponse,
    AcademicPeriodUpdate,
    AssessmentCreate,
    AssessmentResponse,
    AssessmentUpdate,
    AttendanceBulkCreate,
    AttendanceRecordResponse,
    ClassroomCreate,
    ClassroomListResponse,
    ClassroomResponse,
    ClassroomUpdate,
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
    InstitutionalTimetableResponse,
    GradeResponse,
    GradeUpdate,
    IntakePlanRequest,
    MajorCreate,
    MajorListResponse,
    MajorResponse,
    MajorUpdate,
    ProgramCreate,
    ProgramListResponse,
    ProgramOfferingCreate,
    ProgramOfferingListResponse,
    ProgramOfferingResponse,
    ProgramOfferingUpdate,
    ProgramResponse,
    ProgramUpdate,
    SectionProgramOfferingUpdate,
    SourceIntakeListResponse,
    TeachableStaffListResponse,
    TeacherAssignmentCreate,
    TeacherAssignmentResponse,
    TimetableEntryCreate,
    TimetableEntryResponse,
    TimetableEntryUpdate,
    TimetableListResponse,
)
from app.services import academic as svc
from app.services import academic_import as import_svc
from app.services import intake_plan as intake_svc
from app.services import period_correction as correction_svc
from app.services import source_intakes as source_intake_svc
from app.services import timetable_reconciliation as reconciliation_svc

router = APIRouter(prefix="/academics", tags=["academics"])


# ── Helpers ──


def _academic_rule_error(exc: ValueError) -> HTTPException:
    """Map a failed academic rule to a stable, localisable API error.

    ``AcademicRuleError`` carries its own code and whether it is really a
    missing row, which is what lets the client say precisely what went wrong
    ("that classroom is already booked") in the user's own language. A bare
    ``ValueError`` from a path not yet converted degrades to a generic conflict
    instead of escaping as a 500.
    """
    if isinstance(exc, svc.AcademicRuleError):
        return HTTPException(
            status_code=404 if exc.not_found else 409,
            detail={"error": {"code": exc.code, "message": str(exc)}},
        )
    return HTTPException(
        status_code=409,
        detail={"error": {"code": "CONFLICT", "message": str(exc)}},
    )


def _check_student_scope(
    current_user: User,
    student_id: uuid.UUID,
    db: DBSession,
) -> None:
    """Students can only access own data; teachers only their assigned students."""
    role_names = {r.name for r in current_user.roles}

    if "STUDENT" in role_names:
        from app.models.identity import Student
        student = db.query(Student).filter(Student.user_id == current_user.id).first()
        if not student or student.id != student_id:
            raise HTTPException(status_code=403, detail="Cannot access other students' data")

    if "TEACHER" in role_names and "ADMIN" not in role_names and "MANAGEMENT" not in role_names:
        from app.models.identity import Staff
        staff = db.query(Staff).filter(Staff.user_id == current_user.id).first()
        if staff is None or not staff.is_active:
            raise HTTPException(status_code=403, detail="No access to this student's data")
        student_class_ids = svc.get_student_class_section_ids(db, student_id)
        teacher_class_ids = svc.get_teacher_class_section_ids(db, staff.id)
        if not student_class_ids.intersection(teacher_class_ids):
            raise HTTPException(status_code=403, detail="No access to this student's data")


def _visible_class_section_ids(
    current_user: User, db: DBSession
) -> set[uuid.UUID] | None:
    """Return the sections a role may read, or None for unrestricted staff.

    Admin/Management are unrestricted. Teachers see only their assigned
    sections and students only their enrolled sections. The timetable and class
    lists must never be broader than this in the API itself, regardless of what
    the UI selects.
    """
    role_names = {r.name for r in current_user.roles}
    if {"ADMIN", "MANAGEMENT"} & role_names:
        return None
    if "TEACHER" in role_names:
        from app.models.identity import Staff
        staff = db.query(Staff).filter(Staff.user_id == current_user.id).first()
        return (
            svc.get_teacher_class_section_ids(db, staff.id)
            if staff and staff.is_active
            else set()
        )
    if "STUDENT" in role_names:
        from app.models.identity import Student
        student = db.query(Student).filter(Student.user_id == current_user.id).first()
        return (
            svc.get_student_visible_class_section_ids(db, student.id)
            if student
            else set()
        )
    return set()


def _require_class_records_access(
    current_user: User,
    class_id: uuid.UUID,
    db: DBSession,
) -> None:
    """Guard class-scoped *records* (rosters, attendance, grades).

    These endpoints return every student in a class, so an enrolled student
    must be refused even though they may legitimately read their own attendance
    and grades through the per-student endpoints.

    Admin/Management: always allowed.
    Teacher: only for a class they are assigned to.
    Everyone else: forbidden.
    """
    role_names = {r.name for r in current_user.roles}

    if {"ADMIN", "MANAGEMENT"} & role_names:
        return

    if "TEACHER" in role_names and svc.can_access_class_section(
        db, current_user, class_id
    ):
        return

    raise HTTPException(
        status_code=403,
        detail="You do not have access to this class's student records",
    )


def _audit_mutation(
    db: DBSession,
    request: Request,
    actor: User,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    context: dict | None = None,
) -> None:
    """Record an academic configuration change.

    Configuration edits (a course's credits, a section's room, a schedule slot)
    decide what a student's record will eventually say, so they are audited on
    the same footing as the student-facing changes they affect. Only
    identifiers and enum values go in the context — never roster contents.
    """
    record_audit(
        db,
        action=action,
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        context=context,
        request=request,
    )
    db.commit()


# ── Majors ──


@router.get("/majors", response_model=MajorListResponse)
def list_majors(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    return svc.list_majors(db, page=page, page_size=page_size, search=search)


@router.get("/majors/{major_id}", response_model=MajorResponse)
def get_major(
    major_id: uuid.UUID,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    major = svc.get_major(db, major_id)
    if not major:
        raise HTTPException(status_code=404, detail="Major not found")
    return MajorResponse.model_validate(major)


@router.post("/majors", response_model=MajorResponse, status_code=201)
def create_major(
    data: MajorCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_majors")),
    db: DBSession = Depends(get_db),
):
    try:
        major = svc.create_major(db, data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.major.created", entity_type="major", entity_id=major.id,
        context={"code": major.code},
    )
    return major


@router.patch("/majors/{major_id}", response_model=MajorResponse)
def update_major(
    major_id: uuid.UUID,
    data: MajorUpdate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_majors")),
    db: DBSession = Depends(get_db),
):
    major = svc.get_major(db, major_id)
    if not major:
        raise HTTPException(status_code=404, detail="Major not found")
    updated = svc.update_major(db, major, data)
    _audit_mutation(
        db, request, current_user,
        action="academic.major.updated", entity_type="major", entity_id=major_id,
        context={"fields": sorted(data.model_dump(exclude_unset=True))},
    )
    return updated


# ── Programs ──


@router.get("/programs", response_model=ProgramListResponse)
def list_programs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    return svc.list_programs(db, page=page, page_size=page_size, search=search)


@router.get("/programs/{program_id}", response_model=ProgramResponse)
def get_program(
    program_id: uuid.UUID,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    from app.schemas.academic import ProgramResponse
    program = svc.get_program(db, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    resp = ProgramResponse.model_validate(program)
    resp.major_name = program.major.name if program.major else None
    return resp


@router.post("/programs", response_model=ProgramResponse, status_code=201)
def create_program(
    data: ProgramCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_programs")),
    db: DBSession = Depends(get_db),
):
    try:
        program = svc.create_program(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.program.created", entity_type="program",
        entity_id=program.id, context={"code": program.code},
    )
    return program


@router.patch("/programs/{program_id}", response_model=ProgramResponse)
def update_program(
    program_id: uuid.UUID,
    data: ProgramUpdate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_programs")),
    db: DBSession = Depends(get_db),
):
    program = svc.get_program(db, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    updated = svc.update_program(db, program, data)
    _audit_mutation(
        db, request, current_user,
        action="academic.program.updated", entity_type="program",
        entity_id=program_id,
        context={"fields": sorted(data.model_dump(exclude_unset=True))},
    )
    return updated


# ── Courses ──


@router.get("/courses", response_model=CourseListResponse)
def list_courses(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    return svc.list_courses(db, page=page, page_size=page_size, search=search)


@router.get("/courses/{course_id}", response_model=CourseResponse)
def get_course(
    course_id: uuid.UUID,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    from app.schemas.academic import CourseResponse
    course = svc.get_course(db, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    resp = CourseResponse.model_validate(course)
    resp.program_name = course.program.name if course.program else None
    return resp


@router.post("/courses", response_model=CourseResponse, status_code=201)
def create_course(
    data: CourseCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_courses")),
    db: DBSession = Depends(get_db),
):
    try:
        course = svc.create_course(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.course.created", entity_type="course",
        entity_id=course.id, context={"code": course.code},
    )
    return course


@router.patch("/courses/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: uuid.UUID,
    data: CourseUpdate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_courses")),
    db: DBSession = Depends(get_db),
):
    course = svc.get_course(db, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    updated = svc.update_course(db, course, data)
    _audit_mutation(
        db, request, current_user,
        action="academic.course.updated", entity_type="course", entity_id=course_id,
        context={"fields": sorted(data.model_dump(exclude_unset=True))},
    )
    return updated


# ── Academic Periods ──


@router.get("/source-intakes", response_model=SourceIntakeListResponse)
def list_source_intakes(
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    """Read the accepted source catalog without creating academic records."""
    return source_intake_svc.list_source_intakes(db)


@router.get("/periods", response_model=AcademicPeriodListResponse)
def list_periods(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    return svc.list_academic_periods(db, page=page, page_size=page_size)


@router.get("/periods/{period_id}", response_model=AcademicPeriodResponse)
def get_period(
    period_id: uuid.UUID,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    period = svc.get_academic_period(db, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Academic period not found")
    return svc.period_response(db, period)


@router.post("/periods", response_model=AcademicPeriodResponse, status_code=201)
def create_period(
    data: AcademicPeriodCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_periods")),
    db: DBSession = Depends(get_db),
):
    try:
        period = svc.create_academic_period(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.period.created", entity_type="academic_period",
        entity_id=period.id, context={"code": period.code},
    )
    return period


@router.patch("/periods/{period_id}", response_model=AcademicPeriodResponse)
def update_period(
    period_id: uuid.UUID,
    data: AcademicPeriodUpdate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_periods")),
    db: DBSession = Depends(get_db),
):
    period = svc.get_academic_period(db, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Academic period not found")
    try:
        updated = svc.update_academic_period(db, period, data)
    except ValueError as exc:
        db.rollback()
        raise _academic_rule_error(exc) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.period.updated", entity_type="academic_period",
        entity_id=period_id,
        context={"fields": sorted(data.model_dump(exclude_unset=True))},
    )
    return updated


def _correction_error(exc: correction_svc.PeriodCorrectionError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error": {"code": exc.code, "message": str(exc)}},
    )


def _correction_response(
    correction: AcademicPeriodDateCorrection,
    actor_name: str | None,
) -> AcademicPeriodDateCorrectionResponse:
    return AcademicPeriodDateCorrectionResponse(
        id=correction.id,
        academic_period_id=correction.academic_period_id,
        previous_start_date=correction.previous_start_date,
        previous_end_date=correction.previous_end_date,
        new_start_date=correction.new_start_date,
        new_end_date=correction.new_end_date,
        reason=correction.reason,
        actor_id=correction.actor_id,
        actor_name=actor_name,
        created_at=correction.created_at,
        placements_reflagged=correction.placements_reflagged,
        admissions_rechecked=correction.admissions_rechecked,
    )


def _require_date_correction_enabled() -> None:
    if not get_settings().ADMISSION_DATE_CORRECTION_ENABLED:
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "code": "PERIOD_CORRECTION_DISABLED",
                    "message": "Intake date correction is currently disabled.",
                }
            },
        )


@router.get(
    "/periods/{period_id}/date-corrections",
    response_model=list[AcademicPeriodDateCorrectionResponse],
)
def list_period_date_corrections(
    period_id: uuid.UUID,
    _user: User = Depends(require_permission("academic.correct_period_dates")),
    db: DBSession = Depends(get_db),
):
    period = svc.get_academic_period(db, period_id)
    if not period:
        raise HTTPException(status_code=404, detail="Academic period not found")
    rows = (
        db.query(AcademicPeriodDateCorrection, User.full_name)
        .join(User, User.id == AcademicPeriodDateCorrection.actor_id)
        .filter(AcademicPeriodDateCorrection.academic_period_id == period_id)
        .order_by(
            AcademicPeriodDateCorrection.created_at.desc(),
            AcademicPeriodDateCorrection.id.desc(),
        )
        .all()
    )
    return [_correction_response(correction, actor_name) for correction, actor_name in rows]


@router.post(
    "/periods/{period_id}/date-correction",
    response_model=AcademicPeriodDateCorrectionResponse,
    status_code=201,
)
def correct_period_dates(
    period_id: uuid.UUID,
    data: AcademicPeriodDateCorrectionCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.correct_period_dates")),
    db: DBSession = Depends(get_db),
):
    _require_date_correction_enabled()
    try:
        result = correction_svc.correct_period_dates(
            db, period_id, data, actor=current_user
        )
        record_audit(
            db,
            action="academic.period.dates_corrected",
            actor=current_user,
            entity_type="academic_period",
            entity_id=period_id,
            context={
                "previous_start_date": result.correction.previous_start_date.isoformat(),
                "previous_end_date": result.correction.previous_end_date.isoformat(),
                "new_start_date": result.correction.new_start_date.isoformat(),
                "new_end_date": result.correction.new_end_date.isoformat(),
                "reason": result.correction.reason,
                "evidence_reference": data.evidence_reference,
                "placements_reflagged": result.placements_reflagged,
                "admissions_rechecked": result.admissions_rechecked,
            },
            request=request,
        )
        db.commit()
    except correction_svc.PeriodCorrectionError as exc:
        db.rollback()
        raise _correction_error(exc) from None
    except Exception:
        db.rollback()
        raise

    return _correction_response(result.correction, current_user.full_name)


# ── Classrooms ──


@router.get("/classrooms", response_model=ClassroomListResponse)
def list_classrooms(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    return svc.list_classrooms(db, page=page, page_size=page_size, search=search)


@router.get("/classrooms/{classroom_id}", response_model=ClassroomResponse)
def get_classroom(
    classroom_id: uuid.UUID,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    classroom = svc.get_classroom(db, classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    return ClassroomResponse.model_validate(classroom)


@router.post("/classrooms", response_model=ClassroomResponse, status_code=201)
def create_classroom(
    data: ClassroomCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_classrooms")),
    db: DBSession = Depends(get_db),
):
    try:
        classroom = svc.create_classroom(db, data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.classroom.created", entity_type="classroom",
        entity_id=classroom.id, context={"room_code": classroom.room_code},
    )
    return classroom


@router.patch("/classrooms/{classroom_id}", response_model=ClassroomResponse)
def update_classroom(
    classroom_id: uuid.UUID,
    data: ClassroomUpdate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_classrooms")),
    db: DBSession = Depends(get_db),
):
    classroom = svc.get_classroom(db, classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    try:
        updated = svc.update_classroom(db, classroom, data)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.classroom.updated", entity_type="classroom",
        entity_id=classroom_id,
        context={"fields": sorted(data.model_dump(exclude_unset=True))},
    )
    return updated


# ── Class Sections ──


@router.get("/classes", response_model=ClassSectionListResponse)
def list_classes(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    course_id: uuid.UUID | None = None,
    period_id: uuid.UUID | None = None,
    program_offering_id: uuid.UUID | None = None,
    current_user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    return svc.list_class_sections(
        db, page=page, page_size=page_size, search=search,
        course_id=course_id, period_id=period_id,
        program_offering_id=program_offering_id,
        visible_class_section_ids=_visible_class_section_ids(current_user, db),
    )


@router.get("/classes/{class_id}", response_model=ClassSectionResponse)
def get_class(
    class_id: uuid.UUID,
    current_user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    cs = svc.get_class_section(db, class_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Class section not found")
    visible = _visible_class_section_ids(current_user, db)
    if visible is not None and class_id not in visible:
        raise HTTPException(status_code=403, detail="No access to this class section")
    return svc._build_class_section_response(db, cs)


@router.post("/classes", response_model=ClassSectionResponse, status_code=201)
def create_class(
    data: ClassSectionCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_classes")),
    db: DBSession = Depends(get_db),
):
    try:
        section = svc.create_class_section(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.class.created", entity_type="class_section",
        entity_id=section.id,
        context={
            "course_id": str(section.course_id),
            "section_code": section.section_code,
        },
    )
    return section


@router.patch("/classes/{class_id}", response_model=ClassSectionResponse)
def update_class(
    class_id: uuid.UUID,
    data: ClassSectionUpdate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_classes")),
    db: DBSession = Depends(get_db),
):
    cs = svc.get_class_section(db, class_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Class section not found")
    try:
        updated = svc.update_class_section(db, cs, data)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.class.updated", entity_type="class_section",
        entity_id=class_id,
        context={"fields": sorted(data.model_dump(exclude_unset=True))},
    )
    return updated


@router.put(
    "/classes/{class_id}/program-offerings",
    response_model=ClassSectionResponse,
)
def set_class_program_offerings(
    class_id: uuid.UUID,
    data: SectionProgramOfferingUpdate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_classes")),
    db: DBSession = Depends(get_db),
):
    """Set all offerings served by one canonical section.

    Replacement is explicit: sending the complete set is how a shared class is
    created, corrected, or unshared. The service refuses any offering from a
    different intake before it touches the join rows.
    """
    section = svc.get_class_section(db, class_id)
    if not section:
        raise HTTPException(status_code=404, detail="Class section not found")
    try:
        updated = svc.set_class_section_program_offerings(db, section, data)
    except ValueError as exc:
        db.rollback()
        raise _academic_rule_error(exc) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.class.offerings_updated", entity_type="class_section",
        entity_id=class_id,
        context={
            "program_offering_ids": [
                str(offering_id) for offering_id in data.program_offering_ids
            ]
        },
    )
    return updated


# ── Teacher Assignments ──


@router.get("/teachers", response_model=TeachableStaffListResponse)
def list_teachers_available(
    search: str | None = None,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    """Staff who can be assigned to a class section.

    Without this the assignment form has no way to resolve a ``staff_id``, so
    the only possible workflow would be pasting a UUID by hand.
    """
    return svc.list_teachable_staff(db, search=search)


@router.get(
    "/classes/{class_id}/teachers",
    response_model=list[TeacherAssignmentResponse],
)
def list_teachers(
    class_id: uuid.UUID,
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    cs = svc.get_class_section(db, class_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Class section not found")
    return svc.list_teacher_assignments(db, class_id)


@router.post(
    "/classes/{class_id}/teachers",
    response_model=TeacherAssignmentResponse,
    status_code=201,
)
def assign_teacher(
    class_id: uuid.UUID,
    data: TeacherAssignmentCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_teachers")),
    db: DBSession = Depends(get_db),
):
    cs = svc.get_class_section(db, class_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Class section not found")
    try:
        assignment = svc.assign_teacher(db, class_id, data)
    except svc.AcademicRuleError as exc:
        db.rollback()
        raise _academic_rule_error(exc) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.teacher.assigned", entity_type="class_section",
        entity_id=class_id, context={"staff_id": str(data.staff_id)},
    )
    return assignment


@router.delete("/classes/{class_id}/teachers/{assignment_id}", status_code=204)
def remove_teacher(
    class_id: uuid.UUID,
    assignment_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_teachers")),
    db: DBSession = Depends(get_db),
):
    try:
        svc.remove_teacher(db, assignment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.teacher.unassigned", entity_type="class_section",
        entity_id=class_id, context={"assignment_id": str(assignment_id)},
    )


# ── Enrollment ──


@router.get(
    "/classes/{class_id}/enrollments",
    response_model=list[EnrollmentResponse],
)
def list_enrollments(
    class_id: uuid.UUID,
    current_user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    cs = svc.get_class_section(db, class_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Class section not found")
    _require_class_records_access(current_user, class_id, db)
    return svc.list_enrollments(db, class_id)


@router.post(
    "/classes/{class_id}/enrollments",
    response_model=EnrollmentResponse,
    status_code=201,
)
def enroll_student(
    class_id: uuid.UUID,
    data: EnrollmentCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_enrollment")),
    db: DBSession = Depends(get_db),
):
    try:
        enrollment = svc.enroll_student(db, class_id, data, actor=current_user)
    except svc.EnrollmentAuthorizationError as exc:
        # The late-enrolment rule is decided by the service, not by this route
        # or the client. A rejected attempt never reaches the audit block below
        # because no enrolment row exists to name.
        db.rollback()
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": str(exc)}},
        ) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None

    record_audit(
        db,
        action="academic.enrollment.created",
        actor=current_user,
        entity_type="enrollment",
        entity_id=enrollment.id,
        context={
            "class_section_id": str(class_id),
            "student_id": str(enrollment.student_id),
            "status": str(enrollment.status),
            "late_authorized": enrollment.authorized_by_id is not None,
            "authorization_reason": enrollment.authorization_reason,
        },
        request=request,
    )
    db.commit()
    return enrollment


@router.post(
    "/classes/{class_id}/enrollments/{enrollment_id}/drop",
    response_model=EnrollmentResponse,
)
def drop_enrollment(
    class_id: uuid.UUID,
    enrollment_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_enrollment")),
    db: DBSession = Depends(get_db),
):
    from app.models.academic import Enrollment

    # A withdrawal is a status transition; without the prior status the audit
    # entry cannot distinguish dropping an active enrolment from a no-op on one
    # that was already withdrawn.
    existing = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    previous_status = existing.status if existing is not None else None

    try:
        enrollment = svc.drop_enrollment(db, enrollment_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None

    record_audit(
        db,
        action="academic.enrollment.dropped",
        actor=current_user,
        entity_type="enrollment",
        entity_id=enrollment.id,
        context={
            "class_section_id": str(class_id),
            "student_id": str(enrollment.student_id),
            "changes": field_changes(
                {"status": previous_status, "dropped_at": None},
                {"status": enrollment.status, "dropped_at": enrollment.dropped_at},
            ),
        },
        request=request,
    )
    db.commit()
    return enrollment


# ── Timetable ──


@router.get("/timetable", response_model=TimetableListResponse)
def list_timetable(
    period_id: uuid.UUID | None = None,
    class_section_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    program_offering_id: uuid.UUID | None = None,
    include_deleted: bool = Query(
        False,
        description="Include soft-deleted slots (management/admin only)",
    ),
    current_user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    if include_deleted and not has_permission(
        current_user, "academic.manage_timetable"
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view deleted timetable entries.",
        )
    entries = svc.list_timetable_entries(
        db,
        period_id=period_id,
        class_section_id=class_section_id,
        course_id=course_id,
        program_offering_id=program_offering_id,
        visible_class_section_ids=_visible_class_section_ids(current_user, db),
        include_deleted=include_deleted,
    )
    return TimetableListResponse(items=entries)


@router.post("/timetable", response_model=TimetableEntryResponse, status_code=201)
def create_timetable_entry(
    data: TimetableEntryCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_timetable")),
    db: DBSession = Depends(get_db),
):
    try:
        entry = svc.create_timetable_entry(db, data)
    except ValueError as e:
        db.rollback()
        raise _academic_rule_error(e) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.timetable.created", entity_type="timetable_entry",
        entity_id=entry.id,
        context={"class_section_id": str(entry.class_section_id)},
    )
    return entry


@router.patch("/timetable/{entry_id}", response_model=TimetableEntryResponse)
def update_timetable_entry(
    entry_id: uuid.UUID,
    data: TimetableEntryUpdate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_timetable")),
    db: DBSession = Depends(get_db),
):
    from app.models.academic import TimetableEntry
    entry = (
        db.query(TimetableEntry)
        .filter(
            TimetableEntry.id == entry_id,
            TimetableEntry.is_deleted.is_(False),
        )
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Timetable entry not found")
    try:
        updated = svc.update_timetable_entry(
            db, entry, data, actor_id=current_user.id
        )
    except ValueError as e:
        db.rollback()
        raise _academic_rule_error(e) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.timetable.updated", entity_type="timetable_entry",
        entity_id=entry_id,
        context={"fields": sorted(data.model_dump(exclude_unset=True))},
    )
    return updated


@router.delete("/timetable/{entry_id}", status_code=204)
def delete_timetable_entry(
    entry_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_timetable")),
    db: DBSession = Depends(get_db),
):
    try:
        svc.delete_timetable_entry(db, entry_id, deleted_by_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.timetable.deleted", entity_type="timetable_entry",
        entity_id=entry_id,
    )


# ── Program offerings ──


@router.get("/program-offerings", response_model=ProgramOfferingListResponse)
def list_program_offerings(
    period_id: uuid.UUID | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    _user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    return svc.list_program_offerings(
        db,
        period_id=period_id,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.post("/program-offerings", response_model=ProgramOfferingResponse, status_code=201)
def create_program_offering(
    data: ProgramOfferingCreate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_programs")),
    db: DBSession = Depends(get_db),
):
    try:
        offering = svc.create_program_offering(db, data)
    except ValueError as exc:
        db.rollback()
        raise _academic_rule_error(exc) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.program_offering.created",
        entity_type="program_offering",
        entity_id=offering.id,
        context={
            "academic_period_id": str(offering.academic_period_id),
            "source_id": offering.source_id,
        },
    )
    return offering


@router.patch("/program-offerings/{offering_id}", response_model=ProgramOfferingResponse)
def update_program_offering(
    offering_id: uuid.UUID,
    data: ProgramOfferingUpdate,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_programs")),
    db: DBSession = Depends(get_db),
):
    offering = svc.get_program_offering(db, offering_id)
    if not offering:
        raise HTTPException(status_code=404, detail="Program offering not found")
    try:
        updated = svc.update_program_offering(db, offering, data)
    except ValueError as exc:
        db.rollback()
        raise _academic_rule_error(exc) from None
    _audit_mutation(
        db, request, current_user,
        action="academic.program_offering.updated",
        entity_type="program_offering",
        entity_id=offering_id,
        context={"fields": sorted(data.model_dump(exclude_unset=True))},
    )
    return updated


# ── Student Academic ──


@router.get("/students/{student_id}")
def get_student_academic(
    student_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db),
):
    _check_student_scope(current_user, student_id, db)

    result = svc.get_student_academic_overview(db, student_id, period_id=period_id)
    if not result:
        raise HTTPException(status_code=404, detail="Student not found")
    return result


@router.get("/students/{student_id}/timetable")
def get_student_timetable(
    student_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db),
):
    _check_student_scope(current_user, student_id, db)

    entries = svc.get_student_timetable(db, student_id, period_id=period_id)
    return TimetableListResponse(items=entries)


# ── Attendance ──


@router.post(
    "/classes/{class_id}/attendance",
    response_model=list[AttendanceRecordResponse],
    status_code=201,
)
def record_attendance(
    class_id: uuid.UUID,
    data: AttendanceBulkCreate,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db),
):
    role_names = {r.name for r in current_user.roles}
    # Only ADMIN, MANAGEMENT, or TEACHER can record attendance
    if not ({"ADMIN", "MANAGEMENT"} & role_names):
        if "TEACHER" in role_names:
            if not svc.can_access_class_section(db, current_user, class_id):
                raise HTTPException(status_code=403, detail="Not assigned to this class section")
        else:
            raise HTTPException(status_code=403, detail="Not authorized to record attendance")

    data.class_section_id = class_id
    try:
        # The service owns the transaction and writes one audit entry per
        # record. A single class-section entry carrying only a count could not
        # say which student's status changed, from what, to what.
        return svc.bulk_record_attendance(db, data, current_user, request=request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/classes/{class_id}/attendance", response_model=list[AttendanceRecordResponse])
def list_attendance(
    class_id: uuid.UUID,
    session_date: str | None = None,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db),
):
    from datetime import date as date_type

    _require_class_records_access(current_user, class_id, db)

    parsed_date = None
    if session_date:
        try:
            parsed_date = date_type.fromisoformat(session_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format") from None

    return svc.list_attendance(db, class_id, session_date=parsed_date)


@router.get("/students/{student_id}/attendance", response_model=list[AttendanceRecordResponse])
def get_student_attendance(
    student_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db),
):
    _check_student_scope(current_user, student_id, db)
    return svc.get_student_attendance(db, student_id)


# ── Assessments ──


@router.get("/classes/{class_id}/assessments", response_model=list[AssessmentResponse])
def list_assessments(
    class_id: uuid.UUID,
    current_user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    """List one class section's assessments.

    `academic.view` alone is a feature permission, not a scope: every student
    holds it for their own record, so it must not enumerate another class's
    assessments. The class-scope guard is the same one the roster, attendance
    and grade reads already use, which keeps Admin and Management unrestricted
    and limits a Teacher to sections they are assigned to.
    """
    cs = svc.get_class_section(db, class_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Class section not found")
    _require_class_records_access(current_user, class_id, db)
    return svc.list_assessments(db, class_id)


@router.post("/classes/{class_id}/assessments", response_model=AssessmentResponse, status_code=201)
def create_assessment(
    class_id: uuid.UUID,
    data: AssessmentCreate,
    _user: User = Depends(require_permission("academic.manage_classes")),
    db: DBSession = Depends(get_db),
):
    data.class_section_id = class_id
    try:
        return svc.create_assessment(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.patch("/classes/{class_id}/assessments/{assessment_id}", response_model=AssessmentResponse)
def update_assessment(
    class_id: uuid.UUID,
    assessment_id: uuid.UUID,
    data: AssessmentUpdate,
    _user: User = Depends(require_permission("academic.manage_classes")),
    db: DBSession = Depends(get_db),
):
    from app.models.academic import Assessment
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment or assessment.class_section_id != class_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    try:
        return svc.update_assessment(db, assessment, data, actor_id=_user.id)
    except ValueError as exc:
        db.rollback()
        raise _academic_rule_error(exc) from None


@router.get(
    "/classes/{class_id}/record-history",
    response_model=list[AcademicChangeHistoryResponse],
)
def get_class_record_history(
    class_id: uuid.UUID,
    entity_type: str | None = Query(None, description="ASSESSMENT or GRADE"),
    _user: User = Depends(require_permission("academic.manage_classes")),
    db: DBSession = Depends(get_db),
):
    """Previous/new values for academic records in this class."""
    cs = svc.get_class_section(db, class_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Class section not found")
    return svc.list_class_record_history(db, class_id, entity_type)


# ── Grades ──


@router.get("/classes/{class_id}/grades", response_model=list[GradeResponse])
def list_grades_for_class(
    class_id: uuid.UUID,
    current_user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    cs = svc.get_class_section(db, class_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Class section not found")
    _require_class_records_access(current_user, class_id, db)
    return svc.list_grades_for_class(db, class_id)


@router.post("/classes/{class_id}/grades", response_model=GradeResponse, status_code=201)
def record_grade(
    class_id: uuid.UUID,
    data: GradeCreate,
    request: Request,
    current_user: User = Depends(require_permission("grades.edit")),
    db: DBSession = Depends(get_db),
):
    if not svc.get_class_section(db, class_id):
        raise HTTPException(status_code=404, detail="Class section not found")
    _require_class_records_access(current_user, class_id, db)
    try:
        grade = svc.record_grade(db, class_id, data, current_user.id)
    except svc.AcademicRuleError as exc:
        db.rollback()
        raise _academic_rule_error(exc) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None

    record_audit(
        db,
        action="academic.grade.updated",
        actor=current_user,
        entity_type="grade",
        entity_id=grade.id,
        context={
            "assessment_id": str(data.assessment_id),
            "student_id": str(data.student_id),
            "class_section_id": str(class_id),
            # The values recorded on first entry. A later correction carries its
            # own previous/new pair (see `update_grade`).
            "changes": field_changes(
                {},
                {
                    "score": grade.score,
                    "letter_grade": grade.letter_grade,
                    "note": grade.note,
                },
            ),
        },
        request=request,
    )
    db.commit()
    return grade


@router.patch(
    "/classes/{class_id}/grades/{grade_id}",
    response_model=GradeResponse,
)
def update_grade(
    class_id: uuid.UUID,
    grade_id: uuid.UUID,
    data: GradeUpdate,
    request: Request,
    current_user: User = Depends(require_permission("grades.edit")),
    db: DBSession = Depends(get_db),
):
    from app.models.academic import Assessment, Grade

    if not svc.get_class_section(db, class_id):
        raise HTTPException(status_code=404, detail="Class section not found")
    _require_class_records_access(current_user, class_id, db)
    grade = db.query(Grade).filter(Grade.id == grade_id).first()
    if not grade:
        raise HTTPException(status_code=404, detail="Grade not found")
    assessment = (
        db.query(Assessment).filter(Assessment.id == grade.assessment_id).first()
    )
    if assessment is None or assessment.class_section_id != class_id:
        raise HTTPException(status_code=404, detail="Grade not found")

    # `update_grade` overwrites in place, so the previous values are captured
    # here before the service runs. `AcademicChangeHistory` remains the
    # authoritative record of the grade's full before/after state; this entry
    # carries the same previous/new pair so the audit trail is readable on its
    # own, without a join.
    previous = {
        "score": grade.score,
        "letter_grade": grade.letter_grade,
        "note": grade.note,
    }

    try:
        updated = svc.update_grade(
            db, class_id, grade, data, actor_id=current_user.id
        )
    except svc.AcademicRuleError as exc:
        db.rollback()
        raise _academic_rule_error(exc) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None

    record_audit(
        db,
        action="academic.grade.updated",
        actor=current_user,
        entity_type="grade",
        entity_id=updated.id,
        context={
            "assessment_id": str(updated.assessment_id),
            "student_id": str(updated.student_id),
            "class_section_id": str(class_id),
            "changes": field_changes(
                previous,
                {
                    "score": updated.score,
                    "letter_grade": updated.letter_grade,
                    "note": updated.note,
                },
            ),
        },
        request=request,
    )
    db.commit()
    return updated


@router.get("/students/{student_id}/grades", response_model=list[GradeResponse])
def get_student_grades(
    student_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db),
):
    _check_student_scope(current_user, student_id, db)
    return svc.list_grades_for_student(db, student_id)


# ── Intakes and timetable reconciliation ──


@router.post("/intakes/plan")
def plan_intakes(
    data: IntakePlanRequest,
    request: Request,
    current_user: User = Depends(require_permission("academic.manage_periods")),
    db: DBSession = Depends(get_db),
):
    """Create missing intakes, idempotently.

    Re-running the same plan changes nothing. A plan that disagrees with an
    existing intake's dates is reported as a CONFLICT and left untouched: an
    intake that already has students must not have its dates rewritten by a
    spreadsheet.
    """
    specs = [
        intake_svc.IntakeSpec(
            code=item.code.strip(),
            name=item.name.strip(),
            start_date=item.start_date,
            end_date=item.end_date,
            status=item.status.strip().upper(),
            offerings=tuple(
                intake_svc.IntakeOfferingSpec(
                    source_id=offering.source_id.strip(),
                    name=offering.name.strip(),
                    program_code=(
                        offering.program_code.strip() if offering.program_code else None
                    ),
                )
                for offering in item.offerings
            ),
        )
        for item in data.intakes
    ]
    try:
        report = intake_svc.plan_intakes(
            db, specs, actor_id=current_user.id, request=request
        )
    except intake_svc.IntakePlanError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": exc.code, "message": exc.message}},
        ) from exc
    return report


@router.get("/intakes/summary")
def intake_summary(
    current_user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    """Per-intake counts: offerings, sections, students placed."""
    return {"items": intake_svc.intake_summary(db)}


@router.get("/timetable/reconciliation")
def timetable_reconciliation(
    period_id: uuid.UUID | None = None,
    current_user: User = Depends(require_permission("academic.manage_timetable")),
    db: DBSession = Depends(get_db),
):
    """Report where the existing timetable disagrees with the academic model.

    Read-only. Repair happens through the normal audited timetable endpoints,
    one row at a time, after a person has read this report.
    """
    if period_id is not None:
        period = svc.resolve_period(db, period_id)
        if period is None:
            raise HTTPException(status_code=404, detail="Academic period not found")
    return reconciliation_svc.reconcile_timetable(db, period_id=period_id)


# ── Shared institutional timetable ──
#
# Deliberately separate from ``/timetable`` (the administrative list) and from
# ``/students/{id}/timetable`` (one student's personal schedule). This endpoint
# filters by the selected period and offering only; enrollment is never
# consulted, so a student browsing it sees the whole cohort schedule.


@router.get(
    "/institutional-timetable",
    response_model=InstitutionalTimetableResponse,
)
def institutional_timetable(
    program_offering_id: uuid.UUID,
    period_id: uuid.UUID | None = None,
    current_user: User = Depends(require_permission("academic.view")),
    db: DBSession = Depends(get_db),
):
    """One offering's complete weekly schedule, for any authenticated viewer.

    Every role that may read academic data may read this: it is the published
    institutional schedule, not a personal or administrative record. The only
    role-dependent part is the issue breakdown, which stays with staff who can
    act on it.
    """
    try:
        return svc.institutional_timetable(
            db,
            period_id=period_id,
            program_offering_id=program_offering_id,
            include_diagnostics=has_permission(
                current_user, "academic.manage_timetable"
            ),
        )
    except svc.AcademicRuleError as exc:
        raise _academic_rule_error(exc) from None


# ── Source-catalogue import ──
#
# The existing staged importer, exposed as preview → apply → rollback. Nothing
# here maps catalogue objects to academic rows: ``academic_import`` does that,
# and a second pathway would be a second source of truth. Authorization is
# `academic.manage_periods`, which Admin and Management hold and teachers and
# students do not.


_IMPORT_PERMISSION = "academic.manage_periods"


@router.get("/imports", response_model=list[AcademicImportBatchReport])
def list_academic_imports(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permission(_IMPORT_PERMISSION)),
    db: DBSession = Depends(get_db),
):
    return [
        AcademicImportBatchReport(**import_svc.batch_report(db, batch.id))
        for batch in import_svc.list_batches(db, limit=limit)
    ]


@router.post("/imports/preview", response_model=AcademicImportBatchReport)
def preview_academic_import(
    request: Request,
    current_user: User = Depends(require_permission(_IMPORT_PERMISSION)),
    db: DBSession = Depends(get_db),
):
    """Stage the source catalogue and return the dry-run report.

    Staging writes only import-batch rows; no period, offering, course, section
    or session is created. Applying is a separate, confirmed request.
    """
    try:
        staged = import_svc.preview_import(db, actor_id=current_user.id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "IMPORT_SOURCE_UNAVAILABLE",
                    "message": "The source catalogue file is not available",
                }
            },
        ) from None
    except (ValueError, KeyError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "IMPORT_SOURCE_INVALID", "message": str(exc)}},
        ) from None

    batch_id = uuid.UUID(str(staged["batch_id"]))
    if not staged.get("already_applied"):
        record_audit(
            db,
            action="academic.import.previewed",
            actor=current_user,
            entity_type="academic_import_batch",
            entity_id=batch_id,
            context={
                "source_sha256": staged.get("source_sha256"),
                "counts": {k: v for k, v in staged.items() if k.endswith("s")},
            },
            request=request,
        )
        db.commit()
    return AcademicImportBatchReport(**import_svc.batch_report(db, batch_id))


@router.get(
    "/imports/{batch_id}",
    response_model=AcademicImportBatchReport,
)
def get_academic_import(
    batch_id: uuid.UUID,
    current_user: User = Depends(require_permission(_IMPORT_PERMISSION)),
    db: DBSession = Depends(get_db),
):
    try:
        return AcademicImportBatchReport(**import_svc.batch_report(db, batch_id))
    except ImportError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "IMPORT_BATCH_NOT_FOUND", "message": str(exc)}},
        ) from None


@router.post(
    "/imports/{batch_id}/apply",
    response_model=AcademicImportBatchReport,
)
def apply_academic_import(
    batch_id: uuid.UUID,
    data: AcademicImportApplyRequest,
    request: Request,
    current_user: User = Depends(require_permission(_IMPORT_PERMISSION)),
    db: DBSession = Depends(get_db),
):
    """Apply a staged batch, but only after an explicit confirmation.

    ``confirm`` is not ceremony: the request must name it, so an accidental
    retry or an unfinished form cannot write academic rows. The period mapping
    is validated here because a stale id must fail before the importer starts
    rather than half-way through.
    """
    if not data.confirm:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "IMPORT_CONFIRMATION_REQUIRED",
                    "message": "Set confirm=true after reviewing the dry run",
                }
            },
        )

    for source_id, period_id in data.period_map.items():
        exists = (
            db.query(AcademicPeriod)
            .filter(AcademicPeriod.id == period_id)
            .first()
        )
        if exists is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": {
                        "code": "IMPORT_PERIOD_NOT_FOUND",
                        "message": f"Mapped period for {source_id} does not exist",
                    }
                },
            )

    try:
        result = import_svc.apply_import(
            db,
            batch_id,
            period_map={key: str(value) for key, value in data.period_map.items()},
            parent_program_map={
                key: str(value) for key, value in data.parent_program_map.items()
            },
        )
    except ImportError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "IMPORT_CONFLICT", "message": str(exc)}},
        ) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "IMPORT_CONFLICT", "message": str(exc)}},
        ) from None

    record_audit(
        db,
        action="academic.import.applied",
        actor=current_user,
        entity_type="academic_import_batch",
        entity_id=batch_id,
        context={
            "status": result.get("status"),
            "period_map": {k: str(v) for k, v in data.period_map.items()},
            "counts": {k: v for k, v in result.items() if k.endswith("s")},
        },
        request=request,
    )
    db.commit()
    return AcademicImportBatchReport(**import_svc.batch_report(db, batch_id))


@router.post(
    "/imports/{batch_id}/rollback",
    response_model=AcademicImportBatchReport,
)
def rollback_academic_import(
    batch_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission(_IMPORT_PERMISSION)),
    db: DBSession = Depends(get_db),
):
    """Remove only the rows this batch created and restore mapped period data."""
    try:
        result = import_svc.rollback_batch(db, batch_id)
    except ImportError as exc:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "IMPORT_BATCH_NOT_FOUND", "message": str(exc)}},
        ) from None

    record_audit(
        db,
        action="academic.import.rolled_back",
        actor=current_user,
        entity_type="academic_import_batch",
        entity_id=batch_id,
        context={k: v for k, v in result.items() if k.endswith("s") or k == "status"},
        request=request,
    )
    db.commit()
    return AcademicImportBatchReport(**import_svc.batch_report(db, batch_id))
