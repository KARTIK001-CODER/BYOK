"""
Full RAG Request Latency Breakdown Benchmark against PostgreSQL.
Measures cold vs warm requests and every stage of the request path.
"""

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "pytest" in sys.modules:
    del sys.modules["pytest"]

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.tracing import RequestTrace, trace_context
from app.db.session import get_session_factory
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.user import User
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService


def stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0}
    s = sorted(values)
    n = len(s)
    return {
        "p50": round(s[int(n * 0.5)], 2),
        "p95": round(s[min(int(n * 0.95), n - 1)], 2),
        "mean": round(statistics.mean(s), 2),
    }


async def main():
    print("=" * 90)
    print("Full RAG Request Latency Breakdown Benchmark (PostgreSQL)")
    print("=" * 90)

    settings = get_settings()
    session_factory = get_session_factory()
    mock_llm = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_llm)
    rag_service = RAGService()

    # Find test user, org, and KB
    async with session_factory() as session:
        r = await session.execute(
            select(KnowledgeBase.id, KnowledgeBase.organization_id, KnowledgeBase.created_by)
            .order_by(KnowledgeBase.created_at.desc())
            .limit(1)
        )
        row = r.first()
        if not row:
            print("No KB found in DB.")
            return
        kb_id, org_id, user_id = str(row[0]), str(row[1]), str(row[2])

    print(f"Target Org: {org_id}")
    print(f"Target KB:  {kb_id}")
    print(f"Target User:{user_id}")
    print("-" * 90)

    query = "What is the recommended architecture for database connection pooling?"

    # 1. Cold Request (Cache Miss)
    tr_cold = RequestTrace(trace_id="rag-cold")
    req_cold = RAGChatRequest(
        message=query,
        knowledge_base_ids=[kb_id],
        provider="mock",
        model="mock-default",
        search_mode="hybrid",
        parallel_execution=False,
    )
    t0 = time.perf_counter()
    async with session_factory() as session:
        with trace_context(tr_cold):
            resp_cold = await rag_service.generate(
                session=session,
                organization_id=org_id,
                user_id=user_id,
                request=req_cold,
            )
    cold_total_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n[COLD REQUEST - Cache Miss]")
    print(f"  Total Wall-Clock Latency:       {cold_total_ms:.2f} ms")
    print(f"  Conversation Lookup:            {tr_cold.stages.get('conversation_lookup_ms', 0):.2f} ms")
    print(f"  User Message Persistence:       {tr_cold.stages.get('user_message_persist_ms', 0):.2f} ms")
    print(f"  KB Authorization:               {tr_cold.stages.get('retrieval_authz_ms', 0):.2f} ms")
    print(f"  Query Embedding (Inference):    {tr_cold.stages.get('query_embedding_ms', 0):.2f} ms")
    print(f"  Vector SQL Execution:           {tr_cold.stages.get('vector_sql_execution_ms', 0):.2f} ms")
    print(f"  Keyword SQL Execution:          {tr_cold.stages.get('keyword_sql_execution_ms', 0):.2f} ms")
    print(f"  Fusion:                         {tr_cold.stages.get('retrieval_fusion_ms', 0):.2f} ms")
    print(f"  Context Assembly:               {tr_cold.stages.get('context_assembly_ms', 0):.2f} ms")
    print(f"  Prompt Construction:            {tr_cold.stages.get('prompt_construction_ms', 0):.2f} ms")
    print(f"  Pre-LLM Commit:                 {tr_cold.stages.get('pre_llm_commit_ms', 0):.2f} ms")
    print(f"  LLM Execution:                  {tr_cold.stages.get('llm_request_ms', 0):.2f} ms")
    print(f"  Assistant Message Save:         {tr_cold.stages.get('assistant_message_save_ms', 0):.2f} ms")
    print(f"  Post-LLM Commit:                {tr_cold.stages.get('persistence_commit_ms', 0):.2f} ms")

    # 2. Warm Requests (Cache Hits)
    warm_totals = []
    warm_stages = {}

    N_WARM = 10
    print(f"\nRunning {N_WARM} Warm Requests (Sequential Hybrid, Cache Hit)...")

    for i in range(N_WARM):
        tr_warm = RequestTrace(trace_id=f"rag-warm-{i}")
        req_warm = RAGChatRequest(
            message=query,
            conversation_id=resp_cold.conversation_id,  # Multi-turn thread
            knowledge_base_ids=[kb_id],
            provider="mock",
            model="mock-default",
            search_mode="hybrid",
            parallel_execution=False,
        )
        t0 = time.perf_counter()
        async with session_factory() as session:
            with trace_context(tr_warm):
                await rag_service.generate(
                    session=session,
                    organization_id=org_id,
                    user_id=user_id,
                    request=req_warm,
                )
        w_lat = (time.perf_counter() - t0) * 1000.0
        warm_totals.append(w_lat)

        for k, v in tr_warm.stages.items():
            warm_stages.setdefault(k, []).append(v)

    total_stats = stats(warm_totals)
    print("\n" + "=" * 90)
    print(f"{'RAG Pipeline Stage':<35} | {'p50 (ms)':<10} | {'p95 (ms)':<10} | {'% of Total':<10}")
    print("-" * 90)

    stage_display = [
        ("conversation_lookup_ms", "1. Conversation Lookup (DB)"),
        ("user_message_persist_ms", "2. User Message Save & Flush (DB)"),
        ("retrieval_authz_ms", "3. KB Auth Check (DB)"),
        ("query_embedding_ms", "4. Query Embedding (Cache Hit)"),
        ("vector_sql_execution_ms", "5. Vector SQL Search (DB)"),
        ("keyword_sql_execution_ms", "6. Keyword SQL Search (DB)"),
        ("retrieval_fusion_ms", "7. RRF Fusion (In-Memory)"),
        ("context_assembly_ms", "8. Context Assembly (In-Memory)"),
        ("prompt_construction_ms", "9. Prompt Construction (In-Memory)"),
        ("pre_llm_commit_ms", "10. Pre-LLM DB Commit (DB)"),
        ("llm_request_ms", "11. LLM Generation (Mock)"),
        ("citation_construction_ms", "12. Citation Construction"),
        ("assistant_message_save_ms", "13. Assistant Msg Save & Flush (DB)"),
        ("persistence_commit_ms", "14. Final DB Commit (DB)"),
    ]

    tot_p50 = total_stats["p50"]
    db_sum = 0.0
    for key, label in stage_display:
        st = stats(warm_stages.get(key, []))
        pct = (st["p50"] / tot_p50 * 100.0) if tot_p50 > 0 else 0.0
        if "DB" in label:
            db_sum += st["p50"]
        print(f"{label:<35} | {st['p50']:<10.2f} | {st['p95']:<10.2f} | {pct:<9.1f}%")

    print("-" * 90)
    print(f"{'TOTAL REQUEST LATENCY':<35} | {total_stats['p50']:<10.2f} | {total_stats['p95']:<10.2f} | 100.0%")
    print(f"{'CUMULATIVE DATABASE ROUND-TRIPS':<35} | {db_sum:<10.2f} | {'-':<10} | {round(db_sum/tot_p50*100, 1)}%")
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(main())
