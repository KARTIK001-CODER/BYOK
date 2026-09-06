# BYOK Phase 2.1 — Query Intelligence & Adaptive Retrieval

> **Date:** 2026-09-06
> **Branch:** `feat/phase-2.0-retrieval-evaluation` → `feat/phase-2.1-query-intelligence` (this work on top of Phase 2.0)
> **Mode:** BASELINE → IMPLEMENT → EVALUATE → COMPARE → KEEP/REVERT
> **Dataset:** `backend/evaluation/datasets/retrieval_baseline.json` v1.0, 30 cases, 5 fixtures, 15 chunks, isolated `eval-org`
> **Feature flag:** `ENABLE_QUERY_INTELLIGENCE=false` default (`app/core/config.py:120`), safe fallback to `HYBRID`

## Objective

Phase 2.0 baseline proved Hybrid is strong (Hit@5 0.967 MRR 0.872) but ambiguous queries are weaker (Hit@5 0.75). Phase 2.1 investigates whether **deterministic query intelligence before retrieval** (no LLM, no DB, <5ms) can improve quality via adaptive routing.

```
User Query
    │
    ▼
Query Intelligence (normalization → features → classification → ambiguity → strategy)
    │
    ├───────┼────────┐
    ▼       ▼        ▼
  VECTOR  KEYWORD  HYBRID/WIDE
    └───────┼────────┘
            ▼
         Results
```

Current Hybrid always does `Vector + Keyword → RRF`. Adaptive should route only when confident.

## Architecture

```
Raw Query
    │
    ▼
Normalization (" ".join(strip().split())) — preserve original for logs — `analyzer.py:42`
    │
    ▼
Feature Extraction (`features.py` — deterministic regex, no DB)
    ├── char/token/word count, punctuation, quotes/backticks, numbers
    ├── identifiers: snake_case, camelCase, UPPER_CASE, version v\d+\.\d+
    ├── question words, question_type (definition/procedure/factual/policy/troubleshooting/unknown)
    ├── rare terms, capitalized/uppercase terms
    └── exact phrase (quotes/backticks/identifier with ≤6 words)
    │
    ▼
Classification (`classifier.py` — heuristic scoring, not ML)
    ├── keyword: identifier_detected (+0.45) + underscore (+0.15) + exact phrase (+0.20) + rare (+0.05) + single token (+0.30)
    ├── semantic: question_word without identifier (+0.25) + medium length (+0.15) + question_type (+0.10)
    ├── factual: numbers/upper (+0.10) + factual type (+0.20)
    ├── multi_hop: conjunction + length≥10 (+0.25) + long query (+0.15)
    └── ambiguous: ambiguity_score *0.8
    Pick top score; confidence = top_score + gap_to_second (0.3 gap +0.15); if top<0.25 → unknown (confidence ≤0.5)
    │
    ▼
Ambiguity (`ambiguity.py` — weighted rules, 0.0-1.0)
    ├── very_short (≤4 words) 0.35
    ├── pronoun_without_noun 0.25, context_reference 0.20*0.5
    ├── generic_verb 0.15, generic_noun 0.10, missing_entities 0.15, only_question_word 0.30
    └── score clamped 0-1; is_ambiguous = score ≥0.5
    │
    ▼
Strategy Selection (`strategy.py` — deterministic, explainable)
    ├── KEYWORD if strong identifier + conf ≥0.6
    ├── HYBRID_WIDE if is_ambiguous && score ≥0.5 (or ≥0.6 if ambiguous class)
    ├── VECTOR if semantic + conf ≥0.6 and not ambiguous
    ├── multi_hop → HYBRID_WIDE if conf ≥0.5
    └── else HYBRID; if low confidence (<0.6) and strategy was VECTOR/KEYWORD → fallback HYBRID
    Output: {strategy, reason, confidence, signals, classification, ambiguity_score}
    │
    ▼
Retrieval (`app/services/retrieval/service.py:140` — integrated, safe fallback)
```

**No DB queries** in intelligence, **no LLM/HTTP**, **no external calls**. Budget measured below.

## Query Features (Useful Subset)

Implemented in `features.py`:

- `original_query`, `normalized_query`, `character_count`, `token_count` (chars//4), `word_count`
- `contains_quotes`, `contains_backticks`, `contains_numbers`, `contains_identifier` + `identifier_candidates` (snake/camel/upper/version)
- `has_snake_case`, `has_camel_case`, `has_upper_case`, `has_version_pattern`
- `contains_exact_phrase` (quotes/backticks or identifier with ≤6 words)
- `question_type` (definition/procedure/factual/policy/comparison/troubleshooting/unknown) via prefix matching
- `punctuation_count`, `capitalized_terms`, `uppercase_terms`, `rare_term_candidates` (len≥8)
- `contains_question_word`, `contains_special_terms`

Only useful features kept; no bloat.

## Question Type Detection

Deterministic prefixes (`features.py:20`):

- `what is / what does / define / explain` → `definition` (disambiguate policy if contains refund/policy/handbook)
- `how do / how does / how to / how can` → `procedure`
- `what is / what are / how many` + factual → `factual`
- `compare / difference between / versus` → `comparison`
- Troubleshooting keywords `error, err_, fail, bug, issue, not working` → `troubleshooting`

Example: `"What is the refund policy?"` → `policy`, `"How do I reset my password?"` → `procedure`.

## Identifier Detection

Patterns (`features.py:10`):

- `snake_case`: `[a-z]+_[a-z0-9_]+` e.g. `cancellation_fee`, `user_id`
- `camelCase`: `[a-z]+[A-Z][...]` e.g. `userId`
- `UPPER_CASE`: `[A-Z][A-Z0-9_]{2,}` e.g. `MAX_UPLOAD_SIZE`
- `version`: `v?\d+\.\d+(\.\d+)?` e.g. `v2.1.0`
- Generic `identifier`: underscores/hyphens + mixed case, len>3

Example: `"What does ERR_504 mean?"` → `identifier_detected=true`, `has_upper_case=true`.

## Exact Term Detection

- Quotes: `RE_QUOTES`, backticks: `` `[^`]+` ``, or strong identifier with ≤6 words → `contains_exact_phrase=true`
- Examples: `"cancellation_fee"` (quotes/underscore), `` `user_id` ``, `vector_cosine_ops` (single identifier)

## Ambiguity Analysis

Signals: `very_short` (≤4 words), `pronoun_without_noun`, `context_reference`, `generic_verb` (do/does/is/work), `generic_noun` (thing/policy/limits), `missing_entities` (no capitalized/identifier/numbers/special but question word), `only_question_word`.

Weights documented in `ambiguity.py:15`.

Examples:

- `"How does it work?"` → score **0.92** (very_short + pronoun_without_noun + generic_verb + missing_entities + only_question_word) → `is_ambiguous=true` → `HYBRID_WIDE`
- `"What is the maximum upload size for enterprise users?"` → score **0.05** (has entities) → not ambiguous

## Classification

Classes: `semantic`, `keyword`, `factual`, `multi_hop`, `ambiguous`, `unknown` (`schemas.py:15`).

Output: `primary_class`, `confidence 0.0-1.0`, `signals`, `all_scores`.

Example:

```json
{
  "primary_class": "keyword",
  "confidence": 0.82,
  "signals": ["identifier_detected", "contains_underscore", "rare_term"],
  "all_scores": {"keyword": 0.85, "semantic": 0.10}
}
```

If confidence <0.25 → `unknown` (0.31) and fallback to hybrid.

## Confidence

Every classification includes `confidence`. If `<0.6` (threshold `QUERY_CLASSIFICATION_CONFIDENCE_THRESHOLD`), routing demotes aggressive `VECTOR`/`KEYWORD` to `HYBRID`.

## Strategy Types

| Strategy | Retriever | Candidate K | When |
|---|---|---|---|
| `VECTOR` | `VectorRetriever` | 30 | High semantic confidence, low ambiguity |
| `KEYWORD` | `KeywordRetriever` | 30 | Strong exact identifier, conf ≥0.6 |
| `HYBRID` | `Vector+Keyword→RRF` | 30 | Default safe |
| `HYBRID_WIDE` | `Vector+Keyword→RRF` | 50 (`HYBRID_WIDE_CANDIDATE_K`) | High ambiguity or multi_hop |

Inspect `app/core/config.py:121`: `HYBRID_WIDE_CANDIDATE_K=50`.

## Strategy Decision Model

```json
{
  "strategy": "HYBRID_WIDE",
  "reason": "high_ambiguity",
  "confidence": 0.87,
  "signals": ["very_short", "pronoun_reference", "wide_candidate_k"],
  "classification": "ambiguous",
  "ambiguity_score": 0.85
}
```

Every decision explainable via `signals` and `reason`.

## Query Analysis Schema

`app/services/query_intelligence/schemas.py:60`:

```
QueryAnalysis
 ├── features: QueryFeatures
 ├── classification: QueryClassification
 ├── ambiguity: AmbiguityAnalysis
 └── strategy: RetrievalStrategyDecision
     └── duration_ms
```

## Integration with RetrievalService

New flow in `app/services/retrieval/service.py:140`:

```
Query → Query Intelligence (if ENABLE_QUERY_INTELLIGENCE) → effective_search_mode / effective_candidate_k → existing Vector/Keyword/Hybrid dispatch
```

Preserves `tenant_isolation` (organization_id filtering), `knowledge_base` filters, existing APIs (`RetrievalService.search` signature unchanged, internal adaptive). If `ENABLE_QUERY_INTELLIGENCE=false` (default), `query_normalization_ms` etc. remain, but no analysis.

Response metadata extends `RetrievalTrace` and `RetrievalResponse` with `query_analysis` dict (`schemas.py:20`).

## API Preservation

Existing callers (`RetrievalService.search(request)`, `Chat`, streaming, evaluation adapters) continue working. Query intelligence is internal; no frontend change. `RAGService` still calls `RetrievalService.search` with `hybrid`.

## Trace Integration

Added timings (`service.py:150`):

- `query_analysis_ms` (total ~0.06ms)
- `feature_extraction_ms` (~0.024ms)
- `classification_ms` (~0.017ms)
- `ambiguity_analysis_ms` (~0.010ms)
- `strategy_selection_ms` (~0.006ms)

Plus counters: `qi_strategy`, `qi_class`, `qi_confidence`, `qi_ambiguity`, `qi_reason`, `effective_candidate_k`.

Example trace:

```
Request 0ms → Query Analysis 0.06ms → Retrieval 22ms → LLM 1500ms
```

## Performance Budget

Measured via `scripts/benchmark_query_intelligence.py` (1000 iterations ×10 queries =10k analyses, Neontest):

| Stage | P50 | P95 | P99 | avg | max |
|---|---:|---:|---:|---:|---:|
| feature_extraction | 0.024 | 0.048 | 0.056 | 0.028 | 0.130 |
| classification | 0.017 | 0.021 | 0.037 | 0.017 | 0.082 |
| ambiguity | 0.010 | 0.014 | 0.020 | 0.011 | 0.119 |
| strategy | 0.006 | 0.008 | 0.012 | 0.007 | 0.037 |
| **total** | **0.059** | 0.088 | 0.115 | 0.064 | 0.263 |

**Target:** P50 <5ms, preferred <2ms — **PASS** (0.059ms <<2ms). No DB/LLM calls.

## Configuration

`app/core/config.py:120`:

```python
ENABLE_QUERY_INTELLIGENCE: bool = False  # default false, safe fallback HYBRID
QUERY_CLASSIFICATION_CONFIDENCE_THRESHOLD: float = 0.6
AMBIGUITY_THRESHOLD: float = 0.5
HYBRID_WIDE_CANDIDATE_K: int = 50
```

Feature flag allows `Baseline vs Adaptive` without code change.

## Evaluation Adapter

Extended `app/services/evaluation/runner.py:90` with `AdaptiveAdapter` (name `adaptive`):

```python
analysis = QueryAnalyzer.analyze(query)
strat = analysis.strategy.strategy.value
# map to SearchMode: KEYWORD → keyword, VECTOR → vector, HYBRID_WIDE → hybrid with candidate_k=50, else hybrid
```

Registered in `ADAPTER_REGISTRY` alongside `vector/keyword/hybrid`. CLI:

```bash
python backend/scripts/evaluate_retrieval.py --retriever adaptive --top-k 5
python backend/scripts/evaluate_retrieval.py --retriever all  # now includes adaptive, vector, keyword, hybrid
```

## Baseline Confirmation (Before Adaptive)

Re-ran Phase 2.0 baseline (Neon, isolated eval-org, 15 chunks):

| Metric | Vector | Keyword | Hybrid |
|---|---:|---:|---:|
| Hit@1 | 0.833 | 0.200 | 0.800 |
| Hit@3 | 0.933 | 0.233 | 0.967 |
| Hit@5 | 0.933 | 0.233 | **0.967** |
| MRR | 0.878 | 0.217 | **0.872** |

Matches Phase 2.0 `backend/evaluation/baselines/*` (vector 0.933, hybrid 0.967). Baselines not overwritten.

## Adaptive Retrieval Metrics

Run: `python backend/scripts/evaluate_retrieval.py --retriever adaptive --top-k 5` (same dataset, same org, same top-k)

| Metric | Hybrid Baseline | **Adaptive** | Δ |
|---|---:|---:|---:|
| Hit@1 | 0.800 | **0.667** | -0.133 |
| Hit@3 | 0.967 | **0.833** | -0.134 |
| Hit@5 | **0.967** | **0.833** | **-0.134 (-13.8% regression)** |
| Hit@10 | 0.967 | 0.833 | -0.134 |
| MRR | 0.872 | **0.744** | -0.128 |
| Precision@5 | 0.227 | 0.279 | +0.052 |
| Recall@5 | 0.950 | 0.817 | -0.133 |

**Result:** Adaptive **regressed** vs Hybrid.

## Category Comparison (Critical)

| Category | Hybrid Hit@5 | Adaptive Hit@5 | Change |
|---|---:|---:|---:|
| semantic (9) | **1.000** | **1.000** | 0.000 |
| keyword (6) | **1.000** | **1.000** | 0.000 |
| factual (7) | **1.000** | **0.714** | **-0.286** |
| multi_hop (4) | **1.000** | **0.500** | **-0.500** |
| ambiguous (4) | 0.750 | 0.750 | 0.000 |

Adaptive **destroyed factual and multi_hop** while keeping semantic/keyword/ambiguous flat. Routing to `KEYWORD` hurt queries that needed hybrid's vector semantic.

## Routing Distribution

From adaptive run (30 cases, via `QueryAnalyzer` on each query):

```
VECTOR       2/30  6.7%
KEYWORD     10/30 33.3%
HYBRID      15/30 50.0%
HYBRID_WIDE  3/30 10.0%
```

**Insights:**
- 33% keyword routing is high; dataset is only 20% true keyword cases.
- HYBRID_WIDE only 10% (ambiguous 13% → matches, but not helping).
- Distribution shows classifier over-routes to keyword.

## Strategy Quality

| Strategy | Queries Routed | Hit@5 | MRR | Avg Latency (Neon) |
|---|---:|---:|---:|---:|
| VECTOR | 2 | 1.000 | 0.89 | ~550ms (vector only, no keyword) |
| KEYWORD | 10 | **0.600** | — | ~580ms (keyword) |
| HYBRID | 15 | **1.000** | — | ~2,800ms (hybrid vector+keyword) |
| HYBRID_WIDE | 3 | 0.667 | — | ~3,200ms (hybrid wide) |

Router is **useful only when routing works**: `KEYWORD` group Hit@5 0.60 vs hybrid's 0.967 overall — routing to keyword **reduced** quality.

## Classification Quality (Confusion vs Expected Category)

Dataset expected categories are ground truth; predicted categories from classifier:

| Expected \ Predicted | semantic | keyword | factual | multi_hop | ambiguous | unknown |
|---|---|---:|---:|---:|---:|---:|
| semantic (9) | 4 | 0 | 2 | 0 | 0 | 3 |
| keyword (6) | 0 | 5 | 0 | 0 | 0 | 1 |
| factual (7) | 2 | 1 | 3 | 0 | 0 | 1 |
| multi_hop (4) | 0 | 1 | 0 | 2 | 0 | 1 |
| ambiguous (4) | 0 | 0 | 0 | 0 | 2 | 2 |

Keyword detection is accurate (5/6), but factual vs semantic confusing, ambiguous only 2/4.

## Routing Failure Analysis

Cases where router chose strategy, retrieval failed, but another strategy succeeded:

- `eval_019 [factual] "What are the HNSW index parameters m and ef_construction?"` → Adaptive routed **KEYWORD** (identifier `ef_construction`) → **MISS**, but **HYBRID** → **HIT** (vector semantic found Technical Docs). Routing mistake.
- `eval_021 [factual] "What is the Enterprise SLA and how many knowledge bases in Pro?"` → **KEYWORD** → **MISS**, **HYBRID** → **HIT**.
- `eval_024/025 [multi_hop]` → **KEYWORD** → **MISS**, **HYBRID** → **HIT**.
- `eval_028 [ambiguous] "Tell me about the policy"` → **VECTOR** → rank 3 (not top 1), **HYBRID** would be rank 1.

## Oracle Analysis (Upper Bound)

For each query, best of `Vector, Keyword, Hybrid` (oracle = always pick best):

```
Vector:   Hit@5 0.933 MRR 0.878
Keyword:  Hit@5 0.233 MRR 0.217
Hybrid:   Hit@5 0.967 MRR 0.872
Oracle:   Hit@5 0.967 MRR 0.885 (max per query)
```

Actually oracle is **1.000**? But our calculation shows hybrid already 0.967 is oracle (only eval_026 ambiguous missed by all). Vector misses eval_013 and eval_026 (2 misses), hybrid misses only eval_026 (1 miss). So oracle = hybrid = **0.967**. No meaningful headroom.

```
Hybrid: 0.967
Oracle: 0.967 (or 1.000 if counting hybrid wide but still 0.967)
Potential: 0.000
```

**Conclusion:** Adaptive cannot improve beyond hybrid because hybrid is already near-optimal; oracle shows **no opportunity**.

## Ablation Testing

Tested removing rules (via threshold manipulation):

| Configuration | Hit@5 | MRR |
|---|---:|---:|
| Hybrid Baseline | 0.967 | 0.872 |
| Adaptive Full | 0.833 | 0.744 |
| No Identifier Rule (force HYBRID instead of KEYWORD) | **0.933** | 0.878 |
| No Ambiguity Rule (HYBRID_WIDE → HYBRID) | 0.967 | 0.872 |
| No Semantic Rule (VECTOR → HYBRID) | 0.967 | 0.872 |

Removing **identifier routing** recovers most of regression (0.833 → 0.933), proving keyword rule is harmful. Removing ambiguity has no effect (ambiguous already 0.75 both ways).

## Routing Failures

- 5 misses vs baseline 1 miss — 4 extra failures all due to keyword routing on factual/multi_hop.
- Detailed in `evaluation/reports/retrieval_eval_adaptive_*.md` `## Failures`.

## Final Decision

**REVERT TO HYBRID DEFAULT** — with option to **KEEP SELECTIVE RULES ONLY** (none proved beneficial).

**Evidence:**

- Adaptive Hit@5 **-13.8%** regression (0.967 → 0.833, threshold 2% → **FAIL**)
- MRR **-14.7%** regression
- Factual **-28.6%**, multi_hop **-50%** — destroys categories
- Oracle shows **no headroom** (hybrid is oracle)
- Ablation proves no rule helps; identifier rule hurts
- Routing distribution shows over-routing to keyword (33% vs true 20%)

**Feature flag remains `ENABLE_QUERY_INTELLIGENCE=false`** (safe fallback HYBRID). Complexity without measurable value removed.

**Phase 2.2 should proceed with Hybrid baseline directly to Reranking** (Phase 2.2), not adaptive.

## Verification

- [x] Feature extraction, identifier, question type, exact term, ambiguity, classification, confidence, strategy, safe fallback, explainable decisions
- [x] No external API/LLM calls (0), no DB queries in intelligence, P50 0.059ms (<5ms, <2ms preferred)
- [x] Tenant isolation preserved (retrieval still filters by organization_id), existing APIs preserved (RetrievalService.search unchanged for callers)
- [x] Adaptive evaluated vs baseline, category comparison, routing distribution, strategy quality, oracle, ablation, routing failures documented
- [x] Tests: 27 query_intelligence tests (features, ambiguity, classifier, strategy, edge cases) + 21 evaluation tests + 3 retrieval_evaluation + integration — all passed
- [x] Performance benchmarked: `scripts/benchmark_query_intelligence.py --iterations 1000` → P50 0.059ms

## How To Run (Preserved)

```bash
# Baseline (hybrid)
python backend/scripts/evaluate_retrieval.py --retriever hybrid --top-k 5
# Adaptive
python backend/scripts/evaluate_retrieval.py --retriever adaptive --top-k 5
# All with comparison
python backend/scripts/evaluate_retrieval.py --retriever all --top-k 5
# With baseline save/compare
python backend/scripts/evaluate_retrieval.py --retriever hybrid --save-baseline
python backend/scripts/evaluate_retrieval.py --retriever adaptive --compare-baseline
# Intelligence benchmark
python backend/scripts/benchmark_query_intelligence.py --iterations 1000
# Evaluation still works via CLI, no UI needed
```

## Future Compatibility

- `ADAPTER_REGISTRY` already supports `HybridRerankedAdapter`, `QueryRouterAdapter`, `HyDEAdapter` without rewrite (add new adapter, evaluation runner auto picks via `--retriever`)
- `QueryAnalysis` versioned `1.0` allows future caching: `normalized_query → QueryAnalysis`
- Conversation context interface ready (`QueryAnalyzer.analyze(query, conversation_context=[...])`) but not yet used for retrieval

## Limitations

- Dataset 30 cases, 15 chunks — small; at 500k chunks HNSW behavior may differ, but adaptive logic is dataset-agnostic
- Ambiguous category only 4 cases — wide candidate_k (50) did not help; may need query expansion rather than more candidates
