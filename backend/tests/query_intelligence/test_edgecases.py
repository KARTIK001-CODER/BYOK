from app.services.query_intelligence.analyzer import QueryAnalyzer


def test_empty_whitespace():
    # Empty should still normalize and handle; analyzer should not crash
    a = QueryAnalyzer.analyze("   ")
    assert a.features.word_count == 0
    assert a.ambiguity.ambiguity_score >= 0.5


def test_single_word():
    a = QueryAnalyzer.analyze("pricing")
    assert a.features.word_count == 1
    assert a.strategy.strategy.value in ["VECTOR", "HYBRID", "KEYWORD", "HYBRID_WIDE"]


def test_very_long():
    long_q = "What is the refund policy? " * 50  # 150 words
    a = QueryAnalyzer.analyze(long_q)
    assert a.features.word_count > 100
    assert a.duration_ms < 5  # still fast


def test_unicode():
    a = QueryAnalyzer.analyze("What is café policy? naïve résumé")
    assert a.features.character_count > 0


def test_code_snippet():
    a = QueryAnalyzer.analyze("```python\npool_size=10\n```")
    assert a.features.contains_backticks is True or a.features.contains_identifier is True


def test_multiple_identifiers():
    a = QueryAnalyzer.analyze("What does cancellation_fee and MAX_UPLOAD_SIZE mean?")
    assert len(a.features.identifier_candidates) >= 1
    assert a.classification.primary_class.value == "keyword"


def test_only_numbers():
    a = QueryAnalyzer.analyze("12345")
    assert a.features.contains_numbers is True
    assert a.features.word_count >= 1


def test_only_punctuation():
    a = QueryAnalyzer.analyze("???")
    assert a.features.punctuation_count >= 1
