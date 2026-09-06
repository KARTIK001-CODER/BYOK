import json
import tempfile
from pathlib import Path
import pytest
from app.services.evaluation.dataset import EvaluationDatasetLoader
from app.services.evaluation.schemas import EvaluationCategory, EvaluationCase, EvaluationDataset, ExpectedResult


def test_dataset_validation_duplicate_ids():
    with pytest.raises(ValueError, match="Duplicate"):
        EvaluationDataset(
            version="1.0",
            cases=[
                EvaluationCase(id="eval_001", query="What is refund?", category=EvaluationCategory.factual, expected=[ExpectedResult(document_name="Refund Policy")]),
                EvaluationCase(id="eval_001", query="Duplicate?", category=EvaluationCategory.factual, expected=[ExpectedResult(document_name="Pricing")]),
            ],
        )


def test_dataset_validation_missing_expected():
    # Expected must be >=1 via pydantic
    with pytest.raises(Exception):
        EvaluationCase(id="eval_002", query="Missing expected?", category=EvaluationCategory.keyword, expected=[])


def test_dataset_validation_invalid_category():
    with pytest.raises(Exception):
        EvaluationCase(id="eval_003", query="Invalid cat?", category="not_a_category", expected=[ExpectedResult(document_name="x")])


def test_loader_valid():
    ds = EvaluationDataset(
        version="1.0",
        cases=[
            EvaluationCase(id="eval_001", query="Valid query about refund policy?", category=EvaluationCategory.semantic, expected=[ExpectedResult(document_name="Refund Policy")]),
        ],
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(ds.model_dump(), f)
        path = f.name
    loaded = EvaluationDatasetLoader.load(Path(path))
    assert len(loaded.cases) == 1


def test_loader_missing_query():
    raw = {"version": "1.0", "cases": [{"id": "eval_001", "query": "  ", "category": "factual", "expected": [{"document_name": "Refund Policy"}]}]}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(raw, f)
        path = f.name
    with pytest.raises(Exception):
        EvaluationDatasetLoader.load(Path(path))


def test_loader_legacy_conversion(tmp_path):
    legacy = {
        "description": "legacy",
        "documents": [{"id": "doc-1", "title": "Doc 1", "content": "hello"}],
        "queries": [{"query": "hello?", "relevant_doc_ids": ["doc-1"]}],
    }
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(legacy), encoding="utf-8")
    ds = EvaluationDatasetLoader.load(p)
    assert ds.version == "0.9-migrated"
    assert len(ds.cases) == 1
    assert ds.cases[0].expected[0].document_name == "doc-1"
