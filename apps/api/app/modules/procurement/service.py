"""Procurement logic: purchase orders, invoices, vendor resolution.

Key behaviors:
- Invoices NEVER reject duplicate numbers: a second invoice with the same
  (org, vendor, number) is a fraud SIGNAL — an ``evidence_matches`` row plus
  ``needs_review`` — never a 409 (docs/API.md §2).
- Remittance details printed on the invoice are fingerprinted with the same
  normalization as trusted accounts, so the fraud module can match them.
- ``field_sources`` stamps every human-entered column ``origin: manual``;
  extracted provenance is attached at binding time.
- resolve-vendor is org-scoped and re-runs the duplicate check when the
  vendor becomes known.
"""

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import InvoiceStatus, PurchaseOrderStatus
from app.core.errors import AppError, ErrorCode
from app.models import Invoice, PurchaseOrder, User, Vendor
from app.modules.fraud.evidence import record_duplicate_number_match
from app.modules.vendors.service import fingerprint_account, normalize_vendor_name


def get_purchase_order(db: Session, *, org_id: object, po_id: object) -> PurchaseOrder:
    po = db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.id == po_id, PurchaseOrder.organization_id == org_id
        )
    )
    if po is None:
        raise AppError(ErrorCode.NOT_FOUND, "Purchase order not found.")
    return po


def create_purchase_order(
    db: Session, *, org_id: object, actor: User, po_number: str,
    vendor_id: object | None, amount: Decimal | None, currency: str | None,
    issued_at, description: str | None,
) -> PurchaseOrder:
    duplicate = db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == org_id,
            PurchaseOrder.po_number == po_number,
        )
    )
    if duplicate is not None:
        raise AppError(ErrorCode.CONFLICT, "A purchase order with this number exists.")
    if vendor_id is not None:
        vendor = db.scalar(
            select(Vendor).where(
                Vendor.id == vendor_id, Vendor.organization_id == org_id
            )
        )
        if vendor is None:
            raise AppError(ErrorCode.NOT_FOUND, "Vendor not found.")
    po = PurchaseOrder(
        organization_id=org_id,
        po_number=po_number.strip(),
        vendor_id=vendor_id,
        amount=amount,
        currency=currency,
        issued_at=issued_at,
        description=description,
        status=PurchaseOrderStatus.ACTIVE.value,
        created_by=actor.id,
    )
    db.add(po)
    db.commit()
    return po


def list_purchase_orders(
    db: Session, *, org_id: object, limit: int, offset: int
) -> tuple[list[PurchaseOrder], int]:
    base = select(PurchaseOrder).where(PurchaseOrder.organization_id == org_id)
    total = len(db.scalars(base).all())
    rows = db.scalars(
        base.order_by(PurchaseOrder.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return list(rows), total


def get_invoice(db: Session, *, org_id: object, invoice_id: object) -> Invoice:
    invoice = db.scalar(
        select(Invoice).where(
            Invoice.id == invoice_id, Invoice.organization_id == org_id
        )
    )
    if invoice is None:
        raise AppError(ErrorCode.NOT_FOUND, "Invoice not found.")
    return invoice


def create_invoice(
    db: Session, *, org_id: object, actor: User, invoice_number: str,
    vendor_id: object | None, purchase_order_id: object | None,
    invoice_date, due_date, currency: str | None,
    subtotal_amount: Decimal | None, tax_amount: Decimal | None,
    total_amount: Decimal | None,
    remittance_bank_name_raw: str | None, remittance_account_raw: str | None,
    source_document_id: object | None,
) -> Invoice:
    """Create an invoice; duplicate numbers are recorded, never rejected."""
    if vendor_id is not None:
        vendor = db.scalar(
            select(Vendor).where(
                Vendor.id == vendor_id, Vendor.organization_id == org_id
            )
        )
        if vendor is None:
            raise AppError(ErrorCode.NOT_FOUND, "Vendor not found.")
    if purchase_order_id is not None:
        get_purchase_order(db, org_id=org_id, po_id=purchase_order_id)

    field_sources: dict[str, dict] = {}
    for column, value in (
        ("invoice_number", invoice_number),
        ("total_amount", total_amount),
        ("subtotal_amount", subtotal_amount),
        ("tax_amount", tax_amount),
        ("remittance_account_raw", remittance_account_raw),
    ):
        if value is not None:
            field_sources[column] = {"origin": "manual"}

    invoice = Invoice(
        organization_id=org_id,
        vendor_id=vendor_id,
        purchase_order_id=purchase_order_id,
        invoice_number=invoice_number.strip(),
        invoice_date=invoice_date,
        due_date=due_date,
        currency=currency,
        subtotal_amount=subtotal_amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
        remittance_bank_name_raw=remittance_bank_name_raw,
        remittance_account_raw=remittance_account_raw,
        remittance_account_fingerprint=(
            fingerprint_account(remittance_account_raw)
            if remittance_account_raw
            else None
        ),
        status=InvoiceStatus.RECEIVED.value,
        field_sources=field_sources,
        source_document_id=source_document_id,
        created_by=actor.id,
    )
    db.add(invoice)
    db.flush()  # id needed for evidence matches

    if vendor_id is not None:
        _record_number_duplicates(db, invoice)

    db.commit()
    return invoice


def _record_number_duplicates(db: Session, invoice: Invoice) -> int:
    """Same org+vendor+number on an earlier invoice → evidence match + review."""
    if invoice.vendor_id is None:
        return 0
    others = db.scalars(
        select(Invoice).where(
            Invoice.organization_id == invoice.organization_id,
            Invoice.vendor_id == invoice.vendor_id,
            Invoice.invoice_number == invoice.invoice_number,
            Invoice.id != invoice.id,
        )
    ).all()
    created = 0
    for other in others:
        record_duplicate_number_match(
            db, source=invoice, target=other, module="procurement"
        )
        created += 1
    if created and invoice.status == InvoiceStatus.RECEIVED.value:
        invoice.status = InvoiceStatus.NEEDS_REVIEW.value
    return created


def list_invoices(
    db: Session, *, org_id: object, limit: int, offset: int
) -> tuple[list[Invoice], int]:
    base = select(Invoice).where(Invoice.organization_id == org_id)
    total = len(db.scalars(base).all())
    rows = db.scalars(
        base.order_by(Invoice.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return list(rows), total


def resolve_vendor(
    db: Session, *, org_id: object, invoice_id: object, vendor_id: object | None,
    vendor_name: str | None, actor: User,
) -> Invoice:
    """Attach the vendor by id, or by exact normalized-name match.

    No fuzzy guessing here: an unmatched name raises 422 and the invoice
    stays unresolved — resolution is a human decision (docs/ARCHITECTURE §4
    step 3).
    """
    invoice = get_invoice(db, org_id=org_id, invoice_id=invoice_id)
    if invoice.status == InvoiceStatus.CLOSED.value:
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION, "A closed invoice cannot be modified."
        )
    if vendor_id is not None:
        vendor = db.scalar(
            select(Vendor).where(
                Vendor.id == vendor_id, Vendor.organization_id == org_id
            )
        )
        if vendor is None:
            raise AppError(ErrorCode.NOT_FOUND, "Vendor not found.")
    elif vendor_name is not None:
        normalized = normalize_vendor_name(vendor_name)
        vendor = db.scalar(
            select(Vendor).where(
                Vendor.organization_id == org_id,
                Vendor.normalized_name == normalized,
            )
        )
        if vendor is None:
            raise AppError(
                ErrorCode.BUSINESS_RULE_VIOLATION,
                "No vendor with this name exists — create the vendor first; "
                "unresolved vendors are never guessed.",
            )
    else:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "Provide vendor_id or vendor_name."
        )

    invoice.vendor_id = vendor.id
    _record_number_duplicates(db, invoice)
    db.commit()
    return invoice
