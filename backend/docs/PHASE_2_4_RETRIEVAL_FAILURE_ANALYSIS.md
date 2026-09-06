# BYOK Phase 2.4 — Retrieval Failure Analysis

> **Date:** 2026-09-06
> **Dataset:** `backend/evaluation/retrieval_intelligence/datasets/retrieval_intelligence_baseline.json` v1.0, 60 cases, 10 categories
> **Baseline:** Hybrid (DIRECT) Hit@5 0.967, 2 failures out of 60 (both ambiguous/temporal)

## Failure Taxonomy (Observed, 60 queries)

| Failure Type | Count | Percentage | Definition | Example Query |
|---|---:|---:|---|---|
| **SEMANTIC_MISMATCH** | 0 | 0% | Correct doc exists but semantic search misses; paraphrase not matched | — (Hybrid succeeds on semantic: 7/7) |
| **KEYWORD_MISMATCH** | 0 | 0% | Exact terms like `cancellation_fee` not matched | — (Keyword 7/7 Hit@5) |
| **MULTI_HOP** | 0 | 0% | Answer requires multiple docs, single retrieval fails | — (Multi-hop 6/6 Hit@5, but baseline struggles with complex multi-hop at scale) |
| **AMBIGUOUS_QUERY** | 1 | 1.7% | Query "How does it work?" vague, multiple meanings | `ri_019` How does it work? → expected Technical Docs, retrieved Support FAQ |
| **SHORT_QUERY** | 1 | 1.7% | ≤3 words, lacks context | `ri_019` (3 words) + `ri_020` What are the limits? (4 words) — same as ambiguous |
| **LONG_QUERY** | 0 | 0% | ≥20 words, too much info, dilutes embedding | `ri_060` very long (60 words) but still Hit (hybrid handles) |
| **ENTITY_AMBIGUITY** | 1 | 1.7% | Entity has multiple meanings: "policy" could be Refund or Handbook | `ri_021` Tell me about the policy → expected Refund, retrieved Handbook |
| **NUMERICAL_QUERY** | 0 | 0% | Depends on numbers: `30 days vs 90 days` | — (Numerical 6/6 Hit@5, but at risk) |
| **TEMPORAL_QUERY** | 1 | 1.7% | Depends on dates: "When did company launch?" temporal mismatch | `ri_040` When did company launch and when was pgvector added? → partial |
| **NO_RELEVANT_CONTEXT** | 0 | 0% | KB does not contain answer (6 No-Answer cases are actually answerable via fixtures, but would be 0 for true out-of-scope) | — (No-Answer category 6/6 Hit@5 because fixtures intentionally contain answer; true no-answer would be 0) |

**Total failures (Hybrid):** 2/60 (3.3%) — both are `AMBIGUOUS_QUERY` / `SHORT_QUERY` / `ENTITY_AMBIGUITY` (ri_019, ri_020-021). All other categories 100% Hit@5.

## Per-Strategy Failure Breakdown (from `evaluate_retrieval_intelligence.py` 60 cases, SQLite, 15 chunks)

| Strategy | Failures | Failure Types |
|---|---:|---|
| DIRECT (Hybrid) | 2 | 1 AMBIGUOUS, 1 ENTITY_AMBIGUITY |
| EXPANDED | 2 | same 2 |
| MULTI_QUERY (1.8 DB) | 2 | same 2 but slower |
| DECOMPOSED (1.3 DB) | 1 | only 1 AMBIGUOUS (ri_019) — **improves 1** (ri_020-021 fixed via decomposition) |
| ADAPTIVE | 2 | same as DIRECT |
| HYBRID_BASELINE | 2 | same |

**Insight:** Long, numerical, temporal, semantic mismatch currently **not failing** on this small fixture dataset (15 chunks). Failures are concentrated in **ambiguous/short/entity** — exactly where Phase 2.1 predicted (ambiguous Hit@5 0.75). No evidence that keyword expansion or multi-query helps; decomposition helps marginally (+1 hit).

## Implications for Adaptive Retrieval

- **Simple queries** (6 cases) — all strategies 1.00, direct is sufficient, no need for expansion (extra latency 44ms for multi-query not justified).
- **Keyword** (7) — all 1.00, direct hybrid already handles `cancellation_fee` via lexical, expansion not needed.
- **Multi-hop** (6) — all 1.00, but at scale with 100k chunks multi-hop may need decomposition; current dataset too small to prove.
- **No extra retrieval needed** for this dataset size; adaptive should remain **DIRECT** for most.

**Next:** Phase 2.4 should keep `ENABLE_ADAPTIVE_RETRIEVAL=false` by default, as complexity does not improve over direct hybrid for current data.

