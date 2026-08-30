# RAGForge Architecture Documentation

RAGForge is a production-grade, modular Retrieval-Augmented Generation (RAG) platform designed for reliability, scalability, multi-tenancy, and strict security compliance.

---

## High-Level System Architecture

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
  (Future Phase 5: Embeddings)        (Future Phase 5: Embeddings)
             │                                   │
             ▼                                   ▼
          pgvector                            pgvector
```

---

## Data Model & Tenancy Hierarchy

```
┌─────────────────────────────────┐
│          organizations          │ (Tenant Boundary)
└───────────────┬─────────────────┘
                │ 1:N (CASCADE)
                ├─────────────────────────────────────────────────┐
                ▼                                                 ▼
┌─────────────────────────────────┐               ┌─────────────────────────────────┐
│         knowledge_bases         │               │         ingestion_jobs          │
├─────────────────────────────────┤               ├─────────────────────────────────┤
│ id (PK, UUID)                   │               │ id (PK, UUID)                   │
│ organization_id (FK, INDEX)     │               │ document_id (FK, INDEX)         │
│ name, slug (INDEX, UQ(org,slug))│               │ document_version_id (FK, INDEX) │
│ description, is_active          │               │ organization_id (FK, INDEX)     │
│ created_by (FK -> users)        │               │ status (PENDING, etc., INDEX)   │
└───────────────┬─────────────────┘               │ attempt_count (INT)             │
                │ 1:N (CASCADE)                   │ started_at, completed_at        │
                ▼                                 │ failed_at, error_code, msg      │
┌─────────────────────────────────┐               └─────────────────────────────────┘
│            documents            │
├─────────────────────────────────┤
│ id (PK, UUID)                   │
│ knowledge_base_id (FK, INDEX)   │
│ organization_id (FK, INDEX)     │ ◄── Explicit Tenant Scoping Column
│ uploaded_by (FK -> users)       │
│ name, original_filename         │
│ content_type, file_size         │
│ storage_key, checksum (SHA-256) │
│ status (UPLOADED, READY, etc.)  │
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
                └────────────────────────────────►│ UQ(version_id, chunk_index)     │
                                                  └─────────────────────────────────┘
```

---

## Document Ingestion & Chunking Pipeline (Phase 4)

### 1. Extractor Layer (`services/ingestion/extractors/`)
- **PDFExtractor**: Uses `pypdf.PdfReader` with memory-safe `io.BytesIO`. Captures `page_number` per extracted text block and detects unextractable/empty documents.
- **DOCXExtractor**: Uses `python-docx` to extract text from headings and paragraphs, capturing `section_title` provenance from heading styles.
- **MarkdownExtractor**: Parses Markdown documents, detecting `#`, `##`, `###` headings to delineate section boundaries and associate `section_title` metadata.
- **TextExtractor**: Decodes plain text using UTF-8, falling back safely to `latin-1` or `cp1252`.

### 2. Normalization Layer (`services/ingestion/normalization.py`)
- Standardizes line endings (`\r\n` ➔ `\n`).
- Strips null bytes (`\x00`) and invisible non-printable control characters.
- Collapses excessive blank lines (`\n{3,}` ➔ `\n\n`) and trailing whitespace while preserving markdown structure, code blocks, URLs, and punctuation.

### 3. Recursive Chunking Layer (`services/ingestion/chunking/recursive.py`)
- Smart boundary splitting hierarchy: `["\n\n", "\n", ". ", "! ", "? ", "; ", " ", ""]`.
- Configured by `CHUNK_SIZE` (default 1000 characters) and `CHUNK_OVERLAP` (default 150 characters).
- Preserves contextual continuity between adjacent chunks.
- Retains rich provenance: `chunk_index` (0-indexed deterministic sequence), `page_number`, `section_title`, `character_count`, and `word_count`.

### 4. Idempotency & Ingestion Job Lifecycle (`services/ingestion/service.py`)
- Extraction and chunking happen **outside** database transactions to avoid long-running locks.
- **Atomic Persistence**:
  1. Deletes previous `DocumentChunk` records for the target `document_version_id`.
  2. Inserts new `DocumentChunk` records.
  3. Updates `Document.status = DocumentStatus.READY`.
  4. Updates `IngestionJob.status = IngestionJobStatus.COMPLETED`.
- **Failure Handling**: On extraction or chunking error, `Document.status` is set to `FAILED`, `IngestionJob.status = FAILED`, recording `error_code` and sanitized `error_message`, while incrementing `attempt_count`.

---

## Future Vector & Retrieval Pipeline

```text
Phase 4 (Completed)
Normalized Chunks + Provenance
        │
        ▼
Phase 5 (Next)
Batch Embeddings ➔ pgvector Storage (HNSW / IVFFlat Indexing)
        │
        ▼
Phase 6
Hybrid Retrieval (Vector Search + BM25 Full-Text Search + RRF + Cross-Encoder Reranking)
        │
        ▼
Phase 7
RAG Generation (Grounding Context + Citations + LLM Provider Integration)
```
