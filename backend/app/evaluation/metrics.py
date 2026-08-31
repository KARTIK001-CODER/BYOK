from collections.abc import Sequence


class RetrievalMetrics:
    """
    Standard Information Retrieval (IR) evaluation metrics.

    Calculates:
    - Recall@K: Proportion of relevant chunks retrieved in top K results.
    - Precision@K: Proportion of top K retrieved chunks that are relevant.
    - MRR (Mean Reciprocal Rank): 1 / rank of the first relevant chunk found.
    """

    @staticmethod
    def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float:
        """
        Recall@K = |Retrieved_K ∩ Relevant| / |Relevant|
        """
        if not relevant_ids:
            return 0.0
        top_k_retrieved = set(retrieved_ids[:k])
        rel_set = set(relevant_ids)
        intersect = top_k_retrieved.intersection(rel_set)
        return len(intersect) / len(rel_set)

    @staticmethod
    def precision_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float:
        """
        Precision@K = |Retrieved_K ∩ Relevant| / K
        """
        if k <= 0:
            return 0.0
        top_k_retrieved = set(retrieved_ids[:k])
        rel_set = set(relevant_ids)
        intersect = top_k_retrieved.intersection(rel_set)
        return len(intersect) / min(k, len(retrieved_ids) if retrieved_ids else k)

    @staticmethod
    def reciprocal_rank(retrieved_ids: Sequence[str], relevant_ids: Sequence[str]) -> float:
        """
        Reciprocal Rank (RR) = 1 / rank of first relevant item in retrieved list (1-indexed).
        Returns 0.0 if no relevant items are found.
        """
        rel_set = set(relevant_ids)
        for rank, item_id in enumerate(retrieved_ids, start=1):
            if item_id in rel_set:
                return 1.0 / rank
        return 0.0

    @classmethod
    def evaluate_query(
        cls,
        retrieved_ids: Sequence[str],
        relevant_ids: Sequence[str],
        k: int = 5,
    ) -> dict[str, float]:
        """Compute all IR metrics for a single query."""
        return {
            f"recall@{k}": cls.recall_at_k(retrieved_ids, relevant_ids, k),
            f"precision@{k}": cls.precision_at_k(retrieved_ids, relevant_ids, k),
            "mrr": cls.reciprocal_rank(retrieved_ids, relevant_ids),
        }
