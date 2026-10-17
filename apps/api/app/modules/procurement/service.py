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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import InvoiceStatus, PurchaseOrderStatus
from app.core.errors import AppError, ErrorCode
from app.models import Invoice, InvoiceLineItem, PurchaseOrder, User, Vendor
from app.modules.fraud.evidence import record_duplicate_number_match
from app.modules.vendors.service import fingerprint_account, normalize_vendor_name

# Extraction field names that map onto invoice columns for provenance binding
# (docs/DATABASE.md §9 field_sources + §12 examples). Both the §12 canonical
# names and the extractor's label vocabulary (app/modules/extraction/fields.py)
# are mapped — provenance must survive either dialect. ``po_reference`` is
# deliberately absent: linking a PO is a human resolution decision, never an
# extraction side effect.
_EXTRACTION_FIELD_TO_COLUMN: dict[str, str] = {
    # DATABASE.md §12 canonical names.
    "invoice_number": "invoice_number",
    "invoice_date": "invoice_date",
    "due_date": "due_date",
    "total_amount": "total_amount",
    "subtotal_amount": "subtotal_amount",
    "tax_amount": "tax_amount",
    "currency": "currency",
    "remittance_bank_name": "remittance_bank_name_raw",
    "remittance_account": "remittance_account_raw",
    # The extractor's label vocabulary (fields.py).
    "total": "total_amount",
    "subtotal": "subtotal_amount",
    "tax": "tax_amount",
    "iban": "remittance_account_raw",
    "bank_name": "remittance_bank_name_raw",
}


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
    """Create an invoice; duplicate numbers are recorded, never rejected.

    With ``source_document_id`` the invoice binds the document's extraction
    provenance (R3): extraction fields whose names map to invoice columns are
    stamped into ``field_sources`` with ``origin: "extracted"``, so the fraud
    gate and the field_provenance_conflict signal are reachable through the
    API. Invoice columns stay the source of truth — binding never overwrites
    a human-entered value; it only attaches provenance.
    """
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
    if source_document_id is not None:
        # Org-scoped: attaching another tenant's document id is a 404, not a
        # silent cross-tenant reference (API.md §5).
        from app.modules.documents.service import get_document

        get_document(db, org_id=org_id, document_id=source_document_id)

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

    if source_document_id is not None:
        _bind_extracted_sources(db, invoice)
    if vendor_id is not None:
        _record_number_duplicates(db, invoice)

    db.commit()
    return invoice


def _bind_extracted_sources(db: Session, invoice: Invoice) -> None:
    """Stamp extracted provenance from the bound document's latest extraction.

    For each mapped extraction field carrying a value:
    - a column the human did NOT enter gains ``origin: "extracted"`` with the
      field id + confidence at ingest + extracted value;
    - a human-entered column KEEPS ``origin: "manual"`` (the column wins) but
      also carries the extracted provenance, so a disagreement later surfaces
      as ``field_provenance_conflict`` (fraud service; ARCHITECTURE §8.3).
    Extraction fields of the bound document are linked to the invoice row.
    """
    from app.modules.extraction import service as extraction_service

    result = extraction_service.get_result(
        db, org_id=invoice.organization_id, document_id=invoice.source_document_id
    )
    if result is None:
        return
    sources = dict(invoice.field_sources or {})
    for field in extraction_service.list_fields(db, result_id=result.id):
        column = _EXTRACTION_FIELD_TO_COLUMN.get(field.field_name)
        if column is None or field.field_value is None:
            continue
        provenance = {
            "extracted_field_id": str(field.id),
            "confidence_at_ingest": field.confidence,
            "extracted_value": field.field_value,
        }
        existing = sources.get(column)
        if existing is None:
            sources[column] = {"origin": "extracted", **provenance}
        else:
            sources[column] = {**existing, **provenance}
        field.invoice_id = invoice.id
    invoice.field_sources = sources


def create_line_item(
    db: Session, *, org_id: object, invoice_id: object, actor: User,
    description: str | None, quantity: Decimal | None,
    unit_price: Decimal | None, line_total: Decimal | None,
) -> InvoiceLineItem:
    """Append one line item; positions are per-invoice sequence numbers."""
    invoice = get_invoice(db, org_id=org_id, invoice_id=invoice_id)
    if invoice.status == InvoiceStatus.CLOSED.value:
        raise AppError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            "A closed invoice cannot be modified.",
        )
    last_position = db.scalar(
        select(func.max(InvoiceLineItem.position)).where(
            InvoiceLineItem.organization_id == org_id,
            InvoiceLineItem.invoice_id == invoice.id,
        )
    )
    row = InvoiceLineItem(
        organization_id=org_id,
        invoice_id=invoice.id,
        position=(last_position or 0) + 1,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        line_total=line_total,
    )
    db.add(row)
    db.commit()
    return row


def list_line_items(
    db: Session, *, org_id: object, invoice_id: object
) -> list[InvoiceLineItem]:
    get_invoice(db, org_id=org_id, invoice_id=invoice_id)  # org-scoped 404 first
    return list(
        db.scalars(
            select(InvoiceLineItem)
            .where(
                InvoiceLineItem.organization_id == org_id,
                InvoiceLineItem.invoice_id == invoice_id,
            )
            .order_by(InvoiceLineItem.position)
        )
    )


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
