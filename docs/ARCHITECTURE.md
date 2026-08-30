# RAGForge Architecture Documentation

RAGForge is a production-grade, modular Retrieval-Augmented Generation (RAG) platform designed for reliability, scalability, multi-tenancy, and strict security compliance.

---

## High-Level System Architecture (Phases 1–5)

```text
                    Organization (Tenant Boundary)
                               │
             ┌─────────────────┴─────────────────┐
             │                                   │
             ▼                                   ▼
      Knowledge Base A                    Knowledge Base B
             │                                   │
             ▼                                   ▼
        Documents                           Documents
             │                                   │
             ▼                                   ▼
       Object Storage                     Object Storage
             │                                   │
             ▼                                   ▼
     Ingestion Pipeline                  Ingestion Pipeline
             │                                   │
       ┌─────┴─────┐                       ┌─────┴─────┐
       ▼           ▼                       ▼           ▼
   Extraction  Normalization           Extraction  Normalization
       │           │                       │           │
       └─────┬─────┘                       └─────┬─────┘
             ▼                                   ▼
          Chunking                            Chunking
             │                                   │
             ▼                                   ▼
      Document Chunks                     Document Chunks
             │                                   │
             ▼                                   ▼
      Embedding Service                   Embedding Service
             │                                   │
             ▼                                   ▼
    FastEmbed Model (384d)              FastEmbed Model (384d)
             │                                   │
             ▼                                   ▼
          pgvector                            pgvector
             │                                   │
             ▼                                   ▼
         HNSW Index                          HNSW Index
```

---

## Data Model & Tenancy Hierarchy

```
┌─────────────────────────────────┐
│          organizations          │ (Tenant Boundary)
└───────────────┬─────────────────┘
                │ 1:N (CASCADE)
                ├─────────────────────────────────────────────────┬─────────────────────────────────┐
                ▼                                                 ▼                                 ▼
┌─────────────────────────────────┐               ┌─────────────────────────────────┐ ┌─────────────────────────────────┐
│         knowledge_bases         │               │         ingestion_jobs          │ │         embedding_jobs          │
├─────────────────────────────────┤               ├─────────────────────────────────┤ ├─────────────────────────────────┤
│ id (PK, UUID)                   │               │ id (PK, UUID)                   │ │ id (PK, UUID)                   │
│ organization_id (FK, INDEX)     │               │ document_id (FK, INDEX)         │ │ document_id (FK, INDEX)         │
│ name, slug (INDEX, UQ(org,slug))│               │ document_version_id (FK, INDEX) │ │ document_version_id (FK, INDEX) │
│ description, is_active          │               │ organization_id (FK, INDEX)     │ │ organization_id (FK, INDEX)     │
│ created_by (FK -> users)        │               │ status (PENDING, etc., INDEX)   │ │ status (PENDING, etc., INDEX)   │
└───────────────┬─────────────────┘               │ attempt_count (INT)             │ │ attempt_count (INT)             │
                │ 1:N (CASCADE)                   │ started_at, completed_at        │ │ total_chunks, processed_chunks  │
                ▼                                 │ failed_at, error_code, msg      │ │ embedding_model, dimension      │
┌─────────────────────────────────┐               └─────────────────────────────────┘ │ started_at, completed_at, msg   │
│            documents            │                                                   └─────────────────────────────────┘
├─────────────────────────────────┤
│ id (PK, UUID)                   │
│ knowledge_base_id (FK, INDEX)   │
│ organization_id (FK, INDEX)     │ ◄── Explicit Tenant Scoping Column
│ uploaded_by (FK -> users)       │
│ name, original_filename         │
│ content_type, file_size         │
│ storage_key, checksum (SHA-256) │
│ status (UPLOADED, READY, etc.)  │
│ embedding_status (COMPLETED)    │
│ current_version (INT)           │
│ deleted_at (TIMESTAMP)          │
└───────────────┬─────────────────┘
                │ 1:N (CASCADE)
                ├─────────────────────────────────────────────────┐
                ▼                                                 ▼
┌─────────────────────────────────┐               ┌─────────────────────────────────┐
│        document_versions        │               │         document_chunks         │
├─────────────────────────────────┤               ├─────────────────────────────────┤
│ id (PK, UUID)                   │               │ id (PK, UUID)                   │
│ document_id (FK, INDEX)         │               │ document_id (FK, INDEX)         │
│ version_number (INT)            │               │ document_version_id (FK, INDEX) │
│ storage_key, checksum           │               │ organization_id (FK, INDEX)     │
│ file_size, content_type         │               │ knowledge_base_id (FK, INDEX)   │
│ uploaded_by (FK -> users)       │               │ chunk_index (INT, INDEX)        │
│ UQ(doc_id, version_number)      │               │ content (TEXT)                  │
└───────────────┬─────────────────┘               │ character_count, word_count     │
                │                                 │ page_number, section_title      │
                │ 1:N (CASCADE)                   │ chunk_metadata (JSON)           │
                │                                 │ embedding (VECTOR(384))         │
                │                                 │ embedding_model, provider, dim  │
                │                                 │ embedded_at (TIMESTAMP)         │
                └────────────────────────────────►│ UQ(version_id, chunk_index)     │
                                                  │ HNSW INDEX (vector_cosine_ops)  │
                                                  └─────────────────────────────────┘
```

---

## Embedding & Vector Storage Architecture (Phase 5)

### 1. Provider Abstraction (`services/embeddings/`)
- `BaseEmbeddingProvider` interface decouples the application from specific AI vendors.
- Exposes `embed_documents` (for passage chunks) and `embed_query` (with query prefix instructions).
- **Default Local Provider**: `LocalEmbeddingProvider` using `fastembed` with `BAAI/bge-small-en-v1.5` (dimension: 384, cosine distance metric).
- Model is loaded once as a cached singleton at startup for low memory overhead and zero API cost.

### 2. Database & Vector Indexing
- Native pgvector column: `document_chunks.embedding vector(384)`.
- Model metadata columns: `embedding_model`, `embedding_provider`, `embedding_dimension`, `embedded_at`.
- Cosine Distance Index: `CREATE INDEX ix_document_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);`.

### 3. Batching, Idempotency & Resumability
- Batched inference: Processed in chunks of `EMBEDDING_BATCH_SIZE` (default: 32).
- Model-aware idempotency: Chunks already embedded with the requested model are skipped.
- Progress updates are committed per batch to `EmbeddingJob.processed_chunks`. If interrupted, retry resumes missing chunks.

---

## Future Retrieval & Generation Pipeline

```text
Phase 5 (Completed)
Dense Vectors in PostgreSQL pgvector (HNSW Index)
        │
        ▼
Phase 6 (Next)
Hybrid Retrieval (Vector Similarity Search + BM25 Full-Text Search + RRF + Cross-Encoder Reranker)
        │
        ▼
Phase 7
RAG Generation (Grounding Context + Citations + LLM Provider Integration)
```
