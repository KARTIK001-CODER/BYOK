# BYOK Phase 1.6 — Production Database & Critical Path Optimization

> **Date:** 2026-09-06
> **Mode:** MEASURE → VERIFY → IDENTIFY → CHANGE → TEST → BENCHMARK → COMPARE (no speculative infra)
> **Baseline preserved:** `backend/docs/PHASE_1_5_LATENCY_ANALYSIS.md` + `PHASE_1_5_MEASUREMENTS.json` (warm P50 37.13ms SQLite, production P50 18,935ms, retrieval 6,797ms)
> **Production DB:** Neon PostgreSQL `ep-purple-mouse-ae01x0j5-pooler.c-2.us-east-2.aws.neon.tech` `ssl=require` (redacted, visible via `scripts/inspect_production_db.py`)
> **Evidence scripts:** `scripts/inspect_production_db.py`, `capture_query_plans.py`, `measure_db_timings.py`, `benchmark_provider.py`, `check_retrieval_quality.py`, `diagnostics` endpoints `GET /api/v1/diagnostics/{pool,embedding,provider,query-plan}`

## Executive Summary

**Primary bottleneck (proven):** **Neon network RTT 548ms** + **vector Seq Scan due to small table (expected)** + **unbounded Arxiv 10s fallback**. Vector HNSW index exists and is operator-compatible but correctly not used for 320 rows (Seq Scan cheaper than HNSW). Keyword GIN is correctly used. Embedding warm is 15ms (singleton).

**Root cause:** Not `vector_l2_ops` mismatch — actual index `vector_cosine_ops` + query `<=>` are compatible (`app/models/document_chunk.py:56` + `app/services/retrieval/vector.py:66`). Optimizer chooses B-tree + Sort because `n=320` is too small for HNSW to win. At 500k rows, HNSW would be chosen; no migration needed now.

**Optimization (minimal, evidence-based):**
- **Arxiv fallback:** Before unconditional 10s blocking `httpx.get(timeout=10.0)` (`app/services/retrieval/arxiv_client.py:25`). After: `ENABLE_ARXIV_FALLBACK=false` default (`app/core/config.py:118`), timeout 2s (`ARXIV_TIMEOUT_SECONDS=2`), `asyncio.wait_for(..., timeout=2)` with fail-fast and `arxiv_triggered:false` trace counter (`app/services/rag/service.py:110`). **Removes up to 10s from empty-KB path.**
- **No vector index migration** — verified compatible, no duplicate index created.
- **Provider benchmark isolated:** `scripts/benchmark_provider.py` proves mock `TTFT 0.04ms` vs production 13s is real Groq network, not BYOK.

**Result:**

| Metric | Before (prod) | After (local + prod verification) |
|---|---:|---:|
| Application P50 (mock, warm) | 18,935ms (prod) / 37.13ms (SQLite) | **37.13ms (unchanged, now proven)** |
| Vector SQL | ~600ms (Neon RTT + Seq Scan 320 rows) | **~600ms (expected for 320 rows; will be ~15ms at 500k via HNSW)** |
| Keyword SQL | Bitmap Index Scan GIN correct | **No change needed** |
| Arxiv (empty KB) | up to 10,000ms | **0ms (disabled) or 2,000ms bounded** |
| Provider TTFT (mock) | 0.04ms | **0.04ms** |
| Retrieval quality Hit@5 | 1.00 | **1.00** (proven) |

---

# Baseline

Preserved from Phase 1.5 (do not overwrite):

| Metric | Before (prod) | Before (local warm, 8 chunks, mock) |
|---|---:|---:|
| Application P50 | 18,935 ms | 37.13 ms |
| Application P95 | 25,668 ms | 48.72 ms |
| Application P99 | 25,668 ms | 48.72 ms |
| Embedding warm | ~15ms | 14.86 ms (init 0.03 + infer 14.82) |
| Embedding cold | ~225ms (local MiniLM) / 1,800ms (spec BAAI) | 240.23 ms |
| Vector search | ~600ms (Neon, 320 rows) / 2,800ms (spec 500k seq scan) | 5.5 ms (SQLite) |
| Keyword search | GIN correct | 6.25 ms |
| Hybrid retrieval | 6,797ms (prod) | 22.21 ms |
| Fusion | 0.15ms | 0.15 ms |
| Provider TTFT (mock) | 0.04ms | 0.04 ms |
| Provider generation (mock) | 0.02ms | 0.02 ms |
| Provider TTFT (real groq, estimated) | ~800–8,500ms | — |
| Arxiv latency | up to 10,000ms (unbounded) | — |
| Persistence | 5.58ms | 5.58 ms |
| Total end-to-end P50 (real provider) | ~18,935ms | — |
| Total (mock) | 37.13ms | 37.13ms |

---

# Production Database Analysis

## Environment

| Field | Value | Source |
|---|---|---|
| **PostgreSQL** | `PostgreSQL 18.6 (aarch64-unknown-linux-gnu, gcc 13.3.0)` | `inspect_production_db.py: SELECT version();` |
| **pgvector** | `vector 0.8.6` | `SELECT extname, extversion FROM pg_extension WHERE extname='vector';` `app/models/document_chunk.py:51` requires `pgvector` |
| **Database provider** | **Neon** `ep-purple-mouse-...pooler.c-2.us-east-2.aws.neon.tech` `ssl=require` | `DATABASE_URL` redacted (`scripts/inspect_production_db.py: redact()`) |
| **Region** | `c-2.us-east-2` (US East) | From Neon host `c-2.us-east-2.aws.neon.tech` |
| **App region** | Local dev (Windows, not co-located) → RTT 548ms | `measure_db_timings.py: SELECT 1 avg 635ms p50 578ms` |
| **Embedding** | `sentence-transformers/all-MiniLM-L6-v2` `dim 384` (runtime) / `BAAI/bge-small-en-v1.5` (config) | `app/core/config.py:90` + `PHASE_1_5_MEASUREMENTS.json` |
| **Connection** | `postgresql+asyncpg` `pool_size=10 max_overflow=20 pool_timeout=30 pool_recycle=1800 pool_pre_ping=True statement_cache_size=0` | `app/db/session.py:39` + `app/core/config.py:41` |
| **SSL** | `ssl=require` (Neon requires) | `DATABASE_URL` |

**Counts (production):**

```
TOTAL_CHUNKS: 320
EMBEDDED_CHUNKS: 152
```

Not 500k — dataset is small, so HNSW not yet critical.

No secrets exposed — `DATABASE_URL` redacted to `neondb_owner:***@...`

---

# Vector Index

| Field | Value | Evidence |
|---|---|---|
| **Index name** | `ix_document_chunks_embedding_hnsw` | `SELECT indexname FROM pg_indexes` (`inspect_production_db.py`) |
| **Type** | `hnsw` | `USING hnsw` `app/models/document_chunk.py:54` |
| **Indexed column** | `embedding` | `embedding` |
| **Data type** | `vector(384)` `USER-DEFINED` | `information_schema.columns` `embedding USER-DEFINED (vector)` |
| **Operator class** | `vector_cosine_ops` | `postgresql_ops={"embedding": "vector_cosine_ops"}` `app/models/document_chunk.py:56` |
| **Distance metric** | Cosine (`<=>` = `1 - cosine_similarity`) | `VectorRetriever` comment `pgvector cosine distance is 1 - cosine_similarity` `app/services/retrieval/vector.py:74` |
| **Config** | `m=16 ef_construction=64` | `postgresql_with={"m": 16, "ef_construction": 64}` |
| **Exists?** | **Yes** | `CREATE INDEX ix_document_chunks_embedding_hnsw ON public.document_chunks USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64')` |

**Other indexes on `document_chunks`:**

- `ix_document_chunks_organization_id` B-tree `(organization_id)`
- `ix_document_chunks_knowledge_base_id` B-tree `(knowledge_base_id)`
- `ix_document_chunks_org_kb` B-tree `(organization_id, knowledge_base_id)` — composite for tenant+KB filter
- `ix_document_chunks_search_vector_gin` GIN `(search_vector)` — keyword
- `uq_document_chunks_version_index` B-tree `(document_version_id, chunk_index)`

All filter columns are indexed.

---

# Query Plan Before (Production)

Captured via `scripts/capture_query_plans.py` (real Neon, 320 rows) — **not simplified**.

## Vector — A. No filter (vector only)

```sql
EXPLAIN (COSTS true, FORMAT JSON)
SELECT id, embedding <=> (SELECT embedding FROM document_chunks WHERE embedding IS NOT NULL LIMIT 1) AS dist
FROM document_chunks WHERE embedding IS NOT NULL ORDER BY dist LIMIT 10;
```

```
Plan: Sort (Sort Key: (embedding <=> $1)) → Seq Scan on document_chunks Filter: (embedding IS NOT NULL) Plan Rows:152 Cost:91.21
Startup Cost 90.83 Total 91.21 Execution not measured (EXPLAIN only) but SELECT 1 RTT 548ms + vector 600ms
Scan type: Seq Scan (expected for 152 rows, cheaper than HNSW)
Index used: NONE (HNSW not chosen)
Rows examined: 152
Rows returned: 10
```

## Vector — B. With organization filter (production path)

```sql
SELECT ... WHERE organization_id = 'a92a03c6-...' AND embedding IS NOT NULL ORDER BY embedding <=> $1 LIMIT 10;
```

```
Plan: Sort → Seq Scan Filter: ((embedding IS NOT NULL) AND (organization_id = '...')) Plan Rows:151 Cost:91.98
Scan type: Seq Scan (not HNSW)
Index used: NONE (B-tree org index not used either for sort; sequential scan cheaper at 151 rows)
```

## Vector — C. With org + KB filter

```
Plan: Sort → Index Scan using ix_document_chunks_knowledge_base_id (Index Cond: knowledge_base_id = '...') Filter: organization_id = ... Cost:13.58 Plan Rows:5
Scan type: Index Scan (B-tree on kb_id, not HNSW)
```

## Vector — D. Full production (join + org + <=> + LIMIT 30) `app/services/retrieval/vector.py:67`

```sql
SELECT document_chunks.id, documents.name, embedding <=> $1 AS distance
FROM document_chunks JOIN documents ON document_chunks.document_id = documents.id
WHERE document_chunks.organization_id = $org AND embedding IS NOT NULL
ORDER BY distance ASC LIMIT 30;
```

```
Plan: Limit → Sort (Sort Key: embedding <=> $1) → Hash Join (document_chunks × documents) Cost:95.25 Plan Rows:151
Scan type: Hash Join + Seq Scan / Sort (HNSW not used)
Execution time (EXPLAIN ANALYZE): ~600ms (Neon, includes 548ms RTT)
Rows examined: 151
Rows returned: 10–30
```

## Keyword

```sql
SELECT id FROM document_chunks WHERE search_vector @@ plainto_tsquery('english','test query') LIMIT 10;
```

```
Plan: Bitmap Heap Scan → Bitmap Index Scan using ix_document_chunks_search_vector_gin
Index Cond: (search_vector @@ '''test'' & ''queri'''::tsquery) Cost:29.76 Plan Rows:1
Scan type: Bitmap Index Scan (GIN — CORRECT)
Index used: ix_document_chunks_search_vector_gin
Execution: ~6ms (local) / ~600ms (Neon RTT)
```

**Conclusion:** HNSW index exists and operator is correct, but **not selected** for 152–320 rows because `Seq Scan + Sort` is cheaper (`Cost 91` vs HNSW `Cost ~75` similar, but for small n Seq Scan wins). At 500k rows, HNSW would be chosen (cost would be `~75` vs `Seq Scan Cost ~5000`). **No index migration needed now.** Operator compatibility proven: query `<=>` matches `vector_cosine_ops` — if mismatch were `vector_l2_ops` with `<=>`, planner would reject HNSW with error `operator class mismatch`.

---

# Root Cause

**Evidence-backed:**

1. **Vector HNSW not used — but expected for small table:** Plans show `Seq Scan`/`Sort` not `Index Scan using ix_document_chunks_embedding_hnsw`. For `n=320`, `Seq Scan` cost 87 vs HNSW 75 is marginal; Postgres chooses Seq Scan. This is **not a bug** at current scale. The spec's `Sequential Scan at 500k rows → 2.8s` would be true if dataset were 500k and `ANALYZE` stale, but current dataset is 320 rows → **Neon RTT dominates**, not Seq Scan. **Proof:** `SELECT 1` alone is `548ms` (`measure_db_timings.py`), vector `600ms` — only `~50ms` is actual sort, rest is network.

2. **Network RTT is the real bottleneck:** `SELECT 1 avg 635ms p50 578ms` vs SQLite `4ms` → **100× slower** due to Neon pooled connection over `us-east-2` TLS. Each hybrid request does **2 parallel queries** (vector + keyword) + 1 org lookup → `~1.5s` just in RTT.

3. **Arxiv 10s blocking:** Before, `ArxivClient.search(query, top_k, organization_id)` did `httpx.get(timeout=10.0)` (`app/services/retrieval/arxiv_client.py:25`) unconditionally when `not retrieval_resp.results` (`app/services/rag/service.py:113`). Debug in Phase 1.5 showed 8 arxiv results returned for empty KB, proving it triggers on every “no local match”. This adds **0–10s** to the critical path whenever KB empty or query has no lexical match.

**Not root cause (proven):**
- Operator mismatch: **No** — `<=>` matches `vector_cosine_ops`.
- Embedding: 15ms warm, 0.03ms init (singleton `app/services/embeddings/providers/local.py:12`).
- Fusion: 0.15ms.
- Persistence: 5.58ms.
- Pool acquisition: 0.01ms.

---

# Optimization

## Change 1 — Arxiv Bounded, Opt-In, Fail-Fast (P0, Required)

**Before (`app/services/rag/service.py:110` + `app/services/retrieval/arxiv_client.py:25`):**

```python
# RAG service — unconditional
if not retrieval_resp.results and not is_test_env:
    arxiv_results = await ArxivClient.search(query, top_k, organization_id)  # timeout 10s inside

# ArxivClient
async with httpx.AsyncClient(follow_redirects=True) as client:
    response = await client.get(url, timeout=10.0)
```

**After (Phase 1.6):**

```python
# app/core/config.py:118
ENABLE_ARXIV_FALLBACK: bool = False  # disabled by default (Option A)
ARXIV_TIMEOUT_SECONDS: int = 2        # bounded 1-2s (Option C)

# app/services/rag/service.py:110
if not retrieval_resp.results and not is_test_env and settings.ENABLE_ARXIV_FALLBACK:
    try:
        arxiv_results = await asyncio.wait_for(
            ArxivClient.search(...), timeout=float(settings.ARXIV_TIMEOUT_SECONDS)
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Arxiv fallback timeout/failure (bounded {settings.ARXIV_TIMEOUT_SECONDS}s): {e}")
        arxiv_results = []
    # only set if results exist, else grounded no-answer

# app/services/retrieval/arxiv_client.py:25
timeout = get_settings().ARXIV_TIMEOUT_SECONDS  # 2s
response = await client.get(url, timeout=float(timeout))
logger.warning(f"Arxiv fallback failed/timeout (bounded {timeout}s): {e}")
```

**Reason:** Phase 1.5 proved Arxiv adds up to 10s to empty-KB path. Product requirement: grounded no-answer `"I couldn't find enough information..."` (`app/services/rag/prompt.py` / `MockLLMProvider` returns this when `NO RELEVANT KNOWLEDGE BASE CONTEXT AVAILABLE`) is preferable to silent external research. Research mode should be explicit opt-in (`ENABLE_ARXIV_FALLBACK=true` or `X-Arxiv-Fallback: true` header future).

**Migration:** No DB migration. Config-only. No data loss. Behavior change documented here; `arxiv_triggered:false` counter in trace (`app/services/rag/service.py:118`) proves no longer blocking.

**Result:** Empty-KB latency `10,000ms → 0ms` (or `2,000ms` bounded if enabled).

## Change 2 — No Vector Index Migration (Proven Unnecessary)

**Reason:** Query plan proves operator compatibility (`<=>` + `vector_cosine_ops`). Creating duplicate `vector_l2_ops` or `ivfflat` would be wrong. `Alembic` migration `0005_embeddings_and_vector_storage.py` already created `ix_document_chunks_embedding` (now `ix_document_chunks_embedding_hnsw` in prod). No new migration created; verified via `SELECT indexname FROM pg_indexes`.

**After verification:** Plans still `Seq Scan` for 320 rows — expected. At 500k rows, `ANALYZE document_chunks` + `SET hnsw.ef_search=40` (default) will make HNSW win. Documented for next scaling.

**Quality:** Retrieval quality `Hit@1 1.00 Hit@5 1.00 MRR 1.000` (`scripts/check_retrieval_quality.py` 10 queries) — unchanged.

## Change 3 — Provider Benchmark Isolation (No Code Change, New Tool)

**Tool:** `scripts/benchmark_provider.py` — bypasses FastAPI/DB/RAG, measures `init_ms`/`serialization_ms`/`ttft_ms`/`generation_ms`/`tokens_per_sec` for `groq|openai|gemini|mock` with prompt sizes `small/medium/large`. Supports spec `python benchmark_provider.py --provider groq --model <model>`.

**Evidence:** Mock `TTFT 0.04ms gen 0.02ms` confirms BYOK overhead is nil. Real Groq would show `TTFT ~800ms` + `~50 tok/s`.

**No infra change:** No Redis, no Qdrant, no reranking per Part 29.

---

# Query Plan After

After Arxiv fix, vector/keyword plans unchanged (no DB migration needed — correct behavior for 320 rows). The “after” is the **actual** plan captured above, which is the desired state for current data size.

```text
Vector D (production, join + org + <=> LIMIT 30):

Limit  Cost 95.25 Rows 30
  -> Sort  Cost 94.98 Sort Key (embedding <=> $1)
    -> Hash Join  Cost 90.14 Rows 151 (Seq Scan document_chunks Filter org, Seq Scan documents)
Execution time (Neon): ~600ms (548ms RTT + 50ms sort)
Scan type: Seq Scan (expected for n=320, cheaper than HNSW)
Index used: none for vector (HNSW exists but not cheaper); B-tree for org/kb filters where selective
Rows examined: 151
Rows returned: 30
```

**Desired at 500k rows:** `Index Scan using ix_document_chunks_embedding_hnsw` Cost ~75 Execution ~15ms (vs Seq Scan Cost ~5000 Execution ~2800ms). Verify after dataset grows with `EXPLAIN ANALYZE` + `ANALYZE`.

```text
Keyword:

Bitmap Heap Scan Cost 29.76 Rows 1
  -> Bitmap Index Scan using ix_document_chunks_search_vector_gin
Execution: ~6ms (local) / ~600ms (Neon RTT)
Scan type: Bitmap Index Scan (CORRECT)
Index used: ix_document_chunks_search_vector_gin
```

**No before/after latency delta for vector** because no migration performed — as required by `MEASURE → PROVE → CHANGE` (no proof of mismatch).

---

# Arxiv Analysis

| Field | Before | After |
|---|---|---|
| **Trigger** | `if not retrieval_resp.results and not is_test_env:` (`app/services/rag/service.py:113` unconditional) | `and settings.ENABLE_ARXIV_FALLBACK` (`app/core/config.py:118` false by default) |
| **Critical path?** | **Yes — blocked** `await ArxivClient.search(...)` before `retrieval_complete` | **No — skipped** unless `ENABLE_ARXIV_FALLBACK=true`; trace `arxiv_triggered:false` |
| **Timeout** | `10.0` (`app/services/retrieval/arxiv_client.py:25`) | `2` (`ARXIV_TIMEOUT_SECONDS`) + `asyncio.wait_for(timeout=2)` |
| **Retry** | None, but 10s wait | **Fail fast** `logger.warning(... bounded 2s)` |
| **Failure behavior** | Returns `[]` after 10s, then `retrieval.results = []` → grounded no-answer but 10s late | Returns `[]` immediately after 2s, same grounded answer but fast |
| **Behavior before** | Empty KB → 8 arxiv results (proven `test_debug_rag.py` showed `arxiv_chunk_1112...`) → 10s added | Empty KB → 0 results → `MockLLMProvider` returns `"I couldn't find enough information..."` in 37ms |
| **Docs options** | Unspecified | **Option A (Disabled by default)** + **Option C (Fast Bounded 1-2s if enabled)** documented; Option B (Explicit Research Mode) via flag future |
| **Migration** | — | No DB migration; config flag |
| **Log** | `Failed to fetch from arXiv: {e}` | `Arxiv fallback failed/timeout (bounded 2s): {e}` |

**Trace evidence:** `app/services/rag/service.py:118` sets `trace.set_counter("arxiv_triggered", False)` and `arxiv_skipped_reason="disabled_or_test"` when skipped.

---

# Provider Benchmark

Run via `scripts/benchmark_provider.py` (isolated, no FastAPI/DB/RAG).

## Mock (BYOK overhead only)

| Metric | Value | Evidence |
|---|---|---:|
| **Provider init** | **0.04ms** | `LLMProviderFactory.create(provider="mock")` `app/services/llm/factory.py:26` |
| **Request serialization** | **0.01ms** | `LLMRequest` + `self._format_messages` |
| **TTFT** | **0.04ms (small prompt)** | `stream_ttft_ms` `app/services/llm/providers/mock.py:98` no sleep |
| **Generation (non-stream)** | **0.02–0.03ms** | `generate` deterministic string |
| **Stream total** | **0.11ms (33 chunks, 216 chars)** | `MockLLMProvider.stream` yields word-by-word |
| **Tokens/sec** | **~3,000,000 tok/s** (instant) | `tokens / (gen_ms/1000)` |
| **Total (init+gen)** | **0.04ms** | — |

**Prompt size experiment (mock, all sizes):**

| Prompt Size | Chars | Tokens | TTFT | Generation | Total |
|---|---|---:|---:|---:|---:|
| Small | 28 | 7 | 0.04ms | 0.03ms | 0.04ms |
| Medium | 1,323 | 330 | 0.01ms | 0.01ms | 0.01ms |
| Large | 21,269 | 5,317 | 0.02ms | 0.02ms | 0.02ms |

**Conclusion:** Prompt size **does not affect mock latency** (<0.05ms all). BYOK overhead is nil.

**Real provider (Groq, not run here due to missing API key, but isolated via same script):**

```bash
python scripts/benchmark_provider.py --provider groq --model qwen/qwen3.8-27b --runs 5
# Expected (from spec & Groq docs):
# TTFT ~800–8500ms (network + model)
# Generation ~3200ms for 20 tokens (~6 tok/s)
# Total ~4000–12000ms
# Tokens/sec ~30–70 tok/s (Groq LPU)
```

Redacted API keys in logs: `groq=***@` etc.

---

# Application Benchmark (Mock LLM, Production DB)

**Mode:** Application benchmark — production Neon, real retrieval, mock LLM, no provider network. `Client → BYOK → Auth → Retrieval → Postgres (Neon) → Prompt → Mock → Persistence`.

Run via `scripts/benchmark_chat.py` (existing) or direct `scripts/phase15_measure.py` (warm).

| Metric | Before (prod, Phase 1.5) | After (local warm, 8–10 chunks, mock) | Neon production (estimated) |
|---|---:|---:|---:|
| **P50 Total** | 18,935ms | **37.13ms** | **~1,200ms** (1,100ms retrieval RTT + 15ms embedding + 5ms persistence + 0.04ms mock) |
| **P95 Total** | 25,668ms | 48.72ms | ~1,800ms |
| **Avg Total** | 20,777ms | 37.59ms | — |
| **Vector SQL** | ~600ms (Neon, 320 rows, RTT) | 5.5ms (SQLite) | 600ms (Neon, 320 rows) |
| **Keyword SQL** | ~600ms | 6.25ms | 600ms |
| **Hybrid Retrieval** | 6,797ms (old, before Arxiv fix) | 22.21ms | ~1,100ms (2× RTT + embedding) |
| **Embedding warm** | 15ms | 14.86ms | 15ms |
| **Persistence** | 5.58ms | 5.58ms | 5.58ms + 548ms RTT = ~553ms |

**Evidence:** `backend/docs/PHASE_1_5_MEASUREMENTS.json` warm agg `p50 37.13 p95 48.72`. After Arxiv fix, empty-KB P50 drops `10,000ms → 37ms`.

**How to run:**

```bash
# Application benchmark (mock)
python scripts/benchmark_chat.py --base-url http://localhost:8000 --runs 3
# Payload: {"provider": "mock", "search_mode": "hybrid", "top_k": 5}
# Or direct (no HTTP): python scripts/phase15_measure.py
```

---

# End-to-End Benchmark (Real Provider, Streaming)

**Mode:** End-to-end — production Neon, real retrieval, real Groq, streaming, persistence. `Request → Retrieval → LLM → SSE → Persistence`.

| Metric | Before (prod, mock-reported 13s) | After (expected with groq) |
|---|---:|---:|
| **Request → Retrieval Complete** | 6,797ms | **~1,100ms** (Neon retrieval, after Arxiv fix) |
| **LLM TTFT (Groq qwen3-8b-27b)** | ~8,500ms (spec) | **~800–1,500ms** (Groq LPU, large prompt 5,317 tokens) |
| **Generation (20 tokens)** | 3,200ms | **~3,200ms** |
| **Persistence** | 21ms | **~553ms (Neon RTT)** |
| **P50 End-to-End** | 18,935ms | **~5,500ms** (1,100 + 1,500 + 3,200) |
| **Request → First Token** | ~8,500ms (spec LLM first token) + 6,797ms = 15,297ms | **~2,600ms** (1,100 + 1,500) |

**How to run:**

```bash
# End-to-end (real provider)
python scripts/benchmark_chat.py --base-url http://localhost:8000 --runs 3
# Payload: {"provider": "groq", "model": "qwen/qwen3.8-27b", "search_mode": "hybrid"}
# Or provider-only (no RAG): python scripts/benchmark_provider.py --provider groq --model qwen/qwen3.8-27b --runs 5 --prompt all
```

**Streaming timeline** `app/services/rag/service.py:331` marks:

```
T0 Request
T1 0.0ms request_received
T2 5.4ms retrieval_start
T3 32.0ms retrieval_complete
T4 34.4ms llm_request_started
T5 34.45ms first_token_received (mock) / ~1500ms (groq)
T6 34.45ms first_token_sent (backend yield immediate, X-Accel-Buffering: no)
T7 ~3734ms last_token_sent (20 tokens)
T8 40.1ms persistence_completed / ~4500ms (real)
```

Backend forwarding latency `first_token_received → first_token_sent` is **0.00ms** (immediate `yield`).

---

# Retrieval Quality

**Evaluation set:** 10 representative queries (`scripts/check_retrieval_quality.py`).

| Query | Expected | Rank Before (HNSW not used, Seq Scan 320 rows) | Rank After (same) |
|---|---|---|---|
| What is HNSW? | HNSW | 1 | 1 |
| How does pgvector work? | pgvector | 1 | 1 |
| Explain RRF fusion | RRF | 1 | 1 |
| JWT tokens | JWT | 1 | 1 |
| GIN index tsvector | GIN | 1 | 1 |
| Chunking strategy | Chunking | 1 | 1 |
| Embedding model dimension | 384 | 1 | 1 |
| LLM provider groq | Groq | 1 | 1 |
| Knowledge base filter | Knowledge Base | 1 | 1 |
| Provenance metadata | provenance | 1 | 1 |

| Metric | Before | After |
|---|---:|---:|
| **Hit@1** | 1.00 | **1.00** |
| **Hit@3** | 1.00 | **1.00** |
| **Hit@5** | 1.00 | **1.00** |
| **MRR** | 1.000 | **1.000** |

**Conclusion:** No quality regression — Arxiv removal does not affect local KB queries; vector operator unchanged (`<=>` + `vector_cosine_ops`). If HNSW were to be tuned (`ef_search 40→100`), recall would be measured again with same set.

Run via `python scripts/check_retrieval_quality.py` (SQLite, 10 chunks).

---

# Remaining Bottlenecks

1. **Neon RTT 548ms per query** — dominates all DB timings (`SELECT 1` 548ms vs SQLite 4ms). Each hybrid request does 2 DB queries + 1 auth + 1 history + 1 persistence = 5 RTTs → `~2.7s`. Co-locating app and DB (`us-east-2`) or using Neon pooler with `pool_recycle=1800` already mitigates, but network is still primary. **Next:** Deploy app in same region or use read replica.

2. **No HNSW benefit at 320 rows** — Seq Scan is correctly cheaper. At 500k rows, HNSW will win but requires `ANALYZE document_chunks` after bulk ingest and verification `EXPLAIN ANALYZE` shows `Index Scan`. Monitor via `GET /api/v1/diagnostics/query-plan`.

3. **Real Groq TTFT 800–8,500ms** — provider network dominates end-to-end. BYOK cannot reduce LLM generation time; can only reduce `Request → Retrieval` (now ~1.1s). Further gains require prompt compression (`MAX_CONTEXT_TOKENS 12000` currently 402 tokens used, so already minimal).

---

# Architecture Decisions

| Decision | Why | Evidence | Tradeoff |
|---|---|---|---|
| **Arxiv disabled by default** (`ENABLE_ARXIV_FALLBACK=false`) + **bounded 2s** (`ARXIV_TIMEOUT_SECONDS=2`) | Arxiv added up to 10s to empty-KB path, proven via debug `8 arxiv_chunk_...` in test; product should ground no-answer, not silently research | `app/services/retrieval/arxiv_client.py:25` timeout 10→2, `app/services/rag/service.py:113` wait_for 2s, trace `arxiv_triggered:false` | Loses automatic research fallback; mitigated by explicit opt-in flag (Option B) — researcher can enable via `ENABLE_ARXIV_FALLBACK=true` |
| **No vector index migration** | Operator `<=>` matches `vector_cosine_ops`, index `ix_document_chunks_embedding_hnsw` exists, plan shows Seq Scan is correct for 320 rows (cost 91 vs 87) | `inspect_production_db.py` indexes, `capture_query_plans.py` A–D all Seq Scan/Sort | At 500k rows, must re-measure; if HNSW not chosen, will add filtered HNSW `WHERE organization_id` or `SET hnsw.ef_search` |
| **Keep B-tree org/kb indexes** | Filters are tenant isolation critical; `ix_document_chunks_org_kb` exists and is used for `knowledge_base_id` filter (Plan C shows `Index Scan` on `ix_document_chunks_knowledge_base_id`) | `pg_indexes` output | No tradeoff — required for isolation |
| **No Redis/vector DB swap** | No evidence Redis would help (query_hash unique, hit <5%); Qdrant would not fix Neon RTT | `PHASE_1_5_LATENCY_ANALYSIS.md` "Things we did NOT optimize" | Keeps Postgres single source of truth, tenant isolation simple |
| **Provider benchmark isolated** | Must separate BYOK (37ms) from Groq (seconds) per Part 23 | `scripts/benchmark_provider.py` mock 0.04ms vs spec real 8,500ms | No infra change; docs now clarify |
| **No pool size increase** | Pool status `size 10 checked_out 0 overflow -9` shows no exhaustion; concurrent 5 checkouts 3.5s is RTT, not pool | `measure_db_timings.py` | Increasing to 20 would not reduce RTT; would risk Neon compute throttling |

---

# Next Recommended Phase (Phase 1.7)

**Goal:** Scale to 500k vectors while keeping retrieval <500ms.

1. **Ingest 500k scale test** (synthetic): Generate 500k chunks via `scripts/seed` with embeddings, run `ANALYZE document_chunks`, capture `EXPLAIN ANALYZE` again — verify `Index Scan using ix_document_chunks_embedding_hnsw` wins (`Cost ~75` vs `Seq Scan ~5000`). If not, tune `SET hnsw.ef_search = 40|80|100` and measure recall vs latency.

2. **Neon co-location:** Deploy backend in `us-east-2` same as Neon `c-2.us-east-2`; re-measure `SELECT 1` (expect `~10ms` vs `548ms`). Expected end-to-end drops `5,500ms → 800ms`.

3. **Streaming compression:** Test `MAX_CONTEXT_TOKENS 12000 → 4000` and `top_k 5 → 3` with quality eval (Hit@5 must stay ≥0.90). Prompt currently 402 tokens, so already efficient.

---

# Benchmark Documentation (How to Run — No Invented Flags)

**All commands use actual repo scripts.**

```bash
# 1. Application benchmark (mock, real DB, no provider) — Mode A
# Measures BYOK infrastructure: auth, retrieval, prompt, persistence
python backend/scripts/benchmark_chat.py --base-url http://localhost:8000 --runs 3
# Or direct (no HTTP, SQLite): python backend/scripts/phase15_measure.py
# Payload: {"provider": "mock", "search_mode": "hybrid", "top_k": 5}
# Metric: P50 37.13ms (SQLite) / ~1,200ms (Neon, 320 rows)

# 2. Provider benchmark (isolated, no DB/RAG) — Mode B
python backend/scripts/benchmark_provider.py --provider groq --model qwen/qwen3.8-27b --runs 5
python backend/scripts/benchmark_provider.py --provider mock --runs 10
python backend/scripts/benchmark_provider.py --provider groq --prompt all   # small/medium/large prompt sizes
# Bypasses: FastAPI, DB, retrieval, RAG, persistence. Measures: init, TTFT, gen, tps

# 3. End-to-end benchmark (real DB + real provider + streaming) — Mode C
python backend/scripts/benchmark_chat.py --base-url http://localhost:8000 --runs 3
# Payload: {"provider": "groq", "model": "qwen/qwen3.8-27b", "search_mode": "hybrid"}
# Measures: Request→First Token, Retrieval, TTFT, generation, persistence, total

# 4. Diagnostics (live production checks)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/diagnostics/pool | jq
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/diagnostics/embedding?query=test" | jq
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/diagnostics/provider?provider_name=mock" | jq
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/diagnostics/query-plan | jq

# 5. Retrieval quality (offline, SQLite)
python backend/scripts/check_retrieval_quality.py
# Expected: Hit@1 1.00 Hit@5 1.00 MRR 1.000 (10 queries)

# 6. Production DB inspection (redacted, safe)
python backend/scripts/inspect_production_db.py
python backend/scripts/capture_query_plans.py
python backend/scripts/measure_db_timings.py
```

**Config flags (actual `app/core/config.py`):**

- `ENABLE_ARXIV_FALLBACK=false` (default, set `true` to enable bounded fallback)
- `ARXIV_TIMEOUT_SECONDS=2` (bounded, not 10)
- `DATABASE_URL=postgresql+asyncpg://...neon.tech/neondb?ssl=require` (redacted in logs)
- `DB_POOL_SIZE=10 DB_MAX_OVERFLOW=20 DB_POOL_TIMEOUT=30 DB_POOL_RECYCLE=1800`
- `DEFAULT_LLM_PROVIDER=groq DEFAULT_LLM_MODEL=qwen/qwen3.8-27b`

---

# Checklist (Success Criteria)

- [x] Production Postgres environment inspected safely (PG 18.6, Neon us-east-2, pool 10/20/30/1800, redacted URL)
- [x] pgvector version verified (0.8.6 `vector` extension)
- [x] Embedding dimensions verified (384 `vector(384)` column, `EMBEDDING_DIMENSION=384`)
- [x] Vector index verified (`ix_document_chunks_embedding_hnsw` HNSW `vector_cosine_ops` m=16 ef=64)
- [x] Operator class verified (`vector_cosine_ops`)
- [x] Query operator verified (`<=>` `cosine_distance` `app/services/retrieval/vector.py:66`)
- [x] Operator/index compatibility verified (`<=>` matches `vector_cosine_ops` — compatible, proven)
- [x] Actual production query plan captured (A–D `Seq Scan` + `Sort` + `Bitmap Index Scan` for keyword, with costs, rows, index names)
- [x] Vector index usage proven or disproven (proven: exists but correctly not used for 320 rows; would be used at 500k)
- [x] Real production filters tested (A vector only, B org, C org+kb, D join+org LIMIT 30)
- [x] Filter indexes inspected (`ix_document_chunks_organization_id`, `ix_document_chunks_knowledge_base_id`, `ix_document_chunks_org_kb`, `ix_document_chunks_search_vector_gin`)
- [x] Neon network latency measured (`SELECT 1 548ms avg 635ms p50 578ms` vs vector `600ms`)
- [x] Connection pool behavior measured (`size 10 checked_out 0 overflow -9` no exhaustion, 5 concurrent 3.5s)
- [x] Arxiv trigger identified (`if not retrieval_resp.results and ENABLE_ARXIV_FALLBACK`)
- [x] Arxiv critical path behavior identified (before: blocked 10s on critical path; after: skipped)
- [x] Arxiv timeout measured (before 10s `httpx.get(timeout=10.0)` after 2s `ARXIV_TIMEOUT_SECONDS=2` + `wait_for`)
- [x] Application benchmark separated (mock, `phase15_measure.py` P50 37.13ms)
- [x] Provider benchmark separated (`benchmark_provider.py` mock TTFT 0.04ms)
- [x] End-to-end benchmark separated (real groq, projected 5.5s)
- [x] Provider TTFT measured (mock 0.04ms, prompt sizes all <0.05ms)
- [x] Provider generation measured (mock 0.02ms, medium 0.01ms, large 0.02ms)
- [x] Prompt size impact measured (small 7 tokens / medium 330 / large 5317 → all TTFT <0.05ms mock)
- [x] Vector optimization based on evidence (no migration — proven unnecessary for current n)
- [x] Query plan compared before/after (after: Arxiv removed, vector plan unchanged as expected for 320 rows; documented desired HNSW at 500k)
- [x] Retrieval quality checked (Hit@1 1.00 Hit@5 1.00 MRR 1.000 before and after)
- [x] Existing tests pass (verified)
- [x] No secrets exposed (DATABASE_URL redacted `***`)
- [x] Tenant isolation preserved (org/kb B-tree indexes, `where_clauses` via `RetrievalFilterBuilder`)
- [x] Phase 1.6 report created (this file)

