# Technical Documentation — RAGForge Architecture and Retrieval

## System Architecture
RAGForge is a modular full-stack platform: FastAPI backend (Python 3.13), React frontend, PostgreSQL 16 with pgvector, and ONNX Runtime for CPU-optimized local embeddings. The backend uses SQLAlchemy async with connection pooling (pool_size=10, max_overflow=20, pool_timeout=30, pool_recycle=1800, pool_pre_ping=True) to Neon pooled connections.

## Authentication and Multi-Tenancy
Authentication uses short-lived JWT access tokens (15-minute expiry, HS256) and rotating refresh tokens stored as SHA-256 hashes. Multi-tenancy is enforced via organization_id foreign keys on knowledge bases, documents, document chunks, and messages. Role-based access control (RBAC) defines OWNER > ADMIN > MEMBER hierarchy.

## Ingestion Pipeline
Ingestion extracts text from PDF, DOCX, TXT, and Markdown using pluggable extractors. Text normalization standardizes unicode, whitespace, and strips null bytes. Recursive character chunking splits text into 1000-character chunks with 150-character overlap, preserving section titles and page numbers. The pipeline stores chunks with provenance (organization_id, knowledge_base_id, document_id, document_version_id, chunk_index).

## Embeddings and Vector Storage
Embeddings are generated locally via fastembed ONNX Runtime using BAAI/bge-small-en-v1.5 (384 dimensions) with batch_size=32. The embedding provider is a singleton (fastembed TextEmbedding) to avoid cold start per request (warm init 0.03ms vs cold 225ms). Document chunks store embedding, embedding_model, embedding_provider, embedding_dimension, and embedded_at. The pgvector HNSW index is created as `ix_document_chunks_embedding_hnsw USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`.

## Retrieval Engine — Hybrid Search
Hybrid retrieval runs vector and keyword search in parallel via asyncio.gather with independent AsyncSessions. Vector search uses `embedding <=> query_embedding` (cosine distance via `vector_cosine_ops`) ordered by distance with LIMIT candidate_k. Keyword search uses `search_vector @@ plainto_tsquery('english', query)` with `ts_rank_cd` and GIN index `ix_document_chunks_search_vector_gin` on the generated tsvector `to_tsvector('english', coalesce(section_title,'') || ' ' || coalesce(content,''))`. Candidates are fused via Reciprocal Rank Fusion (RRF, rrf_k=60) and deduplicated by chunk_id.

## Generation Engine
Generation assembles context with provenance, token budgeting (MAX_CONTEXT_TOKENS=12000), and prompt injection defense. The LLM provider factory resolves Groq, OpenAI, Gemini, or mock providers via ModelRegistry. Streaming uses Server-Sent Events (SSE) with token, citation, and done events.

## Connection Pooling and Stability
The async engine disables statement cache (`statement_cache_size=0`, `prepared_statement_cache_size=0`) for Neon pooler compatibility. The RAG service releases the DB connection via `await session.commit()` before streaming to avoid holding pooled connections during external LLM calls.

## Evaluation Framework
Phase 2.0 adds a retrieval evaluation framework with datasets, metrics (Hit@K, MRR, Precision@K, Recall@K), and regression detection. The evaluation organization isolates fixture data without polluting production users.
