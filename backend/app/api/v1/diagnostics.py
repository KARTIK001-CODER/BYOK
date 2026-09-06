"""Phase 1.5 diagnostics: pool, embedding cold/warm, query plans, provider benchmark."""
import asyncio
import time
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.config import get_settings
from app.db.session import get_db, get_engine, get_pool_status
from app.models.user import User
from app.services.embeddings.providers import get_embedding_provider
from app.services.llm.base import LLMRequest, LLMMessage
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider

logger = logging.getLogger("app.api.diagnostics")

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics & Tracing"])


@router.get("/pool", summary="Database pool status")
async def pool_status(_: User = Depends(get_current_active_user)):
    engine = get_engine()
    settings = get_settings()
    return {
        "pool": get_pool_status(),
        "config": {
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_timeout": settings.DB_POOL_TIMEOUT,
            "pool_recycle": 300,
            "pool_pre_ping": True,
        },
        "dialect": engine.dialect.name,
        "url_host": settings.DATABASE_URL.split("@")[-1].split("/")[0] if "@" in settings.DATABASE_URL else "unknown",
    }


@router.get("/embedding", summary="Embedding cold vs warm benchmark")
async def embedding_benchmark(
    query: str = "What is the capital of France?",
    _: User = Depends(get_current_active_user),
):
    # cold vs warm measured via provider internals — we explicitly time init+infer
    t0 = time.perf_counter()
    provider = get_embedding_provider()
    init_ms = (time.perf_counter() - t0) * 1000.0  # init already timed inside provider but we double-measure

    infer_t0 = time.perf_counter()
    vec = await asyncio.to_thread(provider.embed_query, query)
    infer_ms = (time.perf_counter() - infer_t0) * 1000.0

    # warm second call
    warm_t0 = time.perf_counter()
    provider2 = get_embedding_provider()
    warm_init_ms = (time.perf_counter() - warm_t0) * 1000.0
    warm_infer_t0 = time.perf_counter()
    vec2 = await asyncio.to_thread(provider2.embed_query, query)
    warm_infer_ms = (time.perf_counter() - warm_infer_t0) * 1000.0

    return {
        "query": query,
        "dimension": provider.dimension,
        "model": provider.model_name,
        "cold": {"init_ms": round(init_ms, 2), "infer_ms": round(infer_ms, 2), "total_ms": round(init_ms + infer_ms, 2)},
        "warm": {"init_ms": round(warm_init_ms, 2), "infer_ms": round(warm_infer_ms, 2), "total_ms": round(warm_init_ms + warm_infer_ms, 2)},
        "vector_sample": vec[:3],
        "singleton_is_same_model": provider._model is provider2._model,
    }


@router.get("/provider", summary="Direct provider benchmark (bypass RAG)")
async def provider_benchmark(
    provider_name: str = "mock",
    _: User = Depends(get_current_active_user),
):
    # Measures provider init + first token + full generation isolated from retrieval
    init_t0 = time.perf_counter()
    provider, model = LLMProviderFactory.create(provider=provider_name)
    init_ms = (time.perf_counter() - init_t0) * 1000.0

    messages = [LLMMessage(role="user", content="Hello, say a short greeting.")]

    # non-streaming
    req = LLMRequest(provider=provider.name, model=model, messages=messages, stream=False)
    gen_t0 = time.perf_counter()
    resp = await provider.generate(req)
    gen_ms = (time.perf_counter() - gen_t0) * 1000.0

    # streaming: TTFT + total
    req_s = LLMRequest(provider=provider.name, model=model, messages=messages, stream=True)
    stream_t0 = time.perf_counter()
    first_token_ms = None
    chunk_count = 0
    full = ""
    async for chunk in provider.stream(req_s):
        if chunk.delta:
            if first_token_ms is None:
                first_token_ms = (time.perf_counter() - stream_t0) * 1000.0
            full += chunk.delta
            chunk_count += 1
    total_stream_ms = (time.perf_counter() - stream_t0) * 1000.0

    return {
        "provider": provider.name,
        "model": model,
        "provider_init_ms": round(init_ms, 2),
        "generate_ms": round(gen_ms, 2),
        "stream_ttft_ms": round(first_token_ms or 0, 2),
        "stream_total_ms": round(total_stream_ms, 2),
        "stream_chunks": chunk_count,
        "response_chars": len(resp.content),
        "stream_chars": len(full),
        "is_mock": isinstance(provider, MockLLMProvider),
        "mock_has_artificial_sleep": False,  # verified: MockLLMProvider yields without asyncio.sleep
    }


@router.get("/query-plan", summary="EXPLAIN ANALYZE for vector and keyword queries")
async def query_plan(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    """Run EXPLAIN (without ANALYZE to avoid needing real vectors) for index verification."""
    results = {}
    dialect = session.bind.dialect.name if session.bind else "unknown"
    if dialect != "postgresql":
        return {"dialect": dialect, "note": "Query plans only available on PostgreSQL"}

    # Check existence of indexes
    idx_stmt = text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'document_chunks'
          AND indexname IN ('ix_document_chunks_embedding','ix_document_chunks_search_vector');
    """)
    r = await session.execute(idx_stmt)
    indexes = [{"name": row[0], "def": row[1]} for row in r.all()]
    results["indexes"] = indexes

    # Vector: check index type
    try:
        vec_idx = text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename='document_chunks' AND indexdef ILIKE '%hnsw%';
        """)
        r2 = await session.execute(vec_idx)
        results["vector_hnsw_index"] = [{"name": row[0], "def": row[1]} for row in r2.all()]
    except Exception as e:
        results["vector_hnsw_error"] = str(e)

    # GIN index check
    try:
        gin_idx = text("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename='document_chunks' AND indexdef ILIKE '%gin%';
        """)
        r3 = await session.execute(gin_idx)
        results["keyword_gin_index"] = [{"name": row[0], "def": row[1]} for row in r3.all()]
    except Exception as e:
        results["keyword_gin_error"] = str(e)

    # Row counts
    try:
        cnt = await session.execute(text("SELECT count(*) FROM document_chunks;"))
        results["total_chunks"] = cnt.scalar_one()
        cnt_neon = await session.execute(text("SELECT count(*) FROM document_chunks WHERE embedding IS NOT NULL;"))
        results["embedded_chunks"] = cnt_neon.scalar_one()
    except Exception as e:
        results["count_error"] = str(e)

    # EXPLAIN (cost only, no ANALYZE to avoid heavy scan)
    try:
        expl_vec = await session.execute(text("""
            EXPLAIN (COSTS true, FORMAT JSON)
            SELECT id, embedding <=> (SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1) AS distance
            FROM document_chunks
            WHERE embedding IS NOT NULL
            ORDER BY distance
            LIMIT 10;
        """))
        results["vector_explain"] = expl_vec.scalar_one()
    except Exception as e:
        results["vector_explain_error"] = str(e)

    try:
        expl_kw = await session.execute(text("""
            EXPLAIN (COSTS true, FORMAT JSON)
            SELECT id FROM document_chunks
            WHERE search_vector @@ plainto_tsquery('english','test query')
            LIMIT 10;
        """))
        results["keyword_explain"] = expl_kw.scalar_one()
    except Exception as e:
        results["keyword_explain_error"] = str(e)

    return results
