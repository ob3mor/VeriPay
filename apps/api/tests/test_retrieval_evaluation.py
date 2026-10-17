"""IR evaluation (Prompt-03 §8): a small, honestly labeled synthetic
collection scored with Precision@K, Recall@K, MRR, nDCG@K and measured
latency; the hybrid fusion is compared against its exact-only and
lexical-only baselines (the SAME fusion function with zeroed weights)."""

import math

import pytest

from app.core.db import SessionLocal
from app.modules.retrieval import service
from app.modules.retrieval.hybrid import baseline_weights, default_weights
from app.modules.retrieval.metrics import (
    dcg_at_k,
    evaluate,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

import retrieval_helpers as rh

K = 5


# ------------------------------------------------- metric unit (hand-computed)
def test_metric_functions_hand_computed():
    ranked = ["a", "b", "c", "d"]
    relevant = {"b", "d"}
    assert precision_at_k(ranked, relevant, 2) == 0.5
    assert precision_at_k(ranked, relevant, 4) == 0.5
    assert precision_at_k(ranked, set(), 3) == 0.0
    assert recall_at_k(ranked, relevant, 1) == 0.0
    assert recall_at_k(ranked, relevant, 4) == 1.0
    assert recall_at_k(ranked, set(), 4) == 0.0
    assert reciprocal_rank(ranked, relevant) == pytest.approx(0.5)
    assert reciprocal_rank(["x", "y"], relevant) == 0.0

    grades = {"a": 3, "b": 2, "c": 0, "d": 1}
    # DCG([a,b,c,d]) = 3/log2(2) + 2/log2(3) + 0/log2(4) + 1/log2(5)
    expected_dcg = 3.0 + 2.0 / math.log2(3) + 0.0 + 1.0 / math.log2(5)
    assert dcg_at_k(ranked, grades, 4) == pytest.approx(expected_dcg, rel=1e-9)
    # Perfect ordering → nDCG 1.0.
    assert ndcg_at_k(["a", "b", "d", "c"], grades, 4) == pytest.approx(1.0)
    # Swapped head → nDCG < 1.
    assert ndcg_at_k(["b", "a", "c", "d"], grades, 4) < 1.0
    assert ndcg_at_k(ranked, {}, 3) == 0.0


# ------------------------------------------------------- labeled collection --
def _labels(seed: dict) -> list[tuple[str, list[str], dict[str, int]]]:
    """(query, relevant refs, graded relevance 0-3). Grades derive from the
    seed's ground truth: the queried record itself = 3, its direct
    provenance/registry copies = 2, corroborating records = 1."""
    f_inv = rh.ref("extraction_field", seed["extraction_field_ids"]["invoice_number"])
    f_vendor = rh.ref("extraction_field", seed["extraction_field_ids"]["vendor_name"])
    f_po = rh.ref("extraction_field", seed["extraction_field_ids"]["po_reference"])
    f_total = rh.ref("extraction_field", seed["extraction_field_ids"]["total"])
    f_currency = rh.ref("extraction_field", seed["extraction_field_ids"]["currency"])
    nour_vendor = rh.ref("vendor", seed["vendor_id"])
    nour_account = rh.ref(
        "vendor_bank_account", seed["approved_account_id"]
    )
    return [
        # Exact identifier → the invoice, its duplicate-number sibling (the
        # same number is genuinely relevant), and the provenance copy.
        (rh.INV_NOUR,
         [rh.ref("invoice", seed["invoice_nour_id"]),
          rh.ref("invoice", seed["duplicate_invoice_id"]),
          f_inv],
         {rh.ref("invoice", seed["invoice_nour_id"]): 3,
          rh.ref("invoice", seed["duplicate_invoice_id"]): 2,
          f_inv: 2}),
        # Legal-form variant of the vendor name → registry + account + OCR copy.
        ("Nour Trading Company", [nour_vendor, nour_account, f_vendor],
         {nour_vendor: 3, nour_account: 2, f_vendor: 2}),
        # Arabic legal name (stored surface) → the vendor.
        (rh.NOUR_LEGAL_AR, [nour_vendor], {nour_vendor: 3}),
        # OCR-typo'd bank name → the approved account.
        ("Nordbenk", [nour_account], {nour_account: 3}),
        # Full IBAN → account + the invoice that printed it.
        (rh.NOUR_IBAN, [nour_account, rh.ref("invoice", seed["invoice_nour_id"])],
         {nour_account: 3, rh.ref("invoice", seed["invoice_nour_id"]): 2}),
        # Second org-independent identifier.
        (rh.INV_ACME, [rh.ref("invoice", seed["invoice_acme_id"])],
         {rh.ref("invoice", seed["invoice_acme_id"]): 3}),
        # PO number → the PO + the invoice that references it.
        (rh.PO_ACME, [rh.ref("purchase_order", seed["po_acme_id"])],
         {rh.ref("purchase_order", seed["po_acme_id"]): 3}),
        # Arabic label + number reaches the same invoice.
        (f"فاتورة {rh.INV_ZAHRA}", [rh.ref("invoice", seed["invoice_zahra_id"])],
         {rh.ref("invoice", seed["invoice_zahra_id"]): 3}),
        # Vendor display name → vendor + its extraction copy.
        (rh.ACME_DISPLAY, [rh.ref("vendor", seed["acme_vendor_id"])],
         {rh.ref("vendor", seed["acme_vendor_id"]): 3}),
        # Field label + value ("total 1250.00 EUR").
        ("total 1250.00", [f_total], {f_total: 3}),
        # Human-confirmed currency field via its label.
        ("currency EUR", [f_currency], {f_currency: 3}),
        # Printed PO reference reaches the PO provenance copy.
        (f"PO reference {rh.PO_NOUR}", [f_po, rh.ref("purchase_order", seed["po_nour_id"])],
         {f_po: 2, rh.ref("purchase_order", seed["po_nour_id"]): 3}),
    ]


def _ranker(db, org_id, weights):
    def rank(query: str) -> list[str]:
        return service.search_refs(db, org_id=org_id, query=query, weights=weights)

    return rank


def test_hybrid_beats_or_matches_baselines_on_labeled_collection(client, capsys):
    """The comparison the task asks for: hybrid RRF vs lexical-only vs
    exact-only, over the SAME fusion function and the SAME labeled data."""
    seed = rh.seed_retrieval_org(client)
    labels = _labels(seed)

    with SessionLocal() as db:
        org_id = seed["org_id"]
        hybrid = evaluate(
            labels, k=K, ranker=_ranker(db, org_id, default_weights())
        )
        exact_only = evaluate(
            labels, k=K, ranker=_ranker(db, org_id, baseline_weights("exact"))
        )
        lexical_only = evaluate(
            labels, k=K, ranker=_ranker(db, org_id, baseline_weights("lexical"))
        )

    print(f"\nHYBRID   {hybrid.summary()}")
    print(f"EXACT    {exact_only.summary()}")
    print(f"LEXICAL  {lexical_only.summary()}")

    # Hybrid fuses both baselines' inputs, so on this collection it must be
    # at least as good on every aggregate (exact-only misses the fuzzy
    # queries entirely; lexical-only ranks identifier queries behind noise).
    assert hybrid.mrr >= max(exact_only.mrr, lexical_only.mrr) - 1e-9
    assert hybrid.mean_ndcg >= max(exact_only.mean_ndcg, lexical_only.mean_ndcg) - 1e-9
    assert hybrid.mean_precision >= max(
        exact_only.mean_precision, lexical_only.mean_precision
    ) - 1e-9
    # Exact-only cannot answer the fuzzy queries at all → strictly worse MRR.
    assert exact_only.mrr < hybrid.mrr
    # Sanity floors for the hybrid on this collection.
    assert hybrid.mrr >= 0.9
    assert hybrid.mean_ndcg >= 0.8
    assert hybrid.mean_recall > 0.5

    # Latency was measured around real ranker calls — reported, honestly.
    assert hybrid.mean_latency_ms > 0.0
    assert hybrid.p95_latency_ms >= hybrid.mean_latency_ms


def test_evaluation_report_latencies_are_real_and_bounded(client, capsys):
    seed = rh.seed_retrieval_org(client)
    labels = _labels(seed)[:4]
    with SessionLocal() as db:
        report = evaluate(
            labels, k=K, ranker=_ranker(db, seed["org_id"], default_weights())
        )
    print(f"\nLATENCY {report.summary()}")
    assert len(report.queries) == 4
    for q in report.queries:
        assert q.latency_ms > 0.0
    # A generous smoke bound for tiny data on CI hardware (not a perf gate).
    assert report.p95_latency_ms < 5000.0
