# Retrieval Evaluation — vector (top_k=5)

- **Dataset:** `C:\Users\karti\OneDrive\Desktop\Projects\BYOK\backend\evaluation\datasets\retrieval_baseline.json` v`1.0`
- **Cases:** 30
- **Timestamp:** 2026-09-06T11:46:33.493587+00:00
- **Commit:** `afa12f9`
- **Config:** `embedding=sentence-transformers/all-MiniLM-L6-v2 dim=384 candidate_k=30 rrf_k=60`

## Overall Metrics

| Metric | Value |
|---|---:|
| Hit@1 | 0.833 |
| Hit@3 | 0.933 |
| Hit@5 | 0.933 |
| Hit@10 | 0.933 |
| MRR | 0.878 |
| Precision@5 | 0.220 |
| Recall@5 | 0.917 |

## By Category

| Category | Hit@5 | MRR | Prec | Recall | Cases |
|---|---:|---:|---:|---:|---:|
| ambiguous | 0.750 | 0.583 | 0.150 | 0.750 | 4 |
| factual | 1.000 | 1.000 | 0.257 | 1.000 | 7 |
| keyword | 0.833 | 0.833 | 0.167 | 0.833 | 6 |
| multi_hop | 1.000 | 1.000 | 0.350 | 0.875 | 4 |
| semantic | 1.000 | 0.889 | 0.200 | 1.000 | 9 |

## By Difficulty

| Difficulty | Hit@5 | MRR | Cases |
|---|---:|---:|---:|
| easy | 1.000 | 0.950 | 10 |
| hard | 0.889 | 0.833 | 9 |
| medium | 0.909 | 0.849 | 11 |

## Failures

- **eval_013** [keyword/medium] `RRF_K=60` — expected `Technical Docs` — retrieved `Support FAQ, Refund Policy, Support FAQ` — rank `None` — `miss`
- **eval_026** [ambiguous/hard] `How does it work?` — expected `Technical Docs` — retrieved `Refund Policy, Support FAQ, Refund Policy` — rank `None` — `miss`

## Worst Queries

- eval_013 MRR 0.000 rank None — `RRF_K=60`
- eval_026 MRR 0.000 rank None — `How does it work?`
- eval_028 MRR 0.333 rank 3 — `Tell me about the policy`
- eval_001 MRR 0.500 rank 2 — `How do I get my money back after buying a plan?`
- eval_008 MRR 0.500 rank 2 — `How can I delete my knowledge and what about backups?`
- eval_016 MRR 1.000 rank 1 — `What is the maximum file size allowed for uploads?`
- eval_023 MRR 1.000 rank 1 — `What happens when a user cancels during trial and then requests a refund after conversion?`
- eval_027 MRR 1.000 rank 1 — `What are the limits?`
- eval_029 MRR 1.000 rank 1 — `How can I get help?`
- eval_017 MRR 1.000 rank 1 — `How many days of refund eligibility for low usage?`

## Recommendations

- Keyword category weak — verify GIN index and lexical matching.
- Baseline is strong; maintain via regression checks.