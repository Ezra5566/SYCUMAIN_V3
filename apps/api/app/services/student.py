"""Student business logic service."""

import math
import uuid
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import aliased, object_session

from app.audit import record_audit
from app.config.settings import get_settings
from app.models.academic import (
    AcademicPeriodStatus,
    EntityStatus,
    Major,
    Program,
    ProgramOffering,
)
from app.models.admission import (
    AcademicAdmission,
    AcademicPlacement,
    AdmissionVerificationStatus,
)
from app.models.identity import Student, StudentStatus, User
from app.models.immigration import ImmigrationProfile
from app.schemas.admission import AdmissionCreate, PlacementCreate
from app.schemas.student import (
    PaginationMeta,
    StudentBrief,
    StudentCreate,
    StudentDetail,
    StudentListResponse,
    StudentOnboard,
    StudentPlacementStatus,
    StudentSelfUpdate,
    StudentUpdate,
)
from app.services.account import create_account
from app.services.admission import create_admission
from app.services.placement import create_placement
from app.services.student_academic import (
    LIVE_ADMISSION_STATUSES,
    latest_effective_admission_subquery,
    student_academic_snapshot,
)

# Expiry windows used to bucket immigration status. Mirrors the thresholds in
# app.services.immigration so the directory filter and the immigration module
# can never disagree about what "urgent" means.
URGENT_DAYS = 30
EXPIRING_DAYS = 90

# Sort keys the directory accepts. Bounded on purpose: an open-ended sort
# parameter would let a caller order by unindexed or sensitive columns.
SORT_OPTIONS = {
    "name": (Student.last_name.asc(), Student.first_name.asc()),
    "-name": (Student.last_name.desc(), Student.first_name.desc()),
    "student_number": (Student.student_id.asc(),),
    "-student_number": (Student.student_id.desc(),),
    "newest": (Student.created_at.desc(),),
    "oldest": (Student.created_at.asc(),),
}


def _worst_expiry_case():
    """SQL expression for the earliest of a profile's three expiry dates."""
    return func.least(
        ImmigrationProfile.passport_expiry_date,
        ImmigrationProfile.visa_expiry_date,
        ImmigrationProfile.residence_permit_expiry_date,
    )


def _apply_immigration_filter(query, immigration_status: str):
    """Filter students by their worst (soonest) immigration expiry.

    The comparison is pushed into SQL rather than resolved in Python so that
    pagination counts stay correct and the database does the work.
    """
    wanted = immigration_status.strip().upper()
    today = date.today()
    worst = _worst_expiry_case()

    if wanted == "NOT_PROVIDED":
        return query.outerjoin(
            ImmigrationProfile, ImmigrationProfile.student_id == Student.id
        ).filter(or_(ImmigrationProfile.id.is_(None), worst.is_(None)))

    query = query.join(
        ImmigrationProfile, ImmigrationProfile.student_id == Student.id
    ).filter(worst.is_not(None))

    if wanted == "EXPIRED":
        return query.filter(worst < today)
    if wanted == "URGENT":
        return query.filter(
            worst >= today, worst <= today + timedelta(days=URGENT_DAYS)
        )
    if wanted == "EXPIRING_SOON":
        return query.filter(
            worst > today + timedelta(days=URGENT_DAYS),
            worst <= today + timedelta(days=EXPIRING_DAYS),
        )
    if wanted == "VALID":
        return query.filter(worst > today + timedelta(days=EXPIRING_DAYS))
    return query


def list_students(
    db: DBSession,
    *,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    status: StudentStatus | None = None,
    student_ids: Iterable[uuid.UUID] | None = None,
    major_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    has_housing: bool | None = None,
    immigration_status: str | None = None,
    original_intake_id: uuid.UUID | None = None,
    current_intake_id: uuid.UUID | None = None,
    sort: str | None = None,
) -> StudentListResponse:
    """List students with pagination, search, and filtering.

    `student_ids` narrows the result set to an explicit scope. It is how
    teacher scoping is applied: pass the IDs derived from the teacher's
    assignments and no other students are reachable. Passing an empty
    iterable yields an empty page rather than the full directory.
    """
    query = db.query(Student)

    if student_ids is not None:
        ids = list(student_ids)
        if not ids:
            return StudentListResponse(
                items=[],
                meta=PaginationMeta(
                    page=page, page_size=page_size, total=0, total_pages=1
                ),
            )
        query = query.filter(Student.id.in_(ids))

    # Filter by status
    if status:
        query = query.filter(Student.status == status)

    # The two intake concepts are deliberately separate filters.
    #
    # * Original admission intake is the intake of the student's original
    #   admission pointer. Only a VERIFIED admission may be presented as a
    #   verified cohort; unverified, disputed and revoked rows are excluded
    #   rather than silently treated as trusted.
    # * Current placement intake is the intake of the one open placement
    #   owned by the effective live admission. A student with no current
    #   placement (or only a terminal episode) is absent from this filter, not
    #   assigned a guessed intake.
    if original_intake_id is not None:
        original_admission = aliased(AcademicAdmission)
        query = query.join(
            original_admission,
            Student.original_admission_id == original_admission.id,
        ).filter(
            original_admission.verification_status
            == AdmissionVerificationStatus.VERIFIED.value,
            original_admission.admission_intake_id == original_intake_id,
        )

    if current_intake_id is not None:
        current_placement = aliased(AcademicPlacement)
        placement_admission = aliased(AcademicAdmission)
        query = (
            query.join(
                current_placement,
                and_(
                    current_placement.student_id == Student.id,
                    current_placement.ended_at.is_(None),
                ),
            )
            .join(
                placement_admission,
                current_placement.admission_id == placement_admission.id,
            )
            .filter(
                current_placement.academic_period_id == current_intake_id,
                placement_admission.status.in_(LIVE_ADMISSION_STATUSES),
            )
        )

    if major_id is not None or program_id is not None:
        effective = latest_effective_admission_subquery(db)
        query = query.join(effective, effective.c.student_id == Student.id)
        if program_id is not None:
            query = query.filter(effective.c.program_id == program_id)
        if major_id is not None:
            query = query.join(Program, Program.id == effective.c.program_id).filter(
                Program.major_id == major_id
            )

    if has_housing is not None:
        # Imported lazily: housing models reference students, so a module-level
        # import here would create an import cycle.
        from app.models.housing import HousingAssignment, HousingAssignmentStatus

        # `HousingAssignment.student_id` references `users.id`, not
        # `students.id`. Joining the two on the same column name compared user
        # ids against student ids, which never matched, so every student read
        # as unhoused. The join therefore goes through the student's account.
        #
        # A row also only describes *current* housing while it is both ACTIVE
        # and inside its own date window: a future-dated assignment has not
        # started, and one whose end date has passed is history. Relying on the
        # status column alone would report a stale ACTIVE row as live housing.
        housed_user_ids = (
            db.query(HousingAssignment.student_id)
            .filter(
                HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
                HousingAssignment.start_date <= func.now(),
                or_(
                    HousingAssignment.end_date.is_(None),
                    HousingAssignment.end_date > func.now(),
                ),
            )
            .subquery()
        )
        housed = db.query(housed_user_ids.c.student_id)
        if has_housing:
            query = query.filter(Student.user_id.in_(housed))
        else:
            # A student without a user account cannot be housed, so the
            # negation must not let SQL's NULL handling drop them.
            query = query.filter(
                or_(Student.user_id.is_(None), Student.user_id.notin_(housed))
            )

    if immigration_status:
        query = _apply_immigration_filter(query, immigration_status)

    # Search by name, student_id, or email
    if search:
        search_pattern = f"%{search}%"
        query = query.join(Student.user, isouter=True).filter(
            (Student.first_name.ilike(search_pattern))
            | (Student.last_name.ilike(search_pattern))
            | (Student.preferred_name.ilike(search_pattern))
            | (Student.student_id.ilike(search_pattern))
            | (User.email.ilike(search_pattern))
        )

    # Get total count
    total = query.distinct().count()

    # Apply pagination
    total_pages = max(1, math.ceil(total / page_size))
    offset = (page - 1) * page_size
    order_by = SORT_OPTIONS.get(sort or "name", SORT_OPTIONS["name"])
    students = (
        query.distinct().order_by(*order_by).offset(offset).limit(page_size).all()
    )

    # Build response with user email
    items = []
    for s in students:
        item = StudentBrief(
            id=s.id,
            user_id=s.user_id,
            student_id=s.student_id,
            first_name=s.first_name,
            last_name=s.last_name,
            preferred_name=s.preferred_name,
            nationality=s.nationality,
            status=s.status,
            user_email=s.user.email if s.user else None,
            created_at=s.created_at,
        )
        items.append(item)

    return StudentListResponse(
        items=items,
        meta=PaginationMeta(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        ),
    )


def get_student(db: DBSession, student_id: uuid.UUID) -> Student | None:
    """Get a student by ID."""
    return db.query(Student).filter(Student.id == student_id).first()


def get_student_by_student_id(db: DBSession, student_id: str) -> Student | None:
    """Get a student by their student_id (e.g., STU-001)."""
    return db.query(Student).filter(Student.student_id == student_id).first()


def get_student_by_user_id(db: DBSession, user_id: uuid.UUID) -> Student | None:
    """Get a student by their user_id."""
    return db.query(Student).filter(Student.user_id == user_id).first()


def create_student(db: DBSession, data: StudentCreate) -> Student:
    """Create a new student record."""
    # Check for duplicate student_id
    existing = get_student_by_student_id(db, data.student_id)
    if existing:
        raise ValueError(f"Student with ID {data.student_id} already exists")

    # Check that user_id is not already linked to a student
    existing_user = db.query(Student).filter(Student.user_id == data.user_id).first()
    if existing_user:
        raise ValueError("This user is already linked to a student record")

    # Verify user exists
    user = db.query(User).filter(User.id == data.user_id).first()
    if not user:
        raise ValueError("User not found")

    student = Student(
        user_id=data.user_id,
        student_id=data.student_id,
        first_name=data.first_name,
        last_name=data.last_name,
        preferred_name=data.preferred_name,
        date_of_birth=data.date_of_birth,
        gender=data.gender,
        nationality=data.nationality,
        phone=data.phone,
        emergency_contact_name=data.emergency_contact_name,
        emergency_contact_phone=data.emergency_contact_phone,
        status=StudentStatus.ACTIVE,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def update_student(db: DBSession, student: Student, data: StudentUpdate) -> Student:
    """Update a student record (admin/management only).

    Academic placement is not part of this service. The student number stays
    explicitly validated because correcting a typo must not create a duplicate
    identifier.

    Raises:
        ValueError: with a machine-readable code for the router to map.
    """
    update_data = data.model_dump(exclude_unset=True)

    new_number = update_data.get("student_id")
    if new_number is not None and new_number != student.student_id:
        clash = (
            db.query(Student.id)
            .filter(Student.student_id == new_number, Student.id != student.id)
            .first()
        )
        if clash is not None:
            raise ValueError("student_number_taken")

    for field, value in update_data.items():
        setattr(student, field, value)
    db.commit()
    db.refresh(student)
    return student

def _resolve_offering_placement(
    db: DBSession, offering_id: uuid.UUID
) -> tuple[ProgramOffering, Program, Major]:
    """Resolve a selectable offering to its canonical program and major.

    A source-only offering has no reviewed canonical program, and a closed
    intake is not a valid placement. Both are refused here rather than being
    stored as an unverifiable academic assignment.
    """
    offering = (
        db.query(ProgramOffering)
        .filter(ProgramOffering.id == offering_id)
        .first()
    )
    if offering is None:
        raise ValueError("program_offering_not_found")
    if offering.academic_period is not None and offering.academic_period.status in {
        AcademicPeriodStatus.CANCELLED,
        AcademicPeriodStatus.COMPLETED,
    }:
        raise ValueError("program_offering_unavailable")
    if offering.program_id is None or offering.program is None:
        raise ValueError("program_offering_not_mapped")
    program = offering.program
    if program.status != EntityStatus.ACTIVE:
        raise ValueError("program_offering_unavailable")
    major = program.major
    if major is None or major.status != EntityStatus.ACTIVE:
        raise ValueError("program_offering_unavailable")
    return offering, program, major

def update_student_self(
    db: DBSession, student: Student, data: StudentSelfUpdate
) -> Student:
    """Update the fields a student is allowed to maintain themselves.

    The allowlisted schema *is* the authorization boundary here: administrative
    fields (student number, status, programme, official name) are absent from
    ``StudentSelfUpdate`` and therefore cannot be mass-assigned even if a
    client submits them.
    """
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(student, field, value)
    db.commit()
    db.refresh(student)
    return student


def archive_student(db: DBSession, student: Student) -> Student:
    """Archive a student (set status to INACTIVE)."""
    student.status = StudentStatus.INACTIVE
    db.commit()
    db.refresh(student)
    return student


def student_to_detail(student: Student) -> StudentDetail:
    """Convert a Student model to a StudentDetail schema.

    Academic placement is resolved from the effective admission and current
    placement. The read-only fields remain on the response for compatibility,
    but no Student projection columns back them.
    """
    db = object_session(student)
    academic = student_academic_snapshot(db, student.id) if db is not None else None
    return StudentDetail(
        id=student.id,
        user_id=student.user_id,
        student_id=student.student_id,
        first_name=student.first_name,
        last_name=student.last_name,
        preferred_name=student.preferred_name,
        date_of_birth=student.date_of_birth,
        gender=student.gender,
        nationality=student.nationality,
        has_photo=bool(student.profile_photo_object_key),
        photo_updated_at=student.profile_photo_updated_at,
        phone=student.phone,
        emergency_contact_name=student.emergency_contact_name,
        emergency_contact_phone=student.emergency_contact_phone,
        status=student.status,
        major_id=academic.major_id if academic else None,
        major_name=academic.major.name if academic and academic.major else None,
        program_id=academic.program_id if academic else None,
        program_name=academic.program.name if academic and academic.program else None,
        program_offering_id=academic.offering_id if academic else None,
        program_offering_name=(
            academic.offering.name if academic and academic.offering else None
        ),
        program_offering_period_id=academic.period_id if academic else None,
        program_offering_period_name=(
            academic.offering.academic_period.name
            if academic
            and academic.offering
            and academic.offering.academic_period
            else None
        ),
        created_at=student.created_at,
        updated_at=student.updated_at,
        user_email=student.user.email if student.user else None,
        user_username=student.user.username if student.user else None,
        user_is_active=student.user.is_active if student.user else None,
    )


def student_to_placement(student: Student) -> StudentPlacementStatus:
    """Build the placement-status response for the academic onboarding step."""
    db = object_session(student)
    academic = student_academic_snapshot(db, student.id) if db is not None else None
    return StudentPlacementStatus(
        can_select=False,
        major_id=academic.major_id if academic else None,
        major_name=academic.major.name if academic and academic.major else None,
        program_id=academic.program_id if academic else None,
        program_name=academic.program.name if academic and academic.program else None,
        program_offering_id=academic.offering_id if academic else None,
        program_offering_name=(
            academic.offering.name if academic and academic.offering else None
        ),
        program_offering_period_id=academic.period_id if academic else None,
        program_offering_period_name=(
            academic.offering.academic_period.name
            if academic
            and academic.offering
            and academic.offering.academic_period
            else None
        ),
    )


def onboard_student(
    db: DBSession,
    data: StudentOnboard,
    *,
    actor: User | None = None,
    request: Any | None = None,
) -> tuple[Student, str, AcademicAdmission | None]:
    """Create a student record together with its login account.

    The account and the student row are written in a single transaction: if
    anything fails, neither exists. That matters operationally — a student who
    exists without an account cannot sign in, and an account without a student
    is an unexplained privileged login.

    With an offering selected, the first admission episode, its first
    placement and both audit entries are written in the same transaction.
    Major/program-only registration is refused: without an intake offering
    there is no admission or placement to record. A lifecycle refusal or audit
    failure rolls the whole registration back.

    Returns the student, the one-time temporary password, and the episode when
    one was recorded.
    """
    if get_student_by_student_id(db, data.student_id):
        raise ValueError(f"Student with ID {data.student_id} already exists")

    admission_settings = get_settings()
    offering_id = data.program_offering_id
    if data.major_id is not None or data.program_id is not None:
        # These retired fields have no intake to attach history to. Refuse
        # them rather than silently dropping a caller's selection.
        raise ValueError("placement_direct_write_retired")
    if offering_id is not None:
        offering, _program, _major = _resolve_offering_placement(db, offering_id)

    if offering_id is not None and not admission_settings.ADMISSIONS_WRITE_ENABLED:
        raise ValueError("ADMISSIONS_WRITE_DISABLED")

    if (
        admission_settings.ADMISSIONS_WRITE_ENABLED
        and offering_id is None
        and (
            data.admission_intake_id is not None
            or data.initial_admission_status is not None
        )
    ):
        raise ValueError("ADMISSION_OFFERING_REQUIRED")

    # A first admission is an admission of record, never a prepared future
    # episode. PENDING is reserved for a later episode created while another
    # admission is active, so an omitted or PENDING status is refused here.
    if (
        admission_settings.ADMISSIONS_WRITE_ENABLED
        and offering_id is not None
        and data.initial_admission_status not in ("ADMITTED", "ACTIVE")
    ):
        raise ValueError("VALIDATION_ERROR")

    full_name = f"{data.first_name} {data.last_name}".strip()
    user, temporary_password = create_account(
        db,
        email=data.email,
        full_name=full_name,
        roles=["STUDENT"],
        must_change_password=True,
    )
    # create_account generates a password whenever none is supplied.
    assert temporary_password is not None  # noqa: S101

    student = Student(
        user_id=user.id,
        student_id=data.student_id,
        first_name=data.first_name,
        last_name=data.last_name,
        preferred_name=data.preferred_name,
        date_of_birth=data.date_of_birth,
        gender=data.gender,
        nationality=data.nationality,
        phone=data.phone,
        emergency_contact_name=data.emergency_contact_name,
        emergency_contact_phone=data.emergency_contact_phone,
        status=StudentStatus.ACTIVE,
    )
    db.add(student)
    db.flush()

    episode: AcademicAdmission | None = None
    placement = None
    if admission_settings.ADMISSIONS_WRITE_ENABLED and offering_id is not None:
        if actor is None:
            db.rollback()
            raise ValueError("ADMISSION_ACTOR_REQUIRED")
        intake_id = data.admission_intake_id or offering.academic_period_id
        try:
            episode = create_admission(
                db,
                student,
                AdmissionCreate(
                    admission_intake_id=intake_id,
                    program_offering_id=offering_id,
                    initial_status=data.initial_admission_status,
                ),
                actor,
            )
        except ValueError:
            # Registration is one unit: no account or student survives a
            # refused admission.
            db.rollback()
            raise

        try:
            placement, _previous = create_placement(
                db,
                student,
                PlacementCreate(
                    admission_id=episode.id,
                    program_offering_id=offering_id,
                ),
                actor,
                can_authorize_earlier=False,
            )
        except ValueError:
            # The first placement is part of registration: no admission,
            # account or student survives a placement refusal.
            db.rollback()
            raise

    if episode is not None:
        # The admission audit shares the registration transaction. If writing
        # it fails, the admission, student and account must all roll back.
        try:
            record_audit(
                db,
                action="admission.created",
                actor=actor,
                entity_type="academic_admission",
                entity_id=episode.id,
                context={
                    "student_id": str(student.id),
                    "intake_id": str(episode.admission_intake_id),
                    "initial_status": episode.initial_status,
                    "status": episode.status,
                    "onboarding": True,
                },
                request=request,
            )
            if placement is not None:
                record_audit(
                    db,
                    action="academic.placement.created",
                    actor=actor,
                    entity_type="academic_placement",
                    entity_id=placement.id,
                    context={
                        "student_id": str(student.id),
                        "admission_id": str(episode.id),
                        "previous_placement_id": None,
                        "new_placement_id": str(placement.id),
                        "admission_intake_id": str(episode.admission_intake_id),
                        "placement_intake_id": str(placement.academic_period_id),
                        "program_offering_id": str(placement.program_offering_id),
                        "is_earlier_intake_placement": False,
                        "effective_from": placement.effective_from.isoformat(),
                        "onboarding": True,
                    },
                    request=request,
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
    else:
        db.commit()

    db.refresh(student)
    db.refresh(user)
    return student, temporary_password, episode
