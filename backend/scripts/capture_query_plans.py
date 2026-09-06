"""Capture query plans for Part 6-7: vector with varying filters."""
import asyncio, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "pytest" in sys.modules:
    del sys.modules["pytest"]
from sqlalchemy import text
from app.db.session import get_engine

async def explain(conn, sql, desc):
    t0=time.perf_counter()
    r=await conn.execute(text(sql))
    plan=r.scalar_one()
    ms=(time.perf_counter()-t0)*1000
    print(f"\n=== {desc} ({ms:.2f} ms) ===")
    import json
    print(json.dumps(plan, indent=2)[:4000])
    return plan

async def main():
    engine=get_engine()
    async with engine.connect() as conn:
        # Get org id and sample embedding
        r=await conn.execute(text("SELECT organization_id, embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1;"))
        row=r.fetchone()
        if not row:
            print("No embedded chunk")
            return
        org_id=row[0]
        # Need vector literal — use subquery trick to avoid needing literal
        # A: Vector only
        await explain(conn, """
            EXPLAIN (COSTS true, BUFFERS false, FORMAT JSON)
            SELECT id, embedding <=> (SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1) AS dist
            FROM document_chunks WHERE embedding IS NOT NULL ORDER BY dist LIMIT 10;
        """, "A. Vector only (no org filter)")

        # B: Vector + org filter (production)
        await explain(conn, f"""
            EXPLAIN (COSTS true, FORMAT JSON)
            SELECT id, embedding <=> (SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1) AS dist
            FROM document_chunks WHERE organization_id = '{org_id}' AND embedding IS NOT NULL ORDER BY dist LIMIT 10;
        """, "B. Vector + organization_id")

        # C: Vector + org + kb filter
        r2=await conn.execute(text(f"SELECT knowledge_base_id FROM document_chunks WHERE organization_id='{org_id}' LIMIT 1;"))
        kb_row=r2.fetchone()
        kb_id=kb_row[0] if kb_row else org_id
        await explain(conn, f"""
            EXPLAIN (COSTS true, FORMAT JSON)
            SELECT id, embedding <=> (SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1) AS dist
            FROM document_chunks WHERE organization_id = '{org_id}' AND knowledge_base_id = '{kb_id}' AND embedding IS NOT NULL ORDER BY dist LIMIT 10;
        """, "C. Vector + org + kb")

        # D: Full production query (with join, as in vector.py)
        await explain(conn, f"""
            EXPLAIN (COSTS true, FORMAT JSON)
            SELECT document_chunks.id, documents.name, embedding <=> (SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1) AS distance
            FROM document_chunks JOIN documents ON document_chunks.document_id = documents.id
            WHERE document_chunks.organization_id = '{org_id}' AND document_chunks.embedding IS NOT NULL
            ORDER BY distance ASC LIMIT 30;
        """, "D. Full production (join + org + <=> + LIMIT 30)")

        # EXPLAIN ANALYZE for D (real execution)
        print("\n--- EXPLAIN ANALYZE D (actual execution) ---")
        t0=time.perf_counter()
        r=await conn.execute(text(f"""
            EXPLAIN (ANALYZE, COSTS true, BUFFERS true, FORMAT JSON)
            SELECT document_chunks.id FROM document_chunks
            WHERE organization_id = '{org_id}' AND embedding IS NOT NULL
            ORDER BY embedding <=> (SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1) LIMIT 10;
        """))
        plan=r.scalar_one()
        ms=(time.perf_counter()-t0)*1000
        import json
        print(json.dumps(plan, indent=2)[:5000])
        print(f"ANALYZE took {ms:.2f} ms")

        # Test hnsw.ef_search tuning
        try:
            await conn.execute(text("SET hnsw.ef_search = 40;"))
            print("SET hnsw.ef_search=40 OK")
            await conn.execute(text("SET hnsw.ef_search = 100;"))
            print("SET hnsw.ef_search=100 OK")
        except Exception as e:
            print(f"hnsw.ef_search set failed: {e}")

    await engine.dispose()

if __name__=="__main__":
    asyncio.run(main())
