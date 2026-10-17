"""Evidence graph queries — relationships, gaps, and data disagreements.

The five relationship families (Prompt-03 §5):

- vendor → invoices
- vendor → approved bank accounts (status = approved ONLY — R5)
- invoice → purchase order (FK link, plus the printed PO reference matched
  against the org's PO registry)
- vendor → verification events (the independent human verification records:
  approved accounts' method/reference/document + account review actions)
- invoice → historical invoices (same vendor) + recorded evidence matches

Gaps are absence findings: severity capped at ``medium`` with language stating
the record may simply not exist in VeriPay (R4 — missing records are not
fraud). Contradictions are *structured data disagreements* surfaced for human
review — they never claim fraud and never claim genuineness (R2); the fraud
module owns the scored signal vocabulary.

Every query is org-scoped before it reads (API.md §5.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.enums import BankAccountStatus
from app.models import (
    EvidenceMatch,
    ExtractionField,
    ExtractionResult,
    InvestigationCase,
    Invoice,
    PurchaseOrder,
    ReviewAction,
    Vendor,
    VendorBankAccount,
)
from app.modules.vendors.service import fingerprint_account

GAP_MISSING = "missing"
GAP_CONTRADICTION = "contradiction"

# R4 cap: absence never exceeds medium.
_MISSING_SEVERITY_CAP = "medium"


@dataclass
class GraphGap:
    """A missing relationship or a data disagreement — structured, citable."""

    kind: str  # "missing" | "contradiction"
    relationship: str  # dotted edge name, e.g. "invoice→purchase_order"
    message: str
    severity: str = "low"  # missing: low..medium (capped); contradictions: medium
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "relationship": self.relationship,
            "message": self.message,
            "severity": self.severity,
            "detail": self.detail,
        }


@dataclass
class InvoiceGraph:
    """The evidence graph around one invoice (org-scoped reads only)."""

    invoice: Invoice
    vendor: Vendor | None
    approved_accounts: list[VendorBankAccount]
    purchase_order: PurchaseOrder | None  # FK link
    printed_po_reference: str | None  # what the invoice printed, if anything
    po_by_reference: PurchaseOrder | None  # printed PO number → registry
    historical_invoices: list[Invoice]
    evidence_matches: list[EvidenceMatch]
    verification_events: list[dict]
    gaps: list[GraphGap]

    def missing_gaps(self) -> list[GraphGap]:
        return [g for g in self.gaps if g.kind == GAP_MISSING]

    def contradictions(self) -> list[GraphGap]:
        return [g for g in self.gaps if g.kind == GAP_CONTRADICTION]


@dataclass
class VendorGraph:
    vendor: Vendor
    invoices: list[Invoice]
    approved_accounts: list[VendorBankAccount]
    verification_events: list[dict]
    gaps: list[GraphGap]

    def missing_gaps(self) -> list[GraphGap]:
        return [g for g in self.gaps if g.kind == GAP_MISSING]

    def contradictions(self) -> list[GraphGap]:
        return [g for g in self.gaps if g.kind == GAP_CONTRADICTION]


def _verification_events(
    db: Session, *, org_id: object, vendor_id: object
) -> list[dict]:
    """The independent human verification record(s) for a vendor's accounts.

    Two structured sources, both org-scoped:
    1. approved accounts with their verification method/reference/document,
    2. review actions of the account-verification kinds reached through cases
       referencing this vendor.
    """
    accounts = (
        db.scalars(
            select(VendorBankAccount).where(
                VendorBankAccount.organization_id == org_id,
                VendorBankAccount.vendor_id == vendor_id,
                VendorBankAccount.status == BankAccountStatus.APPROVED.value,
            )
        )
        .unique()
        .all()
    )
    events: list[dict] = []
    for a in accounts:
        events.append(
            {
                "type": "bank_account_approved",
                "account_id": str(a.id),
                "verification_method": a.verification_method,
                "verification_reference": a.verification_reference,
                "verification_document_id": (
                    str(a.verification_document_id)
                    if a.verification_document_id
                    else None
                ),
                "verified_at": a.verified_at.isoformat() if a.verified_at else None,
                "verified_by": str(a.verified_by) if a.verified_by else None,
            }
        )
    account_review_kinds = (
        "account_verified",
        "account_change_approved",
    )
    actions = (
        db.scalars(
            select(ReviewAction)
            .join(InvestigationCase, InvestigationCase.id == ReviewAction.case_id)
            .where(
                ReviewAction.organization_id == org_id,
                InvestigationCase.organization_id == org_id,
                InvestigationCase.vendor_id == vendor_id,
                ReviewAction.action_type.in_(account_review_kinds),
            )
        )
        .unique()
        .all()
    )
    for a in actions:
        events.append(
            {
                "type": "review_action",
                "action_type": a.action_type,
                "review_action_id": str(a.id),
                "case_id": str(a.case_id),
                "body": a.body,
                "actor_user_id": str(a.actor_user_id) if a.actor_user_id else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
        )
    return events


def _approved_accounts(db: Session, *, org_id: object, vendor_id: object):
    return list(
        db.scalars(
            select(VendorBankAccount).where(
                VendorBankAccount.organization_id == org_id,
                VendorBankAccount.vendor_id == vendor_id,
                VendorBankAccount.status == BankAccountStatus.APPROVED.value,
            )
        )
        .unique()
        .all()
    )


def invoice_evidence_graph(db: Session, *, org_id: object, invoice: Invoice) -> InvoiceGraph:
    """Build the invoice-centric evidence graph + gaps + contradictions."""
    vendor = None
    if invoice.vendor_id is not None:
        vendor = db.scalar(
            select(Vendor).where(
                Vendor.id == invoice.vendor_id, Vendor.organization_id == org_id
            )
        )

    purchase_order = None
    if invoice.purchase_order_id is not None:
        purchase_order = db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.id == invoice.purchase_order_id,
                PurchaseOrder.organization_id == org_id,
            )
        )

    po_by_reference = _po_by_printed_reference(db, org_id=org_id, invoice=invoice)
    printed_reference = _printed_po_reference(db, org_id=org_id, invoice=invoice)

    historical: list[Invoice] = []
    if invoice.vendor_id is not None:
        historical = list(
            db.scalars(
                select(Invoice).where(
                    Invoice.organization_id == org_id,
                    Invoice.vendor_id == invoice.vendor_id,
                    Invoice.id != invoice.id,
                )
                .order_by(Invoice.created_at.desc())
            )
            .unique()
            .all()
        )

    matches = list(
        db.scalars(
            select(EvidenceMatch).where(
                EvidenceMatch.organization_id == org_id,
                or_(
                    (EvidenceMatch.source_entity_type == "invoice")
                    & (EvidenceMatch.source_entity_id == invoice.id),
                    (EvidenceMatch.target_entity_type == "invoice")
                    & (EvidenceMatch.target_entity_id == invoice.id),
                ),
            )
        )
        .unique()
        .all()
    )

    approved_accounts: list[VendorBankAccount] = []
    verification_events: list[dict] = []
    if vendor is not None:
        approved_accounts = _approved_accounts(db, org_id=org_id, vendor_id=vendor.id)
        verification_events = _verification_events(
            db, org_id=org_id, vendor_id=vendor.id
        )

    gaps = _invoice_gaps(
        db,
        org_id=org_id,
        invoice=invoice,
        vendor=vendor,
        purchase_order=purchase_order,
        po_by_reference=po_by_reference,
        approved_accounts=approved_accounts,
        historical=historical,
    )
    return InvoiceGraph(
        invoice=invoice,
        vendor=vendor,
        approved_accounts=approved_accounts,
        purchase_order=purchase_order,
        printed_po_reference=printed_reference,
        po_by_reference=po_by_reference,
        historical_invoices=historical,
        evidence_matches=matches,
        verification_events=verification_events,
        gaps=gaps,
    )


def vendor_evidence_graph(db: Session, *, org_id: object, vendor: Vendor) -> VendorGraph:
    """Build the vendor-centric evidence graph + gaps."""
    invoices = list(
        db.scalars(
            select(Invoice).where(
                Invoice.organization_id == org_id, Invoice.vendor_id == vendor.id
            ).order_by(Invoice.created_at.desc())
        )
        .unique()
        .all()
    )
    accounts = _approved_accounts(db, org_id=org_id, vendor_id=vendor.id)
    events = _verification_events(db, org_id=org_id, vendor_id=vendor.id)
    gaps: list[GraphGap] = []
    if not accounts:
        gaps.append(
            GraphGap(
                kind=GAP_MISSING,
                relationship="vendor→approved_bank_account",
                message=(
                    "No approved bank account is on file for this vendor. The record may "
                    "simply not exist in VeriPay yet; a first payment to this vendor is "
                    "handled by the fraud module's bank_account_unverified signal."
                ),
                severity=_MISSING_SEVERITY_CAP,
                detail={"vendor_id": str(vendor.id)},
            )
        )
    if not events:
        gaps.append(
            GraphGap(
                kind=GAP_MISSING,
                relationship="vendor→verification_events",
                message=(
                    "No independent verification events recorded for this vendor's "
                    "accounts. The record may simply not exist in VeriPay."
                ),
                severity=_MISSING_SEVERITY_CAP,
                detail={"vendor_id": str(vendor.id)},
            )
        )
    return VendorGraph(
        vendor=vendor,
        invoices=invoices,
        approved_accounts=accounts,
        verification_events=events,
        gaps=gaps,
    )


# ------------------------------------------------------------------ helpers ---
def _po_by_printed_reference(
    db: Session, *, org_id: object, invoice: Invoice
) -> PurchaseOrder | None:
    """PO matched by the printed/extracted PO reference (org-scoped, exact
    per-org PO number registry). NULL when no reference was printed or none
    matches — absence, not an error."""
    reference = _printed_po_reference(db, org_id=org_id, invoice=invoice)
    if not reference:
        return None
    return db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == org_id,
            PurchaseOrder.po_number == reference,
        )
    )


def _printed_po_reference(db: Session, *, org_id: object, invoice: Invoice) -> str | None:
    """The printed PO reference from the invoice document's extraction fields.

    Scans the document's extraction results newest-first and uses the newest
    one that actually carries a po_reference value (a later run that parsed
    nothing must not hide the printed reference).
    """
    if invoice.source_document_id is None:
        return None
    results = (
        db.scalars(
            select(ExtractionResult)
            .where(
                ExtractionResult.organization_id == org_id,
                ExtractionResult.document_id == invoice.source_document_id,
            )
            .order_by(ExtractionResult.created_at.desc())
        )
        .unique()
        .all()
    )
    for result in results:
        field = db.scalar(
            select(ExtractionField)
            .where(
                ExtractionField.organization_id == org_id,
                ExtractionField.extraction_result_id == result.id,
                ExtractionField.field_name == "po_reference",
                ExtractionField.field_value.is_not(None),
            )
            .order_by(ExtractionField.created_at)
        )
        if field is not None and field.field_value:
            return field.field_value.strip()
    return None


def _invoice_gaps(
    db: Session,
    *,
    org_id: object,
    invoice: Invoice,
    vendor: Vendor | None,
    purchase_order: PurchaseOrder | None,
    po_by_reference: PurchaseOrder | None,
    approved_accounts: list[VendorBankAccount],
    historical: list[Invoice],
) -> list[GraphGap]:
    gaps: list[GraphGap] = []

    # ---------------------------------------------------------- missing ----
    if vendor is None:
        gaps.append(
            GraphGap(
                kind=GAP_MISSING,
                relationship="invoice→vendor",
                message=(
                    "No vendor is linked to this invoice. The vendor record may simply "
                    "not exist in VeriPay yet; resolution is a human decision."
                ),
                severity=_MISSING_SEVERITY_CAP,
                detail={"invoice_id": str(invoice.id)},
            )
        )
    if purchase_order is None and po_by_reference is None:
        gaps.append(
            GraphGap(
                kind=GAP_MISSING,
                relationship="invoice→purchase_order",
                message=(
                    "No purchase order is linked and no printed PO reference matches the "
                    "org's PO registry. The PO may simply not exist in VeriPay."
                ),
                severity=_MISSING_SEVERITY_CAP,
                detail={"invoice_id": str(invoice.id)},
            )
        )
    if vendor is not None and not approved_accounts:
        gaps.append(
            GraphGap(
                kind=GAP_MISSING,
                relationship="vendor→approved_bank_account",
                message=(
                    "No approved bank account is on file for the linked vendor. The record "
                    "may simply not exist in VeriPay; the pay-to destination risk is "
                    "signaled separately by the fraud module."
                ),
                severity=_MISSING_SEVERITY_CAP,
                detail={"vendor_id": str(vendor.id)},
            )
        )
    if invoice.source_document_id is None:
        gaps.append(
            GraphGap(
                kind=GAP_MISSING,
                relationship="invoice→source_document",
                message=(
                    "No source document is attached to this invoice. The document may "
                    "simply not exist in VeriPay."
                ),
                severity=_MISSING_SEVERITY_CAP,
                detail={"invoice_id": str(invoice.id)},
            )
        )
    if not historical:
        gaps.append(
            GraphGap(
                kind=GAP_MISSING,
                relationship="invoice→historical_invoices",
                message=(
                    "No earlier invoices exist for this vendor in VeriPay. The record may "
                    "simply not exist yet."
                ),
                severity="low",
                detail={"vendor_id": str(vendor.id) if vendor else None},
            )
        )

    # -------------------------------------------------- contradictions ----
    # Structured data disagreements for human review — never fraud claims.
    effective_po = purchase_order or po_by_reference
    if (
        effective_po is not None
        and invoice.total_amount is not None
        and effective_po.amount is not None
        and Decimal(str(invoice.total_amount)) != Decimal(str(effective_po.amount))
    ):
        gaps.append(
            GraphGap(
                kind=GAP_CONTRADICTION,
                relationship="invoice↔purchase_order",
                message=(
                    "Invoice total and PO amount disagree — surfaced for human review."
                ),
                severity="medium",
                detail={
                    "invoice_total": str(invoice.total_amount),
                    "po_amount": str(effective_po.amount),
                    "po_id": str(effective_po.id),
                    "po_source": (
                        "linked" if purchase_order is not None else "printed_reference"
                    ),
                },
            )
        )
    gaps.extend(_remittance_contradictions(db, org_id=org_id, invoice=invoice, vendor=vendor))
    return gaps


def _remittance_contradictions(
    db: Session, *, org_id: object, invoice: Invoice, vendor: Vendor | None
) -> list[GraphGap]:
    """The printed remittance fingerprint hitting a NON-approved on-file
    account — a disagreement between the invoice and the trusted registry."""
    if invoice.remittance_account_fingerprint is None:
        return []
    # Any account on file (any status) with the same fingerprint, org-scoped.
    query = select(VendorBankAccount).where(
        VendorBankAccount.organization_id == org_id,
        VendorBankAccount.account_fingerprint == invoice.remittance_account_fingerprint,
    )
    if vendor is not None:
        query = query.where(VendorBankAccount.vendor_id == vendor.id)
    hits = list(db.scalars(query).unique().all())
    gaps: list[GraphGap] = []
    for account in hits:
        if account.status == BankAccountStatus.APPROVED.value:
            continue
        gaps.append(
            GraphGap(
                kind=GAP_CONTRADICTION,
                relationship="invoice↔vendor_bank_account",
                message=(
                    "The printed remittance details match an on-file account whose "
                    "status is not approved — surfaced for human review."
                ),
                severity="medium",
                detail={
                    "account_id": str(account.id),
                    "account_status": account.status,
                    "invoice_fingerprint_source": "remittance_account_raw",
                },
            )
        )
    # Also flag when the raw account string was altered after fingerprinting.
    if invoice.remittance_account_raw and invoice.remittance_account_fingerprint != (
        fingerprint_account(invoice.remittance_account_raw)
    ):
        gaps.append(
            GraphGap(
                kind=GAP_CONTRADICTION,
                relationship="invoice↔remittance_fingerprint",
                message=(
                    "The stored remittance fingerprint does not match the printed "
                    "account string — surfaced for human review."
                ),
                severity="medium",
                detail={"invoice_id": str(invoice.id)},
            )
        )
    return gaps


__all__ = [
    "GAP_CONTRADICTION",
    "GAP_MISSING",
    "GraphGap",
    "InvoiceGraph",
    "VendorGraph",
    "invoice_evidence_graph",
    "vendor_evidence_graph",
    "MatchKind",  # re-exported for tests of the vocabulary
    "MatchStatus",
]
