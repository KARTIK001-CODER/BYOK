# Evaluation Datasets

## Retrieval Baseline v1.0

- **File:** `retrieval_baseline.json`
- **Version:** 1.0
- **Cases:** 30
- **Distribution:**
  - Semantic: 9 (30%)
  - Keyword: 6 (20%)
  - Factual: 6 + 1 (23%) — includes mixed
  - Multi-hop: 4 (13%)
  - Ambiguous: 4 (13%) + 1 mixed
- **Fixture documents (stable identifiers use `document_name`):**
  - `Company Handbook` — `evaluation/fixtures/company_handbook.md`
  - `Refund Policy` — `refund_policy.md`
  - `Pricing` — `pricing.md`
  - `Technical Docs` — `technical_docs.md`
  - `Support FAQ` — `support_faq.md`

## Stable Identifiers

Do NOT use volatile DB `document_id` or `chunk_id`. Use `document_name` (fixture title) as stable key. `chunk_content_snippet` is reserved for future chunk-level relevance. All cases include at least one `document_name` in `expected`.

## Categories

- **semantic:** paraphrased, requires embedding understanding
- **keyword:** exact terms like `cancellation_fee`, `vector_cosine_ops`, `pool_size=10`
- **factual:** direct lookup (e.g., "maximum file size")
- **multi_hop:** requires 2+ documents (e.g., refund + trial)
- **ambiguous:** vague query with expected single best doc

## Relevance

Binary for v1.0: `relevance_grade: 1` = relevant, `0` = not. Schema supports 0-3 graded future.

## Versioning

Bump `version` on any change to expected relevance or query set. Baseline snapshots store `dataset_version`.

## Adding Fixtures

Add future adapters (reranker, query router, HyDE) without changing this dataset — they consume same `EvaluationCase`.
