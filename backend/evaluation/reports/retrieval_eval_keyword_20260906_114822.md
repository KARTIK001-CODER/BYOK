# Retrieval Evaluation — keyword (top_k=5)

- **Dataset:** `C:\Users\karti\OneDrive\Desktop\Projects\BYOK\backend\evaluation\datasets\retrieval_baseline.json` v`1.0`
- **Cases:** 30
- **Timestamp:** 2026-09-06T11:48:22.101044+00:00
- **Commit:** `afa12f9`
- **Config:** `embedding=sentence-transformers/all-MiniLM-L6-v2 dim=384 candidate_k=30 rrf_k=60`

## Overall Metrics

| Metric | Value |
|---|---:|
| Hit@1 | 0.200 |
| Hit@3 | 0.233 |
| Hit@5 | 0.233 |
| Hit@10 | 0.233 |
| MRR | 0.217 |
| Precision@5 | 0.172 |
| Recall@5 | 0.233 |

## By Category

| Category | Hit@5 | MRR | Prec | Recall | Cases |
|---|---:|---:|---:|---:|---:|
| ambiguous | 0.250 | 0.250 | 0.250 | 0.250 | 4 |
| factual | 0.000 | 0.000 | 0.000 | 0.000 | 7 |
| keyword | 1.000 | 0.917 | 0.694 | 1.000 | 6 |
| multi_hop | 0.000 | 0.000 | 0.000 | 0.000 | 4 |
| semantic | 0.000 | 0.000 | 0.000 | 0.000 | 9 |

## By Difficulty

| Difficulty | Hit@5 | MRR | Cases |
|---|---:|---:|---:|
| easy | 0.300 | 0.300 | 10 |
| hard | 0.111 | 0.111 | 9 |
| medium | 0.273 | 0.227 | 11 |

## Failures

- **eval_001** [semantic/easy] `How do I get my money back after buying a plan?` — expected `Refund Policy` — retrieved `` — rank `None` — `miss`
- **eval_002** [semantic/medium] `Tell me how to receive a reimbursement for my subscription` — expected `Refund Policy` — retrieved `` — rank `None` — `miss`
- **eval_003** [semantic/medium] `What is the hybrid search mechanism that combines vectors and text search?` — expected `Technical Docs` — retrieved `` — rank `None` — `miss`
- **eval_004** [semantic/medium] `Explain how my data stays private and where it is stored` — expected `Company Handbook` — retrieved `` — rank `None` — `miss`
- **eval_005** [semantic/easy] `I want to understand the company's work-from-home rules` — expected `Company Handbook` — retrieved `` — rank `None` — `miss`
- **eval_006** [semantic/easy] `How much does the Pro tier cost and what does it include?` — expected `Pricing` — retrieved `` — rank `None` — `miss`
- **eval_007** [semantic/medium] `Describe the chunking process that splits documents` — expected `Technical Docs` — retrieved `` — rank `None` — `miss`
- **eval_008** [semantic/hard] `How can I delete my knowledge and what about backups?` — expected `Support FAQ` — retrieved `` — rank `None` — `miss`
- **eval_009** [semantic/easy] `What does the onboarding look like for new engineers?` — expected `Company Handbook` — retrieved `` — rank `None` — `miss`
- **eval_016** [factual/easy] `What is the maximum file size allowed for uploads?` — expected `Pricing` — retrieved `` — rank `None` — `miss`
- **eval_017** [factual/easy] `How many days of refund eligibility for low usage?` — expected `Refund Policy` — retrieved `` — rank `None` — `miss`
- **eval_018** [factual/easy] `What embedding model and dimension does the system use?` — expected `Technical Docs` — retrieved `` — rank `None` — `miss`
- **eval_019** [factual/medium] `What are the HNSW index parameters m and ef_construction?` — expected `Technical Docs` — retrieved `` — rank `None` — `miss`
- **eval_020** [factual/medium] `How many days of annual leave and what is the learning budget?` — expected `Company Handbook` — retrieved `` — rank `None` — `miss`
- **eval_021** [factual/hard] `What is the Enterprise SLA and how many knowledge bases in Pro?` — expected `Pricing, Technical Docs` — retrieved `` — rank `None` — `miss`
- **eval_022** [multi_hop/hard] `If I buy an annual plan and cancel after 20 days with 30% usage, what refund and fee apply?` — expected `Refund Policy, Pricing` — retrieved `` — rank `None` — `miss`
- **eval_023** [multi_hop/hard] `What happens when a user cancels during trial and then requests a refund after conversion?` — expected `Refund Policy, Support FAQ` — retrieved `` — rank `None` — `miss`
- **eval_024** [multi_hop/hard] `Explain how a document goes from upload (25 MB limit) through chunking (1000/150) to HNSW indexing` — expected `Technical Docs, Pricing` — retrieved `` — rank `None` — `miss`
- **eval_025** [multi_hop/hard] `How does hybrid retrieval work from query to RRF fusion to context for LLM?` — expected `Technical Docs, Pricing` — retrieved `` — rank `None` — `miss`
- **eval_026** [ambiguous/hard] `How does it work?` — expected `Technical Docs` — retrieved `Company Handbook, Support FAQ` — rank `None` — `miss`
- **eval_027** [ambiguous/hard] `What are the limits?` — expected `Pricing` — retrieved `Technical Docs` — rank `None` — `miss`
- **eval_028** [ambiguous/medium] `Tell me about the policy` — expected `Refund Policy` — retrieved `` — rank `None` — `miss`
- **eval_030** [factual/medium] `What is the 25 MB limit and what happens if I exceed it?` — expected `Pricing, Support FAQ` — retrieved `` — rank `None` — `miss`

## Worst Queries

- eval_001 MRR 0.000 rank None — `How do I get my money back after buying a plan?`
- eval_024 MRR 0.000 rank None — `Explain how a document goes from upload (25 MB limit) through chunking (1000/150) to HNSW indexing`
- eval_026 MRR 0.000 rank None — `How does it work?`
- eval_028 MRR 0.000 rank None — `Tell me about the policy`
- eval_006 MRR 0.000 rank None — `How much does the Pro tier cost and what does it include?`
- eval_027 MRR 0.000 rank None — `What are the limits?`
- eval_008 MRR 0.000 rank None — `How can I delete my knowledge and what about backups?`
- eval_005 MRR 0.000 rank None — `I want to understand the company's work-from-home rules`
- eval_007 MRR 0.000 rank None — `Describe the chunking process that splits documents`
- eval_009 MRR 0.000 rank None — `What does the onboarding look like for new engineers?`

## Recommendations

- Retrieval Hit@5 below 0.85 — consider improving hybrid fusion or candidate_k.
- Multi-hop weak — may need query decomposition or multi-query retrieval (future).
- Baseline is strong; maintain via regression checks.