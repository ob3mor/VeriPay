"""Schemas for procurement, fraud, cases, and audit surfaces."""

import uuid

from pydantic import BaseModel, Field


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


class FraudAssessmentOut(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    risk_level: str
    risk_score: float | None
    model_version: str
    signals: list
    explanation: list
    status: str
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
