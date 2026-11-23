"""Document API.

Uploads are validated on the server (size, magic-number type, declared type),
stored in private object storage, and downloaded only through an
authorization-checked endpoint. Storage provider credentials never reach the
client, and no permanent public URL is ever generated.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi import status as http_status
from fastapi.responses import Response
from sqlalchemy.orm import Session as DBSession

from app.audit import record_audit
from app.auth.dependencies import CurrentUser
from app.config.settings import get_settings
from app.database.session import get_db
from app.models.identity import Student
from app.models.platform import DocumentScanStatus, DocumentVisibility
from app.permissions.checks import has_permission
from app.schemas.platform import (
    DocumentDownloadResponse,
    DocumentExpectationRequest,
    DocumentListResponse,
    DocumentResponse,
    DocumentReviewRequest,
    DocumentTypeListResponse,
    StudentDocumentSummary,
)
from app.services.document import (
    archive_document,
    can_view_student_documents,
    document_type_options,
    get_accessible_document,
    is_staff,
    list_documents,
    purge_document,
    replace_document,
    review_document,
    set_document_expectation,
    student_document_summary,
    to_response,
    upload_document,
)
from app.services.malware_scan import MalwareScanError
from app.storage import (
    ObjectNotFoundError,
    StorageError,
    UploadValidationError,
    get_storage,
    read_upload_limited,
)

router = APIRouter(prefix="/documents", tags=["documents"])

PAGE_SIZE_MAX = 100
INLINE_PREVIEW_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}


def _require(user, permission: str) -> None:
    if not has_permission(user, permission):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to perform this action.",
                }
            },
        )


def _get_document_or_404(db: DBSession, user, document_id: uuid.UUID):
    document = get_accessible_document(db, user=user, document_id=document_id)
    if document is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Document not found."}},
        )
    return document


@router.get("", response_model=DocumentListResponse)
def list_all_documents(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID | None = Query(None),
    document_type: str | None = Query(None, max_length=50),
    search: str | None = Query(None, max_length=200),
    include_archived: bool = Query(
        False, description="Include archived documents (document managers only)."
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=PAGE_SIZE_MAX),
):
    """List documents the caller is authorized to see."""
    _require(current_user, "documents.view")

    items, total = list_documents(
        db,
        user=current_user,
        student_id=student_id,
        document_type=document_type,
        search=search,
        include_archived=include_archived,
        page=page,
        page_size=page_size,
    )
    return DocumentListResponse(
        items=[to_response(db, d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DocumentResponse, status_code=http_status.HTTP_201_CREATED)
async def upload_new_document(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(..., max_length=50),
    title: str = Form(..., max_length=255),
    description: str | None = Form(None, max_length=2000),
    student_id: uuid.UUID | None = Form(None),
    student_visible: bool = Form(False),
):
    """Upload a document into private storage.

    A student may only upload against their own record and can never create a
    staff-only or mislabelled document.
    """
    _require(current_user, "documents.upload")

    staff = is_staff(current_user)

    if student_id is not None:
        if not staff:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "You may only upload documents to your own record.",
                    }
                },
            )
        if db.query(Student.id).filter(Student.id == student_id).first() is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail={"error": {"code": "NOT_FOUND", "message": "Student not found."}},
            )
    elif not staff:
        student = db.query(Student).filter(Student.user_id == current_user.id).first()
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
        student_id = student.id

    # A student's own uploads are always visible to them; staff choose.
    if staff:
        visibility = (
            DocumentVisibility.STUDENT_VISIBLE
            if student_visible
            else DocumentVisibility.STAFF_ONLY
        )
    else:
        visibility = DocumentVisibility.STUDENT_VISIBLE

    settings = get_settings()
    try:
        data = await read_upload_limited(
            file, max_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        )
    except UploadValidationError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": exc.code.upper(), "message": exc.message}},
        ) from exc

    try:
        document = upload_document(
            db,
            actor=current_user,
            data=data,
            filename=file.filename,
            content_type=file.content_type,
            document_type=document_type,
            title=title,
            description=description,
            student_id=student_id,
            visibility=visibility,
            request=request,
        )
    except MalwareScanError as exc:
        raise HTTPException(
            status_code=(
                http_status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.unavailable
                else http_status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={"error": {"code": exc.code.upper(), "message": exc.message}},
        ) from exc
    except UploadValidationError as exc:
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
                    "message": "Document storage is currently unavailable.",
                }
            },
        ) from exc

    return to_response(db, document)


@router.get("/{document_id}/preview")
def preview_document(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    document_id: uuid.UUID,
    request: Request,
):
    """Inline preview for browser-safe types, with the same object ACL as download."""
    _require(current_user, "documents.view")
    document = _get_document_or_404(db, current_user, document_id)
    if document.content_type not in INLINE_PREVIEW_TYPES:
        raise HTTPException(
            status_code=http_status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error": {
                    "code": "PREVIEW_UNSUPPORTED",
                    "message": "This document type cannot be previewed inline.",
                }
            },
        )
    if document.scan_status not in {
        DocumentScanStatus.CLEAN,
        DocumentScanStatus.LEGACY_UNSCANNED,
    }:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "DOCUMENT_NOT_SCANNED",
                    "message": "This document is not cleared for viewing.",
                }
            },
        )

    record_audit(
        db,
        action="document.previewed",
        actor=current_user,
        entity_type="document",
        entity_id=document.id,
        request=request,
    )
    db.commit()

    storage = get_storage()
    try:
        payload = storage.read(document.object_key)
    except ObjectNotFoundError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_410_GONE,
            detail={
                "error": {
                    "code": "OBJECT_MISSING",
                    "message": "The stored file is no longer available.",
                }
            },
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "STORAGE_UNAVAILABLE",
                    "message": "Document storage is currently unavailable.",
                }
            },
        ) from exc

    safe_name = document.original_filename.replace('"', "").replace("\\", "")
    return Response(
        content=payload,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.get("/types", response_model=DocumentTypeListResponse)
def list_document_types(current_user: CurrentUser):
    """The document vocabulary the client should offer.

    Served by the API rather than hard-coded in the UI so a new category does
    not require a frontend release, and so an unknown value can never be
    offered.
    """
    _require(current_user, "documents.view")
    return DocumentTypeListResponse(items=document_type_options())


@router.get("/students/{student_id}/summary", response_model=StudentDocumentSummary)
def get_student_document_summary(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    student_id: uuid.UUID,
):
    """Document completeness for one student: required, missing, pending.

    This is what makes the student profile Documents tab useful — "you are
    missing your residence permit" is a different answer from "here are four
    files".
    """
    _require(current_user, "documents.view")

    if db.query(Student.id).filter(Student.id == student_id).first() is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Student not found."}},
        )

    # An unauthorized viewer learns nothing: the response is indistinguishable
    # from a student that does not exist.
    if not can_view_student_documents(db, user=current_user, student_id=student_id):
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Student not found."}},
        )

    return student_document_summary(db, student_id=student_id, viewer=current_user)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document_metadata(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    document_id: uuid.UUID,
):
    """Document metadata (never the file bytes)."""
    _require(current_user, "documents.view")
    document = _get_document_or_404(db, current_user, document_id)
    return to_response(db, document)


@router.get("/{document_id}/download")
def download_document(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    document_id: uuid.UUID,
    request: Request,
    redirect: bool = Query(
        False,
        description="Return a short-lived presigned URL instead of streaming.",
    ),
):
    """Download a document, subject to object-level authorization."""
    _require(current_user, "documents.view")
    document = _get_document_or_404(db, current_user, document_id)

    record_audit(
        db,
        action="document.downloaded",
        actor=current_user,
        entity_type="document",
        entity_id=document.id,
        request=request,
    )
    db.commit()

    storage = get_storage()

    if redirect:
        url = storage.download_url(document.object_key, document.original_filename)
        if url:
            return DocumentDownloadResponse(
                document_id=document.id,
                filename=document.original_filename,
                content_type=document.content_type,
                expires_in=300,
                url=url,
            )

    try:
        payload = storage.read(document.object_key)
    except ObjectNotFoundError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_410_GONE,
            detail={
                "error": {
                    "code": "OBJECT_MISSING",
                    "message": "The stored file is no longer available.",
                }
            },
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "STORAGE_UNAVAILABLE",
                    "message": "Document storage is currently unavailable.",
                }
            },
        ) from exc

    safe_name = document.original_filename.replace('"', "").replace("\\", "")
    return Response(
        content=payload,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            # Private documents must never be cached by shared proxies.
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{document_id}/review", response_model=DocumentResponse)
def review_document_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    document_id: uuid.UUID,
    payload: DocumentReviewRequest,
    request: Request,
):
    """Approve or reject an uploaded document. Document managers only."""
    _require(current_user, "documents.manage")
    document = _get_document_or_404(db, current_user, document_id)

    try:
        document = review_document(
            db,
            document=document,
            actor=current_user,
            decision=payload.decision,
            note=payload.note,
            request=request,
        )
    except ValueError as exc:
        if str(exc) == "replacement_reason_required":
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "REPLACEMENT_REASON_REQUIRED",
                        "message": (
                            "A reason is required when rejecting a document "
                            "or requesting a replacement."
                        ),
                    }
                },
            ) from exc
        if str(exc) == "invalid_review_transition":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail={
                    "error": {
                        "code": "INVALID_REVIEW_TRANSITION",
                        "message": "This document version already has a final review decision.",
                    }
                },
            ) from exc
        if str(exc) == "document_not_scanned":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail={
                    "error": {
                        "code": "DOCUMENT_NOT_SCANNED",
                        "message": "This document must be scanned clean before review.",
                    }
                },
            ) from exc
        if str(exc) == "document_file_missing":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail={
                    "error": {
                        "code": "DOCUMENT_FILE_MISSING",
                        "message": (
                            "The stored file is no longer available. "
                            "Upload it again before reviewing this document."
                        ),
                    }
                },
            ) from exc
        if str(exc) == "document_storage_unavailable":
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": {
                        "code": "STORAGE_UNAVAILABLE",
                        "message": "Document storage is currently unavailable.",
                    }
                },
            ) from exc
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "INVALID_REVIEW_DECISION",
                    "message": "That review decision is not valid.",
                }
            },
        ) from exc

    return to_response(db, document)


@router.patch("/{document_id}/expectation", response_model=DocumentResponse)
def update_document_expectation(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    document_id: uuid.UUID,
    payload: DocumentExpectationRequest,
    request: Request,
):
    """Flag a document as institutionally required and/or set its expiry."""
    _require(current_user, "documents.manage")
    document = _get_document_or_404(db, current_user, document_id)

    document = set_document_expectation(
        db,
        document=document,
        actor=current_user,
        is_required=payload.is_required,
        expires_on=payload.expires_on,
        expires_on_set="expires_on" in payload.model_fields_set,
        request=request,
    )
    return to_response(db, document)


@router.post(
    "/{document_id}/replace",
    response_model=DocumentResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def replace_existing_document(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    document_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(None, max_length=255),
    description: str | None = Form(None, max_length=2000),
    expires_on: str | None = Form(None),
    student_visible: bool | None = Form(None),
):
    """Upload a new version of a document, preserving the previous one.

    Replacing never overwrites history: the old row is marked superseded and
    the new version starts its own review cycle.
    """
    _require(current_user, "documents.upload")

    superseded = _get_document_or_404(db, current_user, document_id)

    # A student may replace their own document but must not be able to flip a
    # staff-only document into student visibility, nor retitle it arbitrarily.
    staff = is_staff(current_user)
    if not staff and superseded.student_id is not None:
        student = db.query(Student).filter(Student.user_id == current_user.id).first()
        if student is None or student.id != superseded.student_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "You may only replace your own documents.",
                    }
                },
            )

    parsed_expiry = None
    if expires_on:
        try:
            parsed_expiry = date.fromisoformat(expires_on)
        except ValueError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "INVALID_DATE",
                        "message": "expires_on must be an ISO date (YYYY-MM-DD).",
                    }
                },
            ) from exc

    visibility = None
    if staff and student_visible is not None:
        visibility = (
            DocumentVisibility.STUDENT_VISIBLE
            if student_visible
            else DocumentVisibility.STAFF_ONLY
        )

    settings = get_settings()
    try:
        data = await read_upload_limited(
            file, max_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        )
    except UploadValidationError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": exc.code.upper(), "message": exc.message}},
        ) from exc

    try:
        replacement = replace_document(
            db,
            superseded=superseded,
            actor=current_user,
            data=data,
            filename=file.filename,
            content_type=file.content_type,
            title=title,
            description=description,
            expires_on=parsed_expiry if expires_on else None,
            visibility=visibility,
            request=request,
        )
    except MalwareScanError as exc:
        raise HTTPException(
            status_code=(
                http_status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.unavailable
                else http_status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail={"error": {"code": exc.code.upper(), "message": exc.message}},
        ) from exc
    except UploadValidationError as exc:
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
                    "message": "Document storage is currently unavailable.",
                }
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": str(exc).upper(),
                    "message": "This document can no longer be replaced.",
                }
            },
        ) from exc

    return to_response(db, replacement)


@router.delete("/{document_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def remove_document(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    document_id: uuid.UUID,
    request: Request,
    hard: bool = Query(False, description="Also delete the stored bytes."),
):
    """Archive (default) or purge a document. Management only."""
    _require(current_user, "documents.manage")
    document = _get_document_or_404(db, current_user, document_id)

    try:
        if hard:
            purge_document(db, document=document, actor=current_user, request=request)
        else:
            archive_document(
                db, document=document, actor=current_user, request=request
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": str(exc).upper(),
                    "message": "An accepted document cannot be archived or deleted.",
                }
            },
        ) from exc

    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
