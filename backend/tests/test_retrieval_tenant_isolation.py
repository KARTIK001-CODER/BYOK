import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.services.embeddings.providers import get_embedding_provider
from app.services.retrieval.errors import RetrievalErrorCode, RetrievalException
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService


@pytest.mark.asyncio
async def test_retrieval_multi_tenant_isolation_strictly_enforced(
    db_session: AsyncSession, test_user_and_org: dict
) -> None:
    """
    CRITICAL SECURITY TEST:
    Org A and Org B both store documents.
    User A queries for secrets/content that exists ONLY in Org B's documents.
    Org B chunks must NEVER be retrieved for Org A, regardless of search mode.
    """
    user_a: User = test_user_and_org["user"]
    org_a: Organization = test_user_and_org["org"]
    provider = get_embedding_provider()

    # 1. Create Org B, User B, KB B
    user_b = User(
        email="user_b@competitor.com",
        password_hash="fakehash",
        full_name="User B Competitor",
    )
    org_b = Organization(name="Competitor Corp", slug="competitor-corp")
    db_session.add_all([user_b, org_b])
    await db_session.flush()

    mem_b = OrganizationMembership(
        organization_id=org_b.id,
        user_id=user_b.id,
        role=OrganizationRole.OWNER,
    )
    kb_b = KnowledgeBase(
        organization_id=org_b.id,
        name="Confidential Trade Secrets",
        slug="confidential-secrets",
        created_by=user_b.id,
    )
    kb_a = KnowledgeBase(
        organization_id=org_a.id,
        name="Org A Public KB",
        slug="org-a-public",
        created_by=user_a.id,
    )
    db_session.add_all([mem_b, kb_b, kb_a])
    await db_session.flush()

    # 2. Add confidential document to Org B
    secret_text = "PROJECT_TITAN_SECRET_API_KEY = sk-secret-titan-9982741104818481"
    doc_b = Document(
        knowledge_base_id=kb_b.id,
        organization_id=org_b.id,
        uploaded_by=user_b.id,
        name="Org B Confidential Keys",
        original_filename="keys.txt",
        content_type="text/plain",
        file_size=len(secret_text),
        storage_key="org_b/keys.txt",
        checksum="chk-org-b",
        status=DocumentStatus.READY,
        current_version=1,
    )
    db_session.add(doc_b)
    await db_session.flush()

    ver_b = DocumentVersion(
        document_id=doc_b.id,
        version_number=1,
        storage_key=doc_b.storage_key,
        checksum=doc_b.checksum,
        file_size=doc_b.file_size,
        content_type=doc_b.content_type,
        uploaded_by=user_b.id,
    )
    db_session.add(ver_b)
    await db_session.flush()

    emb_b = provider.embed_documents([secret_text])[0]
    chunk_b = DocumentChunk(
        document_id=doc_b.id,
        document_version_id=ver_b.id,
        organization_id=org_b.id,
        knowledge_base_id=kb_b.id,
        chunk_index=0,
        content=secret_text,
        character_count=len(secret_text),
        word_count=len(secret_text.split()),
        embedding=emb_b,
    )
    db_session.add(chunk_b)

    # 3. Add regular document to Org A
    org_a_text = "Welcome to Organization A documentation and knowledge repository."
    doc_a = Document(
        knowledge_base_id=kb_a.id,
        organization_id=org_a.id,
        uploaded_by=user_a.id,
        name="Org A Welcome",
        original_filename="welcome.txt",
        content_type="text/plain",
        file_size=len(org_a_text),
        storage_key="org_a/welcome.txt",
        checksum="chk-org-a",
        status=DocumentStatus.READY,
        current_version=1,
    )
    db_session.add(doc_a)
    await db_session.flush()

    ver_a = DocumentVersion(
        document_id=doc_a.id,
        version_number=1,
        storage_key=doc_a.storage_key,
        checksum=doc_a.checksum,
        file_size=doc_a.file_size,
        content_type=doc_a.content_type,
        uploaded_by=user_a.id,
    )
    db_session.add(ver_a)
    await db_session.flush()

    emb_a = provider.embed_documents([org_a_text])[0]
    chunk_a = DocumentChunk(
        document_id=doc_a.id,
        document_version_id=ver_a.id,
        organization_id=org_a.id,
        knowledge_base_id=kb_a.id,
        chunk_index=0,
        content=org_a_text,
        character_count=len(org_a_text),
        word_count=len(org_a_text.split()),
        embedding=emb_a,
    )
    db_session.add(chunk_a)
    await db_session.commit()

    # 4. User A queries specifically for Org B's secret text
    modes = [SearchMode.VECTOR, SearchMode.KEYWORD, SearchMode.HYBRID]
    for mode in modes:
        req = RetrievalRequest(
            query="PROJECT_TITAN_SECRET_API_KEY sk-secret-titan",
            search_mode=mode,
            top_k=10,
        )
        resp = await RetrievalService.search(
            session=db_session,
            organization_id=org_a.id,
            request=req,
        )

        for result in resp.results:
            assert result.chunk_id != chunk_b.id
            assert "PROJECT_TITAN_SECRET_API_KEY" not in result.content
            assert result.provenance.organization_id == org_a.id

    # 5. User A tries to explicitly target Org B's knowledge base
    unauth_req = RetrievalRequest(
        query="trade secrets",
        knowledge_base_ids=[kb_b.id],
        search_mode=SearchMode.HYBRID,
    )
    with pytest.raises(RetrievalException) as exc_info:
        await RetrievalService.search(
            session=db_session,
            organization_id=org_a.id,
            request=unauth_req,
        )
    assert exc_info.value.code == RetrievalErrorCode.UNAUTHORIZED_KNOWLEDGE_BASE.value
    assert exc_info.value.status_code == 403
