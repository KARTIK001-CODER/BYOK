# Support FAQ — RAGForge Help Center

## How do I get my money back?
If you are within 14 days and below 25% quota, request a refund via the Support Portal with subject "Refund Request: [Order ID]". Billing responds within 1 business day.

## How do I cancel after the trial period?
Trials automatically convert on day 15 if not cancelled. To cancel, go to Billing → Subscription → Cancel before day 15. After conversion, the cancellation_fee of 15% applies to annual contracts if cancelled early (see Refund Policy). Trial data is retained 7 days after expiration.

## What is the maximum file size?
The maximum file size is 25 MB per document. This is enforced before ingestion (HTTP 413 if exceeded). Chunking uses 1000 characters with 150 overlap, max 10,000 chunks per document, max extracted text 5,000,000 characters.

## What happens if a user cancels after the trial period and requests a refund?
The trial converts to paid on day 15. If the user cancels within 14 days of the paid start and usage is below 25%, they are eligible for a full refund. Otherwise, pro-rata refunds up to 30 days apply (25–50% usage). After 30 days, no refund. Contact billing@ragforge.example.com.

## How does it work? (Knowledge Base Search)
RAGForge hybrid search combines semantic vectors (pgvector HNSW, cosine) and lexical full-text search (PostgreSQL tsvector/GIN with ts_rank_cd). Results are fused with RRF (k=60). This is the short answer for ambiguous queries about how the system works.

## How do I report a bug?
Open a ticket in the Support Portal with category "Bug" and include steps to reproduce, expected vs actual behavior, and browser version. Critical bugs are triaged within 4 hours.

## What embedding model is used?
BAAI/bge-small-en-v1.5 with 384 dimensions, cosine distance, batch size 32, HNSW m=16 ef_construction=64.

## How do I increase quotas?
Upgrade your plan from the dashboard (Billing → Plans) or contact sales@ragforge.example.com for Enterprise. Quotas reset on the monthly anniversary.

## How do I enable research mode?
External research (Arxiv) fallback is disabled by default to avoid blocking chat (bounded 2s if enabled via ENABLE_ARXIV_FALLBACK=true). Enable via organization settings if you want empty-KB queries to search arXiv.

## Data Retention
Documents are stored encrypted (AES-256 at rest, TLS 1.3 in transit). Deleted documents are retained in soft-delete for 30 days before permanent deletion. Backups are retained 90 days.
