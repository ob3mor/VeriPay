"""Document/extraction response schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    kind: str
    vendor_id: uuid.UUID | None
    file_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    processing_status: str
    uploaded_by: uuid.UUID
    # storage_key is deliberately NOT serialized — it is server-side only.


class ExtractionFieldOut(BaseModel):
    id: uuid.UUID
    field_name: str
    field_value: str | None
    confidence: float | None
    evidence_spans: list
    verification_status: str
    verified_value: str | None
    # Additive (Prompt-02): typed normal form + who/when verified.
    normalized_value: dict | None = None
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None


class ExtractionResultOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    extraction_version: str
    ocr_provider: str | None
    status: str
    error: str | None
    # Additive (Prompt-02): provider provenance + validation summary.
    provider_meta: dict | None = None
    validation_summary: dict | None = None


class ExtractionFieldReviewIn(BaseModel):
    """Human field review (R3): confirm the extracted value, or correct it.

    On ``correct`` a non-empty ``verified_value`` is mandatory; the original
    extraction is preserved and the human's value lands in verified_value.
    """

    action: Literal["confirm", "correct"]
    verified_value: str | None = None


class ProcessedDocumentOut(DocumentOut):
    """Upload/process response including the inline processing outcome."""

    job_id: uuid.UUID | None = None
    job_status: str | None = None
    deduplicated: bool = False
