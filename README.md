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

---

## TracePilot: AI Incident Investigation Platform (Milestone 1 — Incident Foundation v0)

TracePilot transforms the platform into an SRE incident investigation engine. The Incident Foundation establishes tenant-isolated incident tracking, normalized multi-source evidence ingestion with deduplication idempotency, and a deterministic chronological timeline.

### 1. Database Migrations
Run forward Alembic migrations to create `incidents` and `evidence_events` tables:
```bash
cd backend
alembic upgrade head
```
*(Linear revision: `0008_incident_foundation` applied on top of `0007_conversations_and_messages`)*

### 2. Core API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/incidents` | Create a new incident scoped to caller's organization |
| `GET` | `/api/v1/incidents` | List incidents with filtering (`status`, `severity`, `service_name`, `environment`) and pagination |
| `GET` | `/api/v1/incidents/{incident_id}` | Retrieve incident details with evidence count |
| `POST` | `/api/v1/incidents/{incident_id}/evidence` | Ingest normalized evidence event (idempotent via `deduplication_key`) |
| `GET` | `/api/v1/incidents/{incident_id}/evidence` | List raw evidence events with pagination |
| `GET` | `/api/v1/incidents/{incident_id}/timeline` | Retrieve deterministic chronologically sorted timeline (`event_timestamp ASC`, tie-breaker `id ASC`) |

### 3. Sample Usage

#### Create an Incident
```bash
curl -X POST "http://localhost:8000/api/v1/incidents" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Payment API Failure Incident",
    "severity": "critical",
    "service_name": "payment-api",
    "environment": "production",
    "description": "502 Bad Gateway spike observed on checkout checkout route"
  }'
```

**Response (201 Created):**
```json
{
  "id": "7b0a8809-5487-4389-9eb1-83952ba5c3b9",
  "organization_id": "org_e92bf189",
  "title": "Payment API Failure Incident",
  "description": "502 Bad Gateway spike observed on checkout checkout route",
  "severity": "critical",
  "status": "open",
  "service_name": "payment-api",
  "environment": "production",
  "created_by_user_id": "usr_99812",
  "resolved_at": null,
  "incident_metadata": null,
  "created_at": "2026-10-04T14:00:00Z",
  "updated_at": "2026-10-04T14:00:00Z",
  "evidence_count": 0
}
```

#### Ingest Evidence (Idempotent)
```bash
curl -X POST "http://localhost:8000/api/v1/incidents/7b0a8809-5487-4389-9eb1-83952ba5c3b9/evidence" \
  -H "Authorization: Bearer <JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "deployment",
    "event_type": "deployment.completed",
    "event_timestamp": "2026-10-04T14:02:10Z",
    "summary": "Deployment v2.4.1 completed for payment-api",
    "source_reference": "commit-sha-9f8a3c",
    "normalized_payload": {
      "service": "payment-api",
      "version": "v2.4.1"
    },
    "deduplication_key": "deploy-payment-api-v2.4.1-20261004140210"
  }'
```
*Note: If the exact same `deduplication_key` is posted again, the API returns `200 OK` with header `X-TracePilot-Duplicate: true` and the existing evidence record without duplicate database row insertion.*

#### Query Deterministic Timeline
```bash
curl -X GET "http://localhost:8000/api/v1/incidents/7b0a8809-5487-4389-9eb1-83952ba5c3b9/timeline" \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

**Response (200 OK):**
```json
{
  "incident_id": "7b0a8809-5487-4389-9eb1-83952ba5c3b9",
  "total_events": 3,
  "events": [
    {
      "id": "ev_01",
      "incident_id": "7b0a8809-5487-4389-9eb1-83952ba5c3b9",
      "source_type": "deployment",
      "event_type": "deployment.completed",
      "event_timestamp": "2026-10-04T14:02:10Z",
      "summary": "Deployment v2.4.1 completed for payment-api",
      "source_reference": "commit-sha-9f8a3c",
      "normalized_payload": {"service": "payment-api", "version": "v2.4.1"},
      "deduplication_key": "deploy-payment-api-v2.4.1-20261004140210"
    },
    {
      "id": "ev_02",
      "incident_id": "7b0a8809-5487-4389-9eb1-83952ba5c3b9",
      "source_type": "alert",
      "event_type": "alert.firing",
      "event_timestamp": "2026-10-04T14:03:04Z",
      "summary": "HTTP 502 Bad Gateway rate exceeded 5% on payment-api",
      "source_reference": "https://monitor.example.com/alerts/502-spike",
      "normalized_payload": {"metric": "http_response_5xx_rate", "value": 0.082},
      "deduplication_key": "alert-payment-api-502-20261004140304"
    },
    {
      "id": "ev_03",
      "incident_id": "7b0a8809-5487-4389-9eb1-83952ba5c3b9",
      "source_type": "log",
      "event_type": "database.connection_timeout",
      "event_timestamp": "2026-10-04T14:03:12Z",
      "summary": "Database connection pool exhausted: connection acquisition timed out after 5000ms",
      "source_reference": "pod/payment-api-7b94cf67f8-8q2ml",
      "normalized_payload": {"pool_size": 20, "waiting_clients": 45},
      "deduplication_key": "log-db-timeout-payment-api-20261004140312"
    }
  ],
  "limit": 100,
  "offset": 0
}
```

### 4. Running Incident Foundation Tests
```bash
cd backend
pytest tests/test_incidents_api.py -v
```

### 5. Milestone Limitations & Next Steps
- **Milestone 1 Scope**: Strictly deterministic foundation (data modeling, tenant isolation, idempotency, ordering).
- **No Premature Causal Inferences**: The chronological timeline presents factual events in order; it does not infer causality from temporal proximity alone.
- **Next Milestone (Milestone 2)**: Persistent investigation jobs, hybrid vector/keyword retrieval over incident evidence, and cited root-cause hypotheses with explicit confidence scoring.

---

## Getting Started

### 1. Prerequisites
- Python 3.12+
- Node 20+ (frontend Vite 6)
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

