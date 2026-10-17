"""EVC duplicate detection — multi-axis, deterministic, dispositionable.

Axes (policy_v1.json › duplicate_detection), each org-scoped and provenance-
carrying (docs/DATABASE.md §14 vocabulary — no content-hash match kind exists
because per-org SHA-256 dedup collapses identical bytes to one document row,
docs/DATABASE.md §11):

1. **Exact content (SHA-256 via dedup):** two invoice rows bound to the SAME
   document row (identical bytes — impossible to re-upload as a second row
   within an org) → the same document billed twice.
2. **Normalized invoice numbers:** retrieval's ``normalize_identifier`` space
   (``INV-2024/007`` ≡ ``inv 2024 007`` ≡ ``INV2024007``), same vendor or a
   vendor ENTITY MATCH (via the retrieval resolution module) when the number
   collides across two vendor records.
3. **Amount + currency + date comparison** on number pairs: distinguishing a
   duplicate upload (equal amounts, or an altered amount with an unchanged
   date) from a genuine corrected version (amount differs AND the later
   document's date is strictly newer) — the latter still requires human
   confirmation but is scored low, not like a duplicate upload.
4. **Near-duplicate field overlap:** distinct numbers, same vendor, equal
   amount + currency, ≥ ``near_duplicate_min_overlap`` of the comparable key
   fields and dates inside the window.

Similarity NEVER yields authenticity: a high overlap is a duplicate
*indicator* for human disposition, never evidence that anything is genuine
(policy_v1.json › explainability).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, Invoice
from app.modules.retrieval.normalize import normalize_identifier
from app.modules.retrieval.resolution import RESOLUTION_FLOOR, resolve_vendor_candidates

# Classifications of a duplicate hit (the message + severity choice).
DUPLICATE_UPLOAD = "duplicate_upload"
CORRECTED_VERSION_CANDIDATE = "corrected_version_candidate"
NEAR_DUPLICATE = "near_duplicate"
FIELD_OVERLAP = "field_overlap"

# Scan bound: invoices considered per assessment for cross-pairing (the org
# filter is in SQL; this bounds the Python-side comparison window).
MAX_CANDIDATE_INVOICES = 500

# Fields compared for overlap scoring (present-on-both fields only).
_OVERLAP_FIELDS = ("total_amount", "currency", "invoice_date", "due_date")


@dataclass(frozen=True)
class DuplicateHit:
    """One machine-detected duplicate candidate between two invoice rows."""

    kind: str  # evidence_matches.match_kind (invoice_number | near_duplicate | field_overlap)
    target: Invoice
    similarity: float
    classification: str
    matched_fields: dict = field(default_factory=dict)

    @property
    def severity(self) -> str:
        """duplicate_candidate severity for this hit. A corrected-version
        candidate stays low (human-confirmed, not scored like an upload);
        everything else is the §8 default medium."""
        return "low" if self.classification == CORRECTED_VERSION_CANDIDATE else "medium"

    @property
    def matched_field_names(self) -> list[str]:
        return sorted(self.matched_fields)


def _as_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _dates_within(a: date | None, b: date | None, window_days: int) -> bool | None:
    """None = not comparable (a date is missing); otherwise within-window."""
    if a is None or b is None:
        return None
    return abs((a - b).days) <= window_days


def _vendor_entity_match(db: Session, *, org_id: object, vendor_a_id: object,
                         vendor_b_id: object) -> bool:
    """Retrieval-module entity match: does vendor A resolve as a candidate for
    vendor B's name surfaces (or vice versa) at/above the resolution floor?

    Read-only candidate scoring — never merges or resolves anything. The
    vendor's OWN name scoring against itself is excluded: only a match that
    ties the OTHER record counts."""
    from app.models import Vendor

    vendor_a = db.get(Vendor, vendor_a_id)
    vendor_b = db.get(Vendor, vendor_b_id)
    if vendor_a is None or vendor_b is None:
        return False
    for named, other in ((vendor_a, vendor_b), (vendor_b, vendor_a)):
        for name in (named.display_name, named.legal_name):
            if not name:
                continue
            for candidate in resolve_vendor_candidates(db, org_id=org_id, name=name, limit=10):
                if (candidate.score >= RESOLUTION_FLOOR
                        and str(candidate.vendor_id) == str(other.id)):
                    return True
    return False


def find_duplicate_candidates(
    db: Session, *, invoice: Invoice
) -> list[DuplicateHit]:
    """All duplicate hits for one invoice across the axes, deterministically
    ordered (kind, target id). Recording evidence-match rows is the caller's
    job (fraud service), so this stays read-only."""
    policy_duplicates = _policy_duplicates()
    hits: list[DuplicateHit] = []
    seen: set[tuple[str, object]] = set()

    others = (
        db.scalars(
            select(Invoice)
            .where(
                Invoice.organization_id == invoice.organization_id,
                Invoice.id != invoice.id,
            )
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
            .limit(MAX_CANDIDATE_INVOICES)
        )
        .unique()
        .all()
    )

    # ---- axis 1: exact content (same document row = same SHA-256, per-org
    # dedup means identical bytes cannot exist as two document rows) --------
    if invoice.source_document_id is not None:
        source_doc = db.get(Document, invoice.source_document_id)
        for other in others:
            if other.source_document_id != invoice.source_document_id:
                continue
            key = ("near_duplicate", other.id)
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                DuplicateHit(
                    kind="near_duplicate",
                    target=other,
                    similarity=1.0,
                    classification=DUPLICATE_UPLOAD,
                    matched_fields={
                        "sha256": source_doc.sha256 if source_doc else None,
                        "source_document_id": str(invoice.source_document_id),
                        "axis": "exact content (per-org sha256 document dedup)",
                    },
                )
            )

    same_vendor_cache: dict[object, bool] = {}

    def _same_entity(other: Invoice) -> bool:
        if invoice.vendor_id is None or other.vendor_id is None:
            return False
        if invoice.vendor_id == other.vendor_id:
            return True
        if other.id not in same_vendor_cache:
            same_vendor_cache[other.id] = _vendor_entity_match(
                db,
                org_id=invoice.organization_id,
                vendor_a_id=invoice.vendor_id,
                vendor_b_id=other.vendor_id,
            )
        return same_vendor_cache[other.id]

    my_number = normalize_identifier(invoice.invoice_number)

    for other in others:
        # ---- axis 2+3: normalized invoice number --------------------------
        other_number = normalize_identifier(other.invoice_number)
        if my_number and other_number == my_number and _same_entity(other):
            key = ("invoice_number", other.id)
            if key not in seen:
                seen.add(key)
                hits.append(_number_pair_hit(invoice, other, policy_duplicates))

        # ---- axis 4: near-duplicate field overlap (distinct numbers) ------
        if other_number == my_number:
            continue  # number axis already covers (or skipped) this pair
        if invoice.vendor_id is None or invoice.vendor_id != other.vendor_id:
            continue
        overlap_hit = _overlap_pair_hit(invoice, other, policy_duplicates)
        if overlap_hit is not None:
            key = (overlap_hit.kind, other.id)
            if key not in seen:
                seen.add(key)
                hits.append(overlap_hit)

    hits.sort(key=lambda h: (h.kind, str(h.target.id)))
    return hits


def _number_pair_hit(invoice: Invoice, other: Invoice, rules: dict) -> DuplicateHit:
    """Classify a same-normalized-number pair: duplicate upload vs corrected
    version (amount differs AND this invoice's date is strictly newer) vs
    altered-amount re-billing (amount differs, date not newer)."""
    my_amount = _as_decimal(invoice.total_amount)
    other_amount = _as_decimal(other.total_amount)
    amounts_differ = (
        my_amount is not None
        and other_amount is not None
        and my_amount != other_amount
    )
    currencies_differ = (
        invoice.currency is not None
        and other.currency is not None
        and invoice.currency != other.currency
    )
    date_relation = _dates_within(
        invoice.invoice_date, other.invoice_date,
        int(rules["number_match_date_window_days"]),
    )
    is_newer = (
        invoice.invoice_date is not None
        and other.invoice_date is not None
        and invoice.invoice_date > other.invoice_date
    )

    matched = {
        "invoice_number_normalized": normalize_identifier(invoice.invoice_number),
        "vendor_id": str(invoice.vendor_id) if invoice.vendor_id else None,
        "amounts_differ": amounts_differ,
        "currencies_differ": currencies_differ,
        "axis": "normalized invoice number",
    }

    if amounts_differ and is_newer:
        classification = CORRECTED_VERSION_CANDIDATE
        matched["date_comparison"] = (
            f"invoice_date {invoice.invoice_date} is newer than the earlier "
            f"{other.invoice_date}"
        )
    else:
        classification = DUPLICATE_UPLOAD
        if amounts_differ:
            matched["date_comparison"] = "amount differs without a newer date"
        elif date_relation is False:
            matched["date_comparison"] = "dates outside the number-match window"
    return DuplicateHit(
        kind="invoice_number",
        target=other,
        similarity=1.0,
        classification=classification,
        matched_fields=matched,
    )


def _overlap_pair_hit(invoice: Invoice, other: Invoice, rules: dict) -> DuplicateHit | None:
    """Near-duplicate (equal amount) vs field_overlap (equal key fields,
    differing amount) across distinct numbers of the same vendor."""
    my_amount = _as_decimal(invoice.total_amount)
    other_amount = _as_decimal(other.total_amount)
    if my_amount is None or other_amount is None:
        return None
    amounts_equal = my_amount == other_amount

    compared = 0
    matches = 0
    for field_name in _OVERLAP_FIELDS:
        mine = getattr(invoice, field_name)
        theirs = getattr(other, field_name)
        if field_name == "total_amount":
            mine, theirs = my_amount, other_amount
        if mine is None or theirs is None:
            continue
        compared += 1
        if mine == theirs:
            matches += 1
    if invoice.remittance_account_fingerprint and other.remittance_account_fingerprint:
        compared += 1
        if (invoice.remittance_account_fingerprint
                == other.remittance_account_fingerprint):
            matches += 1

    date_relation = _dates_within(
        invoice.invoice_date, other.invoice_date,
        int(rules["near_duplicate_date_window_days"]),
    )
    if date_relation is False:
        return None  # far apart in time — recurring billing, not a near-copy

    if compared < 3:
        return None
    overlap = matches / compared
    if overlap < float(rules["near_duplicate_min_overlap"]):
        return None

    if amounts_equal:
        return DuplicateHit(
            kind="near_duplicate",
            target=other,
            similarity=round(overlap, 4),
            classification=NEAR_DUPLICATE,
            matched_fields={
                "axis": "near-duplicate field overlap",
                "overlap": round(overlap, 4),
                "compared_fields": compared,
                "total_amount": str(my_amount),
                "currency": invoice.currency,
            },
        )

    # Amounts differ: field_overlap needs the pay-to fingerprint AND close
    # dates (same payee, same day, different number AND amount).
    field_overlap_min = int(rules["field_overlap_min_matches"])
    fp_match = bool(
        invoice.remittance_account_fingerprint
        and invoice.remittance_account_fingerprint == other.remittance_account_fingerprint
    )
    dates_close = _dates_within(
        invoice.invoice_date, other.invoice_date,
        int(rules["number_match_date_window_days"]),
    )
    if not (fp_match and dates_close is not False and matches >= field_overlap_min):
        return None
    return DuplicateHit(
        kind="field_overlap",
        target=other,
        similarity=round(overlap, 4),
        classification=FIELD_OVERLAP,
        matched_fields={
            "axis": "field overlap (key fields match, values differ)",
            "overlap": round(overlap, 4),
            "compared_fields": compared,
            "remittance_fingerprint_match": fp_match,
        },
    )


def _policy_duplicates() -> dict:
    """Late import: policy lives above this module in the package."""
    from app.modules.fraud.policy import load_policy

    return load_policy().duplicates
