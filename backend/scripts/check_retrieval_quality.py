"""Retrieval quality check — Hit@1, Hit@3, Hit@5, MRR."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules["pytest"] = sys.modules.get("pytest") or type(sys)("pytest")
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.db.base import Base
from app.models.document_chunk import DocumentChunk
from app.models.document import Document, DocumentStatus
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.user import User
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService
from app.services.embeddings.providers import get_embedding_provider

# Fixed evaluation set — 10 queries with expected chunk content substring
EVAL_SET = [
    ("What is HNSW?", "HNSW"),
    ("How does pgvector work?", "pgvector"),
    ("Explain RRF fusion", "RRF"),
    ("JWT tokens", "JWT"),
    ("GIN index tsvector", "GIN"),
    ("Chunking strategy", "Chunking"),
    ("Embedding model dimension", "384"),
    ("LLM provider groq", "Groq"),
    ("Knowledge base filter", "Knowledge Base"),
    ("Provenance metadata", "provenance"),
]

async def setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory

async def seed(factory):
    async with factory() as session:
        from app.services.auth.password import PasswordService
        ph = PasswordService.hash("StrongPassword123!")
        user = User(email="testuser@example.com", password_hash=ph, full_name="Test", is_active=True, is_verified=True)
        session.add(user); await session.flush()
        org = Organization(name="Ws", slug="ws"); session.add(org); await session.flush()
        mem = OrganizationMembership(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER); session.add(mem); await session.flush()
        kb = KnowledgeBase(organization_id=org.id, name="Research Docs", slug="research-docs", description="docs", created_by=user.id, is_active=True); session.add(kb); await session.flush()
        doc = Document(knowledge_base_id=kb.id, organization_id=org.id, uploaded_by=user.id, name="Doc1", original_filename="doc1.md", content_type="text/markdown", file_size=1000, storage_key="k1", checksum="chk1", status=DocumentStatus.READY, current_version=1); session.add(doc); await session.flush()
        ver = DocumentVersion(document_id=doc.id, version_number=1, storage_key=doc.storage_key, checksum=doc.checksum, file_size=doc.file_size, content_type=doc.content_type, uploaded_by=user.id); session.add(ver); await session.flush()
        contents = [
            "Hybrid search combines dense pgvector semantic vectors with PostgreSQL FTS using RRF.",
            "RAGForge uses JWT access tokens and rotating refresh tokens. Tokens are revoked on logout.",
            "PostgreSQL pgvector HNSW index accelerates vector search with cosine distance and m=16 ef_construction=64.",
            "Full-text search uses GIN index on tsvector with plainto_tsquery and ts_rank_cd.",
            "Chunking splits documents into overlapping windows with provenance metadata and character_count.",
            "Embedding model BAAI/bge-small-en-v1.5 produces 384-dimensional vectors for semantic search.",
            "LLM providers include Groq, OpenAI, Gemini and mock for testing with 4096 max tokens.",
            "Knowledge Base filtering uses organization_id and knowledge_base_id B-tree indexes.",
            "Provenance tracks organization_id, knowledge_base_id, document_id, chunk_index, page_number.",
            "Arxiv fallback is bounded 2s timeout and disabled by default to avoid blocking chat.",
        ]
        prov = get_embedding_provider()
        vecs = prov.embed_documents(contents)
        for idx, (c, v) in enumerate(zip(contents, vecs)):
            ch = DocumentChunk(document_id=doc.id, document_version_id=ver.id, organization_id=org.id, knowledge_base_id=kb.id, chunk_index=idx, content=c, character_count=len(c), word_count=len(c.split()), section_title=f"Section {idx}", embedding=v, embedding_model=prov.model_name, embedding_provider=prov.provider_name, embedding_dimension=prov.dimension)
            session.add(ch)
        await session.commit()
        return org, kb

async def evaluate():
    engine, factory = await setup()
    org, kb = await seed(factory)
    hits1=hits3=hits5=0
    mrr=0.0
    for query, expected in EVAL_SET:
        async with factory() as session:
            req = RetrievalRequest(query=query, top_k=5, candidate_k=30, search_mode=SearchMode.HYBRID, debug=False)
            resp = await RetrievalService.search(session=session, organization_id=org.id, request=req)
            # check if expected substring in any result
            ranked_contents = [r.content for r in resp.results]
            found_rank = None
            for rank, content in enumerate(ranked_contents, start=1):
                if expected.lower() in content.lower():
                    found_rank = rank
                    break
            if found_rank:
                if found_rank <=1: hits1+=1
                if found_rank <=3: hits3+=1
                if found_rank <=5: hits5+=1
                mrr += 1.0/found_rank
            print(f"Q: {query:30s} expected '{expected:15s}' -> rank {found_rank} (results {len(ranked_contents)})")
    total=len(EVAL_SET)
    print(f"\nHit@1: {hits1}/{total} = {hits1/total:.2f}")
    print(f"Hit@3: {hits3}/{total} = {hits3/total:.2f}")
    print(f"Hit@5: {hits5}/{total} = {hits5/total:.2f}")
    print(f"MRR: {mrr/total:.3f}")
    await engine.dispose()
    return {"hit1": hits1/total, "hit3": hits3/total, "hit5": hits5/total, "mrr": mrr/total}

if __name__=="__main__":
    asyncio.run(evaluate())
