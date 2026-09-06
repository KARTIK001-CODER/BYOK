# Retrieval Evaluation — adaptive (top_k=5)

- **Dataset:** `C:\Users\karti\OneDrive\Desktop\Projects\BYOK\backend\evaluation\datasets\retrieval_baseline.json` v`1.0`
- **Cases:** 30
- **Timestamp:** 2026-09-06T12:05:33.805241+00:00
- **Commit:** `de98772`
- **Config:** `embedding=sentence-transformers/all-MiniLM-L6-v2 dim=384 candidate_k=30 rrf_k=60`

## Overall Metrics

| Metric | Value |
|---|---:|
| Hit@1 | 0.667 |
| Hit@3 | 0.833 |
| Hit@5 | 0.833 |
| Hit@10 | 0.833 |
| MRR | 0.744 |
| Precision@5 | 0.279 |
| Recall@5 | 0.817 |

## By Category

| Category | Hit@5 | MRR | Prec | Recall | Cases |
|---|---:|---:|---:|---:|---:|
| ambiguous | 0.750 | 0.458 | 0.150 | 0.750 | 4 |
| factual | 0.714 | 0.714 | 0.171 | 0.714 | 7 |
| keyword | 1.000 | 0.917 | 0.694 | 1.000 | 6 |
| multi_hop | 0.500 | 0.500 | 0.150 | 0.375 | 4 |
| semantic | 1.000 | 0.889 | 0.200 | 1.000 | 9 |

## By Difficulty

| Difficulty | Hit@5 | MRR | Cases |
|---|---:|---:|---:|
| easy | 1.000 | 0.950 | 10 |
| hard | 0.556 | 0.444 | 9 |
| medium | 0.909 | 0.803 | 11 |

## Failures

- **eval_019** [factual/medium] `What are the HNSW index parameters m and ef_construction?` — expected `Technical Docs` — retrieved `` — rank `None` — `miss`
- **eval_021** [factual/hard] `What is the Enterprise SLA and how many knowledge bases in Pro?` — expected `Pricing, Technical Docs` — retrieved `` — rank `None` — `miss`
- **eval_024** [multi_hop/hard] `Explain how a document goes from upload (25 MB limit) through chunking (1000/150) to HNSW indexing` — expected `Technical Docs, Pricing` — retrieved `` — rank `None` — `miss`
- **eval_025** [multi_hop/hard] `How does hybrid retrieval work from query to RRF fusion to context for LLM?` — expected `Technical Docs, Pricing` — retrieved `` — rank `None` — `miss`
- **eval_026** [ambiguous/hard] `How does it work?` — expected `Technical Docs` — retrieved `Support FAQ, Company Handbook, Refund Policy` — rank `None` — `miss`

## Worst Queries

- eval_026 MRR 0.000 rank None — `How does it work?`
- eval_021 MRR 0.000 rank None — `What is the Enterprise SLA and how many knowledge bases in Pro?`
- eval_025 MRR 0.000 rank None — `How does hybrid retrieval work from query to RRF fusion to context for LLM?`
- eval_019 MRR 0.000 rank None — `What are the HNSW index parameters m and ef_construction?`
- eval_024 MRR 0.000 rank None — `Explain how a document goes from upload (25 MB limit) through chunking (1000/150) to HNSW indexing`
- eval_028 MRR 0.333 rank 3 — `Tell me about the policy`
- eval_001 MRR 0.500 rank 2 — `How do I get my money back after buying a plan?`
- eval_027 MRR 0.500 rank 2 — `What are the limits?`
- eval_008 MRR 0.500 rank 2 — `How can I delete my knowledge and what about backups?`
- eval_013 MRR 0.500 rank 2 — `RRF_K=60`

## Recommendations

- Retrieval Hit@5 below 0.85 — consider improving hybrid fusion or candidate_k.
- Multi-hop weak — may need query decomposition or multi-query retrieval (future).
- Baseline is strong; maintain via regression checks.