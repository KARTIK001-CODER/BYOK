"""Strategy selection — deterministic, explainable, safe fallback to HYBRID."""

from __future__ import annotations

from app.core.config import get_settings
from app.services.query_intelligence.schemas import (
    AmbiguityAnalysis,
    QueryClassification,
    QueryFeatures,
    RetrievalStrategy,
    RetrievalStrategyDecision,
)


def select_strategy(
    features: QueryFeatures,
    classification: QueryClassification,
    ambiguity: AmbiguityAnalysis,
    confidence_threshold: float | None = None,
    ambiguity_threshold: float | None = None,
) -> RetrievalStrategyDecision:
    settings = get_settings()
    conf_thresh = confidence_threshold if confidence_threshold is not None else getattr(settings, "QUERY_CLASSIFICATION_CONFIDENCE_THRESHOLD", 0.6)
    amb_thresh = ambiguity_threshold if ambiguity_threshold is not None else getattr(settings, "AMBIGUITY_THRESHOLD", 0.5)

    # Defaults
    strategy = RetrievalStrategy.HYBRID
    reason = "fallback_hybrid"
    confidence = classification.confidence
    signals = list(classification.signals) + list(ambiguity.signals)

    # Rule 1: Strong identifier → KEYWORD (requires high confidence)
    if classification.primary_class.value == "keyword" and classification.confidence >= conf_thresh:
        # Additional guard: need actual identifier or exact phrase
        if features.contains_identifier and (features.has_snake_case or features.has_upper_case or features.contains_exact_phrase or features.word_count == 1):
            strategy = RetrievalStrategy.KEYWORD
            reason = "strong_identifier"
            confidence = classification.confidence
            signals = ["identifier_detected", "classification_keyword"] + ambiguity.signals
        elif features.contains_identifier:
            # Ambiguous keyword? Still maybe keyword but lower confidence
            strategy = RetrievalStrategy.KEYWORD
            reason = "identifier_detected"
            signals = ["identifier_detected"]

    # Rule 2: High ambiguity → HYBRID_WIDE (more candidates)
    elif ambiguity.is_ambiguous and ambiguity.ambiguity_score >= amb_thresh:
        # Only if confidence in ambiguous is reasonable or ambiguity high
        if classification.primary_class.value == "ambiguous" or ambiguity.ambiguity_score >= 0.6:
            strategy = RetrievalStrategy.HYBRID_WIDE
            reason = "high_ambiguity"
            confidence = ambiguity.ambiguity_score
            signals = ambiguity.signals + ["wide_candidate_k"]
        else:
            strategy = RetrievalStrategy.HYBRID_WIDE
            reason = "high_ambiguity_fallback"
            signals = ambiguity.signals

    # Rule 3: High semantic confidence, low ambiguity → VECTOR
    elif classification.primary_class.value == "semantic" and classification.confidence >= conf_thresh and not ambiguity.is_ambiguous:
        strategy = RetrievalStrategy.VECTOR
        reason = "high_semantic_low_ambiguity"
        signals = ["semantic_confident", "low_ambiguity"]

    # Rule 4: Factual with low ambiguity → HYBRID (default is already hybrid, but keep)
    elif classification.primary_class.value == "factual" and not ambiguity.is_ambiguous:
        strategy = RetrievalStrategy.HYBRID
        reason = "factual_default_hybrid"
        signals = ["factual"]

    # Rule 5: Multi-hop → HYBRID_WIDE (needs broader recall)
    elif classification.primary_class.value == "multi_hop" and classification.confidence >= 0.5:
        strategy = RetrievalStrategy.HYBRID_WIDE
        reason = "multi_hop_wide"
        signals = ["multi_hop"] + ambiguity.signals

    # Rule 6: Low confidence → safe fallback HYBRID
    if classification.confidence < conf_thresh and strategy in (RetrievalStrategy.VECTOR, RetrievalStrategy.KEYWORD):
        # Demote aggressive routing if not confident
        strategy = RetrievalStrategy.HYBRID
        reason = "low_confidence_fallback_hybrid"
        signals = ["low_confidence"] + signals

    # Clamp confidence
    confidence = max(0.0, min(1.0, float(confidence)))

    return RetrievalStrategyDecision(
        strategy=strategy,
        reason=reason,
        confidence=round(confidence, 3),
        signals=list(dict.fromkeys(signals))[:8],
        classification=classification.primary_class,
        ambiguity_score=ambiguity.ambiguity_score,
    )
