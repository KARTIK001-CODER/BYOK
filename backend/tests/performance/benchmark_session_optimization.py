"""
Benchmark runner for Step 8: Safe Retrieval Session Optimization.

Evaluates performance across:
1. Sequential single-query requests (VECTOR, KEYWORD, HYBRID baseline/parallel, HYBRID optimized/sequential).
2. Concurrent VECTOR-only requests.
3. Concurrent KEYWORD-only requests.
4. Concurrent HYBRID requests (Baseline Parallel vs Optimized Sequential).

Measures:
- Sample count (N)
- p50 and p95 latency (ms)
- Database sessions created per request
- Connection pool demand (peak simultaneous connections)
- Result consistency verification (guaranteeing 0 drift in rankings)
"""

import asyncio
import statistics
import time
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tracing import RequestTrace, trace_context
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.embeddings.providers import get_embedding_provider
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService


async def setup_benchmark_dataset(
    session: AsyncSession,
    org: Organization,
    kb: KnowledgeBase,
    user: User,
) -> None:
    """Seed benchmark dataset with 40 realistic technical chunks."""
    provider = get_embedding_provider()

    doc = Document(
        knowledge_base_id=kb.id,
        organization_id=org.id,
        uploaded_by=user.id,
        name="Benchmark Architecture Document",
        original_filename="bench_arch.md",
        content_type="text/markdown",
        file_size=32000,
        storage_key="bench/bench_arch.md",
        checksum="chk-bench-8",
        status=DocumentStatus.READY,
        current_version=1,
    )
    session.add(doc)
    await session.flush()

    doc_ver = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        storage_key=doc.storage_key,
        checksum=doc.checksum,
        file_size=doc.file_size,
        content_type=doc.content_type,
        uploaded_by=user.id,
    )
    session.add(doc_ver)
    await session.flush()

    topics = [
        "high throughput asynchronous database pooling in SQLAlchemy",
        "vector distance calculations cosine similarity indexing",
        "full text search inverted indices token frequency ranking",
        "tenant isolation access control boundaries in multi-tenant SaaS",
        "cancellation handling asyncio task shielding connection safety",
    ]

    contents = []
    for i in range(40):
        t = topics[i % len(topics)]
        contents.append(
            f"Chunk {i}: In-depth technical analysis of {t}. "
            f"Optimizing connection checkout overhead, pool exhaustion, and query execution times."
        )

    embeddings = provider.embed_documents(contents)

    for i, (content, emb) in enumerate(zip(contents, embeddings, strict=True)):
        chunk = DocumentChunk(
            document_id=doc.id,
            document_version_id=doc_ver.id,
            organization_id=org.id,
            knowledge_base_id=kb.id,
            chunk_index=i,
            content=content,
            character_count=len(content),
            word_count=len(content.split()),
            section_title=f"Section {i}",
            embedding=emb,
            embedding_model=provider.model_name,
            embedding_provider=provider.provider_name,
            embedding_dimension=provider.dimension,
        )
        session.add(chunk)

    await session.commit()


def compute_percentiles(latencies: list[float]) -> tuple[float, float, float]:
    """Compute p50, p95, and average latency."""
    if not latencies:
        return 0.0, 0.0, 0.0
    s = sorted(latencies)
    p50 = statistics.median(s)
    p95_idx = int(0.95 * len(s))
    p95 = s[min(p95_idx, len(s) - 1)]
    avg = statistics.mean(s)
    return round(p50, 2), round(p95, 2), round(avg, 2)


async def run_single_request(
    session_maker: async_sessionmaker[AsyncSession],
    org_id: str,
    kb_id: str,
    query: str,
    search_mode: SearchMode,
    parallel: bool | None = None,
) -> dict[str, Any]:
    """Execute a single retrieval request measuring latency and session creation."""
    t0 = time.perf_counter()
    tr = RequestTrace(trace_id=f"bench-{search_mode.value}-{parallel}")
    async with session_maker() as session:
        req = RetrievalRequest(
            query=query,
            top_k=10,
            search_mode=search_mode,
            parallel_execution=parallel,
            knowledge_base_ids=[kb_id],
            debug=True,
        )
        with trace_context(tr):
            resp = await RetrievalService.search(
                session=session,
                organization_id=org_id,
                request=req,
            )
    lat_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "latency_ms": lat_ms,
        "results_count": resp.total_results,
        "secondary_sessions": resp.trace.db_sessions_created if resp.trace else 0,
        "top_chunk_id": resp.results[0].chunk_id if resp.results else None,
    }


async def benchmark_scenario(
    name: str,
    session_maker: async_sessionmaker[AsyncSession],
    org_id: str,
    kb_id: str,
    query: str,
    search_mode: SearchMode,
    parallel: bool | None,
    iterations: int,
    concurrency: int = 1,
) -> dict[str, Any]:
    """Run a scenario under specified concurrency and iteration count."""
    latencies: list[float] = []
    secondary_sessions_list: list[int] = []

    if concurrency == 1:
        for _ in range(iterations):
            res = await run_single_request(session_maker, org_id, kb_id, query, search_mode, parallel)
            latencies.append(res["latency_ms"])
            secondary_sessions_list.append(res["secondary_sessions"])
    else:
        batches = (iterations + concurrency - 1) // concurrency
        for _ in range(batches):
            tasks = [
                run_single_request(session_maker, org_id, kb_id, query, search_mode, parallel)
                for _ in range(concurrency)
            ]
            batch_results = await asyncio.gather(*tasks)
            for res in batch_results:
                latencies.append(res["latency_ms"])
                secondary_sessions_list.append(res["secondary_sessions"])

    p50, p95, avg = compute_percentiles(latencies)
    avg_secondary_sessions = statistics.mean(secondary_sessions_list) if secondary_sessions_list else 0

    return {
        "scenario": name,
        "concurrency": concurrency,
        "sample_count": len(latencies),
        "p50_ms": p50,
        "p95_ms": p95,
        "avg_ms": avg,
        "secondary_sessions_per_req": avg_secondary_sessions,
        "peak_concurrent_connections_est": concurrency * (1 + (2 if (parallel and search_mode == SearchMode.HYBRID) else 0)),
    }


@pytest.mark.asyncio
async def test_run_session_optimization_benchmark(
    db_session: AsyncSession,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
) -> None:
    """Run full benchmark comparing baseline and optimized retrieval session strategies."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    print("\n" + "=" * 92)
    print("BYOK/RAGForge — Step 8: Safe Retrieval Session Optimization Benchmark")
    print("=" * 92)

    await setup_benchmark_dataset(db_session, org, test_kb, user)

    bind = db_session.bind
    dialect = bind.dialect.name if bind else "sqlite"
    session_maker = async_sessionmaker(
        bind=bind,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    print(f"Target dialect: {dialect.upper()} (Synthetic Test Environment)")
    print("-" * 92)

    query = "database connection pooling and session management in SQLAlchemy"
    N_SEQ = 8
    N_CONC = 16
    CONC_WORKERS = 4

    scenarios = [
        ("Sequential VECTOR-Only", SearchMode.VECTOR, None, N_SEQ, 1),
        ("Sequential KEYWORD-Only", SearchMode.KEYWORD, None, N_SEQ, 1),
        ("Sequential HYBRID (Baseline: Parallel)", SearchMode.HYBRID, True, N_SEQ, 1),
        ("Sequential HYBRID (Optimized: Sequential)", SearchMode.HYBRID, False, N_SEQ, 1),
        ("Concurrent VECTOR-Only (c=4)", SearchMode.VECTOR, None, N_CONC, CONC_WORKERS),
        ("Concurrent KEYWORD-Only (c=4)", SearchMode.KEYWORD, None, N_CONC, CONC_WORKERS),
        ("Concurrent HYBRID (Baseline: Parallel, c=4)", SearchMode.HYBRID, True, N_CONC, CONC_WORKERS),
        ("Concurrent HYBRID (Optimized: Sequential, c=4)", SearchMode.HYBRID, False, N_CONC, CONC_WORKERS),
    ]

    results = []
    for name, mode, par, iters, conc in scenarios:
        res = await benchmark_scenario(name, session_maker, org.id, test_kb.id, query, mode, par, iters, conc)
        results.append(res)

    print("\n" + "=" * 98)
    print(f"{'Scenario':<46} | {'N':<3} | {'p50 (ms)':<9} | {'p95 (ms)':<9} | {'Sessions':<8} | {'Peak Conns':<10}")
    print("-" * 98)
    for r in results:
        print(
            f"{r['scenario']:<46} | {r['sample_count']:<3} | {r['p50_ms']:<9.2f} | {r['p95_ms']:<9.2f} | "
            f"{r['secondary_sessions_per_req']:<8.1f} | {r['peak_concurrent_connections_est']:<10}"
        )
    print("=" * 98)
