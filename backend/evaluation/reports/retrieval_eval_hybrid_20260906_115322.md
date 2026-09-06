# Retrieval Evaluation — hybrid (top_k=5)

- **Dataset:** `C:\Users\karti\OneDrive\Desktop\Projects\BYOK\backend\evaluation\datasets\retrieval_baseline.json` v`1.0`
- **Cases:** 30
- **Timestamp:** 2026-09-06T11:53:22.596796+00:00
- **Commit:** `afa12f9`
- **Config:** `embedding=sentence-transformers/all-MiniLM-L6-v2 dim=384 candidate_k=30 rrf_k=60`

## Overall Metrics

| Metric | Value |
|---|---:|
| Hit@1 | 0.800 |
| Hit@3 | 0.967 |
| Hit@5 | 0.967 |
| Hit@10 | 0.967 |
| MRR | 0.872 |
| Precision@5 | 0.227 |
| Recall@5 | 0.950 |

## By Category

| Category | Hit@5 | MRR | Prec | Recall | Cases |
|---|---:|---:|---:|---:|---:|
| ambiguous | 0.750 | 0.458 | 0.150 | 0.750 | 4 |
| factual | 1.000 | 1.000 | 0.257 | 1.000 | 7 |
| keyword | 1.000 | 0.889 | 0.200 | 1.000 | 6 |
| multi_hop | 1.000 | 1.000 | 0.350 | 0.875 | 4 |
| semantic | 1.000 | 0.889 | 0.200 | 1.000 | 9 |

## By Difficulty

| Difficulty | Hit@5 | MRR | Cases |
|---|---:|---:|---:|
| easy | 1.000 | 0.950 | 10 |
| hard | 0.889 | 0.778 | 9 |
| medium | 1.000 | 0.879 | 11 |

## Failures

- **eval_026** [ambiguous/hard] `How does it work?` — expected `Technical Docs` — retrieved `Support FAQ, Company Handbook, Refund Policy` — rank `None` — `miss`

## Worst Queries

- eval_026 MRR 0.000 rank None — `How does it work?`
- eval_013 MRR 0.333 rank 3 — `RRF_K=60`
- eval_028 MRR 0.333 rank 3 — `Tell me about the policy`
- eval_001 MRR 0.500 rank 2 — `How do I get my money back after buying a plan?`
- eval_008 MRR 0.500 rank 2 — `How can I delete my knowledge and what about backups?`
- eval_027 MRR 0.500 rank 2 — `What are the limits?`
- eval_004 MRR 1.000 rank 1 — `Explain how my data stays private and where it is stored`
- eval_003 MRR 1.000 rank 1 — `What is the hybrid search mechanism that combines vectors and text search?`
- eval_010 MRR 1.000 rank 1 — `What is the cancellation_fee?`
- eval_006 MRR 1.000 rank 1 — `How much does the Pro tier cost and what does it include?`

## Recommendations

- Baseline is strong; maintain via regression checks.