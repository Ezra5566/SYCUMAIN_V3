"""Immigration business logic service with expiration calculation and change workflow."""

import contextlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import and_, case, false, func, or_
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import aliased

from app.audit import record_audit
from app.config.settings import get_settings
from app.models.academic import AcademicPeriod
from app.models.admission import AcademicAdmission, AcademicPlacement
from app.models.identity import Student, StudentStatus, User
from app.models.immigration import (
    IMMIGRATION_PROFILE_FIELDS,
    ImmigrationChangeRequest,
    ImmigrationChangeRequestStatus,
    ImmigrationDocument,
    ImmigrationDocumentType,
    ImmigrationProfile,
    ImmigrationProfileVersion,
)
from app.schemas.immigration import (
    CountryStudentCount,
    ImmigrationChangeRequestResponse,
    ImmigrationCohortResponse,
    ImmigrationCohortSummary,
    ImmigrationDocumentResponse,
    ImmigrationImportApplyResponse,
    ImmigrationImportPreviewRecord,
    ImmigrationImportPreviewResponse,
    ImmigrationOverviewItem,
    ImmigrationOverviewResponse,
    ImmigrationProfileResponse,
    ImmigrationProfileStudentView,
    ImmigrationProfileUpdate,
    ImmigrationProfileVersionResponse,
    ImmigrationUntrustedCounts,
    NationalityDistributionResponse,
)
from app.services.countries import country_code

# Expiry tiers. The window boundaries are a single source of truth shared
# with the student-directory filter in app.services.student, so the two can
# never disagree about which bucket a document falls into.
WARNING_DAYS_90 = 90
WARNING_DAYS_30 = 30

# Ordered from most to least urgent. Used to pick the worst document on a
# profile, and to bucket the overview.
STATUS_SEVERITY = ("EXPIRED", "URGENT", "EXPIRING_SOON", "VALID")


def calculate_document_status(
    expiry_date: date | None,
    today: date | None = None,
) -> tuple[str | None, int | None]:
    """Calculate derived status and days remaining for an immigration document.

    The status is always derived from the expiry date and the current date — it
    is never stored — so a countdown can never go stale.

    Tiers:
        ``EXPIRED``        expiry is before today
        ``URGENT``         expiry is within ``WARNING_DAYS_30`` days
        ``EXPIRING_SOON``  expiry is within ``WARNING_DAYS_90`` days
        ``VALID``          expiry is further out
        ``NOT_PROVIDED``   no expiry date recorded

    Returns:
        (status, days_remaining). ``days_remaining`` is negative once expired.
    """
    if expiry_date is None:
        return ("NOT_PROVIDED", None)

    if today is None:
        today = date.today()

    days_remaining = (expiry_date - today).days

    if days_remaining < 0:
        return ("EXPIRED", days_remaining)
    if days_remaining <= WARNING_DAYS_30:
        return ("URGENT", days_remaining)
    if days_remaining <= WARNING_DAYS_90:
        return ("EXPIRING_SOON", days_remaining)
    return ("VALID", days_remaining)


def worst_status(statuses: list[str | None]) -> str:
    """Reduce several document statuses to the most urgent one.

    A student with a valid visa but an expired passport is ``EXPIRED``: the
    most urgent document defines the person's position.
    """
    for status in STATUS_SEVERITY:
        if status in statuses:
            return status
    return "NOT_PROVIDED"


def _profile_snapshot(profile: ImmigrationProfile) -> dict:
    """JSON-safe snapshot of every official (non-derived) field."""
    return {
        field: (
            getattr(profile, field).isoformat()
            if isinstance(getattr(profile, field), date)
            else getattr(profile, field)
        )
        for field in IMMIGRATION_PROFILE_FIELDS
    }


def _record_version(
    db: DBSession,
    profile: ImmigrationProfile,
    previous: dict | None,
    new: dict,
    *,
    actor_id: uuid.UUID | None,
    reason: str | None,
    change_request_id: uuid.UUID | None = None,
) -> ImmigrationProfileVersion | None:
    """Append a version when at least one official value changed."""
    changed = sorted(
        field
        for field in IMMIGRATION_PROFILE_FIELDS
        if (previous or {}).get(field) != new.get(field)
    )
    if not changed:
        return None

    last_number = (
        db.query(func.max(ImmigrationProfileVersion.version_number))
        .filter(ImmigrationProfileVersion.immigration_profile_id == profile.id)
        .scalar()
        or 0
    )
    version = ImmigrationProfileVersion(
        immigration_profile_id=profile.id,
        version_number=last_number + 1,
        previous_data=json.dumps(previous) if previous is not None else None,
        new_data=json.dumps(new),
        changed_fields=json.dumps(changed),
        changed_by_id=actor_id,
        change_reason=reason,
        change_request_id=change_request_id,
    )
    db.add(version)
    return version


def get_or_create_immigration_profile(
    db: DBSession, student_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> ImmigrationProfile:
    """Get existing or create a new immigration profile for a student."""
    profile = (
        db.query(ImmigrationProfile)
        .filter(ImmigrationProfile.student_id == student_id)
        .first()
    )
    if not profile:
        profile = ImmigrationProfile(student_id=student_id)
        db.add(profile)
        db.flush()
        _record_version(
            db,
            profile,
            None,
            _profile_snapshot(profile),
            actor_id=actor_id,
            reason="Profile created",
        )
        db.commit()
        db.refresh(profile)
    return profile


def get_immigration_profile(
    db: DBSession, student_id: uuid.UUID
) -> ImmigrationProfile | None:
    """Get immigration profile for a student."""
    return (
        db.query(ImmigrationProfile)
        .filter(ImmigrationProfile.student_id == student_id)
        .first()
    )


def update_immigration_profile(
    db: DBSession,
    profile: ImmigrationProfile,
    data: dict,
    *,
    actor_id: uuid.UUID | None = None,
    reason: str | None = None,
    data_source: str = "MANAGEMENT",
    request: object | None = None,
) -> ImmigrationProfile:
    """Update profile fields while preserving the previous official values."""
    # Lock the profile so version numbers cannot collide and a concurrent
    # approval cannot interleave with a direct correction.
    profile = (
        db.query(ImmigrationProfile)
        .filter(ImmigrationProfile.id == profile.id)
        .with_for_update()
        .first()
    )
    if profile is None:
        raise ValueError("Immigration profile not found")

    previous = _profile_snapshot(profile)
    for key, value in data.items():
        if value is not None and key in IMMIGRATION_PROFILE_FIELDS:
            setattr(profile, key, value)
    new = _profile_snapshot(profile)
    # A direct correction is an explicit authorized staff act, so it carries
    # verification rather than leaving the record in an ambiguous state.
    profile.data_source = data_source
    profile.verification_status = "VERIFIED"
    profile.verified_at = datetime.now(UTC)
    profile.verified_by_id = actor_id
    version = _record_version(
        db,
        profile,
        previous,
        new,
        actor_id=actor_id,
        reason=reason or "Direct correction by staff",
    )

    # A passport or permit correction is a security-relevant administrative act,
    # so it belongs in the audit trail as well as in the profile's own version
    # history. The event is staged on *this* transaction and committed with the
    # change, so a failed write cannot leave an audit entry claiming a
    # correction that did not happen. Only changed field *names* are recorded:
    # the values live in ``immigration_profile_versions``, and identifiers such
    # as ``passport_number`` are on the audit redaction list on purpose.
    if version is not None:
        record_audit(
            db,
            action="immigration.profile.updated",
            actor_id=actor_id,
            entity_type="immigration_profile",
            entity_id=profile.id,
            context={
                "student_id": str(profile.student_id),
                "version_number": version.version_number,
                "fields": json.loads(version.changed_fields or "[]"),
                "reason": reason,
                "data_source": data_source,
            },
            request=request,
        )

    db.commit()
    db.refresh(profile)
    return profile


def profile_to_response(
    profile: ImmigrationProfile,
    student_id: uuid.UUID | None = None,
) -> ImmigrationProfileResponse:
    """Convert profile model to response schema with derived statuses."""
    today = date.today()

    passport_status, passport_days = calculate_document_status(
        profile.passport_expiry_date, today
    )
    visa_status, visa_days = calculate_document_status(
        profile.visa_expiry_date, today
    )
    rp_status, rp_days = calculate_document_status(
        profile.residence_permit_expiry_date, today
    )

    return ImmigrationProfileResponse(
        id=profile.id,
        student_id=profile.student_id,
        passport_number=profile.passport_number,
        passport_issuing_country=profile.passport_issuing_country,
        passport_issue_date=profile.passport_issue_date,
        passport_expiry_date=profile.passport_expiry_date,
        passport_name_as_shown=profile.passport_name_as_shown,
        visa_type=profile.visa_type,
        visa_number=profile.visa_number,
        visa_issue_date=profile.visa_issue_date,
        visa_expiry_date=profile.visa_expiry_date,
        visa_entries=profile.visa_entries,
        visa_issuing_authority=profile.visa_issuing_authority,
        residence_permit_number=profile.residence_permit_number,
        residence_permit_issue_date=profile.residence_permit_issue_date,
        residence_permit_expiry_date=profile.residence_permit_expiry_date,
        residence_permit_issuing_authority=profile.residence_permit_issuing_authority,
        passport_status=passport_status,
        passport_days_remaining=passport_days,
        visa_status=visa_status,
        visa_days_remaining=visa_days,
        residence_permit_status=rp_status,
        residence_permit_days_remaining=rp_days,
        documents=[
            ImmigrationDocumentResponse.model_validate(d)
            for d in profile.documents
        ],
        data_source=profile.data_source,
        verification_status=profile.verification_status,
        source_reference=profile.source_reference,
        verified_at=profile.verified_at,
        verified_by_id=profile.verified_by_id,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def profile_to_student_view(
    profile: ImmigrationProfile,
) -> ImmigrationProfileStudentView:
    """Convert profile to limited student view (same fields, fewer documents)."""
    today = date.today()

    passport_status, passport_days = calculate_document_status(
        profile.passport_expiry_date, today
    )
    visa_status, visa_days = calculate_document_status(
        profile.visa_expiry_date, today
    )
    rp_status, rp_days = calculate_document_status(
        profile.residence_permit_expiry_date, today
    )

    return ImmigrationProfileStudentView(
        id=profile.id,
        student_id=profile.student_id,
        passport_number=profile.passport_number,
        passport_issuing_country=profile.passport_issuing_country,
        passport_issue_date=profile.passport_issue_date,
        passport_expiry_date=profile.passport_expiry_date,
        passport_name_as_shown=profile.passport_name_as_shown,
        visa_type=profile.visa_type,
        visa_number=profile.visa_number,
        visa_issue_date=profile.visa_issue_date,
        visa_expiry_date=profile.visa_expiry_date,
        visa_entries=profile.visa_entries,
        visa_issuing_authority=profile.visa_issuing_authority,
        residence_permit_number=profile.residence_permit_number,
        residence_permit_issue_date=profile.residence_permit_issue_date,
        residence_permit_expiry_date=profile.residence_permit_expiry_date,
        residence_permit_issuing_authority=profile.residence_permit_issuing_authority,
        passport_status=passport_status,
        passport_days_remaining=passport_days,
        visa_status=visa_status,
        visa_days_remaining=visa_days,
        residence_permit_status=rp_status,
        residence_permit_days_remaining=rp_days,
        document_count=len(profile.documents),
        verification_status=profile.verification_status,
        updated_at=profile.updated_at,
        created_at=profile.created_at,
    )


# --- Change Request Workflow ---


def submit_change_request(
    db: DBSession,
    immigration_profile_id: uuid.UUID,
    submitted_by: uuid.UUID,
    change_type: str,
    proposed_data: dict,
) -> ImmigrationChangeRequest:
    """Submit a change request (student workflow)."""
    profile = (
        db.query(ImmigrationProfile)
        .filter(ImmigrationProfile.id == immigration_profile_id)
        .first()
    )
    if not profile:
        raise ValueError("Immigration profile not found")

    # Build current data snapshot
    current_snapshot = {}
    for field_name in proposed_data:
        if hasattr(profile, field_name):
            val = getattr(profile, field_name)
            current_snapshot[field_name] = (
                val.isoformat() if isinstance(val, date) else str(val) if val is not None else None
            )

    request = ImmigrationChangeRequest(
        immigration_profile_id=immigration_profile_id,
        submitted_by=submitted_by,
        change_type=change_type,
        proposed_data=json.dumps(proposed_data),
        current_data_snapshot=json.dumps(current_snapshot) if current_snapshot else None,
        status=ImmigrationChangeRequestStatus.PENDING,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def approve_change_request(
    db: DBSession,
    request_id: uuid.UUID,
    reviewed_by: uuid.UUID,
) -> ImmigrationChangeRequest:
    """Approve a change request and update the official record atomically."""
    request = (
        db.query(ImmigrationChangeRequest)
        .filter(
            and_(
                ImmigrationChangeRequest.id == request_id,
                ImmigrationChangeRequest.status == ImmigrationChangeRequestStatus.PENDING,
            )
        )
        .with_for_update()
        .first()
    )
    if not request:
        raise ValueError("Pending change request not found")

    profile = (
        db.query(ImmigrationProfile)
        .filter(ImmigrationProfile.id == request.immigration_profile_id)
        .with_for_update()
        .first()
    )
    if not profile:
        raise ValueError("Immigration profile not found")

    previous = _profile_snapshot(profile)

    # Apply changes to official record
    proposed = json.loads(request.proposed_data)
    for field_name, value in proposed.items():
        if field_name in IMMIGRATION_PROFILE_FIELDS:
            # Convert date strings back to date objects
            if value and field_name.endswith("_date"):
                with contextlib.suppress(ValueError, TypeError):
                    value = date.fromisoformat(value)
            setattr(profile, field_name, value)

    # Update request status
    request.status = ImmigrationChangeRequestStatus.APPROVED
    request.reviewed_by = reviewed_by
    request.reviewed_at = datetime.now(UTC)
    profile.data_source = "STUDENT"
    profile.verification_status = "VERIFIED"
    profile.verified_at = datetime.now(UTC)
    profile.verified_by_id = reviewed_by

    _record_version(
        db,
        profile,
        previous,
        _profile_snapshot(profile),
        actor_id=reviewed_by,
        reason=f"Approved {request.change_type} change request",
        change_request_id=request.id,
    )

    db.commit()
    db.refresh(request)
    return request


def reject_change_request(
    db: DBSession,
    request_id: uuid.UUID,
    reviewed_by: uuid.UUID,
    rejection_reason: str | None = None,
) -> ImmigrationChangeRequest:
    """Reject a change request (official data unchanged)."""
    request = (
        db.query(ImmigrationChangeRequest)
        .filter(
            and_(
                ImmigrationChangeRequest.id == request_id,
                ImmigrationChangeRequest.status == ImmigrationChangeRequestStatus.PENDING,
            )
        )
        .first()
    )
    if not request:
        raise ValueError("Pending change request not found")

    request.status = ImmigrationChangeRequestStatus.REJECTED
    request.reviewed_by = reviewed_by
    request.reviewed_at = datetime.now(UTC)
    request.rejection_reason = rejection_reason

    db.commit()
    db.refresh(request)
    return request


def list_profile_versions(
    db: DBSession, profile_id: uuid.UUID
) -> list[ImmigrationProfileVersionResponse]:
    """Return immutable history newest-first, with actor names."""
    versions = (
        db.query(ImmigrationProfileVersion)
        .filter(ImmigrationProfileVersion.immigration_profile_id == profile_id)
        .order_by(ImmigrationProfileVersion.version_number.desc())
        .all()
    )
    result = []
    for version in versions:
        actor = (
            db.query(User).filter(User.id == version.changed_by_id).first()
            if version.changed_by_id
            else None
        )
        result.append(
            ImmigrationProfileVersionResponse(
                id=version.id,
                immigration_profile_id=version.immigration_profile_id,
                version_number=version.version_number,
                previous_data=json.loads(version.previous_data)
                if version.previous_data
                else None,
                new_data=json.loads(version.new_data),
                changed_fields=json.loads(version.changed_fields),
                changed_by_id=version.changed_by_id,
                changed_by_name=actor.full_name if actor else None,
                changed_at=version.changed_at,
                change_reason=version.change_reason,
                change_request_id=version.change_request_id,
            )
        )
    return result


def change_request_to_response(
    db: DBSession, request: ImmigrationChangeRequest
) -> ImmigrationChangeRequestResponse:
    """Convert change request model to response schema."""
    # Get student info through the profile
    profile = (
        db.query(ImmigrationProfile)
        .filter(ImmigrationProfile.id == request.immigration_profile_id)
        .first()
    )
    student_id = profile.student_id if profile else None

    student = None
    if student_id:
        student = db.query(Student).filter(Student.id == student_id).first()

    submitter = db.query(User).filter(User.id == request.submitted_by).first()
    reviewer = (
        db.query(User).filter(User.id == request.reviewed_by).first()
        if request.reviewed_by
        else None
    )

    return ImmigrationChangeRequestResponse(
        id=request.id,
        immigration_profile_id=request.immigration_profile_id,
        student_id=student_id,
        student_name=f"{student.first_name} {student.last_name}" if student else None,
        submitted_by=request.submitted_by,
        submitter_name=submitter.full_name if submitter else None,
        reviewed_by=request.reviewed_by,
        reviewer_name=reviewer.full_name if reviewer else None,
        change_type=request.change_type,
        proposed_data=json.loads(request.proposed_data),
        current_data_snapshot=json.loads(request.current_data_snapshot)
        if request.current_data_snapshot
        else None,
        status=request.status,
        rejection_reason=request.rejection_reason,
        submitted_at=request.submitted_at,
        reviewed_at=request.reviewed_at,
    )


# --- Immigration Overview ---


# --- Immigration Overview ---

_TRUST_REASON_FIELDS = {
    "UNVERIFIED": "unverified",
    "REVOKED": "revoked",
    "DISPUTED": "disputed",
    "NO_ADMISSION": "no_admission",
}


def _cohort_source() -> str:
    """Read the read-only Phase 6 cohort switch."""
    return get_settings().ADMISSION_COHORT_SOURCE.upper()


def _base_student_query(db: DBSession):
    """Active students plus original admission and its intake.

    Placement is deliberately not joined here. Cohort attribution must never
    depend on where a student is currently placed.
    """
    return (
        db.query(Student, AcademicAdmission, AcademicPeriod, User, ImmigrationProfile)
        .outerjoin(
            AcademicAdmission,
            Student.original_admission_id == AcademicAdmission.id,
        )
        .outerjoin(
            AcademicPeriod,
            AcademicAdmission.admission_intake_id == AcademicPeriod.id,
        )
        .outerjoin(User, Student.user_id == User.id)
        .outerjoin(ImmigrationProfile, ImmigrationProfile.student_id == Student.id)
        .filter(Student.status == StudentStatus.ACTIVE.value)
    )


def _status_columns(document_type: str | None):
    """The document date columns considered by a status filter."""
    mapping = {
        "passport": ImmigrationProfile.passport_expiry_date,
        "visa": ImmigrationProfile.visa_expiry_date,
        "residence_permit": ImmigrationProfile.residence_permit_expiry_date,
    }
    if document_type in mapping:
        return [mapping[document_type]]
    return list(mapping.values())


def _status_condition(
    document_type: str | None, wanted_status: str, today: date
):
    """SQL equivalent of calculate_document_status + worst_status.

    Keeping this predicate in SQL is what makes status-filtered pagination
    stable: the database selects the page instead of loading every active
    student and filtering in Python.
    """
    columns = _status_columns(document_type)
    has_any = or_(*[column.is_not(None) for column in columns])
    expired = or_(*[column < today for column in columns])
    urgent = and_(
        ~expired,
        or_(
            *[
                and_(column >= today, column <= today + timedelta(days=WARNING_DAYS_30))
                for column in columns
            ]
        ),
    )
    expiring = and_(
        ~expired,
        ~urgent,
        or_(
            *[
                and_(
                    column > today + timedelta(days=WARNING_DAYS_30),
                    column <= today + timedelta(days=WARNING_DAYS_90),
                )
                for column in columns
            ]
        ),
    )
    conditions = {
        "EXPIRED": expired,
        "URGENT": urgent,
        "EXPIRING_SOON": expiring,
        "VALID": and_(has_any, ~expired, ~urgent, ~expiring),
        "NOT_PROVIDED": ~has_any,
    }
    return conditions.get(wanted_status, false())


def _filtered_rows_query(
    db: DBSession,
    *,
    source: str,
    status_filter: str | None,
    document_type: str | None,
    intake_id: uuid.UUID | None,
    today: date,
):
    query = _base_student_query(db)
    if source == "POINTER" and intake_id is not None:
        # An intake filter is an original-admission-intake filter. It can only
        # match verified named cohorts; untrusted students have no cohort.
        query = query.filter(
            AcademicAdmission.verification_status == "VERIFIED",
            AcademicAdmission.admission_intake_id == intake_id,
        )
    if status_filter:
        query = query.filter(
            _status_condition(document_type, status_filter, today)
        )
    return query


def _cohort_summaries(
    db: DBSession, *, source: str, intake_id: uuid.UUID | None
) -> tuple[list[ImmigrationCohortSummary], ImmigrationUntrustedCounts, int]:
    """Named cohorts, untrusted reasons and active total, all in SQL."""
    if source != "POINTER":
        total = (
            db.query(func.count(Student.id))
            .filter(Student.status == StudentStatus.ACTIVE.value)
            .scalar()
            or 0
        )
        return [], ImmigrationUntrustedCounts(), total

    cohort_query = (
        db.query(
            AcademicPeriod.id,
            AcademicPeriod.name,
            AcademicPeriod.code,
            AcademicPeriod.start_date,
            func.count(Student.id),
        )
        .join(
            AcademicAdmission,
            Student.original_admission_id == AcademicAdmission.id,
        )
        .join(
            AcademicPeriod,
            AcademicAdmission.admission_intake_id == AcademicPeriod.id,
        )
        .filter(
            Student.status == StudentStatus.ACTIVE.value,
            AcademicAdmission.verification_status == "VERIFIED",
        )
    )
    if intake_id is not None:
        cohort_query = cohort_query.filter(
            AcademicAdmission.admission_intake_id == intake_id
        )
    cohort_rows = (
        cohort_query.group_by(
            AcademicPeriod.id,
            AcademicPeriod.name,
            AcademicPeriod.code,
            AcademicPeriod.start_date,
        )
        .order_by(AcademicPeriod.start_date.desc(), AcademicPeriod.name)
        .all()
    )
    cohorts = [
        ImmigrationCohortSummary(
            intake_id=row[0],
            intake_name=row[1],
            intake_code=row[2],
            start_date=row[3],
            count=row[4],
        )
        for row in cohort_rows
    ]

    total_query = (
        db.query(func.count(Student.id))
        .filter(Student.status == StudentStatus.ACTIVE.value)
    )
    if intake_id is not None:
        total_query = (
            total_query.join(
                AcademicAdmission,
                Student.original_admission_id == AcademicAdmission.id,
            )
            .filter(
                AcademicAdmission.verification_status == "VERIFIED",
                AcademicAdmission.admission_intake_id == intake_id,
            )
        )
    total_students = total_query.scalar() or 0

    untrusted = ImmigrationUntrustedCounts()
    if intake_id is None:
        reason = case(
            (AcademicAdmission.id.is_(None), "NO_ADMISSION"),
            else_=AcademicAdmission.verification_status,
        )
        reason_rows = (
            db.query(reason, func.count(Student.id))
            .outerjoin(
                AcademicAdmission,
                Student.original_admission_id == AcademicAdmission.id,
            )
            .filter(
                Student.status == StudentStatus.ACTIVE.value,
                or_(
                    AcademicAdmission.id.is_(None),
                    AcademicAdmission.verification_status != "VERIFIED",
                ),
            )
            .group_by(reason)
            .all()
        )
        for reason_value, count in reason_rows:
            untrusted.total += count
            field = _TRUST_REASON_FIELDS.get(reason_value)
            if field is not None:
                setattr(untrusted, field, count)

    return cohorts, untrusted, total_students


def _pending_count_map(db: DBSession, profile_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not profile_ids:
        return {}
    rows = (
        db.query(
            ImmigrationChangeRequest.immigration_profile_id,
            func.count(ImmigrationChangeRequest.id),
        )
        .filter(
            ImmigrationChangeRequest.immigration_profile_id.in_(profile_ids),
            ImmigrationChangeRequest.status
            == ImmigrationChangeRequestStatus.PENDING,
        )
        .group_by(ImmigrationChangeRequest.immigration_profile_id)
        .all()
    )
    return {row[0]: row[1] for row in rows}


def _placement_map(db: DBSession, student_ids: list[uuid.UUID]):
    if not student_ids:
        return {}
    period = aliased(AcademicPeriod)
    rows = (
        db.query(AcademicPlacement.student_id, period)
        .join(period, AcademicPlacement.academic_period_id == period.id)
        .filter(
            AcademicPlacement.student_id.in_(student_ids),
            AcademicPlacement.ended_at.is_(None),
        )
        .all()
    )
    return dict(rows)


def _overview_items(
    db: DBSession,
    rows,
    *,
    source: str,
    today: date,
) -> list[ImmigrationOverviewItem]:
    student_ids = [row[0].id for row in rows]
    placement_by_student = _placement_map(db, student_ids)
    profile_ids = [row[4].id for row in rows if row[4] is not None]
    pending_by_profile = _pending_count_map(db, profile_ids)

    items: list[ImmigrationOverviewItem] = []
    for student, admission, intake, user, profile in rows:
        student_name = (
            user.full_name if user else f"{student.first_name} {student.last_name}"
        )
        passport_status, passport_days = (None, None)
        visa_status, visa_days = (None, None)
        rp_status, rp_days = (None, None)
        passport_expiry = None
        visa_expiry = None
        rp_expiry = None
        visa_type = None
        pending = 0
        if profile is not None:
            passport_status, passport_days = calculate_document_status(
                profile.passport_expiry_date, today
            )
            visa_status, visa_days = calculate_document_status(
                profile.visa_expiry_date, today
            )
            rp_status, rp_days = calculate_document_status(
                profile.residence_permit_expiry_date, today
            )
            passport_expiry = profile.passport_expiry_date
            visa_expiry = profile.visa_expiry_date
            rp_expiry = profile.residence_permit_expiry_date
            visa_type = profile.visa_type
            pending = pending_by_profile.get(profile.id, 0)

        placement_period = placement_by_student.get(student.id)
        trusted = (
            source == "POINTER"
            and admission is not None
            and admission.verification_status == "VERIFIED"
        )
        cohort_admission = admission if trusted else None
        cohort_intake = intake if trusted else None
        verification_status = None
        if source == "POINTER":
            verification_status = (
                admission.verification_status if admission is not None else "NO_ADMISSION"
            )

        items.append(
            ImmigrationOverviewItem(
                student_id=student.id,
                student_name=student_name,
                student_number=student.student_id,
                original_admission_intake_id=(
                    cohort_intake.id if cohort_intake is not None else None
                ),
                original_admission_intake_name=(
                    cohort_intake.name if cohort_intake is not None else None
                ),
                original_admission_intake_start_date=(
                    cohort_intake.start_date if cohort_intake is not None else None
                ),
                verification_status=verification_status,
                last_verified_at=(
                    cohort_admission.verified_at
                    if cohort_admission is not None
                    else None
                ),
                placement_intake_id=(
                    placement_period.id if placement_period is not None else None
                ),
                placement_intake_name=(
                    placement_period.name if placement_period is not None else None
                ),
                passport_expiry_date=passport_expiry,
                passport_status=passport_status,
                passport_days_remaining=passport_days,
                visa_type=visa_type,
                visa_expiry_date=visa_expiry,
                visa_status=visa_status,
                visa_days_remaining=visa_days,
                residence_permit_expiry_date=rp_expiry,
                residence_permit_status=rp_status,
                residence_permit_days_remaining=rp_days,
                pending_requests_count=pending,
            )
        )
    return items


def get_nationality_distribution(
    db: DBSession,
    *,
    intake_id: uuid.UUID | None = None,
) -> NationalityDistributionResponse:
    """Aggregate active students by ISO country code.

    This is the only source for the immigration map. It deliberately selects
    two columns — nationality and a count — and never a student identifier.
    The intake filter follows the original-admission cohort basis and only
    includes verified admissions.
    """
    query = db.query(Student.nationality, func.count(Student.id)).filter(
        Student.status == StudentStatus.ACTIVE.value
    )
    if intake_id is not None:
        query = (
            query.join(
                AcademicAdmission,
                Student.original_admission_id == AcademicAdmission.id,
            )
            .filter(
                AcademicAdmission.verification_status == "VERIFIED",
                AcademicAdmission.admission_intake_id == intake_id,
            )
            .group_by(Student.nationality)
        )
    else:
        query = query.group_by(Student.nationality)

    counts: dict[str, int] = {}
    total = 0
    missing = 0
    unmapped = 0
    for value, count in query.all():
        total += count
        if value is None or not value.strip():
            missing += count
            continue
        code = country_code(value)
        if code is None:
            unmapped += count
            continue
        counts[code] = counts.get(code, 0) + count

    countries = [
        CountryStudentCount(code=code, count=count)
        for code, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    return NationalityDistributionResponse(
        total_students=total,
        mapped_students=sum(counts.values()),
        missing_country_count=missing,
        unmapped_country_count=unmapped,
        countries=countries,
    )


def get_immigration_overview(
    db: DBSession,
    status_filter: str | None = None,
    document_type: str | None = None,
    *,
    intake_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 25,
) -> ImmigrationOverviewResponse:
    """Immigration overview over the original-admission cohort basis.

    In POINTER mode every named cohort joins
    ``students.original_admission_id -> academic_admissions.admission_intake_id``.
    Placement rows are read only to display the academic placement intake.
    In LEGACY mode the pre-Phase-6 population (all active students) is kept and
    the additive cohort fields remain empty/null.
    """
    source = _cohort_source()
    wanted_status = status_filter.strip().upper() if status_filter else None
    wanted_doc = document_type.strip().lower() if document_type else None
    today = date.today()

    base = _filtered_rows_query(
        db,
        source=source,
        status_filter=None,
        document_type=wanted_doc,
        intake_id=intake_id,
        today=today,
    )
    filtered = _filtered_rows_query(
        db,
        source=source,
        status_filter=wanted_status,
        document_type=wanted_doc,
        intake_id=intake_id,
        today=today,
    )
    total = filtered.count()
    rows = (
        filtered.order_by(Student.last_name, Student.first_name, Student.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    status_counts = {
        status: base.filter(_status_condition(wanted_doc, status, today)).count()
        for status in ("VALID", "EXPIRING_SOON", "URGENT", "EXPIRED", "NOT_PROVIDED")
    }
    cohorts, untrusted, total_students = _cohort_summaries(
        db, source=source, intake_id=intake_id
    )

    scope_ids = base.with_entities(Student.id).subquery()
    pending_total = (
        db.query(func.count(ImmigrationChangeRequest.id))
        .join(
            ImmigrationProfile,
            ImmigrationChangeRequest.immigration_profile_id == ImmigrationProfile.id,
        )
        .filter(
            ImmigrationProfile.student_id.in_(scope_ids.select()),
            ImmigrationChangeRequest.status
            == ImmigrationChangeRequestStatus.PENDING,
        )
        .scalar()
        or 0
    )

    return ImmigrationOverviewResponse(
        items=_overview_items(db, rows, source=source, today=today),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size if page_size else 0,
        total_students=total_students,
        valid_count=status_counts["VALID"],
        expiring_count=status_counts["EXPIRING_SOON"],
        urgent_count=status_counts["URGENT"],
        expired_count=status_counts["EXPIRED"],
        no_data_count=status_counts["NOT_PROVIDED"],
        pending_requests_count=pending_total,
        cohorts=cohorts,
        untrusted=untrusted,
    )


def get_immigration_cohort_rollup(db: DBSession):
    """Shared read-only rollup for the overview and the reports page."""
    source = _cohort_source()
    cohorts, untrusted, total = _cohort_summaries(
        db, source=source, intake_id=None
    )
    return source, cohorts, untrusted, total


def get_immigration_cohort(
    db: DBSession, student_id: uuid.UUID
) -> ImmigrationCohortResponse:
    """Original-admission cohort context for one student.

    This view is independent of placement and of later admission episodes.
    """
    student = db.get(Student, student_id)
    if student is None:
        raise ValueError("STUDENT_NOT_FOUND")
    admission = (
        db.get(AcademicAdmission, student.original_admission_id)
        if student.original_admission_id
        else None
    )
    intake = (
        db.get(AcademicPeriod, admission.admission_intake_id)
        if admission is not None
        else None
    )
    placement_period = (
        db.query(AcademicPeriod)
        .join(AcademicPlacement, AcademicPlacement.academic_period_id == AcademicPeriod.id)
        .filter(
            AcademicPlacement.student_id == student.id,
            AcademicPlacement.ended_at.is_(None),
        )
        .first()
    )

    confirmer_ids = {
        value
        for value in (
            admission.management_confirmed_by_id if admission else None,
            admission.admin_confirmed_by_id if admission else None,
            admission.management_revoked_by_id if admission else None,
            admission.admin_revoked_by_id if admission else None,
        )
        if value is not None
    }
    names = (
        dict(
            db.query(User.id, User.full_name)
            .filter(User.id.in_(confirmer_ids))
            .all()
        )
        if confirmer_ids
        else {}
    )
    management_name = names.get(admission.management_confirmed_by_id) if admission else None
    admin_name = names.get(admission.admin_confirmed_by_id) if admission else None

    confirmations = []
    if admission is not None:
        if admission.management_confirmed_at is not None:
            confirmations.append((admission.management_confirmed_at, management_name))
        if admission.admin_confirmed_at is not None:
            confirmations.append((admission.admin_confirmed_at, admin_name))
    last_confirmer_name = None
    last_confirmed_at = None
    if confirmations:
        last_confirmed_at, last_confirmer_name = max(confirmations, key=lambda row: row[0])

    revocations = []
    if admission is not None:
        if admission.management_revoked_at is not None:
            revocations.append(
                (
                    admission.management_revoked_at,
                    names.get(admission.management_revoked_by_id),
                    admission.management_revocation_reason,
                )
            )
        if admission.admin_revoked_at is not None:
            revocations.append(
                (
                    admission.admin_revoked_at,
                    names.get(admission.admin_revoked_by_id),
                    admission.admin_revocation_reason,
                )
            )
    revoked_at = None
    revoked_by_name = None
    revocation_reason = None
    if revocations:
        revoked_at, revoked_by_name, revocation_reason = max(
            revocations, key=lambda row: row[0]
        )

    return ImmigrationCohortResponse(
        student_id=student.id,
        original_admission_id=student.original_admission_id,
        original_admission_intake_id=(intake.id if intake else None),
        original_admission_intake_name=(intake.name if intake else None),
        original_admission_intake_code=(intake.code if intake else None),
        original_admission_intake_start_date=(intake.start_date if intake else None),
        verification_status=(
            admission.verification_status if admission is not None else "NO_ADMISSION"
        ),
        verified_at=(admission.verified_at if admission else None),
        management_confirmer_name=management_name,
        management_confirmed_at=(admission.management_confirmed_at if admission else None),
        management_revoked_at=(admission.management_revoked_at if admission else None),
        management_revocation_reason=(
            admission.management_revocation_reason if admission else None
        ),
        admin_confirmer_name=admin_name,
        admin_confirmed_at=(admission.admin_confirmed_at if admission else None),
        admin_revoked_at=(admission.admin_revoked_at if admission else None),
        admin_revocation_reason=(admission.admin_revocation_reason if admission else None),
        last_confirmer_name=last_confirmer_name,
        last_confirmed_at=last_confirmed_at,
        revoked_by_name=revoked_by_name,
        revoked_at=revoked_at,
        revocation_reason=revocation_reason,
        placement_intake_id=(placement_period.id if placement_period else None),
        placement_intake_name=(placement_period.name if placement_period else None),
    )


# --- Document Management ---


def import_immigration_profile(
    db: DBSession,
    *,
    student_id: uuid.UUID,
    data: dict,
    source_reference: str | None,
    actor_id: uuid.UUID | None,
) -> tuple[ImmigrationProfile, list[str], bool]:
    """Import values without promoting them to verified official data.

    Returns the profile, the fields that were *not* applied because the profile
    already holds a different value, and whether anything changed. The third
    value matters for reporting: re-importing an identical row is a no-op, and
    saying "applied: 1" for a row that changed nothing is a false success.
    """
    profile = get_or_create_immigration_profile(db, student_id, actor_id=actor_id)
    previous = _profile_snapshot(profile)
    conflicts: list[str] = []
    applied = False

    for field, value in data.items():
        if field not in IMMIGRATION_PROFILE_FIELDS or value is None:
            continue
        existing = getattr(profile, field)
        # Any differing existing value is a conflict, verified or not. An
        # import fills blanks; it never replaces what the institution already
        # recorded, and it never does so silently.
        if existing is not None and existing != value:
            conflicts.append(field)
            continue
        if existing is None:
            setattr(profile, field, value)
            applied = True

    if applied:
        profile.data_source = "IMPORT"
        profile.source_reference = source_reference
        profile.verification_status = "UNVERIFIED"
        profile.verified_at = None
        profile.verified_by_id = None
        _record_version(
            db,
            profile,
            previous,
            _profile_snapshot(profile),
            actor_id=actor_id,
            reason=f"Imported from {source_reference or 'external source'}; unverified",
        )
    db.commit()
    db.refresh(profile)
    return profile, sorted(set(conflicts)), applied


def resolve_student_reference(db: DBSession, reference: str) -> Student | None:
    """Resolve an import reference to a student.

    The student number is tried first because it is the stable identifier the
    campus actually knows; the record UUID is accepted as a fallback so an
    existing caller that already holds one keeps working.
    """
    value = (reference or "").strip()
    if not value:
        return None
    student = db.query(Student).filter(Student.student_id == value).first()
    if student is not None:
        return student
    try:
        record_id = uuid.UUID(value)
    except ValueError:
        return None
    return db.query(Student).filter(Student.id == record_id).first()


def _import_values(values: dict) -> tuple[dict, list[str]]:
    """Validate an import row through the existing profile schema.

    Extra keys are rejected rather than ignored, so an import cannot smuggle
    ``verification_status``, ownership or timestamps into the profile.
    """
    try:
        parsed = ImmigrationProfileUpdate.model_validate(values)
    except ValidationError as exc:
        return {}, [str(error["msg"]) for error in exc.errors()]
    data = parsed.model_dump(exclude_unset=True, exclude={"change_reason"})
    return {key: value for key, value in data.items() if key in IMMIGRATION_PROFILE_FIELDS}, []


def _json_value(value):
    return value.isoformat() if isinstance(value, date) else value


def preview_immigration_import(
    db: DBSession, records: list
) -> ImmigrationImportPreviewResponse:
    """Validate and preview an import without changing any stored record."""
    previews: list[ImmigrationImportPreviewRecord] = []
    for record in records:
        student = resolve_student_reference(db, record.student_id)
        if student is None:
            previews.append(
                ImmigrationImportPreviewRecord(
                    student_id=None,
                    student_reference=record.student_id,
                    status="INVALID",
                    errors=[f"Student not found: {record.student_id}"],
                )
            )
            continue

        values, errors = _import_values(record.values)
        profile = (
            db.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        current = {
            field: _json_value(getattr(profile, field))
            for field in values
        } if profile else {}
        applied: list[str] = []
        conflicts: list[str] = []
        if not errors:
            for field, value in values.items():
                existing = getattr(profile, field) if profile else None
                if existing is not None and existing != value:
                    conflicts.append(field)
                else:
                    applied.append(field)

        if errors:
            row_status = "INVALID"
        elif conflicts:
            row_status = "CONFLICT"
        elif not applied:
            row_status = "UNCHANGED"
        else:
            row_status = "APPLY"

        previews.append(
            ImmigrationImportPreviewRecord(
                student_id=student.id,
                student_reference=record.student_id,
                student_name=f"{student.first_name} {student.last_name}",
                student_number=student.student_id,
                status=row_status,
                current_values=current,
                proposed_values={key: _json_value(value) for key, value in values.items()},
                applied_fields=applied,
                conflicts=conflicts,
                errors=errors,
            )
        )

    return ImmigrationImportPreviewResponse(
        records=previews,
        applyable=sum(1 for row in previews if row.status != "INVALID"),
        conflicts=sum(1 for row in previews if row.conflicts),
        invalid=sum(1 for row in previews if row.status == "INVALID"),
    )


def apply_immigration_import(
    db: DBSession, *, records: list, source_reference: str, actor_id: uuid.UUID
) -> ImmigrationImportApplyResponse:
    """Apply a validated batch without ever promoting it to VERIFIED."""
    preview = preview_immigration_import(db, records)
    if preview.invalid:
        raise ValueError("The import contains invalid records; correct them before applying.")

    applied = 0
    for record in records:
        student = resolve_student_reference(db, record.student_id)
        if student is None:
            raise ValueError("The import contains invalid records; correct them before applying.")
        values, errors = _import_values(record.values)
        if errors:
            raise ValueError("The import contains invalid records; correct them before applying.")
        _, _, changed = import_immigration_profile(
            db,
            student_id=student.id,
            data=values,
            source_reference=source_reference,
            actor_id=actor_id,
        )
        if changed:
            applied += 1

    return ImmigrationImportApplyResponse(
        **preview.model_dump(),
        applied=applied,
        skipped=len(records) - applied,
        confirmed=True,
    )


def upload_immigration_document(
    db: DBSession,
    immigration_profile_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    document_type: ImmigrationDocumentType,
    storage_reference: str,
    original_filename: str,
    content_type: str | None = None,
    file_size: int | None = None,
    notes: str | None = None,
) -> ImmigrationDocument:
    """Upload an immigration document (metadata only, file goes to object storage)."""
    document = ImmigrationDocument(
        immigration_profile_id=immigration_profile_id,
        uploaded_by=uploaded_by,
        document_type=document_type,
        storage_reference=storage_reference,
        original_filename=original_filename,
        content_type=content_type,
        file_size=file_size,
        notes=notes,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
