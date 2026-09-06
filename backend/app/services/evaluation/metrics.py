"""Core IR metrics — Hit@K, MRR, Precision@K, Recall@K with per-category aggregation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from app.services.evaluation.schemas import CaseResult, EvaluationCategory, MetricResult


class EvaluationMetrics:
    """Stateless metric calculations + aggregation helpers."""

    @staticmethod
    def hit_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> bool:
        if k <= 0 or not relevant_ids:
            return False
        return bool(set(retrieved_ids[:k]).intersection(set(relevant_ids)))

    @staticmethod
    def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float:
        if not relevant_ids:
            return 0.0
        top_k = set(retrieved_ids[:k])
        rel = set(relevant_ids)
        return len(top_k.intersection(rel)) / len(rel)

    @staticmethod
    def precision_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float:
        if k <= 0:
            return 0.0
        top_k = set(retrieved_ids[:k])
        rel = set(relevant_ids)
        intersect = top_k.intersection(rel)
        denom = min(k, len(retrieved_ids) if retrieved_ids else k)
        return len(intersect) / denom if denom else 0.0

    @staticmethod
    def reciprocal_rank(retrieved_ids: Sequence[str], relevant_ids: Sequence[str]) -> float:
        rel = set(relevant_ids)
        for rank, rid in enumerate(retrieved_ids, start=1):
            if rid in rel:
                return 1.0 / rank
        return 0.0

    @staticmethod
    def mrr(case_mrrs: Sequence[float]) -> float:
        if not case_mrrs:
            return 0.0
        return sum(case_mrrs) / len(case_mrrs)

    @classmethod
    def evaluate_case(
        cls,
        retrieved_ids: Sequence[str],
        relevant_ids: Sequence[str],
        k: int,
        top_k_values: Sequence[int] | None = None,
    ) -> dict[str, float | bool]:
        top_k_values = top_k_values or [1, 3, 5, 10]
        out: dict[str, float | bool] = {}
        for tk in top_k_values:
            out[f"hit@{tk}"] = cls.hit_at_k(retrieved_ids, relevant_ids, tk)
            out[f"recall@{tk}"] = cls.recall_at_k(retrieved_ids, relevant_ids, tk)
            out[f"precision@{tk}"] = cls.precision_at_k(retrieved_ids, relevant_ids, tk)
        out["mrr"] = cls.reciprocal_rank(retrieved_ids, relevant_ids)
        return out

    @classmethod
    def aggregate(
        cls,
        case_results: list[CaseResult],
        top_k: int = 5,
        top_k_values: Sequence[int] | None = None,
    ) -> MetricResult:
        top_k_values = top_k_values or [1, 3, 5, 10]
        n = len(case_results)
        if n == 0:
            return MetricResult(top_k=top_k, total_cases=0)
        # collect per-case values for requested top_k
        hits_1 = sum(1 for c in case_results if c.hit_at_k.get("1", False)) / n
        hits_3 = sum(1 for c in case_results if c.hit_at_k.get("3", False)) / n
        hits_5 = sum(1 for c in case_results if c.hit_at_k.get("5", False)) / n
        hits_10 = sum(1 for c in case_results if c.hit_at_k.get("10", False)) / n if 10 in top_k_values else None
        avg_mrr = sum(c.mrr for c in case_results) / n
        avg_prec = sum(c.precision_at_k for c in case_results) / n
        avg_rec = sum(c.recall_at_k for c in case_results) / n
        return MetricResult(
            hit_at_1=round(hits_1, 4),
            hit_at_3=round(hits_3, 4),
            hit_at_5=round(hits_5, 4),
            hit_at_10=round(hits_10, 4) if hits_10 is not None else None,
            mrr=round(avg_mrr, 4),
            precision_at_k=round(avg_prec, 4),
            recall_at_k=round(avg_rec, 4),
            total_cases=n,
            top_k=top_k,
        )

    @classmethod
    def aggregate_by_category(
        cls,
        case_results: list[CaseResult],
        top_k: int = 5,
    ) -> dict[str, MetricResult]:
        grouped: dict[str, list[CaseResult]] = defaultdict(list)
        for c in case_results:
            grouped[c.category.value].append(c)
        return {cat: cls.aggregate(cases, top_k=top_k) for cat, cases in grouped.items()}

    @classmethod
    def aggregate_by_difficulty(
        cls,
        case_results: list[CaseResult],
        top_k: int = 5,
    ) -> dict[str, MetricResult]:
        grouped: dict[str, list[CaseResult]] = defaultdict(list)
        for c in case_results:
            grouped[c.difficulty.value].append(c)
        return {diff: cls.aggregate(cases, top_k=top_k) for diff, cases in grouped.items()}
