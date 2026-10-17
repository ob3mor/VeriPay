"""Retrieval service: hybrid search + the invoice evidence aggregation.

``search`` — the full hybrid pipeline (Prompt-03 §2/§3/§6):

1. build the org-scoped index (org filter in SQL BEFORE candidates exist),
2. run the dialect-selected backend's techniques (exact / normalized text /
   trigram / optional vector),
3. fuse the per-technique rank lists with RRF (configurable weights),
4. apply the trust-tier multiplier — retrieval quality and trust stay two
   separately auditable steps,
5. return citable hits: id, title, scores, techniques, explanations,
   provenance, document location, trust status, record version.

``get_invoice_evidence`` — GET /invoices/{id}/evidence backing: graph
relationships (deterministic) + fuzzy retrieval over the invoice's own
identifiers, gaps and contradictions included. Everything read-only; nothing
here mutates any record, approves anything, or claims genuineness.
"""

from __future__ import annotations

import uuid as uuid_module
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.procurement import service as procurement_service
from app.modules.retrieval.graph import InvoiceGraph, invoice_evidence_graph
from app.modules.retrieval.hybrid import FusedHit, default_weights, fuse
from app.modules.retrieval.indexing import (
    ENTITY_REVIEW_ACTION,
    ENTITY_VENDOR,
    ENTITY_VENDOR_BANK_ACCOUNT,
    SearchIndex,
    SearchRow,
    build_search_index,
)
from app.modules.retrieval.techniques import (
    TECH_GRAPH,
    get_backend,
)
from app.modules.retrieval.trust import TrustTier, trust_score

MAX_GRAPH_ITEMS = 10


def _uuid(value: object) -> object:
    """Coerce str ids to UUID so ``Uuid(as_uuid=True)`` binds work regardless
    of whether the caller passes the API's str form or the model's UUID form."""
    if isinstance(value, str):
        return uuid_module.UUID(value)
    return value


@dataclass
class SearchHit:
    """One citable retrieval result."""

    entity_type: str
    entity_id: str
    title: str
    fused_score: float
    trust_tier: TrustTier
    final_score: float
    techniques: list[str]
    explanation: str
    matched_field: str | None
    provenance: dict
    location: dict | None
    record_version: str | None

    def to_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "title": self.title,
            "fused_score": self.fused_score,
            "trust_tier": self.trust_tier.value,
            "final_score": self.final_score,
            "techniques": self.techniques,
            "explanation": self.explanation,
            "matched_field": self.matched_field,
            "provenance": self.provenance,
            "location": self.location,
            "record_version": self.record_version,
        }


def _hit_from_fused(fused: FusedHit, row: SearchRow) -> SearchHit:
    tier = row.trust_tier
    return SearchHit(
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        title=row.title,
        fused_score=round(fused.fused_score, 6),
        trust_tier=tier,
        final_score=round(trust_score(fused.fused_score, tier), 6),
        techniques=fused.technique_names,
        explanation=fused.explanation(),
        matched_field=None,
        provenance=row.provenance,
        location=row.location,
        record_version=(
            row.record_version.isoformat() if row.record_version else None
        ),
    )


def search(
    db: Session,
    *,
    org_id: object,
    query: str,
    entity_types=None,
    limit: int = 25,
    weights: dict[str, float] | None = None,
    fusion_k: int | None = None,
) -> dict:
    """Hybrid retrieval for one org. Org-scoped before candidate generation."""
    started = perf_counter()
    org_id = _uuid(org_id)
    backend = get_backend(db)
    index = build_search_index(db, org_id=org_id, entity_types=entity_types)
    technique_results = backend.run(
        db, org_id=org_id, query=query, index=index, entity_types=entity_types
    )
    effective_k = (
        fusion_k if fusion_k is not None else get_settings().retrieval_fusion_k
    )
    fused = fuse(technique_results, weights=weights, k=fusion_k)

    hits: list[SearchHit] = []
    skipped_stale_refs = 0
    for candidate in fused:
        if len(hits) >= limit:
            break
        row = index.by_ref(candidate.ref)
        if row is None:
            # The record changed between the technique pass and hydration —
            # skipped, counted, never guessed.
            skipped_stale_refs += 1
            continue
        hits.append(_hit_from_fused(candidate, row))
    hits.sort(key=lambda h: (-h.final_score, h.entity_type, h.entity_id))

    elapsed_ms = (perf_counter() - started) * 1000.0
    return {
        "hits": hits,
        "meta": {
            "backend": backend.name,
            "weights": {k: v for k, v in (weights or default_weights()).items()},
            "fusion_k": effective_k,
            "query": query,
            "latency_ms": round(elapsed_ms, 3),
            "skipped_stale_refs": skipped_stale_refs,
            "technique_notes": {
                r.technique: r.note for r in technique_results if r.note
            },
        },
    }


def search_refs(
    db: Session, *, org_id: object, query: str, weights: dict[str, float] | None = None
) -> list[str]:
    """Ranked refs ("type:id") — the ranker interface the evaluation uses."""
    result = search(db, org_id=org_id, query=query, limit=100, weights=weights)
    return [f"{h.entity_type}:{h.entity_id}" for h in result["hits"]]


def suggest_vendor_resolutions(
    db: Session, *, org_id: object, name: str, limit: int = 5
) -> list:
    """Vendor-resolution CANDIDATES (never auto-merge — see resolution.py).

    The human confirm flow stays ``POST /invoices/{id}/resolve-vendor``.
    """
    from app.modules.retrieval.resolution import resolve_vendor_candidates

    return resolve_vendor_candidates(db, org_id=org_id, name=name, limit=limit)


# ---------------------------------------------------------------------------
# Invoice evidence (GET /invoices/{id}/evidence)
# ---------------------------------------------------------------------------
def _graph_item(
    row: SearchRow, *, relationship: str, matched_field: str | None
) -> SearchHit:
    tier = row.trust_tier
    return SearchHit(
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        title=row.title,
        fused_score=1.0,
        trust_tier=tier,
        final_score=round(trust_score(1.0, tier), 6),
        techniques=[TECH_GRAPH],
        explanation=f"Graph relationship: {relationship}",
        matched_field=matched_field,
        provenance=row.provenance,
        location=row.location,
        record_version=(
            row.record_version.isoformat() if row.record_version else None
        ),
    )


def _merge_fuzzy_hits(
    items: dict[tuple[str, str], SearchHit],
    result: dict,
    *,
    seed: str,
    exclude: set[tuple[str, str]] | None = None,
) -> None:
    """Fold fuzzy retrieval hits into the evidence map (keep the better score,
    merge technique lists)."""
    for hit in result["hits"]:
        ref = (hit.entity_type, hit.entity_id)
        if exclude and ref in exclude:
            continue
        existing = items.get(ref)
        if existing is None:
            hit.explanation = f"query {seed!r} → {hit.explanation}"
            items[ref] = hit
        elif hit.final_score > existing.final_score:
            hit.techniques = sorted(set(existing.techniques) | set(hit.techniques))
            hit.explanation = f"query {seed!r} → {hit.explanation}"
            items[ref] = hit


def get_invoice_evidence(db: Session, *, org_id: object, invoice_id: object) -> dict:
    """Citable evidence for one invoice: graph relationships + fuzzy retrieval.

    Org-scoped 404 first (procurement service); every subsequent query is
    org-filtered. Returns evidence items (source id/category/matched field/
    explanation/document location/trust status/retrieval score), the missing
    relationships, the data disagreements, and query metadata.
    """
    started = perf_counter()
    org_id = _uuid(org_id)
    invoice = procurement_service.get_invoice(
        db, org_id=org_id, invoice_id=_uuid(invoice_id)
    )
    graph: InvoiceGraph = invoice_evidence_graph(db, org_id=org_id, invoice=invoice)
    index = build_search_index(db, org_id=org_id)

    items: dict[tuple[str, str], SearchHit] = {}

    # ------------------------------------------------- deterministic edges --
    if graph.vendor is not None:
        vendor_row = index.by_ref((ENTITY_VENDOR, str(graph.vendor.id)))
        if vendor_row is not None:
            items[vendor_row.ref] = _graph_item(
                vendor_row,
                relationship="invoice→vendor",
                matched_field="vendor_id",
            )
    for account in graph.approved_accounts:
        row = index.by_ref((ENTITY_VENDOR_BANK_ACCOUNT, str(account.id)))
        if row is not None:
            items[row.ref] = _graph_item(
                row,
                relationship="vendor→approved_bank_account",
                matched_field="vendor_id",
            )
    effective_po = graph.purchase_order or graph.po_by_reference
    if effective_po is not None:
        from app.modules.retrieval.indexing import ENTITY_PURCHASE_ORDER

        row = index.by_ref((ENTITY_PURCHASE_ORDER, str(effective_po.id)))
        if row is not None:
            items[row.ref] = _graph_item(
                row,
                relationship=(
                    "invoice→purchase_order (linked)"
                    if graph.purchase_order is not None
                    else "invoice→purchase_order (printed reference match)"
                ),
                matched_field=(
                    "purchase_order_id"
                    if graph.purchase_order is not None
                    else "po_reference"
                ),
            )
    for earlier in graph.historical_invoices[:MAX_GRAPH_ITEMS]:
        from app.modules.retrieval.indexing import ENTITY_INVOICE

        row = index.by_ref((ENTITY_INVOICE, str(earlier.id)))
        if row is not None:
            items[row.ref] = _graph_item(
                row,
                relationship="vendor→historical_invoices",
                matched_field="vendor_id",
            )
    if graph.vendor is not None:
        verification_rows = [
            row
            for row in index.rows
            if row.entity_type == ENTITY_REVIEW_ACTION
            and row.provenance.get("case_vendor_id") == str(graph.vendor.id)
        ]
        for row in verification_rows[:MAX_GRAPH_ITEMS]:
            items[row.ref] = _graph_item(
                row,
                relationship="vendor→verification_events",
                matched_field="action_type",
            )

    # ------------------------------------------------------ fuzzy retrieval --
    # ``seeds`` feeds the actual search and may hold the raw remittance
    # account; ``meta_seeds`` is what the response echoes and carries the
    # masked form instead — full account numbers never leave the server
    # (schemas header; docs/API.md §5.8).
    seeds: list[str] = [invoice.invoice_number]
    meta_seeds: list[str] = [invoice.invoice_number]
    if graph.vendor is not None:
        seeds.append(graph.vendor.display_name)
        meta_seeds.append(graph.vendor.display_name)
        if graph.vendor.legal_name:
            seeds.append(graph.vendor.legal_name)
            meta_seeds.append(graph.vendor.legal_name)
    if graph.printed_po_reference:
        seeds.append(graph.printed_po_reference)
        meta_seeds.append(graph.printed_po_reference)
    if invoice.remittance_account_raw:
        seeds.append(invoice.remittance_account_raw)
        meta_seeds.append(
            "remittance_account_last4:" + invoice.remittance_account_raw[-4:]
        )
    for seed in seeds:
        result = search(db, org_id=org_id, query=seed, limit=25)
        _merge_fuzzy_hits(
            items,
            result,
            seed=seed,
            exclude={("invoice", str(invoice.id))},
        )

    ranked = sorted(
        items.values(),
        key=lambda h: (-h.final_score, h.entity_type, h.entity_id),
    )
    elapsed_ms = (perf_counter() - started) * 1000.0
    return {
        "evidence": ranked,
        "gaps": [g.to_dict() for g in graph.missing_gaps()],
        "contradictions": [g.to_dict() for g in graph.contradictions()],
        "meta": {
            "backend": get_backend(db).name,
            "weights": default_weights(),
            "seeds": meta_seeds,
            "latency_ms": round(elapsed_ms, 3),
        },
    }
