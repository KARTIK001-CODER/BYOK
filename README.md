# RAGForge

> A production-oriented, modular Retrieval-Augmented Generation (RAG) platform with Bring-Your-Own-Key (BYOK) secret management, hybrid retrieval, reranking, and observability.

---

## 📌 Project Status

**Current Status**: **Phase 3 Complete (Knowledge Bases & Document Management)**.
- Implemented **Knowledge Bases** scoped to tenant Organizations with unique slugs and RBAC.
- Implemented **Document Management** with multipart uploads, file validation (PDF, TXT, MD, DOCX), and magic bytes inspection.
- Implemented **Cryptographic SHA-256 Checksums** and **Duplicate Document Detection** (409 Conflict).
- Implemented **Object Storage Abstraction** (`StorageService` / `LocalStorageService`) with path traversal protection.
- Implemented **Controlled Document Lifecycle**: `UPLOADING` ➔ `UPLOADED` (Phase 3 terminal state) ➔ `PROCESSING` ➔ `READY` / `FAILED` / `ARCHIVED`.
- Implemented **Immutable Document Versions** schema (`DocumentVersion`).
- Verified strict tenant isolation (cross-tenant KB/document access is rejected).
- All Phase 1, Phase 2, and Phase 3 features tested and verified (47 automated tests).

---

## 🛠️ Technology Stack

- **Language & Runtime**: Python 3.12+
- **Web Framework**: FastAPI (Async ASGI)
- **Database & Vector Engine**: Neon PostgreSQL / PostgreSQL 16 + `pgvector`
- **ORM & Migrations**: SQLAlchemy 2.0 (AsyncIO) & Alembic
- **Security & Authentication**: Argon2id (`argon2-cffi`), PyJWT, Pydantic v2
- **File & Storage Abstraction**: `python-multipart`, LocalStorageService (ready for S3/R2/GCS)
- **Containerization**: Docker & Docker Compose
- **Quality & Testing**: Ruff (Linter & Formatter), pytest, pytest-asyncio, HTTPX

---

## 📂 Project Structure

```text
ragforge/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py               # Auth, RBAC, KB & Document dependencies
│   │   │   ├── router.py             # Top-level API router aggregator
│   │   │   └── v1/
│   │   │       ├── health.py         # Liveness, readiness, and system info endpoints
│   │   │       ├── auth.py           # Register, login, refresh, logout, me endpoints
│   │   │       ├── organizations.py  # Tenant-isolated organization endpoints
│   │   │       ├── knowledge_bases.py# Knowledge base CRUD, search, pagination
│   │   │       └── documents.py      # Multipart upload, list, metadata, archive, delete
│   │   ├── core/
│   │   │   ├── config.py             # Settings (JWT, limits, storage directory)
│   │   │   ├── security.py           # Argon2id hashing, JWT encoding, refresh token hashing
│   │   │   ├── logging.py            # Structured logging with request ID context
│   │   │   └── exceptions.py         # Centralized error handlers & envelopes
│   │   ├── db/
│   │   │   ├── base.py               # DeclarativeBase, UUID & timestamp mixins
│   │   │   └── session.py            # Async engine, connection pool & sessionmaker
│   │   ├── models/
│   │   │   ├── user.py               # User account model
│   │   │   ├── organization.py       # Organization tenant model
│   │   │   ├── membership.py         # OrganizationMembership model (OWNER, ADMIN, MEMBER)
│   │   │   ├── refresh_token.py      # RefreshToken model (rotation & revocation)
│   │   │   ├── provider_credential.py# ProviderCredential model (BYOK DB foundation)
│   │   │   ├── knowledge_base.py     # KnowledgeBase model (tenant scoped, unique slug)
│   │   │   ├── document.py           # Document model (status lifecycle, tenant aware)
│   │   │   └── document_version.py   # DocumentVersion model (storage key, revision)
│   │   ├── schemas/                  # Pydantic schemas (Auth, Users, KBs, Docs, Health)
│   │   ├── services/
│   │   │   ├── auth/                 # AuthService, PasswordService, TokenService
│   │   │   ├── users/                # UserService
│   │   │   ├── organizations/        # OrganizationService
│   │   │   ├── knowledge_bases/      # KnowledgeBaseService
│   │   │   └── documents/            # DocumentService, StorageService, Validation
│   │   └── main.py                   # FastAPI app entry point & lifespan
│   ├── alembic/                      # Database migrations (async)
│   ├── tests/                        # Automated unit & integration tests (47 tests)
│   ├── pyproject.toml                # Project metadata, dependencies & tool configs
│   └── Dockerfile                    # Multi-stage container definition
├── frontend/                         # Frontend application (Planned)
├── docker/
│   └── postgres/
│       └── init.sql                  # PostgreSQL extension initializations
├── docs/
│   ├── ARCHITECTURE.md               # Architecture details, Auth, Storage & RAG design
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

### Quickstart with Docker Compose

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
- **Knowledge Bases**: `POST /api/v1/knowledge-bases`, `GET /api/v1/knowledge-bases`
- **Document Upload**: `POST /api/v1/knowledge-bases/{kb_id}/documents`

---

## 🗺️ Roadmap

- [x] **Phase 1: Project Foundation** (FastAPI, PostgreSQL + pgvector, Alembic, Logging, Healthchecks, Docker)
- [x] **Phase 2: Authentication & Multi-Tenancy** (User accounts, Argon2id, JWT, Token Rotation, Organizations, RBAC, Tenant Isolation, BYOK DB Schema)
- [x] **Phase 3: Knowledge Bases & Document Management** (Knowledge bases, documents, storage abstraction, duplicate detection, lifecycle states, versioning)
- [ ] **Phase 4: Document Ingestion & Chunking Pipeline** (Parsers, semantic & recursive chunking, metadata extraction)
- [ ] **Phase 5: Embeddings & Vector Indexing** (Multi-provider embeddings, HNSW / IVFFlat indexing in pgvector)
- [ ] **Phase 6: Hybrid Retrieval & Reranking** (Dense vector search + BM25 sparse search + Cohere/Cross-Encoder reranking)
- [ ] **Phase 7: RAG Generation & LLM Gateway** (Context assembly, streaming responses, citations, BYOK secret vault)
- [ ] **Phase 8: Grounding Verification & Evaluation** (Hallucination detection, RAGAS metrics)
- [ ] **Phase 9: Frontend UI** (Modern SPA for document management & RAG playground)
