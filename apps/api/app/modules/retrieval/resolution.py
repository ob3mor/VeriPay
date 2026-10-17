"""Vendor entity resolution — CANDIDATES with scores, never auto-merge.

The existing human confirm flow (``POST /invoices/{id}/resolve-vendor``,
procurement service) remains the ONLY way an invoice gains a vendor. This
module is a read-only suggestion engine for investigators:

- Arabic/English *legal-form* variants (``Acme Co.`` ≡ ``Acme Company`` ≡
  ``شركة Acme``) via the shared legal-form equivalence class,
- common name differences (token order, extra words) via token-set overlap,
- OCR-error tolerance via trigram similarity AND difflib ratio — e.g. a
  misread ``Gr0up`` still reaches ``Group``,
- every stored name surface is a candidate source: ``display_name``,
  ``legal_name``, and the vendor_name strings previously extracted from this
  vendor's documents (provenance-linked through invoices).

What is deliberately NOT here: cross-script transliteration (Arabic ↔ Latin
phonetic mapping). An org that records both spellings (display + legal name,
or a prior extraction) is matched on either surface; inventing transliteration
would guess, and unresolved vendors are never guessed (ARCHITECTURE §4 step 3).

Writes: none. This module performs zero inserts/updates — an unverified
upload can never be promoted into the trusted vendor master through it.
"""

from __future__ import annotations

import uuid as uuid_module
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ExtractionField, Invoice, Vendor

from app.modules.retrieval.normalize import (
    normalize_text,
    strip_legal_forms,
    trigram_similarity,
)

# Candidates below this overall score are noise for a human reviewer.
RESOLUTION_FLOOR = 0.4

# Extraction field carrying the printed vendor name.
_VENDOR_NAME_FIELD = "vendor_name"


@dataclass
class VendorCandidate:
    """A suggested vendor match — a candidate, never a decision."""

    vendor_id: str
    display_name: str
    legal_name: str | None
    score: float
    matched_via: list[str] = field(default_factory=list)
    # OCR-extracted vendor_name strings that also support this candidate.
    ocr_variants: list[str] = field(default_factory=list)


def _score_pair(query: str, candidate: str) -> tuple[float, list[str]]:
    """Max over the component scorers, with the fired techniques listed."""
    if not candidate:
        return 0.0, []
    via: list[str] = []
    q_norm = normalize_text(query)
    c_norm = normalize_text(candidate)
    best = 0.0

    if q_norm and q_norm == c_norm:
        best = 1.0
        via.append("exact normalized name")

    q_stripped = strip_legal_forms(query)
    c_stripped = strip_legal_forms(candidate)
    if q_stripped and q_stripped == c_stripped and best < 0.98:
        best = max(best, 0.98)
        via.append("legal-form-insensitive equality (Co./شركة equivalents)")

    q_tokens = set(q_stripped.split())
    c_tokens = set(c_stripped.split())
    if q_tokens and c_tokens:
        jaccard = len(q_tokens & c_tokens) / len(q_tokens | c_tokens)
        if jaccard > best:
            best = jaccard
            if jaccard >= RESOLUTION_FLOOR:
                via.append("token overlap (common name differences)")

    dice = trigram_similarity(query, candidate)
    if dice > best:
        best = dice
        if dice >= RESOLUTION_FLOOR:
            via.append("trigram similarity (OCR-error tolerance)")

    ratio = SequenceMatcher(None, q_norm, c_norm).ratio()
    if ratio > best:
        best = ratio
        if ratio >= RESOLUTION_FLOOR:
            via.append("difflib sequence ratio (OCR-error tolerance)")

    return best, via


def _ocr_names_by_vendor(db: Session, org_id: object) -> dict[str, list[str]]:
    """Extracted vendor_name strings → vendor, via invoice binding (org-scoped).

    Provenance-safe: only fields whose invoice is bound to a vendor count, and
    the join filters BOTH tables by the org before any row is read.
    """
    rows = (
        db.execute(
            select(Invoice.vendor_id, ExtractionField.field_value)
            .join(ExtractionField, ExtractionField.invoice_id == Invoice.id)
            .where(
                Invoice.organization_id == org_id,
                ExtractionField.organization_id == org_id,
                ExtractionField.field_name == _VENDOR_NAME_FIELD,
                Invoice.vendor_id.is_not(None),
                ExtractionField.field_value.is_not(None),
            )
        )
        .unique()
        .all()
    )
    names: dict[str, list[str]] = {}
    for vendor_id, value in rows:
        names.setdefault(str(vendor_id), []).append(str(value))
    return names


def resolve_vendor_candidates(
    db: Session, *, org_id: object, name: str, limit: int = 5
) -> list[VendorCandidate]:
    """Suggest vendor candidates for a printed/extracted name.

    Read-only: no vendor is created, updated, or merged; the invoice's vendor
    is only ever set by the human confirm flow. Candidates are returned sorted
    by score (desc, id asc for determinism).
    """
    if not name or not normalize_text(name):
        return []
    if isinstance(org_id, str):
        org_id = uuid_module.UUID(org_id)
    floor = max(RESOLUTION_FLOOR, get_settings().retrieval_trigram_threshold)
    vendors = (
        db.scalars(
            select(Vendor).where(
                # Org filter before candidate generation.
                Vendor.organization_id == org_id
            )
        )
        .unique()
        .all()
    )
    ocr_names = _ocr_names_by_vendor(db, org_id)

    candidates: list[VendorCandidate] = []
    for vendor in vendors:
        surfaces = [
            (vendor.display_name, "registry display_name"),
            (vendor.legal_name, "registry legal_name"),
        ]
        surfaces += [
            (variant, "extracted vendor_name (OCR provenance)")
            for variant in ocr_names.get(str(vendor.id), [])
        ]
        best_score, best_via = 0.0, []
        for surface, source_label in surfaces:
            if not surface:
                continue
            score, via = _score_pair(name, surface)
            if score > best_score:
                best_score = score
                best_via = [f"{source_label}: {v}" for v in via]
        if best_score >= floor:
            candidates.append(
                VendorCandidate(
                    vendor_id=str(vendor.id),
                    display_name=vendor.display_name,
                    legal_name=vendor.legal_name,
                    score=round(best_score, 6),
                    matched_via=best_via,
                    ocr_variants=ocr_names.get(str(vendor.id), []),
                )
            )
    candidates.sort(key=lambda c: (-c.score, c.vendor_id))
    return candidates[:limit]
