"""
Tests for RAG transaction safety, commit failure handling, and rollback behavior.
Verifies that database commit exceptions are properly surfaced, downstream LLM execution
is aborted when persistence fails, session rollback is executed, and original exceptions
are preserved even if rollback fails.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tracing import RequestTrace, trace_context
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.llm.base import LLMResponse
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService


@pytest.mark.asyncio
async def test_generate_pre_llm_commit_failure_prevents_llm_call(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that a commit failure before LLM invocation prevents LLM calls and triggers rollback."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    mock_provider.generate = AsyncMock(
        return_value=LLMResponse(
            content="Should not be generated", model="mock-default", provider="mock"
        )
    )
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="What is the refund policy?",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-tx-fail-1", request_id="req-tx-fail-1")

    # Spy on session.rollback
    original_rollback = db_session.rollback
    rollback_mock = AsyncMock(side_effect=original_rollback)

    # Force commit failure on pre-LLM commit
    commit_call_count = 0

    async def failing_commit():
        nonlocal commit_call_count
        commit_call_count += 1
        raise SQLAlchemyError("Simulated database commit failure (disk full / dropped connection)")

    with (
        patch.object(db_session, "commit", side_effect=failing_commit),
        patch.object(db_session, "rollback", rollback_mock),
        trace_context(trace),
        pytest.raises(SQLAlchemyError, match="Simulated database commit failure"),
    ):
        await rag_service.generate(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        )

    # 1. LLM provider must NEVER have been invoked
    mock_provider.generate.assert_not_called()

    # 2. Rollback must have been executed
    rollback_mock.assert_awaited()

    # 3. Trace must record failure with DATABASE_COMMIT_ERROR category
    assert trace.outcome == "FAILED"
    assert trace.error_category == "DATABASE_COMMIT_ERROR"
    assert any("pre_llm_commit_failed" in err for err in trace.errors)


@pytest.mark.asyncio
async def test_generate_post_llm_commit_failure_triggers_rollback(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that a commit failure when persisting assistant message triggers rollback and raises."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Explain database transactions.",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-tx-fail-2", request_id="req-tx-fail-2")

    commit_calls = 0
    original_commit = db_session.commit
    rollback_mock = AsyncMock(side_effect=db_session.rollback)

    async def commit_fail_on_second():
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 1:
            # Pre-LLM commit succeeds
            return await original_commit()
        # Post-LLM assistant commit fails
        raise SQLAlchemyError("Simulated assistant message commit failure")

    with (
        patch.object(db_session, "commit", side_effect=commit_fail_on_second),
        patch.object(db_session, "rollback", rollback_mock),
        trace_context(trace),
        pytest.raises(SQLAlchemyError, match="Simulated assistant message commit failure"),
    ):
        await rag_service.generate(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        )

    # Rollback must have been executed on the assistant commit failure
    rollback_mock.assert_awaited()
    assert trace.outcome == "FAILED"
    assert trace.error_category == "DATABASE_COMMIT_ERROR"
    assert any("assistant_commit_failed" in err for err in trace.errors)


@pytest.mark.asyncio
async def test_stream_chat_user_commit_failure_prevents_llm(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that commit failure on user message in streaming prevents LLM stream and yields error."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    mock_provider.stream = AsyncMock()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Hello streaming world",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-tx-stream-1", request_id="req-tx-stream-1")
    rollback_mock = AsyncMock(side_effect=db_session.rollback)

    async def fail_user_commit():
        raise SQLAlchemyError("User message commit error")

    events = []
    with (
        patch.object(db_session, "commit", side_effect=fail_user_commit),
        patch.object(db_session, "rollback", rollback_mock),
        trace_context(trace),
    ):
        async for event_chunk in rag_service.stream_chat(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        ):
            events.append(event_chunk)

    # 1. LLM stream must NOT have been called
    mock_provider.stream.assert_not_called()

    # 2. Rollback must have been called
    rollback_mock.assert_awaited()

    # 3. Only error event must be yielded, NO start event
    assert len(events) == 1
    assert "event: error" in events[0]
    assert "event: start" not in "".join(events)

    # 4. Trace must reflect commit failure
    assert trace.outcome == "FAILED"
    assert trace.error_category == "DATABASE_COMMIT_ERROR"


@pytest.mark.asyncio
async def test_stream_chat_pre_llm_commit_failure_aborts_before_tokens(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that failure on pre-LLM read-release commit in streaming aborts before streaming tokens."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    mock_provider.stream = AsyncMock()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Streaming query",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-tx-stream-2", request_id="req-tx-stream-2")
    rollback_mock = AsyncMock(side_effect=db_session.rollback)

    commit_count = 0
    original_commit = db_session.commit

    async def fail_pre_llm_commit():
        nonlocal commit_count
        commit_count += 1
        if commit_count == 1:
            # User message commit succeeds
            return await original_commit()
        # Pre-LLM commit fails
        raise SQLAlchemyError("Pre-LLM commit failure")

    events = []
    with (
        patch.object(db_session, "commit", side_effect=fail_pre_llm_commit),
        patch.object(db_session, "rollback", rollback_mock),
        trace_context(trace),
    ):
        async for event_chunk in rag_service.stream_chat(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        ):
            events.append(event_chunk)

    # LLM stream must NOT have been called
    mock_provider.stream.assert_not_called()
    rollback_mock.assert_awaited()

    # Must contain error event, and NO token or done event
    all_events = "".join(events)
    assert "event: error" in all_events
    assert "event: token" not in all_events
    assert "event: done" not in all_events
    assert trace.outcome == "FAILED"
    assert trace.error_category == "DATABASE_COMMIT_ERROR"


@pytest.mark.asyncio
async def test_stream_chat_assistant_commit_failure_yields_error_not_done(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify that failure on final assistant commit yields error instead of done event."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Streaming with assistant failure",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
    )

    trace = RequestTrace(trace_id="test-tx-stream-3", request_id="req-tx-stream-3")
    rollback_mock = AsyncMock(side_effect=db_session.rollback)

    commit_count = 0
    original_commit = db_session.commit

    async def fail_final_commit():
        nonlocal commit_count
        commit_count += 1
        if commit_count < 3:
            # 1: user commit, 2: pre-llm commit
            return await original_commit()
        # 3: final assistant commit fails
        raise SQLAlchemyError("Final assistant commit error")

    events = []
    with (
        patch.object(db_session, "commit", side_effect=fail_final_commit),
        patch.object(db_session, "rollback", rollback_mock),
        trace_context(trace),
    ):
        async for event_chunk in rag_service.stream_chat(
            session=db_session,
            organization_id=org.id,
            user_id=user.id,
            request=req,
        ):
            events.append(event_chunk)

    all_events = "".join(events)
    # Tokens were sent
    assert "event: token" in all_events
    # But done event must NOT have been sent!
    assert "event: done" not in all_events
    # Instead, an error event must terminate the stream
    assert "event: error" in all_events
    rollback_mock.assert_awaited()
    assert trace.outcome == "FAILED"
    assert trace.error_category == "DATABASE_COMMIT_ERROR"


@pytest.mark.asyncio
async def test_safe_commit_preserves_original_exception_when_rollback_fails():
    """Verify _safe_commit preserves the commit exception when rollback also fails."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock(
        side_effect=OperationalError("COMMIT", {}, Exception("DB disconnect"))
    )
    mock_session.rollback = AsyncMock(
        side_effect=OperationalError("ROLLBACK", {}, Exception("Socket dead"))
    )

    with pytest.raises(OperationalError) as exc_info:
        await RAGService._safe_commit(mock_session)

    # The raised exception must be the commit error
    assert "DB disconnect" in str(exc_info.value)
    # The cause must be the rollback error
    assert exc_info.value.__cause__ is not None
    assert "Socket dead" in str(exc_info.value.__cause__)
