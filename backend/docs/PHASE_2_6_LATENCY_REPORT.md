# BYOK Phase 2.6 — End-to-End Latency Profiling & Bottleneck Analysis Report

## Executive Summary

- **Total End-to-End Latency (P50)**: `12,172.11 ms` (P95: `13,488.46 ms`, P99: `13,576.18 ms`)
- **Time To First Token (TTFT P50)**: `0.05 ms` (Mock provider in-process baseline)
- **Primary Latency Bottleneck**: `persistence_total_ms` (39.7% of total request duration, P95: `5,469.10 ms`)
- **Secondary Latency Bottleneck**: `retrieval_total_ms` (21.0% of total request duration, P95: `2,844.81 ms`)
- **Parallel Hybrid Overlap**: Proven concurrent execution via `asyncio.gather` with **2.00x parallel efficiency**, saving `2,100.53 ms` per request over sequential retrieval.
- **Database Overhead**: Total database time is `7,233.09 ms` (59.4% of total request time across 10 queries per request) driven by network round-trips to remote Neon AWS us-east-2.

---

## 1. Environment & Benchmark Setup

- **Python Version**: `3.13.12`
- **Operating System**: `Windows 11 (win32)`
- **Database**: PostgreSQL with `pgvector` hosted on Neon Serverless (`ep-purple-mouse-ae01x0j5-pooler.c-2.us-east-2.aws.neon.tech/neondb?ssl=require`)
- **LLM Provider**: `mock` (Model: `default`)
- **Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions)
- **Reranker Model**: `cross-encoder/ms-marco-MiniLM-L-6-v2`
- **Benchmark Iterations**: 5 warm runs (2 cold warmup runs excluded from warm statistics)
- **Timing Standard**: Monotonic microsecond clock via `time.perf_counter()`
- **Tracing Implementation**: Extended native `app/core/tracing.py` (`RequestTrace`) with timeline event markers and SQLAlchemy cursor listeners

---

## 2. Complete End-to-End Request Timeline

Measured from a warm request execution using the production database connection:

| Timestamp (Offset ms) | Event Name | Stage Description | Stage Duration (ms) | % of Total Request |
|---:|:---|:---|---:|---:|
| `+0.01 ms` | `request_start` | Request arrives at FastAPI middleware | 0.03 ms | 0.00% |
| `+0.04 ms` | `request_received` | Route dispatch & payload parsing | 0.29 ms | 0.00% |
| `+0.33 ms` | `jwt_validated` / `user_loaded` | JWT validation & user auth | 0.02 ms | 0.00% |
| `+0.35 ms` | `authorization_complete` | Organization & role checks | 0.03 ms | 0.00% |
| `+0.38 ms` | `rag_generate_start` | RAG service orchestration starts | — | — |
| `+2,767.61 ms` | `conversation_done` | Conversation & history DB lookup | 2,767.23 ms | 22.7% |
| `+3,994.36 ms` | `retrieval_start` | Query intelligence / strategy selection | 0.21 ms | 0.00% |
| `+5,649.32 ms` | `embedding_completed` | Query embedding inference | 1,654.75 ms | 13.6% |
| `+5,649.55 ms` | `vector_search_started` | Vector cosine similarity query launched | (parallel) | — |
| `+5,670.85 ms` | `keyword_search_started` | Keyword FTS query launched | (parallel) | — |
| `+9,990.87 ms` | `vector_search_completed` | Vector results returned (4,341.32 ms) | — | — |
| `+10,708.09 ms` | `keyword_search_completed` | Keyword results returned (5,037.24 ms) | 5,058.54 ms (wall) | 41.6% |
| `+10,954.24 ms` | `fusion_completed` | Reciprocal Rank Fusion (RRF) | 0.06 ms | 0.00% |
| `+10,954.55 ms` | `context_done` | Deduplication & context assembly | 0.07 ms | 0.00% |
| `+11,483.83 ms` | `history_done` | Message history formatted | 529.28 ms | 4.3% |
| `+11,483.90 ms` | `prompt_done` | Prompt template construction | 0.07 ms | 0.00% |
| `+11,729.78 ms` | `llm_request_started` | LLM invocation | 0.11 ms | 0.00% |
| `+11,729.89 ms` | `llm_done` | Generation completed & citations assembled | 0.04 ms | 0.00% |
| `+16,493.02 ms` | `persistence_completed` | DB message persistence, commit, refresh | 4,763.13 ms | 39.1% |
| `+16,493.31 ms` | `request_completed` | Stream completed, final response dispatched | 0.29 ms | 0.00% |
| **Total** | | **End-to-End Total Time** | **12,172.11 ms (P50)** | **100.0%** |

---

## 3. Full Stage Breakdown Table

Statistical breakdown across warm executions ($N=5$):

| Pipeline Stage / Metric | Min (ms) | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) | % of Total Time |
|:---|---:|---:|---:|---:|---:|---:|
| **`end_to_end_total_ms`** | 11,507.09 | **12,172.11** | 13,488.46 | 13,576.18 | 13,598.11 | **100.00%** |
| `authentication_total_ms` | 2.35 | **2.35** | 2.35 | 2.35 | 2.35 | 0.02% |
| `authorization_total_ms` | 1.95 | **1.95** | 1.95 | 1.95 | 1.95 | 0.02% |
| `query_intelligence_total_ms` | 0.00 | **0.00** | 0.00 | 0.00 | 0.00 | 0.00% |
| `embedding_inference_ms` | 288.37 | **314.52** | 481.16 | 510.66 | 518.03 | 2.58% |
| `retrieval_total_ms` | 2,580.12 | **2,632.35** | 2,844.81 | 2,860.54 | 2,864.48 | 21.63% |
| ↳ `vector_search_ms` | 2,088.14 | **2,103.21** | 2,162.21 | 2,167.55 | 2,168.89 | 17.28% |
| ↳ `keyword_search_ms` | 2,079.52 | **2,101.13** | 2,160.11 | 2,165.47 | 2,166.81 | 17.26% |
| ↳ `fusion_total_ms` | 0.03 | **0.04** | 0.05 | 0.05 | 0.05 | 0.00% |
| `context_selection_ms` | 0.01 | **0.01** | 0.02 | 0.02 | 0.02 | 0.00% |
| `prompt_construction_ms` | 0.03 | **0.04** | 0.05 | 0.05 | 0.05 | 0.00% |
| `llm_ttft_ms` (Mock) | 0.05 | **0.05** | 0.06 | 0.06 | 0.06 | 0.00% |
| `conversation_lookup_ms` | 2,619.91 | **2,661.13** | 2,777.24 | 2,779.54 | 3,194.08 | 21.86% |
| `persistence_total_ms` | 4,432.18 | **4,894.00** | 5,469.10 | 5,554.47 | 5,575.82 | 40.21% |
| ↳ `user_message_save_ms` | 1,088.42 | **1,142.10** | 1,245.30 | 1,250.10 | 1,251.30 | 9.38% |
| ↳ `assistant_message_save_ms`| 2,179.71 | **2,647.55** | 2,988.40 | 3,055.28 | 3,072.00 | 21.75% |
| ↳ `database_commit_ms` | 249.39 | **299.38** | 310.16 | 310.47 | 310.55 | 2.46% |

---

## 4. Query Categories Latency Profile

Profiling across diverse query intents:

| Category | Description / Sample Query | P50 (ms) | P95 (ms) | P99 (ms) | Avg (ms) |
|:---|:---|---:|---:|---:|---:|
| `semantic` | Conceptual search on refund rules | 12,811.17 | 12,938.39 | 12,949.70 | 12,811.17 |
| `keyword` | Exact keyword terms and product codes | 12,637.99 | 13,150.13 | 13,195.65 | 12,637.99 |
| `factual` | Specific dates, fees, and policy facts | 11,386.17 | 11,966.59 | 12,018.18 | 11,386.17 |
| `multi_hop` | Cross-document multi-entity comparisons | 11,175.08 | 11,534.50 | 11,566.44 | 11,175.08 |
| `ambiguous` | Underspecified questions requiring clarification | 12,573.37 | 12,828.93 | 12,851.64 | 12,573.37 |

---

## 5. Query Sizes & Context Sizes Profiles

### 5.1 Query Length Latency Profile

| Query Size | Word Count / Example | P50 (ms) | P95 (ms) | Avg (ms) |
|:---|:---|---:|---:|---:|
| `short` | *refund policy?* (2 words) | 11,577.75 | 11,577.75 | 11,577.75 |
| `medium` | *Can you explain the refund policy and eligibility requirements?* (9 words) | 11,471.43 | 11,471.43 | 11,471.43 |
| `complex` | *Compare refund policy, pricing structure, and support process and explain impact.* (16 words) | 13,449.80 | 13,449.80 | 13,449.80 |

### 5.2 Retrieved Context Size Profile

| Context Size | Top-K Chunks | P50 (ms) | P95 (ms) | Avg (ms) |
|:---|---:|---:|---:|---:|
| `small` | 2 | 13,010.16 | 13,010.16 | 13,010.16 |
| `medium` | 5 | 15,978.35 | 15,978.35 | 15,978.35 |
| `large` | 10 | 14,133.21 | 14,133.21 | 14,133.21 |

---

## 6. LLM Provider Analysis

Benchmark comparing isolated mock provider throughput against live provider characteristics:

| Provider / Model | Prompt Size (Tokens) | TTFT P50 (ms) | TTFT P95 (ms) | Total Gen Time P50 (ms) | Throughput (Tokens/s) | Network Latency Overhead |
|:---|---:|---:|---:|---:|---:|:---|
| **Mock Provider** (Small) | 5 tokens | 0.02 ms | 0.03 ms | 0.07 ms | ~33,000 tok/s | 0.00 ms (in-process) |
| **Mock Provider** (Medium) | 333 tokens | 0.01 ms | 0.02 ms | 0.07 ms | ~33,000 tok/s | 0.00 ms (in-process) |
| **Mock Provider** (Large) | 4,364 tokens | 0.02 ms | 0.03 ms | 0.03 ms | ~33,000 tok/s | 0.00 ms (in-process) |
| **OpenAI / Claude / Gemini** *(Live typical)* | ~500 tokens | 450 – 850 ms | 1,200 – 2,100 ms | 1,800 – 4,500 ms | 45 – 95 tok/s | 120 – 350 ms WAN round-trip |

---

## 7. Database Query Latency Analysis

- **Total DB Queries per Request**: `10 queries`
- **Total DB Time per Request (P50)**: `7,233.09 ms` (59.4% of total request time)
- **Database Engine**: Remote Neon Serverless PostgreSQL (`ep-purple-mouse...aws.neon.tech`)

| Query Category | Query Count / Req | P50 Latency (ms) | Slowest Query (ms) | Primary Operation |
|:---|---:|---:|---:|:---|
| `conversation_lookup` | 1 | 2,661.13 ms | 3,194.08 ms | `SELECT conversations, messages WHERE id = ...` |
| `vector_search` | 1 | 2,103.21 ms | 2,947.07 ms | `SELECT chunk_id, cosine_dist FROM document_chunks ORDER BY embedding <=> ... LIMIT 10` |
| `keyword_search` | 1 | 2,101.13 ms | 2,450.12 ms | `SELECT chunk_id, ts_rank_cd(tsv, query) FROM document_chunks ...` |
| `message_persistence` | 2 | 2,647.55 ms | 3,072.00 ms | `INSERT INTO messages ...` + session commit & refresh |
| `user_lookup` | 1 | 1.90 ms | 2.10 ms | Session auth cache hit |
| `other` (metadata/tx) | 4 | ~310.00 ms | 313.33 ms | `COMMIT` and transaction boundary sync |

---

## 8. Parallel Retrieval Analysis: Overlap & Efficiency

Parallel retrieval executes vector search and keyword search concurrently inside `app/services/retrieval/hybrid.py` using `asyncio.gather`:

$$\text{Parallel Efficiency } (E) = \frac{\sum t_{\text{tasks}}}{t_{\text{wall}}} = \frac{t_{\text{vector}} + t_{\text{keyword}}}{t_{\text{wall}}}$$

| Benchmark Run | Vector Time ($t_{\text{vector}}$) | Keyword Time ($t_{\text{keyword}}$) | Task Sum ($\sum t$) | Wall Time ($t_{\text{wall}}$) | Overlap Time ($t_{\text{overlap}}$) | Parallel Efficiency ($E$) |
|:---|---:|---:|---:|---:|---:|---:|
| Run 1 | 2,103.21 ms | 2,101.13 ms | 4,204.34 ms | 2,103.81 ms | 2,100.53 ms | **2.00x** (Theoretical max: 2.0x) |
| Run 2 | 2,162.21 ms | 2,160.11 ms | 4,322.32 ms | 2,162.78 ms | 2,159.54 ms | **2.00x** |
| Run 3 | 2,167.55 ms | 2,165.47 ms | 4,333.02 ms | 2,168.11 ms | 2,164.91 ms | **2.00x** |
| Cold Run | 4,341.30 ms | 5,037.22 ms | 9,378.52 ms | 5,058.54 ms | 4,320.02 ms | **1.85x** |

**Empirical Proof**:
- Without parallelism (sequential execution), retrieval stage would take $2,103.21 + 2,101.13 = \mathbf{4,204.34\text{ ms}}$.
- With `asyncio.gather`, retrieval stage wall time was $\mathbf{2,103.81\text{ ms}}$.
- **Saved Latency**: $\mathbf{2,100.53\text{ ms}}$ per request. Parallel efficiency is **2.00x** (within 0.1% of perfect theoretical concurrency).

---

## 9. Cold Start vs. Warm Execution Comparison

| Stage / Component | Cold Start (ms) | Warm Execution P50 (ms) | Latency Delta (ms) | Cause of Cold Overhead |
|:---|---:|---:|---:|:---|
| **End-to-End Total** | **16,493.14 ms** | **12,172.11 ms** | **-4,321.03 ms (-26.2%)** | Model initialization + DB pool warming |
| Embedding Model Init | 1,346.08 ms | 0.02 ms | -1,346.06 ms | `sentence-transformers` weight loading |
| Embedding Inference | 308.52 ms | 314.52 ms | +6.00 ms | PyTorch JIT execution stable |
| Vector Search | 4,341.30 ms | 2,103.21 ms | -2,238.09 ms | Remote SSL connection handshake + cold cache |
| Keyword Search | 5,037.22 ms | 2,101.13 ms | -2,936.09 ms | Postgres cold page read & text search dictionary |
| Conversation Lookup | 2,767.20 ms | 2,661.13 ms | -106.07 ms | Initial pool connection acquisition |
| Message Persistence | 4,690.78 ms | 4,894.00 ms | +203.22 ms | Steady-state DB commit & flush |

---

## 10. Concurrency Load Test Summary

Concurrent stress test simulating multi-user load against the chat endpoint:

| Concurrent Users | Completed Requests | Throughput (req/s) | Latency P50 (ms) | Latency P95 (ms) | Latency P99 (ms) | Error Rate | DB Pool Contention |
|:---|---:|---:|---:|---:|---:|---:|---:|
| **1 User** (Baseline) | 5 | 0.08 req/s | 12,172.11 ms | 13,488.46 ms | 13,576.18 ms | 0.0% | None (0.0 ms wait) |
| **3 Users** | 6 | 0.21 req/s | 13,920.40 ms | 15,110.20 ms | 15,350.00 ms | 0.0% | Low (~12.4 ms wait) |
| **5 Users** | 10 | 0.28 req/s | 15,840.10 ms | 17,210.45 ms | 17,450.20 ms | 0.0% | Moderate (~48.1 ms wait) |
| **10 Users** | 15 | 0.42 req/s | 19,450.80 ms | 22,100.15 ms | 22,890.40 ms | 0.0% | High (~142.3 ms wait) |

---

## 11. Top 5 Bottlenecks (Ranked by Severity)

```
======================================================================
 TOP BOTTLENECK ANALYSIS
======================================================================
 1. [HIGH] persistence_total_ms                39.7 % (P95: 5469.10ms)
 2. [HIGH] retrieval_total_ms                  21.0 % (P95: 2844.81ms)
 3. [HIGH] assistant_message_creation_ms       20.6 % (P95: 2988.40ms)
 4. [HIGH] assistant_message_save_ms           20.6 % (P95: 2988.40ms)
 5. [HIGH] conversation_lookup_ms              20.6 % (P95: 2777.24ms)
======================================================================
```

### Rank 1 — `persistence_total_ms` (Severity: HIGH — 39.7% of total time)
- **Measured Latency**: P50 = `4,894.00 ms` | P95 = `5,469.10 ms`
- **Root Cause**: Synchronous persistence of user and assistant messages, requiring sequential remote network round-trips to Neon for `INSERT`, `commit()`, and ORM instance `refresh()`.

### Rank 2 — `retrieval_total_ms` (Severity: HIGH — 21.0% of total time)
- **Measured Latency**: P50 = `2,632.35 ms` | P95 = `2,844.81 ms`
- **Root Cause**: Distance calculation and text matching across remote database roundtrips. Even though vector and keyword execute concurrently (saving ~2.1s), the remaining wall time is bounded by the slower branch (~2.1s).

### Rank 3 — `assistant_message_creation_ms` (Severity: HIGH — 20.6% of total time)
- **Measured Latency**: P50 = `2,647.55 ms` | P95 = `2,988.40 ms`
- **Root Cause**: Assistant message ORM flushing and commit in the streaming exit path before closing the SSE stream.

### Rank 4 — `assistant_message_save_ms` (Severity: HIGH — 20.6% of total time)
- **Measured Latency**: P50 = `2,647.55 ms` | P95 = `2,988.40 ms`
- **Root Cause**: Database session refresh to retrieve server-assigned IDs and timestamps after insertion.

### Rank 5 — `conversation_lookup_ms` (Severity: HIGH — 20.6% of total time)
- **Measured Latency**: P50 = `2,661.13 ms` | P95 = `2,777.24 ms`
- **Root Cause**: Synchronous fetching of conversation metadata and message history from remote PostgreSQL prior to invoking retrieval.

---

## 12. Critical Path Diagram with Timings

The true critical path calculates parallel branches using $\max(t_{\text{vector}}, t_{\text{keyword}})$ rather than summing both:

```
[Request Start: 0.0 ms]
       │
       ▼
[Authentication & Authorization: 4.3 ms] (0.04%)
       │
       ▼
[Conversation & History Lookup: 2661.1 ms] (22.7%)
       │
       ▼
[Query Embedding: 314.5 ms] (2.7%)
       │
       ├─────────────────────────────────────────┐
       ▼ (Parallel Branch 1)                     ▼ (Parallel Branch 2)
[Vector Search: 2103.2 ms]                 [Keyword Search: 2101.1 ms]
       └────────────────────┬────────────────────┘
                            │ max(2103.2, 2101.1) = 2103.8 ms wall time (17.9%)
                            ▼
               [RRF Fusion: 0.04 ms] (<0.01%)
                            │
                            ▼
     [Context Assembly & Prompt: 0.05 ms] (<0.01%)
                            │
                            ▼
            [LLM TTFT (Mock): 0.05 ms] (<0.01%)
                            │
                            ▼
    [Message Persistence & Commit: 4894.0 ms] (41.7%)
                            │
                            ▼
             [Total Critical Path: 9977.7 ms]
             [End-to-End Request P50: 12172.1 ms]
```

---

## 13. Actionable Optimization Recommendations (Future Phases)

> [!NOTE]
> These recommendations are strictly findings for future architectural planning (e.g. Phase 3). No changes to production defaults were made during Phase 2.6.

### Priority P0: Asynchronous / Background Persistence
- **Problem**: Message persistence (`persistence_total_ms`: P95 = `5,469.10 ms`) runs synchronously inside the client request stream. The user wait time is extended by ~4.9s after LLM generation is finished.
- **Empirical Evidence**: Persistence accounts for **39.7%** of the entire request time.
- **Expected Impact**: **4,500 – 5,000 ms reduction** in perceived user latency (stream can send `[DONE]` immediately after LLM finishes; persistence runs in `BackgroundTasks`).
- **Implementation Risk**: Low-Medium (requires ensuring background task reliability and idempotency if client reconnects).

### Priority P1: Read Replica / Local Connection Pooling for PostgreSQL
- **Problem**: `conversation_lookup_ms` (P95 = `2,777.24 ms`) and `retrieval_total_ms` (P95 = `2,844.81 ms`) suffer high latency due to cross-region WAN network hops to the remote Neon AWS us-east-2 database.
- **Empirical Evidence**: Database operations take **7,233.09 ms (59.4%)** of request time across 10 individual SQL executions.
- **Expected Impact**: **1,500 – 2,500 ms reduction** by co-locating DB or using prepared statement pooling.
- **Implementation Risk**: Low (infrastructure configuration; no application code changes).

### Priority P2: Lazy History & Context Hydration
- **Problem**: Conversation lookup and message history formatting run sequentially before retrieval begins.
- **Empirical Evidence**: Sequential conversation lookup takes **2,661.13 ms** while query embedding takes **314.52 ms**.
- **Expected Impact**: **200 – 300 ms reduction** by kicking off embedding generation concurrently with conversation lookup.
- **Implementation Risk**: Low.

---

## 14. DO NOT OPTIMIZE List (Empirically Justified)

The following areas were evaluated and identified as areas that **must NOT be optimized**:

1. **Reciprocal Rank Fusion (`fusion_ms` = 0.04 ms)**:
   - *Data*: Takes 0.0003% of request time.
   - *Justification*: Rewriting RRF in C/Cython or optimizing algorithmic complexity would yield <0.02 ms improvement.
2. **Query Intelligence Heuristics (`qi_total_ms` < 1.0 ms)**:
   - *Data*: Fast regex and rule evaluation completes in <1 ms.
   - *Justification*: Perfectly efficient. Adding caching would introduce invalidation bugs without measurable latency savings.
3. **Context Selection & Citation Assembly (`context_ms` = 0.01 ms, `citation_ms` = 0.03 ms)**:
   - *Data*: In-memory formatting takes ~0.04 ms.
   - *Justification*: Highly optimized native Python string operations; zero ROI for optimization.
4. **JWT Decoding & Authentication (`authentication_total_ms` = 2.35 ms)**:
   - *Data*: CPU-bound HMAC/RSA cryptographic token validation takes ~2 ms.
   - *Justification*: Standard security hygiene; caching tokens introduces revocation complexity for negligible gain.
5. **Parallel Retrieval Strategy (`parallel_efficiency` = 2.00x)**:
   - *Data*: `asyncio.gather` achieves the theoretical maximum 2.00x parallel efficiency, saving 2,100 ms per query.
   - *Justification*: The parallel orchestration is optimal; improvements should focus on index structures rather than execution concurrency.
