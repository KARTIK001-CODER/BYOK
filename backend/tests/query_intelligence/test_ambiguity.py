from app.services.query_intelligence.analyzer import QueryAnalyzer


def test_high_ambiguity():
    a = QueryAnalyzer.analyze("How does it work?")
    assert a.ambiguity.is_ambiguous is True
    assert a.ambiguity.ambiguity_score >= 0.5
    assert a.classification.primary_class.value == "ambiguous" or a.strategy.strategy.value == "HYBRID_WIDE"
    assert a.strategy.strategy.value == "HYBRID_WIDE"


def test_low_ambiguity():
    a = QueryAnalyzer.analyze("What is the maximum upload size for enterprise users?")
    assert a.ambiguity.is_ambiguous is False
    assert a.ambiguity.ambiguity_score < 0.5


def test_very_short():
    a = QueryAnalyzer.analyze("pricing")
    # single word may be ambiguous but not necessarily very high
    assert a.features.word_count == 1


def test_pronoun_reference():
    a = QueryAnalyzer.analyze("What about that?")
    assert "context_reference" in a.ambiguity.signals
    assert a.ambiguity.ambiguity_score >= 0.4


def test_ambiguity_score_range():
    for q in ["How does it work?", "Tell me more", "What about pricing?", "Can I do that?", "What happens then?"]:
        a = QueryAnalyzer.analyze(q)
        assert 0.0 <= a.ambiguity.ambiguity_score <= 1.0
