"""
Regression and verification tests for Step 7: Production-Representative RAG Performance Optimization.
Verifies:
1. First-turn chat requests (conversation_id=None) bypass redundant DB history queries.
2. Multi-turn chat requests (conversation_id provided) accurately load existing message history.
3. Embedding cache timing metrics, hits, and provider call counts propagate to performance summaries.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tracing import RequestTrace, trace_context
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService


@pytest.mark.asyncio
async def test_new_conversation_bypasses_history_query(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that conversation_id=None does not execute redundant DB message queries."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_llm = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_llm)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Hello, starting a brand new thread!",
        conversation_id=None,
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    tr = RequestTrace(trace_id="test-new-conv-opt")
    with (
        trace_context(tr),
        patch(
            "app.services.rag.conversations.ConversationService.get_recent_messages",
            new_callable=AsyncMock,
        ) as mock_get_history,
    ):
        resp = await rag_service.generate(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        )

    # Redundant query must NOT be invoked on brand new conversation
    assert not mock_get_history.called
    assert resp.conversation_id is not None
    assert tr.stages.get("message_history_ms", -1) == 0.0
    assert tr.counters.get("history_messages") == 0


@pytest.mark.asyncio
async def test_existing_conversation_loads_history(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that continuing an existing conversation invokes get_recent_messages."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_llm = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_llm)
    rag_service = RAGService()

    from app.services.rag.conversations import ConversationService

    conv = await ConversationService.create_conversation(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        title="Test thread",
        knowledge_base_ids=[test_kb.id],
    )
    await db_session.commit()

    req = RAGChatRequest(
        message="Follow-up question",
        conversation_id=conv.id,
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    tr = RequestTrace(trace_id="test-turn-2")
    with (
        trace_context(tr),
        patch(
            "app.services.rag.conversations.ConversationService.get_recent_messages",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_get_history,
    ):
        resp = await rag_service.generate(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        )

    assert mock_get_history.called
    assert resp.conversation_id == conv.id


@pytest.mark.asyncio
async def test_performance_summary_includes_embedding_cache_fields(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that performance summary dictionaries expose embedding cache latency and provider calls."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_llm = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_llm)
    rag_service = RAGService()

    q = "What is cache telemetry propagation in RAGForge?"
    req = RAGChatRequest(
        message=q,
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    # 1. First execution (cache miss)
    tr1 = RequestTrace(trace_id="tr-cache-miss")
    with trace_context(tr1):
        await rag_service.generate(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        )

    summary1 = tr1.to_performance_summary()
    assert "embedding_cache_latency_ms" in summary1["latencies"]
    assert "embedding_cache_hit" in summary1["counts"]
    assert "embedding_provider_calls" in summary1["counts"]

    # 2. Second execution (cache hit)
    tr2 = RequestTrace(trace_id="tr-cache-hit")
    with trace_context(tr2):
        await rag_service.generate(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        )

    summary2 = tr2.to_performance_summary()
    assert summary2["counts"]["embedding_cache_hit"] is True
    assert summary2["counts"]["embedding_provider_calls"] == 0
    assert summary2["latencies"]["embedding_cache_latency_ms"] >= 0.0
