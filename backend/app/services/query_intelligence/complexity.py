"""Query complexity estimation — deterministic, no LLM/DB. Single source of truth for 'what is query' complexity."""

from __future__ import annotations

from app.services.query_intelligence.schemas import (
    AmbiguityAnalysis,
    QueryCategory,
    QueryClassification,
    QueryComplexity,
    QueryComplexityDetail,
    QueryFeatures,
)

MULTI_HOP_SIGNALS = [" and ", " affect ", " impact ", " based on ", " across ", " then "]
COMPARISON_WORDS = ["compare", "difference", "between", "versus", "vs"]


def estimate_complexity(
    features: QueryFeatures,
    classification: QueryClassification,
    ambiguity: AmbiguityAnalysis,
) -> QueryComplexityDetail:
    """Estimate query complexity. Does NOT execute retrieval."""
    lower = features.normalized_query.lower()
    word_count = features.word_count
    signals: list[str] = []
    level = QueryComplexity.SIMPLE
    score = 0.2

    # Multi-hop detection: conjunction + length + classification
    if classification.primary_class == QueryCategory.multi_hop and classification.confidence >= 0.3:
        level = QueryComplexity.MULTI_HOP
        score = 0.85
        signals.append("classification_multi_hop")
    elif any(kw in lower for kw in MULTI_HOP_SIGNALS) and word_count >= 10:
        level = QueryComplexity.MULTI_HOP
        score = 0.75
        signals.append("multi_hop_signal_and_length")
    elif any(w in lower for w in COMPARISON_WORDS) and word_count >= 8:
        level = QueryComplexity.COMPLEX
        score = 0.65
        signals.append("comparison_signal")
    elif word_count <= 6:
        level = QueryComplexity.SIMPLE
        score = 0.2
        signals.append("short_query_simple")
    elif word_count <= 12:
        # ambiguous short -> simple, otherwise moderate
        if ambiguity.is_ambiguous:
            level = QueryComplexity.SIMPLE
            score = 0.3
            signals.append("ambiguous_short_simple")
        else:
            level = QueryComplexity.MODERATE
            score = 0.45
            signals.append("medium_length_moderate")
    else:
        level = QueryComplexity.COMPLEX
        score = 0.6
        signals.append("long_query_complex")

    # Adjust for multiple questions
    if features.normalized_query.count("?") > 1 or lower.count(" and ") >= 2:
        if level != QueryComplexity.MULTI_HOP:
            level = QueryComplexity.COMPLEX
        score = min(1.0, score + 0.15)
        signals.append("multiple_questions_or_conjunctions")

    requires_multiple = (
        level in (QueryComplexity.MULTI_HOP, QueryComplexity.COMPLEX) or " and " in lower
    )

    return QueryComplexityDetail(
        level=level,
        score=round(score, 3),
        requires_multiple_sources=requires_multiple,
        signals=signals,
    )
