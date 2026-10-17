"""Purchase orders, invoices, line items (docs/DATABASE.md §8-§10).

There is deliberately NO unique constraint on (organization_id, vendor_id,
invoice_number): duplicate numbers are a fraud *signal* recorded in
``evidence_matches`` with ``needs_review`` — never a 409 rejection.
"""

from datetime import date
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.core.enums import InvoiceStatus, PurchaseOrderStatus


class PurchaseOrder(TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("organization_id", "po_number", name="uq_po_org_number"),
        Index("ix_po_org_vendor", "organization_id", "vendor_id"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    po_number: Mapped[str] = mapped_column(String(100), nullable=False)
    # POs may be ingested before vendor resolution.
    vendor_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendors.id"), nullable=True
    )
    # NULL until extraction/manual entry completes.
    amount: Mapped[object | None] = mapped_column(Numeric(14, 2), nullable=True)
    # ISO 4217.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PurchaseOrderStatus.DRAFT.value
    )
    # Set when the PO was ingested by upload.
    source_document_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    created_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index(
            "ix_invoice_org_vendor_number",
            "organization_id",
            "vendor_id",
            "invoice_number",
        ),
        Index("ix_invoice_org_status", "organization_id", "status"),
        Index("ix_invoice_org_number", "organization_id", "invoice_number"),
        Index(
            "ix_invoice_org_remittance_fp",
            "organization_id",
            "remittance_account_fingerprint",
        ),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    # NULL until vendor resolution — NULL is a state, not an error.
    vendor_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendors.id"), nullable=True
    )
    # NULL → missing_evidence signal (R4), never fraud by itself.
    purchase_order_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True
    )
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    subtotal_amount: Mapped[object | None] = mapped_column(Numeric(14, 2), nullable=True)
    tax_amount: Mapped[object | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_amount: Mapped[object | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Pay-to bank name as printed on the invoice.
    remittance_bank_name_raw: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    # Pay-to account/IBAN as printed.
    remittance_account_raw: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Normalized fingerprint of the printed details.
    remittance_account_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    # The trusted account matched to the remittance details; NULL (no match)
    # → bank_account_unverified, severity high, forces needs_review (R5).
    payment_account_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendor_bank_accounts.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=InvoiceStatus.RECEIVED.value
    )
    # Per-column provenance: {column: {origin, extracted_field_id, confidence}}.
    # Invoice columns are the source of truth; extracted_fields are provenance.
    field_sources: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_document_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    created_by: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class InvoiceLineItem(TimestampMixin, Base):
    __tablename__ = "invoice_line_items"
    __table_args__ = (
        Index("ix_ili_org_invoice", "organization_id", "invoice_id"),
    )

    id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    invoice_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id"), nullable=False
    )
    # Parse/display order.
    position: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[object | None] = mapped_column(Numeric(14, 4), nullable=True)
    # Fractional unit prices are legitimate.
    unit_price: Mapped[object | None] = mapped_column(Numeric(14, 4), nullable=True)
    line_total: Mapped[object | None] = mapped_column(Numeric(14, 2), nullable=True)
