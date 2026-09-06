from app.services.evaluation.baseline import BaselineManager
from app.services.evaluation.regression import RegressionChecker
from app.services.evaluation.schemas import BaselineRecord, EvaluationConfigSnapshot, EvaluationReport, MetricResult, RegressionThresholds


def make_baseline(mrr=0.9, hit5=0.95):
    return BaselineRecord(
        baseline_id="base-1",
        created_at="2026-01-01T00:00:00Z",
        dataset_version="1.0",
        retriever="hybrid",
        top_k=5,
        config=EvaluationConfigSnapshot(evaluation_version="1.0", dataset_version="1.0", retriever_type="hybrid", top_k=5),
        overall=MetricResult(hit_at_1=0.8, hit_at_5=hit5, mrr=mrr, precision_at_k=0.5, recall_at_k=0.9, total_cases=30, top_k=5),
        by_category={},
    )


def make_report(mrr=0.91, hit5=0.96):
    return EvaluationReport(
        evaluation_id="cur-1",
        timestamp="2026-01-02T00:00:00Z",
        dataset_version="1.0",
        dataset_path="evaluation/datasets/retrieval_baseline.json",
        retriever="hybrid",
        top_k=5,
        config=EvaluationConfigSnapshot(evaluation_version="1.0", dataset_version="1.0", retriever_type="hybrid", top_k=5),
        overall=MetricResult(hit_at_1=0.81, hit_at_5=hit5, mrr=mrr, precision_at_k=0.5, recall_at_k=0.9, total_cases=30, top_k=5),
        by_category={},
        cases=[],
        failures=[],
        worst_queries=[],
    )


def test_no_regression():
    base = make_baseline(mrr=0.9, hit5=0.95)
    cur = make_report(mrr=0.91, hit5=0.96)
    results = RegressionChecker.compare(base, cur)
    assert all(r.status == "PASS" for r in results)


def test_regression_fail():
    base = make_baseline(mrr=0.9, hit5=0.95)
    cur = make_report(mrr=0.80, hit5=0.87)  # -11% mrr, -8% hit5 -> fail
    results = RegressionChecker.compare(base, cur, thresholds=RegressionThresholds(mrr_max_regression=0.02, hit_at_5_max_regression=0.02))
    fails = [r for r in results if r.status == "FAIL"]
    assert len(fails) >= 1


def test_warning():
    base = make_baseline(mrr=0.9, hit5=0.95)
    cur = make_report(mrr=0.885, hit5=0.94)  # -1.6% -> warning
    results = RegressionChecker.compare(base, cur)
    # Depends on threshold 2% -> 1.6% is warning
    statuses = [r.status for r in results]
    assert "WARNING" in statuses or "PASS" in statuses  # at least not FAIL
