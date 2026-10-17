"""S3-compatible StorageProvider for MinIO (PROFILE A) — lazy boto3 import.

boto3 is imported only when a method runs, keeping vendor SDKs out of the
default dependency tree and out of the test path. This adapter CANNOT be
exercised on the development machine (no Docker for MinIO, no cloud access);
it targets the same StorageProvider protocol as the local provider.
"""

from typing import Any, BinaryIO

from app.adapters.storage.base import StoredObject, StorageObjectNotFound

_DEFAULT_CONTENT_TYPE = "application/octet-stream"


class MinIOS3Provider:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._region = region
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3  # lazy — see module docstring
            except ImportError as exc:
                raise RuntimeError(
                    "The S3/MinIO storage provider requires boto3. "
                    "Install it (pip install boto3) or set "
                    "VERIPAY_STORAGE_BACKEND=local."
                ) from exc
            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
                region_name=self._region,
            )
        return self._client

    def put(
        self, key: str, data: bytes, content_type: str = _DEFAULT_CONTENT_TYPE
    ) -> StoredObject:
        self._get_client().put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    def save(
        self, key: str, data: bytes, content_type: str = _DEFAULT_CONTENT_TYPE
    ) -> StoredObject:
        return self.put(key, data, content_type)

    def open(self, key: str) -> BinaryIO:
        from botocore.exceptions import ClientError  # lazy — boto3 extra

        try:
            response = self._get_client().get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                raise StorageObjectNotFound(key) from exc
            raise
        return response["Body"]

    def delete(self, key: str) -> None:
        # S3 DeleteObject is a no-op for missing keys — idempotent.
        self._get_client().delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError  # lazy — boto3 extra

        try:
            self._get_client().head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                return False
            raise
        return True

    def temporary_url(self, key: str, ttl_s: int) -> str | None:
        return self._get_client().generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl_s,
        )
