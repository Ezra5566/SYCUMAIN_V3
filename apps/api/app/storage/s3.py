"""S3-compatible object storage backend.

Works with AWS S3, Cloudflare R2, Supabase Storage (S3 endpoint), MinIO, and
any other S3-compatible provider. `boto3` is an optional dependency; it is
imported lazily so the application runs unchanged when this backend is not
configured.
"""

from __future__ import annotations

from app.storage.base import (
    ObjectNotFoundError,
    StorageBackend,
    StorageError,
    StoredObject,
)


class S3Storage(StorageBackend):
    """Private bucket storage with short-lived presigned downloads."""

    name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        presign_expiry_seconds: int = 300,
    ) -> None:
        if not bucket:
            raise StorageError(
                "STORAGE_S3_BUCKET must be set when STORAGE_BACKEND=s3"
            )

        try:
            import boto3  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on install
            raise StorageError(
                "boto3 is required for the S3 storage backend. "
                "Install it with: pip install 'school-portal-api[s3]'"
            ) from exc

        self._bucket = bucket
        self._presign_expiry_seconds = presign_expiry_seconds
        self._client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def save(self, key: str, data: bytes, content_type: str) -> StoredObject:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                # Never let a bucket policy accidentally expose documents.
                ACL="private",
            )
        except Exception as exc:  # noqa: BLE001 - provider SDK raises broadly
            raise StorageError(f"Failed to store object: {exc}") from exc
        return StoredObject(key=key, size=len(data), provider=self.name)

    def read(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except self._client.exceptions.NoSuchKey as exc:
            raise ObjectNotFoundError(key) from exc
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to read object: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to delete object: {exc}") from exc

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001 - any error means "not retrievable"
            return False

    def healthcheck(self) -> bool:
        """Verify the bucket is reachable and the credentials work."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except Exception:  # noqa: BLE001 - any failure means "not usable"
            return False

    def download_url(self, key: str, filename: str | None = None) -> str | None:
        """Return a short-lived presigned GET URL.

        The URL is time-limited and never stored in the database, so it cannot
        become a permanent public link to a private document.
        """
        params: dict[str, str] = {"Bucket": self._bucket, "Key": key}
        if filename:
            safe_name = filename.replace('"', "").replace("\\", "")
            params["ResponseContentDisposition"] = f'attachment; filename="{safe_name}"'
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=self._presign_expiry_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to presign URL: {exc}") from exc


__all__ = ["S3Storage"]
