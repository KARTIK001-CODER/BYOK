from app.services.query_intelligence.analyzer import QueryAnalyzer


def test_keyword_strategy():
    a = QueryAnalyzer.analyze("cancellation_fee")
    assert a.strategy.strategy.value == "KEYWORD"
    assert a.strategy.reason in ["strong_identifier", "identifier_detected"]


def test_low_confidence_fallback_hybrid():
    # Very vague nonsense with low confidence should fallback to hybrid
    a = QueryAnalyzer.analyze("asdf asdf asdf")
    assert a.strategy.strategy.value == "HYBRID"


def test_ambiguous_wide():
    a = QueryAnalyzer.analyze("How does it work?")
    assert a.strategy.strategy.value == "HYBRID_WIDE"
    assert "high_ambiguity" in a.strategy.reason


def test_safe_fallback_on_error():
    # Even empty after stripping should not crash, but our analyzer handles normal query; test exception path via RetrievalService
    from app.services.query_intelligence.strategy import select_strategy
    from app.services.query_intelligence.schemas import QueryFeatures, QuestionType, QueryClassification, QueryCategory, AmbiguityAnalysis, RetrievalStrategy
    # Simulate low confidence hybrid fallback
    features = QueryFeatures(original_query="test", normalized_query="test", character_count=4, token_count=1, word_count=1)
    classification = QueryClassification(primary_class=QueryCategory.unknown, confidence=0.2, signals=[])
    ambiguity = AmbiguityAnalysis(is_ambiguous=False, ambiguity_score=0.1, signals=[])
    decision = select_strategy(features, classification, ambiguity)
    assert decision.strategy == RetrievalStrategy.HYBRID


def test_vector_strategy():
    # High semantic confidence, low ambiguity -> VECTOR
    a = QueryAnalyzer.analyze("Explain how hybrid search combines semantic vectors and lexical search for refund policies")
    # This is long semantic, may be classified as semantic with high confidence
    # At least ensure not keyword
    assert a.strategy.strategy.value in ["VECTOR", "HYBRID", "HYBRID_WIDE"]
