# RAGForge Backend

FastAPI asynchronous backend for RAGForge.

## Structure
- `app/api/`: Versioned API endpoints (`/api/v1`)
- `app/core/`: Configuration, structured logging, centralized exception handlers
- `app/db/`: Async SQLAlchemy 2.0 database engine, session management, declarative models
- `app/models/`: Database ORM models
- `app/schemas/`: Pydantic request/response validation schemas
- `app/services/`: Domain services (e.g. `HealthService`)
- `alembic/`: Database migrations
- `tests/`: Automated pytest test suite

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
