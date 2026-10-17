"""Local filesystem StorageProvider — the default backend on this machine.

Files live under the configured root (default ``./data/documents``); keys are
org-scoped and path-traversal-checked.
"""

from pathlib import Path
from typing import BinaryIO

from app.adapters.storage.base import (
    StoredObject,
    StorageKeyError,
    StorageObjectNotFound,
)

_DEFAULT_CONTENT_TYPE = "application/octet-stream"


class LocalFilesystemProvider:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        candidate = (self._root / key).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageKeyError(f"storage key escapes provider root: {key!r}")
        return candidate

    def put(
        self, key: str, data: bytes, content_type: str = _DEFAULT_CONTENT_TYPE
    ) -> StoredObject:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    def save(
        self, key: str, data: bytes, content_type: str = _DEFAULT_CONTENT_TYPE
    ) -> StoredObject:
        return self.put(key, data, content_type)

    def open(self, key: str) -> BinaryIO:
        path = self._path_for(key)
        if not path.is_file():
            raise StorageObjectNotFound(key)
        return path.open("rb")

    def delete(self, key: str) -> None:
        # Idempotent: missing_ok swallows the not-found case.
        self._path_for(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()

    def temporary_url(self, key: str, ttl_s: int) -> str | None:
        return None  # not supported by the local filesystem provider
