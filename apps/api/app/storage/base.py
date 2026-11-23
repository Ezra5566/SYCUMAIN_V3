"""Storage backend interface.

Application code depends on this abstraction, never on a concrete provider.
PostgreSQL stores document *metadata*; the bytes live behind
:class:`StorageBackend`.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


class StorageError(Exception):
    """Raised when a storage operation fails."""


class ObjectNotFoundError(StorageError):
    """Raised when a requested object does not exist."""


@dataclass(frozen=True)
class StoredObject:
    """Result of storing bytes."""

    key: str
    size: int
    provider: str


class StorageBackend(abc.ABC):
    """Abstract private object store."""

    #: Short identifier persisted alongside document metadata.
    name: str = "base"

    @abc.abstractmethod
    def save(self, key: str, data: bytes, content_type: str) -> StoredObject:
        """Persist bytes under `key` and return storage details."""

    @abc.abstractmethod
    def read(self, key: str) -> bytes:
        """Return the bytes for `key`, or raise ObjectNotFoundError."""

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        """Remove the object. Must not raise if it is already absent."""

    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        """Return True when the object exists."""

    def healthcheck(self) -> bool:
        """Return True when the backend is usable right now.

        Must not raise: readiness reporting needs a boolean, and a provider
        outage is an ordinary answer ("not ready") rather than an error.
        """
        return True

    def download_url(self, key: str, filename: str | None = None) -> str | None:
        """Return a short-lived direct URL, when the provider supports it.

        Returning None means the caller must stream the object through the
        application instead. Providers that can presign should override this.
        """
        return None


def build_object_key(
    *,
    scope: str,
    owner_id: str,
    filename: str,
    unique_prefix: str,
) -> str:
    """Build a storage key that is opaque and cannot collide.

    The original filename is intentionally *not* used as the key: it is
    attacker-controlled and would allow path traversal or overwrites. Only a
    sanitized extension and a unique prefix are used.
    """
    import os

    extension = os.path.splitext(filename)[1].lower()
    # Keep only a conservative, known-safe extension shape.
    if len(extension) > 10 or not extension[1:].isalnum():
        extension = ""

    return f"{scope}/{owner_id}/{unique_prefix}{extension}"


__all__ = [
    "StorageBackend",
    "StorageError",
    "ObjectNotFoundError",
    "StoredObject",
    "build_object_key",
]
