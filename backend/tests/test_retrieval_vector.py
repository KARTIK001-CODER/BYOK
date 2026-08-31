import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.providers import get_embedding_provider
from app.services.retrieval.errors import RetrievalErrorCode, RetrievalException
from app.services.retrieval.schemas import RetrievalFilter, RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService
from app.services.retrieval.vector import VectorRetriever


class MockMismatchProvider(BaseEmbeddingProvider):
    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-mismatch"

    @property
    def dimension(self) -> int:
        return 384

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]

    def embed_query(self, _query: str) -> list[float]:
        # Return wrong dimension (128 instead of 384)
        return [0.1] * 128


@pytest.mark.asyncio
async def test_vector_retriever_exact_and_semantic_match(
    db_session: AsyncSession, test_user_and_org: dict, test_kb: KnowledgeBase
) -> None:
    """Verify vector search retrieves the most semantically relevant chunks with scores."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    provider = get_embedding_provider()

    # 1. Create Document & Version
    doc = Document(
        knowledge_base_id=test_kb.id,
        organization_id=org.id,
        uploaded_by=user.id,
        name="Auth System Guide",
        original_filename="auth.md",
        content_type="text/markdown",
        file_size=1000,
        storage_key="docs/auth.md",
        checksum="chk-auth-1",
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

    # 2. Insert 3 Chunks with real embeddings
    texts = [
        "JWT tokens expire after 15 minutes and refresh tokens are rotated safely in PostgreSQL.",
        "The recursive chunker splits raw text into 1000 character windows with 150 overlap.",
        "PostgreSQL pgvector provides cosine distance indexing with HNSW graph indexing.",
    ]
    vectors = provider.embed_documents(texts)

    for idx, (text, vec) in enumerate(zip(texts, vectors, strict=True)):
        chunk = DocumentChunk(
            document_id=doc.id,
            document_version_id=doc_ver.id,
            organization_id=org.id,
            knowledge_base_id=test_kb.id,
            chunk_index=idx,
            content=text,
            character_count=len(text),
            word_count=len(text.split()),
            section_title=f"Section {idx}",
            embedding=vec,
            embedding_model=provider.model_name,
            embedding_provider=provider.provider_name,
            embedding_dimension=provider.dimension,
        )
        db_session.add(chunk)

    await db_session.commit()

    # 3. Query for JWT Authentication
    query = "How do JWT access and refresh tokens work?"
    query_emb = provider.embed_query(query)

    candidates = await VectorRetriever.retrieve(
        session=db_session,
        organization_id=org.id,
        query_embedding=query_emb,
        candidate_k=10,
    )

    assert len(candidates) == 3
    # Top match should be the JWT chunk
    assert candidates[0].chunk.chunk_index == 0
    assert "JWT tokens expire" in candidates[0].chunk.content
    assert candidates[0].score > 0.4
    assert candidates[0].source == "vector"

    # 4. Search via RetrievalService
    req = RetrievalRequest(
        query=query,
        top_k=2,
        search_mode=SearchMode.VECTOR,
    )
    response = await RetrievalService.search(
        session=db_session,
        organization_id=org.id,
        request=req,
    )

    assert response.total_results == 2
    assert len(response.results) == 2
    assert response.results[0].rank == 1
    assert response.results[0].vector_score is not None
    assert response.results[0].provenance.chunk_id == candidates[0].chunk.id
    assert response.results[0].provenance.organization_id == org.id


@pytest.mark.asyncio
async def test_vector_retriever_dimension_mismatch(
    db_session: AsyncSession, test_user_and_org: dict
) -> None:
    """Verify error raised if query embedding dimension does not match provider dimension."""
    org: Organization = test_user_and_org["org"]
    mismatch_provider = MockMismatchProvider()

    req = RetrievalRequest(
        query="Test query",
        search_mode=SearchMode.VECTOR,
    )

    with pytest.raises(RetrievalException) as exc_info:
        await RetrievalService.search(
            session=db_session,
            organization_id=org.id,
            request=req,
            provider=mismatch_provider,
        )

    assert exc_info.value.code == RetrievalErrorCode.EMBEDDING_DIMENSION_MISMATCH.value


@pytest.mark.asyncio
async def test_vector_retriever_scoped_filters(
    db_session: AsyncSession, test_user_and_org: dict, test_kb: KnowledgeBase
) -> None:
    """Verify metadata filters restrict vector candidate pool."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    provider = get_embedding_provider()

    # Create 2 documents
    doc1 = Document(
        knowledge_base_id=test_kb.id,
        organization_id=org.id,
        uploaded_by=user.id,
        name="Doc 1",
        original_filename="doc1.md",
        content_type="text/markdown",
        file_size=100,
        storage_key="docs/doc1.md",
        checksum="chk-1",
        status=DocumentStatus.READY,
        current_version=1,
    )
    doc2 = Document(
        knowledge_base_id=test_kb.id,
        organization_id=org.id,
        uploaded_by=user.id,
        name="Doc 2",
        original_filename="doc2.md",
        content_type="text/markdown",
        file_size=100,
        storage_key="docs/doc2.md",
        checksum="chk-2",
        status=DocumentStatus.READY,
        current_version=1,
    )
    db_session.add_all([doc1, doc2])
    await db_session.flush()

    ver1 = DocumentVersion(
        document_id=doc1.id,
        version_number=1,
        storage_key=doc1.storage_key,
        checksum=doc1.checksum,
        file_size=100,
        content_type="text/markdown",
    )
    ver2 = DocumentVersion(
        document_id=doc2.id,
        version_number=1,
        storage_key=doc2.storage_key,
        checksum=doc2.checksum,
        file_size=100,
        content_type="text/markdown",
    )
    db_session.add_all([ver1, ver2])
    await db_session.flush()

    emb = provider.embed_documents(["Content 1", "Content 2"])
    chunk1 = DocumentChunk(
        document_id=doc1.id,
        document_version_id=ver1.id,
        organization_id=org.id,
        knowledge_base_id=test_kb.id,
        chunk_index=0,
        content="Content 1",
        character_count=9,
        word_count=2,
        embedding=emb[0],
    )
    chunk2 = DocumentChunk(
        document_id=doc2.id,
        document_version_id=ver2.id,
        organization_id=org.id,
        knowledge_base_id=test_kb.id,
        chunk_index=0,
        content="Content 2",
        character_count=9,
        word_count=2,
        embedding=emb[1],
    )
    db_session.add_all([chunk1, chunk2])
    await db_session.commit()

    # Query with filter on doc1 only
    req = RetrievalRequest(
        query="Content",
        search_mode=SearchMode.VECTOR,
        filters=RetrievalFilter(document_ids=[doc1.id]),
    )
    resp = await RetrievalService.search(
        session=db_session,
        organization_id=org.id,
        request=req,
    )

    assert resp.total_results == 1
    assert resp.results[0].document_id == doc1.id
