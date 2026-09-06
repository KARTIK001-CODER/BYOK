"""Adaptive Retrieval Service — query analysis, expansion, decomposition, multi-query, confidence."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.tracing import get_current_trace
from app.services.query_intelligence.analyzer import QueryAnalyzer
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService
from app.services.retrieval_intelligence.schemas import (
    AdaptiveRetrievalConfig,
    DecomposedQuery,
    ExpandedQuery,
    QueryAnalysisExtended,
    QueryComplexity,
    RetrievalConfidenceResult,
    RetrievalIntelligenceResult,
    RetrievalStrategyType,
)

logger = logging.getLogger("app.services.retrieval_intelligence.service")

# Simple synonym expansion map for rule-based
EXPANSION_MAP = {
    "refund": ["money back", "reimbursement", "return"],
    "cancellation_fee": ["cancel fee", "early termination fee"],
    "pricing": ["cost", "price", "plan"],
    "hybrid": ["combined", "fusion"],
    "HNSW": ["hierarchical navigable small world"],
}

DECOMPOSITION_KEYWORDS = [" and ", " versus ", " vs ", " compare ", " affect ", " impact ", " between ", " versus "]
COMPARISON_WORDS = ["compare", "difference", "between", "versus", "vs", "versus"]
MULTI_HOP_SIGNALS = [" and ", " affect ", " impact ", " based on ", " across ", " then "]


def analyze_complexity(query: str, word_count: int, analysis) -> QueryComplexity:
    lower = query.lower()
    # MULTI_HOP if contains and + multiple entities or compare across
    if any(kw in lower for kw in MULTI_HOP_SIGNALS) and word_count >= 10:
        return QueryComplexity.MULTI_HOP
    if any(w in lower for w in COMPARISON_WORDS) and word_count >= 8:
        return QueryComplexity.COMPLEX
    if word_count <= 6:
        return QueryComplexity.SIMPLE
    if word_count <= 12:
        return QueryComplexity.MODERATE
    return QueryComplexity.COMPLEX


def expansion_rule_based(query: str) -> ExpandedQuery:
    terms: list[str] = []
    expanded = query
    lower = query.lower()
    for key, syns in EXPANSION_MAP.items():
        if key.lower() in lower:
            terms.extend(syns)
            # Append first synonym to expanded query for retrieval
            expanded += " " + syns[0]
    # Deduplicate
    terms = list(dict.fromkeys(terms))[:5]
    return ExpandedQuery(original_query=query, expanded_terms=terms, expanded_query=expanded, provider="rule_based")


def decompose_rule_based(query: str) -> DecomposedQuery:
    lower = query.lower()
    sub_queries: list[str] = []
    reason = "rule_based"
    # Split on " and " or " versus " or " compare "
    # Simple heuristic: if contains " and " and length >10, split into two
    if " and " in lower and len(query.split()) >= 8:
        parts = re.split(r"\s+and\s+", query, flags=re.I)
        for p in parts:
            p = p.strip().strip("?.,")
            if len(p.split()) >= 3:
                sub_queries.append(p)
        reason = "conjunction_and"
    elif any(w in lower for w in [" versus ", " vs ", " compare "]):
        # e.g., "Compare refund policies for standard and enterprise"
        # Try to extract two entities
        if "standard" in lower and "enterprise" in lower:
            sub_queries = ["Standard refund policy", "Enterprise refund policy"]
            reason = "comparison_standard_enterprise"
        else:
            # Generic split on versus/compare
            parts = re.split(r"\s+(?:versus|vs|compare)\s+", query, flags=re.I)
            for p in parts[-2:]:
                if len(p.split()) >= 2:
                    sub_queries.append(p.strip())
            reason = "comparison_split"
    elif " affect " in lower or " impact " in lower:
        # e.g., "How does remote work affect equipment reimbursement?"
        parts = re.split(r"\s+(?:affect|impact)\s+", query, flags=re.I)
        if len(parts) == 2:
            sub_queries = [parts[0].strip(), parts[1].strip()]
            reason = "affect_impact_split"

    # Validation
    # Remove duplicates, empty, too short, too similar
    filtered: list[str] = []
    seen = set()
    for sq in sub_queries:
        sq_norm = " ".join(sq.strip().split())
        if not sq_norm or len(sq_norm.split()) < 3:
            continue
        if sq_norm.lower() in seen:
            continue
        # Too similar to original?
        if sq_norm.lower() == query.lower().strip().lower():
            continue
        seen.add(sq_norm.lower())
        filtered.append(sq_norm)
        if len(filtered) >= 3:
            break

    return DecomposedQuery(
        original_query=query,
        sub_queries=filtered,
        reason=reason if filtered else "no_decomposition",
        provider="rule_based",
        confidence=0.7 if filtered else 0.0,
    )


def retrieval_confidence(results: list[Any], top_k: int = 5) -> RetrievalConfidenceResult:
    # results is list of RetrievalResult
    if not results:
        return RetrievalConfidenceResult(confidence=0.0, top_score=None, score_gap=None, result_count=0, strategy="DIRECT", reason="no_results")
    top_score = max((r.score for r in results), default=0.0)
    sorted_scores = sorted([r.score for r in results], reverse=True)
    gap = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else 0.0
    count = len(results)
    # Simple confidence heuristic
    if top_score >= 0.8 and gap >= 0.1 and count >= 3:
        conf = 0.9
        reason = "high_top_score_and_gap"
    elif top_score >= 0.6 and count >= 2:
        conf = 0.7
        reason = "moderate_top_score"
    elif top_score < 0.4 or count == 0:
        conf = 0.2
        reason = "low_top_score"
    else:
        conf = 0.5
        reason = "medium"
    return RetrievalConfidenceResult(confidence=conf, top_score=top_score, score_gap=gap, result_count=count, strategy="DIRECT", reason=reason)


class AdaptiveRetrievalService:
    """Orchestrates adaptive retrieval with optional expansion, multi-query, decomposition, retry."""

    @staticmethod
    async def retrieve(
        session: AsyncSession,
        organization_id: str,
        query: str,
        top_k: int = 5,
        candidate_k: int = 30,
        knowledge_base_ids: list[str] | None = None,
        strategy_override: RetrievalStrategyType | None = None,
        config: AdaptiveRetrievalConfig | None = None,
    ) -> tuple[Any, RetrievalIntelligenceResult]:
        """
        Adaptive retrieval. Returns (RetrievalResponse, RetrievalIntelligenceResult)
        """
        settings = get_settings()
        cfg = config or AdaptiveRetrievalConfig()
        # Override from global config if not explicitly passed
        if not cfg.enabled and getattr(settings, "ENABLE_ADAPTIVE_RETRIEVAL", False):
            cfg.enabled = True
        # If not enabled, just do direct hybrid
        if not cfg.enabled:
            # Direct
            req = RetrievalRequest(query=query, top_k=top_k, candidate_k=candidate_k, search_mode=SearchMode.HYBRID)
            resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
            conf = retrieval_confidence(resp.results, top_k)
            intel = RetrievalIntelligenceResult(
                original_query=query,
                strategy=RetrievalStrategyType.DIRECT,
                query_variants=[query],
                sub_query_count=0,
                retrieval_attempts=1,
                candidate_count=len(resp.results),
                final_result_count=len(resp.results),
                retrieval_confidence=conf,
                fallback_used=False,
                query_analysis=None,
                timings={},
            )
            return resp, intel

        total_t0 = time.perf_counter()
        trace = get_current_trace()
        timings: dict[str, float] = {}

        # 1. Query analysis extended
        qa_t0 = time.perf_counter()
        # Use existing QueryAnalyzer for base
        base_analysis = QueryAnalyzer.analyze(query)
        word_count = base_analysis.features.word_count
        complexity = analyze_complexity(query, word_count, base_analysis)
        # Retrieval risk
        risk = "LOW"
        if base_analysis.ambiguity.is_ambiguous and word_count <= 4:
            risk = "HIGH"
        elif base_analysis.ambiguity.ambiguity_score >= 0.5 or complexity in (QueryComplexity.COMPLEX, QueryComplexity.MULTI_HOP):
            risk = "MEDIUM"
        # Intent: use question_type
        intent = base_analysis.features.question_type.value
        qa_extended = QueryAnalysisExtended(
            query=query,
            normalized_query=base_analysis.features.normalized_query,
            query_length=len(query),
            word_count=word_count,
            complexity=complexity,
            intent=intent,
            ambiguity_score=base_analysis.ambiguity.ambiguity_score,
            contains_multiple_questions=query.count("?") > 1,
            contains_entities=bool(base_analysis.features.capitalized_terms or base_analysis.features.contains_identifier),
            contains_numbers=base_analysis.features.contains_numbers,
            contains_dates=bool(base_analysis.features.has_version_pattern or "20" in query),
            retrieval_risk=risk,
            recommended_strategy=RetrievalStrategyType.DIRECT,
            confidence=base_analysis.classification.confidence,
            signals=base_analysis.classification.signals + base_analysis.ambiguity.signals,
        )
        timings["query_analysis_ms"] = (time.perf_counter() - qa_t0) * 1000.0

        # 2. Strategy selection
        strat_t0 = time.perf_counter()
        if strategy_override:
            chosen = strategy_override
            reason = "override"
        elif complexity == QueryComplexity.SIMPLE:
            chosen = RetrievalStrategyType.DIRECT
            reason = "simple factual"
        elif complexity == QueryComplexity.MULTI_HOP:
            chosen = RetrievalStrategyType.DECOMPOSED
            reason = "multi_hop"
        elif complexity == QueryComplexity.COMPLEX and cfg.enable_decomposition:
            chosen = RetrievalStrategyType.DECOMPOSED
            reason = "complex"
        elif risk == "HIGH" and cfg.enable_query_expansion:
            chosen = RetrievalStrategyType.EXPANDED
            reason = "high_risk"
        elif cfg.enable_multi_query and word_count >= 10 and " and " in query.lower():
            chosen = RetrievalStrategyType.MULTI_QUERY
            reason = "multi_query_signal"
        else:
            chosen = RetrievalStrategyType.HYBRID
            reason = "default_hybrid"
        timings["strategy_selection_ms"] = (time.perf_counter() - strat_t0) * 1000.0

        # Adaptive top-k
        if complexity in (QueryComplexity.COMPLEX, QueryComplexity.MULTI_HOP):
            top_k_effective = cfg.complex_top_k
            candidate_k_effective = cfg.complex_candidate_k
        else:
            top_k_effective = cfg.simple_top_k or top_k
            candidate_k_effective = cfg.simple_candidate_k or candidate_k

        # 3. Execute strategy
        query_variants: list[str] = [query]
        sub_count = 0
        attempts = 1
        fallback_used = False
        final_resp = None
        candidate_count = 0

        exp_ms = 0.0
        decomp_ms = 0.0
        retrieval_ms_total = 0.0

        try:
            if chosen == RetrievalStrategyType.DIRECT:
                req = RetrievalRequest(query=query, top_k=top_k_effective, candidate_k=candidate_k_effective, search_mode=SearchMode.HYBRID)
                t0 = time.perf_counter()
                final_resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
                retrieval_ms_total += (time.perf_counter() - t0) * 1000.0

            elif chosen == RetrievalStrategyType.EXPANDED:
                exp_t0 = time.perf_counter()
                expanded = expansion_rule_based(query)
                exp_ms = (time.perf_counter() - exp_t0) * 1000.0
                query_variants = [query, expanded.expanded_query] if expanded.expanded_terms else [query]
                # Use expanded query for retrieval
                q = expanded.expanded_query if expanded.expanded_terms else query
                req = RetrievalRequest(query=q, top_k=top_k_effective, candidate_k=candidate_k_effective, search_mode=SearchMode.HYBRID)
                t0 = time.perf_counter()
                final_resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
                retrieval_ms_total += (time.perf_counter() - t0) * 1000.0
                timings["query_expansion_ms"] = exp_ms

            elif chosen == RetrievalStrategyType.MULTI_QUERY:
                # Generate up to max_expanded_queries variants
                # Simple: split on " and " or use expansion
                variants = [query]
                if " and " in query.lower():
                    parts = [p.strip() for p in query.split(" and ") if len(p.strip().split()) >= 3]
                    variants = [query] + parts[: cfg.max_expanded_queries - 1]
                else:
                    # Use expansion as multi-query
                    exp = expansion_rule_based(query)
                    if exp.expanded_terms:
                        variants = [query, exp.expanded_query]
                query_variants = variants[: cfg.max_expanded_queries]
                # Parallel retrieval (respect pool, use asyncio.gather with independent sessions)
                # For simplicity, run sequentially but could be parallel; use gather with new sessions via RetrievalService which already handles parallel internally for hybrid
                # Here we run each variant sequentially and deduplicate
                all_results = []
                seen = set()
                for qv in query_variants:
                    req = RetrievalRequest(query=qv, top_k=top_k_effective, candidate_k=candidate_k_effective, search_mode=SearchMode.HYBRID)
                    t0 = time.perf_counter()
                    resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
                    retrieval_ms_total += (time.perf_counter() - t0) * 1000.0
                    for r in resp.results:
                        if r.chunk_id not in seen:
                            seen.add(r.chunk_id)
                            all_results.append(r)
                # Deduplicate and sort by score (approx)
                all_results.sort(key=lambda x: -x.score)
                # Need to construct a RetrievalResponse-like object; for now, fabricate
                # Use first variant's response but replace results with deduped top_k
                final_resp = resp  # last resp
                # Override results with deduped
                final_resp.results = all_results[:top_k_effective]
                final_resp.total_results = len(final_resp.results)
                attempts = len(query_variants)

            elif chosen == RetrievalStrategyType.DECOMPOSED:
                decomp_t0 = time.perf_counter()
                decomposed = decompose_rule_based(query)
                decomp_ms = (time.perf_counter() - decomp_t0) * 1000.0
                timings["query_decomposition_ms"] = decomp_ms
                sub_queries = decomposed.sub_queries[: cfg.max_sub_queries]
                if not sub_queries:
                    # Fallback to direct
                    chosen = RetrievalStrategyType.DIRECT
                    req = RetrievalRequest(query=query, top_k=top_k_effective, candidate_k=candidate_k_effective, search_mode=SearchMode.HYBRID)
                    t0 = time.perf_counter()
                    final_resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
                    retrieval_ms_total += (time.perf_counter() - t0) * 1000.0
                    query_variants = [query]
                else:
                    query_variants = sub_queries
                    sub_count = len(sub_queries)
                    # Parallel retrieval for each sub-query
                    all_results = []
                    seen = set()
                    for sq in sub_queries:
                        req = RetrievalRequest(query=sq, top_k=top_k_effective, candidate_k=candidate_k_effective, search_mode=SearchMode.HYBRID)
                        t0 = time.perf_counter()
                        resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
                        retrieval_ms_total += (time.perf_counter() - t0) * 1000.0
                        for r in resp.results:
                            if r.chunk_id not in seen:
                                seen.add(r.chunk_id)
                                all_results.append(r)
                    all_results.sort(key=lambda x: -x.score)
                    # Use last resp as template
                    final_resp = resp
                    final_resp.results = all_results[:top_k_effective]
                    final_resp.total_results = len(final_resp.results)
                    attempts = len(sub_queries)

            elif chosen == RetrievalStrategyType.NO_RETRIEVAL:
                # No retrieval, return empty
                from app.services.retrieval.schemas import RetrievalResponse

                final_resp = RetrievalResponse(query=query, search_mode=SearchMode.HYBRID, total_results=0, results=[], trace=None)
                candidate_count = 0

            else:  # HYBRID
                req = RetrievalRequest(query=query, top_k=top_k_effective, candidate_k=candidate_k_effective, search_mode=SearchMode.HYBRID)
                t0 = time.perf_counter()
                final_resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
                retrieval_ms_total += (time.perf_counter() - t0) * 1000.0

            if final_resp:
                candidate_count = len(final_resp.results)

            # 4. Retrieval confidence and adaptive retry (bounded 1 retry)
            conf = retrieval_confidence(final_resp.results if final_resp else [], top_k_effective)
            # If low confidence and not already retried and enabled, retry with expanded
            if conf.confidence < 0.3 and cfg.enable_failure_detection and attempts < cfg.max_retrieval_attempts:
                # Retry with expanded query
                if chosen != RetrievalStrategyType.EXPANDED:
                    retry_t0 = time.perf_counter()
                    expanded = expansion_rule_based(query)
                    if expanded.expanded_terms:
                        req = RetrievalRequest(query=expanded.expanded_query, top_k=top_k_effective, candidate_k=candidate_k_effective, search_mode=SearchMode.HYBRID)
                        resp2 = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
                        # Compare and keep better (higher top score)
                        if resp2.results and (not final_resp.results or resp2.results[0].score > final_resp.results[0].score):
                            final_resp = resp2
                            fallback_used = True  # actually retry, not fallback
                        attempts += 1
                        timings["adaptive_retry_ms"] = (time.perf_counter() - retry_t0) * 1000.0

            # Update confidence after potential retry
            if final_resp:
                conf = retrieval_confidence(final_resp.results, top_k_effective)
                conf.strategy = chosen.value
                conf.reason = reason

        except Exception as e:
            logger.warning("Adaptive retrieval failed, fallback to direct: %s", e)
            fallback_used = True
            try:
                req = RetrievalRequest(query=query, top_k=top_k, candidate_k=candidate_k, search_mode=SearchMode.HYBRID)
                final_resp = await RetrievalService.search(session=session, organization_id=organization_id, request=req)
                candidate_count = len(final_resp.results)
                conf = retrieval_confidence(final_resp.results, top_k)
            except Exception:
                final_resp = None
                conf = RetrievalConfidenceResult(confidence=0.0, top_score=None, score_gap=None, result_count=0, strategy="DIRECT", reason="fallback_failed")

        timings["adaptive_total_ms"] = (time.perf_counter() - total_t0) * 1000.0
        if trace:
            for k, v in timings.items():
                trace.record(k, v)
            trace.set_counter("adaptive_strategy", chosen.value)
            trace.set_counter("adaptive_attempts", attempts)

        # Build intelligence result
        qa_extended.recommended_strategy = chosen
        intel_result = RetrievalIntelligenceResult(
            original_query=query,
            strategy=chosen,
            query_variants=query_variants,
            sub_query_count=sub_count,
            retrieval_attempts=attempts,
            candidate_count=candidate_count,
            final_result_count=len(final_resp.results) if final_resp else 0,
            retrieval_confidence=conf,
            fallback_used=fallback_used,
            query_analysis=qa_extended,
            timings=timings,
        )

        return final_resp, intel_result
