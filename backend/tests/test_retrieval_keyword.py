import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.retrieval.keyword import KeywordRetriever
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService


@pytest.mark.asyncio
async def test_keyword_retriever_exact_and_technical_terms(
    db_session: AsyncSession, test_user_and_org: dict, test_kb: KnowledgeBase
) -> None:
    """Verify keyword retriever finds exact terms, codes, and technical phrases."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    doc = Document(
        knowledge_base_id=test_kb.id,
        organization_id=org.id,
        uploaded_by=user.id,
        name="Security Policy",
        original_filename="security.md",
        content_type="text/markdown",
        file_size=500,
        storage_key="docs/security.md",
        checksum="chk-sec-1",
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

    chunk1 = DocumentChunk(
        document_id=doc.id,
        document_version_id=doc_ver.id,
        organization_id=org.id,
        knowledge_base_id=test_kb.id,
        chunk_index=0,
        content="Argon2id password hashing parameters include m=65536, t=3, p=4.",
        character_count=64,
        word_count=8,
        section_title="Password Hashing",
    )
    chunk2 = DocumentChunk(
        document_id=doc.id,
        document_version_id=doc_ver.id,
        organization_id=org.id,
        knowledge_base_id=test_kb.id,
        chunk_index=1,
        content="Cross-Origin Resource Sharing (CORS) origins must be strictly validated.",
        character_count=73,
        word_count=9,
        section_title="CORS Policy",
    )
    db_session.add_all([chunk1, chunk2])
    await db_session.commit()

    # 1. Search for technical term 'Argon2id'
    candidates = await KeywordRetriever.retrieve(
        session=db_session,
        organization_id=org.id,
        query="Argon2id hashing",
        candidate_k=10,
    )

    assert len(candidates) >= 1
    assert candidates[0].chunk.id == chunk1.id
    assert candidates[0].source == "keyword"
    assert candidates[0].score > 0.0

    # 2. Search via RetrievalService
    req = RetrievalRequest(
        query="CORS origins",
        search_mode=SearchMode.KEYWORD,
        top_k=5,
    )
    resp = await RetrievalService.search(
        session=db_session,
        organization_id=org.id,
        request=req,
    )

    assert resp.total_results >= 1
    assert resp.results[0].chunk_id == chunk2.id
    assert resp.results[0].keyword_score is not None


@pytest.mark.asyncio
async def test_keyword_retriever_no_matches(
    db_session: AsyncSession, test_user_and_org: dict
) -> None:
    """Verify empty result set when no keywords match."""
    org: Organization = test_user_and_org["org"]

    req = RetrievalRequest(
        query="nonexistent_xylophone_quux_keyword",
        search_mode=SearchMode.KEYWORD,
        top_k=5,
    )
    resp = await RetrievalService.search(
        session=db_session,
        organization_id=org.id,
        request=req,
    )

    assert resp.total_results == 0
    assert len(resp.results) == 0
