import asyncio, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "pytest" in sys.modules: del sys.modules["pytest"]
from sqlalchemy import text
from app.db.session import get_engine, get_pool_status
from app.core.config import get_settings

async def timed(conn, sql, desc):
    t0=time.perf_counter()
    await conn.execute(text(sql))
    ms=(time.perf_counter()-t0)*1000
    print(f"{desc:40s} {ms:7.2f} ms")
    return ms

async def main():
    settings=get_settings()
    print(f"Pool config: size={settings.DB_POOL_SIZE} overflow={settings.DB_MAX_OVERFLOW} timeout={settings.DB_POOL_TIMEOUT} recycle={settings.DB_POOL_RECYCLE}")
    engine=get_engine()
    print(f"Pool status before: {get_pool_status()}")
    async with engine.connect() as conn:
        # Warm
        await timed(conn, "SELECT 1;", "SELECT 1 (warm)")
        # Multiple to get avg
        times=[]
        for i in range(5):
            t0=time.perf_counter()
            await conn.execute(text("SELECT 1;"))
            times.append((time.perf_counter()-t0)*1000)
        import statistics
        print(f"SELECT 1 avg {statistics.mean(times):.2f} p50 {sorted(times)[len(times)//2]:.2f}")

        # Vector query timing (real)
        r=await conn.execute(text("SELECT organization_id FROM document_chunks LIMIT 1;"))
        org=row=row[0] if (row:=r.fetchone()) else None
        if org:
            # need sample embedding
            t0=time.perf_counter()
            await conn.execute(text(f"""
                SELECT id, embedding <=> (SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1) AS dist
                FROM document_chunks WHERE organization_id = '{org}' AND embedding IS NOT NULL ORDER BY dist LIMIT 10;
            """))
            vec_ms=(time.perf_counter()-t0)*1000
            print(f"Vector SQL (org filter) {vec_ms:.2f} ms")
            # Compare: SELECT 1 is 548ms, vector is similar -> network dominates

        # Pool checkout measurement
        print(f"Pool status after: {get_pool_status()}")
        # Simulate concurrent checkout
        import asyncio
        async def checkout():
            async with engine.connect() as c2:
                await c2.execute(text("SELECT 1;"))
                await asyncio.sleep(0.05)
        t0=time.perf_counter()
        await asyncio.gather(*[checkout() for _ in range(5)])
        print(f"5 concurrent checkouts { (time.perf_counter()-t0)*1000:.2f} ms total")

        # pool_pre_ping impact: measure with and without (hard to toggle without restart, just report)

    await engine.dispose()

if __name__=="__main__":
    asyncio.run(main())
