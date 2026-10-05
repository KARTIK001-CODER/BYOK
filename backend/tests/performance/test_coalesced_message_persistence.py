import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.knowledge_base import KnowledgeBase
from app.models.message import Message, MessageRole
from app.models.organization import Organization
from app.models.user import User
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.services.rag.conversations import ConversationService
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService


@pytest.mark.asyncio
async def test_add_message_deferred_flush_in_memory_id(
    db_session: AsyncSession,
    test_user_and_org: dict,
):
    """Verify add_message with flush=False sets id and created_at in memory without immediate DB insert."""
    org: Organization = test_user_and_org["org"]
    user: User = test_user_and_org["user"]

    conv = await ConversationService.create_conversation(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        title="Deferred Flush Test",
        flush=True,
    )

    msg = await ConversationService.add_message(
        session=db_session,
        conversation_id=conv.id,
        role=MessageRole.USER,
        content="Testing deferred flush",
        flush=False,
    )

    assert msg.id is not None
    assert len(msg.id) == 36
    assert msg.created_at is not None
    assert msg.content == "Testing deferred flush"

    # Commit should persist it cleanly
    await db_session.commit()

    # Query back to verify persistence
    stmt = select(Message).where(Message.id == msg.id)
    result = await db_session.execute(stmt)
    persisted = result.scalar_one_or_none()
    assert persisted is not None
    assert persisted.content == "Testing deferred flush"
    assert persisted.conversation_id == conv.id


@pytest.mark.asyncio
async def test_create_conversation_deferred_flush(
    db_session: AsyncSession,
    test_user_and_org: dict,
):
    """Verify create_conversation with flush=False assigns id immediately and commits cleanly with messages."""
    org: Organization = test_user_and_org["org"]
    user: User = test_user_and_org["user"]

    conv = await ConversationService.create_conversation(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        title="Batch Staged Conv",
        flush=False,
    )
    assert conv.id is not None
    assert len(conv.id) == 36

    msg = await ConversationService.add_message(
        session=db_session,
        conversation_id=conv.id,
        role=MessageRole.USER,
        content="First message in staged conversation",
        flush=False,
    )
    assert msg.conversation_id == conv.id

    # Commit both together in a single transaction
    await db_session.commit()

    # Verify both exist in DB
    c_res = await db_session.execute(select(Conversation).where(Conversation.id == conv.id))
    assert c_res.scalar_one_or_none() is not None

    m_res = await db_session.execute(select(Message).where(Message.id == msg.id))
    assert m_res.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_deferred_flush_rollback_safety(
    db_session: AsyncSession,
    test_user_and_org: dict,
):
    """Verify that uncommitted messages added with flush=False are discarded upon session rollback."""
    org: Organization = test_user_and_org["org"]
    user: User = test_user_and_org["user"]

    conv = await ConversationService.create_conversation(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        title="Rollback Test",
        flush=True,
    )

    msg = await ConversationService.add_message(
        session=db_session,
        conversation_id=conv.id,
        role=MessageRole.USER,
        content="Should be rolled back",
        flush=False,
    )
    msg_id = msg.id

    # Roll back transaction
    await db_session.rollback()

    # Query back to verify it was NOT persisted
    stmt = select(Message).where(Message.id == msg_id)
    result = await db_session.execute(stmt)
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_rag_generate_coalesced_persistence(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify full RAG generate pipeline persists both user and assistant messages with valid IDs."""
    org: Organization = test_user_and_org["org"]
    user: User = test_user_and_org["user"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="What is the policy for remote work?",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
        search_mode="vector",
    )

    resp = await rag_service.generate(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        request=req,
    )

    assert resp.conversation_id is not None
    assert resp.message_id is not None
    assert len(resp.answer) > 0

    # Query all messages in the conversation
    stmt = (
        select(Message)
        .where(Message.conversation_id == resp.conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db_session.execute(stmt)
    msgs = list(result.scalars().all())

    assert len(msgs) == 2
    assert msgs[0].role == MessageRole.USER
    assert msgs[0].content == "What is the policy for remote work?"
    assert msgs[1].role == MessageRole.ASSISTANT
    assert msgs[1].id == resp.message_id


@pytest.mark.asyncio
async def test_rag_stream_chat_coalesced_persistence(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Verify stream_chat pipeline persists both user and assistant messages with coalesced flushes."""
    org: Organization = test_user_and_org["org"]
    user: User = test_user_and_org["user"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    rag_service = RAGService()
    req = RAGChatRequest(
        message="Explain vacation accrual rules.",
        knowledge_base_ids=[test_kb.id],
        provider="mock",
        model="mock-default",
        search_mode="vector",
    )

    events = []
    gen = rag_service.stream_chat(
        session=db_session,
        organization_id=org.id,
        user_id=user.id,
        request=req,
    )
    async for event_line in gen:
        if event_line.strip():
            events.append(event_line)

    joined = "".join(events)
    assert "event: start" in joined
    assert "event: done" in joined

    # Extract conversation_id from the DB
    stmt = (
        select(Conversation)
        .where(
            Conversation.organization_id == org.id,
            Conversation.user_id == user.id,
        )
        .order_by(Conversation.created_at.desc())
    )
    res = await db_session.execute(stmt)
    conv = res.scalars().first()
    assert conv is not None

    # Check messages in that conversation
    msg_stmt = (
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc())
    )
    m_res = await db_session.execute(msg_stmt)
    msgs = list(m_res.scalars().all())

    assert len(msgs) == 2
    assert msgs[0].role == MessageRole.USER
    assert msgs[0].content == "Explain vacation accrual rules."
    assert msgs[1].role == MessageRole.ASSISTANT
