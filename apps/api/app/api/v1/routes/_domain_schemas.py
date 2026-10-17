"""Schemas for procurement, fraud, cases, and audit surfaces."""

import uuid

from pydantic import BaseModel, Field, model_validator


# -------------------------------------------------------- purchase orders ---
class PurchaseOrderIn(BaseModel):
    po_number: str = Field(min_length=1, max_length=100)
    vendor_id: uuid.UUID | None = None
    amount: str | None = Field(default=None, description="Decimal string, e.g. '1250.00'")
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    issued_at: str | None = None
    description: str | None = None


class PurchaseOrderOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    po_number: str
    vendor_id: uuid.UUID | None
    amount: str | None
    currency: str | None
    issued_at: str | None
    status: str


# ---------------------------------------------------------------- invoices ---
class InvoiceIn(BaseModel):
    invoice_number: str = Field(min_length=1, max_length=100)
    vendor_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    subtotal_amount: str | None = None
    tax_amount: str | None = None
    total_amount: str | None = None
    remittance_bank_name_raw: str | None = Field(default=None, max_length=200)
    remittance_account_raw: str | None = Field(default=None, max_length=120)
    source_document_id: uuid.UUID | None = None


class InvoiceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    invoice_number: str
    vendor_id: uuid.UUID | None
    purchase_order_id: uuid.UUID | None
    invoice_date: str | None
    currency: str | None
    total_amount: str | None
    status: str
    remittance_bank_name_raw: str | None
    remittance_account_last4: str | None = None
    payment_account_id: uuid.UUID | None


class ResolveVendorIn(BaseModel):
    vendor_id: uuid.UUID | None = None
    vendor_name: str | None = Field(default=None, max_length=200)


# ----------------------------------------------------------- line items ---
class LineItemIn(BaseModel):
    description: str | None = Field(default=None, max_length=2000)
    quantity: str | None = Field(default=None, description="Decimal string, e.g. '2'")
    unit_price: str | None = Field(default=None, description="Decimal string, e.g. '19.99'")
    line_total: str | None = Field(default=None, description="Decimal string, e.g. '39.98'")


class LineItemOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    invoice_id: uuid.UUID
    position: int
    description: str | None
    quantity: str | None
    unit_price: str | None
    line_total: str | None


# ------------------------------------------------------------------ fraud ---
class FraudFindingOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    signal_type: str
    severity: str
    message: str
    field_refs: list
    evidence_refs: list
    disposition: str
    dispositioned_by: uuid.UUID | None = None
    dispositioned_at: str | None = None


class FindingDispositionIn(BaseModel):
    """Human disposition of one signal (reviewer/org_admin).

    A NON-EMPTY reason (``reason``, or the legacy ``note`` alias) is
    mandatory: an override without a recorded reason is refused. The optional
    ``case_id`` anchors the generated review-actions row to a case; without
    it the invoice's latest case is used, or a case-less review action is
    written."""

    disposition: str = Field(max_length=32)
    reason: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    case_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _reason_required(self) -> "FindingDispositionIn":
        text = (self.reason or self.note or "").strip()
        if not text:
            raise ValueError(
                "A disposition reason is mandatory (reason or note)."
            )
        self.reason = text
        return self


class EvidenceMatchOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    source_entity_type: str
    source_entity_id: uuid.UUID
    target_entity_type: str
    target_entity_id: uuid.UUID
    match_kind: str
    similarity_score: float
    matched_fields: dict
    status: str
    reviewed_by: uuid.UUID | None = None
    reviewed_at: str | None = None


class MatchReviewIn(BaseModel):
    """Human review decision on one evidence match (reviewer/org_admin).

    A NON-EMPTY reason (``reason``, or the legacy ``note`` alias) is
    mandatory."""

    status: str = Field(max_length=32)
    reason: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    case_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _reason_required(self) -> "MatchReviewIn":
        text = (self.reason or self.note or "").strip()
        if not text:
            raise ValueError("A review reason is mandatory (reason or note).")
        self.reason = text
        return self


class FraudAssessmentOut(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    risk_level: str
    risk_score: float | None
    model_version: str
    signals: list
    explanation: list
    status: str
    # The EVC structure (features, weights, contributions, policy_version,
    # result state, overrides) — NULL only for legacy rows.
    evc: dict | None = None
    findings: list[FraudFindingOut] = []


# ------------------------------------------------------------------ cases ---
class CaseIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    severity: str = Field(max_length=32)
    invoice_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    description: str | None = None


class CaseOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    case_number: str
    invoice_id: uuid.UUID | None
    vendor_id: uuid.UUID | None
    title: str
    severity: str
    status: str
    outcome: str | None
    assigned_to: uuid.UUID | None
    # R6 provenance: the assessment that opened the case (auto-opened ones).
    triggering_assessment_id: uuid.UUID | None = None


class CaseAssignIn(BaseModel):
    user_id: uuid.UUID


class CaseCloseIn(BaseModel):
    outcome: str = Field(max_length=32)
    resolution_summary: str = Field(min_length=1)


class ReviewActionIn(BaseModel):
    action_type: str = Field(max_length=32)
    body: str = Field(min_length=1)
    payload: dict | None = None


class ReviewActionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    action_type: str
    body: str
    payload: dict | None
    actor_user_id: uuid.UUID | None


# ------------------------------------------------------------------ audit ---
class AuditEventOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    organization_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    actor_type: str
    action: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    detail: dict | None
    occurred_at: str | None = None


# ------------------------------------------------------------------ stats ---
class DashboardStatsOut(BaseModel):
    """Org-scoped headline counts. Work-queue sizes — never verdicts (R2)."""

    organization_id: uuid.UUID
    total_invoices: int
    needs_review_invoices: int
    open_cases: int
    high_risk_invoices: int
    processing_failures: int


# ------------------------------------------------------------ processing ---
class ProcessingJobOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    job_type: str
    document_id: uuid.UUID | None
    invoice_id: uuid.UUID | None
    idempotency_key: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None
    backend: str
    started_at: str | None = None
    completed_at: str | None = None
