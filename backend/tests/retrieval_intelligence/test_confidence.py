from unittest.mock import MagicMock

from app.services.retrieval_intelligence.service import retrieval_confidence


def _res(score):
    return MagicMock(
        score=score,
        chunk_id="c",
        document_id="d",
        document_name="Doc",
        content="hi",
        provenance=MagicMock(),
    )


def test_high_confidence():
    results = [_res(0.9), _res(0.75), _res(0.6)]
    conf = retrieval_confidence(results, top_k=5)
    assert conf.confidence >= 0.8


def test_low_confidence():
    results = [_res(0.3), _res(0.2)]
    conf = retrieval_confidence(results, top_k=5)
    assert conf.confidence < 0.4


def test_no_results():
    conf = retrieval_confidence([], top_k=5)
    assert conf.confidence == 0.0
    assert conf.reason == "no_results"


def test_medium_confidence():
    results = [_res(0.65), _res(0.6)]
    conf = retrieval_confidence(results, top_k=5)
    assert 0.4 <= conf.confidence <= 0.8


def test_score_gap():
    results = [_res(0.9), _res(0.5)]
    conf = retrieval_confidence(results, top_k=5)
    assert conf.score_gap == 0.4
