"""Private document storage abstraction.

Usage::

    from app.storage import get_storage

    storage = get_storage()
    storage.save(key, data, content_type)

Concrete providers are selected by the ``STORAGE_BACKEND`` setting. Business
code never imports a provider directly.
"""

from __future__ import annotations

from app.config.settings import get_settings
from app.storage.base import (
    ObjectNotFoundError,
    StorageBackend,
    StorageError,
    StoredObject,
    build_object_key,
)

_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the configured storage backend (cached per process)."""
    global _backend  # noqa: PLW0603 - process-wide singleton by design
    if _backend is None:
        _backend = _build_backend()
    return _backend


def set_storage(backend: StorageBackend | None) -> None:
    """Override the backend. Used by tests."""
    global _backend  # noqa: PLW0603
    _backend = backend


def _build_backend() -> StorageBackend:
    settings = get_settings()

    if settings.STORAGE_BACKEND == "s3":
        from app.storage.s3 import S3Storage  # noqa: PLC0415

        return S3Storage(
            bucket=settings.STORAGE_S3_BUCKET,
            region=settings.STORAGE_S3_REGION,
            endpoint_url=settings.STORAGE_S3_ENDPOINT_URL,
            access_key_id=settings.STORAGE_S3_ACCESS_KEY_ID,
            secret_access_key=settings.STORAGE_S3_SECRET_ACCESS_KEY,
            presign_expiry_seconds=settings.STORAGE_PRESIGN_EXPIRE_SECONDS,
        )

    from app.storage.local import LocalFilesystemStorage  # noqa: PLC0415

    return LocalFilesystemStorage(settings.STORAGE_LOCAL_ROOT)


# --- Upload validation -----------------------------------------------------

#: Content types the portal accepts for document uploads.
ALLOWED_UPLOAD_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def validate_upload(
    *,
    filename: str | None,
    content_type: str | None,
    data: bytes,
    max_bytes: int,
) -> tuple[str, str]:
    """Validate an uploaded file and return `(content_type, extension)`.

    Validation is performed on the actual bytes, not on the client-supplied
    filename or Content-Type header:

    * the size is measured from the received payload;
    * the real type is sniffed from the magic number;
    * the claimed Content-Type must agree with the sniffed type;
    * the extension is derived from the sniffed type.

    Raises:
        UploadValidationError: when the upload is not acceptable.
    """
    if not filename:
        raise UploadValidationError("filename_required", "A file name is required.")

    if len(data) == 0:
        raise UploadValidationError("empty_file", "The uploaded file is empty.")

    if len(data) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise UploadValidationError(
            "file_too_large", f"File exceeds the {max_mb}MB limit."
        )

    sniffed = sniff_content_type(data)
    if sniffed is None or sniffed not in ALLOWED_UPLOAD_TYPES:
        raise UploadValidationError(
            "unsupported_file_type",
            "Unsupported file type. Upload a PDF, JPEG, PNG, or WEBP file.",
        )

    if content_type and content_type not in ("application/octet-stream", sniffed):
        raise UploadValidationError(
            "content_type_mismatch",
            "The declared file type does not match the file contents.",
        )

    return sniffed, ALLOWED_UPLOAD_TYPES[sniffed]


async def read_upload_limited(file, *, max_bytes: int) -> bytes:
    """Read an upload in bounded chunks and reject it before buffering it all.

    ``UploadFile.read()`` with no argument materialises the whole request body,
    including a multi-gigabyte body sent to exhaust memory. One extra chunk is
    read so a file exactly at the limit is accepted, and the function stops as
    soon as the first byte beyond the limit is seen.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            max_mb = max_bytes // (1024 * 1024)
            raise UploadValidationError(
                "file_too_large", f"File exceeds the {max_mb}MB limit."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def sniff_content_type(data: bytes) -> str | None:
    """Detect a file's real type from its magic number."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class UploadValidationError(Exception):
    """Raised when an upload fails validation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


__all__ = [
    "StorageBackend",
    "StorageError",
    "ObjectNotFoundError",
    "StoredObject",
    "UploadValidationError",
    "ALLOWED_UPLOAD_TYPES",
    "build_object_key",
    "get_storage",
    "set_storage",
    "sniff_content_type",
    "read_upload_limited",
    "validate_upload",
]
