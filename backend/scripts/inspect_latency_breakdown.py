"""
Inspect PostgreSQL Query Plans with EXPLAIN (ANALYZE, BUFFERS) and Disaggregate Network vs DB Time.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "pytest" in sys.modules:
    del sys.modules["pytest"]

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine
from app.services.embeddings.providers import get_embedding_provider


async def main():
    print("=" * 80)
    print("PostgreSQL Server-Side Execution Time vs Network Round-Trip Analysis")
    print("=" * 80)

    settings = get_settings()
    engine = get_engine()
    provider = get_embedding_provider()

    dummy_query = "database architecture connection pooling and performance"
    vec = provider.embed_query(dummy_query)
    vec_str = "[" + ",".join(str(round(x, 6)) for x in vec) + "]"

    async with engine.connect() as conn:
        # Measure ping / SELECT 1
        pings = []
        for _ in range(5):
            t0 = time.perf_counter()
            await conn.execute(text("SELECT 1;"))
            pings.append((time.perf_counter() - t0) * 1000.0)

        print("Network Ping (SELECT 1) over TLS to Neon AWS us-east-2:")
        print(
            f"  min: {min(pings):.2f} ms | p50: {pings[len(pings) // 2]:.2f} ms | max: {max(pings):.2f} ms"
        )
        print("-" * 80)

        # Find target KB
        r_kb = await conn.execute(
            text("SELECT id, organization_id, name FROM knowledge_bases LIMIT 1;")
        )
        kb_row = r_kb.fetchone()
        if not kb_row:
            print("No KB found.")
            return
        kb_id, org_id, kb_name = str(kb_row[0]), str(kb_row[1]), str(kb_row[2])
        print(f"Target KB: '{kb_name}' (ID: {kb_id}, Org: {org_id})")

        # 1. Vector Search Query with EXPLAIN (ANALYZE, BUFFERS)
        vec_sql = f"""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        SELECT document_chunks.id, documents.name,
               (document_chunks.embedding <=> '{vec_str}'::vector) AS distance
        FROM document_chunks
        JOIN documents ON document_chunks.document_id = documents.id
        WHERE document_chunks.organization_id = '{org_id}'
          AND document_chunks.knowledge_base_id = '{kb_id}'
          AND document_chunks.embedding IS NOT NULL
        ORDER BY distance ASC
        LIMIT 50;
        """
        t0 = time.perf_counter()
        res_vec = await conn.execute(text(vec_sql))
        client_vec_ms = (time.perf_counter() - t0) * 1000.0
        plan_vec = res_vec.scalar()

        server_vec_time = plan_vec[0]["Execution Time"]
        planning_vec_time = plan_vec[0]["Planning Time"]

        print("\nVector Query Performance:")
        print(f"  Client-measured round trip:   {client_vec_ms:.2f} ms")
        print(f"  Server-side planning time:    {planning_vec_time:.2f} ms")
        print(f"  Server-side execution time:   {server_vec_time:.2f} ms")
        print(f"  Network / TLS overhead delta: {client_vec_ms - server_vec_time:.2f} ms")
        print(f"  Server Plan Root Node:        {plan_vec[0]['Plan']['Node Type']}")

        # 2. Keyword Search Query with EXPLAIN (ANALYZE, BUFFERS)
        kw_sql = f"""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        SELECT document_chunks.id, documents.name,
               ts_rank_cd(document_chunks.search_vector, plainto_tsquery('english', '{dummy_query}')) AS rank_score
        FROM document_chunks
        JOIN documents ON document_chunks.document_id = documents.id
        WHERE document_chunks.organization_id = '{org_id}'
          AND document_chunks.knowledge_base_id = '{kb_id}'
          AND document_chunks.search_vector @@ plainto_tsquery('english', '{dummy_query}')
        ORDER BY rank_score DESC
        LIMIT 50;
        """
        t0 = time.perf_counter()
        res_kw = await conn.execute(text(kw_sql))
        client_kw_ms = (time.perf_counter() - t0) * 1000.0
        plan_kw = res_kw.scalar()

        server_kw_time = plan_kw[0]["Execution Time"]
        planning_kw_time = plan_kw[0]["Planning Time"]

        print("\nKeyword Query Performance:")
        print(f"  Client-measured round trip:   {client_kw_ms:.2f} ms")
        print(f"  Server-side planning time:    {planning_kw_time:.2f} ms")
        print(f"  Server-side execution time:   {server_kw_time:.2f} ms")
        print(f"  Network / TLS overhead delta: {client_kw_ms - server_kw_time:.2f} ms")
        print(f"  Server Plan Root Node:        {plan_kw[0]['Plan']['Node Type']}")

    print("\n" + "=" * 80)
    print("Diagnosis complete.")


if __name__ == "__main__":
    asyncio.run(main())
