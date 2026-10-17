"""Hybrid ranking: Reciprocal Rank Fusion over technique lists (Prompt-03 §3).

``score(d) = Σ_t  w_t / (k + rank_t(d))`` — rank is the 1-based position of
``d`` in technique ``t``'s list; ``k`` (default 60) dampens the head so one
list cannot dominate. Weights are configurable, which is what makes the
lexical-only and exact-only baselines expressible as special cases of the
same function (the evaluation tests compare them honestly).

Fusion output is still *unscaled* evidence; the trust-tier multiplier
(``trust.py``) is applied afterwards as a separate, inspectable step — never
inside the fusion, so retrieval quality and trust are independently auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings
from app.modules.retrieval.techniques import (
    TECH_EXACT,
    TECH_TEXT,
    TECH_TRIGRAM,
    TECH_VECTOR,
    TechniqueResult,
    Ref,
)

CANONICAL_TECHNIQUES = (TECH_EXACT, TECH_TEXT, TECH_TRIGRAM, TECH_VECTOR)


def default_weights() -> dict[str, float]:
    """Settings-backed defaults (VERIPAY_RETRIEVAL_WEIGHT_*)."""
    settings = get_settings()
    return {
        TECH_EXACT: settings.retrieval_weight_exact,
        TECH_TEXT: settings.retrieval_weight_text,
        TECH_TRIGRAM: settings.retrieval_weight_trigram,
        TECH_VECTOR: settings.retrieval_weight_vector,
    }


def baseline_weights(kind: str) -> dict[str, float]:
    """The comparison baselines as special cases of the same fusion.

    - ``exact``: exact identifiers only.
    - ``lexical``: normalized/full-text + trigram (no exact, no vector).
    """
    zeros = {t: 0.0 for t in CANONICAL_TECHNIQUES}
    if kind == "exact":
        zeros[TECH_EXACT] = 1.0
    elif kind == "lexical":
        zeros[TECH_TEXT] = 1.0
        zeros[TECH_TRIGRAM] = 1.0
    else:
        raise ValueError(f"unknown baseline: {kind!r}")
    return zeros


@dataclass
class FusedHit:
    """One fused candidate with its per-technique contributions (auditable)."""

    ref: Ref
    fused_score: float
    techniques: dict[str, int] = field(default_factory=dict)  # name → best rank
    contributions: dict[str, float] = field(default_factory=dict)  # name → score

    @property
    def technique_names(self) -> list[str]:
        return sorted(self.techniques)

    def explanation(self) -> str:
        parts = [
            f"{name}: rank {rank} (contribution {self.contributions[name]:.5f})"
            for name, rank in sorted(self.techniques.items(), key=lambda kv: kv[1])
        ]
        return "RRF[" + "; ".join(parts) + "]"


def fuse(
    technique_results: list[TechniqueResult],
    *,
    weights: dict[str, float] | None = None,
    k: int | None = None,
) -> list[FusedHit]:
    """Reciprocal Rank Fusion over the technique lists.

    Zero-weighted techniques are excluded entirely (that is how the baselines
    disable techniques); a technique with an empty list contributes nothing.
    Ties resolve by (score desc, ref asc) — deterministic order.
    """
    w = weights if weights is not None else default_weights()
    k = k if k is not None else get_settings().retrieval_fusion_k
    fused: dict[Ref, FusedHit] = {}
    for result in technique_results:
        weight = float(w.get(result.technique, 0.0))
        if weight == 0.0 or not result.hits:
            continue
        for rank, hit in enumerate(result.hits, start=1):
            contribution = weight / (k + rank)
            entry = fused.setdefault(
                hit.ref, FusedHit(ref=hit.ref, fused_score=0.0)
            )
            entry.fused_score += contribution
            if hit.ref and (
                result.technique not in entry.techniques
                or rank < entry.techniques[result.technique]
            ):
                entry.techniques[result.technique] = rank
            entry.contributions[result.technique] = (
                entry.contributions.get(result.technique, 0.0) + contribution
            )
    return sorted(fused.values(), key=lambda h: (-h.fused_score, h.ref))
