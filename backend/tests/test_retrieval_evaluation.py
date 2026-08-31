import pytest

from app.evaluation.metrics import RetrievalMetrics


def test_retrieval_metrics_recall_at_k() -> None:
    """Verify Recall@K calculation."""
    retrieved = ["doc-1", "doc-2", "doc-3", "doc-4", "doc-5"]
    relevant = ["doc-2", "doc-4", "doc-6"]

    # In top 3: only doc-2 retrieved -> 1 / 3 ≈ 0.3333
    assert pytest.approx(RetrievalMetrics.recall_at_k(retrieved, relevant, k=3), 1e-4) == 1 / 3

    # In top 5: doc-2 and doc-4 retrieved -> 2 / 3 ≈ 0.6667
    assert pytest.approx(RetrievalMetrics.recall_at_k(retrieved, relevant, k=5), 1e-4) == 2 / 3

    # Edge cases
    assert RetrievalMetrics.recall_at_k([], relevant, k=5) == 0.0
    assert RetrievalMetrics.recall_at_k(retrieved, [], k=5) == 0.0


def test_retrieval_metrics_precision_at_k() -> None:
    """Verify Precision@K calculation."""
    retrieved = ["doc-1", "doc-2", "doc-3", "doc-4", "doc-5"]
    relevant = ["doc-2", "doc-4", "doc-6"]

    # In top 3: only doc-2 is relevant -> 1 / 3 ≈ 0.3333
    assert pytest.approx(RetrievalMetrics.precision_at_k(retrieved, relevant, k=3), 1e-4) == 1 / 3

    # In top 5: doc-2 and doc-4 are relevant -> 2 / 5 = 0.40
    assert pytest.approx(RetrievalMetrics.precision_at_k(retrieved, relevant, k=5), 1e-4) == 0.40

    # Edge cases
    assert RetrievalMetrics.precision_at_k(retrieved, relevant, k=0) == 0.0
    assert RetrievalMetrics.precision_at_k([], relevant, k=5) == 0.0


def test_retrieval_metrics_reciprocal_rank() -> None:
    """Verify Mean Reciprocal Rank (MRR) individual item calculation."""
    # First relevant item at rank 1 -> RR = 1.0
    assert RetrievalMetrics.reciprocal_rank(["doc-1", "doc-2"], ["doc-1"]) == 1.0

    # First relevant item at rank 2 -> RR = 0.5
    assert RetrievalMetrics.reciprocal_rank(["doc-1", "doc-2", "doc-3"], ["doc-2"]) == 0.5

    # First relevant item at rank 4 -> RR = 0.25
    assert RetrievalMetrics.reciprocal_rank(["d1", "d2", "d3", "d4"], ["d4"]) == 0.25

    # No relevant items -> RR = 0.0
    assert RetrievalMetrics.reciprocal_rank(["d1", "d2"], ["d3"]) == 0.0
