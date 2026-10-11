# TracePilot Backend

FastAPI asynchronous backend for TracePilot — an AI-powered SRE incident investigation and root-cause analysis platform.

## Module Map (see root `README.md`, `ARCHITECTURE.md`, and `DEPLOYMENT.md` for details)
- `app/api/`: Versioned API endpoints (`/api/v1/auth`, `/api/v1/incidents`, `/api/v1/investigations`, `/api/v1/evidence`, `/api/v1/runbooks`, `/api/v1/remediations`, `/api/v1/evaluations`, `/api/v1/knowledge-bases`, `/api/v1/documents`, `/api/v1/retrieval`, `/api/v1/health`)
- `app/core/`: Configuration, structured logging, Argon2id security, JWT tokens, centralized exception handlers
- `app/db/`: Async SQLAlchemy 2.0 database engine, session management, declarative models
- `app/models/`: Database ORM models (`User`, `Organization`, `Incident`, `EvidenceEvent`, `InvestigationJob`, `RemediationProposal`, `ApprovalDecision`, `AuditEvent`, `WorkerHeartbeat`, `RunbookIndex`, `EvaluationRun`, `KnowledgeBase`, `Document`, `DocumentChunk`)
- `app/schemas/`: Pydantic request/response validation schemas
- `app/services/`: Domain services (`incidents`, `investigations`, `evidence`, `remediation`, `evaluation`, `runbook`, `retrieval`, `embeddings`, `auth`, `health`)
- `alembic/`: Database migrations (`0001` through `0016`; current head: `0016_worker_heartbeats`)
- `tests/`: Comprehensive pytest automated test suite

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
