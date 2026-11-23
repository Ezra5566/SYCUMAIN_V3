"""Document service.

Only metadata is stored in PostgreSQL. The bytes go to the configured
private storage backend, and are reachable only through an authorization
checked download path — never through a public URL.
"""

import contextlib
import hashlib
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.audit import record_audit
from app.config.settings import get_settings
from app.models.identity import Student, User
from app.models.platform import (
    DOCUMENT_TYPES,
    Document,
    DocumentReviewStatus,
    DocumentScanStatus,
    DocumentStatus,
    DocumentVisibility,
    NotificationType,
)
from app.permissions.scope import can_access_student
from app.permissions.scope import role_names as scope_role_names
from app.schemas.platform import (
    DocumentResponse,
    RequiredDocumentStatus,
    StudentDocumentSummary,
)
from app.services.malware_scan import MalwareScanError, ScanOutcome, scan_bytes
from app.services.notification import create_notification
from app.storage import (
    StorageError,
    build_object_key,
    get_storage,
    validate_upload,
)

MANAGEMENT_ROLES = {"ADMIN", "MANAGEMENT"}
STAFF_ROLES = {"ADMIN", "MANAGEMENT", "TEACHER"}

# Re-exported so existing callers keep working; the implementation lives in the
# shared scope module so documents, photos and academic data cannot drift.
role_names = scope_role_names


def is_staff(user: User) -> bool:
    return bool(role_names(user) - {"STUDENT"})


def can_manage_documents(user: User) -> bool:
    return bool(MANAGEMENT_ROLES & role_names(user))


def to_response(db: DBSession, document: Document) -> DocumentResponse:
    student_user = None
    if document.student is not None:
        student_user = (
            db.query(User).filter(User.id == document.student.user_id).first()
        )

    return DocumentResponse(
        id=document.id,
        student_id=document.student_id,
        student_name=student_user.full_name if student_user else None,
        document_type=document.document_type,
        title=document.title,
        description=document.description,
        original_filename=document.original_filename,
        content_type=document.content_type,
        file_size=document.file_size,
        visibility=document.visibility,
        status=document.status,
        review_status=document.review_status,
        scan_status=document.scan_status,
        scan_engine=document.scan_engine,
        scanned_at=document.scanned_at,
        reviewed_at=document.reviewed_at,
        reviewer_name=document.reviewer.full_name if document.reviewer else None,
        review_note=document.review_note,
        is_required=document.is_required,
        expires_on=document.expires_on,
        superseded_by_id=document.superseded_by_id,
        uploaded_by=document.uploaded_by,
        uploader_name=document.uploader.full_name if document.uploader else None,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def get_accessible_document(
    db: DBSession, *, user: User, document_id: uuid.UUID
) -> Document | None:
    """Fetch a document only when `user` is authorized for that specific row."""
    # Only ACTIVE documents are retrievable. Archiving therefore revokes
    # access immediately while keeping the metadata row for the audit trail.
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.status == DocumentStatus.ACTIVE)
        .first()
    )
    if document is None:
        return None

    roles = role_names(user)

    if MANAGEMENT_ROLES & roles:
        return document

    if "TEACHER" in roles:
        # Class membership is academic scope, not authority to read passports,
        # permits or private student files. Deny explicitly even if a legacy
        # role row still carries a document permission.
        return None

    if "STUDENT" in roles:
        if document.visibility != DocumentVisibility.STUDENT_VISIBLE:
            return None
        student = db.query(Student).filter(Student.user_id == user.id).first()
        if student is not None and document.student_id == student.id:
            return document

    return None


def student_visible_filter(db: DBSession, user: User):
    """SQL predicate describing documents visible to `user` in a listing."""
    roles = role_names(user)

    if MANAGEMENT_ROLES & roles:
        return None

    if "TEACHER" in roles:
        return Document.id.is_(None)

    if "STUDENT" in roles:
        student = db.query(Student).filter(Student.user_id == user.id).first()
        if student is None:
            return Document.id.is_(None)
        return (Document.student_id == student.id) & (
            Document.visibility == DocumentVisibility.STUDENT_VISIBLE
        )

    return Document.id.is_(None)


def list_documents(
    db: DBSession,
    *,
    user: User,
    student_id: uuid.UUID | None = None,
    document_type: str | None = None,
    search: str | None = None,
    include_archived: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Document], int]:
    """List documents the caller is allowed to see.

    Archived documents are hidden by default; only document managers may ask
    for them explicitly.
    """
    allowed_statuses = [DocumentStatus.ACTIVE]
    if include_archived and can_manage_documents(user):
        allowed_statuses.append(DocumentStatus.ARCHIVED)

    query = db.query(Document).filter(Document.status.in_(allowed_statuses))

    scope = student_visible_filter(db, user)
    if scope is not None:
        query = query.filter(scope)

    if student_id is not None:
        query = query.filter(Document.student_id == student_id)
    if document_type:
        query = query.filter(Document.document_type == document_type)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Document.title.ilike(pattern),
                Document.original_filename.ilike(pattern),
            )
        )

    total = query.count()
    items = (
        query.order_by(Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def upload_document(
    db: DBSession,
    *,
    actor: User,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    document_type: str,
    title: str,
    description: str | None = None,
    student_id: uuid.UUID | None = None,
    visibility: DocumentVisibility = DocumentVisibility.STAFF_ONLY,
    request=None,
) -> Document:
    """Validate, store, and register a document.

    Raises:
        UploadValidationError: file rejected (never trusted from the client).
        StorageError: the storage backend refused the write.
    """
    settings = get_settings()

    detected_type, _extension = validate_upload(
        filename=filename,
        content_type=content_type,
        data=data,
        max_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
    )
    scan = _clean_scan(data)

    owner_scope = f"student/{student_id}" if student_id else f"general/{actor.id}"
    key = build_object_key(
        scope=owner_scope,
        owner_id=str(actor.id),
        filename=filename or "upload",
        unique_prefix=uuid.uuid4().hex,
    )

    stored = get_storage().save(key, data, detected_type)

    document = Document(
        student_id=student_id,
        uploaded_by=actor.id,
        document_type=document_type,
        title=title,
        description=description,
        storage_provider=stored.provider,
        object_key=stored.key,
        original_filename=(filename or "upload")[:255],
        content_type=detected_type,
        file_size=stored.size,
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        visibility=visibility,
        status=DocumentStatus.ACTIVE,
        review_status=DocumentReviewStatus.PENDING,
        scan_status=scan.status,
        scan_engine=scan.engine,
        scanned_at=datetime.now(UTC),
    )
    db.add(document)

    record_audit(
        db,
        action="document.uploaded",
        actor=actor,
        entity_type="document",
        entity_id=document.id,
        # Never log the file name or contents; only safe descriptors.
        context={"document_type": document_type, "file_size": stored.size},
        request=request,
    )

    if student_id is not None:
        student = db.query(Student).filter(Student.id == student_id).first()
        if student is not None and visibility == DocumentVisibility.STUDENT_VISIBLE:
            create_notification(
                db,
                user_id=student.user_id,
                notification_type=NotificationType.DOCUMENT_UPLOADED,
                params={"document_type": document_type, "title": title},
                link_url="/app/documents",
                entity_type="document",
                entity_id=document.id,
            )

    try:
        db.commit()
    except Exception:
        # A failed metadata write must not leave an orphaned object or a
        # half-created Pending record behind.
        db.rollback()
        with contextlib.suppress(StorageError):
            get_storage().delete(stored.key)
        raise
    db.refresh(document)
    return document


def review_document(
    db: DBSession,
    *,
    document: Document,
    actor: User,
    decision: DocumentReviewStatus,
    note: str | None = None,
    request=None,
) -> Document:
    """Record an institutional decision on an uploaded document.

    Approval/rejection is a decision about *this version* of *this* document:
    re-uploading a corrected file produces a new row that starts PENDING again,
    so a rejection can never silently apply to a replacement.

    Raises:
        ValueError: when asked to reject without a note, so the student is
            never left with a rejection they cannot act on.
    """
    if decision in (DocumentReviewStatus.PENDING,):
        raise ValueError("pending_not_a_decision")
    if decision not in {
        DocumentReviewStatus.UNDER_REVIEW,
        DocumentReviewStatus.APPROVED,
        DocumentReviewStatus.REJECTED,
        DocumentReviewStatus.REPLACEMENT_REQUIRED,
    }:
        raise ValueError("invalid_review_decision")

    # A decision is final for a version. A correction is a new row with its own
    # review cycle, which is what keeps an accepted file's decision immutable.
    if document.review_status not in {
        DocumentReviewStatus.PENDING,
        DocumentReviewStatus.UNDER_REVIEW,
    } or document.superseded_by_id is not None:
        raise ValueError("invalid_review_transition")

    if document.scan_status != DocumentScanStatus.CLEAN:
        raise ValueError("document_not_scanned")

    # Review is a decision about a stored file, not about a metadata row. If
    # the object disappeared (storage repair, manual deletion, a failed
    # provider write), the row must not be approvable as if the evidence were
    # present.
    try:
        if (
            not document.object_key
            or document.file_size <= 0
            or not get_storage().exists(document.object_key)
        ):
            raise ValueError("document_file_missing")
    except StorageError as exc:
        raise ValueError("document_storage_unavailable") from exc

    if decision in {
        DocumentReviewStatus.REJECTED,
        DocumentReviewStatus.REPLACEMENT_REQUIRED,
    } and not (note or "").strip():
        raise ValueError("replacement_reason_required")

    document.review_status = decision
    document.reviewed_by = actor.id
    # `datetime.now(UTC)` rather than naive `utcnow()`: the column is
    # TIMESTAMPTZ, and an aware value keeps comparisons with other aware
    # timestamps valid instead of relying on the server's session timezone.
    document.reviewed_at = datetime.now(UTC)
    document.review_note = (note or "").strip() or None

    record_audit(
        db,
        action=f"document.review_{decision.value.lower()}",
        actor=actor,
        entity_type="document",
        entity_id=document.id,
        # The reviewer's note may contain sensitive commentary; log only the
        # decision and the safe descriptors.
        context={"document_type": document.document_type},
        request=request,
    )

    if document.student_id is not None:
        student = db.query(Student).filter(Student.id == document.student_id).first()
        if student is not None:
            create_notification(
                db,
                user_id=student.user_id,
                notification_type=NotificationType.DOCUMENT_UPLOADED,
                params={
                    "document_type": document.document_type,
                    "title": document.title,
                    "decision": decision.value,
                },
                link_url="/app/documents",
                entity_type="document",
                entity_id=document.id,
            )

    db.commit()
    db.refresh(document)
    return document


def set_document_expectation(
    db: DBSession,
    *,
    document: Document,
    actor: User,
    is_required: bool | None = None,
    expires_on: date | None = None,
    expires_on_set: bool = False,
    request=None,
) -> Document:
    """Update the institutional expectation flags on a document."""
    if is_required is not None:
        document.is_required = is_required
    if expires_on_set:
        document.expires_on = expires_on

    record_audit(
        db,
        action="document.expectation_updated",
        actor=actor,
        entity_type="document",
        entity_id=document.id,
        context={
            "is_required": document.is_required,
            "expires_on": document.expires_on.isoformat() if document.expires_on else None,
        },
        request=request,
    )
    db.commit()
    db.refresh(document)
    return document


def replace_document(
    db: DBSession,
    *,
    superseded: Document,
    actor: User,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    title: str | None = None,
    description: str | None = None,
    expires_on: date | None = None,
    visibility: DocumentVisibility | None = None,
    request=None,
) -> Document:
    """Upload a new version of an existing document.

    History is preserved rather than overwritten: the previous row is marked
    ``superseded_by_id`` and kept, and the new row inherits the business
    attributes a reviewer would expect (type, student, required flag) while
    starting its own review cycle.

    Raises:
        UploadValidationError: file rejected.
        StorageError: the storage backend refused the write.
    """
    if superseded.superseded_by_id is not None:
        raise ValueError("document_already_superseded")
    if superseded.status != DocumentStatus.ACTIVE:
        raise ValueError("document_not_active")

    settings = get_settings()

    detected_type, _extension = validate_upload(
        filename=filename,
        content_type=content_type,
        data=data,
        max_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
    )
    scan = _clean_scan(data)

    owner_scope = (
        f"student/{superseded.student_id}"
        if superseded.student_id
        else f"general/{actor.id}"
    )
    key = build_object_key(
        scope=owner_scope,
        owner_id=str(actor.id),
        filename=filename or "upload",
        unique_prefix=uuid.uuid4().hex,
    )

    stored = get_storage().save(key, data, detected_type)

    replacement = Document(
        student_id=superseded.student_id,
        uploaded_by=actor.id,
        document_type=superseded.document_type,
        title=(title or superseded.title),
        description=description if description is not None else superseded.description,
        storage_provider=stored.provider,
        object_key=stored.key,
        original_filename=(filename or "upload")[:255],
        content_type=detected_type,
        file_size=stored.size,
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        visibility=visibility or superseded.visibility,
        status=DocumentStatus.ACTIVE,
        review_status=DocumentReviewStatus.PENDING,
        scan_status=scan.status,
        scan_engine=scan.engine,
        scanned_at=datetime.now(UTC),
        is_required=superseded.is_required,
        expires_on=expires_on if expires_on is not None else superseded.expires_on,
    )
    db.add(replacement)
    db.flush()

    # Mark the old version as superseded. It stays ACTIVE (and therefore
    # downloadable) so the institution can answer "what did we actually see
    # last year?", but the summary resolves the current version through this
    # pointer.
    superseded.superseded_by_id = replacement.id

    record_audit(
        db,
        action="document.replaced",
        actor=actor,
        entity_type="document",
        entity_id=replacement.id,
        context={
            "document_type": replacement.document_type,
            "supersedes": str(superseded.id),
            "file_size": stored.size,
        },
        request=request,
    )

    try:
        db.commit()
    except Exception:
        db.rollback()
        with contextlib.suppress(StorageError):
            get_storage().delete(stored.key)
        raise
    db.refresh(replacement)
    return replacement


def _clean_scan(data: bytes) -> ScanOutcome:
    """Reject infected or unscannable bytes before they are persisted."""
    outcome = scan_bytes(data)
    if outcome.status == DocumentScanStatus.INFECTED:
        raise MalwareScanError(
            "malware_detected",
            "The uploaded file was rejected by malware scanning.",
        )
    if outcome.status != DocumentScanStatus.CLEAN:
        raise MalwareScanError(
            "scanner_unavailable",
            "The file could not be scanned for malware and was not stored.",
            unavailable=True,
        )
    return outcome


def can_view_student_documents(
    db: DBSession, *, user: User, student_id: uuid.UUID
) -> bool:
    """Whether `user` may see the document set of one specific student.

    Delegates to the shared scope resolver so a summary can never reveal a
    student's document state that the underlying documents would refuse to
    serve.
    """
    if "TEACHER" in role_names(user):
        return False
    return can_access_student(db, user, student_id)


def document_type_options() -> list[dict[str, str]]:
    """The document vocabulary the UI should offer.

    Served by the API so the picker cannot drift from the backend, and so
    adding a category is a one-line change rather than a UI release.
    """
    return [
        {"value": value, "label_key": f"types.{value}"} for value in DOCUMENT_TYPES
    ]


def _current_documents(db: DBSession, *, student_id: uuid.UUID) -> list[Document]:
    """Active documents for a student, excluding superseded versions.

    A superseded row is historical evidence, not the student's current
    submission, so it must not satisfy an institutional requirement.
    """
    return (
        db.query(Document)
        .filter(
            Document.student_id == student_id,
            Document.status == DocumentStatus.ACTIVE,
            Document.superseded_by_id.is_(None),
        )
        .order_by(Document.created_at.desc())
        .all()
    )


def student_document_summary(
    db: DBSession,
    *,
    student_id: uuid.UUID,
    viewer: User,
) -> StudentDocumentSummary:
    """Completeness view for one student's documents.

    Two sources feed "what is required":

    1. the institution-wide baseline list (``REQUIRED_DOCUMENT_TYPES``), which
       is configuration rather than schema; and
    2. any document explicitly flagged ``is_required``, which lets a case
       worker demand something for one student without a code change.

    A required category with no current document is reported ``MISSING`` —
    derived at read time, never stored.
    """
    from app.services.immigration import calculate_document_status  # noqa: PLC0415

    settings = get_settings()
    baseline = [
        value.strip().upper()
        for value in settings.REQUIRED_DOCUMENT_TYPES.split(",")
        if value.strip()
    ]

    documents = _current_documents(db, student_id=student_id)

    by_type: dict[str, list[Document]] = {}
    for document in documents:
        by_type.setdefault(document.document_type, []).append(document)

    explicitly_required = [d.document_type for d in documents if d.is_required]
    required_types = list(dict.fromkeys(baseline + explicitly_required))

    # Students must not learn the contents of staff-only documents, but "you
    # are missing a residence permit" is exactly the instruction they need.
    # Staff-only rows still count toward completeness for staff viewers;
    # students only ever see their own visible uploads here.
    viewer_is_staff = is_staff(viewer)

    required: list[RequiredDocumentStatus] = []
    for document_type in required_types:
        candidates = by_type.get(document_type, [])
        if not viewer_is_staff:
            candidates = [
                d
                for d in candidates
                if d.visibility == DocumentVisibility.STUDENT_VISIBLE
            ]

        if not candidates:
            required.append(
                RequiredDocumentStatus(document_type=document_type, state="MISSING")
            )
            continue

        current = candidates[0]
        status, _days = calculate_document_status(current.expires_on)

        # A rejected or still-pending document is more important to surface
        # than a distant expiry date; expiry only differentiates once the
        # document itself has been accepted.
        if current.review_status == DocumentReviewStatus.REJECTED:
            state = "REJECTED"
        elif current.review_status == DocumentReviewStatus.REPLACEMENT_REQUIRED:
            state = "REPLACEMENT_REQUIRED"
        elif current.review_status in {
            DocumentReviewStatus.PENDING,
            DocumentReviewStatus.UNDER_REVIEW,
        }:
            state = "PENDING"
        elif status in ("EXPIRED", "URGENT", "EXPIRING_SOON"):
            state = "EXPIRED" if status == "EXPIRED" else "EXPIRING"
        else:
            state = "APPROVED"

        required.append(
            RequiredDocumentStatus(
                document_type=document_type,
                state=state,
                expires_on=current.expires_on,
                document_id=current.id,
                title=current.title,
            )
        )

    required_type_set = set(required_types)
    other = [
        to_response(db, d)
        for d in documents
        if d.document_type not in required_type_set
        and (viewer_is_staff or d.visibility == DocumentVisibility.STUDENT_VISIBLE)
    ]

    # Counts describe the *current* set, so they always agree with the lists
    # rendered beside them.
    all_current = [
        d
        for d in documents
        if viewer_is_staff or d.visibility == DocumentVisibility.STUDENT_VISIBLE
    ]
    expiring = 0
    expired = 0
    for document in all_current:
        status, _days = calculate_document_status(document.expires_on)
        if status == "EXPIRED":
            expired += 1
        elif status in ("URGENT", "EXPIRING_SOON"):
            expiring += 1

    return StudentDocumentSummary(
        student_id=student_id,
        required=required,
        other=other,
        missing_count=sum(1 for r in required if r.state == "MISSING"),
        pending_count=sum(1 for r in required if r.state == "PENDING"),
        rejected_count=sum(1 for r in required if r.state == "REJECTED"),
        expiring_count=expiring,
        expired_count=expired,
    )


def archive_document(
    db: DBSession, *, document: Document, actor: User, request=None
) -> Document:
    """Soft-delete a document, keeping the audit trail intact.

    An accepted version is evidence. It may be superseded by a newer version,
    but it must not disappear through an ordinary archive operation.
    """
    if document.review_status == DocumentReviewStatus.APPROVED:
        raise ValueError("accepted_document_immutable")
    document.status = DocumentStatus.ARCHIVED
    record_audit(
        db,
        action="document.archived",
        actor=actor,
        entity_type="document",
        entity_id=document.id,
        request=request,
    )
    db.commit()
    db.refresh(document)
    return document


def purge_document(
    db: DBSession, *, document: Document, actor: User, request=None
) -> None:
    """Remove the stored bytes and mark the row deleted.

    Used only for genuinely incorrect uploads. The metadata row is retained so
    the audit chain still resolves. Accepted evidence is never purged.
    """
    if document.review_status == DocumentReviewStatus.APPROVED:
        raise ValueError("accepted_document_immutable")
    # The metadata state is advanced regardless: a dangling object is far less
    # harmful than a document that claims to exist but cannot be served.
    with contextlib.suppress(StorageError):
        get_storage().delete(document.object_key)

    document.status = DocumentStatus.DELETED
    record_audit(
        db,
        action="document.deleted",
        actor=actor,
        entity_type="document",
        entity_id=document.id,
        request=request,
    )
    db.commit()


__all__ = [
    "archive_document",
    "can_manage_documents",
    "can_view_student_documents",
    "document_type_options",
    "get_accessible_document",
    "is_staff",
    "list_documents",
    "purge_document",
    "replace_document",
    "review_document",
    "set_document_expectation",
    "student_document_summary",
    "student_visible_filter",
    "to_response",
    "upload_document",
]
