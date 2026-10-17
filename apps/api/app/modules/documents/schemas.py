"""Document/extraction response schemas."""

import uuid

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


class ExtractionResultOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    extraction_version: str
    ocr_provider: str | None
    status: str
    error: str | None


class ProcessedDocumentOut(DocumentOut):
    """Upload/process response including the inline processing outcome."""

    job_id: uuid.UUID | None = None
    job_status: str | None = None
    deduplicated: bool = False
