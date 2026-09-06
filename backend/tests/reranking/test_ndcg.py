import pytest
from app.services.evaluation.metrics import EvaluationMetrics


def test_ndcg_perfect():
    retrieved = ["a", "b", "c"]
    relevant = {"a": 3, "b": 2, "c": 1}
    # Perfect order a,b,c should give NDCG 1.0
    assert EvaluationMetrics.ndcg_at_k(retrieved, relevant, 3) == pytest.approx(1.0)


def test_ndcg_reverse():
    retrieved = ["c", "b", "a"]
    relevant = {"a": 3, "b": 2, "c": 1}
    # Reverse should be lower
    ndcg = EvaluationMetrics.ndcg_at_k(retrieved, relevant, 3)
    assert 0 < ndcg < 1.0
    # Worst vs perfect
    perfect = EvaluationMetrics.ndcg_at_k(["a", "b", "c"], relevant, 3)
    assert ndcg < perfect


def test_ndcg_no_relevant():
    assert EvaluationMetrics.ndcg_at_k(["a", "b"], {}, 3) == 0.0
    assert EvaluationMetrics.ndcg_at_k(["a", "b"], {"a": 0}, 3) == 0.0


def test_ndcg_single():
    assert EvaluationMetrics.ndcg_at_k(["a"], {"a": 1}, 1) == pytest.approx(1.0)
    assert EvaluationMetrics.ndcg_at_k(["b"], {"a": 1}, 1) == 0.0


def test_ndcg_empty():
    assert EvaluationMetrics.ndcg_at_k([], {"a": 1}, 5) == 0.0


def test_ndcg_dedup():
    # Duplicate doc should not inflate NDCG >1
    retrieved = ["a", "a", "b"]
    relevant = {"a": 1}
    ndcg = EvaluationMetrics.ndcg_at_k(retrieved, relevant, 3)
    assert ndcg <= 1.0
