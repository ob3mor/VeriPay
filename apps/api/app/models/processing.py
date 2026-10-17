"""Durable processing jobs (docs/DATABASE.md — processing_jobs).

A job row is the unit of work for every asynchronous machine step (OCR
extraction, duplicate scan, assessment). Design goals:

- **Durable state**: the state machine lives in the database, so it survives
  restarts and can be inspected/retried via the API — no fire-and-forget
  in-process tasks.
- **Idempotent retries**: re-enqueueing with the same idempotency_key returns
  the existing job instead of duplicating work (unique per org+type+key).
- **Backend-agnostic**: the ProcessingBackend seam (app/adapters/processing)
  decides WHERE jobs execute — inline (default; scale-to-zero cloud demo),
  Celery/Redis (optional local worker), or a future cloud mechanism.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    DateTime,
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
from app.core.enums import ProcessingStatus


class ProcessingJob(TimestampMixin, Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "job_type",
            "idempotency_key",
            name="uq_pj_org_type_key",
        ),
        Index("ix_pj_org_status", "organization_id", "status"),
        Index("ix_pj_org_document", "organization_id", "document_id"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    document_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    invoice_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id"), nullable=True
    )
    # Caller-defined dedup key (e.g. f"ocr:{document_id}:{version}").
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProcessingStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Which backend owns/executes this job ("inline", "celery", ...).
    backend: Mapped[str] = mapped_column(String(32), nullable=False, default="inline")
