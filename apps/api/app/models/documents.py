"""Documents, extraction results, and per-field evidence (docs/DATABASE.md).

Bytes are never stored in the database — only ``storage_provider`` +
``storage_key``; bytes move exclusively through the StorageProvider seam
(docs/ARCHITECTURE.md §7.1).

R3: extracted fields carry evidence spans and confidence; NULL confidence
behaves like "below gate" and must never become confident fraud evidence.

Processing states (documents.processing_status, extraction_results.status,
processing_jobs.status) all use ProcessingStatus and are transitioned only
through guarded service functions — retries are idempotent.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.core.enums import ExtractionFieldVerificationStatus, ProcessingStatus


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        # Per-org content dedup: identical bytes re-uploaded within an org
        # return the same document row.
        UniqueConstraint("organization_id", "sha256", name="uq_document_org_sha256"),
        Index("ix_document_org_kind", "organization_id", "kind"),
        Index("ix_document_org_vendor", "organization_id", "vendor_id"),
        Index("ix_document_org_processing", "organization_id", "processing_status"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # Vendor context for non-invoice documents (bank letters, statements).
    vendor_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendors.id"), nullable=True, index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Validated against an allowlist (mime + magic bytes) at upload time.
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # "local" | "minio" | "azure_blob" — which adapter wrote the bytes.
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # Tenant-prefixed object key {org_id}/{document_id}/{sha256}{ext}.
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # Durable processing state machine (guarded transitions; idempotent retry).
    processing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProcessingStatus.PENDING.value
    )
    processing_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )


class ExtractionResult(TimestampMixin, Base):
    """One extraction run over one document (the umbrella record).

    Re-extraction with the SAME ``extraction_version`` upserts: its result row
    is reused and its field rows replaced in place. Different versions
    coexist side by side.
    """

    __tablename__ = "extraction_results"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "document_id",
            "extraction_version",
            name="uq_er_org_doc_version",
        ),
        Index("ix_er_org_document", "organization_id", "document_id"),
        Index("ix_er_org_status", "organization_id", "status"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    document_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    # Extractor + model version.
    extraction_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ocr_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProcessingStatus.PENDING.value
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ExtractionField(TimestampMixin, Base):
    """One extracted field of one extraction result — the R3 evidence unit."""

    __tablename__ = "extraction_fields"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "extraction_result_id",
            "field_name",
            name="uq_efld_org_result_field",
        ),
        Index("ix_efld_org_result", "organization_id", "extraction_result_id"),
        Index("ix_efld_org_field", "organization_id", "field_name"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    extraction_result_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("extraction_results.id"),
        nullable=False,
        index=True,
    )
    # Set when an invoice record is created/bound from this document.
    invoice_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id", use_alter=True), nullable=True
    )
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    field_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Typed normal form, e.g. {"value": "1250.00", "currency": "EUR"}.
    normalized_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 0..1; NULL when the provider gives none — NULL behaves like "below gate".
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # [{page, block, text, bbox, confidence}] — provenance humans inspect.
    evidence_spans: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    verification_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ExtractionFieldVerificationStatus.UNVERIFIED.value,
    )
    # The human's value when corrected.
    verified_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
