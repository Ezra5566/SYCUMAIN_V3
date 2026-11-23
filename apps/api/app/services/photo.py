"""Student profile photo service.

Photos obey the same storage discipline as documents: the bytes live in the
private object storage backend and PostgreSQL holds only a reference plus the
sniffed content type. There is deliberately no public URL — the image is
served by an authorization-checked endpoint, so a leaked id is not a leaked
photograph.

Validation is performed on the received bytes (magic number) rather than on
the client-supplied filename or ``Content-Type``, because both are attacker
controlled. Only raster image formats are accepted; SVG is excluded on purpose
since it can carry script.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.audit import record_audit
from app.config.settings import get_settings
from app.storage import (
    ObjectNotFoundError,
    StorageError,
    build_object_key,
    get_storage,
    sniff_content_type,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

    from app.models.identity import Student, User

#: Image formats accepted for a profile photo.
ALLOWED_PHOTO_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class PhotoValidationError(Exception):
    """Raised when an uploaded photo is not acceptable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_photo(*, data: bytes, max_bytes: int) -> str:
    """Validate photo bytes and return the sniffed content type.

    Raises:
        PhotoValidationError: empty, oversized, or not a supported image.
    """
    if not data:
        raise PhotoValidationError("empty_file", "The uploaded image is empty.")

    if len(data) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise PhotoValidationError(
            "file_too_large", f"Image exceeds the {max_mb}MB limit."
        )

    detected = sniff_content_type(data)
    if detected is None or detected not in ALLOWED_PHOTO_TYPES:
        raise PhotoValidationError(
            "unsupported_image_type",
            "Unsupported image type. Upload a JPEG, PNG, or WEBP image.",
        )
    return detected


def set_student_photo(
    db: DBSession,
    *,
    student: Student,
    actor: User,
    data: bytes,
    filename: str | None,
    request=None,
) -> Student:
    """Store a new profile photo and point the student record at it.

    The previous object is deleted only after the new one is safely stored, so
    a failed upload can never leave a student with no photo at all.
    """
    settings = get_settings()
    detected = validate_photo(data=data, max_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024)

    previous_key = student.profile_photo_object_key

    key = build_object_key(
        scope="student-photo",
        owner_id=str(student.id),
        filename=filename or "photo",
        unique_prefix=uuid.uuid4().hex,
    )
    stored = get_storage().save(key, data, detected)

    student.profile_photo_object_key = stored.key
    student.profile_photo_content_type = detected
    # Aware UTC, matching `auth/service.py`; the column is TIMESTAMPTZ and the
    # value is later returned as an aware datetime, so writing a naive one would
    # make the round trip depend on the database session timezone.
    student.profile_photo_updated_at = datetime.now(UTC)

    record_audit(
        db,
        action="student.photo_updated",
        actor=actor,
        entity_type="student",
        entity_id=student.id,
        # Never log the object key or the image bytes.
        context={"content_type": detected, "file_size": stored.size},
        request=request,
    )
    db.commit()
    db.refresh(student)

    # Old object is now unreferenced; removing it keeps storage from growing
    # without bound on repeated replacements.
    if previous_key and previous_key != stored.key:
        with contextlib.suppress(StorageError):
            get_storage().delete(previous_key)

    return student


def read_student_photo(student: Student) -> tuple[bytes, str] | None:
    """Return ``(bytes, content_type)`` for a student's photo, or None."""
    if not student.profile_photo_object_key:
        return None

    try:
        payload = get_storage().read(student.profile_photo_object_key)
    except (ObjectNotFoundError, StorageError):
        # A dangling reference must not break the profile page: fall back to
        # "no photo" rather than surfacing a storage error to the browser.
        return None

    return payload, student.profile_photo_content_type or "application/octet-stream"


def clear_student_photo(
    db: DBSession,
    *,
    student: Student,
    actor: User,
    request=None,
) -> Student:
    """Remove a student's photo and delete the stored object."""
    previous_key = student.profile_photo_object_key

    student.profile_photo_object_key = None
    student.profile_photo_content_type = None
    student.profile_photo_updated_at = None

    record_audit(
        db,
        action="student.photo_removed",
        actor=actor,
        entity_type="student",
        entity_id=student.id,
        request=request,
    )
    db.commit()
    db.refresh(student)

    if previous_key:
        with contextlib.suppress(StorageError):
            get_storage().delete(previous_key)

    return student


__all__ = [
    "ALLOWED_PHOTO_TYPES",
    "PhotoValidationError",
    "clear_student_photo",
    "read_student_photo",
    "set_student_photo",
    "validate_photo",
]
