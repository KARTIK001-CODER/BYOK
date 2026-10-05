# RAGForge Backend

FastAPI asynchronous backend for RAGForge (multi-tenant RAG + TracePilot Incident Foundation v0).

## Module Map (see root `README.md`, `ARCHITECTURE.md`, and `docs/DEVELOPMENT.md` for details)
- `app/api/`: Versioned API endpoints (`/api/v1/auth`, `/api/v1/organizations`, `/api/v1/knowledge-bases`, `/api/v1/documents`, `/api/v1/ingestion`, `/api/v1/embeddings`, `/api/v1/retrieval`, `/api/v1/chat`, `/api/v1/conversations`, `/api/v1/diagnostics`, `/api/v1/incidents`, `/api/v1/health`)
- `app/core/`: Configuration, structured logging, Argon2id security, JWT tokens, centralized exception handlers
- `app/db/`: Async SQLAlchemy 2.0 database engine, session management, declarative models
- `app/models/`: Database ORM models (`User`, `Organization`, `OrganizationMembership`, `RefreshToken`, `ProviderCredential`, `KnowledgeBase`, `Document`, `DocumentVersion`, `DocumentChunk`, `IngestionJob`, `EmbeddingJob`, `Conversation`, `Message`, `Incident`, `EvidenceEvent`)
- `app/schemas/`: Pydantic request/response validation schemas
- `app/services/`: Domain services (`auth`, `users`, `organizations`, `documents`, `ingestion`, `embeddings`, `retrieval`, `query_intelligence`, `retrieval_intelligence`, `reranking`, `verification`, `llm`, `rag`, `incidents`, `knowledge_bases`, `evaluation`, `health`)
- `alembic/`: Database migrations (`0001`–`0009`; head: `0009_evidence_dedup_idempotency`)
- `tests/`: Comprehensive pytest automated test suite (SQLite in-memory; see `docs/DEVELOPMENT.md` for Postgres parity notes)

## Quick Commands
```bash
# Run tests
pytest -v

# Run linter
ruff check .

# Run format check
ruff format --check .

# Start dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
