"""The search index: an org-scoped, derived projection of searchable rows.

Sources (Prompt-03 §1): ``vendors``, ``vendor_bank_accounts`` (**status =
approved only** — R5: nothing unapproved is ever searchable as a trusted
destination), ``invoices``, ``purchase_orders``, ``extraction_fields`` (via
their extraction results), and ``review_actions`` joined to their cases (the
human verification/review record).

Tenancy rule (API.md §5.3, enforced structurally): **every** query below
starts from ``WHERE organization_id = :org_id`` — the org filter is applied in
SQL before any row reaches Python, so candidate generation cannot see another
tenant's data even before matching begins. The PostgreSQL backend's technique
branches (``techniques.py``) repeat the same predicate inside every UNION arm.

Maintenance semantics: the index is *derived per request* from the source-of-
truth tables — it cannot drift, and every row carries the source record's
``updated_at`` as its ``record_version``. At production scale this projection
is the seam a materialized/persisted index would plug into; correctness never
depends on persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import BankAccountStatus, ExtractionFieldVerificationStatus
from app.models import (
    ExtractionField,
    ExtractionResult,
    InvestigationCase,
    Invoice,
    PurchaseOrder,
    ReviewAction,
    Vendor,
    VendorBankAccount,
)

from app.modules.retrieval.normalize import (
    normalize_identifier,
    normalize_text,
    strip_legal_forms,
)
from app.modules.retrieval.trust import TrustTier, effective_tier

# Canonical entity types (the vocabulary used by techniques, fusion, API).
ENTITY_VENDOR = "vendor"
ENTITY_VENDOR_BANK_ACCOUNT = "vendor_bank_account"
ENTITY_INVOICE = "invoice"
ENTITY_PURCHASE_ORDER = "purchase_order"
ENTITY_EXTRACTION_FIELD = "extraction_field"
ENTITY_REVIEW_ACTION = "review_action"

ALL_ENTITY_TYPES = (
    ENTITY_VENDOR,
    ENTITY_VENDOR_BANK_ACCOUNT,
    ENTITY_INVOICE,
    ENTITY_PURCHASE_ORDER,
    ENTITY_EXTRACTION_FIELD,
    ENTITY_REVIEW_ACTION,
)

# Extraction field names whose values are exact-matchable identifiers.
_IDENTIFIER_FIELD_NAMES = {"invoice_number", "po_reference", "vendor_tax_id", "iban"}


def entity_ref(entity_type: str, entity_id: object) -> tuple[str, str]:
    """Stable (entity_type, entity_id) reference used across fusion."""
    return (entity_type, str(entity_id))


@dataclass
class SearchRow:
    """One searchable record with provenance, trust and document location."""

    entity_type: str
    entity_id: str
    organization_id: str
    title: str
    # Combined raw text (display form) and its normalized form + tokens,
    # precomputed so every technique works in the same normalized space.
    text: str
    normalized: str = ""
    tokens: list[str] = field(default_factory=list)
    # Normalized identifier values for exact matching, keyed by field name
    # (invoice_number, po_number, tax_id, account_fingerprint, ...).
    identifier_fields: dict[str, str] = field(default_factory=dict)
    trust_tier: TrustTier = TrustTier.UNVERIFIED_UPLOAD
    # Module/record provenance (document id, extraction version, case, ...).
    provenance: dict = field(default_factory=dict)
    # Document location when the row cites a document span: {document_id,
    # page, bbox} — how a human navigates to the evidence (R3 provenance).
    location: dict | None = None
    # Source record version (updated_at) — indexing currency + staleness.
    record_version: datetime | None = None
    # Denormalized relationship links used by the evidence graph + evidence API.
    vendor_id: str | None = None
    invoice_id: str | None = None
    document_id: str | None = None

    @property
    def ref(self) -> tuple[str, str]:
        return (self.entity_type, self.entity_id)

    def name_key(self) -> str:
        """Legal-form-stripped normalized text — vendor-name comparisons."""
        return strip_legal_forms(self.normalized)


@dataclass
class SearchIndex:
    """The projection for one org, with ref-keyed access."""

    organization_id: str
    rows: list[SearchRow]

    def __post_init__(self) -> None:
        self._by_ref: dict[tuple[str, str], SearchRow] = {r.ref: r for r in self.rows}

    def by_ref(self, ref: tuple[str, str]) -> SearchRow | None:
        return self._by_ref.get(ref)

    def refs(self) -> set[tuple[str, str]]:
        return set(self._by_ref)

    def filter_types(self, entity_types) -> "SearchIndex":
        wanted = set(entity_types)
        return SearchIndex(
            self.organization_id, [r for r in self.rows if r.entity_type in wanted]
        )


def _tier(base: TrustTier, updated_at: datetime | None) -> TrustTier:
    return effective_tier(base, updated_at)


def build_search_index(
    db: Session, *, org_id: object, entity_types=None
) -> SearchIndex:
    """Build the org-scoped projection. Org filter precedes every query."""
    wanted = set(entity_types) if entity_types else set(ALL_ENTITY_TYPES)
    rows: list[SearchRow] = []
    if ENTITY_VENDOR in wanted:
        rows.extend(_vendor_rows(db, org_id))
    if ENTITY_VENDOR_BANK_ACCOUNT in wanted:
        rows.extend(_bank_account_rows(db, org_id))
    if ENTITY_INVOICE in wanted:
        rows.extend(_invoice_rows(db, org_id))
    if ENTITY_PURCHASE_ORDER in wanted:
        rows.extend(_purchase_order_rows(db, org_id))
    if ENTITY_EXTRACTION_FIELD in wanted:
        rows.extend(_extraction_field_rows(db, org_id))
    if ENTITY_REVIEW_ACTION in wanted:
        rows.extend(_review_action_rows(db, org_id))
    return SearchIndex(str(org_id), rows)


# ------------------------------------------------------------------ vendors ---
def _vendor_rows(db: Session, org_id: object) -> list[SearchRow]:
    vendor_list = (
        db.scalars(
            select(Vendor).where(
                # Org filter FIRST — before any row reaches Python.
                Vendor.organization_id == org_id
            )
        )
        .unique()
        .all()
    )
    rows = []
    for v in vendor_list:
        text = " ".join(x for x in (v.display_name, v.legal_name, v.notes) if x)
        identifiers = {"name": normalize_text(v.normalized_name)}
        if v.tax_id:
            identifiers["tax_id"] = normalize_identifier(v.tax_id)
        rows.append(
            SearchRow(
                entity_type=ENTITY_VENDOR,
                entity_id=str(v.id),
                organization_id=str(org_id),
                title=v.display_name,
                text=text,
                normalized=normalize_text(text),
                tokens=normalize_text(text).split(),
                identifier_fields=identifiers,
                # The vendor registry is human-managed → trusted tier.
                trust_tier=_tier(TrustTier.TRUSTED_REGISTRY, v.updated_at),
                provenance={"status": v.status, "normalized_name": v.normalized_name},
                record_version=v.updated_at,
                vendor_id=str(v.id),
            )
        )
    return rows


# ---------------------------------------------------- bank accounts (R5) ------
def _bank_account_rows(db: Session, org_id: object) -> list[SearchRow]:
    # status = approved ONLY: pending/rejected/revoked accounts are never
    # searchable as trusted destinations (R5 — human-approved registry only).
    accounts = (
        db.scalars(
            select(VendorBankAccount).where(
                VendorBankAccount.organization_id == org_id,
                VendorBankAccount.status == BankAccountStatus.APPROVED.value,
            )
        )
        .unique()
        .all()
    )
    rows = []
    for a in accounts:
        text = " ".join(
            x for x in (a.account_holder_name, a.bank_name, a.bank_country) if x
        )
        identifiers = {
            "account_fingerprint": a.account_fingerprint,
        }
        if a.account_number_last4:
            identifiers["account_number_last4"] = a.account_number_last4
        rows.append(
            SearchRow(
                entity_type=ENTITY_VENDOR_BANK_ACCOUNT,
                entity_id=str(a.id),
                organization_id=str(org_id),
                title=a.account_holder_name,
                text=text,
                normalized=normalize_text(text),
                tokens=normalize_text(text).split(),
                identifier_fields=identifiers,
                # Approved = human verification record exists (R5).
                trust_tier=_tier(TrustTier.TRUSTED_REGISTRY, a.updated_at),
                provenance={
                    "vendor_id": str(a.vendor_id),
                    "status": a.status,
                    "is_current": a.is_current,
                    # The independent verification record (citable provenance).
                    "verification_method": a.verification_method,
                    "verification_reference": a.verification_reference,
                    "verification_document_id": (
                        str(a.verification_document_id)
                        if a.verification_document_id
                        else None
                    ),
                    "verified_at": a.verified_at.isoformat() if a.verified_at else None,
                    "verified_by": str(a.verified_by) if a.verified_by else None,
                },
                record_version=a.updated_at,
                vendor_id=str(a.vendor_id),
                document_id=(
                    str(a.verification_document_id)
                    if a.verification_document_id
                    else None
                ),
            )
        )
    return rows


# ---------------------------------------------------------------- invoices ----
def _reviewed_invoice_ids(db: Session, org_id: object) -> set[str]:
    """Invoices touched by human review (case or review action) — the
    "previously reviewed" tier. Org-scoped joins only."""
    case_ids = select(InvestigationCase.id).where(
        InvestigationCase.organization_id == org_id
    )
    case_invoice_ids = select(InvestigationCase.invoice_id).where(
        InvestigationCase.organization_id == org_id,
        InvestigationCase.invoice_id.is_not(None),
    )
    action_invoice_ids = (
        select(InvestigationCase.invoice_id)
        .join(ReviewAction, ReviewAction.case_id == InvestigationCase.id)
        .where(
            ReviewAction.organization_id == org_id,
            InvestigationCase.invoice_id.is_not(None),
        )
        .where(InvestigationCase.id.in_(case_ids))
    )
    ids: set[str] = set()
    for value in db.scalars(case_invoice_ids).unique().all():
        ids.add(str(value))
    for value in db.scalars(action_invoice_ids).unique().all():
        if value is not None:
            ids.add(str(value))
    return ids


def _invoice_rows(db: Session, org_id: object) -> list[SearchRow]:
    invoices = (
        db.scalars(
            select(Invoice).where(Invoice.organization_id == org_id)
        )
        .unique()
        .all()
    )
    reviewed = _reviewed_invoice_ids(db, org_id)
    rows = []
    for i in invoices:
        text = " ".join(
            x
            for x in (
                i.invoice_number,
                i.currency,
                i.remittance_bank_name_raw,
                i.remittance_account_raw,
            )
            if x
        )
        identifiers = {"invoice_number": normalize_identifier(i.invoice_number)}
        if i.remittance_account_fingerprint:
            identifiers["remittance_fingerprint"] = i.remittance_account_fingerprint
        base_tier = (
            TrustTier.PREVIOUSLY_REVIEWED
            if str(i.id) in reviewed
            else TrustTier.UNVERIFIED_UPLOAD
        )
        rows.append(
            SearchRow(
                entity_type=ENTITY_INVOICE,
                entity_id=str(i.id),
                organization_id=str(org_id),
                title=i.invoice_number,
                text=text,
                normalized=normalize_text(text),
                tokens=normalize_text(text).split(),
                identifier_fields=identifiers,
                trust_tier=_tier(base_tier, i.updated_at),
                provenance={
                    "status": i.status,
                    "purchase_order_id": (
                        str(i.purchase_order_id) if i.purchase_order_id else None
                    ),
                    "total_amount": str(i.total_amount) if i.total_amount else None,
                    "currency": i.currency,
                },
                record_version=i.updated_at,
                vendor_id=str(i.vendor_id) if i.vendor_id else None,
                invoice_id=str(i.id),
                document_id=str(i.source_document_id) if i.source_document_id else None,
            )
        )
    return rows


# ----------------------------------------------------------- purchase orders --
def _purchase_order_rows(db: Session, org_id: object) -> list[SearchRow]:
    po_list = (
        db.scalars(
            select(PurchaseOrder).where(PurchaseOrder.organization_id == org_id)
        )
        .unique()
        .all()
    )
    rows = []
    for p in po_list:
        text = " ".join(x for x in (p.po_number, p.description) if x)
        base_tier = (
            TrustTier.TRUSTED_REGISTRY
            if p.created_by is not None
            else TrustTier.UNVERIFIED_UPLOAD
        )
        rows.append(
            SearchRow(
                entity_type=ENTITY_PURCHASE_ORDER,
                entity_id=str(p.id),
                organization_id=str(org_id),
                title=p.po_number,
                text=text,
                normalized=normalize_text(text),
                tokens=normalize_text(text).split(),
                identifier_fields={"po_number": normalize_identifier(p.po_number)},
                trust_tier=_tier(base_tier, p.updated_at),
                provenance={
                    "status": p.status,
                    "amount": str(p.amount) if p.amount else None,
                    "currency": p.currency,
                    "vendor_id": str(p.vendor_id) if p.vendor_id else None,
                },
                record_version=p.updated_at,
                vendor_id=str(p.vendor_id) if p.vendor_id else None,
                document_id=str(p.source_document_id) if p.source_document_id else None,
            )
        )
    return rows


# -------------------------------------------------------- extraction fields ---
def _extraction_field_rows(db: Session, org_id: object) -> list[SearchRow]:
    """Fields of the latest extraction result per document (org-scoped).

    "Latest" = newest result per document that actually HAS fields: a later
    empty run (e.g. a parse that produced nothing) contributes no searchable
    rows, so the previous run's fields stay retrievable; ties at the DB's
    timestamp precision break deterministically by id.

    R3: unverified fields stay ``unverified_upload`` regardless of provider
    confidence — confidence alone never upgrades trust.
    """
    results = (
        db.scalars(
            select(ExtractionResult).where(ExtractionResult.organization_id == org_id)
        )
        .unique()
        .all()
    )
    if not results:
        return []
    fields = (
        db.scalars(
            select(ExtractionField).where(
                ExtractionField.organization_id == org_id,
                ExtractionField.extraction_result_id.in_(
                    [r.id for r in results]
                ),
            )
        )
        .unique()
        .all()
    )
    result_ids_with_fields = {str(f.extraction_result_id) for f in fields}
    result_by_id = {str(r.id): r for r in results}

    def _sort_key(r: ExtractionResult):
        created = r.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (created or datetime.min.replace(tzinfo=timezone.utc), str(r.id))

    latest_with_fields: dict[str, ExtractionResult] = {}
    for r in sorted(results, key=_sort_key, reverse=True):
        doc_key = str(r.document_id)
        if doc_key in latest_with_fields:
            continue
        if str(r.id) in result_ids_with_fields:
            latest_with_fields[doc_key] = r
    if not latest_with_fields:
        return []

    kept_ids = {str(r.id) for r in latest_with_fields.values()}
    rows = []
    for f in fields:
        if str(f.extraction_result_id) not in kept_ids:
            continue
        result = result_by_id[str(f.extraction_result_id)]
        text = " ".join(x for x in (f.field_name, f.field_value) if x)
        identifiers: dict[str, str] = {}
        if f.field_name in _IDENTIFIER_FIELD_NAMES and f.field_value:
            key = (
                "invoice_number"
                if f.field_name == "invoice_number"
                else ("po_number" if f.field_name == "po_reference" else f.field_name)
            )
            identifiers[key] = normalize_identifier(f.field_value)
        location = None
        spans = f.evidence_spans or []
        if spans:
            span = spans[0]
            location = {
                "document_id": str(result.document_id) if result else None,
                "page": span.get("page"),
                "bbox": span.get("bbox"),
            }
        base_tier = (
            TrustTier.TRUSTED_REGISTRY
            if f.verification_status
            in (
                ExtractionFieldVerificationStatus.CONFIRMED.value,
                ExtractionFieldVerificationStatus.CORRECTED.value,
            )
            else TrustTier.UNVERIFIED_UPLOAD
        )
        rows.append(
            SearchRow(
                entity_type=ENTITY_EXTRACTION_FIELD,
                entity_id=str(f.id),
                organization_id=str(org_id),
                title=f"{f.field_name}: {f.field_value or ''}".strip(": "),
                text=text,
                normalized=normalize_text(text),
                tokens=normalize_text(text).split(),
                identifier_fields=identifiers,
                trust_tier=_tier(base_tier, f.updated_at),
                provenance={
                    "field_name": f.field_name,
                    "field_value": f.field_value,
                    "confidence": f.confidence,
                    "verification_status": f.verification_status,
                    "extraction_result_id": str(f.extraction_result_id),
                    "extraction_version": (
                        result.extraction_version if result else None
                    ),
                },
                location=location,
                record_version=f.updated_at,
                invoice_id=str(f.invoice_id) if f.invoice_id else None,
                document_id=str(result.document_id) if result else None,
            )
        )
    return rows


# ----------------------------------------------------------- review actions ---
def _review_action_rows(db: Session, org_id: object) -> list[SearchRow]:
    """Human investigation records (cases' review actions) — searchable
    verification events with their case provenance."""
    actions = (
        db.scalars(
            select(ReviewAction)
            .join(InvestigationCase, InvestigationCase.id == ReviewAction.case_id)
            .where(
                # Org filter FIRST, on the concrete table (not the join target).
                ReviewAction.organization_id == org_id,
                InvestigationCase.organization_id == org_id,
            )
        )
        .unique()
        .all()
    )
    case_by_id = {
        str(c.id): c
        for c in db.scalars(
            select(InvestigationCase).where(InvestigationCase.organization_id == org_id)
        )
        .unique()
        .all()
    }
    rows = []
    for a in actions:
        case = case_by_id.get(str(a.case_id))
        text = " ".join(x for x in (a.action_type, a.body) if x)
        rows.append(
            SearchRow(
                entity_type=ENTITY_REVIEW_ACTION,
                entity_id=str(a.id),
                organization_id=str(org_id),
                title=a.action_type.replace("_", " ").title(),
                text=text,
                normalized=normalize_text(text),
                tokens=normalize_text(text).split(),
                identifier_fields={},
                # A human investigation record → trusted tier.
                trust_tier=_tier(TrustTier.TRUSTED_REGISTRY, a.updated_at),
                provenance={
                    "action_type": a.action_type,
                    "case_id": str(a.case_id),
                    "case_number": case.case_number if case else None,
                    "case_invoice_id": (
                        str(case.invoice_id) if case and case.invoice_id else None
                    ),
                    "case_vendor_id": (
                        str(case.vendor_id) if case and case.vendor_id else None
                    ),
                    "actor_user_id": str(a.actor_user_id) if a.actor_user_id else None,
                },
                record_version=a.updated_at,
                invoice_id=(
                    str(case.invoice_id) if case and case.invoice_id else None
                ),
                vendor_id=(
                    str(case.vendor_id) if case and case.vendor_id else None
                ),
            )
        )
    return rows
