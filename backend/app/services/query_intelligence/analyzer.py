"""QueryAnalyzer — orchestrates normalization → features → classification → ambiguity → strategy. No DB, no LLM, <2ms."""

from __future__ import annotations

import time
import logging
from typing import Any

from app.services.query_intelligence.ambiguity import analyze_ambiguity
from app.services.query_intelligence.classifier import classify_query
from app.services.query_intelligence.features import extract_features
from app.services.query_intelligence.schemas import QueryAnalysis, QueryClassification, QueryFeatures
from app.services.query_intelligence.strategy import select_strategy

logger = logging.getLogger("app.services.query_intelligence.analyzer")


class QueryAnalyzer:
    """Deterministic, cheap, inspectable query intelligence pipeline."""

    VERSION = "1.0"

    @classmethod
    def analyze(
        cls,
        query: str,
        normalized_query: str | None = None,
        conversation_context: list[str] | None = None,
    ) -> QueryAnalysis:
        """
        Analyze query without DB or LLM calls. Supports optional conversation_context for future.

        Args:
            query: Original raw query
            normalized_query: Optional pre-normalized (if provided, avoids duplicate normalization)
            conversation_context: Optional list of recent messages for context-aware ambiguity (Phase 2.1 keeps interface but does not use retrieval over it)
        """
        t0 = time.perf_counter()

        # Normalization — preserve original, produce normalized
        original = query
        if normalized_query is not None:
            normalized = normalized_query
        else:
            # Simple normalization: collapse whitespace, strip, preserve case for identifier detection
            normalized = " ".join(original.strip().split())
            # Remove excessive punctuation duplication? Keep as is for identifier
            # Do not lowercse here — features handle case

        # Stage timings (for tracing)
        feat_t0 = time.perf_counter()
        features = extract_features(original, normalized)
        feat_ms = (time.perf_counter() - feat_t0) * 1000.0

        # If conversation context provided, we could adjust ambiguity (e.g., "that" with context is less ambiguous)
        # For Phase 2.1, we keep interface but only log
        if conversation_context:
            # Future: if last assistant message contains entities, reduce ambiguity
            # For now, just record
            logger.debug("QueryAnalyzer received context with %d messages (not yet used for retrieval)", len(conversation_context))

        amb_t0 = time.perf_counter()
        ambiguity = analyze_ambiguity(features)
        amb_ms = (time.perf_counter() - amb_t0) * 1000.0

        cls_t0 = time.perf_counter()
        classification = classify_query(features=features, ambiguity=ambiguity)
        cls_ms = (time.perf_counter() - cls_t0) * 1000.0

        strat_t0 = time.perf_counter()
        strategy = select_strategy(features=features, classification=classification, ambiguity=ambiguity)
        strat_ms = (time.perf_counter() - strat_t0) * 1000.0

        total_ms = (time.perf_counter() - t0) * 1000.0

        # Debug logging for trace integration
        logger.debug(
            "QueryAnalysis query=%.40s class=%s conf=%.2f amb=%.2f strategy=%s (feat=%.2f cls=%.2f amb=%.2f strat=%.2f total=%.2f)",
            original,
            classification.primary_class.value,
            classification.confidence,
            ambiguity.ambiguity_score,
            strategy.strategy.value,
            feat_ms,
            cls_ms,
            amb_ms,
            strat_ms,
            total_ms,
        )

        return QueryAnalysis(
            features=features,
            classification=classification,
            ambiguity=ambiguity,
            strategy=strategy,
            duration_ms=round(total_ms, 3),
            version=cls.VERSION,
        )

    @classmethod
    def analyze_with_timings(cls, query: str, normalized_query: str | None = None) -> tuple[QueryAnalysis, dict[str, float]]:
        """Helper for tracing — returns analysis + per-stage timings."""
        t0 = time.perf_counter()
        original = query
        normalized = normalized_query if normalized_query is not None else " ".join(original.strip().split())
        feat_t0 = time.perf_counter()
        features = extract_features(original, normalized)
        feat_ms = (time.perf_counter() - feat_t0) * 1000.0
        amb_t0 = time.perf_counter()
        from app.services.query_intelligence.ambiguity import analyze_ambiguity

        ambiguity = analyze_ambiguity(features)
        amb_ms = (time.perf_counter() - amb_t0) * 1000.0
        cls_t0 = time.perf_counter()
        classification = classify_query(features=features, ambiguity=ambiguity)
        cls_ms = (time.perf_counter() - cls_t0) * 1000.0
        strat_t0 = time.perf_counter()
        strategy = select_strategy(features=features, classification=classification, ambiguity=ambiguity)
        strat_ms = (time.perf_counter() - strat_t0) * 1000.0
        total_ms = (time.perf_counter() - t0) * 1000.0
        analysis = QueryAnalysis(
            features=features,
            classification=classification,
            ambiguity=ambiguity,
            strategy=strategy,
            duration_ms=round(total_ms, 3),
            version=cls.VERSION,
        )
        timings = {
            "feature_extraction_ms": round(feat_ms, 3),
            "ambiguity_analysis_ms": round(amb_ms, 3),
            "classification_ms": round(cls_ms, 3),
            "strategy_selection_ms": round(strat_ms, 3),
            "query_analysis_ms": round(total_ms, 3),
        }
        return analysis, timings
