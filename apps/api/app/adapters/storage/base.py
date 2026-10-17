"""StorageProvider protocol (docs/ARCHITECTURE.md §7.1).

Structural ``typing.Protocol`` — no inheritance coupling. Every
implementation must pass the same contract tests (roundtrip, not-found,
delete idempotency, content-type preservation).
"""

from dataclasses import dataclass
from typing import BinaryIO, Protocol, runtime_checkable
from uuid import UUID


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str


class StorageObjectNotFound(Exception):
    """The referenced object does not exist."""


class StorageKeyError(ValueError):
    """A key would escape the provider root (path traversal)."""


@runtime_checkable
class StorageProvider(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    # Alias of ``put`` (used interchangeably by callers/docs).
    def save(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    def open(self, key: str) -> BinaryIO:
        """Read handle; raises StorageObjectNotFound when absent."""
        ...

    def delete(self, key: str) -> None:
        """Idempotent — deleting a missing object is a no-op."""
        ...

    def exists(self, key: str) -> bool: ...

    def temporary_url(self, key: str, ttl_s: int) -> str | None:
        """Presigned/read URL, or None where unsupported."""
        ...


def build_document_key(
    org_id: UUID | str,
    document_id: UUID | str,
    sha256_hex: str,
    extension: str = "",
) -> str:
    """Tenant-prefixed object key: {org_id}/{document_id}/{sha256}{ext}."""
    ext = extension if (not extension or extension.startswith(".")) else f".{extension}"
    return f"{org_id}/{document_id}/{sha256_hex}{ext}"
