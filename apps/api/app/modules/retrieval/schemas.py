"""Response schemas for the retrieval surfaces (GET /invoices/{id}/evidence).

Serialization-only path — storage keys, full account numbers and internal
flags never appear (API.md §5.8); account data is limited to what the
indexing projection already exposes (holder, bank, country, last4-only
identifiers, verification record).
"""

import uuid

from pydantic import BaseModel, Field


class DocumentLocationOut(BaseModel):
    """Where in a source document the evidence lives (R3 provenance)."""

    document_id: uuid.UUID | None = None
    page: int | None = None
    bbox: list[float] | None = None


class EvidenceItemOut(BaseModel):
    """One citable evidence item (Prompt-03 §7)."""

    entity_type: str = Field(
        description="Evidence category: vendor | vendor_bank_account | invoice | "
        "purchase_order | extraction_field | review_action"
    )
    entity_id: uuid.UUID
    title: str
    matched_field: str | None = None
    match_explanation: str
    trust_status: str
    retrieval_score: float
    fused_score: float
    techniques: list[str]
    document_location: DocumentLocationOut | None = None
    provenance: dict = Field(default_factory=dict)
    record_version: str | None = None


class GraphGapOut(BaseModel):
    """A missing relationship (R4-capped) or a structured data disagreement."""

    kind: str  # "missing" | "contradiction"
    relationship: str
    message: str
    severity: str
    detail: dict = Field(default_factory=dict)


class EvidenceMetaOut(BaseModel):
    backend: str
    weights: dict[str, float]
    seeds: list[str]
    latency_ms: float


class InvoiceEvidenceOut(BaseModel):
    evidence: list[EvidenceItemOut]
    gaps: list[GraphGapOut]
    contradictions: list[GraphGapOut]
    meta: EvidenceMetaOut
