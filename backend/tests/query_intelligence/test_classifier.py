from app.services.query_intelligence.analyzer import QueryAnalyzer


def test_identifier_classification():
    a = QueryAnalyzer.analyze("What is cancellation_fee?")
    assert a.classification.primary_class.value == "keyword"
    assert a.classification.confidence >= 0.6
    assert "identifier_detected" in a.classification.signals


def test_keyword_confidence_high():
    a = QueryAnalyzer.analyze("ERR_504")
    assert a.classification.primary_class.value == "keyword"
    assert a.classification.confidence >= 0.8


def test_semantic_low_identifier():
    a = QueryAnalyzer.analyze("How do I get my money back after buying a plan?")
    # No identifier, medium length, question word -> semantic or factual
    assert a.classification.primary_class.value in ["semantic", "factual", "unknown"]


def test_unknown_low_confidence():
    a = QueryAnalyzer.analyze("asdfghjkl")
    # nonsense should be low confidence unknown
    assert a.classification.confidence < 0.6 or a.classification.primary_class.value == "unknown"


def test_multi_hop():
    a = QueryAnalyzer.analyze("If I buy annual and cancel after 20 days with 30% usage, what refund and fee apply?")
    # Should be multi_hop or at least not keyword
    assert a.classification.primary_class.value in ["multi_hop", "semantic", "factual", "unknown"]
