"""IR evaluation metrics (Prompt-03 §8): Precision@K, Recall@K, MRR, nDCG@K.

Pure functions over ranked id lists + labeled relevance — no DB, no scores
invented. Graded relevance uses the standard 0–3 scale (0 = not relevant).
Latency is measured with ``time.perf_counter`` around real ranker calls and
reported (mean / p95) — honestly labeled synthetic data, real timing.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from statistics import mean


def precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for doc in top if doc in relevant) / len(top)


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(ranked[:k])
    return len(top & relevant) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    for position, doc in enumerate(ranked, start=1):
        if doc in relevant:
            return 1.0 / position
    return 0.0


def dcg_at_k(ranked: list[str], grades: dict[str, int], k: int) -> float:
    """Discounted cumulative gain with the standard log2 discount."""
    total = 0.0
    for position, doc in enumerate(ranked[:k], start=1):
        gain = float(grades.get(doc, 0))
        total += gain / math.log2(position + 1)
    return total


def ndcg_at_k(ranked: list[str], grades: dict[str, int], k: int) -> float:
    if k <= 0 or not grades:
        return 0.0
    ideal = sorted(grades.values(), reverse=True)
    idcg = sum(float(g) / math.log2(i + 2) for i, g in enumerate(ideal[:k]))
    if idcg == 0.0:
        return 0.0
    return dcg_at_k(ranked, grades, k) / idcg


@dataclass
class QueryMetrics:
    query: str
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg_at_k: float
    latency_ms: float


@dataclass
class EvaluationReport:
    k: int
    queries: list[QueryMetrics]

    @property
    def mean_precision(self) -> float:
        return mean(q.precision_at_k for q in self.queries) if self.queries else 0.0

    @property
    def mean_recall(self) -> float:
        return mean(q.recall_at_k for q in self.queries) if self.queries else 0.0

    @property
    def mrr(self) -> float:
        return mean(q.mrr for q in self.queries) if self.queries else 0.0

    @property
    def mean_ndcg(self) -> float:
        return mean(q.ndcg_at_k for q in self.queries) if self.queries else 0.0

    @property
    def mean_latency_ms(self) -> float:
        return mean(q.latency_ms for q in self.queries) if self.queries else 0.0

    @property
    def p95_latency_ms(self) -> float:
        if not self.queries:
            return 0.0
        ordered = sorted(q.latency_ms for q in self.queries)
        index = min(len(ordered) - 1, max(0, round(0.95 * (len(ordered) - 1))))
        return ordered[index]

    def summary(self) -> str:
        return (
            f"P@{self.k}={self.mean_precision:.3f} "
            f"R@{self.k}={self.mean_recall:.3f} "
            f"MRR={self.mrr:.3f} "
            f"nDCG@{self.k}={self.mean_ndcg:.3f} "
            f"latency mean={self.mean_latency_ms:.2f}ms "
            f"p95={self.p95_latency_ms:.2f}ms"
        )


def evaluate(
    labeled: list[tuple[str, list[str], dict[str, int]]],
    *,
    k: int,
    ranker,
) -> EvaluationReport:
    """Run ``ranker(query) -> ranked ids`` over the labeled collection.

    ``labeled`` items are ``(query, relevant_ids, graded_relevance)``.
    Latency is measured around each real ``ranker`` call.
    """
    rows: list[QueryMetrics] = []
    for query, relevant_ids, grades in labeled:
        started = time.perf_counter()
        ranked = list(ranker(query))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        relevant = set(relevant_ids)
        rows.append(
            QueryMetrics(
                query=query,
                precision_at_k=precision_at_k(ranked, relevant, k),
                recall_at_k=recall_at_k(ranked, relevant, k),
                mrr=reciprocal_rank(ranked, relevant),
                ndcg_at_k=ndcg_at_k(ranked, grades, k),
                latency_ms=elapsed_ms,
            )
        )
    return EvaluationReport(k=k, queries=rows)
