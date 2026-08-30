# Changelog

All notable changes to the RAGForge platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4.0] - 2026-08-30

### Added
- **Multi-Format Document Extractors**: Modular, lightweight document extractors for PDF (page-by-page extraction via `pypdf`), DOCX (headings and paragraphs via `python-docx`), Markdown (heading detection and section title extraction), and Plain Text (UTF-8, Latin-1, CP1252 fallback safe).
- **Text Normalizer**: Clean text normalizer converting CRLF/CR to LF, stripping null bytes and non-printable control characters, compressing whitespace and excessive blank lines, while preserving markdown structure, code blocks, URLs, and punctuation.
- **Recursive Text Chunker**: Smart boundary-aware recursive chunker (`\n\n` ➔ `\n` ➔ `. ` ➔ `! ` ➔ `? ` ➔ `; ` ➔ ` ` ➔ `""`) respecting configurable `CHUNK_SIZE` (1000 chars) and `CHUNK_OVERLAP` (150 chars).
- **Provenance Tracking**: Every chunk retains `chunk_index` (0-indexed deterministic sequence), `page_number`, `section_title`, `character_count`, `word_count`, and `chunk_metadata`.
- **Ingestion Job Model**: `IngestionJob` tracking processing lifecycle (`PENDING` ➔ `PROCESSING` ➔ `COMPLETED` / `FAILED`), attempt count, execution timings, and error codes (`IngestionErrorCode`).
- **Document Chunk Model**: `DocumentChunk` schema with explicit `organization_id`, `knowledge_base_id`, and `UNIQUE(document_version_id, chunk_index)` constraint.
- **Idempotent Ingestion & Reprocessing**: Ingestion pipeline safely replaces previous chunks on reprocessing without generating duplicate records or dangling state.
- **Database Migration 0004**: Alembic migration `0004_ingestion_jobs_and_chunks.py` creating `ingestion_jobs` and `document_chunks` tables with cascading foreign keys and indexes.
- **API Endpoints**:
  - `POST /api/v1/documents/{document_id}/ingest`: Triggers document extraction, normalization, and chunking (requires `ADMIN` or `OWNER`).
  - `GET /api/v1/ingestion-jobs/{job_id}`: Retrieves job execution status, attempt counts, and error metadata.
  - `GET /api/v1/documents/{document_id}/chunks`: Lists paginated provenance-aware text chunks.
- **Automated Test Suite**: 63 automated tests verifying all Phase 1–4 capabilities, including multi-format extractors, normalizer, chunker boundaries, idempotency, retries, and cross-tenant isolation.

---

## [0.3.0] - 2026-08-30

### Added
- **Knowledge Base Model & API**: Multi-tenant `KnowledgeBase` collection model with slug collision resistance, CRUD endpoints, and search querying.
- **Document Model & Storage Architecture**: `Document` model with explicit tenant column, status state machine (`UPLOADED`, `PROCESSING`, `READY`, `FAILED`, `ARCHIVED`), and `DocumentVersion` revision history.
- **Storage Abstraction**: `StorageService` protocol and `LocalStorageService` with path-traversal safeguards and async non-blocking file operations.
- **File Validation & Magic Bytes Inspection**: Validates `.pdf` (`%PDF`), `.txt`, `.md`, and `.docx` (`PK\x03\x04`) files with configurable `MAX_UPLOAD_SIZE_MB`.
- **SHA-256 Checksumming & Duplicate Detection**: Computes cryptographic checksums on upload and returns `409 Conflict` if duplicate file is uploaded to the same Knowledge Base.
- **Database Migration 0003**: Alembic migration `0003_knowledge_bases_and_documents.py` creating `knowledge_bases`, `documents`, and `document_versions` tables.
- **Automated Test Suite**: 47 automated tests covering document uploads, magic byte rejection, duplicate conflicts, tenant isolation, and pagination.

---

## [0.2.0] - 2026-08-30

### Added
- **User Authentication**: Argon2id password hashing, JWT access tokens (15-min TTL), and rotating refresh tokens (7-day TTL).
- **Refresh Token Rotation & Reuse Detection**: Cryptographically random refresh tokens stored as SHA-256 hashes with automatic breach invalidation.
- **Multi-Tenancy & Organizations**: `Organization` tenant isolation and `OrganizationMembership` supporting `OWNER > ADMIN > MEMBER` RBAC.
- **BYOK-Ready Provider Schema**: `ProviderCredential` model prepared for future encrypted API key vaults.
- **Database Migration 0002**: Alembic migration `0002_auth_and_multitenancy.py`.
- **API Endpoints**: `/api/v1/auth/register`, `/api/v1/auth/login`, `/api/v1/auth/refresh`, `/api/v1/auth/logout`, `/api/v1/auth/me`, `/api/v1/organizations`.

---

## [0.1.0] - 2026-08-30

### Added
- Initial project architecture and directory layout.
- FastAPI application factory with lifespan management and structured CORS.
- Async SQLAlchemy 2.0 database engine with connection pooling and PostgreSQL/Neon support.
- `pgvector` extension activation migration (`0001_enable_pgvector.py`).
- Structured logging with ISO UTC timestamps and request context.
- Correlation ID tracking via `X-Request-ID` middleware.
- Health check endpoints: `/health` (liveness probe), `/ready` (readiness probe), and `/api/v1/info`.
- Docker Compose setup with `pgvector/pgvector:pg16` database.
