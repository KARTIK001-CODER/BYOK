import tempfile
from pathlib import Path
from app.services.evaluation.reporting import console_report, write_json_report, write_markdown_report
from app.services.evaluation.schemas import EvaluationReport, EvaluationConfigSnapshot, MetricResult, CaseResult, EvaluationCategory, EvaluationDifficulty


def make_report():
    overall = MetricResult(hit_at_1=0.8, hit_at_3=0.9, hit_at_5=0.95, mrr=0.88, precision_at_k=0.5, recall_at_k=0.95, total_cases=10, top_k=5)
    by_cat = {"semantic": MetricResult(hit_at_1=0.9, hit_at_5=1.0, mrr=0.95, precision_at_k=0.6, recall_at_k=1.0, total_cases=3, top_k=5)}
    config = EvaluationConfigSnapshot(evaluation_version="1.0", dataset_version="1.0", retriever_type="hybrid", embedding_model="test-model", embedding_dimension=384, top_k=5, candidate_k=30, fusion_method="rrf", rrf_k=60)
    case = CaseResult(case_id="eval_001", query="refund?", category=EvaluationCategory.semantic, difficulty=EvaluationDifficulty.easy, expected=[], retrieved=[], top_k=5, hit_at_k={"5": True}, mrr=1.0, precision_at_k=1.0, recall_at_k=1.0, first_relevant_rank=1, status="hit")
    return EvaluationReport(evaluation_id="test-id", timestamp="2026-01-01T00:00:00Z", dataset_version="1.0", dataset_path="evaluation/datasets/retrieval_baseline.json", retriever="hybrid", top_k=5, config=config, overall=overall, by_category=by_cat, cases=[case], failures=[], worst_queries=[case])


def test_console():
    r = make_report()
    out = console_report(r)
    assert "BYOK RETRIEVAL EVALUATION" in out
    assert "Hit@5" in out


def test_json_and_markdown(tmp_path):
    r = make_report()
    j = write_json_report(r, tmp_path)
    assert j.exists()
    m = write_markdown_report(r, tmp_path)
    assert m.exists()
    assert "Retrieval Evaluation" in m.read_text()
