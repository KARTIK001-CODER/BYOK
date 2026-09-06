"""Reranking service — candidate prep, dedup, rerank, sort, top-k, fallback, tracing, timeout."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import get_settings
from app.core.tracing import get_current_trace
from app.services.reranking.factory import RerankerFactory
from app.services.reranking.schemas import RerankerTrace

logger = logging.getLogger("app.services.reranking.service")


class RerankingService:
    """Dedicated reranking service — separate from retrieval."""

    @staticmethod
    async def rerank(
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int | None = None,
        candidate_k: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[list[dict[str, Any]], RerankerTrace]:
        """
        Rerank candidates. Returns (reranked_top_k, trace).

        Safe: on any failure returns original candidates truncated to top_k.
        Bounded: timeout via asyncio.wait_for.
        No DB queries.
        """
        settings = get_settings()
        enabled = getattr(settings, "ENABLE_RERANKING", False)
        # If not enabled, fallback quickly — but service can still be called explicitly
        top_k = top_k if top_k is not None else getattr(settings, "RERANKER_TOP_K", 5)
        candidate_k = candidate_k if candidate_k is not None else getattr(settings, "RERANKER_CANDIDATE_K", 30)
        timeout = timeout_seconds if timeout_seconds is not None else getattr(settings, "RERANKER_TIMEOUT_SECONDS", 2.0)

        trace = get_current_trace()
        t0_total = time.perf_counter()

        # Candidate preparation
        prep_t0 = time.perf_counter()
        # Deduplicate by chunk_id (identical chunk)
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for cand in candidates:
            cid = cand.get("chunk_id") or cand.get("id") or str(id(cand))
            if cid in seen:
                continue
            seen.add(cid)
            deduped.append(cand)
        # Truncate to candidate_k before reranking (bounded)
        to_rerank = deduped[:candidate_k]
        prep_ms = (time.perf_counter() - prep_t0) * 1000.0

        if not to_rerank:
            trace_obj = RerankerTrace(
                enabled=enabled,
                candidate_count=0,
                result_count=0,
                candidate_preparation_ms=round(prep_ms, 2),
                total_ms=round((time.perf_counter() - t0_total) * 1000.0, 2),
                fallback=True,
                fallback_reason="empty_candidates",
            )
            if trace:
                trace.record("reranker_candidate_preparation_ms", prep_ms)
                trace.record("reranker_total_ms", trace_obj.total_ms)
            return [], trace_obj

        # If not enabled, return original top_k without reranking (but trace)
        if not enabled:
            # Still return original order truncated
            result = to_rerank[:top_k]
            # annotate rerank fields for compatibility
            for idx, item in enumerate(result):
                item.setdefault("rerank_score", item.get("retrieval_score") or 0.0)
                item.setdefault("original_rank", idx + 1)
                item.setdefault("rerank_rank", idx + 1)
            trace_obj = RerankerTrace(
                enabled=False,
                candidate_count=len(to_rerank),
                result_count=len(result),
                candidate_preparation_ms=round(prep_ms, 2),
                total_ms=round((time.perf_counter() - t0_total) * 1000.0, 2),
                fallback=True,
                fallback_reason="disabled",
            )
            if trace:
                trace.record("reranker_candidate_preparation_ms", prep_ms)
                trace.record("reranker_total_ms", trace_obj.total_ms)
                trace.set_counter("reranking_enabled", False)
            return result, trace_obj

        # Provider resolution
        res_t0 = time.perf_counter()
        try:
            reranker = RerankerFactory.create(provider=provider)
            provider_name = reranker.name
            model_name = reranker.model_name
        except Exception as e:
            logger.warning("RerankerFactory failed: %s", e)
            # fallback
            result = to_rerank[:top_k]
            trace_obj = RerankerTrace(
                enabled=True,
                candidate_count=len(to_rerank),
                result_count=len(result),
                candidate_preparation_ms=round(prep_ms, 2),
                total_ms=round((time.perf_counter() - t0_total) * 1000.0, 2),
                fallback=True,
                fallback_reason=f"factory_error: {e}",
            )
            if trace:
                trace.record("reranker_resolution_ms", (time.perf_counter() - res_t0) * 1000.0)
            return result, trace_obj
        res_ms = (time.perf_counter() - res_t0) * 1000.0

        # Check warm vs cold
        from app.services.reranking.providers.local import LocalReranker

        is_warm = LocalReranker.is_warm() if provider_name == "local" else True
        init_ms = 0.0
        if not is_warm:
            # Load already happened in factory, but measure
            load_ms = LocalReranker.load_ms()
            init_ms = load_ms or 0.0

        # Reranking with timeout
        infer_t0 = time.perf_counter()
        fallback = False
        fallback_reason: str | None = None
        timeout_flag = False
        reranked: list[dict[str, Any]] | None = None
        try:
            reranked = await asyncio.wait_for(
                reranker.rerank(query, to_rerank, top_k=top_k),
                timeout=float(timeout),
            )
        except asyncio.TimeoutError:
            logger.warning("Reranking timeout after %.2fs for query %.40s", timeout, query)
            fallback = True
            fallback_reason = f"timeout_{timeout}s"
            timeout_flag = True
            reranked = None
        except Exception as e:
            logger.warning("Reranking inference failed: %s", e)
            fallback = True
            fallback_reason = f"inference_error: {e}"

        if fallback or reranked is None:
            # Fallback to original order
            result = to_rerank[:top_k]
            for idx, item in enumerate(result):
                item.setdefault("rerank_score", item.get("retrieval_score") or 0.0)
                item.setdefault("original_rank", idx + 1)
                item.setdefault("rerank_rank", idx + 1)
            infer_ms = (time.perf_counter() - infer_t0) * 1000.0
            # sorting not needed for fallback
            sort_ms = 0.0
        else:
            infer_ms = (time.perf_counter() - infer_t0) * 1000.0
            # Sorting already done by provider; measure trivial sort
            sort_t0 = time.perf_counter()
            # Provider already sorted, but ensure top_k
            result = reranked[:top_k]
            sort_ms = (time.perf_counter() - sort_t0) * 1000.0

        total_ms = (time.perf_counter() - t0_total) * 1000.0

        trace_obj = RerankerTrace(
            enabled=True,
            provider=provider_name,
            model=model_name,
            candidate_count=len(to_rerank),
            result_count=len(result),
            candidate_preparation_ms=round(prep_ms, 2),
            initialization_ms=round(init_ms, 2),
            inference_ms=round(infer_ms, 2),
            sorting_ms=round(sort_ms, 2),
            total_ms=round(total_ms, 2),
            fallback=fallback,
            fallback_reason=fallback_reason,
            is_warm=is_warm,
            timeout=timeout_flag,
        )

        if trace:
            trace.record("reranker_resolution_ms", res_ms)
            trace.record("reranker_initialization_ms", init_ms)
            trace.record("reranker_candidate_preparation_ms", prep_ms)
            trace.record("reranker_inference_ms", infer_ms)
            trace.record("reranker_sorting_ms", sort_ms)
            trace.record("reranker_total_ms", total_ms)
            trace.set_counter("reranking_enabled", True)
            trace.set_counter("reranking_candidate_count", len(to_rerank))
            trace.set_counter("reranking_result_count", len(result))
            trace.set_counter("reranking_fallback", fallback)
            trace.set_counter("reranking_model_warm", is_warm)

        return result, trace_obj
