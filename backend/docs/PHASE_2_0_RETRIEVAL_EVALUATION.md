# BYOK Phase 2.0 — Retrieval Evaluation & RAG Quality Framework

> **Date:** 2026-09-06
> **Mode:** MEASURE → ESTABLISH BASELINE → EVALUATE → PROVE (no retrieval optimization yet)
> **Branch:** `feat/phase-1.5-1.6-tracing-production-optimization` + Phase 2.0 additions
> **Dataset:** `backend/evaluation/datasets/retrieval_baseline.json` v1.0 (30 cases)
> **Reports:** `backend/evaluation/reports/retrieval_eval_*.json/md`
> **Baselines:** `backend/evaluation/baselines/retrieval_baseline_{vector,keyword,hybrid}_v1.0.json`

## Objective

Build a **reusable, deterministic, extensible, automated, versioned, CI-friendly** retrieval evaluation system that answers:

- Which retriever performs best? Vector vs Keyword vs Hybrid
- Did a new technique improve MRR/Hit@5?
- Did an optimization introduce regression?

Every future change (reranker, query router, HyDE, multi-query, parent document) reuses this framework without rewrite.

## Architecture

```
Evaluation Dataset (retrieval_baseline.json v1.0, 30 cases)
        │
        ▼
EvaluationDatasetLoader (dataset.py — validation, legacy conversion)
        │
        ▼
EvaluationRunner (runner.py)
        │
   ┌────┴────┐
   │ Adapter │
   ├── VectorAdapter  ──► RetrievalService.search(vector)
   ├── KeywordAdapter ──► RetrievalService.search(keyword)
   ├── HybridAdapter  ──► RetrievalService.search(hybrid) + RRF
   ├── (future) HybridRerankedAdapter
   ├── (future) QueryRouterAdapter
   └── (future) HyDEAdapter
        │
        ▼
Results (RetrievedResult per rank, is_relevant via stable document_name)
        │
        ▼
Metrics (EvaluationMetrics — Hit@K, MRR, Precision@K, Recall@K)
        │
        ├─► Overall
        ├─► By Category (semantic/keyword/factual/multi_hop/ambiguous)
        └─► By Difficulty (easy/medium/hard)
        │
        ▼
Reports
        ├─► Console (console_report)
        ├─► JSON (write_json_report → evaluation/reports/retrieval_eval_{retriever}_{timestamp}.json)
        └─► Markdown (write_markdown_report)
        │
        ▼
Baseline (BaselineManager.save — evaluation/baselines/retrieval_baseline_{retriever}_v1.0.json)
        │
        ▼
Regression (RegressionChecker.compare — thresholds 2% MRR/Hit@5, PASS/WARNING/FAIL)
```

**No existing retrieval logic modified** — `VectorRetriever`, `KeywordRetriever`, `HybridRetriever`, `Fusion` unchanged; adapters wrap `RetrievalService.search` (`app/services/evaluation/runner.py:50`).

## Directory Structure

```
backend/app/services/evaluation/
├── __init__.py          — re-exports runner, metrics, baseline, regression
├── schemas.py           — Pydantic: EvaluationCase, EvaluationDataset, CaseResult, MetricResult, EvaluationReport, BaselineRecord, RegressionResult, EvaluationConfigSnapshot
├── dataset.py           — EvaluationDatasetLoader (load, validate, legacy migration)
├── runner.py            — EvaluationRunner + Vector/Keyword/Hybrid adapters + ADAPTER_REGISTRY
├── metrics.py           — EvaluationMetrics (Hit@K, MRR, Precision@K, Recall@K, aggregation)
├── reporting.py         — console_report, write_json_report, write_markdown_report + worst/failure analysis
├── baseline.py          — BaselineManager (save/load latest, git commit)
└── regression.py        — RegressionChecker (thresholds, PASS/WARNING/FAIL)

backend/evaluation/
├── datasets/
│   ├── retrieval_baseline.json  — v1.0, 30 cases, categories, stable document_name
│   └── README.md                — versioning, identifier decision
├── fixtures/
│   ├── company_handbook.md
│   ├── refund_policy.md
│   ├── pricing.md
│   ├── technical_docs.md
│   └── support_faq.md
├── reports/                     — JSON + Markdown per evaluation
└── baselines/                   — retrieval_baseline_{vector,keyword,hybrid}_v1.0.json + _latest.json

backend/app/evaluation/          — legacy (kept for backward compat, re-exports new)
├── datasets/retrieval_examples.json — 8 queries, 5 docs (migrated via loader)
├── metrics.py                   — RetrievalMetrics (old Hit@K)
└── retrieval.py                 — RetrievalEvaluator (old)

backend/scripts/
├── evaluate_retrieval.py        — CLI runner (--retriever all|vector|keyword|hybrid --dataset --top-k --output --save-baseline --compare-baseline)
└── seed_evaluation_data.py      — creates eval-org/eval-kb, ingests fixtures via real chunker + embedding pipeline, --reset

backend/tests/evaluation/
├── test_metrics.py              — Hit@K, MRR, Precision, Recall, aggregation, edge cases
├── test_dataset.py              — duplicate IDs, missing expected, validation
├── test_runner.py               — adapter registry, mock adapter, top-k config
├── test_reporting.py            — console/JSON/Markdown generation
├── test_regression.py           — baseline vs current PASS/WARNING/FAIL
└── test_integration.py          — full pipeline (seed → ingestion → embedding → 3 retrievers → metrics)
```

## Dataset Design

### Stable Identifiers

**Decision:** Use `document_name` (fixture title) as stable key, not volatile DB `document_id`/`chunk_id`. Reason: IDs differ per environment (Neon vs SQLite vs CI); names are deterministic from `evaluation/fixtures/*.md` titles.

Schema (`app/services/evaluation/schemas.py:25`):

```python
class ExpectedResult(BaseModel):
    document_name: str | None  # e.g. "Refund Policy"
    document_slug: str | None  # future
    chunk_content_snippet: str | None  # future chunk-level
    relevance_grade: int = 1  # 0-3, binary 1 for v1.0, graded future
```

Dataset `retrieval_baseline.json` v1.0 uses `document_name` only.

### Fixture Documents (Realistic, Not Lorem)

Created in `backend/evaluation/fixtures/` specifically to test:

- **Company Handbook** — policies, hybrid work, onboarding, Slack, privacy, career ladder (tests semantic, factual, ambiguous)
- **Refund Policy** — refund eligibility, `cancellation_fee` exact keyword, trial 14 days (tests keyword, factual, multi-hop)
- **Pricing** — plans (€49/€199/custom), `STORAGE: 25 MB`, quotas, `pool_size=10` etc. (tests keyword, factual)
- **Technical Docs** — architecture, `vector_cosine_ops`, `RRF_K=60`, `pool_size=10`, HNSW `m=16`, `MAX_CONTEXT_TOKENS=12000` (tests keyword, factual, semantic)
- **Support FAQ** — refunds, `ENABLE_ARXIV_FALLBACK`, data retention, `How does it work?` ambiguous (tests ambiguous, factual)

Each ~3–4 chunks via real `RecursiveTextChunker` (1000 chars, 150 overlap) → total 15 chunks (verified `seed_evaluation_data.py` output: "15 chunks, 15 embedded").

### Evaluation Categories (30 Queries)

| Category | Count | Definition | Example Query → Expected |
|---|---:|---|---|
| **semantic** (30%) | 9 | Paraphrased, embedding similarity | "How do I get my money back?" → Refund Policy |
| **keyword** (20%) | 6 | Exact term, lexical match | "What is the cancellation_fee?" → Refund Policy |
| **factual** (20%+1 mixed) | 7 | Direct lookup | "What is the maximum file size?" → Pricing (25 MB) |
| **multi_hop** (13%) | 4 | Requires 2+ docs | "If I buy annual and cancel after 20 days with 30% usage, what refund and fee?" → Refund Policy + Pricing |
| **ambiguous** (13%+1 mixed) | 4 | Vague, single best expected | "How does it work?" → Technical Docs |

Distribution matches spec 30/20/20/15/15 (9/6/7/4/4). Every query has documented `notes`.

**Dataset size:** 30 (exceeds minimum 20, within recommended 30–50). Quality over quantity.

### Versioning

`{"version": "1.0", "created_at": "2026-09-06"}` in JSON. Baseline snapshots store `dataset_version` and `config.dataset_version` (`EvaluationConfigSnapshot`). Loader validates duplicate IDs, missing expected, invalid categories.

## Retrieval Configuration Snapshot

Every `EvaluationReport` records (`app/services/evaluation/schemas.py:80`):

```python
EvaluationConfigSnapshot(
    evaluation_version="1.0",
    dataset_version="1.0",
    retriever_type="hybrid",
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",  # or BAAI/bge-small-en-v1.5
    embedding_dimension=384,
    top_k=5,
    candidate_k=30,  # max(top_k*4, 30)
    fusion_method="rrf",
    rrf_k=60,
    extra={"top_k_values": [1,3,5,10]}
)
```

Thus `Evaluation A vs Evaluation B` are comparable.

## Metrics

### Definitions & Formulas

**Hit@K** — Did at least one relevant result appear in Top K?

```
Hit@K = |{queries with relevant in Top K}| / |{all queries}|
```

Example: 10 queries, 8 have relevant in Top 5 → Hit@5=0.80. (`metrics.py:15`)

**MRR** — Mean Reciprocal Rank

```
RR = 1 / rank_of_first_relevant (rank 1 → 1.0, rank 2 → 0.5, rank 4 → 0.25)
MRR = avg(RR over queries)
```

Example: ranks 1,2,4 → MRR=(1+0.5+0.25)/3=0.58. (`metrics.py:28`)

**Precision@K** — Relevant in Top K / K

```
Precision@K = |Retrieved_K ∩ Relevant| / K
```

Example: Top 5 has 3 relevant → 0.6. (`metrics.py:18`)

**Recall@K** — Relevant retrieved / Total relevant

```
Recall@K = |Retrieved_K ∩ Relevant| / |Relevant|
```

Example: Total 4 relevant, retrieved 3 → 0.75. (`metrics.py:12`)

Implementation: `app/services/evaluation/metrics.py` → `EvaluationMetrics` with `hit_at_k`, `recall_at_k`, `precision_at_k`, `reciprocal_rank`, `aggregate`, `aggregate_by_category`, `aggregate_by_difficulty`. Tested in `tests/evaluation/test_metrics.py` with edge cases (empty, duplicates, multiple relevant, no relevant, k=0).

### Configuration

`top_k_values = [1,3,5,10]` (`runner.py:53`) — not hardcoded to 5; supports `--top-k 5|10` via CLI.

## Retriever Comparison (Real Results — Neon, 15 chunks, 30 queries)

Run via:

```bash
python scripts/evaluate_retrieval.py --retriever all --top-k 5
python scripts/evaluate_retrieval.py --retriever vector|keyword|hybrid --top-k 5 --save-baseline
```

### Baseline (v1.0, production Neon, eval-org isolated)

| Metric | Vector | Keyword | **Hybrid** |
|---|---:|---:|---:|
| **Hit@1** | 0.833 | 0.200 | **0.800** |
| **Hit@3** | 0.933 | 0.233 | **0.967** |
| **Hit@5** | **0.933** | 0.233 | **0.967** |
| **MRR** | **0.878** | 0.217 | **0.872** |
| **Precision@5** | 0.220 | — | **0.227** |
| **Recall@5** | 0.917 | — | **0.950** |

*Evidence:* `evaluation/reports/retrieval_eval_{vector,keyword,hybrid}_20260906_*.json` + console logs. Hybrid slightly beats Vector (Hit@5 0.967 vs 0.933) and dramatically beats Keyword (0.233) on semantic-heavy dataset; Keyword only wins on exact underscore terms but hybrid retains via fusion.

### By Category (Hybrid — shows strengths/weaknesses)

| Category | Hit@5 Vector | Hit@5 Keyword | Hit@5 Hybrid | MRR Hybrid |
|---|---:|---:|---:|---:|
| **semantic** | 1.000 | 0.000 | **1.000** | 0.889 |
| **keyword** | 0.833 | 0.500 | **1.000** | 0.889 |
| **factual** | 1.000 | 0.286 | **1.000** | 1.000 |
| **multi_hop** | 1.000 | 0.500 | **1.000** | 1.000 |
| **ambiguous** | 0.750 | 0.250 | **0.750** | 0.458 |

*Insight:* Hybrid repairs Keyword's weakness on semantic/factual (keyword 0.000 on semantic vs hybrid 1.000). Ambiguous is hardest for all (0.75) — vague queries like "How does it work?" rank Technical Docs vs Handbook.

### By Difficulty

| Difficulty | Hit@5 Hybrid | MRR Hybrid |
|---|---:|---:|
| easy | 1.000 | 0.950 |
| medium | 1.000 | 0.879 |
| hard | 0.889 | 0.778 |

Hard multi-hop/ambiguous drive failures.

## Failure Analysis

### Failures (hybrid, 1/30 misses)

```
- eval_026 [ambiguous/hard] "How does it work?" → rank None (miss) — expected Technical Docs, retrieved Support FAQ/Handbook; ambiguous query has no strong signal, all retrievers miss.
```

Full list in `reports/retrieval_eval_hybrid_*.md` under `## Failures`.

### Worst 10 Queries (lowest MRR)

| Rank | Case | Query | Category | First Rank | Status |
|---|---:|---|---|---|---|
| 1 | eval_026 | How does it work? | ambiguous | None | MISS |
| 2 | eval_013 | RRF_K=60 | keyword | 3 | WEAK |
| 2 | eval_028 | Tell me about the policy | ambiguous | 3 | WEAK |
| 4 | eval_001 | How do I get my money back after buying a plan? | semantic | 2 | OK |
| 4 | eval_027 | What are the limits? | ambiguous | 2 | OK |

*Why failed:* eval_026/028/027 are ambiguous with no lexical anchor; eval_013 `RRF_K=60` exact keyword is rare and vector dominates. Hybrid still retrieves 3rd rank, not top.

### Top-K Configuration

Runner supports `--top-k 1|3|5|10` and `top_k_values=[1,3,5,10]` in config snapshot. Baseline recorded with `top_k=5 candidate_k=30 rrf_k=60`.

## Baseline Management

**Save:** `python scripts/evaluate_retrieval.py --retriever hybrid --save-baseline` → `evaluation/baselines/retrieval_baseline_hybrid_v1.0.json` + `_latest.json` (`app/services/evaluation/baseline.py:22`).

Contains: `metrics`, `dataset_version`, `config`, `timestamp`, `git_commit` (via `git rev-parse --short HEAD`).

**Load:** `BaselineManager.load_latest(retriever="hybrid")`.

## Regression Detection

**Check:** `python scripts/evaluate_retrieval.py --retriever hybrid --compare-baseline`

Thresholds (`app/services/evaluation/schemas.py:110` + `regression.py:12`):

```python
RegressionThresholds(mrr_max_regression=0.02, hit_at_5_max_regression=0.02, hit_at_1_max_regression=0.05)
```

**Statuses:**

- **PASS** — delta >=0 or within threshold
- **WARNING** — regression 1–2% (e.g., MRR -1.5%)
- **FAIL** — regression >2% (e.g., Hit@5 0.95 → 0.87 = -8.4% FAIL)

Example output:

```
MRR: baseline 0.872 -> current 0.872 delta +0.0% status PASS
Hit@5: baseline 0.967 -> current 0.967 delta +0.0% status PASS
PASS: No meaningful regression
```

Run before and after any retrieval change; CI can fail on `FAIL`.

## Fixture Seeding & Isolation

**Isolated:** Dedicated `eval-org` (`eval-org` slug) + `eval-kb` under it, not production `ragforge` org. Tenant isolation via `organization_id` foreign key.

**Script:** `backend/scripts/seed_evaluation_data.py`

```bash
python scripts/seed_evaluation_data.py              # create org/kb, ingest 5 fixtures via real chunker + embedding pipeline, verify 15 chunks
python scripts/seed_evaluation_data.py --reset      # delete only eval org/kb (never user data), then recreate
python scripts/seed_evaluation_data.py --reset-only # delete only
```

Uses real `RecursiveTextChunker` (1000/150) + `EmbeddingService.process_document_embeddings` (singleton `BAAI/bge-small-en-v1.5` or `all-MiniLM-L6-v2`). Logs: "Ingested ... 3 chunks, Embedded ..., Verification: 15 chunks, 15 embedded".

**Reset safety:** Explicit `WHERE slug='eval-org'`, never `DELETE FROM organizations` bare; `OrganizationMembership` and `Document` scoped.

## How To Run

```bash
# 1. Seed fixtures (isolated, real pipeline)
python backend/scripts/seed_evaluation_data.py --reset

# 2. Evaluate one retriever
python backend/scripts/evaluate_retrieval.py --retriever hybrid --top-k 5

# 3. Evaluate all + compare
python backend/scripts/evaluate_retrieval.py --retriever all --top-k 5

# 4. Save baseline (after establishing)
python backend/scripts/evaluate_retrieval.py --retriever hybrid --top-k 5 --save-baseline
python backend/scripts/evaluate_retrieval.py --retriever vector --top-k 5 --save-baseline
python backend/scripts/evaluate_retrieval.py --retriever keyword --top-k 5 --save-baseline

# 5. Check regression after change
python backend/scripts/evaluate_retrieval.py --retriever hybrid --compare-baseline

# 6. Custom dataset/top-k
python backend/scripts/evaluate_retrieval.py --dataset evaluation/datasets/retrieval_baseline.json --top-k 10 --output evaluation/reports

# 7. Legacy dataset (auto-migrated)
python backend/scripts/evaluate_retrieval.py --dataset backend/app/evaluation/datasets/retrieval_examples.json
```

**CLI flags:** `--retriever {vector,keyword,hybrid,all}` `--dataset` `--top-k` `--candidate-k` `--output` `--save-baseline` `--compare-baseline` `--verbose`.

No Groq/LLM needed; no external API.

## Tests

**Location:** `backend/tests/evaluation/`

- `test_metrics.py` — Hit@K, MRR, Precision, Recall, aggregation, duplicates, empty, multiple relevant, no relevant, k=0
- `test_dataset.py` — duplicate IDs, missing expected, invalid category, missing query, legacy conversion
- `test_runner.py` — adapter registry, mock adapter, top-k config
- `test_reporting.py` — console/JSON/Markdown generation
- `test_regression.py` — PASS/WARNING/FAIL thresholds
- `test_integration.py` — full pipeline: in-memory DB → seed 2 docs → embed → vector/keyword/hybrid → metrics → report

**Existing:** `backend/tests/test_retrieval_evaluation.py` (3 metrics tests) still passes.

Run:

```bash
backend\.venv\Scripts\python.exe -m pytest backend/tests/evaluation -v
# 21 passed
backend\.venv\Scripts\python.exe -m pytest backend/tests/test_retrieval_evaluation.py -v
# 3 passed
```

## Documentation & Future Compatibility

- **Not added:** LLM-as-judge, RAGAS, Cross-Encoder reranker, HyDE, query router, multi-query, semantic caching — Phase 2.0 is baseline only.
- **Extensible:** `ADAPTER_REGISTRY` in `runner.py` allows future `HybridRerankedAdapter`, `QueryRouterAdapter`, `HyDEAdapter` without rewrite; `EvaluationCase` supports `tags` and `chunk_content_snippet` for future chunk-level or graded relevance (0-3).
- **Determinism:** Same dataset + same DB (eval-org, 15 chunks) + same embedding model + same `top_k` → same `Hit@K/MRR` (verified via re-evaluation: hybrid 0.967, vector 0.933).

## Limitations & Next Steps (Phase 2.2)

- Keyword retriever weak on semantic (Hit@5 0.233) — will test if reranking improves.
- Ambiguous category (Hit@5 0.75) — needs query routing or multi-query.
- Only 15 chunks; scale to 500k and re-measure HNSW selection (per Phase 1.6).
- Add reranker adapter and re-run baseline comparison: `Hybrid MRR 0.872 → Hybrid+Reranker MRR ?`

```
CHANGE → EVALUATE → METRICS → IMPROVED/REGRESSED → KEEP/REVERT
```

## Reports Generated

- `backend/evaluation/reports/retrieval_eval_{hybrid,vector,keyword}_*.json` (machine-readable, includes per-case ranks, scores, duration)
- `backend/evaluation/reports/retrieval_eval_{hybrid,vector,keyword}_*.md` (human-readable, console summary + failures + worst queries)
- `backend/evaluation/baselines/retrieval_baseline_*_v1.0.json` (versioned, with config snapshot and git commit)

Use these for every future AI engineering decision.
