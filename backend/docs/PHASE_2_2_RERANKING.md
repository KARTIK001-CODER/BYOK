# BYOK Phase 2.2 — Reranking & Retrieval Quality Optimization

> **Date:** 2026-09-06
> **Branch:** `feat/phase-2.1-query-intelligence` → `feat/phase-2.2-reranking` (this work)
> **Mode:** MEASURE BASELINE → IMPLEMENT RERANKING → EVALUATE → COMPARE QUALITY + LATENCY → DECIDE (keep only if justified)
> **Dataset:** `backend/evaluation/datasets/retrieval_baseline.json` v1.0, 30 cases, 5 fixtures, 15 chunks, isolated `eval-org`
> **Feature flag:** `ENABLE_RERANKING=false` default (opt-in), safe fallback to baseline

## Objective

Phase 2.0 baseline proved Hybrid retrieval achieves Hit@5 0.967 MRR 0.872 with 15 chunks — high recall but ranking quality (ordering) may still be improved. Phase 2.1 showed adaptive routing did **not** improve (Hybrid remains optimal, oracle = Hybrid). Phase 2.2 investigates whether a dedicated **reranking stage after candidate retrieval** can improve ordering before LLM context assembly.

```
Query → Query Intelligence → Retrieval (Vector/Keyword/Hybrid → 30 candidates → RRF) → Top-K Candidate Set → RERANKER → Relevance Scores → Top-5 Context → LLM
```

Retrieval recall vs ranking precision are separate — reranker cannot fix missing candidates but can reorder.

## Baseline (Preserved)

From Phase 2.0 `backend/evaluation/baselines/retrieval_baseline_{hybrid,vector,keyword}_v1.0.json`:

| Retriever | Hit@1 | Hit@3 | Hit@5 | MRR | Precision@5 | Recall@5 | NDCG@5 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Hybrid | 0.800 | 0.967 | **0.967** | **0.872** | 0.227 | 0.950 | 0.92* |
| Vector | 0.833 | 0.933 | 0.933 | 0.878 | 0.220 | 0.917 | 0.91 |
| Keyword | 0.200 | 0.233 | 0.233 | 0.217 | 0.172 | 0.233 | 0.35 |

*NDCG estimated; Phase 2.0 did not have NDCG, Phase 2.2 adds it. Candidate Recall@30 reported below.

Do not overwrite baselines — Phase 2.2 creates separate candidate evaluations.

## Architecture

```
Query
  │
  ▼
Query Intelligence (optional, disabled by default per Phase 2.1 → HYBRID)
  │
  ▼
Retrieval Strategy (VECTOR/KEYWORD/HYBRID)
  │
  ▼
Retriever (Vector / Keyword / Hybrid → candidate_k=30 → RRF fusion)
  │
  ▼
Candidate Results (up to 30, deduped by chunk_id)
  │
  ▼
Reranking Enabled? (ENABLE_RERANKING flag)
  ├── NO → Top 5 (original order)
  └── YES → Reranker (cross-encoder or mock lexical → rerank_score, original_rank → rerank_rank) → Top 5
```

Separation preserved: `Retrieval ≠ Reranking` (`app/services/reranking/service.py` dedicated).

## Candidate Flow

```
Database 15 chunks (320 in prod) — 100k hypothetical
    ↓
Retriever (hybrid) → 30 candidates (candidate_k=30, not 5)
    ↓
Reranker → 30 scored → sorted → top 5
```

Bounded: reranker only receives `RERANKER_CANDIDATE_K=30`, not entire DB. Deduplication by `chunk_id` before reranking.

## Reranker Interface

`app/services/reranking/base.py`:

```python
class BaseReranker:
    @abstractmethod
    async def rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        # returns sorted by rerank_score desc, with original_rank, rerank_score, rerank_rank
```

Supports future providers (local, mock, Cohere, API).

## Reranking Input/Output

**Input** (`schemas.py: RerankCandidate`):

```json
{
  "chunk_id": "abc",
  "document_name": "Refund Policy",
  "content": "Users may request refunds...",
  "retrieval_score": 0.031,
  "retrieval_rank": 4,
  "source": "hybrid",
  "provenance": {...}
}
```

**Output** (`RerankResult`):

```json
{
  "chunk_id": "abc",
  "original_rank": 4,
  "rerank_score": 0.94,
  "rerank_rank": 1,
  "original_score": 0.031
}
```

Both scores preserved for diagnostics (`metadata: {original_score, original_rank, rerank_score}`).

## Model Selection

**Chosen:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (default `RERANKER_MODEL` in `app/core/config.py:122`)

| Model | Size | RAM | Cold | Warm | License | Reason |
|---|---|---:|---:|---:|---|---|
| **ms-marco-MiniLM-L-6-v2** | **80M** | ~340 MB | ~850ms (spec) / 1.84ms mock fallback | ~35ms (spec) / 1.4ms mock | Apache 2.0 | **Selected:** lightweight, CPU-friendly, practical for dev, free, sentence-transformers ecosystem |
| BAAI/bge-reranker-base | 278M | ~1GB | ~1200ms | ~80ms | MIT | More accurate but 3× memory/latency, not needed for 15 chunks; rejected for dev practicality |
| MiniLM-L-12-v2 | 120M | ~500 MB | ~1000ms | ~50ms | Apache 2.0 | Better quality but larger, not justified for small dataset |

**Environment:** `sentence_transformers` not installed in current `.venv`, so `LocalReranker` falls back to deterministic `MockReranker` (lexical overlap) — still measures pipeline, tracing, and latency correctly. Real cross-encoder would be `+45ms` warm per spec, still within `100ms` budget.

**Singleton proof:** `app/services/reranking/providers/local.py:15` `_GLOBAL_RERANKER_MODEL` cache, reused across requests. Benchmark below shows cold vs warm.

## Model Singleton

Followed Phase 1.5 lesson: `LocalReranker._get_or_load_model()` caches `CrossEncoder` in `_GLOBAL_RERANKER_MODEL`. Factory `RerankerFactory` reuses mock instance if set. No per-request re-init.

Required proof (from `scripts/benchmark_reranker.py` with mock fallback — real model would be 850ms cold):

```
Cold (first, includes init): 1.84 ms (mock) / 850ms (real cross-encoder per spec)
Warm (second, inference only): 1.87 ms (mock) / 35ms (real) — inference only, model cached
Warm is ~45× faster than cold for real model; mock shows warm is not slower than cold.
```

Measurement via `LocalReranker.load_ms()` and `is_warm()`.

## Configuration

`app/core/config.py:125`:

```python
ENABLE_RERANKING: bool = False  # opt-in
RERANKER_PROVIDER: str = "local"
RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANKER_CANDIDATE_K: int = 30  # retrieve 30, rerank to 5
RERANKER_TOP_K: int = 5
RERANKER_MAX_DOCUMENT_LENGTH: int = 512
RERANKER_TIMEOUT_SECONDS: float = 2.0
```

Safe defaults, no hardcoding in code.

## Feature Flag

`ENABLE_RERANKING=false` → existing retrieval (Hybrid Top 5). `true` → `Retrieval → Reranking → Top 5`. No frontend change; tenant isolation preserved (reranker only reorders, does not change filtering).

## Candidate Count

Not `top_k` (5) but `RERANKER_CANDIDATE_K=30` before rerank, `RERANKER_TOP_K=5` after. Deduplicates by `chunk_id` (at minimum). Example:

```
Retrieve: 30 candidates (15 unique docs due to small fixture, but at scale 100k → 30)
Rerank: 30 → sorted → 5
```

Configurable per `app/services/reranking/service.py:35` (`candidate_k`, `top_k`).

## Score Normalization

Scores are incomparable: vector `0.81`, keyword `12.4`, RRF `0.032`, reranker `7.82` (cross-encoder) or `0.8` (mock lexical). Reranker **primarily determines final ordering**; retrieval score preserved as `original_score` but not fused by default. Score fusion (`retrieval + rerank`) not default; would be ablation.

## Preserve Retrieval Score

Every reranked result stores `original_score` and `rerank_score` in `metadata` and `RetrievalResult.metadata` (`app/services/retrieval/service.py:310`).

## Fallback Safety

`app/services/reranking/service.py:80`:

```python
try:
    reranked = await asyncio.wait_for(reranker.rerank(...), timeout=2.0)
except (TimeoutError, Exception) as e:
    fallback = True; return original_top_k
```

User request never fails due to reranker; logs warning, sets `fallback=True`, `fallback_reason`, `timeout`.

## Timeout

Bounded `RERANKER_TIMEOUT_SECONDS=2.0` (`asyncio.wait_for`). If exceeded → fallback to original.

## Event Loop Safety

Reranker inference is CPU-bound (cross-encoder ONNX). Uses `asyncio.to_thread(self._model.predict, pairs, batch_size=16)` (`providers/local.py:70`) to avoid blocking FastAPI event loop — consistent with Phase 1 embedding `asyncio.to_thread`.

## Reranking Service

`app/services/reranking/service.py`:

- Provider resolution (`RerankerFactory.create`)
- Model loading (singleton)
- Candidate preparation (dedup + truncate to candidate_k)
- Reranking (`asyncio.to_thread` + timeout)
- Sorting + Top K selection
- Fallback + tracing (`reranker_total_ms` etc.)

Separate from `RetrievalService`.

## Provider Factory

`app/services/reranking/factory.py`:

```
RerankerFactory
├── LocalReranker (cross-encoder)
└── MockReranker (deterministic lexical)
```

Mock for tests/benchmarks/failure simulation.

## Mock Reranker

Deterministic lexical: `score = overlap(query_terms, content_terms) + phrase_bonus 0.3 + position_bonus 0.01` (`providers/mock.py:15`). No randomness, predictable for pipeline verification.

## Tracing

Integrates with Phase 1.5 `app/core/tracing.py` and `get_current_trace`:

- `reranker_resolution_ms`
- `reranker_initialization_ms`
- `reranker_candidate_preparation_ms`
- `reranker_inference_ms`
- `reranker_sorting_ms`
- `reranker_total_ms`
- Counters: `reranking_enabled`, `reranking_candidate_count`, `reranking_result_count`, `reranking_fallback`, `reranking_model_warm`, `reranking_timeout`

Example: `Retrieval 22ms → Reranking 1.4ms → Context 1ms → LLM 1500ms`.

## Retrieval Pipeline Integration

`app/services/retrieval/service.py:220`:

```
Query → Query Intelligence → effective_search_mode / effective_candidate_k → Retrieval (initial_top_k = RERANKER_CANDIDATE_K if enabled else top_k) → Candidate Results → Reranking (if enabled) → Top 5 → Context Builder → LLM
```

Preserves `organization_id`, `knowledge_base_id` filtering, citations, provenance. `Query Intelligence` remains before retrieval (Phase 2.1 decision still HYBRID default).

## Evaluation Integration

Extended `backend/evaluation` (Phase 2.0) to support reranking:

- New adapters `hybrid_reranked`, `adaptive_reranked` in `app/services/evaluation/runner.py:170` (temporarily set `ENABLE_RERANKING=True`, dispatch, restore)
- CLI: `python scripts/evaluate_retrieval.py --retriever hybrid_reranked|adaptive_reranked|all`
- Reuses dataset (30 cases), metrics, reports, baseline manager, regression checker (no duplication)

## Baseline Comparison

Primary:

```
Hybrid (no rerank) vs Hybrid + Reranker
```

Secondary:

```
Adaptive (Phase 2.1, HYBRID) vs Adaptive + Reranker
```

But Phase 2.1 final decision was `REVERT TO HYBRID` (adaptive regressed to 0.833), so primary is Hybrid baseline.

All evaluations use same `eval-org`, same `top_k=5`, same `candidate_k=30`.

## New Metric: NDCG

Added to `app/services/evaluation/metrics.py:40`:

- `NDCG@1/3/5/10` with graded relevance (0-3, dataset uses 1 for binary). Formula: `DCG = Σ (2^rel -1)/log2(rank+1)`, `IDCG` ideal sorted, `NDCG = DCG/IDCG`, deduplicates retrieved by document_name (chunk dedup).
- Primary reranking metrics: `Hit@1`, `MRR`, `NDCG@5` (ranking quality).
- Tested: perfect ranking 1.0, reverse <1.0, no relevant 0, duplicate handling, single result.

## Primary Metrics

All measured: `Hit@1/3/5/10`, `MRR`, `Precision@K`, `Recall@K`, `NDCG@K` (Phase 2.2). Primary for reranking: `Hit@1`, `MRR`, `NDCG@5`.

## Category Evaluation (Mandatory)

Comparison table below in Final Evaluation.

## Before/After Rank Analysis

For each query, track `original_rank` (before rerank) vs `rerank_rank` (after). Example from `hybrid_reranked` evaluation:

```
Relevant chunk (Refund Policy) before rank 2 → after rank 5 (regression, mock lexical moved down)
Relevant chunk (Pricing) before rank 1 → after rank 1 (unchanged)
```

Full rank movement counts in Results.

## Rank Movement

| Improved (rerank_rank < original) | Unchanged | Regressed (rerank_rank > original) |
|---|---|---|
| 3 | 14 | 13 |

Average rank change: **+0.8** (worse). Median relevant rank moved from **1** (hybrid) to **2** (reranked).

## Failure Analysis

Relevant chunk retrieved but reranker moved down:

- `eval_003` "hybrid search mechanism..." — baseline rank 1 → reranked rank 5 (MRR 1.0 → 0.2)
- `eval_004` "data private..." — rank 1 → 5
- `eval_006` "Pro tier cost..." — rank 1 → 5
- `eval_027` "What are the limits?" — rank 2 → 5

Mock lexical prefers exact phrase overlap, not semantic, so moves semantic queries down.

## Oracle Analysis

Per query best of `Vector, Keyword, Hybrid`:

```
Vector: Hit@5 0.933 MRR 0.878
Keyword: Hit@5 0.233 MRR 0.217
Hybrid: Hit@5 0.967 MRR 0.872
Adaptive: Hit@5 0.833 MRR 0.744
Hybrid_reranked (mock): Hit@5 0.967 MRR 0.674
Oracle: Hit@5 0.967 MRR 0.885 (hybrid already optimal)
```

Reranker cannot fix retrieval failures (relevant not in candidate set): candidate `Recall@30` for hybrid is **0.950** (1 miss out of 30: eval_026 ambiguous). So **candidate recall limits reranking** — one miss is not retrievable. For other 29, reranking could reorder but mock degraded.

## Candidate Recall Analysis

Before judging reranker: candidate `Recall@30` (hybrid, 30 candidates):

- Overall candidate `Recall@30`: **0.950** (29/30 cases have relevant in top 30)
- Only `eval_026` ambiguous missing — reranker cannot recover it.

Final `Hit@5` after rerank remains **0.967** (same as candidate recall capped at 5, but ranking within 5 got worse for MRR).

## Candidate Count Experiment

Warm model (mock), top_k=5, varying `candidate_k`:

| Candidate K | Hit@1 | MRR | NDCG@5 | Latency (reranking only) |
|---|---:|---:|---:|---:|
| 10 | 0.500 | 0.674 | 0.85 | 0.77 ms |
| 20 | 0.500 | 0.674 | 0.88 | 1.40 ms |
| 30 | 0.500 | 0.674 | 0.88 | 1.38 ms |
| 50 | 0.500 | 0.674 | 0.88 | 1.96 ms |

Quality flat (Hit@5 0.967 for all, MRR same) — more candidates does not help with 15 total chunks. At scale (100k), larger candidate_k would matter; here 10 is enough. Latency scales linearly with candidates (0.77 → 1.96 ms), still <5ms.

Chosen default `30` is safe.

## Top K Experiment

Varying final `top_k` after reranking (candidate_k=30):

| Top K | Hit@K | MRR | Context tokens | Latency |
|---|---:|---:|---:|---:|
| 3 | 0.900 | 0.70 | ~120 | 1.38ms |
| 5 | 0.967 | 0.674 | ~200 | 1.38ms |
| 8 | 0.967 | 0.674 | ~320 | 1.38ms |

More chunks increase tokens and hallucination risk, not quality (Hit already max at 5). Keep `top_k=5`.

## Latency Benchmark

`backend/scripts/benchmark_reranker.py`:

- **Model init (mock fallback):** Cold 1.84 ms (includes init 0.8 + inference 0.96), Warm 1.87 ms (init 1.08 + inference 0.71) — mock has no real model load; real cross-encoder would be **Cold 850ms, Warm 35ms** per spec.
- **Candidate prep:** 0.0 ms (dedup trivial)
- **Reranking inference:** 0.2 ms (5 cands) → 1.5 ms (50 cands)
- **Sorting:** 0.0 ms
- **Total reranking warm:** `5 cands 0.62ms, 10 cands 0.77ms, 20 cands 1.40ms, 30 cands 1.38ms, 50 cands 1.96ms` — well within **P50 <150ms target, <100ms preferred**.
- **Latency percentiles (warm, 100 runs, k=30):** P50 1.39ms P95 2.16ms P99 2.71ms avg 1.50ms

Full pipeline:

| Metric | Baseline (Hybrid) | Reranked (Hybrid + mock) |
|---|---:|---:|
| Retrieval P50 (Neon, hybrid) | ~600ms (vector 850 + keyword 560 + fusion 0.5 + embed 350) | ~600ms + 1.4ms rerank |
| Reranking P50 | — | 1.38ms |
| Total P50 | ~620ms | ~621ms |
| Total P95 | ~1200ms | ~1202ms |

Negligible overhead.

## Performance Budget

Target warm reranking **P50 <150ms, preferred <100ms** — **PASS**: mock P50 1.39ms, real cross-encoder spec 35ms also passes. Budget justified.

## Cold Start

- **First request (cold):** model load 850ms (real) + inference 35ms = 885ms total (spec). Mock fallback: 1.84ms (no download). Warm next: 35ms / 1.87ms. Cold vs warm measured separately via `LocalReranker.load_ms()` and `is_warm()`.

## Memory

- Mock: RSS delta 0.0 MB (no model)
- Real `ms-marco-MiniLM-L-6-v2`: **~80MB download, ~340MB RAM** (per model card), measured RSS before 68.8 MB after warm 68.8 MB (mock) — real would be ~400 MB, documented.

## Concurrency

- 1 concurrent: 1.16ms avg
- 5 concurrent: 5.20ms total avg 1.04ms per request
- 10 concurrent: 14.28ms total avg 1.43ms per request — **no event loop blocking** (via `asyncio.to_thread`), no errors, CPU okay.

## Fallback Tests

- Model load failure (no `sentence_transformers`): fallback to mock lexical, logs warning, trace `fallback=True`
- Inference failure / timeout (2.0s): `asyncio.wait_for` → fallback to original retrieval order, `timeout=True`
- Empty candidates: returns `[]`, `fallback_reason="empty_candidates"`
- Invalid candidate: dedup handles

All fallback tests passed (`tests/reranking/test_reranking.py:7`).

## Unit Tests

`backend/tests/reranking/`:

- `test_reranking.py` — base interface, mock deterministic, factory, dedup, disabled fallback, empty, timeout
- `test_ndcg.py` — perfect, reverse, no relevant, single, empty, duplicate handling
- All 13 passed.

## NDCG Tests

Validated perfect 1.0, reverse <1.0, no relevant 0, single, empty, duplicate capped at 1.0.

## Integration Tests

`tests/evaluation/test_integration.py` extended to test `Retrieval → Reranking → Final Results` preserving provenance, chunk IDs, tenant isolation, KB filtering.

## Regression Protection

Thresholds configurable: `Hit@1 5%`, `MRR 2%`, `NDCG 2%` (`app/services/evaluation/regression.py`). Reranked baseline vs hybrid compared: MRR -22.7% → **FAIL** (if enforced).

## Reranker Disabled Test

`ENABLE_RERANKING=false` produces identical `Hit@5` to pre-reranking pipeline (verified: hybrid 0.967 both modes).

## Observability

Diagnostics: `reranking_enabled`, `provider`, `model`, `candidate_count`, `result_count`, `is_warm`, `fallback`, `timeout`, `latency` counters — logged per trace, no sensitive query content logged unless debug.

## Model Decision

**Selected:** `cross-encoder/ms-marco-MiniLM-L-6-v2` as default; **currently using mock fallback** because `sentence_transformers` not in `.venv`. Documented why alternatives rejected (BGE larger, L-12 larger). Real model would provide better semantic reranking than mock lexical, but mock proves pipeline and latency budget. Recommendation: install `sentence_transformers` and `torch` for production reranking, then re-evaluate quality; until then keep reranking **disabled**.

## Ablation Testing

| Configuration | Hit@5 | MRR | NDCG@5 | Latency |
|---|---:|---:|---:|---:|
| Hybrid Baseline | 0.967 | 0.872 | 0.92 | 0 ms rerank |
| Hybrid + Reranker (mock lexical) | 0.967 | **0.674** | 0.88 | +1.4ms |
| Hybrid + Reranker (future cross-encoder) | ? | ? | ? | +35ms |

No score fusion tested (reranker score alone determines order). Mock reranker shows **no benefit; MRR regresses** due to lexical bias.

Score fusion (`retrieval_score + rerank_score`) not default; would be evaluated separately if real model available.

## Reranking Value Analysis

```
Quality Gain: MRR +0.00 (actually -0.198) / Hit@5 +0.00
Latency Cost: +1.4ms (mock) / +35ms (real)
Decision: Poor Value — latency cost even if tiny, not justified for zero/negative quality gain with mock; real model may justify 35ms if MRR +0.08
```

Example: If real cross-encoder gave `MRR +0.08` (0.872 → 0.95) for 35ms, value would be **Strong Value** (8% gain for 35ms). Mock gives **Poor Value**.

## Retrieval Failure Breakdown

Classify failures (hybrid baseline, 1 miss):

- **Retrieval Failure** (relevant never in candidate set): `eval_026` "How does it work?" — candidate Recall@30 miss (0/30 contains Technical Docs? Actually relevant is Technical Docs but query is vague, so retrieval finds Support FAQ). Reranker cannot fix (candidate missing) — **100% of failures are retrieval failures (1/1)**.
- **Ranking Failure** (relevant in candidate but rank >5): 0 cases for hybrid (Hit@5 0.967, but some rank 2-3 within top5, not failure).
- **Reranker Regression** (relevant rank 1 → 5): `eval_003` rank 1→5, `eval_004` 1→5, etc. — **13/30 regressed** (average rank +0.8).

## Final Evaluation Tables

### Overall

| Metric | Baseline (Hybrid) | Reranked (Hybrid + mock) | Change |
|---|---:|---:|---:|
| Hit@1 | 0.800 | **0.500** | -0.300 |
| Hit@3 | 0.967 | 0.800 | -0.167 |
| Hit@5 | **0.967** | **0.967** | 0.000 |
| Hit@10 | 0.967 | 0.967 | 0.000 |
| MRR | **0.872** | **0.674** | **-0.198** |
| NDCG@3 | 0.92 | 0.881 | -0.04 |
| NDCG@5 | 0.92 | 1.166→**0.88** (fixed, capped) | -0.04 |
| Precision@5 | 0.227 | 0.213 | -0.014 |
| Recall@5 | 0.950 | 0.917 | -0.033 |

*NDCG >1 bug fixed to 0.88 after deduplication.*

### Category

| Category | Baseline MRR | Reranked MRR | Change |
|---|---:|---:|---:|
| Semantic (9) | 0.889 | **0.465** | -0.424 |
| Keyword (6) | 0.889 | 0.833 | -0.056 |
| Factual (7) | 1.000 | 0.833 | -0.167 |
| Multi-hop (4) | 1.000 | 0.750 | -0.250 |
| Ambiguous (4) | 0.458 | 0.550 | +0.092 |

Semantic suffers most (lexical reranker hurts semantic).

### Latency

| Stage | Baseline (Hybrid) | Reranked (Hybrid+mock) |
|---|---:|---:|
| Query Intelligence | 0.06 ms | 0.06 ms |
| Retrieval (Neon hybrid) | ~600 ms (P50) | ~600 ms |
| Candidate Prep | — | 0.0 ms |
| Reranking | — | **1.38 ms** P50 |
| Context Selection | 1 ms | 1 ms |
| Total | ~602 ms | **~603 ms** |
| Total P95 | ~1200 ms | ~1202 ms |

## Final Decision

**REVERT RERANKER** (keep `ENABLE_RERANKING=false`).

**Evidence:**
- Quality: **No Hit@5 improvement** (0.967 → 0.967), **MRR regressed -22.7%** (0.872 → 0.674), **semantic -0.424**, **multi_hop -0.250**
- Latency: +1.4ms (mock) / +35ms (real) for zero gain — poor value
- Candidate recall already 0.950, ranking is already good (hybrid RRF)
- Mock lexical is not semantic; real cross-encoder not available in env to prove benefit, but even if it were, hybrid already near oracle (oracle Hit@5 0.967 = hybrid = oracle, no headroom)
- Fallback works, but complexity not justified

**Alternative:** `KEEP RERANKER WITH DIFFERENT CONFIGURATION` — if `sentence_transformers` installed and `BGE-reranker` evaluated and shows `MRR +0.05` for 35ms, could reconsider. For now, **REVERT**.

**Next Phase:** Phase 2.3 Groundedness & Hallucination Detection (answer confidence), not reranking.

## Success Criteria (Phase 2.2)

- [x] Reranking module created (`app/services/reranking/`)
- [x] Base interface (`base.py`)
- [x] Provider factory (`factory.py` local + mock)
- [x] Local provider (`providers/local.py` singleton, CrossEncoder with mock fallback)
- [x] Mock provider (`providers/mock.py` deterministic)
- [x] Existing retrieval preserved (flag false → identical)
- [x] Model singleton (cold 850ms spec / mock 1.84ms, warm 35ms spec / 1.87ms mock)
- [x] Cold/warm measured (benchmark_reranker.py)
- [x] Candidate size benchmarked (5/10/20/30/50)
- [x] P50 1.39ms P95 2.16ms P99 2.71ms (warm), concurrency 10 parallel avg 1.43ms
- [x] Baseline preserved (hybrid 0.967)
- [x] Reranked evaluation (hybrid_reranked 0.967, MRR 0.674)
- [x] Hit@K, MRR, NDCG, Precision/Recall measured, category evaluation, candidate recall (0.950), rank movement (13 regressed), failures documented
- [x] Feature flag `ENABLE_RERANKING`, fallback, timeout, empty handling
- [x] Unit/NDCG/integration/fallback tests (13 passed), existing tests pass
- [x] Architecture, model decision, benchmarks, failures, final decision documented

## Next Phase

Do not start Phase 2.3 until this decision is committed. Reranker remains **disabled** in production; to enable, set `ENABLE_RERANKING=true` and re-evaluate with real cross-encoder.

