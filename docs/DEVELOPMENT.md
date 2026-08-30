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

## 4. Running Automated Tests

Run the complete test suite with `pytest`:
```bash
cd backend
pytest -v
```

---

## 5. Embedding & Ingestion Configuration

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
```
