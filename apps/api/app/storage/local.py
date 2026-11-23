"""Local filesystem storage backend.

Intended for development and tests. The root directory lives outside any
publicly served path, and every key is resolved and verified to stay inside
the root before any file operation is performed.
"""

from __future__ import annotations

from pathlib import Path

from app.storage.base import (
    ObjectNotFoundError,
    StorageBackend,
    StorageError,
    StoredObject,
)


class StorageSecurityError(StorageError):
    """Raised when a key would escape the storage root."""


class LocalFilesystemStorage(StorageBackend):
    """Stores objects as files beneath a private root directory."""

    name = "local"

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, key: str) -> Path:
        """Resolve a key to an absolute path inside the storage root.

        Rejects absolute keys, parent traversal, and symlink escapes.
        """
        if not key or key.startswith("/") or key.startswith("\\"):
            raise StorageSecurityError(f"Invalid storage key: {key!r}")

        candidate = (self._root / key).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageSecurityError(f"Storage key escapes root: {key!r}")
        return candidate

    def save(self, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary sibling then replace, so a failed write never
        # leaves a partially written object behind.
        tmp_path = path.with_suffix(path.suffix + ".part")
        tmp_path.write_bytes(data)
        tmp_path.replace(path)
        return StoredObject(key=key, size=len(data), provider=self.name)

    def read(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        path.unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def healthcheck(self) -> bool:
        """Prove the root is writable.

        A read-only or full volume is the failure mode that matters: uploads
        would fail after the request has already been accepted, so readiness
        has to detect it before traffic arrives.
        """
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            probe = self._root / ".healthcheck"
            probe.write_bytes(b"ok")
            probe.unlink()
            return True
        except OSError:
            return False


__all__ = ["LocalFilesystemStorage", "StorageSecurityError"]
