# RAGForge

> A production-oriented, modular Retrieval-Augmented Generation (RAG) platform with Bring-Your-Own-Key (BYOK) secret management, hybrid retrieval, reranking, and observability.

---

## 📌 Project Status

**Current Status**: **Phase 2 Complete (Authentication, Multi-Tenancy & BYOK-Ready Database)**.
- Implemented user accounts with Argon2id password hashing and normalized email uniqueness.
- Implemented JWT access tokens (15m) and rotating refresh tokens (7d) with automatic reuse detection.
- Implemented multi-tenant organizations with automatic default workspace provisioning upon registration.
- Implemented centralized Role-Based Access Control (RBAC): `OWNER`, `ADMIN`, `MEMBER`.
- Implemented and verified strict tenant isolation (cross-tenant access rejected).
- Created `ProviderCredential` database schema for future BYOK credential ciphertext storage.
- All Phase 1 infrastructure preserved, tested, and verified.

*Note: Actual BYOK encryption algorithms, provider SDK integrations (Groq, OpenAI, Gemini), document ingestion, and vector retrieval are planned for upcoming phases.*

---

## 🛠️ Technology Stack

- **Language & Runtime**: Python 3.12+
- **Web Framework**: FastAPI (Async ASGI)
- **Database & Vector Engine**: PostgreSQL 16 + `pgvector`
- **ORM & Migrations**: SQLAlchemy 2.0 (AsyncIO) & Alembic
- **Security & Authentication**: Argon2id (`argon2-cffi`), PyJWT, Pydantic v2
- **Configuration & Validation**: `pydantic-settings` & `email-validator`
- **Containerization**: Docker & Docker Compose
- **Quality & Testing**: Ruff (Linter & Formatter), pytest, pytest-asyncio, HTTPX

---

## 📂 Project Structure

```text
ragforge/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py               # Authentication & RBAC FastAPI dependencies
│   │   │   ├── router.py             # Top-level API router aggregator
│   │   │   └── v1/
│   │   │       ├── health.py         # Liveness, readiness, and system info endpoints
│   │   │       ├── auth.py           # Register, login, refresh, logout, me endpoints
│   │   │       └── organizations.py  # Tenant-isolated organization endpoints
│   │   ├── core/
│   │   │   ├── config.py             # Server settings & JWT token expiration configs
│   │   │   ├── security.py           # Argon2id hashing, JWT encoding, refresh token hashing
│   │   │   ├── logging.py            # Structured logging with request ID context
│   │   │   └── exceptions.py         # Centralized error handlers & envelopes
│   │   ├── db/
│   │   │   ├── base.py               # DeclarativeBase, UUID & timestamp mixins
│   │   │   └── session.py            # Async engine, connection pool & sessionmaker
│   │   ├── models/
│   │   │   ├── user.py               # User account model (normalized email, is_active)
│   │   │   ├── organization.py       # Organization tenant model (slug, name)
│   │   │   ├── membership.py         # OrganizationMembership model (OWNER, ADMIN, MEMBER)
│   │   │   ├── refresh_token.py      # RefreshToken model (rotation & revocation)
│   │   │   └── provider_credential.py# ProviderCredential model (BYOK DB foundation)
│   │   ├── schemas/                  # Pydantic schemas (Auth, Users, Organizations, Health)
│   │   ├── services/                 # Domain service layer (Auth, Users, Organizations, Health)
│   │   └── main.py                   # FastAPI app entry point & lifespan
│   ├── alembic/                      # Database migrations (async)
│   ├── tests/                        # Automated unit & integration tests
│   ├── pyproject.toml                # Project metadata, dependencies & tool configs
│   └── Dockerfile                    # Multi-stage container definition
├── frontend/                         # Frontend application (Planned)
├── docker/
│   └── postgres/
│       └── init.sql                  # PostgreSQL extension initializations
├── docs/
│   ├── ARCHITECTURE.md               # Architecture details, Auth & BYOK design
│   └── DEVELOPMENT.md                # Development, tooling & migration workflows
├── .github/workflows/ci.yml          # GitHub Actions CI workflow
├── docker-compose.yml                # Multi-container orchestration (Backend + Postgres)
├── .env.example                      # Server environment configuration template
├── Makefile                          # Development shortcut commands
├── CHANGELOG.md                      # Release changelog
└── README.md
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.12+
- Docker & Docker Compose

### 1. Quickstart with Docker Compose

```bash
# Copy example environment file
cp .env.example .env

# Build and start services
docker compose up --build
```

Endpoints available:
- **API Documentation (Swagger UI)**: `http://localhost:8000/docs`
- **Liveness Probe**: `http://localhost:8000/health`
- **Readiness Probe**: `http://localhost:8000/ready`
- **Registration**: `POST http://localhost:8000/api/v1/auth/register`
- **Login**: `POST http://localhost:8000/api/v1/auth/login`
- **Current User Profile**: `GET http://localhost:8000/api/v1/auth/me`

---

### 2. Local Python Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
# Activate:
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1

# Install dependencies in editable mode with development packages
pip install --upgrade pip
pip install -e ".[dev]"

# Start PostgreSQL container
docker compose up -d postgres

# Run database migrations
alembic upgrade head

# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 🧪 Testing & Code Quality

```bash
# Run pytest test suite
pytest -v

# Run lint checks
ruff check .

# Run code format checks
ruff format --check .

# Apply auto-formatting
ruff format .
```

---

## 🔒 Security & Multi-Tenancy Architecture

- **Argon2id Password Hashing**: Passwords are hashed with salt using Argon2id. Plaintext passwords and hashes are never returned or logged.
- **JWT & Token Rotation**: 15-minute access tokens + 7-day rotating refresh tokens. Reusing a revoked refresh token triggers reuse detection and revokes all active tokens for the user.
- **Tenant Isolation**: Every organization is an isolated tenant. The backend strictly checks membership and role server-side; cross-tenant access is denied (`403 Forbidden`).
- **BYOK Preparation**: Database schema is established with `provider_credentials` scoped by organization, separate from server secrets.

---

## 🗺️ Roadmap

- [x] **Phase 1: Project Foundation** (FastAPI, PostgreSQL + pgvector, Alembic, Logging, Healthchecks, Docker)
- [x] **Phase 2: Authentication & Multi-Tenancy** (User accounts, Argon2id, JWT, Token Rotation, Organizations, RBAC, Tenant Isolation, BYOK DB Schema)
- [ ] **Phase 3: Document Ingestion & Chunking Pipeline** (Parsers, semantic & recursive chunking, metadata extraction)
- [ ] **Phase 4: Embeddings & Vector Indexing** (Multi-provider embeddings, HNSW / IVFFlat indexing in pgvector)
- [ ] **Phase 5: Hybrid Retrieval & Reranking** (Dense vector search + BM25 sparse search + Cohere/Cross-Encoder reranking)
- [ ] **Phase 6: RAG Generation & LLM Gateway** (Context assembly, streaming responses, citations, BYOK secret vault)
- [ ] **Phase 7: Grounding Verification & Evaluation** (Hallucination detection, RAGAS metrics)
- [ ] **Phase 8: Frontend UI** (Modern Next.js / Vite SPA for document management & RAG playground)
