"""Local storage provider contract: roundtrip save/open/delete, not-found,
delete idempotency, traversal guard (docs/ARCHITECTURE.md Â§7.1)."""

import uuid

import pytest

from app.adapters.storage import get_storage_provider
from app.adapters.storage.base import StorageObjectNotFound, build_document_key
from app.adapters.storage.local import LocalFilesystemProvider
from app.core.config import Settings


def test_local_storage_roundtrips_save_open_delete(tmp_path):
    provider = LocalFilesystemProvider(tmp_path / "documents")
    key = build_document_key(uuid.uuid4(), uuid.uuid4(), "cafebabe" * 8, ".bin")

    stored = provider.save(key, b"veripay-bytes", "application/pdf")
    assert stored.key == key
    assert stored.size_bytes == len(b"veripay-bytes")
    assert stored.content_type == "application/pdf"

    assert provider.exists(key) is True
    with provider.open(key) as handle:
        assert handle.read() == b"veripay-bytes"

    provider.delete(key)
    assert provider.exists(key) is False

    provider.delete(key)  # idempotent
    with pytest.raises(StorageObjectNotFound):
        provider.open(key)


def test_local_storage_rejects_path_traversal(tmp_path):
    provider = LocalFilesystemProvider(tmp_path)

    with pytest.raises(ValueError):
        provider.put("../escaped.txt", b"x", "text/plain")
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_storage_factory_default_is_local(tmp_path):
    settings = Settings(storage_local_root=str(tmp_path / "docs"))
    provider = get_storage_provider(settings)

    assert isinstance(provider, LocalFilesystemProvider)
