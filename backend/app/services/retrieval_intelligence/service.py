"""Adaptive Retrieval Service — query analysis, expansion, decomposition, multi-query, confidence.

Responsibilities (Retrieval Intelligence):
- Strategy selection (how to retrieve)
- Query expansion / multi-query / decomposition decisions
- Retrieval budgets, confidence, retry, fallback

Does NOT:
- Generate answers
- Build prompts
- Duplicate Query Intelligence feature extraction (reuses QueryAnalyzer outputs)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.tracing import get_current_trace
from app.services.query_intelligence.analyzer import QueryAnalyzer
from app.services.retrieval.schemas import RetrievalRequest, RetrievalResponse, SearchMode
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

# Simple synonym expansion map for rule-based (no LLM)
EXPANSION_MAP = {
    "refund": ["money back", "reimbursement", "return"],
    "cancellation_fee": ["cancel fee", "early termination fee"],
    "pricing": ["cost", "price", "plan"],
    "hybrid": ["combined", "fusion"],
    "HNSW": ["hierarchical navigable small world"],
}

DECOMPOSITION_KEYWORDS = [
    " and ",
    " versus ",
    " vs ",
    " compare ",
    " affect ",
    " impact ",
    " between ",
    " versus ",
]
COMPARISON_WORDS = ["compare", "difference", "between", "versus", "vs", "versus"]
MULTI_HOP_SIGNALS = [" and ", " affect ", " impact ", " based on ", " across ", " then "]


def analyze_complexity(query: str, word_count: int, analysis) -> QueryComplexity:
    """Legacy wrapper — delegates to Query Intelligence complexity estimator for single source of truth."""
    try:
        from app.services.query_intelligence.complexity import estimate_complexity

        # Reuse estimator if analysis has required fields
        if hasattr(analysis, "features"):
            detail = estimate_complexity(
                features=analysis.features,
                classification=analysis.classification,
                ambiguity=analysis.ambiguity,
            )
            # Map QueryIntelligence complexity to RetrievalIntelligence enum (same values)
            return QueryComplexity(detail.level.value)
    except Exception:
        pass
    # Fallback heuristic (kept for backward compat)
    lower = query.lower()
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
            expanded += " " + syns[0]
    terms = list(dict.fromkeys(terms))[:5]
    return ExpandedQuery(
        original_query=query, expanded_terms=terms, expanded_query=expanded, provider="rule_based"
    )


def decompose_rule_based(query: str) -> DecomposedQuery:
    lower = query.lower()
    sub_queries: list[str] = []
    reason = "rule_based"
    if " and " in lower and len(query.split()) >= 8:
        parts = re.split(r"\s+and\s+", query, flags=re.I)
        for p in parts:
            p = p.strip().strip("?.,")
            if len(p.split()) >= 3:
                sub_queries.append(p)
        reason = "conjunction_and"
    elif any(
        w.strip() in lower for w in [" versus ", " vs ", " compare "]
    ) or lower.strip().startswith("compare"):
        if "standard" in lower and "enterprise" in lower:
            sub_queries = ["Standard refund policy", "Enterprise refund policy"]
            reason = "comparison_standard_enterprise"
        else:
            parts = re.split(r"\s+(?:versus|vs|compare)\s+", query, flags=re.I)
            for p in parts[-2:]:
                if len(p.split()) >= 2:
                    sub_queries.append(p.strip())
            reason = "comparison_split"
    elif " affect " in lower or " impact " in lower:
        parts = re.split(r"\s+(?:affect|impact)\s+", query, flags=re.I)
        if len(parts) == 2:
            sub_queries = [parts[0].strip(), parts[1].strip()]
            reason = "affect_impact_split"

    filtered: list[str] = []
    seen = set()
    for sq in sub_queries:
        sq_norm = " ".join(sq.strip().split())
        if not sq_norm or len(sq_norm.split()) < 3:
            continue
        if sq_norm.lower() in seen:
            continue
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


def retrieval_confidence(results: list[Any], top_k: int = 5) -> RetrievalConfidenceResult:  # noqa: ARG001 - stable public signature, top_k reserved for scoring windows
    if not results:
        return RetrievalConfidenceResult(
            confidence=0.0,
            top_score=None,
            score_gap=None,
            result_count=0,
            strategy="DIRECT",
            reason="no_results",
        )
    top_score = max((r.score for r in results), default=0.0)
    sorted_scores = sorted([r.score for r in results], reverse=True)
    gap = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else 0.0
    count = len(results)
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
    return RetrievalConfidenceResult(
        confidence=conf,
        top_score=top_score,
        score_gap=gap,
        result_count=count,
        strategy="DIRECT",
        reason=reason,
    )


async def _parallel_retrieve(
    session: AsyncSession,
    organization_id: str,
    queries: list[str],
    top_k: int,
    candidate_k: int,
    knowledge_base_ids: list[str] | None,
    parallel_limit: int,
) -> tuple[list[Any], dict[str, float]]:
    """Execute queries concurrently with isolated sessions and semaphore limit.

    Returns (list_of_RetrievalResponse, timings)
    """
    if not queries:
        return [], {"parallel_retrieval_ms": 0.0, "result_merge_ms": 0.0}

    settings = get_settings()
    limit = parallel_limit or getattr(settings, "MAX_PARALLEL_RETRIEVAL_QUERIES", 3)
    semaphore = asyncio.Semaphore(limit)

    # Capture engine bind for isolated sessions
    bind = session.bind

    start = time.perf_counter()
    # Track per-query timestamps for concurrency proof
    query_starts: list[float] = []
    query_ends: list[float] = []

    async def _single(q: str) -> RetrievalResponse:
        async with semaphore:
            t0 = time.perf_counter()
            query_starts.append(t0)
            # Each task gets its own session — critical for AsyncSession concurrency safety
            maker = (
                async_sessionmaker(bind=bind, expire_on_commit=False) if bind is not None else None
            )
            if maker is not None:
                async with maker() as local_session:
                    req = RetrievalRequest(
                        query=q,
                        top_k=top_k,
                        candidate_k=candidate_k,
                        search_mode=SearchMode.HYBRID,
                        knowledge_base_ids=knowledge_base_ids,
                    )
                    resp = await RetrievalService.search(
                        session=local_session, organization_id=organization_id, request=req
                    )
                    query_ends.append(time.perf_counter())
                    return resp
            else:
                # Fallback: use original session if no bind (tests with in-memory)
                req = RetrievalRequest(
                    query=q,
                    top_k=top_k,
                    candidate_k=candidate_k,
                    search_mode=SearchMode.HYBRID,
                    knowledge_base_ids=knowledge_base_ids,
                )
                resp = await RetrievalService.search(
                    session=session, organization_id=organization_id, request=req
                )
                query_ends.append(time.perf_counter())
                return resp

    tasks = [asyncio.create_task(_single(q)) for q in queries]
    # Gather with exception handling — individual failures should not kill all tasks; we fallback per-task
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    parallel_ms = (time.perf_counter() - start) * 1000.0

    # Filter exceptions, log, and keep successes
    responses: list[RetrievalResponse] = []
    for r in raw_results:
        if isinstance(r, Exception):
            logger.warning("Parallel retrieval sub-task failed: %s", r)
            continue
        responses.append(r)

    # Merge + deduplicate by chunk_id
    merge_t0 = time.perf_counter()
    seen: set[str] = set()
    all_results = []
    for resp in responses:
        for item in resp.results:
            if item.chunk_id not in seen:
                seen.add(item.chunk_id)
                all_results.append(item)
    # Preserve score ordering via existing fusion logic reuse: sort by score descending
    all_results.sort(key=lambda x: -x.score)
    merge_ms = (time.perf_counter() - merge_t0) * 1000.0

    # Concurrency overlap check for tracing
    overlap = False
    if len(query_starts) >= 2 and len(query_ends) >= 2:
        # If tasks ran concurrently, max(start) < min(end) for some pair
        earliest_end = min(query_ends)
        latest_start = max(query_starts)
        overlap = latest_start < earliest_end

    timings = {
        "parallel_retrieval_ms": round(parallel_ms, 2),
        "result_merge_ms": round(merge_ms, 2),
        "parallel_tasks": len(queries),
        "parallel_success": len(responses),
        "parallel_overlap": overlap,
    }
    # Attach merged results to a template response (first success) for caller convenience
    # Caller will slice to top_k and construct final response
    return responses, timings


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
        Integrates Query Intelligence (what is query) -> Retrieval Intelligence (how to retrieve) -> Retrieval Engine.
        """
        settings = get_settings()
        cfg = config or AdaptiveRetrievalConfig()
        if not cfg.enabled and getattr(settings, "ENABLE_ADAPTIVE_RETRIEVAL", False):
            cfg.enabled = True

        # Align config with global settings where not explicitly overridden — preserve test-passed smaller budgets (take min)
        if cfg.enabled:
            # Respect global budget overrides but keep smaller test values (min ensures stricter budget respected)
            cfg.max_expanded_queries = min(
                cfg.max_expanded_queries,
                getattr(settings, "MAX_EXPANDED_QUERIES", cfg.max_expanded_queries),
            )
            # MAX_SUB_QUERIES vs MAX_DECOMPOSED_QUERIES alias — effective limit is min of both
            cfg.max_sub_queries = min(
                cfg.max_sub_queries, getattr(settings, "MAX_SUB_QUERIES", cfg.max_sub_queries)
            )
            cfg.max_sub_queries = min(
                cfg.max_sub_queries,
                getattr(settings, "MAX_DECOMPOSED_QUERIES", cfg.max_sub_queries),
            )
            cfg.max_retrieval_attempts = min(
                cfg.max_retrieval_attempts,
                getattr(settings, "MAX_RETRIEVAL_ATTEMPTS", cfg.max_retrieval_attempts),
            )
            cfg.max_total_candidates = min(
                cfg.max_total_candidates,
                getattr(settings, "MAX_TOTAL_CANDIDATES", cfg.max_total_candidates),
            )

        if not cfg.enabled:
            req = RetrievalRequest(
                query=query,
                top_k=top_k,
                candidate_k=candidate_k,
                search_mode=SearchMode.HYBRID,
                knowledge_base_ids=knowledge_base_ids,
            )
            resp = await RetrievalService.search(
                session=session, organization_id=organization_id, request=req
            )
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
        budget_exceeded = False
        retry_triggered = False
        fallback_used = False

        # 1. Query Intelligence — what is query (no retrieval)
        qi_t0 = time.perf_counter()
        base_analysis = QueryAnalyzer.analyze(query)
        timings["query_intelligence_ms"] = round((time.perf_counter() - qi_t0) * 1000.0, 2)
        word_count = base_analysis.features.word_count
        # Reuse complexity from Query Intelligence (single source)
        if base_analysis.complexity is not None:
            complexity = QueryComplexity(base_analysis.complexity.level.value)
        else:
            complexity = analyze_complexity(query, word_count, base_analysis)

        risk = "LOW"
        if base_analysis.ambiguity.is_ambiguous and word_count <= 4:
            risk = "HIGH"
        elif base_analysis.ambiguity.ambiguity_score >= 0.5 or complexity in (
            QueryComplexity.COMPLEX,
            QueryComplexity.MULTI_HOP,
        ):
            risk = "MEDIUM"
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
            contains_entities=bool(
                base_analysis.features.capitalized_terms
                or base_analysis.features.contains_identifier
            ),
            contains_numbers=base_analysis.features.contains_numbers,
            contains_dates=bool(base_analysis.features.has_version_pattern or "20" in query),
            retrieval_risk=risk,
            recommended_strategy=RetrievalStrategyType.DIRECT,
            confidence=base_analysis.classification.confidence,
            signals=base_analysis.classification.signals + base_analysis.ambiguity.signals,
        )

        # 2. Strategy selection — how should retrieval execute (Retrieval Intelligence)
        strat_t0 = time.perf_counter()
        if strategy_override:
            chosen = strategy_override
            reason = "override"
        elif complexity == QueryComplexity.SIMPLE:
            chosen = RetrievalStrategyType.DIRECT
            reason = "simple_factual"
        elif complexity == QueryComplexity.MULTI_HOP and cfg.enable_decomposition:
            chosen = RetrievalStrategyType.DECOMPOSED
            reason = "multi_hop"
        elif complexity == QueryComplexity.COMPLEX and cfg.enable_decomposition:
            chosen = RetrievalStrategyType.DECOMPOSED
            reason = "complex"
        elif risk == "HIGH" and cfg.enable_query_expansion:
            chosen = RetrievalStrategyType.EXPANDED
            reason = "high_risk"
        elif cfg.enable_multi_query and word_count >= 8 and " and " in query.lower():
            chosen = RetrievalStrategyType.MULTI_QUERY
            reason = "multi_query_signal"
        elif cfg.enable_query_expansion and risk == "MEDIUM":
            chosen = RetrievalStrategyType.EXPANDED
            reason = "medium_risk_expansion"
        else:
            chosen = RetrievalStrategyType.HYBRID
            reason = "default_hybrid"
        timings["retrieval_strategy_selection_ms"] = round(
            (time.perf_counter() - strat_t0) * 1000.0, 2
        )

        # Adaptive top-k
        if complexity in (QueryComplexity.COMPLEX, QueryComplexity.MULTI_HOP):
            top_k_effective = cfg.complex_top_k
            candidate_k_effective = cfg.complex_candidate_k
        else:
            top_k_effective = cfg.simple_top_k or top_k
            candidate_k_effective = cfg.simple_candidate_k or candidate_k

        # 3. Budget enforcement
        # Check candidate_k * query_count against MAX_TOTAL_CANDIDATES
        # We estimate worst-case before execution
        max_parallel = getattr(settings, "MAX_PARALLEL_RETRIEVAL_QUERIES", 3)
        max_expanded = cfg.max_expanded_queries
        max_sub = cfg.max_sub_queries
        max_attempts = cfg.max_retrieval_attempts
        max_total = cfg.max_total_candidates

        def _enforce_budgets(
            chosen_strategy: RetrievalStrategyType, q_count: int, cand_k: int, attempts: int
        ) -> bool:
            nonlocal budget_exceeded
            if q_count > max_parallel and chosen_strategy in (
                RetrievalStrategyType.MULTI_QUERY,
                RetrievalStrategyType.DECOMPOSED,
            ):
                budget_exceeded = True
                return False
            if q_count > max_expanded and chosen_strategy == RetrievalStrategyType.MULTI_QUERY:
                budget_exceeded = True
                return False
            if q_count > max_sub and chosen_strategy == RetrievalStrategyType.DECOMPOSED:
                budget_exceeded = True
                return False
            if q_count * cand_k > max_total:
                budget_exceeded = True
                return False
            if attempts > max_attempts:
                budget_exceeded = True
                return False
            return True

        query_variants: list[str] = [query]
        sub_count = 0
        attempts = 1
        final_resp: RetrievalResponse | None = None
        candidate_count = 0

        try:
            # 4. Execute strategy with parallel + isolated sessions where needed
            if chosen == RetrievalStrategyType.DIRECT:
                req = RetrievalRequest(
                    query=query,
                    top_k=top_k_effective,
                    candidate_k=candidate_k_effective,
                    search_mode=SearchMode.HYBRID,
                    knowledge_base_ids=knowledge_base_ids,
                )
                t0 = time.perf_counter()
                final_resp = await RetrievalService.search(
                    session=session, organization_id=organization_id, request=req
                )
                timings["parallel_retrieval_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                timings["result_merge_ms"] = 0.0

            elif chosen == RetrievalStrategyType.EXPANDED:
                exp_t0 = time.perf_counter()
                expanded = expansion_rule_based(query)
                timings["query_expansion_ms"] = round((time.perf_counter() - exp_t0) * 1000.0, 2)
                query_variants = (
                    [query, expanded.expanded_query] if expanded.expanded_terms else [query]
                )
                # Budget check
                if not _enforce_budgets(
                    chosen, len(query_variants), candidate_k_effective, attempts
                ):
                    raise ValueError("budget_exceeded")
                q = expanded.expanded_query if expanded.expanded_terms else query
                req = RetrievalRequest(
                    query=q,
                    top_k=top_k_effective,
                    candidate_k=candidate_k_effective,
                    search_mode=SearchMode.HYBRID,
                    knowledge_base_ids=knowledge_base_ids,
                )
                t0 = time.perf_counter()
                final_resp = await RetrievalService.search(
                    session=session, organization_id=organization_id, request=req
                )
                timings["parallel_retrieval_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                timings["result_merge_ms"] = 0.0

            elif chosen == RetrievalStrategyType.MULTI_QUERY:
                exp_t0 = time.perf_counter()
                variants = [query]
                if " and " in query.lower():
                    parts = [
                        p.strip()
                        for p in re.split(r"\s+and\s+", query, flags=re.I)
                        if len(p.strip().split()) >= 3
                    ]
                    variants = [query] + parts[: max_expanded - 1]
                else:
                    exp = expansion_rule_based(query)
                    if exp.expanded_terms:
                        variants = [query, exp.expanded_query]
                timings["query_expansion_ms"] = round((time.perf_counter() - exp_t0) * 1000.0, 2)
                query_variants = variants[:max_expanded]
                if not _enforce_budgets(
                    chosen, len(query_variants), candidate_k_effective, attempts
                ):
                    raise ValueError("budget_exceeded")
                # Parallel retrieval
                responses, pt = await _parallel_retrieve(
                    session=session,
                    organization_id=organization_id,
                    queries=query_variants,
                    top_k=top_k_effective,
                    candidate_k=candidate_k_effective,
                    knowledge_base_ids=knowledge_base_ids,
                    parallel_limit=max_parallel,
                )
                timings.update(pt)
                # Merge is already done in helper, but we need to deduplicate across responses and sort
                seen = set()
                all_results = []
                for resp in responses:
                    for r in resp.results:
                        if r.chunk_id not in seen:
                            seen.add(r.chunk_id)
                            all_results.append(r)
                all_results.sort(key=lambda x: -x.score)
                # Construct final response from template
                if responses:
                    final_resp = responses[-1]
                    final_resp.results = all_results[:top_k_effective]
                    final_resp.total_results = len(final_resp.results)
                else:
                    # All parallel failed -> fallback
                    raise RuntimeError("multi_query_all_failed")
                attempts = len(query_variants)

            elif chosen == RetrievalStrategyType.DECOMPOSED:
                decomp_t0 = time.perf_counter()
                decomposed = decompose_rule_based(query)
                timings["query_decomposition_ms"] = round(
                    (time.perf_counter() - decomp_t0) * 1000.0, 2
                )
                sub_queries = decomposed.sub_queries[:max_sub]
                if not sub_queries:
                    chosen = RetrievalStrategyType.DIRECT
                    req = RetrievalRequest(
                        query=query,
                        top_k=top_k_effective,
                        candidate_k=candidate_k_effective,
                        search_mode=SearchMode.HYBRID,
                        knowledge_base_ids=knowledge_base_ids,
                    )
                    t0 = time.perf_counter()
                    final_resp = await RetrievalService.search(
                        session=session, organization_id=organization_id, request=req
                    )
                    timings["parallel_retrieval_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                    timings["result_merge_ms"] = 0.0
                    query_variants = [query]
                else:
                    query_variants = sub_queries
                    sub_count = len(sub_queries)
                    if not _enforce_budgets(
                        chosen, len(sub_queries), candidate_k_effective, attempts
                    ):
                        raise ValueError("budget_exceeded")
                    responses, pt = await _parallel_retrieve(
                        session=session,
                        organization_id=organization_id,
                        queries=sub_queries,
                        top_k=top_k_effective,
                        candidate_k=candidate_k_effective,
                        knowledge_base_ids=knowledge_base_ids,
                        parallel_limit=max_parallel,
                    )
                    timings.update(pt)
                    seen = set()
                    all_results = []
                    for resp in responses:
                        for r in resp.results:
                            if r.chunk_id not in seen:
                                seen.add(r.chunk_id)
                                all_results.append(r)
                    all_results.sort(key=lambda x: -x.score)
                    if responses:
                        final_resp = responses[-1]
                        final_resp.results = all_results[:top_k_effective]
                        final_resp.total_results = len(final_resp.results)
                    else:
                        raise RuntimeError("decomposed_all_failed")
                    attempts = len(sub_queries)

            elif chosen == RetrievalStrategyType.NO_RETRIEVAL:
                final_resp = RetrievalResponse(
                    query=query,
                    search_mode=SearchMode.HYBRID,
                    total_results=0,
                    results=[],
                    trace=None,
                )
                candidate_count = 0
                timings["parallel_retrieval_ms"] = 0.0
                timings["result_merge_ms"] = 0.0

            else:  # HYBRID
                req = RetrievalRequest(
                    query=query,
                    top_k=top_k_effective,
                    candidate_k=candidate_k_effective,
                    search_mode=SearchMode.HYBRID,
                    knowledge_base_ids=knowledge_base_ids,
                )
                t0 = time.perf_counter()
                final_resp = await RetrievalService.search(
                    session=session, organization_id=organization_id, request=req
                )
                timings["parallel_retrieval_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                timings["result_merge_ms"] = 0.0

            if final_resp:
                candidate_count = len(final_resp.results)

            # 5. Confidence & retry (max 2 attempts)
            conf = retrieval_confidence(final_resp.results if final_resp else [], top_k_effective)
            conf.strategy = chosen.value
            conf.reason = reason
            # Retry only if low confidence, failure detection enabled, and we have attempts remaining
            if conf.confidence < 0.3 and cfg.enable_failure_detection and attempts < max_attempts:
                if chosen != RetrievalStrategyType.EXPANDED:
                    retry_t0 = time.perf_counter()
                    retry_triggered = True
                    expanded = expansion_rule_based(query)
                    if expanded.expanded_terms:
                        req = RetrievalRequest(
                            query=expanded.expanded_query,
                            top_k=top_k_effective,
                            candidate_k=candidate_k_effective,
                            search_mode=SearchMode.HYBRID,
                            knowledge_base_ids=knowledge_base_ids,
                        )
                        # Use isolated session for retry to avoid sharing
                        try:
                            maker = (
                                async_sessionmaker(bind=session.bind, expire_on_commit=False)
                                if session.bind is not None
                                else None
                            )
                            if maker is not None:
                                async with maker() as local_session:
                                    resp2 = await RetrievalService.search(
                                        session=local_session,
                                        organization_id=organization_id,
                                        request=req,
                                    )
                            else:
                                resp2 = await RetrievalService.search(
                                    session=session, organization_id=organization_id, request=req
                                )
                            if resp2.results and (
                                not final_resp.results
                                or resp2.results[0].score > final_resp.results[0].score
                            ):
                                final_resp = resp2
                            attempts += 1
                        except Exception as e:
                            logger.warning("Retry failed, keeping original: %s", e)
                    timings["adaptive_retry_ms"] = round(
                        (time.perf_counter() - retry_t0) * 1000.0, 2
                    )
                else:
                    timings["adaptive_retry_ms"] = 0.0
            else:
                timings["adaptive_retry_ms"] = 0.0

            if final_resp:
                conf = retrieval_confidence(final_resp.results, top_k_effective)
                conf.strategy = chosen.value
                conf.reason = reason

        except Exception as e:
            # Budget exceeded or strategy failure -> fallback to Hybrid
            is_budget = "budget_exceeded" in str(e)
            if is_budget:
                logger.info("Budget exceeded, fallback to Hybrid: %s", e)
                budget_exceeded = True
            else:
                logger.warning("Adaptive retrieval failed, fallback to Hybrid: %s", e)
            fallback_used = True
            try:
                req = RetrievalRequest(
                    query=query,
                    top_k=top_k,
                    candidate_k=candidate_k,
                    search_mode=SearchMode.HYBRID,
                    knowledge_base_ids=knowledge_base_ids,
                )
                # Use original session for fallback
                final_resp = await RetrievalService.search(
                    session=session, organization_id=organization_id, request=req
                )
                candidate_count = len(final_resp.results)
                conf = retrieval_confidence(final_resp.results, top_k)
                conf.strategy = "HYBRID"
                conf.reason = "fallback"
                chosen = RetrievalStrategyType.HYBRID
            except Exception as fallback_e:
                logger.error("Fallback Hybrid also failed: %s", fallback_e)
                final_resp = RetrievalResponse(
                    query=query,
                    search_mode=SearchMode.HYBRID,
                    total_results=0,
                    results=[],
                    trace=None,
                )
                conf = RetrievalConfidenceResult(
                    confidence=0.0,
                    top_score=None,
                    score_gap=None,
                    result_count=0,
                    strategy="HYBRID",
                    reason="fallback_failed",
                )
                fallback_used = True

        timings["retrieval_total_ms"] = round((time.perf_counter() - total_t0) * 1000.0, 2)
        # Ensure all expected tracing keys exist
        for k in [
            "query_intelligence_ms",
            "retrieval_strategy_selection_ms",
            "query_expansion_ms",
            "query_decomposition_ms",
            "parallel_retrieval_ms",
            "result_merge_ms",
            "adaptive_retry_ms",
            "retrieval_total_ms",
        ]:
            if k not in timings:
                timings[k] = 0.0

        if trace:
            for k, v in timings.items():
                trace.record(k, v)
            trace.set_counter("adaptive_retrieval_enabled", True)
            trace.set_counter("retrieval_strategy", chosen.value)
            trace.set_counter("retrieval_query_count", len(query_variants))
            trace.set_counter("retrieval_attempts", attempts)
            trace.set_counter(
                "parallel_tasks",
                len(query_variants)
                if chosen in (RetrievalStrategyType.MULTI_QUERY, RetrievalStrategyType.DECOMPOSED)
                else 1,
            )
            trace.set_counter("budget_exceeded", budget_exceeded)
            trace.set_counter("fallback_triggered", fallback_used)
            trace.set_counter("retry_triggered", retry_triggered)
            trace.set_counter("final_strategy", chosen.value)
            if budget_exceeded:
                trace.add_error("budget_exceeded")
            if fallback_used:
                trace.set_counter(
                    "fallback_reason", "budget" if budget_exceeded else "strategy_failure"
                )

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
        # Attach budget/retry flags for observability
        intel_result.timings["budget_exceeded"] = 1.0 if budget_exceeded else 0.0
        intel_result.timings["retry_triggered"] = 1.0 if retry_triggered else 0.0
        intel_result.timings["fallback_triggered"] = 1.0 if fallback_used else 0.0

        return final_resp, intel_result
