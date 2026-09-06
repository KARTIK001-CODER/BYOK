import pytest
from app.services.evaluation.metrics import EvaluationMetrics


def test_hit_at_k():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = ["b", "d"]
    assert EvaluationMetrics.hit_at_k(retrieved, relevant, 1) is False
    assert EvaluationMetrics.hit_at_k(retrieved, relevant, 2) is True
    assert EvaluationMetrics.hit_at_k(retrieved, relevant, 5) is True
    assert EvaluationMetrics.hit_at_k([], relevant, 5) is False
    assert EvaluationMetrics.hit_at_k(retrieved, [], 5) is False
    assert EvaluationMetrics.hit_at_k(retrieved, relevant, 0) is False


def test_mrr():
    assert EvaluationMetrics.reciprocal_rank(["a", "b", "c"], ["a"]) == 1.0
    assert EvaluationMetrics.reciprocal_rank(["a", "b", "c"], ["b"]) == 0.5
    assert EvaluationMetrics.reciprocal_rank(["a", "b", "c", "d"], ["d"]) == 0.25
    assert EvaluationMetrics.reciprocal_rank(["a", "b"], ["c"]) == 0.0
    assert EvaluationMetrics.reciprocal_rank([], ["a"]) == 0.0


def test_precision_recall():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = ["b", "d", "f"]
    # top3: b only
    assert EvaluationMetrics.precision_at_k(retrieved, relevant, 3) == pytest.approx(1 / 3)
    assert EvaluationMetrics.recall_at_k(retrieved, relevant, 3) == pytest.approx(1 / 3)
    # top5: b,d
    assert EvaluationMetrics.precision_at_k(retrieved, relevant, 5) == pytest.approx(2 / 5)
    assert EvaluationMetrics.recall_at_k(retrieved, relevant, 5) == pytest.approx(2 / 3)
    # edge
    assert EvaluationMetrics.precision_at_k(retrieved, relevant, 0) == 0.0
    assert EvaluationMetrics.recall_at_k([], relevant, 5) == 0.0
    assert EvaluationMetrics.recall_at_k(retrieved, [], 5) == 0.0


def test_aggregate():
    from app.services.evaluation.schemas import CaseResult, EvaluationCategory, EvaluationDifficulty, RetrievedResult

    def make_case(hit):
        return CaseResult(
            case_id="x",
            query="q",
            category=EvaluationCategory.semantic,
            difficulty=EvaluationDifficulty.easy,
            expected=[],
            retrieved=[],
            top_k=5,
            hit_at_k={"1": hit, "3": hit, "5": hit, "10": hit},
            mrr=1.0 if hit else 0.0,
            precision_at_k=1.0 if hit else 0.0,
            recall_at_k=1.0 if hit else 0.0,
            first_relevant_rank=1 if hit else None,
            status="hit" if hit else "miss",
        )

    cases = [make_case(True), make_case(True), make_case(False)]
    agg = EvaluationMetrics.aggregate(cases, top_k=5)
    assert agg.hit_at_5 == pytest.approx(0.6667, abs=1e-3)
    assert agg.hit_at_1 == pytest.approx(0.6667, abs=1e-3)
    assert agg.mrr == pytest.approx(0.6667, abs=1e-3)


def test_no_relevant():
    assert EvaluationMetrics.hit_at_k(["a", "b"], [], 5) is False
    assert EvaluationMetrics.precision_at_k(["a", "b"], [], 5) == 0.0  # actually precision with no relevant but retrieved: 0


def test_duplicate_results():
    # duplicates should not double count
    retrieved = ["a", "a", "b"]
    relevant = ["a"]
    assert EvaluationMetrics.hit_at_k(retrieved, relevant, 2) is True
    assert EvaluationMetrics.precision_at_k(retrieved, relevant, 3) == pytest.approx(1 / 3)  # only one unique relevant? set based so 1/3
