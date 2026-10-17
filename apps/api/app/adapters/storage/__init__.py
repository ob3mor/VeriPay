"""StorageProvider seam — protocol + local (default) + MinIO/S3 (PROFILE A).

Modules depend on the protocol only (inversion, ADR 0003). Object keys are
tenant-prefixed ``{org_id}/{document_id}/{sha256}{ext}`` so a misconfigured
shared bucket still cannot silently merge tenants' objects
(docs/ARCHITECTURE.md §7.1).
"""

from app.adapters.storage.base import (
    StorageKeyError,
    StorageObjectNotFound,
    StorageProvider,
    StoredObject,
    build_document_key,
)
from app.adapters.storage.local import LocalFilesystemProvider
from app.adapters.storage.s3 import MinIOS3Provider
from app.core.config import Settings


def get_storage_provider(settings: Settings) -> StorageProvider:
    """Build the configured provider (factory; no global state)."""
    if settings.storage_backend == "local":
        return LocalFilesystemProvider(settings.storage_local_root)
    if settings.storage_backend == "minio":
        return MinIOS3Provider(
            bucket=settings.storage_s3_bucket,
            endpoint_url=settings.storage_s3_endpoint_url,
            access_key_id=settings.storage_s3_access_key_id,
            secret_access_key=settings.storage_s3_secret_access_key,
            region=settings.storage_s3_region,
        )
    raise ValueError(f"Unknown storage backend: {settings.storage_backend!r}")


__all__ = [
    "LocalFilesystemProvider",
    "MinIOS3Provider",
    "StorageKeyError",
    "StorageObjectNotFound",
    "StorageProvider",
    "StoredObject",
    "build_document_key",
    "get_storage_provider",
]
