# RAGForge Development Guide

This guide details developer workflows, environment setup, testing, and migration instructions for RAGForge.

---

## 1. Local Environment Setup

### Using Python Virtual Environment
```bash
cd backend
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

pip install -e ".[dev]"
```

### Starting Dependencies with Docker
```bash
docker compose up -d postgres
```

---

## 2. Database Migrations

RAGForge uses **Alembic** to manage database schema migrations.

### Apply Migrations
```bash
cd backend
alembic upgrade head
```

### Dry-Run SQL Generation
```bash
cd backend
alembic upgrade head --sql
```

### Migration History
- `0001_enable_pgvector`: Enables pgvector PostgreSQL extension.
- `0002_auth_and_multitenancy`: Creates users, organizations, memberships, refresh tokens, and provider credentials tables.
- `0003_knowledge_bases_and_documents`: Creates knowledge bases, documents, and document versions tables.
- `0004_ingestion_jobs_and_chunks`: Creates ingestion jobs and document chunks tables.
- `0005_embeddings_and_vector_storage`: Adds vector embedding column, embedding metadata, embedding jobs table, and HNSW cosine index.
- `0006_retrieval_and_full_text_search`: Adds `search_vector` TSVECTOR column, GIN index, and retrieval composite indexes.
- `0007_conversations_and_messages`: Creates conversations and messages tables for RAG chat history and provenance.
- `0008_incident_foundation`: Creates incidents and evidence_events tables for TracePilot Incident Foundation v0.
- `0009_evidence_dedup_idempotency`: Adds UNIQUE constraint on `(incident_id, deduplication_key)` for evidence idempotency and aligns the `source_type` composite index with ORM metadata.

---

## 3. Code Quality & Linters

Run Ruff linter and formatter:
```bash
cd backend
ruff check .
ruff format --check .
```

To auto-fix lint and formatting issues:
```bash
ruff check --fix .
ruff format .
```

---

## 4. Running Automated Tests & Evaluation

Run the complete test suite with `pytest`:
```bash
cd backend
pytest -v
```

> **SQLite vs PostgreSQL test parity.** The pytest suite runs against an
> in-memory SQLite database (`sqlite+aiosqlite`, schema created from ORM
> metadata via `Base.metadata.create_all`) with a pure-Python lexical
> fallback for keyword search. It does **not** exercise Alembic migrations,
> pgvector HNSW cosine (`<=>`), `TSVECTOR`/GIN ranking, or Postgres-scale
> RRF behavior. Run Postgres-backed integration (Docker Compose or Neon)
> plus `alembic upgrade head --sql` review before release.

Run the offline IR retrieval benchmark:
```bash
cd backend
python -m app.evaluation.retrieval
# or from root:
make evaluate-retrieval
```

---

## 5. Retrieval & Embedding Configuration

Configurable environment variables in `.env`:
```env
# Ingestion Chunking
CHUNK_SIZE=1000
CHUNK_OVERLAP=150
MAX_EXTRACTED_TEXT_CHARS=5000000
MAX_CHUNKS_PER_DOCUMENT=10000

# Vector Embeddings
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIMENSION=384
EMBEDDING_BATCH_SIZE=32
EMBEDDING_DEVICE=cpu
MAX_EMBEDDING_CHUNKS_PER_JOB=10000

# Retrieval Engine & Hybrid Search (Phase 6)
DEFAULT_SEARCH_MODE=hybrid
DEFAULT_TOP_K=10
MAX_TOP_K=100
DEFAULT_CANDIDATE_K=50
MAX_CANDIDATE_K=500
RRF_K=60
MAX_QUERY_LENGTH=2000
```
