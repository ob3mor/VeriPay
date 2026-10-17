"""Hybrid ranking tests (Prompt-03 §3): Reciprocal Rank Fusion semantics,
configurable weights, and the baseline special-cases used for comparison."""

import pytest

from app.modules.retrieval.hybrid import (
    baseline_weights,
    default_weights,
    fuse,
)
from app.modules.retrieval.techniques import (
    RankedHit,
    TechniqueResult,
    TECH_EXACT,
    TECH_TEXT,
    TECH_TRIGRAM,
)


def _hit(ref, score=1.0):
    return RankedHit(ref=ref, score=score, explanation="test")


def _result(technique, refs):
    return TechniqueResult(technique, "test", [_hit(r) for r in refs])


ALL_ON = {"exact": 1.0, "text": 1.0, "trigram": 0.8, "vector": 0.0}


def test_rrf_prefers_candidates_present_in_multiple_lists():
    results = [
        _result(TECH_EXACT, [("invoice", "a"), ("invoice", "b")]),
        _result(TECH_TEXT, [("invoice", "b")]),
    ]
    fused = fuse(results, weights=ALL_ON, k=60)
    # b: 1/62 + 1/61 > a: 1/61 — appearing in both lists wins.
    assert [f.ref for f in fused] == [("invoice", "b"), ("invoice", "a")]
    a_score = 1.0 / (60 + 1)
    b_score = 1.0 / (60 + 2) + 1.0 / (60 + 1)
    assert fused[0].fused_score == pytest.approx(b_score)
    assert fused[1].fused_score == pytest.approx(a_score)


def test_rrf_weights_scale_contributions():
    results = [
        _result(TECH_EXACT, [("invoice", "a")]),
        _result(TECH_TEXT, [("invoice", "b")]),
    ]
    fused = fuse(
        results,
        weights={"exact": 1.5, "text": 1.0, "trigram": 0.0, "vector": 0.0},
        k=60,
    )
    # Both rank 1 in their single list; the higher weight wins.
    by_ref = {f.ref: f for f in fused}
    assert by_ref[("invoice", "a")].fused_score > by_ref[("invoice", "b")].fused_score

    inverted = fuse(
        results,
        weights={"exact": 0.5, "text": 1.0, "trigram": 0.0, "vector": 0.0},
        k=60,
    )
    by_ref = {f.ref: f for f in inverted}
    assert by_ref[("invoice", "b")].fused_score > by_ref[("invoice", "a")].fused_score


def test_zero_weight_excludes_a_technique_entirely():
    results = [
        _result(TECH_EXACT, [("invoice", "a")]),
        _result(TECH_TEXT, [("invoice", "b")]),
    ]
    fused = fuse(
        results,
        weights={"exact": 0.0, "text": 1.0, "trigram": 0.0, "vector": 0.0},
        k=60,
    )
    assert [f.ref for f in fused] == [("invoice", "b")]


def test_k_dampens_head_ranks():
    results = [_result(TECH_EXACT, [("invoice", "a"), ("invoice", "b")])]
    k60 = fuse(results, weights=ALL_ON, k=60)
    k1 = fuse(results, weights=ALL_ON, k=1)
    # With k=60, rank 1 and 2 are nearly equal; with k=1 they differ 2:1.
    spread_60 = k60[0].fused_score - k60[1].fused_score
    spread_1 = k1[0].fused_score - k1[1].fused_score
    assert spread_1 > spread_60


def test_deterministic_tiebreak_by_ref():
    # Same score → ref ascending. Two docs at rank 1 of two equally-weighted
    # lists tie in RRF; 'vendor:a' sorts before 'vendor:z'.
    results = [
        _result(TECH_EXACT, [("vendor", "z")]),
        _result(TECH_TEXT, [("vendor", "a")]),
    ]
    fused = fuse(
        results,
        weights={"exact": 1.0, "text": 1.0, "trigram": 0.0, "vector": 0.0},
        k=10,
    )
    assert [f.ref for f in fused] == [("vendor", "a"), ("vendor", "z")]


def test_baseline_weights_shapes():
    exact = baseline_weights("exact")
    lexical = baseline_weights("lexical")
    assert exact == {"exact": 1.0, "text": 0.0, "trigram": 0.0, "vector": 0.0}
    assert lexical == {"exact": 0.0, "text": 1.0, "trigram": 1.0, "vector": 0.0}
    with pytest.raises(ValueError):
        baseline_weights("nope")


def test_default_weights_come_from_settings():
    from app.core.config import get_settings

    settings = get_settings()
    weights = default_weights()
    assert weights["exact"] == settings.retrieval_weight_exact
    assert weights["text"] == settings.retrieval_weight_text
    assert weights["trigram"] == settings.retrieval_weight_trigram
    assert weights["vector"] == settings.retrieval_weight_vector


def test_explanation_lists_rank_and_contribution():
    results = [
        _result(TECH_EXACT, [("invoice", "a")]),
        _result(TECH_TRIGRAM, [("invoice", "a")]),
    ]
    fused = fuse(results, weights=ALL_ON, k=60)
    text = fused[0].explanation()
    assert "exact" in text and "trigram" in text
