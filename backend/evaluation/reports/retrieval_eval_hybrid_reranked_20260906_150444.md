# Retrieval Evaluation — hybrid_reranked (top_k=5)

- **Dataset:** `C:\Users\karti\OneDrive\Desktop\Projects\BYOK\backend\evaluation\datasets\retrieval_baseline.json` v`1.0`
- **Cases:** 30
- **Timestamp:** 2026-09-06T15:04:44.500667+00:00
- **Commit:** `99c26bd`
- **Config:** `embedding=sentence-transformers/all-MiniLM-L6-v2 dim=384 candidate_k=30 rrf_k=60`

## Overall Metrics

| Metric | Value |
|---|---:|
| Hit@1 | 0.500 |
| Hit@3 | 0.800 |
| Hit@5 | 0.967 |
| Hit@10 | 0.967 |
| MRR | 0.674 |
| NDCG@3 | 0.881 |
| NDCG@5 | 1.166 |
| NDCG@10 | 1.166 |
| Precision@5 | 0.213 |
| Recall@5 | 0.917 |

## By Category

| Category | Hit@5 | MRR | NDCG@5 | Prec | Recall | Cases |
|---|---:|---:|---:|---:|---:|---:|
| ambiguous | 0.750 | 0.550 | 1.037 | 0.150 | 0.750 | 4 |
| factual | 1.000 | 0.833 | 1.373 | 0.229 | 0.929 | 7 |
| keyword | 1.000 | 0.833 | 1.386 | 0.200 | 1.000 | 6 |
| multi_hop | 1.000 | 0.750 | 1.205 | 0.300 | 0.750 | 4 |
| semantic | 1.000 | 0.465 | 0.897 | 0.200 | 1.000 | 9 |

## By Difficulty

| Difficulty | Hit@5 | MRR | Cases |
|---|---:|---:|---:|
| easy | 1.000 | 0.612 | 10 |
| hard | 0.889 | 0.689 | 9 |
| medium | 1.000 | 0.718 | 11 |

## Failures

- **eval_026** [ambiguous/hard] `How does it work?` — expected `Technical Docs` — retrieved `Support FAQ, Refund Policy, Company Handbook` — rank `None` — `miss`

## Worst Queries

- eval_026 MRR 0.000 rank None — `How does it work?`
- eval_003 MRR 0.200 rank 5 — `What is the hybrid search mechanism that combines vectors and text search?`
- eval_027 MRR 0.200 rank 5 — `What are the limits?`
- eval_006 MRR 0.200 rank 5 — `How much does the Pro tier cost and what does it include?`
- eval_004 MRR 0.200 rank 5 — `Explain how my data stays private and where it is stored`
- eval_001 MRR 0.250 rank 4 — `How do I get my money back after buying a plan?`
- eval_018 MRR 0.333 rank 3 — `What embedding model and dimension does the system use?`
- eval_009 MRR 0.333 rank 3 — `What does the onboarding look like for new engineers?`
- eval_005 MRR 0.500 rank 2 — `I want to understand the company's work-from-home rules`
- eval_020 MRR 0.500 rank 2 — `How many days of annual leave and what is the learning budget?`

## Recommendations

- Baseline is strong; maintain via regression checks.