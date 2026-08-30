# RAGForge Backend

FastAPI asynchronous backend for RAGForge.

## Phase 2 Modules
- `app/api/`: Versioned API endpoints (`/api/v1/auth`, `/api/v1/organizations`, `/api/v1/health`)
- `app/core/`: Configuration, structured logging, Argon2id security, JWT tokens, centralized exception handlers
- `app/db/`: Async SQLAlchemy 2.0 database engine, session management, declarative models
- `app/models/`: Database ORM models (`User`, `Organization`, `OrganizationMembership`, `RefreshToken`, `ProviderCredential`)
- `app/schemas/`: Pydantic request/response validation schemas (`Auth`, `Users`, `Organizations`, `Health`)
- `app/services/`: Domain services (`AuthService`, `UserService`, `OrganizationService`, `TokenService`, `PasswordService`, `HealthService`)
- `alembic/`: Database migrations (`0001_enable_pgvector.py`, `0002_auth_and_multitenancy.py`)
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
