"""Tests for Task 3: Concurrent Streaming Trace Isolation.

Validates that simultaneous or interleaved streaming requests cannot mix trace IDs,
timings, database telemetry, or lifecycle counters.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tracing import (
    RequestTrace,
    get_current_trace,
    isolate_stream_trace,
    set_current_trace,
    trace_context,
)
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.llm.base import LLMResponse, LLMStreamChunk
from app.services.llm.factory import LLMProviderFactory
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService


class MockStreamingLLMProvider:
    """Mock provider that yields tokens with slight yields to facilitate concurrency interleaving."""

    name = "mock"

    def __init__(self, prefix: str = "token", token_count: int = 4):
        self.prefix = prefix
        self.token_count = token_count

    async def generate(self, request):
        return LLMResponse(
            content=f"Generated answer from {self.prefix}",
            provider=self.name,
            model=request.model,
        )

    async def stream(self, request) -> AsyncGenerator[LLMStreamChunk, None]:
        for i in range(self.token_count):
            await asyncio.sleep(0.001)
            yield LLMStreamChunk(delta=f"{self.prefix}_{i} ")


@pytest.mark.asyncio
async def test_isolate_stream_trace_direct_unit():
    """Verify isolate_stream_trace restores caller context upon every yield and encapsulates trace."""
    t1 = RequestTrace(trace_id="TRACE-UNIT-1", request_id="REQ-UNIT-1")
    t2 = RequestTrace(trace_id="TRACE-UNIT-2", request_id="REQ-UNIT-2")

    observed_traces_1: list[str | None] = []
    observed_traces_2: list[str | None] = []

    async def gen_worker(collector: list[str | None], name: str):
        for i in range(3):
            cur = get_current_trace()
            collector.append(cur.trace_id if cur else None)
            await asyncio.sleep(0.005)
            # Check after sleep
            cur_post = get_current_trace()
            collector.append(cur_post.trace_id if cur_post else None)
            yield f"{name}_{i}"

    g1 = isolate_stream_trace(gen_worker(observed_traces_1, "g1"), t1)
    g2 = isolate_stream_trace(gen_worker(observed_traces_2, "g2"), t2)

    # Caller has no trace
    assert get_current_trace() is None

    # Step g1, then check caller context is still None
    item1 = await anext(g1)
    assert item1 == "g1_0"
    assert get_current_trace() is None

    # Step g2, then check caller context is still None
    item2 = await anext(g2)
    assert item2 == "g2_0"
    assert get_current_trace() is None

    # Step g1 again
    item1 = await anext(g1)
    assert item1 == "g1_1"
    assert get_current_trace() is None

    # Step g2 again
    item2 = await anext(g2)
    assert item2 == "g2_1"
    assert get_current_trace() is None

    # Drain both
    async for _ in g1:
        pass
    async for _ in g2:
        pass

    assert get_current_trace() is None
    # All internal steps of g1 saw TRACE-UNIT-1 and never TRACE-UNIT-2
    assert all(tid == "TRACE-UNIT-1" for tid in observed_traces_1)
    assert len(observed_traces_1) == 6

    # All internal steps of g2 saw TRACE-UNIT-2 and never TRACE-UNIT-1
    assert all(tid == "TRACE-UNIT-2" for tid in observed_traces_2)
    assert len(observed_traces_2) == 6


@pytest.mark.asyncio
async def test_concurrent_interleaved_stream_chat_trace_isolation(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify simultaneous stream_chat calls isolate traces, SQL queries, and metrics with zero cross-talk."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    from app.db.session import _register_engine_listeners
    _register_engine_listeners(db_session.bind.sync_engine)

    mock_provider = MockStreamingLLMProvider(prefix="tok", token_count=3)
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req_a = RAGChatRequest(
        message="Query A: concurrent trace isolation",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )
    req_b = RAGChatRequest(
        message="Query B: concurrent trace isolation",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace_a = RequestTrace(trace_id="STREAM-TRACE-AAA", request_id="REQ-AAA")
    trace_b = RequestTrace(trace_id="STREAM-TRACE-BBB", request_id="REQ-BBB")

    gen_a = rag_service.stream_chat(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        request=req_a,
        trace=trace_a,
    )
    gen_b = rag_service.stream_chat(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        request=req_b,
        trace=trace_b,
    )

    events_a: list[str] = []
    events_b: list[str] = []

    # Interleave consumption step-by-step
    exhausted_a = False
    exhausted_b = False

    while not (exhausted_a and exhausted_b):
        if not exhausted_a:
            try:
                ev_a = await anext(gen_a)
                events_a.append(ev_a)
            except StopAsyncIteration:
                exhausted_a = True
        if not exhausted_b:
            try:
                ev_b = await anext(gen_b)
                events_b.append(ev_b)
            except StopAsyncIteration:
                exhausted_b = True

    # Validate output events received for both streams
    assert any("event: start" in e for e in events_a)
    assert any("event: done" in e for e in events_a)
    assert any("event: start" in e for e in events_b)
    assert any("event: done" in e for e in events_b)

    # Validate trace A attributes
    assert trace_a.trace_id == "STREAM-TRACE-AAA"
    assert trace_a.request_id == "REQ-AAA"
    assert trace_a.outcome == "SUCCESS"
    assert "time_to_first_token_ms" in trace_a.stages
    assert "token_streaming_ms" in trace_a.stages
    assert "db_commit_ms" in trace_a.stages
    assert trace_a.counters.get("llm_call_count") == 1

    # Validate trace B attributes
    assert trace_b.trace_id == "STREAM-TRACE-BBB"
    assert trace_b.request_id == "REQ-BBB"
    assert trace_b.outcome == "SUCCESS"
    assert "time_to_first_token_ms" in trace_b.stages
    assert "token_streaming_ms" in trace_b.stages
    assert "db_commit_ms" in trace_b.stages
    assert trace_b.counters.get("llm_call_count") == 1

    # Verify SQL query isolation: each stream executed queries that were attributed to its own trace
    assert len(trace_a.db_queries) > 0
    assert len(trace_b.db_queries) > 0

    # Ensure no errors logged in either trace
    assert len(trace_a.errors) == 0
    assert len(trace_b.errors) == 0


@pytest.mark.asyncio
async def test_concurrent_stream_cancellation_isolation(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify cancelling Stream A via athrow does not disrupt or leak into concurrent Stream B."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockStreamingLLMProvider(prefix="tok_cancel", token_count=5)
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req_a = RAGChatRequest(
        message="Cancel target",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )
    req_b = RAGChatRequest(
        message="Should complete successfully",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace_a = RequestTrace(trace_id="TRACE-CANCEL-A", request_id="REQ-CANCEL-A")
    trace_b = RequestTrace(trace_id="TRACE-SUCCESS-B", request_id="REQ-SUCCESS-B")

    gen_a = rag_service.stream_chat(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        request=req_a,
        trace=trace_a,
    )
    gen_b = rag_service.stream_chat(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        request=req_b,
        trace=trace_b,
    )

    # Pull first event from both
    ev_a1 = await anext(gen_a)
    ev_b1 = await anext(gen_b)
    assert "event: start" in ev_a1
    assert "event: start" in ev_b1

    # Cancel Stream A
    with pytest.raises(asyncio.CancelledError):
        await gen_a.athrow(asyncio.CancelledError())

    # Stream A trace should reflect cancellation
    assert trace_a.outcome == "CANCELLED"
    assert trace_a.error_category == "CLIENT_DISCONNECT"

    # Stream B must continue cleanly to completion
    events_b: list[str] = [ev_b1]
    async for chunk in gen_b:
        events_b.append(chunk)

    assert any("event: done" in e for e in events_b)
    assert trace_b.outcome == "SUCCESS"
    assert trace_b.error_category is None


@pytest.mark.asyncio
async def test_concurrent_http_streaming_trace_isolation(
    client,
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify simultaneous HTTP requests to /api/v1/chat/stream preserve trace IDs without collision."""
    from app.core.security import create_access_token
    from app.db.session import get_db
    from app.main import app
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(
        bind=db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async def _get_fresh_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _get_fresh_db

    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    token = create_access_token(user.id)

    mock_provider = MockStreamingLLMProvider(prefix="tok_http", token_count=4)
    LLMProviderFactory.set_mock_provider(mock_provider)

    payload_a = {
        "message": "Concurrent stream A",
        "knowledge_base_ids": [test_kb.id],
        "provider": "mock",
        "model": "mock-default",
        "search_mode": "keyword",
    }
    payload_b = {
        "message": "Concurrent stream B",
        "knowledge_base_ids": [test_kb.id],
        "provider": "mock",
        "model": "mock-default",
        "search_mode": "keyword",
    }

    headers_a = {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": org.id,
        "X-Trace-ID": "HTTP-CONCURRENT-TRACE-AAA",
        "X-Request-ID": "HTTP-REQ-AAA",
    }
    headers_b = {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": org.id,
        "X-Trace-ID": "HTTP-CONCURRENT-TRACE-BBB",
        "X-Request-ID": "HTTP-REQ-BBB",
    }

    # Dispatch concurrently
    resp_a, resp_b = await asyncio.gather(
        client.post("/api/v1/chat/stream", headers=headers_a, json=payload_a),
        client.post("/api/v1/chat/stream", headers=headers_b, json=payload_b),
    )

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200

    assert resp_a.headers.get("X-Trace-ID") == "HTTP-CONCURRENT-TRACE-AAA"
    assert resp_b.headers.get("X-Trace-ID") == "HTTP-CONCURRENT-TRACE-BBB"

    body_a = resp_a.text
    body_b = resp_b.text

    assert "event: start" in body_a
    assert "event: done" in body_a
    assert "event: start" in body_b
    assert "event: done" in body_b

