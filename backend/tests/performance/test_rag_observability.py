"""
End-to-End Tests for RAG Request Lifecycle Observability (Phase 5).
Verifies stage timing measurements, failure handling, trace propagation,
concurrency isolation, parallel retrieval semantics, streaming, and sanitization.
"""

import asyncio
import json
import logging
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, patch

from app.core.logging import SensitiveDataFilter
from app.core.tracing import RequestTrace, get_current_trace, trace_context
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.llm.errors import LLMException
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService
from app.services.retrieval.errors import RetrievalErrorCode, RetrievalException
from app.services.retrieval.service import RetrievalService


@pytest.mark.asyncio
async def test_successful_rag_request_timing_and_summary(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify timing measurements and structured performance summary on successful RAG request."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="What are the platform capabilities?",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-rag-trace-1", request_id="test-rag-req-1")
    with trace_context(trace):
        resp = await rag_service.generate(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        )

    # 1. Assert response correctness
    assert resp.conversation_id is not None
    assert resp.answer is not None

    # 2. Assert all lifecycle stage timings exist and are non-negative
    expected_stages = [
        "query_preprocessing_ms",
        "conversation_lookup_ms",
        "user_message_persist_ms",
        "retrieval_total_ms",
        "context_selection_ms",
        "context_assembly_ms",
        "prompt_construction_ms",
        "llm_request_ms",
        "llm_total_ms",
        "database_latency_ms",
        "persistence_total_ms",
        "total_ms",
    ]
    for stage in expected_stages:
        assert stage in trace.stages, f"Missing stage timing: {stage}"
        assert trace.stages[stage] >= 0.0, f"Stage {stage} is negative"

    # 3. Assert counters
    assert trace.counters.get("retrieval_query_count") is not None
    assert trace.counters.get("llm_call_count") == 1
    assert trace.counters.get("db_queries", 0) >= 4

    # 4. Assert structured performance summary
    summary = trace.to_performance_summary()
    assert summary["trace_id"] == "test-rag-trace-1"
    assert summary["request_id"] == "test-rag-req-1"
    assert summary["outcome"] == "SUCCESS"
    assert summary["error_category"] is None
    assert summary["total_latency_ms"] >= 0.0

    latencies = summary["latencies"]
    assert latencies["query_preprocessing_ms"] >= 0.0
    assert latencies["retrieval_latency_ms"] >= 0.0
    assert latencies["context_assembly_ms"] >= 0.0
    assert latencies["llm_total_ms"] >= 0.0

    counts = summary["counts"]
    assert counts["llm_calls"] == 1
    assert counts["db_queries"] >= 4


@pytest.mark.asyncio
async def test_failed_llm_stage_attribution(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that an LLM failure is caught, categorized, and recorded in performance summary."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    mock_provider.generate = AsyncMock(
        side_effect=LLMException(code="PROVIDER_ERROR", message="Simulated LLM rate limit")
    )
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Simulate LLM failure",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-fail-llm-trace", request_id="test-fail-llm-req")
    with trace_context(trace):
        with pytest.raises(LLMException):
            await rag_service.generate(
                session=db_session,
                organization_id=org.id,
                user_id=user.id,
                request=req,
            )

    # Verification: trace captured failure without crashing
    assert trace.outcome == "FAILED"
    assert trace.error_category == "LLM_PROVIDER_ERROR"
    assert len(trace.errors) > 0
    assert "Simulated LLM rate limit" in trace.errors[0]

    summary = trace.to_performance_summary()
    assert summary["outcome"] == "FAILED"
    assert summary["error_category"] == "LLM_PROVIDER_ERROR"


@pytest.mark.asyncio
async def test_failed_retrieval_stage_attribution(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that a retrieval exception is tagged with sanitized error category."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Simulate retrieval failure",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-fail-retrieval-trace", request_id="test-fail-retrieval-req")
    with trace_context(trace):
        with patch.object(
            RetrievalService,
            "search",
            side_effect=RetrievalException(
                message="Unauthorized KB access",
                code=RetrievalErrorCode.UNAUTHORIZED_KNOWLEDGE_BASE,
                status_code=403,
            ),
        ):
            with pytest.raises(RetrievalException):
                await rag_service.generate(
                    session=db_session,
                    organization_id=org.id,
                    user_id=user.id,
                    request=req,
                )

    assert trace.outcome == "FAILED"
    assert trace.error_category == "RETRIEVAL_UNAUTHORIZED_KNOWLEDGE_BASE"
    summary = trace.to_performance_summary()
    assert summary["outcome"] == "FAILED"
    assert summary["error_category"] == "RETRIEVAL_UNAUTHORIZED_KNOWLEDGE_BASE"


def test_trace_id_propagation():
    """Verify trace ID propagates cleanly within trace context and resets afterwards."""
    trace = RequestTrace(trace_id="propagated-trace-777", request_id="propagated-req-888")
    assert get_current_trace() is None

    with trace_context(trace) as active:
        assert active.trace_id == "propagated-trace-777"
        current = get_current_trace()
        assert current is not None
        assert current.trace_id == "propagated-trace-777"
        assert current.request_id == "propagated-req-888"

    assert get_current_trace() is None


@pytest.mark.asyncio
async def test_concurrent_requests_trace_isolation():
    """Verify concurrent async requests maintain isolated traces, counters, and stage timings."""
    async def worker(worker_id: int):
        t_id = f"worker-trace-{worker_id}"
        r_id = f"worker-req-{worker_id}"
        tr = RequestTrace(trace_id=t_id, request_id=r_id)
        with trace_context(tr):
            # Simulate async task work
            await asyncio.sleep(0.01)
            active = get_current_trace()
            assert active is not None
            assert active.trace_id == t_id
            assert active.request_id == r_id
            tr.record("worker_stage_ms", worker_id * 10.0)
            tr.set_counter("worker_counter", worker_id)
            await asyncio.sleep(0.01)
            # Verify after sleep contextvar remains strictly isolated
            active_after = get_current_trace()
            assert active_after.trace_id == t_id
            assert active_after.counters["worker_counter"] == worker_id
            return tr.to_performance_summary()

    results = await asyncio.gather(*(worker(i) for i in range(1, 6)))
    assert len(results) == 5
    for i, res in enumerate(results, start=1):
        assert res["trace_id"] == f"worker-trace-{i}"
        assert res["request_id"] == f"worker-req-{i}"


def test_parallel_retrieval_timing_semantics():
    """Verify parallel task sum vs wall clock semantics in parallel retrieval metrics."""
    trace = RequestTrace()
    trace.record("vector_search_ms", 45.0)
    trace.record("keyword_search_ms", 35.0)
    # Simulate overlapping start/end offsets
    trace.timestamps["vector_search_started"] = 10.0
    trace.timestamps["vector_search_completed"] = 55.0  # 45ms duration
    trace.timestamps["keyword_search_started"] = 12.0
    trace.timestamps["keyword_search_completed"] = 47.0  # 35ms duration

    metrics = trace.calculate_parallel_metrics()
    assert metrics["parallel_task_count"] == 2
    # Wall clock time: min start (10) to max end (55) = 45ms
    assert metrics["parallel_wall_time_ms"] == 45.0
    # Sum task time: 45 + 35 = 80ms
    assert metrics["parallel_sum_task_time_ms"] == 80.0
    # Efficiency = sum / wall = 80 / 45 ~= 1.78
    assert metrics["parallel_efficiency"] >= 1.5


@pytest.mark.asyncio
async def test_streaming_chat_observability_and_cancellation(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify streaming RAG generator captures TTFT, token metrics, and handles cancellation."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Stream response test",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-stream-trace", request_id="test-stream-req")
    events = []
    with trace_context(trace):
        gen = rag_service.stream_chat(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        )
        async for event_line in gen:
            if event_line.strip():
                events.append(event_line)

    assert len(events) > 0
    # Check that events include start, retrieval, tokens, done
    joined = "".join(events)
    assert "event: start" in joined
    assert "event: retrieval" in joined
    assert "event: done" in joined

    # Verify streaming timing
    assert "time_to_first_token_ms" in trace.stages
    assert "token_streaming_ms" in trace.stages
    assert trace.counters.get("llm_call_count") == 1

    summary = trace.to_performance_summary()
    assert summary["outcome"] == "SUCCESS"
    assert summary["latencies"]["llm_ttft_ms"] >= 0.0


@pytest.mark.asyncio
async def test_streaming_chat_client_cancellation_semantics(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that when a client disconnects (CancelledError), outcome is CANCELLED and CLIENT_DISCONNECT."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Cancel test",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-stream-cancel-trace", request_id="test-stream-cancel-req")
    with trace_context(trace):
        gen = rag_service.stream_chat(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        )
        # Read first event then simulate client disconnect (throw CancelledError into generator)
        await anext(gen)
        try:
            await gen.athrow(asyncio.CancelledError())
        except (asyncio.CancelledError, StopAsyncIteration):
            pass

    assert trace.outcome == "CANCELLED"
    assert trace.error_category == "CLIENT_DISCONNECT"


def test_sensitive_data_absence_and_filter():
    """Verify that credentials, tokens, and sensitive keys are absent from performance summaries and logs."""
    trace = RequestTrace()
    trace.set_counter("api_key", "sk-secret-12345")
    trace.set_counter("user_password", "super-secret")
    trace.set_counter("jwt_token", "bearer.ey...secret")
    trace.set_counter("safe_counter", 100)

    export_dict = trace.to_export_dict()
    counters = export_dict["counters"]
    assert "safe_counter" in counters
    assert "api_key" not in counters
    assert "user_password" not in counters
    assert "jwt_token" not in counters

    # SensitiveDataFilter verification
    filt = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Calling provider with api_key=xyz",
        args=(),
        exc_info=None,
    )
    filt.filter(record)
    assert record.msg == "[FILTERED_SENSITIVE_DATA]"
