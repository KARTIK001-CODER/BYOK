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
                │                                 │ search_vector (TSVECTOR)        │
                │                                 │ GIN INDEX (search_vector)       │
                │                                 │ IX(organization_id, kb_id)     │
                └────────────────────────────────►│ UQ(version_id, chunk_index)     │
                                                  │ HNSW INDEX (vector_cosine_ops)  │
                                                  └─────────────────────────────────┘
```

---

## Retrieval Engine & Hybrid Search Architecture (Phase 6)

### 1. Multi-Modal Retrieval Strategy

```text
                         User Query
                              │
                              ▼
                     Retrieval Service
                              │
                 ┌────────────┴────────────┐
                 │                         │
                 ▼                         ▼
          Query Embedding             PostgreSQL FTS
                 │                         │
                 ▼                         ▼
             pgvector                 Keyword Search
                 │                         │
                 └────────────┬────────────┘
                              ▼
                         RRF Fusion
                              │
                              ▼
                        Deduplication
                              │
                              ▼
                        Top-K Results
                              │
                              ▼
                       Future Reranker
                              │
                              ▼
                         Future LLM
```

- **Semantic Vector Search**: pgvector cosine distance (`<=>`) using `BAAI/bge-small-en-v1.5` embeddings.
- **PostgreSQL Full-Text Search (FTS)**: Native `tsvector` generated column on `(coalesce(section_title, '') || ' ' || content)`, GIN indexed, ranked via `ts_rank_cd` (Cover Density).
- **Hybrid Search**: Concurrent or resilient dual-branch candidate retrieval with fallback protection.
- **Reciprocal Rank Fusion (RRF)**:
  $$RRF(d) = \sum_{m \in M} \frac{1}{RRF\_K + rank_m(d)}$$
  (Default $RRF\_K = 60$). Combines disparate scoring scales into a single normalized monotonic ranking.

### 2. Tenant Isolation & Version Integrity
- **Database-Level Filtering**: All retrieval queries strictly filter `WHERE document_chunks.organization_id = :organization_id` at the database level.
- **Knowledge Base Authorization**: Explicit validation that all requested knowledge base IDs belong to the caller's organization before query execution.
- **Document Version Integrity**: Filters ensure only active chunks from the latest version (`document_versions.version_number == documents.current_version`) of `READY` documents are retrieved.

### 3. Evaluation & Golden Benchmark
- Offline development benchmark evaluating **Recall@K**, **Precision@K**, and **MRR** across Vector, Keyword, and Hybrid search strategies using `python -m app.evaluation.retrieval`.

---

## Future Generation Pipeline

```text
Phase 6 (Completed)
Hybrid Retrieval (pgvector + PostgreSQL FTS + RRF)
        │
        ▼
Phase 7 (Next)
RAG Generation (Prompt Construction, Context Synthesis, Citations & Grounding, Provider Integration)
        │
        ▼
Phase 8
BYOK Vault & Master Encryption (AES-256-GCM Vault for Groq, OpenAI, Anthropic, Gemini)
```
