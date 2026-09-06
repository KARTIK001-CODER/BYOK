"""Safely inspect production Neon DB — no secrets logged."""
import asyncio
import time
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# prevent pytest tsvector issue — we want real postgres path
if "pytest" in sys.modules:
    del sys.modules["pytest"]

from sqlalchemy import text
from app.core.config import get_settings
from app.db.session import get_engine

def redact(url: str) -> str:
    # postgresql+asyncpg://user:pass@host/db?ssl=require -> postgresql+asyncpg://user:***@host/db?ssl=require
    try:
        if "://" in url and "@" in url:
            before_host = url.split("://")[1]
            creds, rest = before_host.split("@", 1)
            if ":" in creds:
                user = creds.split(":")[0]
                return url.split("://")[0] + f"://{user}:***@" + rest
            return url.split("://")[0] + "://***@" + rest
    except Exception:
        pass
    return "***"

async def main():
    settings = get_settings()
    print(f"APP_ENV={settings.APP_ENV}")
    print(f"DATABASE_URL={redact(settings.DATABASE_URL)}")
    print(f"DB_POOL_SIZE={settings.DB_POOL_SIZE} MAX_OVERFLOW={settings.DB_MAX_OVERFLOW} TIMEOUT={settings.DB_POOL_TIMEOUT} RECYCLE={settings.DB_POOL_RECYCLE}")
    print(f"EMBEDDING_MODEL={settings.EMBEDDING_MODEL} dim={settings.EMBEDDING_DIMENSION}")
    # try connect with 5s timeout
    engine = None
    try:
        # use get_engine but with timeout wrapper
        engine = get_engine()
        print(f"Engine dialect={engine.dialect.name} driver={engine.dialect.driver}")
        # quick pool + version checks with timeout
        async def do_checks():
            async with engine.connect() as conn:
                # pg version
                r = await conn.execute(text("SELECT version();"))
                pg_version = r.scalar_one()
                print(f"PG_VERSION: {pg_version[:120]}")

                # pgvector
                try:
                    r2 = await conn.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname='vector';"))
                    row = r2.fetchone()
                    if row:
                        print(f"PGVECTOR: {row[0]} {row[1]}")
                    else:
                        print("PGVECTOR: NOT INSTALLED")
                except Exception as e:
                    print(f"PGVECTOR check error: {e}")

                # document_chunks schema
                r3 = await conn.execute(text("""
                    SELECT column_name, data_type, udt_name FROM information_schema.columns 
                    WHERE table_name='document_chunks' AND column_name IN ('embedding','search_vector','organization_id','knowledge_base_id')
                    ORDER BY column_name;
                """))
                print("COLUMNS:")
                for row in r3.fetchall():
                    print(f"  {row[0]} {row[1]} ({row[2]})")

                # indexes
                r4 = await conn.execute(text("""
                    SELECT indexname, indexdef FROM pg_indexes WHERE tablename='document_chunks' ORDER BY indexname;
                """))
                print("INDEXES:")
                for idx, idef in r4.fetchall():
                    print(f"  {idx}: {idef[:200]}")

                # row counts
                r5 = await conn.execute(text("SELECT count(*) FROM document_chunks;"))
                cnt = r5.scalar_one()
                print(f"TOTAL_CHUNKS: {cnt}")
                r6 = await conn.execute(text("SELECT count(*) FROM document_chunks WHERE embedding IS NOT NULL;"))
                cnt2 = r6.scalar_one()
                print(f"EMBEDDED_CHUNKS: {cnt2}")

                # simple SELECT 1 latency
                t0 = time.perf_counter()
                await conn.execute(text("SELECT 1;"))
                sel1 = (time.perf_counter()-t0)*1000
                print(f"SELECT_1_LATENCY_MS: {sel1:.2f}")

                # vector query EXPLAIN (without ANALYZE first to avoid heavy)
                try:
                    # get a sample embedding if exists
                    r7 = await conn.execute(text("SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1;"))
                    sample = r7.scalar_one_or_none()
                    if sample and cnt > 0:
                        # Use pgvector operator with sample — we need to pass vector literal
                        # For now just EXPLAIN without actual vector
                        r8 = await conn.execute(text("""
                            EXPLAIN (COSTS true, FORMAT JSON)
                            SELECT id, embedding <=> (SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1) AS dist
                            FROM document_chunks WHERE organization_id = (SELECT organization_id FROM document_chunks LIMIT 1)
                            ORDER BY dist LIMIT 10;
                        """))
                        plan = r8.scalar_one()
                        print(f"VECTOR_EXPLAIN: {str(plan)[:2000]}")
                    else:
                        print("VECTOR_EXPLAIN: no sample embedding, skipped")
                except Exception as e:
                    print(f"VECTOR_EXPLAIN error: {e}")

                # keyword explain
                try:
                    r9 = await conn.execute(text("""
                        EXPLAIN (COSTS true, FORMAT JSON)
                        SELECT id FROM document_chunks WHERE search_vector @@ plainto_tsquery('english','test query') LIMIT 10;
                    """))
                    plan2 = r9.scalar_one()
                    print(f"KEYWORD_EXPLAIN: {str(plan2)[:2000]}")
                except Exception as e:
                    print(f"KEYWORD_EXPLAIN error: {e}")

        await asyncio.wait_for(do_checks(), timeout=15)
        print("INSPECTION_DONE")
    except asyncio.TimeoutError:
        print("INSPECTION_TIMEOUT: DB did not respond in 15s (Neon cold start or network)")
    except Exception as e:
        print(f"INSPECTION_ERROR: {type(e).__name__}: {e}")
    finally:
        if engine:
            try:
                await engine.dispose()
            except Exception:
                pass

if __name__ == "__main__":
    asyncio.run(main())
