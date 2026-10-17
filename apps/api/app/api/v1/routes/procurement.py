"""Procurement routes: purchase orders, invoices, vendor resolution."""

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError, ErrorCode
from app.modules.audit.service import AuditContext, record_audit
from app.modules.procurement import service
from app.models import User
from app.tenancy.deps import get_current_user
from app.tenancy.permissions import CAN_CONTRIBUTE, require_roles
from app.api.v1.routes import _domain_schemas as ds

router = APIRouter(tags=["procurement"])

_contributor = require_roles(*CAN_CONTRIBUTE)

_Db = Annotated[Session, Depends(get_db)]
_PageLimit = Annotated[int, Query(ge=1, le=100)]
_PageOffset = Annotated[int, Query(ge=0)]


def _dec(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"Invalid decimal value: {value!r}") from exc


def _date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"Invalid date: {value!r}") from exc


def _po_out(po) -> ds.PurchaseOrderOut:
    return ds.PurchaseOrderOut(
        id=po.id,
        po_number=po.po_number,
        vendor_id=po.vendor_id,
        amount=str(po.amount) if po.amount is not None else None,
        currency=po.currency,
        issued_at=po.issued_at.isoformat() if po.issued_at else None,
        status=po.status,
    )


def _invoice_out(inv) -> ds.InvoiceOut:
    return ds.InvoiceOut(
        id=inv.id,
        invoice_number=inv.invoice_number,
        vendor_id=inv.vendor_id,
        purchase_order_id=inv.purchase_order_id,
        invoice_date=inv.invoice_date.isoformat() if inv.invoice_date else None,
        currency=inv.currency,
        total_amount=str(inv.total_amount) if inv.total_amount is not None else None,
        status=inv.status,
        remittance_bank_name_raw=inv.remittance_bank_name_raw,
        remittance_account_last4=(
            inv.remittance_account_raw[-4:] if inv.remittance_account_raw else None
        ),
        payment_account_id=inv.payment_account_id,
    )


@router.post("/purchase-orders", response_model=ds.PurchaseOrderOut, status_code=201)
def create_purchase_order(
    payload: ds.PurchaseOrderIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
) -> ds.PurchaseOrderOut:
    po = service.create_purchase_order(
        db,
        org_id=actor.organization_id,
        actor=actor,
        po_number=payload.po_number,
        vendor_id=payload.vendor_id,
        amount=_dec(payload.amount),
        currency=payload.currency,
        issued_at=_date(payload.issued_at),
        description=payload.description,
    )
    record_audit(
        db,
        action="purchase_order.created",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="purchase_order",
        entity_id=po.id,
        detail={"po_number": po.po_number},
        context=AuditContext.from_request(request),
    )
    return _po_out(po)


@router.get("/purchase-orders", response_model=list[ds.PurchaseOrderOut])
def list_purchase_orders(
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
    limit: _PageLimit = 25,
    offset: _PageOffset = 0,
) -> list[ds.PurchaseOrderOut]:
    rows, _t = service.list_purchase_orders(
        db, org_id=actor.organization_id, limit=limit, offset=offset
    )
    return [_po_out(po) for po in rows]


@router.get("/purchase-orders/{po_id}", response_model=ds.PurchaseOrderOut)
def get_purchase_order(
    po_id: uuid.UUID, db: _Db, actor: Annotated[User, Depends(get_current_user)]
) -> ds.PurchaseOrderOut:
    return _po_out(service.get_purchase_order(db, org_id=actor.organization_id, po_id=po_id))


@router.post("/invoices", response_model=ds.InvoiceOut, status_code=201)
def create_invoice(
    payload: ds.InvoiceIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
) -> ds.InvoiceOut:
    """Create an invoice. Duplicate vendor+number is allowed — it becomes an
    evidence match + needs_review (a fraud signal, never a 409)."""
    invoice = service.create_invoice(
        db,
        org_id=actor.organization_id,
        actor=actor,
        invoice_number=payload.invoice_number,
        vendor_id=payload.vendor_id,
        purchase_order_id=payload.purchase_order_id,
        invoice_date=_date(payload.invoice_date),
        due_date=_date(payload.due_date),
        currency=payload.currency,
        subtotal_amount=_dec(payload.subtotal_amount),
        tax_amount=_dec(payload.tax_amount),
        total_amount=_dec(payload.total_amount),
        remittance_bank_name_raw=payload.remittance_bank_name_raw,
        remittance_account_raw=payload.remittance_account_raw,
        source_document_id=payload.source_document_id,
    )
    record_audit(
        db,
        action="invoice.created",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="invoice",
        entity_id=invoice.id,
        detail={"invoice_number": invoice.invoice_number, "status": invoice.status},
        context=AuditContext.from_request(request),
    )
    return _invoice_out(invoice)


@router.get("/invoices", response_model=list[ds.InvoiceOut])
def list_invoices(
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
    limit: _PageLimit = 25,
    offset: _PageOffset = 0,
) -> list[ds.InvoiceOut]:
    rows, _t = service.list_invoices(
        db, org_id=actor.organization_id, limit=limit, offset=offset
    )
    return [_invoice_out(i) for i in rows]


@router.get("/invoices/{invoice_id}", response_model=ds.InvoiceOut)
def get_invoice(
    invoice_id: uuid.UUID, db: _Db, actor: Annotated[User, Depends(get_current_user)]
) -> ds.InvoiceOut:
    return _invoice_out(service.get_invoice(db, org_id=actor.organization_id, invoice_id=invoice_id))


@router.post("/invoices/{invoice_id}/resolve-vendor", response_model=ds.InvoiceOut)
def resolve_vendor(
    invoice_id: uuid.UUID,
    payload: ds.ResolveVendorIn,
    db: _Db,
    request: Request,
    actor: Annotated[User, Depends(_contributor)],
) -> ds.InvoiceOut:
    invoice = service.resolve_vendor(
        db,
        org_id=actor.organization_id,
        invoice_id=invoice_id,
        vendor_id=payload.vendor_id,
        vendor_name=payload.vendor_name,
        actor=actor,
    )
    record_audit(
        db,
        action="invoice.vendor_resolved",
        organization_id=actor.organization_id,
        actor_user_id=actor.id,
        entity_type="invoice",
        entity_id=invoice.id,
        detail={"vendor_id": str(invoice.vendor_id)},
        context=AuditContext.from_request(request),
    )
    return _invoice_out(invoice)
