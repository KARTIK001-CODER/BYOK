import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider


@pytest.mark.asyncio
async def test_chat_models_endpoint(client: AsyncClient, test_user_and_org: dict):
    """Test GET /api/v1/chat/models."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)

    resp = await client.get("/api/v1/chat/models", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    providers = resp.json()
    assert len(providers) >= 2
    prov_ids = [p["id"] for p in providers]
    assert "groq" in prov_ids
    assert "openai" in prov_ids


@pytest.mark.asyncio
async def test_rag_chat_synchronous_generation(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Test full synchronous POST /api/v1/chat flow with mock provider."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    token = create_access_token(user.id)

    # Seed a document and chunk
    doc = Document(
        knowledge_base_id=test_kb.id,
        organization_id=org.id,
        uploaded_by=user.id,
        name="Security Whitepaper.pdf",
        original_filename="Security Whitepaper.pdf",
        content_type="application/pdf",
        file_size=1024,
        storage_key="test/doc.pdf",
        checksum="chk-123",
        status=DocumentStatus.READY,
    )
    db_session.add(doc)
    await db_session.flush()

    ver = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        storage_key="test/doc.pdf",
        content_type="application/pdf",
        file_size=1024,
        checksum="chk-123",
    )
    db_session.add(ver)
    await db_session.flush()

    chunk = DocumentChunk(
        document_id=doc.id,
        document_version_id=ver.id,
        organization_id=org.id,
        knowledge_base_id=test_kb.id,
        chunk_index=0,
        content="The platform enforces rotation on all refresh tokens after single use.",
        character_count=75,
        word_count=12,
        page_number=3,
        section_title="Token Lifecycle",
        embedding=[0.05] * 384,
    )
    db_session.add(chunk)
    await db_session.commit()

    # Set mock provider
    mock_provider = MockLLMProvider(
        default_response="Refresh tokens are rotated after single use for maximum security. [1]"
    )
    LLMProviderFactory.set_mock_provider(mock_provider)

    resp = await client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Organization-ID": org.id},
        json={
            "message": "How do refresh tokens rotate?",
            "knowledge_base_ids": [test_kb.id],
            "provider": "mock",
            "model": "mock-default",
            "search_mode": "keyword",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "conversation_id" in data
    assert "message_id" in data
    assert "rotated after single use" in data["answer"]
    assert len(data["citations"]) >= 1
    assert data["citations"][0]["id"] == 1
    assert data["citations"][0]["document_name"] == "Security Whitepaper.pdf"
    assert data["citations"][0]["page_number"] == 3
    assert data["citations"][0]["section_title"] == "Token Lifecycle"
    assert data["retrieval"]["result_count"] >= 1


@pytest.mark.asyncio
async def test_rag_chat_stream_generation(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """Test SSE streaming POST /api/v1/chat/stream flow with mock provider."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    token = create_access_token(user.id)

    # Seed a document and chunk
    doc = Document(
        knowledge_base_id=test_kb.id,
        organization_id=org.id,
        name="Auth Architecture",
        original_filename="auth.txt",
        content_type="text/plain",
        file_size=500,
        storage_key="test/auth.txt",
        checksum="chk-auth",
        status=DocumentStatus.READY,
    )
    db_session.add(doc)
    await db_session.flush()

    ver = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        storage_key="test/auth.txt",
        content_type="text/plain",
        file_size=500,
        checksum="chk-auth",
    )
    db_session.add(ver)
    await db_session.flush()

    chunk = DocumentChunk(
        document_id=doc.id,
        document_version_id=ver.id,
        organization_id=org.id,
        knowledge_base_id=test_kb.id,
        chunk_index=0,
        content="Access tokens are short lived and signed via HS256 algorithm.",
        character_count=60,
        word_count=10,
        page_number=1,
        section_title="Tokens",
        embedding=[0.1] * 384,
    )
    db_session.add(chunk)
    await db_session.commit()

    mock_provider = MockLLMProvider(default_response="Access tokens use HS256 signatures. [1]")
    LLMProviderFactory.set_mock_provider(mock_provider)

    resp = await client.post(
        "/api/v1/chat/stream",
        headers={"Authorization": f"Bearer {token}", "X-Organization-ID": org.id},
        json={
            "message": "What signing algorithm is used for access tokens?",
            "knowledge_base_ids": [test_kb.id],
            "provider": "mock",
            "model": "mock-default",
            "search_mode": "keyword",
        },
    )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text

    assert "event: start" in body
    assert "event: retrieval" in body
    assert "event: token" in body
    assert "event: citation" in body
    assert "event: done" in body
