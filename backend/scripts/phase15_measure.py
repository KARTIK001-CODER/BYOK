"""
Run local Phase 1.5 measurements using in-memory SQLite + mock provider.
Captures cold vs warm embedding, retrieval breakdown, vector/keyword, fusion, context, prompt, persistence.
Outputs JSON for report.

We reuse the tracing RequestTrace infrastructure directly.
"""
import asyncio
import json
import statistics
import sys
import time
import os
import psutil
from pathlib import Path

# Ensure backend app is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Need to set pytest marker BEFORE importing models so sqlite fallback triggers (see document_chunk.py:154)
sys.modules["pytest"] = sys.modules.get("pytest") or type(sys)("pytest")

# Force pytest-like env to avoid arxiv but also allow embedding
# We want to test cold/warm directly.

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.db.base import Base
from app.models.user import User
from app.models.organization import Organization
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document, DocumentStatus
from app.models.document_version import DocumentVersion
from app.models.document_chunk import DocumentChunk
from app.services.embeddings.providers import get_embedding_provider
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.core.tracing import RequestTrace
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService

async def setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    return engine, factory

async def seed(factory):
    async with factory() as session:
        from app.services.auth.password import PasswordService
        ph = PasswordService.hash("StrongPassword123!")
        user = User(email="testuser@example.com", password_hash=ph, full_name="Test", is_active=True, is_verified=True)
        session.add(user)
        await session.flush()
        org = Organization(name="Ws", slug="ws")
        session.add(org)
        await session.flush()
        mem = OrganizationMembership(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER)
        session.add(mem)
        await session.flush()
        kb = KnowledgeBase(organization_id=org.id, name="Research Docs", slug="research-docs", description="docs", created_by=user.id, is_active=True)
        session.add(kb)
        await session.flush()
        # Create document with chunks
        doc = Document(
            knowledge_base_id=kb.id, organization_id=org.id, uploaded_by=user.id,
            name="Doc1", original_filename="doc1.md", content_type="text/markdown",
            file_size=1000, storage_key="k1", checksum="chk1", status=DocumentStatus.READY, current_version=1
        )
        session.add(doc)
        await session.flush()
        ver = DocumentVersion(document_id=doc.id, version_number=1, storage_key=doc.storage_key, checksum=doc.checksum, file_size=doc.file_size, content_type=doc.content_type, uploaded_by=user.id)
        session.add(ver)
        await session.flush()

        contents = [
            "Hybrid search combines dense pgvector semantic vectors with PostgreSQL FTS using RRF.",
            "RAGForge uses JWT access tokens and rotating refresh tokens. Tokens are revoked on logout.",
            "PostgreSQL pgvector HNSW index accelerates vector search with cosine distance.",
            "Full-text search uses GIN index on tsvector with plainto_tsquery and ts_rank_cd.",
            "Chunking splits documents into overlapping windows with provenance metadata.",
            "Embedding model BAAI/bge-small-en-v1.5 produces 384-dim vectors for semantic search.",
            "LLM providers include Groq, OpenAI, Gemini and mock for testing.",
            "Retrieval fuses vector and keyword candidates via Reciprocal Rank Fusion (RRF).",
        ]
        provider = get_embedding_provider()
        vectors = provider.embed_documents(contents)
        for idx, (c, v) in enumerate(zip(contents, vectors)):
            chunk = DocumentChunk(
                document_id=doc.id, document_version_id=ver.id,
                organization_id=org.id, knowledge_base_id=kb.id,
                chunk_index=idx, content=c, character_count=len(c), word_count=len(c.split()),
                section_title=f"Section {idx}", embedding=v,
                embedding_model=provider.model_name, embedding_provider=provider.provider_name,
                embedding_dimension=provider.dimension,
            )
            session.add(chunk)
        await session.commit()
        await session.refresh(kb)
        return {"user": user, "org": org, "kb": kb}

async def measure_embedding_cold_warm():
    # Clear singleton to simulate cold
    import app.services.embeddings.providers.local as local_mod
    # Force cold by resetting global
    local_mod._GLOBAL_LOCAL_EMBEDDING_MODEL = None

    # Cold
    t0 = time.perf_counter()
    prov = get_embedding_provider()
    cold_init = (time.perf_counter() - t0)*1000
    t1 = time.perf_counter()
    vec = await asyncio.to_thread(prov.embed_query, "What is pgvector?")
    cold_infer = (time.perf_counter() - t1)*1000

    # Warm
    t2 = time.perf_counter()
    prov2 = get_embedding_provider()
    warm_init = (time.perf_counter() - t2)*1000
    t3 = time.perf_counter()
    vec2 = await asyncio.to_thread(prov2.embed_query, "What is pgvector?")
    warm_infer = (time.perf_counter() - t3)*1000

    return {
        "cold_init_ms": round(cold_init,2),
        "cold_infer_ms": round(cold_infer,2),
        "cold_total_ms": round(cold_init+cold_infer,2),
        "warm_init_ms": round(warm_init,2),
        "warm_infer_ms": round(warm_infer,2),
        "warm_total_ms": round(warm_init+warm_infer,2),
        "is_singleton": prov._model is prov2._model,
        "dimension": prov.dimension,
        "model": prov.model_name,
    }

async def measure_retrieval(factory, org_id):
    # Test vector, keyword, hybrid with debug trace
    results = {}
    for mode in ["vector", "keyword", "hybrid"]:
        async with factory() as session:
            trace = RequestTrace(trace_id=f"trace-{mode}", request_id=f"req-{mode}")
            # monkey-patch current trace via contextvar
            from app.core.tracing import set_current_trace
            tok = set_current_trace(trace)
            req = RetrievalRequest(query="What is pgvector HNSW?", top_k=5, candidate_k=30, search_mode=SearchMode(mode), debug=True)
            t0 = time.perf_counter()
            resp = await RetrievalService.search(session=session, organization_id=org_id, request=req)
            total = (time.perf_counter()-t0)*1000
            # capture trace stages
            results[mode] = {
                "total_ms": round(total,2),
                "trace": resp.trace.model_dump() if resp.trace else None,
                "stages": trace.to_dict(),
                "results": len(resp.results),
            }
            set_current_trace(None)
    return results

async def measure_rag(factory, user, org, kb):
    LLMProviderFactory.set_mock_provider(MockLLMProvider())
    rag = RAGService()
    timings = []
    # warm up once
    async with factory() as session:
        from app.core.tracing import set_current_trace
        trace = RequestTrace(trace_id="warmup", request_id="warmup")
        tok = set_current_trace(trace)
        req = RAGChatRequest(message="What is pgvector?", knowledge_base_ids=[kb.id], provider="mock", model="mock-default", top_k=5, search_mode="hybrid")
        # warmup not measured
        await rag.generate(session=session, organization_id=org.id, user_id=user.id, request=req)
        set_current_trace(None)

    # Now measure 10 warm runs
    for i in range(10):
        async with factory() as session:
            from app.core.tracing import set_current_trace
            trace = RequestTrace(trace_id=f"rag-{i}", request_id=f"rag-{i}")
            tok = set_current_trace(trace)
            req = RAGChatRequest(message="Explain hybrid search and RRF", knowledge_base_ids=[kb.id], provider="mock", model="mock-default", top_k=5, search_mode="hybrid")
            t0 = time.perf_counter()
            resp = await rag.generate(session=session, organization_id=org.id, user_id=user.id, request=req)
            total = (time.perf_counter()-t0)*1000
            data = trace.to_dict()
            timings.append({
                "total_ms": round(total,2),
                "retrieval_ms": resp.retrieval.latency_ms,
                "stages": data["stages"],
                "timestamps": data["timestamps"],
                "counters": data["counters"],
            })
            set_current_trace(None)
            await asyncio.sleep(0.05)
    return timings

async def measure_provider_direct():
    init_t0 = time.perf_counter()
    provider, model = LLMProviderFactory.create(provider="mock")
    init_ms = (time.perf_counter()-init_t0)*1000
    from app.services.llm.base import LLMRequest, LLMMessage
    req = LLMRequest(provider=provider.name, model=model, messages=[LLMMessage(role="user", content="Hello")], stream=False)
    t0 = time.perf_counter()
    resp = await provider.generate(req)
    gen_ms = (time.perf_counter()-t0)*1000
    # streaming
    req_s = LLMRequest(provider=provider.name, model=model, messages=[LLMMessage(role="user", content="Hello")], stream=True)
    s_t0 = time.perf_counter()
    first = None
    cnt=0
    full=""
    async for chunk in provider.stream(req_s):
        if chunk.delta:
            if first is None:
                first = (time.perf_counter()-s_t0)*1000
            full+=chunk.delta
            cnt+=1
    total_s = (time.perf_counter()-s_t0)*1000
    return {
        "provider_init_ms": round(init_ms,2),
        "generate_ms": round(gen_ms,2),
        "stream_ttft_ms": round(first or 0,2),
        "stream_total_ms": round(total_s,2),
        "chunks": cnt,
        "chars": len(full),
        "is_mock_no_sleep": True,
    }

async def main():
    print("Setting up DB...")
    engine, factory = await setup_db()
    seed_data = await seed(factory)
    user = seed_data["user"]
    org = seed_data["org"]
    kb = seed_data["kb"]
    print(f"Seeded org={org.id} kb={kb.id}")

    emb = await measure_embedding_cold_warm()
    print("Embedding:", emb)

    retr = await measure_retrieval(factory, org.id)
    print("Retrieval:", json.dumps(retr, indent=2))

    rag_timings = await measure_rag(factory, user, org, kb)
    print("RAG timings sample:", rag_timings[0])

    provider_diag = await measure_provider_direct()
    print("Provider:", provider_diag)

    # System resources
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    pool_info = "sqlite - no pool"

    # Aggregate warm stats
    totals = [t["total_ms"] for t in rag_timings]
    rets = [t["retrieval_ms"] for t in rag_timings]
    agg = {
        "p50": round(sorted(totals)[len(totals)//2],2),
        "p95": round(sorted(totals)[int(len(totals)*0.95)],2),
        "avg": round(statistics.mean(totals),2),
        "min": round(min(totals),2),
        "max": round(max(totals),2),
        "p50_retrieval": round(sorted(rets)[len(rets)//2],2),
        "avg_retrieval": round(statistics.mean(rets),2),
    }

    report = {
        "embedding": emb,
        "retrieval": retr,
        "rag_warm": {"agg": agg, "details": rag_timings},
        "provider_direct": provider_diag,
        "system": {"cpu_percent": cpu, "mem_percent": mem, "pool": pool_info},
    }

    out = Path(__file__).parent.parent / "docs" / "PHASE_1_5_MEASUREMENTS.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Written to {out}")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
