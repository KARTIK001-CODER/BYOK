# RAGForge

RAGForge is a production-oriented, multi-tenant Retrieval-Augmented Generation (RAG) platform built with **FastAPI**, **PostgreSQL + pgvector / Neon PostgreSQL**, and a modular, provider-agnostic AI pipeline.

---

## Current Architecture Roadmap

- [x] **Phase 1: Project Foundation** (FastAPI, PostgreSQL 16 + pgvector, Async SQLAlchemy 2.0, Alembic, Docker, Structured Logging, Health Probes)
- [x] **Phase 2: Auth, Multi-Tenancy & BYOK Schema** (Argon2id, JWT + Refresh Token Rotation, Organizations, RBAC `OWNER > ADMIN > MEMBER`, BYOK Schema)
- [x] **Phase 3: Knowledge Bases & Document Management** (Knowledge Bases, Document Lifecycle `UPLOADED ➔ PROCESSING ➔ READY ➔ FAILED ➔ ARCHIVED`, Storage Abstraction, Magic Byte Inspection, Duplicate Detection)
- [x] **Phase 4: Document Ingestion & Processing Pipeline** (Multi-Format Extraction [PDF, TXT, MD, DOCX], Text Normalization, Recursive Chunking, Ingestion Jobs, Provenance Chunks)
- [x] **Phase 5: Embeddings & Vector Storage** (Embedding Provider Abstraction, FastEmbed `BAAI/bge-small-en-v1.5`, Native `pgvector` Vector Storage, HNSW Cosine Index, Resumable Batching)
- [x] **Phase 6: Retrieval Engine & Hybrid Search** (Dense Vector pgvector `<=>` Search, PostgreSQL Full-Text Search `tsvector` + GIN + `ts_rank_cd`, Reciprocal Rank Fusion `RRF(d)`, Tenant Isolation, IR Evaluation Framework)
- [x] **Phase 7: RAG Generation & LLM Orchestration** (Prompt Engineering, Context Synthesis, Grounding & Citations, SSE Streaming, Conversations) — implemented in `backend/app/services/rag/` + `backend/app/api/v1/chat.py`, verified by `tests/test_rag_*.py` + `tests/test_chat_api.py`
- [ ] **Phase 8: BYOK Vault & Provider Integrations** (AES-256-GCM Key Vault — schema only in `provider_credentials`; provider pattern done for Groq/OpenAI/Gemini/Mock via `backend/app/services/llm/`, server-key fallback; Anthropic pending)

---

## End-to-End Pipeline (Phases 1–7)

```text
User Query
    │
    ▼
RAG Service (Conversation → Retrieval Router → Context → Prompt → LLM)
    │
    ▼
Retrieval Service (Tenant Authorization & Scoping, Query Intelligence opt-in)
    │
    ├─────────────────────────────┐
    ▼                             ▼
Query Embedding (384-dim)    PostgreSQL Full-Text Search
(asyncio.to_thread,               │
overlaps KB authz)                ▼
    │                      GIN Index + ts_rank_cd
    ▼                             │
pgvector Cosine Search            │
(HNSW, isolated session)          │
    │                             │
    └──────────────┬──────────────┘
                   ▼
       Reciprocal Rank Fusion (RRF k=60)
                   │
                   ▼
         Chunk Deduplication
                   │
                   ▼
     Metadata & Version Filtering
                   │
                   ▼
   Top-K Ranked Evidence + Provenance
                   │
                   ▼
   Context Builder (token budget) → Prompt Builder → LLM (Groq/OpenAI/Gemini/Mock)
                   │
                   ▼
   Citations + SSE (start/retrieval/token/citation/groundedness/done/error) → Persistence
```

> Data plane is **single Postgres + pgvector + FTS** (not polyglot): one `pgvector/pgvector:pg16` service in `docker-compose.yml`, `Vector(384)` HNSW + `TSVECTOR` GIN on `document_chunks`, structured tables for users/orgs/KBs/docs/conversations/messages.

---

## Getting Started

### 1. Prerequisites
- Python 3.12+
- Node 20+ (frontend Vite 6)
- Docker & Docker Compose
- PostgreSQL 16+ with `pgvector` extension (or [Neon PostgreSQL](https://neon.tech))

---

## Getting Started

### 1. Prerequisites
- Python 3.12+
- Docker & Docker Compose
- PostgreSQL 16+ with `pgvector` extension (or [Neon PostgreSQL](https://neon.tech))

### 2. Environment Configuration
Copy `.env.example` to `.env` and configure settings:
```bash
cp .env.example .env
```

### 3. Running Locally with Docker
```bash
docker compose up -d
```

### 4. Running Backend Development Server
```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate  # Windows
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Running Tests & Linters
```bash
cd backend
pytest -v
ruff check app
ruff format --check app

cd ../frontend
npm ci
npm run build
```

See `Makefile` for shortcuts: `make test`, `make lint`, `make format`, `make frontend`, `make ci`.
