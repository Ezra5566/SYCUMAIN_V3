"""Student CRUD API router with authorization."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi import status as http_status
from fastapi.responses import Response
from sqlalchemy.orm import Session as DBSession

from app.audit import record_audit
from app.auth.dependencies import CurrentUser
from app.config.settings import get_settings
from app.database.session import get_db
from app.models.admission import AcademicAdmission, AdmissionVerificationSlot
from app.models.identity import Student, StudentStatus, User
from app.permissions import scope
from app.permissions.checks import has_permission
from app.schemas.admission import (
    AdmissionCreate,
    AdmissionListResponse,
    AdmissionRead,
    AdmissionStatusCorrection,
    AdmissionTransition,
    MigratedAdmissionCreate,
    MigratedAdmissionUpdate,
    OriginalAdmissionCorrection,
    OriginalAdmissionCorrectionRead,
    VerificationActRead,
    VerificationConfirm,
    VerificationRevoke,
)
from app.schemas.student import (
    BulkResultItem,
    StudentAcademicUpdate,
    StudentAccountResponse,
    StudentBulkResponse,
    StudentBulkStatusUpdate,
    StudentCreate,
    StudentDetail,
    StudentListResponse,
    StudentOnboard,
    StudentOnboardedResponse,
    StudentPlacementStatus,
    StudentProgramOfferingUpdate,
    StudentSelfUpdate,
    StudentStatusUpdate,
    StudentUpdate,
)
from app.services.admission import (
    admission_to_read,
    correct_admission_status,
    create_admission,
    list_admissions,
    transition_admission,
)
from app.services.admission_verification import (
    OriginalAdmissionOrderConflictError,
    confirm_slot,
    correct_original_admission,
    create_migrated_candidate,
    list_verification_acts,
    revoke_slot,
    update_migrated_candidate,
    verification_acts_to_read,
)
from app.services.photo import (
    PhotoValidationError,
    clear_student_photo,
    read_student_photo,
    set_student_photo,
)
from app.services.student import (
    archive_student,
    create_student,
    get_student,
    get_student_by_user_id,
    list_students,
    onboard_student,
    student_to_detail,
    student_to_placement,
    update_student,
    update_student_self,
)
from app.storage import StorageError

router = APIRouter(prefix="/students", tags=["students"])

#: Fields that used to write the placement projection directly. They remain
#: accepted by the request models only so a populated legacy body can be
#: refused explicitly instead of being discarded by validation.
RETIRED_PLACEMENT_FIELDS = frozenset({"major_id", "program_id", "program_offering_id"})


def _get_student_or_404(db: DBSession, student_id: uuid.UUID) -> Student:
    """Get a student or raise 404."""
    student = get_student(db, student_id)
    if not student:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Student not found.",
                }
            },
        )
    return student


def _check_student_access(db: DBSession, current_user: User, student: Student) -> None:
    """Authorize access to one student record through the shared scope policy.

    The rule itself lives in `app.permissions.scope` — this function only
    chooses the message, so the router cannot drift from the policy that also
    governs documents, immigration and housing.
    """
    permitted = scope.accessible_student_ids(db, current_user)
    if permitted is None or student.id in permitted:
        return

    roles = scope.role_names(current_user)
    if "TEACHER" in roles:
        message = "This student is not in one of your classes."
    elif "STUDENT" in roles:
        message = "You can only access your own student record."
    else:
        message = "You do not have permission to access student records."

    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail={"error": {"code": "FORBIDDEN", "message": message}},
    )


# --- List Students ---


@router.get("/", response_model=StudentListResponse)
def list_students_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    search: str | None = Query(None, description="Search by name, student ID, or email"),
    student_status: StudentStatus | None = Query(
        None, alias="status", description="Filter by status"
    ),
    major_id: uuid.UUID | None = Query(None, description="Filter by major"),
    program_id: uuid.UUID | None = Query(None, description="Filter by program"),
    has_housing: bool | None = Query(
        None, description="Filter by whether the student has active housing"
    ),
    immigration_status: str | None = Query(
        None,
        description=(
            "Filter by immigration document status: "
            "VALID, EXPIRING_SOON, URGENT, EXPIRED, NOT_PROVIDED"
        ),
    ),
    original_intake_id: uuid.UUID | None = Query(
        None,
        description=(
            "Filter by the intake of the verified original admission. "
            "Unverified, disputed and revoked admissions are excluded."
        ),
    ),
    current_intake_id: uuid.UUID | None = Query(
        None,
        description=(
            "Filter by the intake of the current open placement owned by the "
            "effective live admission."
        ),
    ),
    sort: str | None = Query(
        None, description="Sort key: name, -name, student_number, newest, oldest"
    ),
) -> StudentListResponse:
    """List students with pagination, search, and filtering.

    - ADMIN/MANAGEMENT: see all students
    - TEACHER: only students enrolled in the class sections they teach
    - STUDENT: cannot list all students
    """
    roles = scope.role_names(current_user)

    # Students cannot list all students
    if "STUDENT" in roles and not ({"ADMIN", "MANAGEMENT", "TEACHER"} & roles):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Students cannot access the student directory.",
                }
            },
        )

    return list_students(
        db,
        page=page,
        page_size=page_size,
        search=search,
        status=student_status,
        student_ids=scope.accessible_student_ids(db, current_user),
        major_id=major_id,
        program_id=program_id,
        has_housing=has_housing,
        immigration_status=immigration_status,
        original_intake_id=original_intake_id,
        current_intake_id=current_intake_id,
        sort=sort,
    )


# --- Onboard Student (record + login account) ---
#
# Declared before the `/`-rooted create below only for readability; the paths
# do not collide because this is a literal segment and FastAPI matches exact
# routes before parameterised ones.


@router.post(
    "/onboard",
    response_model=StudentOnboardedResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def onboard_new_student(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    data: StudentOnboard,
    request: Request,
) -> StudentOnboardedResponse:
    """Create a student record and its login account in one transaction.

    This is the operational onboarding path: the administrator receives a
    one-time temporary password to hand to the student, who is then required
    to change it on first use.
    """
    if not has_permission(current_user, "student.create"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to create students.",
                }
            },
        )

    # Creating the login account is account administration, so it needs the
    # account permission as well — `student.create` alone must not be able to
    # mint a privileged login on a delegated operator's behalf.
    if not (
        has_permission(current_user, "users.manage")
        or has_permission(current_user, "users.manage_students")
    ):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to create accounts.",
                }
            },
        )

    try:
        student, temporary_password, _episode = onboard_student(
            db, data, actor=current_user, request=request
        )
    except ValueError as exc:
        # Placement-specific failures (source-only offerings, closed intakes)
        # get a typed response; the legacy onboarding conflicts keep their
        # historical 409 semantics and human-readable message.
        if str(exc) in _PLACEMENT_ERRORS:
            raise _placement_error(exc) from exc
        if str(exc) in _ADMISSION_ERRORS:
            raise _admission_error(exc) from exc
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"error": {"code": "CONFLICT", "message": str(exc)}},
        ) from exc

    record_audit(
        db,
        action="student.created",
        actor=current_user,
        entity_type="student",
        entity_id=student.id,
        context={
            "student_number": student.student_id,
            "account_created": True,
        },
        request=request,
    )
    record_audit(
        db,
        action="account.created",
        actor=current_user,
        entity_type="user",
        entity_id=student.user_id,
        context={"roles": ["STUDENT"], "onboarding": True},
        request=request,
    )
    db.commit()
    db.refresh(student)

    account = student.user
    return StudentOnboardedResponse(
        student=student_to_detail(student),
        account=StudentAccountResponse(
            user_id=account.id,
            email=account.email,
            username=account.username,
            is_active=account.is_active,
            must_change_password=account.must_change_password,
            last_login_at=account.last_login_at,
        ),
        temporary_password=temporary_password,
    )


# Declared before `/{student_id}` on purpose: that route is typed as a UUID,
# so a literal `/me` reaching it would be rejected as a malformed identifier.


@router.get("/me", response_model=StudentDetail)
def get_own_student_record(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
) -> StudentDetail:
    """Return the caller's own student record.

    Self-service needs a way to resolve "my record" without knowing an
    identifier that the student is never shown. Scoping is by session identity
    only, so this cannot be used to read anyone else.
    """
    student = (
        db.query(Student).filter(Student.user_id == current_user.id).first()
    )
    if student is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NO_STUDENT_RECORD",
                    "message": "No student record is associated with this account.",
                }
            },
        )
    return student_to_detail(student)


@router.get("/me/academic", response_model=StudentPlacementStatus)
def get_own_placement_status(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
) -> StudentPlacementStatus:
    """Whether the signed-in student may still choose their own placement.

    The UI uses this to decide between showing a major picker and showing a
    read-only value, rather than guessing the rule and disagreeing with the
    backend.
    """
    student = get_student_by_user_id(db, current_user.id)
    if student is None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "NO_STUDENT_RECORD",
                    "message": "No student record is associated with this account.",
                }
            },
        )
    return student_to_placement(student)


@router.post("/me/academic", response_model=StudentDetail)
def select_own_academic_placement(
    current_user: CurrentUser,
    data: StudentAcademicUpdate,
) -> StudentDetail:
    """Refuse every legacy self-service direct-placement selection.

    Phase 8b retires all three fields, including ``program_offering_id``. A
    programme change must use the dedicated Phase 4 admission-change request
    endpoint, where the target is validated against the live episode.
    """
    # Authentication remains required, but the body is rejected before any
    # student lookup or feature-flag/lifecycle branch can change the outcome.
    if RETIRED_PLACEMENT_FIELDS & data.model_fields_set:
        raise _placement_error(ValueError("placement_direct_write_retired"))

    if not data.model_fields_set:
        raise _placement_error(ValueError("major_id_required"))

    raise _placement_error(ValueError("placement_direct_write_retired"))


@router.get("/{student_id}/account", response_model=StudentAccountResponse)
def get_student_account(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
) -> StudentAccountResponse:
    """Read a student's linked login account. Never exposes credentials."""
    if not has_permission(current_user, "users.view"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to view accounts.",
                }
            },
        )
    student = _get_student_or_404(db, student_id)
    account = student.user
    if account is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NO_ACCOUNT",
                    "message": "This student has no login account.",
                }
            },
        )
    return StudentAccountResponse(
        user_id=account.id,
        email=account.email,
        username=account.username,
        is_active=account.is_active,
        must_change_password=account.must_change_password,
        last_login_at=account.last_login_at,
    )


# --- Bulk Status Update ---


@router.post("/bulk/status", response_model=StudentBulkResponse)
def bulk_update_student_status(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    data: StudentBulkStatusUpdate,
    request: Request,
) -> StudentBulkResponse:
    """Apply one status change to many students.

    Each student is reported individually rather than failing the whole batch:
    an operator selecting a mixed page should get the ones they may change, and
    a clear reason for each one they may not.
    """
    if not has_permission(current_user, "student.edit"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to edit students.",
                }
            },
        )

    permitted = scope.accessible_student_ids(db, current_user)
    results: list[BulkResultItem] = []
    succeeded = 0

    for target_id in data.student_ids:
        student = get_student(db, target_id)
        if student is None:
            results.append(
                BulkResultItem(
                    student_id=target_id, ok=False, error="Student not found."
                )
            )
            continue

        if permitted is not None and student.id not in permitted:
            results.append(
                BulkResultItem(
                    student_id=target_id,
                    student_number=student.student_id,
                    ok=False,
                    error="Outside your scope.",
                )
            )
            continue

        previous = student.status
        student.status = data.status
        record_audit(
            db,
            action="student.status_changed",
            actor=current_user,
            entity_type="student",
            entity_id=student.id,
            context={
                "from": str(previous),
                "to": str(data.status),
                "bulk": True,
            },
            request=request,
        )
        succeeded += 1
        results.append(
            BulkResultItem(
                student_id=target_id, student_number=student.student_id, ok=True
            )
        )

    db.commit()
    return StudentBulkResponse(
        requested=len(data.student_ids),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


# --- Create Student ---


@router.post("/", response_model=StudentDetail, status_code=http_status.HTTP_201_CREATED)
def create_student_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    data: StudentCreate,
    request: Request,
) -> StudentDetail:
    """Create a new student record.

    Only ADMIN and MANAGEMENT can create students.
    """
    if not has_permission(current_user, "student.create"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to create students.",
                }
            },
        )

    try:
        student = create_student(db, data)
    except ValueError as e:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "CONFLICT",
                    "message": str(e),
                }
            },
        ) from e

    record_audit(
        db,
        action="student.created",
        actor=current_user,
        entity_type="student",
        entity_id=student.id,
        context={"student_number": student.student_id},
        request=request,
    )
    db.commit()
    return student_to_detail(student)


# --- Get Student ---


@router.get("/{student_id}", response_model=StudentDetail)
def get_student_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
) -> StudentDetail:
    """Get a student's detailed profile."""
    student = _get_student_or_404(db, student_id)
    _check_student_access(db, current_user, student)
    return student_to_detail(student)


#: Human-readable text for the placement/identifier errors the service raises.
#: The API returns a stable machine-readable code so the frontend localizes
#: the message rather than parsing prose, which is what makes the multilingual
#: contract survive new error cases.
#:
#: Each entry carries its code as a literal, keyed by the service-layer reason.
#: The code used to be produced by uppercasing the key at runtime, which meant
#: nothing in the source named the string the client actually receives — so a
#: whole family of codes reached the frontend with no message in any language
#: and no check noticed. Naming them here is what lets `check-i18n.mjs` verify
#: them (`CODE_CARRYING_MAPPINGS`).
_PLACEMENT_ERRORS: dict[str, tuple[int, str, str]] = {
    # service reason -> (status, public code, message)
    "student_number_taken": (
        http_status.HTTP_409_CONFLICT,
        "DUPLICATE_STUDENT_NUMBER",
        "That student number is already in use.",
    ),
    "major_not_found": (
        http_status.HTTP_404_NOT_FOUND,
        "MAJOR_NOT_FOUND",
        "Major not found.",
    ),
    "program_not_found": (
        http_status.HTTP_404_NOT_FOUND,
        "PROGRAM_NOT_FOUND",
        "Program not found.",
    ),
    "program_major_mismatch": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROGRAM_MAJOR_MISMATCH",
        "That program does not belong to the selected major.",
    ),
    "inactive_major": (
        http_status.HTTP_409_CONFLICT,
        "INACTIVE_MAJOR",
        "That major is not accepting students.",
    ),
    "inactive_program": (
        http_status.HTTP_409_CONFLICT,
        "INACTIVE_PROGRAM",
        "That program is not accepting students.",
    ),
    "placement_already_confirmed": (
        http_status.HTTP_409_CONFLICT,
        "PLACEMENT_ALREADY_CONFIRMED",
        "Your academic placement has already been confirmed. Contact the office "
        "to request a change.",
    ),
    "program_offering_not_found": (
        http_status.HTTP_404_NOT_FOUND,
        "PROGRAM_OFFERING_NOT_FOUND",
        "Program offering not found.",
    ),
    "program_offering_change_reason_required": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROGRAM_OFFERING_REASON_REQUIRED",
        "A reason is required when changing an existing program offering.",
    ),
    "program_offering_unavailable": (
        http_status.HTTP_409_CONFLICT,
        "PROGRAM_OFFERING_UNAVAILABLE",
        "That intake offering is not open for student placement.",
    ),
    "program_offering_not_mapped": (
        http_status.HTTP_409_CONFLICT,
        "PROGRAM_OFFERING_NOT_MAPPED",
        "That source offering has not been mapped to a canonical program.",
    ),
    "major_id_required": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "MAJOR_REQUIRED",
        "Select a program offering or a major and program.",
    ),
    "placement_direct_write_retired": (
        http_status.HTTP_409_CONFLICT,
        "PLACEMENT_DIRECT_WRITE_RETIRED",
        "Direct academic-placement writes are retired. Use the placement or "
        "admission-change workflow.",
    ),
}


def _placement_error(exc: ValueError) -> HTTPException:
    """Map a service-layer placement error to a typed HTTP response."""
    code = str(exc)
    status_code, public_code, message = _PLACEMENT_ERRORS.get(
        code,
        (
            http_status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "The submitted values are not valid.",
        ),
    )
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": public_code, "message": message}},
    )


# --- Update Student ---


@router.patch("/{student_id}", response_model=StudentDetail)
def update_student_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    data: StudentUpdate,
    request: Request,
) -> StudentDetail:
    """Update ordinary student details (admin/management only).

    Placement fields are retired and refuse the whole request with
    ``PLACEMENT_DIRECT_WRITE_RETIRED``; they are never silently ignored.
    """
    student = _get_student_or_404(db, student_id)
    _check_student_access(db, current_user, student)

    if not has_permission(current_user, "student.edit"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to edit students.",
                }
            },
        )

    if RETIRED_PLACEMENT_FIELDS & data.model_fields_set:
        # The profile endpoint still maintains ordinary student details. A
        # placement field is refused as a whole request so no partial update
        # is applied while the caller believes the placement changed.
        raise _placement_error(ValueError("placement_direct_write_retired"))

    try:
        updated = update_student(db, student, data)
    except ValueError as e:
        raise _placement_error(e) from e

    record_audit(
        db,
        action="student.updated",
        actor=current_user,
        entity_type="student",
        entity_id=updated.id,
        # Field *names* only — never values, which can be sensitive.
        context={"fields": sorted(data.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    db.commit()
    return student_to_detail(updated)


# --- Program offering assignment ---


@router.patch(
    "/{student_id}/program-offering",
    response_model=StudentDetail,
    deprecated=True,
)
def update_student_program_offering_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    data: StudentProgramOfferingUpdate,
    request: Request,
) -> StudentDetail:
    """Retired direct offering reassignment.

    Phase 8b removed the backing Student columns, so this route always refuses
    with ``PLACEMENT_DIRECT_WRITE_RETIRED``. Placement changes must use the
    placement or admission-change workflow.
    """
    student = _get_student_or_404(db, student_id)
    _check_student_access(db, current_user, student)

    if not has_permission(current_user, "student.edit"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to edit students.",
                }
            },
        )

    raise _placement_error(ValueError("placement_direct_write_retired"))


# --- Student Self-Update ---


@router.patch("/{student_id}/self", response_model=StudentDetail)
def update_student_self_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    data: StudentSelfUpdate,
) -> StudentDetail:
    """Update own student profile (limited fields).

    Students can update: phone, emergency_contact_name, emergency_contact_phone.
    """
    student = _get_student_or_404(db, student_id)
    _check_student_access(db, current_user, student)

    # Only the student themselves can use self-update
    if "STUDENT" not in scope.role_names(current_user):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Self-update is only available to students.",
                }
            },
        )

    updated = update_student_self(db, student, data)
    return student_to_detail(updated)


# --- Archive Student ---


@router.post("/{student_id}/archive", response_model=StudentDetail)
def archive_student_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    request: Request,
) -> StudentDetail:
    """Archive a student (set status to INACTIVE).

    Only ADMIN and MANAGEMENT can archive students.
    """
    student = _get_student_or_404(db, student_id)
    _check_student_access(db, current_user, student)

    if not has_permission(current_user, "student.archive"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to archive students.",
                }
            },
        )

    archived = archive_student(db, student)

    record_audit(
        db,
        action="student.archived",
        actor=current_user,
        entity_type="student",
        entity_id=archived.id,
        request=request,
    )
    db.commit()
    return student_to_detail(archived)


# --- Update Student Status ---


@router.patch("/{student_id}/status", response_model=StudentDetail)
def update_student_status_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    data: StudentStatusUpdate,
    request: Request,
) -> StudentDetail:
    """Update student status (admin/management only)."""
    student = _get_student_or_404(db, student_id)
    _check_student_access(db, current_user, student)

    if not has_permission(current_user, "student.edit"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to edit students.",
                }
            },
        )

    previous_status = student.status
    student.status = data.status

    record_audit(
        db,
        action="student.status_changed",
        actor=current_user,
        entity_type="student",
        entity_id=student.id,
        context={"from": str(previous_status), "to": str(data.status)},
        request=request,
    )
    db.commit()
    db.refresh(student)
    return student_to_detail(student)


# --- Profile photo ---------------------------------------------------------


def _is_own_record(current_user: User, student: Student) -> bool:
    return current_user.id == student.user_id


def _check_photo_write_access(db: DBSession, current_user: User, student: Student) -> None:
    """A student may manage their own photo; staff need ``student.edit``.

    Photos are personal data rather than an institutional record, so the
    student owning the record is allowed to change it without holding any
    administrative permission.
    """
    if _is_own_record(current_user, student):
        return

    if not has_permission(current_user, "student.edit"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to change this photo.",
                }
            },
        )

    _check_student_access(db, current_user, student)


@router.put("/{student_id}/photo", response_model=StudentDetail)
async def upload_student_photo(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
) -> StudentDetail:
    """Upload or replace a student's profile photo.

    The image is validated by magic number (never by filename or the declared
    ``Content-Type``) and stored in the private object backend. The response
    carries no URL: the photo is fetched through ``GET .../photo``.
    """
    student = _get_student_or_404(db, student_id)
    _check_photo_write_access(db, current_user, student)

    data = await file.read()

    try:
        student = set_student_photo(
            db,
            student=student,
            actor=current_user,
            data=data,
            filename=file.filename,
            request=request,
        )
    except PhotoValidationError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": exc.code.upper(), "message": exc.message}},
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "STORAGE_UNAVAILABLE",
                    "message": "Photo storage is currently unavailable.",
                }
            },
        ) from exc

    return student_to_detail(student)


@router.get("/{student_id}/photo")
def get_student_photo(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
):
    """Serve a student's profile photo to an authorized viewer.

    Streamed rather than redirected to a public URL, so the photo is exactly
    as private as the record it belongs to.
    """
    student = _get_student_or_404(db, student_id)
    _check_student_access(db, current_user, student)

    photo = read_student_photo(student)
    if photo is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "No photo on file."}},
        )

    payload, content_type = photo
    return Response(
        content=payload,
        media_type=content_type,
        headers={
            # Personal data: never cached by shared proxies.
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@router.delete("/{student_id}/photo", response_model=StudentDetail)
def delete_student_photo(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    request: Request,
) -> StudentDetail:
    """Remove a student's profile photo."""
    student = _get_student_or_404(db, student_id)
    _check_photo_write_access(db, current_user, student)

    student = clear_student_photo(db, student=student, actor=current_user, request=request)
    return student_to_detail(student)


# --- Admissions (Phase 1) --------------------------------------------------

_ADMISSION_ERRORS: dict[str, tuple[int, str, str]] = {
    "STUDENT_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "STUDENT_NOT_FOUND",
        "Student not found.",
    ),
    "ADMISSION_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "ADMISSION_NOT_FOUND",
        "Admission not found.",
    ),
    "ADMISSION_INTAKE_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "ADMISSION_INTAKE_NOT_FOUND",
        "Intake not found.",
    ),
    "ADMISSION_INTAKE_ALREADY_LIVE": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_INTAKE_ALREADY_LIVE",
        "This student already has a live admission for that intake.",
    ),
    "PROGRAM_CHANGE_NOT_NEW_ADMISSION": (
        http_status.HTTP_409_CONFLICT,
        "PROGRAM_CHANGE_NOT_NEW_ADMISSION",
        "The student already has a live admission in this intake. Record a "
        "programme change on that episode instead of a new admission.",
    ),
    "NO_ADMISSION_EPISODE": (
        http_status.HTTP_409_CONFLICT,
        "NO_ADMISSION_EPISODE",
        "A programme change requires a live admission episode.",
    ),
    "CHANGE_REQUEST_PENDING_EXISTS": (
        http_status.HTTP_409_CONFLICT,
        "CHANGE_REQUEST_PENDING_EXISTS",
        "A pending request of this type already exists for the admission.",
    ),
    "PROGRAM_CHANGE_TARGET_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROGRAM_CHANGE_TARGET_REQUIRED",
        "Select the programme the student is changing to.",
    ),
    "PROGRAM_CHANGE_TARGET_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "PROGRAM_CHANGE_TARGET_NOT_FOUND",
        "The selected programme was not found.",
    ),
    "PROGRAM_CHANGE_TARGET_INACTIVE": (
        http_status.HTTP_409_CONFLICT,
        "PROGRAM_CHANGE_TARGET_INACTIVE",
        "The selected programme is not active.",
    ),
    "PROGRAM_CHANGE_SAME_PROGRAM": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROGRAM_CHANGE_SAME_PROGRAM",
        "The selected programme is already the current programme.",
    ),
    "PROGRAM_CHANGE_OFFERING_INTAKE_MISMATCH": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROGRAM_CHANGE_OFFERING_INTAKE_MISMATCH",
        "A programme change offering must belong to the existing admission intake.",
    ),
    "PROGRAM_CHANGE_OFFERING_MISMATCH": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "PROGRAM_CHANGE_OFFERING_MISMATCH",
        "The selected offering does not belong to the selected programme.",
    ),
    "ADMISSION_MUST_BE_PENDING": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_MUST_BE_PENDING",
        "The student already has an active admission. A future admission may "
        "only be recorded as pending.",
    ),
    "ADMISSION_ALREADY_ACTIVE": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_ALREADY_ACTIVE",
        "The student already has an active admission. End it before activating "
        "another one.",
    ),
    "ADMISSION_INTAKE_PRECEDES_ACTIVE_EPISODE": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_INTAKE_PRECEDES_ACTIVE_EPISODE",
        "That intake starts before the active admission's intake. Use the "
        "verified-migration workflow for a historical admission.",
    ),
    "ADMISSION_TERMINAL": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_TERMINAL",
        "A completed, withdrawn or cancelled admission cannot change status.",
    ),
    "ADMISSION_TRANSITION_NOT_ALLOWED": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_TRANSITION_NOT_ALLOWED",
        "That status transition is not allowed.",
    ),
    "ADMISSION_REASON_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "ADMISSION_REASON_REQUIRED",
        "A reason is required when withdrawing or cancelling an admission.",
    ),
    "ADMISSION_CORRECTION_NOT_TERMINAL": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_CORRECTION_NOT_TERMINAL",
        "Only a completed, withdrawn or cancelled admission can be corrected here.",
    ),
    "ADMISSION_CORRECTION_UNCHANGED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "ADMISSION_CORRECTION_UNCHANGED",
        "Select a status different from the recorded status.",
    ),
    "ADMISSION_CORRECTION_REASON_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "ADMISSION_CORRECTION_REASON_REQUIRED",
        "A reason is required to correct an admission status.",
    ),
    "ADMISSION_CORRECTIONS_DISABLED": (
        http_status.HTTP_403_FORBIDDEN,
        "ADMISSION_CORRECTIONS_DISABLED",
        "Admission corrections are currently disabled.",
    ),
    "INTAKE_DATES_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INTAKE_DATES_REQUIRED",
        "The intake must have both an official start and end date.",
    ),
    "INTAKE_DATES_INVALID": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "INTAKE_DATES_INVALID",
        "The intake's end date cannot precede its start date.",
    ),
    "ADMISSION_OFFERING_INTAKE_MISMATCH": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "ADMISSION_OFFERING_INTAKE_MISMATCH",
        "That offering does not belong to the selected intake.",
    ),
    "ADMISSION_OFFERING_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "ADMISSION_OFFERING_REQUIRED",
        "Select a program offering to record an admission.",
    ),
    "ADMISSION_ACTOR_REQUIRED": (
        http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        "ADMISSION_ACTOR_REQUIRED",
        "The admission could not be attributed to an operator.",
    ),
    "ADMISSIONS_WRITE_DISABLED": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSIONS_WRITE_DISABLED",
        "Admission writes are currently disabled.",
    ),
    "MIGRATION_CONSOLE_DISABLED": (
        http_status.HTTP_403_FORBIDDEN,
        "MIGRATION_CONSOLE_DISABLED",
        "The admission migration verification console is disabled.",
    ),
    "MIGRATION_VALIDATION_ERROR": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "MIGRATION_VALIDATION_ERROR",
        "Provide an intake or program offering for the migration candidate.",
    ),
    "ADMISSION_NOT_MIGRATED": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_NOT_MIGRATED",
        "Only migrated admission candidates can be verified or revoked.",
    ),
    "CANDIDATE_LOCKED": (
        http_status.HTTP_409_CONFLICT,
        "CANDIDATE_LOCKED",
        "This candidate can no longer be edited because verification has started.",
    ),
    "SLOT_ALREADY_CONFIRMED": (
        http_status.HTTP_409_CONFLICT,
        "SLOT_ALREADY_CONFIRMED",
        "That confirmation slot is already confirmed.",
    ),
    "CONFIRMATION_ACTOR_MUST_DIFFER": (
        http_status.HTTP_403_FORBIDDEN,
        "CONFIRMATION_ACTOR_MUST_DIFFER",
        "The two confirmation slots must be filled by different users.",
    ),
    "SLOT_NOT_CONFIRMED": (
        http_status.HTTP_409_CONFLICT,
        "SLOT_NOT_CONFIRMED",
        "That confirmation slot is not currently confirmed.",
    ),
    "SLOT_ALREADY_REVOKED": (
        http_status.HTTP_409_CONFLICT,
        "SLOT_ALREADY_REVOKED",
        "That confirmation slot has already been revoked.",
    ),
    "EVIDENCE_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "EVIDENCE_REQUIRED",
        "An evidence reference is required to confirm a candidate.",
    ),
    "REVOCATION_REASON_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "REVOCATION_REASON_REQUIRED",
        "A reason is required to revoke a confirmation.",
    ),
    "POINTER_TARGET_NOT_VERIFIED": (
        http_status.HTTP_409_CONFLICT,
        "POINTER_TARGET_NOT_VERIFIED",
        "The original-admission pointer can only point to a verified admission.",
    ),
    "POINTER_UNCHANGED": (
        http_status.HTTP_409_CONFLICT,
        "POINTER_UNCHANGED",
        "The original-admission pointer already points to that admission.",
    ),
    "POINTER_REASON_REQUIRED": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "POINTER_REASON_REQUIRED",
        "A reason is required to correct the original-admission pointer.",
    ),
    "ORIGINAL_ADMISSION_ORDER_CONFLICT": (
        http_status.HTTP_409_CONFLICT,
        "ORIGINAL_ADMISSION_ORDER_CONFLICT",
        "That admission predates the existing original-admission pointer; "
        "an administrator must correct the pointer deliberately.",
    ),
    "ADMISSION_CONFLICT": (
        http_status.HTTP_409_CONFLICT,
        "ADMISSION_CONFLICT",
        "The admission conflicts with the current lifecycle state.",
    ),
    "VALIDATION_ERROR": (
        http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        "VALIDATION_ERROR",
        "Select ADMITTED or ACTIVE as the initial admission status.",
    ),
    "PROGRAM_OFFERING_NOT_FOUND": (
        http_status.HTTP_404_NOT_FOUND,
        "PROGRAM_OFFERING_NOT_FOUND",
        "Program offering not found.",
    ),
    "PROGRAM_OFFERING_NOT_MAPPED": (
        http_status.HTTP_409_CONFLICT,
        "PROGRAM_OFFERING_NOT_MAPPED",
        "That source offering has not been mapped to a canonical program.",
    ),
}


def _admission_error(exc: ValueError) -> HTTPException:
    """Map a service-layer admission refusal to a typed HTTP response."""
    code = str(exc)
    status_code, public_code, message = _ADMISSION_ERRORS.get(
        code,
        (
            http_status.HTTP_409_CONFLICT,
            "ADMISSION_CONFLICT",
            "The admission conflicts with the current lifecycle state.",
        ),
    )
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": public_code, "message": message}},
    )


def _require_admission_permission(current_user: User, codename: str) -> None:
    if not has_permission(current_user, codename):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to manage admissions.",
                }
            },
        )


def _require_admission_writes_enabled() -> None:
    if not get_settings().ADMISSIONS_WRITE_ENABLED:
        raise _admission_error(ValueError("ADMISSIONS_WRITE_DISABLED"))


def _require_migration_console_enabled() -> None:
    if not get_settings().ADMISSION_MIGRATION_CONSOLE_ENABLED:
        raise _admission_error(ValueError("MIGRATION_CONSOLE_DISABLED"))


def _require_corrections_enabled() -> None:
    if not get_settings().ADMISSION_CORRECTIONS_ENABLED:
        raise _admission_error(ValueError("ADMISSION_CORRECTIONS_DISABLED"))


def _slot_permission(slot: AdmissionVerificationSlot) -> str:
    return (
        "academic.confirm_admission_management"
        if slot is AdmissionVerificationSlot.MANAGEMENT
        else "academic.confirm_admission_admin"
    )


@router.get("/{student_id}/admissions", response_model=AdmissionListResponse)
def list_student_admissions(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
) -> AdmissionListResponse:
    """Every admission episode for one student, newest first."""
    _require_admission_permission(current_user, "academic.view_admissions")
    student = _get_student_or_404(db, student_id)
    episodes = list_admissions(db, student.id)
    return AdmissionListResponse(
        items=[admission_to_read(db, episode) for episode in episodes],
        total=len(episodes),
    )


@router.post(
    "/{student_id}/admissions",
    response_model=AdmissionRead,
    status_code=http_status.HTTP_201_CREATED,
)
def create_student_admission(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    data: AdmissionCreate,
    request: Request,
) -> AdmissionRead:
    """Record an admission episode.

    While another episode is active, only ``PENDING`` is accepted. The
    admitted programme is derived from the offering; it cannot be supplied by
    the client.
    """
    _require_admission_permission(current_user, "academic.manage_admissions")
    _require_admission_writes_enabled()
    student = _get_student_or_404(db, student_id)

    try:
        episode = create_admission(db, student, data, current_user)
    except ValueError as exc:
        raise _admission_error(exc) from exc

    response = admission_to_read(db, episode)
    record_audit(
        db,
        action="admission.created",
        actor=current_user,
        entity_type="academic_admission",
        entity_id=episode.id,
        context={
            "student_id": str(student.id),
            "intake_id": str(episode.admission_intake_id),
            "initial_status": episode.initial_status,
            "status": episode.status,
        },
        request=request,
    )
    db.commit()
    return response


@router.post(
    "/{student_id}/admissions/migrated",
    response_model=AdmissionRead,
    status_code=http_status.HTTP_201_CREATED,
)
def create_migrated_candidate_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    data: MigratedAdmissionCreate,
    request: Request,
) -> AdmissionRead:
    """Propose an existing student's original admission for dual confirmation."""
    _require_admission_permission(current_user, "academic.manage_admissions")
    _require_admission_writes_enabled()
    _require_migration_console_enabled()
    student = _get_student_or_404(db, student_id)

    try:
        episode = create_migrated_candidate(db, student, data, current_user, request)
    except ValueError as exc:
        raise _admission_error(exc) from exc

    response = admission_to_read(db, episode)
    db.commit()
    return response


@router.patch(
    "/{student_id}/admissions/{admission_id}/migrated",
    response_model=AdmissionRead,
)
def update_migrated_candidate_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    data: MigratedAdmissionUpdate,
    request: Request,
) -> AdmissionRead:
    """Correct a candidate while it is still unverified."""
    _require_admission_permission(current_user, "academic.manage_admissions")
    _require_admission_writes_enabled()
    _require_migration_console_enabled()
    student = _get_student_or_404(db, student_id)

    try:
        episode = update_migrated_candidate(
            db, student, admission_id, data, current_user, request
        )
    except ValueError as exc:
        raise _admission_error(exc) from exc

    response = admission_to_read(db, episode)
    db.commit()
    return response


@router.post(
    "/{student_id}/admissions/{admission_id}/confirm/{slot}",
    response_model=AdmissionRead,
)
def confirm_migrated_slot(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    slot: AdmissionVerificationSlot,
    data: VerificationConfirm,
    request: Request,
) -> AdmissionRead:
    """Append one independent Management or Admin confirmation."""
    _require_admission_permission(current_user, _slot_permission(slot))
    _require_admission_writes_enabled()
    _require_migration_console_enabled()
    student = _get_student_or_404(db, student_id)

    try:
        episode = confirm_slot(
            db, student, admission_id, slot, data, current_user, request
        )
    except OriginalAdmissionOrderConflictError as exc:
        # Verification and both acts are valid, but the pointer stayed put.
        db.commit()
        raise _admission_error(ValueError("ORIGINAL_ADMISSION_ORDER_CONFLICT")) from exc
    except ValueError as exc:
        raise _admission_error(exc) from exc

    response = admission_to_read(db, episode)
    db.commit()
    return response


@router.post(
    "/{student_id}/admissions/{admission_id}/confirm/{slot}/revoke",
    response_model=AdmissionRead,
)
def revoke_migrated_slot(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    slot: AdmissionVerificationSlot,
    data: VerificationRevoke,
    request: Request,
) -> AdmissionRead:
    """Revoke a slot while retaining every earlier confirmation act."""
    _require_admission_permission(current_user, _slot_permission(slot))
    _require_admission_writes_enabled()
    _require_migration_console_enabled()
    student = _get_student_or_404(db, student_id)

    try:
        episode = revoke_slot(
            db, student, admission_id, slot, data, current_user, request
        )
    except ValueError as exc:
        raise _admission_error(exc) from exc

    response = admission_to_read(db, episode)
    db.commit()
    return response


@router.get(
    "/{student_id}/admissions/{admission_id}/verification-acts",
    response_model=list[VerificationActRead],
)
def list_migrated_verification_acts(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
) -> list[VerificationActRead]:
    """Every confirmation and revocation act, in order, including revoked acts."""
    _require_admission_permission(current_user, "academic.view_admissions")
    student = _get_student_or_404(db, student_id)
    acts = list_verification_acts(db, student.id, admission_id)
    return verification_acts_to_read(db, acts)


@router.post(
    "/{student_id}/original-admission/correction",
    response_model=OriginalAdmissionCorrectionRead,
)
def correct_student_original_admission(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    data: OriginalAdmissionCorrection,
    request: Request,
) -> OriginalAdmissionCorrectionRead:
    """ADMIN-only, audited replacement of the original-admission pointer."""
    _require_admission_permission(current_user, "academic.correct_original_admission")
    _require_admission_writes_enabled()
    _require_migration_console_enabled()
    _require_corrections_enabled()
    student = _get_student_or_404(db, student_id)
    previous = student.original_admission_id

    try:
        updated = correct_original_admission(
            db, student, data, current_user, request
        )
    except ValueError as exc:
        raise _admission_error(exc) from exc

    db.commit()
    return OriginalAdmissionCorrectionRead(
        student_id=updated.id,
        previous_admission_id=previous,
        original_admission_id=data.new_admission_id,
    )


@router.post(
    "/{student_id}/admissions/{admission_id}/status",
    response_model=AdmissionRead,
)
def transition_student_admission(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    data: AdmissionTransition,
    request: Request,
) -> AdmissionRead:
    """Apply one lifecycle transition to an episode."""
    required = {
        "ADMITTED": "academic.manage_admissions",
        "ACTIVE": "academic.activate_admission",
        "COMPLETED": "academic.end_admission",
        "WITHDRAWN": "academic.end_admission",
        "CANCELLED": "academic.end_admission",
    }[data.status]
    _require_admission_permission(current_user, required)
    _require_admission_writes_enabled()
    student = _get_student_or_404(db, student_id)

    existing = (
        db.query(AcademicAdmission)
        .filter(
            AcademicAdmission.id == admission_id,
            AcademicAdmission.student_id == student.id,
        )
        .first()
    )
    if existing is None:
        raise _admission_error(ValueError("ADMISSION_NOT_FOUND"))
    previous = existing.status

    try:
        episode = transition_admission(
            db, student, admission_id, data, current_user
        )
    except ValueError as exc:
        raise _admission_error(exc) from exc

    response = admission_to_read(db, episode)
    try:
        record_audit(
            db,
            action="admission.status_changed",
            actor=current_user,
            entity_type="academic_admission",
            entity_id=episode.id,
            context={
                "student_id": str(student.id),
                "from": previous,
                "to": episode.status,
                "reason": data.reason,
            },
            request=request,
        )
        db.commit()
    except Exception:
        # The status, history trigger row and placement closure share this
        # transaction; an audit failure must not leave any of them committed.
        db.rollback()
        raise
    return response


@router.post(
    "/{student_id}/admissions/{admission_id}/corrections/status",
    response_model=AdmissionRead,
)
def correct_student_admission_status(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    admission_id: uuid.UUID,
    data: AdmissionStatusCorrection,
    request: Request,
) -> AdmissionRead:
    """ADMIN-only, audited correction of a mistaken lifecycle status."""
    _require_admission_permission(current_user, "academic.correct_admission_status")
    _require_admission_writes_enabled()
    _require_corrections_enabled()
    student = _get_student_or_404(db, student_id)

    try:
        episode = correct_admission_status(
            db,
            student,
            admission_id,
            data,
            current_user,
            request,
            require_terminal=True,
        )
    except ValueError as exc:
        raise _admission_error(exc) from exc

    response = admission_to_read(db, episode)
    db.commit()
    return response
