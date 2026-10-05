"""Request-level latency tracing infrastructure for Phase 1.5 deep tracing."""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("app.tracing")

# ── Context variables (re-exported from logging to keep single source of truth) ─
from app.core.logging import (  # noqa: E402  (circular-safe: logging has no dep on tracing)
    request_id_ctx_var,
    set_request_id,
    set_trace_id,
    trace_id_ctx_var,
)

# ── Trace collector ───────────────────────────────────────────────────────


@dataclass
class RequestTrace:
    """Collects per-request stage timings; serialised as JSON at the end."""

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    _start: float = field(default_factory=time.perf_counter)
    stages: dict[str, float] = field(default_factory=dict)
    timestamps: dict[str, float] = field(default_factory=dict)
    counters: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    db_queries: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    outcome: str = "SUCCESS"
    error_category: str | None = None
    _summary_emitted: bool = False

    def mark(self, name: str, data: Any = None) -> None:
        """Record absolute timestamp (ms since trace start) and add to timeline."""
        ms = (time.perf_counter() - self._start) * 1000.0
        self.timestamps[name] = ms
        entry = {"event": name, "timestamp_ms": round(ms, 2)}
        if data is not None:
            entry["data"] = data
        self.timeline.append(entry)

    def record_event(self, name: str, data: Any = None) -> None:
        """Alias for mark() for explicit timeline event recording."""
        self.mark(name, data)

    def record(self, stage: str, duration_ms: float) -> None:
        self.stages[stage] = round(float(duration_ms), 2)

    def set_counter(self, key: str, value: Any) -> None:
        self.counters[key] = value

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def record_session_created(self, count: int = 1) -> None:
        """Record the creation of database session(s)."""
        self.counters["db_sessions_created"] = self.counters.get("db_sessions_created", 0) + count

    def record_db_query(self, category: str, duration_ms: float) -> None:
        """Record database query execution safely without sensitive parameters."""
        d_ms = round(float(duration_ms), 2)
        self.db_queries.append({"category": category, "duration_ms": d_ms})
        self.counters["db_queries"] = self.counters.get("db_queries", 0) + 1
        self.counters["db_total_time_ms"] = round(
            self.counters.get("db_total_time_ms", 0.0) + d_ms, 2
        )
        self.counters["sql_statement_execution_ms"] = self.counters["db_total_time_ms"]
        self.stages["sql_statement_execution_ms"] = self.counters["sql_statement_execution_ms"]
        current_slowest = self.counters.get("slowest_query_ms", 0.0)
        if d_ms > current_slowest:
            self.counters["slowest_query_ms"] = d_ms
            self.counters["slowest_query_category"] = category

    def record_db_connection_acquisition(self, duration_ms: float) -> None:
        """Record database connection pool checkout / acquisition overhead in ms."""
        d_ms = round(float(duration_ms), 2)
        self.counters["db_pool_checkouts"] = self.counters.get("db_pool_checkouts", 0) + 1
        self.counters["db_connection_acquisition_ms"] = round(
            self.counters.get("db_connection_acquisition_ms", 0.0) + d_ms, 2
        )
        self.stages["db_connection_acquisition_ms"] = self.counters["db_connection_acquisition_ms"]

    def record_db_commit(self, duration_ms: float) -> None:
        """Record database transaction flush and commit overhead in ms."""
        d_ms = round(float(duration_ms), 2)
        self.counters["db_commits"] = self.counters.get("db_commits", 0) + 1
        self.counters["db_commit_ms"] = round(self.counters.get("db_commit_ms", 0.0) + d_ms, 2)
        self.stages["db_commit_ms"] = self.counters["db_commit_ms"]
        self.stages["database_commit_ms"] = self.counters["db_commit_ms"]

    @contextmanager
    def span(self, stage: str):
        """Context-manager that measures elapsed ms and records automatically."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.record(stage, (time.perf_counter() - t0) * 1000.0)

    def calculate_parallel_metrics(self) -> dict[str, Any]:
        """Calculate parallel execution overlap and efficiency for hybrid retrieval."""
        v_time = self.stages.get("vector_search_ms", self.stages.get("vector_total_ms", 0.0))
        k_time = self.stages.get("keyword_search_ms", self.stages.get("keyword_total_ms", 0.0))

        v_start = self.timestamps.get(
            "vector_search_started", self.timestamps.get("vector_start_offset_ms")
        )
        v_end = self.timestamps.get(
            "vector_search_completed", self.timestamps.get("vector_end_offset_ms")
        )
        k_start = self.timestamps.get(
            "keyword_search_started", self.timestamps.get("keyword_start_offset_ms")
        )
        k_end = self.timestamps.get(
            "keyword_search_completed", self.timestamps.get("keyword_end_offset_ms")
        )

        has_both = v_time > 0 and k_time > 0
        sum_time = round(v_time + k_time, 2)

        if (
            has_both
            and v_start is not None
            and v_end is not None
            and k_start is not None
            and k_end is not None
        ):
            earliest_start = min(v_start, k_start)
            latest_end = max(v_end, k_end)
            wall_time = round(max(0.01, latest_end - earliest_start), 2)
            overlap_start = max(v_start, k_start)
            overlap_end = min(v_end, k_end)
            overlap_ms = round(max(0.0, overlap_end - overlap_start), 2)
        elif has_both:
            # Wall time estimate if timestamps not set: approx max of both
            wall_time = round(max(v_time, k_time), 2)
            overlap_ms = round(min(v_time, k_time), 2)
        else:
            wall_time = sum_time
            overlap_ms = 0.0

        efficiency = round(sum_time / max(wall_time, 0.01), 2) if wall_time > 0 else 1.0

        return {
            "parallel_task_count": 2 if has_both else (1 if (v_time > 0 or k_time > 0) else 0),
            "parallel_start_ms": round(min(v_start or 0.0, k_start or 0.0), 2)
            if (v_start or k_start)
            else None,
            "parallel_end_ms": round(max(v_end or 0.0, k_end or 0.0), 2)
            if (v_end or k_end)
            else None,
            "parallel_overlap_ms": overlap_ms,
            "parallel_wall_time_ms": wall_time,
            "parallel_sum_task_time_ms": sum_time,
            "parallel_efficiency": efficiency,
        }

    def calculate_critical_path(self) -> dict[str, Any]:
        """
        Calculate true sequential critical path duration.
        Parallel tasks (vector vs keyword) take max() instead of being summed.
        """
        auth_ms = self.stages.get(
            "authentication_total_ms", self.stages.get("authentication_ms", 0.0)
        )
        authz_ms = self.stages.get(
            "authorization_total_ms", self.stages.get("authorization_ms", 0.0)
        )
        qi_ms = self.stages.get(
            "query_intelligence_total_ms", self.stages.get("query_intelligence_ms", 0.0)
        )
        embed_ms = self.stages.get(
            "embedding_total_ms", self.stages.get("retrieval_embedding_ms", 0.0)
        )

        # Parallel retrieval contribution: wall time or max(vector, keyword)
        parallel_data = self.calculate_parallel_metrics()
        retrieval_branch_ms = parallel_data["parallel_wall_time_ms"]
        fusion_ms = self.stages.get("fusion_total_ms", self.stages.get("fusion_ms", 0.0))
        rerank_ms = self.stages.get("reranking_total_ms", self.stages.get("reranker_total_ms", 0.0))
        context_ms = self.stages.get("context_selection_ms", 0.0)
        prompt_ms = self.stages.get("prompt_construction_ms", 0.0)

        # LLM TTFT & Generation
        ttft_ms = self.stages.get("time_to_first_token_ms", 0.0)
        token_gen_ms = self.stages.get(
            "token_streaming_ms", self.stages.get("token_generation_ms", 0.0)
        )
        if token_gen_ms == 0.0:
            token_gen_ms = max(0.0, self.stages.get("generation_completion_ms", 0.0) - ttft_ms)

        persist_ms = self.stages.get("persistence_total_ms", 0.0)

        steps = [
            ("authentication", auth_ms),
            ("authorization", authz_ms),
            ("query_intelligence", qi_ms),
            ("embedding", embed_ms),
            ("parallel_retrieval", retrieval_branch_ms),
            ("fusion", fusion_ms),
            ("reranking", rerank_ms),
            ("context_assembly", context_ms),
            ("prompt_construction", prompt_ms),
            ("llm_ttft", ttft_ms),
            ("token_generation", token_gen_ms),
            ("persistence", persist_ms),
        ]

        critical_path_ms = round(sum(ms for _, ms in steps), 2)
        total_request_ms = self.stages.get(
            "request_total_ms",
            self.stages.get("http_total_ms", (time.perf_counter() - self._start) * 1000.0),
        )

        return {
            "critical_path_ms": critical_path_ms,
            "total_request_ms": round(total_request_ms, 2),
            "steps": [{"step": s, "ms": round(m, 2)} for s, m in steps if m > 0],
        }

    def to_dict(self) -> dict[str, Any]:
        total = (time.perf_counter() - self._start) * 1000.0
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "total_ms": round(total, 2),
            "stages": dict(self.stages),
            "timestamps": dict(self.timestamps),
            "timeline": list(self.timeline),
            "counters": dict(self.counters),
            "errors": list(self.errors),
        }

    def to_export_dict(self) -> dict[str, Any]:
        """Produces structured JSON output complying with BYOK Phase 2.6 specification."""
        total = self.stages.get(
            "request_total_ms",
            self.stages.get("http_total_ms", (time.perf_counter() - self._start) * 1000.0),
        )

        # Sanitize counters: remove sensitive data
        sanitized_counters = {
            k: v
            for k, v in self.counters.items()
            if not any(sub in k.lower() for sub in ("key", "token", "password", "secret"))
        }

        ttft = self.stages.get("time_to_first_token_ms", 0.0)
        gen_ms = self.stages.get(
            "token_streaming_ms", self.stages.get("generation_completion_ms", 0.0)
        )
        llm_total = self.stages.get(
            "llm_total_ms", self.stages.get("llm_request_ms", (ttft + gen_ms))
        )

        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "request": {
                "total_ms": round(total, 2),
                "middleware_ms": self.stages.get("middleware_ms", 0.0),
            },
            "stages": {
                "authentication": {
                    "jwt_validation_ms": self.stages.get("jwt_validation_ms", 0.0),
                    "user_lookup_ms": self.stages.get("user_lookup_ms", 0.0),
                    "total_ms": self.stages.get(
                        "authentication_total_ms", self.stages.get("authentication_ms", 0.0)
                    ),
                },
                "authorization": {
                    "organization_resolution_ms": self.stages.get(
                        "organization_resolution_ms", 0.0
                    ),
                    "knowledge_base_resolution_ms": self.stages.get(
                        "knowledge_base_resolution_ms", 0.0
                    ),
                    "authorization_check_ms": self.stages.get(
                        "authorization_check_ms", self.stages.get("authorization_ms", 0.0)
                    ),
                    "total_ms": self.stages.get(
                        "authorization_total_ms", self.stages.get("org_verify_total_ms", 0.0)
                    ),
                },
                "query_intelligence": {
                    "feature_extraction_ms": self.stages.get("feature_extraction_ms", 0.0),
                    "ambiguity_detection_ms": self.stages.get("ambiguity_detection_ms", 0.0),
                    "query_classification_ms": self.stages.get("query_classification_ms", 0.0),
                    "complexity_estimation_ms": self.stages.get("complexity_estimation_ms", 0.0),
                    "total_ms": self.stages.get(
                        "query_intelligence_total_ms", self.stages.get("query_intelligence_ms", 0.0)
                    ),
                },
                "retrieval_intelligence": {
                    "strategy_selection_ms": self.stages.get(
                        "retrieval_strategy_selection_ms", 0.0
                    ),
                    "query_expansion_ms": self.stages.get("query_expansion_ms", 0.0),
                    "query_decomposition_ms": self.stages.get("query_decomposition_ms", 0.0),
                    "retry_ms": self.stages.get("adaptive_retry_ms", 0.0),
                    "total_ms": self.stages.get("retrieval_intelligence_total_ms", 0.0),
                },
                "embedding": {
                    "initialization_ms": self.stages.get("embedding_model_initialization_ms", 0.0),
                    "inference_ms": self.stages.get("embedding_inference_ms", 0.0),
                    "total_ms": self.stages.get(
                        "embedding_total_ms", self.stages.get("retrieval_embedding_ms", 0.0)
                    ),
                },
                "retrieval": {
                    "vector_ms": self.stages.get(
                        "vector_search_ms", self.stages.get("retrieval_vector_ms", 0.0)
                    ),
                    "keyword_ms": self.stages.get(
                        "keyword_search_ms", self.stages.get("retrieval_keyword_ms", 0.0)
                    ),
                    "fusion_ms": self.stages.get(
                        "fusion_total_ms", self.stages.get("fusion_ms", 0.0)
                    ),
                    "parallel": self.calculate_parallel_metrics(),
                    "total_ms": self.stages.get(
                        "retrieval_total_ms", self.stages.get("retrieval_overall_ms", 0.0)
                    ),
                },
                "reranking": {
                    "executed": self.counters.get("reranking_enabled", False),
                    "candidate_preparation_ms": self.stages.get(
                        "reranker_candidate_preparation_ms", 0.0
                    ),
                    "inference_ms": self.stages.get("reranker_inference_ms", 0.0),
                    "total_ms": self.stages.get(
                        "reranking_total_ms", self.stages.get("reranker_total_ms", 0.0)
                    ),
                },
                "rag": {
                    "context_selection_ms": self.stages.get("context_selection_ms", 0.0),
                    "prompt_construction_ms": self.stages.get("prompt_construction_ms", 0.0),
                    "citation_construction_ms": self.stages.get("citation_construction_ms", 0.0),
                },
                "llm": {
                    "provider_resolution_ms": self.stages.get("provider_resolution_ms", 0.0),
                    "ttft_ms": round(ttft, 2),
                    "generation_ms": round(gen_ms, 2),
                    "total_ms": round(llm_total, 2),
                    "tokens_generated": self.counters.get(
                        "generated_tokens_est", self.counters.get("completion_tokens", 0)
                    ),
                    "tokens_per_second": round(self.counters.get("tokens_per_sec", 0.0), 2),
                },
                "sse": {
                    "first_token_gap_ms": self.stages.get(
                        "sse_first_token_gap_ms",
                        self.stages.get("llm_to_client_first_token_overhead_ms", 0.0),
                    ),
                    "first_token_sent_ms": self.stages.get("first_token_sent_ms", 0.0),
                    "last_token_sent_ms": self.stages.get("last_token_sent_ms", 0.0),
                    "done_event_sent_ms": self.stages.get("done_event_sent_ms", 0.0),
                    "sse_done_gap_ms": self.stages.get("sse_done_gap_ms", 0.0),
                },
                "database": {
                    "sql_statement_execution_ms": self.stages.get(
                        "sql_statement_execution_ms",
                        self.counters.get(
                            "sql_statement_execution_ms", self.counters.get("db_total_time_ms", 0.0)
                        ),
                    ),
                    "db_connection_acquisition_ms": self.stages.get(
                        "db_connection_acquisition_ms",
                        self.counters.get("db_connection_acquisition_ms", 0.0),
                    ),
                    "db_commit_ms": self.stages.get(
                        "db_commit_ms",
                        self.counters.get("db_commit_ms", 0.0),
                    ),
                    "total_ms": self.stages.get("database_latency_ms", 0.0),
                    "queries_count": int(self.counters.get("db_queries", 0)),
                },
                "persistence": {
                    "conversation_lookup_ms": self.stages.get("conversation_lookup_ms", 0.0),
                    "user_message_save_ms": self.stages.get(
                        "user_message_save_ms", self.stages.get("user_message_persist_ms", 0.0)
                    ),
                    "assistant_message_save_ms": self.stages.get(
                        "assistant_message_save_ms",
                        self.stages.get("assistant_message_creation_ms", 0.0),
                    ),
                    "database_commit_ms": self.stages.get(
                        "database_commit_ms", self.stages.get("persistence_commit_ms", 0.0)
                    ),
                    "db_commit_ms": self.stages.get(
                        "db_commit_ms",
                        self.stages.get(
                            "database_commit_ms", self.stages.get("persistence_commit_ms", 0.0)
                        ),
                    ),
                    "total_ms": self.stages.get("persistence_total_ms", 0.0),
                },
            },
            "critical_path": self.calculate_critical_path(),
            "counters": sanitized_counters,
            "timeline": self.timeline,
            "errors": list(self.errors),
        }

    def log_summary(self) -> None:
        """Emit structured trace summary via logger at INFO level."""
        d = self.to_dict()
        # Build compact ASCII waterfall for human-readable
        stages_sorted = sorted(d["stages"].items(), key=lambda x: -x[1])
        total = d["total_ms"] or 1.0
        lines = [f"TRACE {d['trace_id']} req={d['request_id']} total={d['total_ms']:.1f}ms"]
        for name, ms in stages_sorted:
            pct = (ms / total) * 100
            lines.append(f"  {name:40s} {ms:8.2f} ms  ({pct:4.1f}%)")
        if d["timestamps"]:
            lines.append("  --- timestamps (ms since request_start) ---")
            for k, v in sorted(d["timestamps"].items(), key=lambda x: x[1]):
                lines.append(f"    {k:40s} {v:8.2f} ms")
        if d["counters"]:
            lines.append(f"  counters: {d['counters']}")
        logger.info("\n".join(lines))

    def to_performance_summary(self) -> dict[str, Any]:
        """
        Produce a production-safe structured performance summary dictionary.
        Complies with Phase 3 RAG observability specification.
        """
        total = self.stages.get(
            "request_total_ms",
            self.stages.get("http_total_ms", (time.perf_counter() - self._start) * 1000.0),
        )

        parallel_metrics = self.calculate_parallel_metrics()

        db_stage_ms = self.stages.get("database_latency_ms", 0.0)
        db_time = round(
            db_stage_ms
            if db_stage_ms > 0
            else (
                self.counters.get("db_total_time_ms", 0.0)
                + self.stages.get("persistence_commit_ms", 0.0)
                + self.stages.get("pre_llm_commit_ms", 0.0)
            ),
            2,
        )

        query_prep_ms = self.stages.get(
            "query_preprocessing_ms",
            self.stages.get("query_normalization_ms", 0.0),
        )
        query_intel_ms = self.stages.get(
            "query_intelligence_total_ms",
            self.stages.get("query_intelligence_ms", 0.0),
        )
        embed_ms = self.stages.get(
            "embedding_total_ms",
            self.stages.get(
                "retrieval_embedding_ms",
                self.stages.get("query_embedding_ms", 0.0),
            ),
        )
        cache_lat_ms = self.stages.get("embedding_cache_latency_ms", 0.0)
        cache_hit = self.counters.get("embedding_cache_hit", False)

        retrieval_ms = self.stages.get(
            "retrieval_total_ms",
            self.stages.get("retrieval_overall_ms", 0.0),
        )
        rerank_ms = self.stages.get(
            "reranking_total_ms",
            self.stages.get("reranker_total_ms", 0.0),
        )
        context_ms = self.stages.get(
            "context_selection_ms",
            self.stages.get("context_assembly_ms", 0.0),
        )
        prompt_ms = self.stages.get("prompt_construction_ms", 0.0)

        ttft_ms = round(self.stages.get("time_to_first_token_ms", 0.0), 2)
        gen_ms = round(
            self.stages.get(
                "token_streaming_ms",
                self.stages.get("generation_completion_ms", 0.0),
            ),
            2,
        )
        llm_total_ms = round(
            self.stages.get("llm_total_ms", self.stages.get("llm_request_ms", (ttft_ms + gen_ms))),
            2,
        )

        v_cands = int(self.counters.get("vector_candidates", 0))
        k_cands = int(self.counters.get("keyword_candidates", 0))
        retrieved_cands = int(self.counters.get("retrieved_candidates", v_cands + k_cands))
        retained_cands = int(
            self.counters.get("retained_candidates", self.counters.get("retrieved_chunks", 0))
        )
        context_chunks = int(
            self.counters.get("selected_chunks", self.counters.get("context_chunks_used", 0))
        )
        queries_count = int(self.counters.get("retrieval_query_count", 1))
        llm_calls = int(
            self.counters.get(
                "llm_call_count",
                1 if (llm_total_ms > 0 or self.stages.get("llm_request_ms", 0.0) > 0) else 0,
            )
        )

        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "outcome": self.outcome,
            "error_category": self.error_category,
            "total_latency_ms": round(total, 2),
            "latencies": {
                "query_preprocessing_ms": round(query_prep_ms, 2),
                "query_intelligence_ms": round(query_intel_ms, 2),
                "query_embedding_ms": round(embed_ms, 2),
                "embedding_cache_latency_ms": round(cache_lat_ms, 2),
                "database_latency_ms": db_time,
                "sql_statement_execution_ms": round(
                    self.stages.get(
                        "sql_statement_execution_ms",
                        self.counters.get(
                            "sql_statement_execution_ms", self.counters.get("db_total_time_ms", 0.0)
                        ),
                    ),
                    2,
                ),
                "db_connection_acquisition_ms": round(
                    self.stages.get(
                        "db_connection_acquisition_ms",
                        self.counters.get("db_connection_acquisition_ms", 0.0),
                    ),
                    2,
                ),
                "db_commit_ms": round(
                    self.stages.get(
                        "db_commit_ms",
                        self.counters.get("db_commit_ms", 0.0),
                    ),
                    2,
                ),
                "retrieval_latency_ms": round(retrieval_ms, 2),
                "parallel_retrieval": {
                    "wall_clock_ms": parallel_metrics["parallel_wall_time_ms"],
                    "sum_task_ms": parallel_metrics["parallel_sum_task_time_ms"],
                    "efficiency": parallel_metrics["parallel_efficiency"],
                },
                "reranking_latency_ms": round(rerank_ms, 2),
                "context_assembly_ms": round(context_ms, 2),
                "prompt_construction_ms": round(prompt_ms, 2),
                "llm_ttft_ms": ttft_ms,
                "llm_generation_ms": gen_ms,
                "llm_total_ms": llm_total_ms,
            },
            "counts": {
                "retrieval_queries": queries_count,
                "retrieved_candidates": retrieved_cands,
                "retained_candidates": retained_cands,
                "context_chunks": context_chunks,
                "llm_calls": llm_calls,
                "db_queries": int(self.counters.get("db_queries", 0)),
                "db_commits": int(self.counters.get("db_commits", 0)),
                "db_pool_checkouts": int(self.counters.get("db_pool_checkouts", 0)),
                "db_sessions_created": int(self.counters.get("db_sessions_created", 0)),
                "embedding_cache_hit": bool(cache_hit),
                "embedding_provider_calls": int(
                    self.counters.get(
                        "embedding_provider_calls",
                        0 if cache_hit else (1 if embed_ms > 0 else 0),
                    )
                ),
            },
        }

    def emit_performance_summary(
        self, outcome: str | None = None, error_category: str | None = None
    ) -> dict[str, Any]:
        """Emit a structured single-line JSON performance summary at INFO level safely."""
        try:
            if not self._summary_emitted:
                if outcome:
                    self.outcome = outcome
                if error_category:
                    self.error_category = error_category
            summary = self.to_performance_summary()
            if not self._summary_emitted:
                self._summary_emitted = True
                logger.info(
                    "RAG_PERFORMANCE_SUMMARY: %s", json.dumps(summary, separators=(",", ":"))
                )
            return summary
        except Exception as exc:
            logger.warning("Failed to emit RAG performance summary: %s", exc)
            return {}

    def as_header_dict(self) -> dict[str, str]:
        return {"X-Trace-ID": self.trace_id, "X-Request-ID": self.request_id}


# Single context-var holding the *current* RequestTrace for implicit access
_current_trace_ctx: contextvars.ContextVar[RequestTrace | None] = contextvars.ContextVar(
    "_current_trace", default=None
)


def get_current_trace() -> RequestTrace | None:
    return _current_trace_ctx.get()


def set_current_trace(trace: RequestTrace | None) -> contextvars.Token[RequestTrace | None]:
    return _current_trace_ctx.set(trace)


@contextmanager
def trace_context(trace: RequestTrace):
    tok = set_current_trace(trace)
    tid_tok = set_trace_id(trace.trace_id)
    rid_tok = set_request_id(trace.request_id)
    try:
        yield trace
    finally:
        _current_trace_ctx.reset(tok)
        trace_id_ctx_var.reset(tid_tok)
        request_id_ctx_var.reset(rid_tok)


async def isolate_stream_trace(
    gen: AsyncGenerator[Any, None],
    trace: RequestTrace | None,
) -> AsyncGenerator[Any, None]:
    """Wrap an async generator ensuring RequestTrace context isolation per step.

    Guarantees that concurrent or interleaved streaming generators do not
    cross-contaminate ContextVars (such as active trace, request ID, and trace ID)
    during async I/O, database queries, and SSE yields.
    """
    if trace is None:
        async for item in gen:
            yield item
        return

    try:
        while True:
            try:
                with trace_context(trace):
                    item = await anext(gen)
            except StopAsyncIteration:
                break
            try:
                yield item
            except GeneratorExit:
                break
            except BaseException as exc:
                with trace_context(trace):
                    try:
                        item = await gen.athrow(exc)
                    except StopAsyncIteration:
                        break
                yield item
    finally:
        with trace_context(trace):
            await gen.aclose()
