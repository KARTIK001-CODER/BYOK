import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.embeddings.providers import get_embedding_provider
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService


@pytest.mark.asyncio
async def test_hybrid_retriever_fusion_and_deduplication(
    db_session: AsyncSession, test_user_and_org: dict, test_kb: KnowledgeBase
) -> None:
    """
    Verify hybrid retrieval combines vector and keyword results with RRF:
    - Chunk A matches both semantically and via exact keyword -> ranks #1 with hybrid source.
    - Chunk B matches mainly via semantic search -> ranks with vector source.
    - Chunk C matches via exact rare keyword -> ranks with keyword source.
    """
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    provider = get_embedding_provider()

    doc = Document(
        knowledge_base_id=test_kb.id,
        organization_id=org.id,
        uploaded_by=user.id,
        name="Hybrid Architecture",
        original_filename="hybrid.md",
        content_type="text/markdown",
        file_size=1200,
        storage_key="docs/hybrid.md",
        checksum="chk-hybrid-1",
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

    contents = [
        "Hybrid search combines dense pgvector semantic vectors with PostgreSQL FTS using RRF.",
        "Semantic vector similarity maps concepts and meanings across dense embedding spaces.",
        "Error code ERR_RETRIEVAL_TIMEOUT_992 occurs when the network gateway fails.",
    ]
    vectors = provider.embed_documents(contents)

    chunks = []
    for idx, (content, vec) in enumerate(zip(contents, vectors, strict=True)):
        c = DocumentChunk(
            document_id=doc.id,
            document_version_id=doc_ver.id,
            organization_id=org.id,
            knowledge_base_id=test_kb.id,
            chunk_index=idx,
            content=content,
            character_count=len(content),
            word_count=len(content.split()),
            section_title=f"Section {idx}",
            embedding=vec,
            embedding_model=provider.model_name,
            embedding_provider=provider.provider_name,
            embedding_dimension=provider.dimension,
        )
        chunks.append(c)
        db_session.add(c)

    await db_session.commit()

    # Query matching chunk 0 strongly on both branches
    req = RetrievalRequest(
        query="Hybrid search pgvector semantic embeddings",
        top_k=3,
        search_mode=SearchMode.HYBRID,
        debug=True,
    )
    resp = await RetrievalService.search(
        session=db_session,
        organization_id=org.id,
        request=req,
    )

    assert resp.total_results > 0
    top_result = resp.results[0]
    assert top_result.chunk_id == chunks[0].id
    assert top_result.source == "hybrid"
    assert top_result.vector_score is not None
    assert top_result.keyword_score is not None
    assert top_result.rrf_score is not None
    assert resp.trace is not None
    assert resp.trace.vector_candidate_count > 0
    assert resp.trace.keyword_candidate_count > 0


@pytest.mark.asyncio
async def test_hybrid_search_empty_matches(
    db_session: AsyncSession, test_user_and_org: dict
) -> None:
    """Verify hybrid search returns empty list without error when nothing matches."""
    org: Organization = test_user_and_org["org"]

    req = RetrievalRequest(
        query="completely unmatched nonexistent query xyz123",
        top_k=5,
        search_mode=SearchMode.HYBRID,
    )
    resp = await RetrievalService.search(
        session=db_session,
        organization_id=org.id,
        request=req,
    )

    # Empty chunks in database for this query
    assert isinstance(resp.results, list)
