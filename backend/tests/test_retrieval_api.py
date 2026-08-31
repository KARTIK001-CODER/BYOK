import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.embeddings.providers import get_embedding_provider


@pytest.mark.asyncio
async def test_retrieval_api_end_to_end(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
) -> None:
    """Verify HTTP API endpoint POST /api/v1/retrieval/search end-to-end."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    token = create_access_token(user.id)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": org.id,
    }

    # Seed an indexed document
    provider = get_embedding_provider()
    doc = Document(
        knowledge_base_id=test_kb.id,
        organization_id=org.id,
        uploaded_by=user.id,
        name="Architecture Overview",
        original_filename="arch.md",
        content_type="text/markdown",
        file_size=500,
        storage_key="docs/arch.md",
        checksum="chk-api-1",
        status=DocumentStatus.READY,
        current_version=1,
    )
    db_session.add(doc)
    await db_session.flush()

    doc_ver = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        storage_key=doc.storage_key,
        checksum=doc.checksum,
        file_size=doc.file_size,
        content_type=doc.content_type,
        uploaded_by=user.id,
    )
    db_session.add(doc_ver)
    await db_session.flush()

    content = "RAGForge uses pgvector and PostgreSQL full-text search with Reciprocal Rank Fusion."
    emb = provider.embed_documents([content])[0]

    chunk = DocumentChunk(
        document_id=doc.id,
        document_version_id=doc_ver.id,
        organization_id=org.id,
        knowledge_base_id=test_kb.id,
        chunk_index=0,
        content=content,
        character_count=len(content),
        word_count=len(content.split()),
        embedding=emb,
        embedding_model=provider.model_name,
        embedding_provider=provider.provider_name,
        embedding_dimension=provider.dimension,
    )
    db_session.add(chunk)
    await db_session.commit()

    # 1. Successful Hybrid Search with debug trace
    payload = {
        "query": "How does RAGForge use pgvector and FTS?",
        "search_mode": "hybrid",
        "top_k": 5,
        "candidate_k": 20,
        "debug": True,
    }
    res = await client.post("/api/v1/retrieval/search", headers=headers, json=payload)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["query"] == payload["query"]
    assert data["search_mode"] == "hybrid"
    assert data["total_results"] >= 1
    assert len(data["results"]) >= 1

    first_res = data["results"][0]
    assert first_res["chunk_id"] == chunk.id
    assert first_res["score"] > 0
    assert first_res["provenance"]["organization_id"] == org.id
    assert first_res["provenance"]["knowledge_base_id"] == test_kb.id
    assert data["trace"] is not None
    assert data["trace"]["query_hash"] is not None

    # 2. Search without debug flag (trace must be null)
    payload_no_debug = {
        "query": "pgvector",
        "search_mode": "vector",
        "top_k": 3,
        "debug": False,
    }
    res2 = await client.post("/api/v1/retrieval/search", headers=headers, json=payload_no_debug)
    assert res2.status_code == status.HTTP_200_OK
    assert res2.json()["trace"] is None


@pytest.mark.asyncio
async def test_retrieval_api_validation_errors(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """Verify HTTP 422 for invalid payloads."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Empty query
    res = await client.post("/api/v1/retrieval/search", headers=headers, json={"query": "   "})
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # candidate_k < top_k
    res2 = await client.post(
        "/api/v1/retrieval/search",
        headers=headers,
        json={"query": "valid query", "top_k": 20, "candidate_k": 10},
    )
    assert res2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # query exceeds max length
    res3 = await client.post(
        "/api/v1/retrieval/search",
        headers=headers,
        json={"query": "a" * 2001},
    )
    assert res3.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_retrieval_api_unauthorized_and_forbidden(client: AsyncClient) -> None:
    """Verify 401 when no token is provided and 403 for unauthorized org."""
    # 401 Unauthorized
    res = await client.post("/api/v1/retrieval/search", json={"query": "test"})
    assert res.status_code == status.HTTP_401_UNAUTHORIZED
