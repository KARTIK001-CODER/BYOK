# TracePilot Development Guide

This guide details developer workflows, environment setup, testing, and migration instructions for TracePilot.

---

## 1. Local Environment Setup

### Backend (Python 3.12+)
```bash
cd backend
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

pip install -e ".[dev]"
```

### Frontend (Node 18+)
```bash
cd frontend
npm install
npm run dev
```

### Starting Dependencies with Docker
```bash
# Start PostgreSQL with pgvector
docker compose up -d postgres
```

---

## 2. Database Migrations

TracePilot uses **Alembic** to manage database schema migrations.

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

### Complete Migration History
- `0001_enable_pgvector`: Enables pgvector PostgreSQL extension.
- `0002_auth_and_multitenancy`: Creates users, organizations, memberships, refresh tokens, and credentials.
- `0003_knowledge_bases_and_documents`: Creates knowledge bases, documents, and document versions.
- `0004_ingestion_jobs_and_chunks`: Creates ingestion jobs and document chunks.
- `0005_embeddings_and_vector_storage`: Adds vector embedding column, embedding jobs, and HNSW cosine index.
- `0006_retrieval_and_full_text_search`: Adds `search_vector` TSVECTOR column, GIN index, and retrieval composite indexes.
- `0007_conversations_and_messages`: Creates conversations and messages tables.
- `0008_incident_foundation`: Creates incidents and evidence_events tables.
- `0009_evidence_dedup_idempotency`: Adds UNIQUE constraint on `(incident_id, deduplication_key)` for evidence idempotency.
- `0010_investigation_jobs`: Creates investigation jobs, hypotheses, and evidence citation tracking.
- `0011_runbook_indices`: Operational runbook linking and search indexes.
- `0012_evaluations`: Groundedness evaluation runs and test benchmarks.
- `0013_batch_ingestion_jobs`: Batch evidence ingestion jobs.
- `0014_remediation_proposals`: Remediation proposals and risk assessment metadata.
- `0015_audit_events`: Append-only audit events table.
- `0016_worker_heartbeats`: Durable worker heartbeat tracking and liveness monitoring.

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
cd backend
ruff check --fix .
ruff format .
```

---

## 4. Running Automated Tests & Evaluation

### Backend Test Suite
```bash
cd backend
pytest -v
```

### Frontend Test Suite & Production Build
```bash
cd frontend
npm test -- --run
npm run build
```

### Groundedness Evaluation Benchmark
```bash
cd backend
python -m evaluation.groundedness.evaluate
```

---

## 5. Core Environment Variables

Configurable environment variables in `.env`:
```env
# General
APP_NAME=TracePilot
APP_ENV=development
DEBUG=true

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/tracepilot

# Security
JWT_SECRET_KEY=change-in-production
API_KEY_ENCRYPTION_KEY=change-in-production

# Investigation & Worker
WORKER_HEARTBEAT_INTERVAL_SECONDS=30
STALE_JOB_THRESHOLD_SECONDS=300
```
