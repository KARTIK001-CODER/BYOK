# RAGForge

> A production-oriented, modular Retrieval-Augmented Generation (RAG) platform with Bring-Your-Own-Key (BYOK) secret management, hybrid retrieval, reranking, and observability.

---

## 📌 Project Status

**Current Status**: **Phase 1 Complete (Foundation & Architecture)**.
- Established clean engineering architecture, FastAPI application factory, and async database layer.
- Configured PostgreSQL 16 with the `pgvector` extension and initial Alembic migrations.
- Implemented structured logging with request ID tracking (`X-Request-ID`), centralized error handling, and health/readiness endpoints.
- Configured Docker Compose, Ruff linting/formatting, and automated pytest suite.

*Note: Document ingestion, chunking, vector indexing, reranking, evaluation, and user authentication are planned for upcoming phases.*

---

## 🛠️ Technology Stack

- **Language & Runtime**: Python 3.12+
- **Web Framework**: FastAPI (Async ASGI)
- **Database & Vector Engine**: PostgreSQL 16 + `pgvector`
- **ORM & Migrations**: SQLAlchemy 2.0 (AsyncIO) & Alembic
- **Configuration & Validation**: Pydantic v2 & `pydantic-settings`
- **Containerization**: Docker & Docker Compose
- **Quality & Testing**: Ruff (Linter & Formatter), pytest, pytest-asyncio, HTTPX

---

## 📂 Project Structure

```text
ragforge/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── router.py             # Top-level API router aggregator
│   │   │   └── v1/
│   │   │       └── health.py         # Liveness, readiness, and system info endpoints
│   │   ├── core/
│   │   │   ├── config.py             # Server settings via Pydantic BaseSettings
│   │   │   ├── logging.py            # Structured logging with request ID context
│   │   │   └── exceptions.py         # Centralized error handlers & envelopes
│   │   ├── db/
│   │   │   ├── base.py               # DeclarativeBase, UUID & timestamp mixins
│   │   │   └── session.py            # Async engine, connection pool & sessionmaker
│   │   ├── models/                   # SQLAlchemy ORM models
│   │   ├── schemas/                  # Pydantic schemas (Request / Response)
│   │   ├── services/                 # Domain service layer (HealthService)
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
│   ├── ARCHITECTURE.md               # Architecture details & BYOK design
│   └── DEVELOPMENT.md                # Development, tooling & migration workflows
├── .github/workflows/ci.yml          # GitHub Actions CI workflow
├── docker-compose.yml                # Multi-container orchestration (Backend + Postgres)
├── .env.example                      # Server environment configuration template
├── Makefile                          # Development shortcut commands
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
- **API v1 Info**: `http://localhost:8000/api/v1/info`

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

## 🔒 Security & BYOK Architecture

- **No Secrets in Git**: `.env` is ignored. `.env.example` contains only server infrastructure settings.
- **BYOK (Bring Your Own Key)**: In subsequent phases, user/organization provider keys (e.g., OpenAI, Groq, Anthropic, Gemini) will be encrypted and stored in PostgreSQL, decrypted only in-memory per request.
- **Fail-Safe Responses**: Stack traces and raw internal error details are sanitized and never exposed to clients.
- **Request Tracing**: All requests carry a unique `X-Request-ID` attached to structured server logs.

---

## 🗺️ Roadmap

- [x] **Phase 1: Project Foundation** (FastAPI, PostgreSQL + pgvector, Alembic, Logging, Healthchecks, Docker)
- [ ] **Phase 2: Authentication & BYOK Vault** (Multi-tenant orgs, AES-256-GCM secret encryption, key management)
- [ ] **Phase 3: Document Ingestion & Chunking Pipeline** (Parsers, semantic & recursive chunking, metadata)
- [ ] **Phase 4: Embeddings & Vector Indexing** (Multi-provider embeddings, HNSW / IVFFlat indexing)
- [ ] **Phase 5: Hybrid Retrieval & Reranking** (Dense vector search + BM25 sparse search + Cohere/Cross-Encoder reranking)
- [ ] **Phase 6: RAG Generation & LLM Gateway** (Context assembly, streaming responses, citations)
- [ ] **Phase 7: Grounding Verification & Evaluation** (Hallucination detection, RAGAS metrics)
- [ ] **Phase 8: Frontend UI** (Modern Next.js / Vite SPA for document management & RAG playground)
