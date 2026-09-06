# Pricing — RAGForge Plans and Quotas

## Plans Overview
RAGForge offers three tiers: Starter, Pro, and Enterprise. All plans include tenant-isolated knowledge bases, JWT authentication, and hybrid retrieval.

## Starter — €49 per month
- Up to 3 knowledge bases
- Up to 100 documents per knowledge base (300 total)
- Maximum file size 25 MB per document (STORAGE: 25 MB, configurable via MAX_UPLOAD_SIZE_MB)
- Up to 10,000 chunks per document (chunking: 1000 characters with 150 overlap)
- Up to 10 embedded knowledge queries per second
- Email support, 48-hour SLA

## Pro — €199 per month
- Up to 20 knowledge bases
- Up to 1,000 documents per knowledge base
- Maximum file size 25 MB, chunking 1000/150, max extracted text 5,000,000 characters
- Unlimited embedding generation (batch size 32, BAAI/bge-small-en-v1.5, 384 dimensions)
- Full-text search with GIN index and ts_rank_cd, plus HNSW vector index (m=16, ef_construction=64, RRF_K=60)
- Priority support, 12-hour SLA, 99.9% uptime SLA

## Enterprise — Custom
- Unlimited knowledge bases and documents
- Dedicated VPC, custom embedding dimensions, and BYOK encryption vault
- Advanced evaluation framework, query routing, and reranking (Phase 2.2)
- 99.99% uptime SLA, 4-hour support response, customer success manager

## Billing and Quotas
Quotas reset on the monthly anniversary. Overage is billed at €0.02 per 1,000 tokens for generation and €0.01 per embedding. The maximum file size of 25 MB is enforced before ingestion; files exceeding this are rejected with HTTP 413.

## Discounts
Annual billing saves 20% on all plans. Non-profit and academic institutions receive 30% off with verification. Referral credits are €20 per converted referral.

## Currency and Taxes
All prices are in EUR and exclude VAT. VAT is applied based on the customer's billing country. Invoices are issued on the first of each month.

## Contact Sales
Contact sales@ragforge.example.com for Enterprise quotes. Sales responds within 1 business day.
