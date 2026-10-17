"""Document ingestion: validation, hashing, tenant storage, metadata.

Upload contract (owner's Phase 2 brief):
- PDF / PNG / JPEG only — mime allowlist AND magic-byte signature checks
  (a renamed .exe must not pass as an invoice).
- Size limit (settings.upload_max_bytes, default 10 MiB).
- SHA-256 over the bytes; per-org content dedup — re-uploading identical
  bytes returns the SAME document (200, not 201).
- Tenant-prefixed storage keys via the StorageProvider seam.
- processing_status state machine; bytes never stored in the database.
"""

import hashlib
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.storage.base import build_document_key
from app.core.config import get_settings
from app.core.enums import DocumentKind, ProcessingStatus
from app.core.errors import AppError, ErrorCode
from app.models import Document, User, Vendor

# (mime, magic prefix) pairs — both must match, so extension lies fail.
_SIGNATURES: tuple[tuple[str, bytes], ...] = (
    ("application/pdf", b"%PDF-"),
    ("image/png", b"\x89PNG\r\n\x1a\n"),
    ("image/jpeg", b"\xff\xd8\xff"),
)
_ALLOWED_MIMES = {mime for mime, _ in _SIGNATURES}


def _detect_mime(data: bytes, declared: str) -> str:
    """Return the canonical mime when bytes AND declaration agree."""
    if declared not in _ALLOWED_MIMES:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Unsupported file type. Allowed: PDF, PNG, JPEG.",
        )
    matched = None
    for mime, magic in _SIGNATURES:
        if data.startswith(magic):
            matched = mime
            break
    if matched is None:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "File content does not match its declared type (signature check failed).",
        )
    if matched != declared:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Declared content type does not match the file signature.",
        )
    return matched


def get_document(db: Session, *, org_id: object, document_id: object) -> Document:
    doc = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.organization_id == org_id
        )
    )
    if doc is None:
        raise AppError(ErrorCode.NOT_FOUND, "Document not found.")
    return doc


def list_documents(
    db: Session, *, org_id: object, limit: int, offset: int
) -> tuple[list[Document], int]:
    base = select(Document).where(Document.organization_id == org_id)
    total = len(db.scalars(base).all())
    rows = db.scalars(
        base.order_by(Document.created_at.desc(), Document.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), total


def ingest_upload(
    db: Session,
    *,
    org_id: object,
    actor: User,
    upload: UploadFile,
    kind: DocumentKind,
    vendor_id: object | None = None,
) -> tuple[Document, bool]:
    """Validate + persist one upload. Returns (document, created).

    created=False means per-org dedup returned the existing document for
    identical bytes.
    """
    data = upload.file.read()
    limit = get_settings().upload_max_bytes
    if not data:
        raise AppError(ErrorCode.VALIDATION_ERROR, "The uploaded file is empty.")
    if len(data) > limit:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"File exceeds the {limit // (1024 * 1024)} MiB limit.",
        )
    declared = upload.content_type or "application/octet-stream"
    mime = _detect_mime(data, declared)

    if vendor_id is not None:
        vendor = db.scalar(
            select(Vendor).where(
                Vendor.id == vendor_id, Vendor.organization_id == org_id
            )
        )
        if vendor is None:
            raise AppError(ErrorCode.NOT_FOUND, "Vendor not found.")

    sha256 = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(Document).where(
            Document.organization_id == org_id, Document.sha256 == sha256
        )
    )
    if existing is not None:
        return existing, False

    settings = get_settings()
    from app.adapters.storage.local import LocalFilesystemProvider

    provider = _build_storage(settings)
    document_id = uuid4()
    extension = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
    }.get(mime, "")
    key = build_document_key(org_id, document_id, sha256, extension)
    provider.put(key, data, mime)

    document = Document(
        id=document_id,
        organization_id=org_id,
        kind=kind.value,
        vendor_id=vendor_id,
        file_name=upload.filename or f"upload{extension}",
        mime_type=mime,
        size_bytes=len(data),
        sha256=sha256,
        storage_provider=settings.storage_backend,
        storage_key=key,
        processing_status=ProcessingStatus.PENDING.value,
        uploaded_by=actor.id,
    )
    db.add(document)
    db.commit()
    return document, True


def _build_storage(settings):
    if settings.storage_backend == "minio":
        from app.adapters.storage.s3 import MinIOS3Provider

        return MinIOS3Provider(settings)
    from app.adapters.storage.local import LocalFilesystemProvider

    return LocalFilesystemProvider(settings.storage_local_root)


def open_document_bytes(db: Session, document: Document) -> BytesIO:
    """Protected download path: the key comes from the DB row, never from the
    client; cross-org documents never resolve to a row (404 upstream)."""
    settings = get_settings()
    provider = _build_storage(settings)
    try:
        return provider.open(document.storage_key)
    except Exception as exc:  # storage object missing — never a 500
        raise AppError(
            ErrorCode.NOT_FOUND, "Stored file is missing from document storage."
        ) from exc


def set_processing_status(
    db: Session, document: Document, new_status: str, *, error: str | None = None
) -> Document:
    """Same guarded machine as processing jobs, on the document row."""
    allowed: dict[str, set[str]] = {
        ProcessingStatus.PENDING.value: {
            ProcessingStatus.PROCESSING.value,
            ProcessingStatus.REQUIRES_MANUAL_INPUT.value,
        },
        ProcessingStatus.PROCESSING.value: {
            ProcessingStatus.COMPLETED.value,
            ProcessingStatus.FAILED.value,
            ProcessingStatus.REQUIRES_MANUAL_INPUT.value,
        },
        ProcessingStatus.FAILED.value: {ProcessingStatus.PENDING.value},
        ProcessingStatus.REQUIRES_MANUAL_INPUT.value: {ProcessingStatus.PENDING.value},
        ProcessingStatus.COMPLETED.value: set(),
    }
    if new_status not in allowed.get(document.processing_status, set()):
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            f"Cannot transition document from {document.processing_status} to {new_status}.",
        )
    document.processing_status = new_status
    if new_status == ProcessingStatus.FAILED.value:
        document.processing_error = error
        document.processing_attempts += 1
    elif new_status == ProcessingStatus.COMPLETED.value:
        document.processing_completed_at = datetime.now(timezone.utc)
        document.processing_error = None
    db.commit()
    return document
