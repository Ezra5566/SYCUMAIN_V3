"""Immigration API router with authorization and change request workflow."""

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession

from app.audit import record_audit
from app.auth.dependencies import CurrentUser
from app.config.settings import get_settings
from app.database.session import get_db
from app.models.identity import Student, User
from app.models.immigration import (
    ImmigrationChangeRequestStatus,
    ImmigrationDocumentType,
    ImmigrationProfile,
)
from app.models.platform import NotificationType
from app.permissions.checks import has_permission
from app.schemas.immigration import (
    ChangeRequestReview,
    ChangeRequestSubmit,
    ImmigrationChangeRequestResponse,
    ImmigrationCohortResponse,
    ImmigrationDocumentUploadResponse,
    ImmigrationImportApplyRequest,
    ImmigrationImportApplyResponse,
    ImmigrationImportPreviewResponse,
    ImmigrationImportRequest,
    ImmigrationOverviewResponse,
    ImmigrationProfileResponse,
    ImmigrationProfileStudentView,
    ImmigrationProfileUpdate,
    ImmigrationProfileVersionResponse,
    NationalityDistributionResponse,
)
from app.schemas.immigration_reminder import (
    ImmigrationReminderList,
    ImmigrationReminderRunResult,
)
from app.services.immigration import (
    apply_immigration_import,
    approve_change_request,
    change_request_to_response,
    get_immigration_cohort,
    get_immigration_overview,
    get_immigration_profile,
    get_nationality_distribution,
    get_or_create_immigration_profile,
    list_profile_versions,
    preview_immigration_import,
    profile_to_response,
    profile_to_student_view,
    reject_change_request,
    submit_change_request,
    update_immigration_profile,
    upload_immigration_document,
)
from app.services.immigration_reminders import (
    list_reminders,
    run_expiry_reminders,
)
from app.services.notification import notify_users_with_role

router = APIRouter(tags=["immigration"])


def _csv_safe(value: object) -> str:
    """Keep spreadsheet formulas and empty values inert in CSV exports."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def _audit(db, *, action, actor, entity_id, context=None, request=None) -> None:
    """Record an immigration audit entry on the current transaction."""
    record_audit(
        db,
        action=action,
        actor=actor,
        entity_type="immigration_change_request",
        entity_id=entity_id,
        context=context,
        request=request,
    )


def _notify_submitter(db, change_request, *, approved: bool, actor: User) -> None:
    """Tell the submitting student the outcome of their request."""
    from app.services.notification import create_notification  # noqa: PLC0415

    if change_request.submitted_by == actor.id:
        return
    create_notification(
        db,
        user_id=change_request.submitted_by,
        notification_type=(
            NotificationType.IMMIGRATION_CHANGE_APPROVED
            if approved
            else NotificationType.IMMIGRATION_CHANGE_REJECTED
        ),
        params={"change_type": change_request.change_type},
        link_url="/app/profile/immigration",
        entity_type="immigration_change_request",
        entity_id=change_request.id,
    )


def _own_student_id(db: DBSession, user: User) -> uuid.UUID | None:
    """Resolve the caller's own student record id (if they have one).

    Students are scoped by their *student record* id, which is deliberately
    distinct from their user id.
    """
    student = db.query(Student).filter(Student.user_id == user.id).first()
    return student.id if student else None


def _get_student_or_404(db: DBSession, student_id: uuid.UUID) -> Student:
    """Get a student or raise 404."""
    student = db.query(Student).filter(Student.id == student_id).first()
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


def _check_immigration_access(
    current_user: User, student: Student, require_write: bool = False
) -> None:
    """Check if current user can access this student's immigration data.

    Rules:
    - ADMIN: full access
    - MANAGEMENT: view + edit (if immigration.edit permission)
    - TEACHER: denied
    - STUDENT: own data only, view only
    """
    role_names = {r.name for r in current_user.roles}

    if "ADMIN" in role_names:
        return

    if "MANAGEMENT" in role_names:
        if require_write and not has_permission(current_user, "immigration.edit"):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "You do not have permission to edit immigration records.",
                    }
                },
            )
        return

    if "TEACHER" in role_names:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Teachers do not have access to immigration records.",
                }
            },
        )

    if "STUDENT" in role_names:
        if current_user.id != student.user_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "You can only access your own immigration information.",
                    }
                },
            )
        return

    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail={
            "error": {
                "code": "FORBIDDEN",
                "message": "You do not have access to immigration records.",
            }
        },
    )


# --- Student Immigration Profile ---


@router.get(
    "/students/{student_id}/immigration",
    response_model=ImmigrationProfileResponse | ImmigrationProfileStudentView,
)
def get_student_immigration(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
):
    """Get immigration profile for a student.

    - ADMIN/MANAGEMENT: full view with sensitive fields
    - STUDENT: own data only (limited view)
    - TEACHER: denied
    """
    student = _get_student_or_404(db, student_id)
    _check_immigration_access(current_user, student)

    profile = get_immigration_profile(db, student_id)
    if not profile:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "No immigration profile found for this student.",
                }
            },
        )

    role_names = {r.name for r in current_user.roles}
    if "STUDENT" in role_names:
        return profile_to_student_view(profile)
    return profile_to_response(profile)


@router.get(
    "/students/{student_id}/immigration/history",
    response_model=list[ImmigrationProfileVersionResponse],
)
def get_immigration_history(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
):
    """Immutable immigration history for Management/Admin only.

    Deliberately not shared with the student-facing profile endpoint: a
    student who may see their current record must not automatically see every
    previous passport or visa identifier.
    """
    student = _get_student_or_404(db, student_id)
    role_names = {r.name for r in current_user.roles}
    if not ({ "ADMIN", "MANAGEMENT" } & role_names) or not has_permission(
        current_user, "immigration.view_all"
    ):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to view immigration history.",
                }
            },
        )

    profile = get_immigration_profile(db, student.id)
    if not profile:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "No immigration profile found for this student.",
                }
            },
        )
    return list_profile_versions(db, profile.id)


@router.patch(
    "/students/{student_id}/immigration",
    response_model=ImmigrationProfileResponse,
)
def update_student_immigration(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    data: ImmigrationProfileUpdate,
    request: Request,
):
    """Update immigration profile (management/admin only, direct update)."""
    student = _get_student_or_404(db, student_id)
    _check_immigration_access(current_user, student, require_write=True)

    profile = get_or_create_immigration_profile(
        db, student_id, actor_id=current_user.id
    )

    update_data = data.model_dump(exclude_unset=True)
    change_reason = update_data.pop("change_reason", None)
    role_names = {r.name for r in current_user.roles}
    profile = update_immigration_profile(
        db,
        profile,
        update_data,
        actor_id=current_user.id,
        reason=change_reason,
        data_source="ADMIN" if "ADMIN" in role_names else "MANAGEMENT",
        # Staged on the same transaction, so the audit entry commits with the
        # correction rather than in a second transaction afterwards.
        request=request,
    )
    return profile_to_response(profile)


@router.post(
    "/immigration/import/preview",
    response_model=ImmigrationImportPreviewResponse,
)
def preview_import_batch(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    data: ImmigrationImportRequest,
):
    """Validate a normalized batch without changing any record."""
    if not has_permission(current_user, "immigration.edit"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to import immigration records.",
                }
            },
        )
    return preview_immigration_import(db, data.records)


@router.post(
    "/immigration/import/apply",
    response_model=ImmigrationImportApplyResponse,
)
def apply_import_batch(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    data: ImmigrationImportApplyRequest,
    request: Request,
):
    """Apply a previewed batch only after explicit confirmation."""
    if not has_permission(current_user, "immigration.edit"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to import immigration records.",
                }
            },
        )
    if not data.confirm:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "IMPORT_CONFIRMATION_REQUIRED",
                    "message": "Preview the batch and explicitly confirm it before applying.",
                }
            },
        )
    try:
        result = apply_immigration_import(
            db,
            records=data.records,
            source_reference=data.source_reference,
            actor_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "VALIDATION_ERROR", "message": str(exc)}},
        ) from exc

    record_audit(
        db,
        action="immigration.import.applied",
        actor=current_user,
        entity_type="immigration_import",
        entity_id=None,
        context={
            "source_reference": data.source_reference,
            "records": len(data.records),
            "applied": result.applied,
            "conflicts": result.conflicts,
        },
        request=request,
    )
    db.commit()
    return result


# --- Change Requests ---


@router.post(
    "/students/{student_id}/immigration/change-requests",
    response_model=ImmigrationChangeRequestResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def submit_immigration_change(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    data: ChangeRequestSubmit,
    request: Request,
):
    """Submit an immigration change request (student workflow).

    Students submit changes that go through management approval.
    """
    student = _get_student_or_404(db, student_id)
    _check_immigration_access(current_user, student)

    # Only the student themselves can submit changes
    role_names = {r.name for r in current_user.roles}
    if "STUDENT" in role_names and current_user.id != student.user_id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You can only submit changes to your own immigration information.",
                }
            },
        )

    # Students must have immigration.edit or be the student themselves
    if "STUDENT" not in role_names and not has_permission(
        current_user, "immigration.edit"
    ):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to submit immigration changes.",
                }
            },
        )

    profile = get_or_create_immigration_profile(db, student_id)

    # Validate change_type
    valid_types = {"PASSPORT", "VISA", "RESIDENCE_PERMIT"}
    if data.change_type.upper() not in valid_types:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"Invalid change type. Must be one of: {', '.join(valid_types)}",
                }
            },
        )

    try:
        change_request = submit_change_request(
            db,
            immigration_profile_id=profile.id,
            submitted_by=current_user.id,
            change_type=data.change_type.upper(),
            proposed_data=data.proposed_data,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(e),
                }
            },
        ) from e

    _audit(
        db,
        action="immigration.change_request.created",
        actor=current_user,
        entity_id=change_request.id,
        context={"change_type": change_request.change_type},
        request=request,
    )
    # Reviewer queue is notified so nothing waits unnoticed.
    notify_users_with_role(
        db,
        role_names=["ADMIN", "MANAGEMENT"],
        notification_type=NotificationType.IMMIGRATION_CHANGE_SUBMITTED,
        params={"student_number": student.student_id},
        link_url="/app/immigration",
        entity_type="immigration_change_request",
        entity_id=change_request.id,
        exclude_user_ids={current_user.id},
    )
    db.commit()

    return change_request_to_response(db, change_request)


@router.get(
    "/immigration/change-requests",
    response_model=list[ImmigrationChangeRequestResponse],
)
def list_change_requests(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    status_filter: ImmigrationChangeRequestStatus | None = Query(
        None, alias="status", description="Filter by status"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    """List immigration change requests.

    - ADMIN/MANAGEMENT: see all requests
    - STUDENT: see own requests only
    """
    from app.models.immigration import ImmigrationChangeRequest

    role_names = {r.name for r in current_user.roles}

    query = db.query(ImmigrationChangeRequest)

    # Students can only see their own requests
    if "STUDENT" in role_names:
        # Scope by the caller's own student record, not their user id.
        own_student_id = _own_student_id(db, current_user)
        if own_student_id is None:
            return []
        profile_ids = [
            p.id
            for p in db.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == own_student_id)
            .all()
        ]
        if not profile_ids:
            return []
        query = query.filter(
            ImmigrationChangeRequest.immigration_profile_id.in_(profile_ids)
        )

    # Teachers cannot see any
    if "TEACHER" in role_names:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Teachers do not have access to immigration change requests.",
                }
            },
        )

    if status_filter:
        query = query.filter(ImmigrationChangeRequest.status == status_filter)

    requests = (
        query.order_by(ImmigrationChangeRequest.submitted_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return [change_request_to_response(db, r) for r in requests]


@router.get(
    "/immigration/change-requests/{request_id}",
    response_model=ImmigrationChangeRequestResponse,
)
def get_change_request(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    request_id: uuid.UUID,
):
    """Get a specific change request."""
    from app.models.immigration import ImmigrationChangeRequest

    request = (
        db.query(ImmigrationChangeRequest)
        .filter(ImmigrationChangeRequest.id == request_id)
        .first()
    )
    if not request:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Change request not found.",
                }
            },
        )

    # Check access
    role_names = {r.name for r in current_user.roles}
    if "STUDENT" in role_names:
        # Students can only see their own requests
        profile = (
            db.query(ImmigrationProfile)
            .filter(ImmigrationProfile.id == request.immigration_profile_id)
            .first()
        )
        if not profile or profile.student_id != _own_student_id(db, current_user):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "You can only view your own change requests.",
                    }
                },
            )

    return change_request_to_response(db, request)


@router.post(
    "/immigration/change-requests/{request_id}/approve",
    response_model=ImmigrationChangeRequestResponse,
)
def approve_change(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    request_id: uuid.UUID,
    request: Request,
):
    """Approve a change request and update official record (management/admin only)."""
    if not has_permission(current_user, "immigration.review_change"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to approve immigration changes.",
                }
            },
        )

    try:
        change_request = approve_change_request(db, request_id, current_user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(e),
                }
            },
        ) from e

    _audit(
        db,
        action="immigration.change_request.approved",
        actor=current_user,
        entity_id=change_request.id,
        context={"change_type": change_request.change_type},
        request=request,
    )
    _notify_submitter(db, change_request, approved=True, actor=current_user)
    db.commit()

    return change_request_to_response(db, change_request)


@router.post(
    "/immigration/change-requests/{request_id}/reject",
    response_model=ImmigrationChangeRequestResponse,
)
def reject_change(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    request_id: uuid.UUID,
    data: ChangeRequestReview,
    request: Request,
):
    """Reject a change request (management/admin only)."""
    if not has_permission(current_user, "immigration.review_change"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to reject immigration changes.",
                }
            },
        )

    try:
        change_request = reject_change_request(
            db, request_id, current_user.id, data.rejection_reason
        )
    except ValueError as e:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(e),
                }
            },
        ) from e

    _audit(
        db,
        action="immigration.change_request.rejected",
        actor=current_user,
        entity_id=change_request.id,
        # The rejection reason is intentionally omitted: it is free text that
        # may contain personal circumstances.
        context={"change_type": change_request.change_type},
        request=request,
    )
    _notify_submitter(db, change_request, approved=False, actor=current_user)
    db.commit()

    return change_request_to_response(db, change_request)


# --- Immigration Overview ---


@router.get(
    "/students/{student_id}/immigration/cohort",
    response_model=ImmigrationCohortResponse,
)
def student_immigration_cohort(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
):
    """Original-admission cohort context for the student-level banner.

    The response is derived from ``students.original_admission_id`` only. A
    current placement or a later admission episode cannot change it.
    """
    student = _get_student_or_404(db, student_id)
    _check_immigration_access(current_user, student)
    return get_immigration_cohort(db, student.id)


@router.get(
    "/immigration/countries",
    response_model=NationalityDistributionResponse,
)
def immigration_country_distribution(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    response: Response,
    intake_id: uuid.UUID | None = Query(None, description="Original admission intake"),
):
    """Aggregated nationality distribution for the immigration map.

    Administrators and management only. The response contains country totals
    and no student-level fields; intake filtering uses the verified original
    admission intake, never the current placement.
    """
    if not has_permission(current_user, "immigration.view_all"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to view immigration aggregates.",
                }
            },
        )

    response.headers["Cache-Control"] = "private, no-store"
    return get_nationality_distribution(db, intake_id=intake_id)


@router.get(
    "/immigration/overview/export",
)
def export_immigration_overview(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    request: Request,
    status_filter: str | None = Query(None, alias="status"),
    document_type: str | None = Query(None, alias="type"),
    intake_id: uuid.UUID | None = Query(None, description="Original admission intake"),
):
    """Export the same filtered overview as CSV, including the trust column."""
    if not has_permission(current_user, "immigration.view_all"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to export immigration records.",
                }
            },
        )

    settings = get_settings()
    overview = get_immigration_overview(
        db,
        status_filter,
        document_type,
        intake_id=intake_id,
        page=1,
        page_size=settings.MAX_EXPORT_ROWS,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "student_number",
            "student_name",
            "original_admission_intake",
            "verification_status",
            "last_verified_at",
            "placement_intake_academic_only",
            "passport_expiry",
            "passport_status",
            "visa_expiry",
            "visa_status",
            "residence_permit_expiry",
            "residence_permit_status",
        ]
    )
    for item in overview.items:
        writer.writerow(
            [
                _csv_safe(item.student_number),
                _csv_safe(item.student_name),
                _csv_safe(item.original_admission_intake_name),
                _csv_safe(item.verification_status),
                _csv_safe(
                    item.last_verified_at.isoformat(timespec="seconds")
                    if item.last_verified_at
                    else None
                ),
                _csv_safe(item.placement_intake_name),
                _csv_safe(
                    item.passport_expiry_date.isoformat()
                    if item.passport_expiry_date
                    else None
                ),
                _csv_safe(item.passport_status),
                _csv_safe(
                    item.visa_expiry_date.isoformat()
                    if item.visa_expiry_date
                    else None
                ),
                _csv_safe(item.visa_status),
                _csv_safe(
                    item.residence_permit_expiry_date.isoformat()
                    if item.residence_permit_expiry_date
                    else None
                ),
                _csv_safe(item.residence_permit_status),
            ]
        )

    record_audit(
        db,
        action="immigration.overview_exported",
        actor=current_user,
        entity_type="immigration_overview",
        entity_id=current_user.id,
        context={"rows": len(overview.items)},
        request=request,
    )
    db.commit()

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="immigration-overview-{stamp}.csv"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/immigration/overview",
    response_model=ImmigrationOverviewResponse,
)
def immigration_overview(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    status_filter: str | None = Query(
        None,
        alias="status",
        description=(
            "Filter: VALID, EXPIRING_SOON, URGENT, EXPIRED, NOT_PROVIDED"
        ),
    ),
    document_type: str | None = Query(
        None, alias="type", description="Filter: passport, visa, residence_permit"
    ),
    intake_id: uuid.UUID | None = Query(
        None, description="Filter by original admission intake"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    """Immigration overview dashboard for management/admin.

    Shows all active students with immigration status summary.

    Gated on ``immigration.view_all`` rather than ``immigration.view``: every
    student holds the latter for their own record, so reusing it here handed a
    signed-in student the entire cohort's document status. Students are also
    denied explicitly, because a hypothetical future role that holds
    ``immigration.view_all`` without being staff must still not read other
    students' records.
    """
    if not has_permission(current_user, "immigration.view_all"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to view immigration overview.",
                }
            },
        )

    return get_immigration_overview(
        db,
        status_filter,
        document_type,
        intake_id=intake_id,
        page=page,
        page_size=page_size,
    )


# --- Document Upload ---


@router.post(
    "/students/{student_id}/immigration/documents",
    response_model=ImmigrationDocumentUploadResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def upload_immigration_doc(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
    file: UploadFile = File(...),
    document_type: ImmigrationDocumentType = Query(..., description="Document type"),
    notes: str | None = Query(None, description="Optional notes"),
):
    """Upload an immigration document.

    Files are stored in object storage; this endpoint stores metadata only.
    In production, the actual file upload would go to S3/object storage.
    For development, we store the metadata with a simulated storage reference.
    """
    student = _get_student_or_404(db, student_id)
    _check_immigration_access(current_user, student)

    # Check permission
    role_names = {r.name for r in current_user.roles}
    if "STUDENT" in role_names and not has_permission(
        current_user, "documents.upload"
    ):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to upload documents.",
                }
            },
        )
    elif "STUDENT" not in role_names and not has_permission(
        current_user, "immigration.manage_documents"
    ):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to manage immigration documents.",
                }
            },
        )

    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "File name is required.",
                }
            },
        )

    # Read file content for size check
    content = await file.read()
    file_size = len(content)

    # 10MB limit
    if file_size > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "File size exceeds 10MB limit.",
                }
            },
        )

    # Validate file type
    allowed_types = {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/jpg",
    }
    content_type = file.content_type
    if content_type and content_type not in allowed_types:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"File type '{content_type}' not allowed. Use PDF, JPEG, or PNG.",
                }
            },
        )

    # Get or create profile
    profile = get_or_create_immigration_profile(db, student_id)

    # Generate storage reference (in production, this would be an S3 key)
    storage_ref = f"immigration/{student_id}/{document_type.value}/{file.filename}"

    document = upload_immigration_document(
        db,
        immigration_profile_id=profile.id,
        uploaded_by=current_user.id,
        document_type=document_type,
        storage_reference=storage_ref,
        original_filename=file.filename,
        content_type=content_type,
        file_size=file_size,
        notes=notes,
    )

    return ImmigrationDocumentUploadResponse(
        id=document.id,
        document_type=document.document_type,
        original_filename=document.original_filename,
        storage_reference=document.storage_reference,
        content_type=document.content_type,
        file_size=document.file_size,
        created_at=document.created_at,
    )


# --- Expiry reminders ------------------------------------------------------


#: Reminders are an operational immigration task. Reading the cohort and running
#: the reconciliation are Admin/Management acts; a student is told about their
#: own documents through notifications, never through this list.
_REMINDER_ROLES = {"ADMIN", "MANAGEMENT"}


def _require_reminder_staff(current_user: User) -> None:
    roles = {role.name for role in current_user.roles}
    if not (roles & _REMINDER_ROLES):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have access to immigration reminders.",
                }
            },
        )


@router.get("/immigration/reminders", response_model=ImmigrationReminderList)
def list_immigration_reminders(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    status_filter: str = Query("open", alias="status", pattern="^(open|resolved|all)$"),
    document_type: str | None = Query(None, pattern="^(PASSPORT|VISA|RESIDENCE_PERMIT)$"),
    tier: str | None = Query(None, pattern="^(EXPIRED|URGENT|EXPIRING_SOON)$"),
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    """Expiry reminder history, open alerts first."""
    _require_reminder_staff(current_user)
    if not has_permission(current_user, "immigration.view_all"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have access to immigration reminders.",
                }
            },
        )
    return list_reminders(
        db,
        status=status_filter,
        document_type=document_type,
        tier=tier,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.post("/immigration/reminders/run", response_model=ImmigrationReminderRunResult)
def run_immigration_reminders(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    request: Request,
):
    """Reconcile expiry alerts against verified profiles.

    Idempotent by construction: a second run in the same conditions creates
    nothing, because an alert is unique on (profile, document, tier, expiry).
    """
    _require_reminder_staff(current_user)
    if not has_permission(current_user, "immigration.view_all"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have access to immigration reminders.",
                }
            },
        )

    result = run_expiry_reminders(db)
    record_audit(
        db,
        action="immigration.reminders.generated",
        actor=current_user,
        entity_type="immigration_reminder",
        context={
            "evaluated": result["evaluated"],
            "created": result["created"],
            "resolved": result["resolved"],
        },
        request=request,
    )
    db.commit()
    return result


@router.get(
    "/students/{student_id}/immigration/documents",
    response_model=list,
)
def list_immigration_documents(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
):
    """List immigration documents for a student."""
    student = _get_student_or_404(db, student_id)
    _check_immigration_access(current_user, student)

    profile = get_immigration_profile(db, student_id)
    if not profile:
        return []

    from app.schemas.immigration import ImmigrationDocumentResponse

    return [ImmigrationDocumentResponse.model_validate(d) for d in profile.documents]
