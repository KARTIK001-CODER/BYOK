# BYOK (Bring Your Own Knowledge) Architecture

This document provides a high-level overview of the BYOK platform's architecture, including the technologies used and the core flow of data across the system. 

## 1. System Overview

BYOK is a Retrieval-Augmented Generation (RAG) platform. It allows users to upload documents, converts those documents into embeddings (vector representations), stores them, and then uses a Large Language Model (LLM) to answer user questions based on the retrieved context from those documents.

The project is structured as a full-stack application with a clear separation of concerns:
- **Frontend (Client)**: A modern web interface for users to upload knowledge, manage settings, and chat with their knowledge base.
- **Backend (API Layer & Business Logic)**: A robust REST API that handles data processing, authentication, integration with vector and relational databases, and orchestration of RAG operations.
- **Data Persistence**: A single PostgreSQL 16 + pgvector database (structured tables + `Vector(384)` HNSW + `TSVECTOR` GIN FTS on `document_chunks`) plus local filesystem object storage. No separate vector DB.

---

## 2. Technology Stack

### Frontend (Client-Side)
The frontend is built for performance and a modern development experience:
- **Framework**: [React 19](https://react.dev/) - A JavaScript library for building user interfaces.
- **Build Tool**: [Vite](https://vitejs.dev/) - A fast, modern frontend build tool.
- **Language**: [TypeScript](https://www.typescriptlang.org/) - For static typing and better developer tooling.
- **Routing**: View switching is state-driven in `App.tsx` (`chat` | `knowledge`); `react-router-dom` (v7) is installed but currently unused — no client-side routes are defined.
- **Icons**: [Lucide React](https://lucide.dev/) - A beautiful and consistent icon toolkit.
- **Markdown Rendering**: [React Markdown](https://github.com/remarkjs/react-markdown) (with GFM via `remark-gfm`; code blocks styled with app CSS) for displaying rich chat responses.

### Backend (Server-Side)
The backend follows a clean architecture pattern, prioritizing type safety, validation, and modularity:
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) - A modern, fast web framework for building APIs with Python 3.8+ based on standard Python type hints.
- **Language**: [Python 3.12](https://www.python.org/) (`requires-python >=3.12` in `backend/pyproject.toml`)
- **RAG & AI Stack**: Hybrid retrieval (pgvector HNSW + Postgres FTS + RRF k=60), FastEmbed `BAAI/bge-small-en-v1.5` 384d, provider-agnostic LLM factory (Groq/OpenAI/Gemini/Mock), plus opt-in intelligence layers: `query_intelligence`, `retrieval_intelligence` (adaptive/multi-query/decomposition), `reranking`, `verification`.
- **Data Validation**: [Pydantic](https://docs.pydantic.dev/latest/) - Data parsing and validation using Python type annotations.
- **ORM (Object-Relational Mapping)**: [SQLAlchemy](https://www.sqlalchemy.org/) - The Python SQL toolkit and Object Relational Mapper.
- **Database Migrations**: [Alembic](https://alembic.sqlalchemy.org/en/latest/) - A lightweight database migration tool for usage with SQLAlchemy.
- **RAG & AI Stack**: Custom modular integrations for LLM providers (OpenAI, Gemini, Groq, local models) and Embedding models.
- **Package Management**: Typically `pip` with `pyproject.toml` (potentially using `poetry` or standard `venv`).

---

## 3. Backend Architecture & Core Modules

The backend (`/backend/app`) is designed in a modular way, where different domains of the application are encapsulated within their own services.

### Directory Structure & Responsibilities

1. **`app/main.py`**: The application entry point. Initializes FastAPI, configures CORS, handles global exception logic, and registers API routers.
2. **`app/core/`**: Core configuration (environment variables), security (password hashing), and application logging.
3. **`app/api/`**: The presentation layer. Defines the REST endpoints (`GET`, `POST`, etc.), receives HTTP requests, validates them via schemas, and calls the appropriate services.
4. **`app/db/`**: Handles the connection to the underlying relational database (via SQLAlchemy).
5. **`app/models/`**: SQLAlchemy models that define the structure of the database tables (e.g., `User`, `Document`, `Conversation`, `Message`).
6. **`app/schemas/`**: Pydantic models (Data Transfer Objects) that define the shape of the data entering (requests) and leaving (responses) the API.
7. **`app/services/`**: The business logic layer.
   - `auth/`: User authentication, JWT token generation, and password validation.
   - `ingestion/`: Handles document uploads, extracts text (PDF, Word, Markdown, Text), normalizes it, and splits it into smaller chunks suitable for embedding.
   - `embeddings/`: Takes text chunks and converts them into dense vector embeddings (local FastEmbed; batch `to_thread` off event loop).
   - `retrieval/`: Hybrid search (vector + keyword in parallel via isolated sessions, RRF fusion). Query embedding overlaps KB authz.
   - `query_intelligence/` + `retrieval_intelligence/`: Opt-in (`ENABLE_*=False`) deterministic strategy/budget/retry/confidence/fallback; adaptive router in `RAGService` falls back to Hybrid.
   - `reranking/` + `verification/`: Opt-in rerank (2s bounded) and groundedness checks.
   - `llm/`: Provider factory (`groq/openai/gemini/mock`); server-key fallback (BYOK vault schema-only).
   - `rag/`: The orchestrator that ties Retrieval and LLMs together (context budget, prompt, citations, SSE `start/retrieval/token/citation/groundedness/done/error`, pre-LLM commit).
   - `incidents/`: TracePilot Incident Foundation v0 — tenant-scoped incidents, idempotent evidence ingestion (`UNIQUE(incident_id, deduplication_key)`), deterministic timeline (`event_timestamp ASC, id ASC`). No causal inference at this layer.
   - `documents/`, `users/`, `organizations/`: Standard CRUD services for application entities.

## 4. TracePilot Incident Foundation v0

Tenant-isolated SRE incident records (`incidents`, `evidence_events`; migration `0008`, hardened by `0009`):

- **Endpoints** (`/api/v1/incidents`): create/list/get incident, ingest/list evidence (idempotent via `deduplication_key`, duplicate signalled with `X-TracePilot-Duplicate`), deterministic timeline.
- **Isolation**: every incident/evidence query filters by `organization_id`; cross-tenant access returns `404` (no existence leak); explicit `organization_id` outside membership returns `403`.
- **Guarantee**: timeline provides chronological evidence only — no root-cause hypotheses (Milestone 2 scope).

## 4b. TracePilot Investigation Engine (Milestone 2)

Durable, evidence-grounded investigations (`investigation_jobs`, `root_cause_hypotheses`, `hypothesis_evidence_links`; migration `0010`):

- **Endpoints**: `POST /api/v1/incidents/{id}/investigations` (idempotent via `idempotency_key`, duplicate signalled with `X-TracePilot-Duplicate`), `GET .../investigations` (list), `GET /api/v1/investigations/{job_id}` (poll for `stage`/`progress`), `POST .../cancel` (queued only), `GET .../hypotheses`, `GET /api/v1/hypotheses/{id}`. Polling is the supported progress mechanism (no SSE).
- **Durability**: DB row is the source of truth; atomic conditional-UPDATE claiming; stale `running` jobs re-queued by `scripts/run_investigation_worker.py` (one pass or `--loop`). State machine: `queued -> running -> completed/failed`, `queued -> cancelled` only. Terminal transitions are conditional UPDATEs, so a stale read (cancel-after-claim, complete-after-cancel) yields 409 instead of an illegal transition; repeated cancel is also 409.
- **Single active job**: at most one `queued`/`running` job per incident — enforced by partial unique index `uq_investigation_jobs_single_active` (migration `0011`) as the final backstop behind the application-level dedupe. Terminal jobs are unconstrained, so re-investigation after completion always works.
- **Retries**: attempts increment on claim only (never on progress writes); stale jobs re-queue until `max_attempts`, then fail with a safe summary. Each attempt starts from a clean slate (prior hypotheses/links cleared) so retries never duplicate results. In-flight provider generation cannot be interrupted; if ownership is lost mid-run, results are discarded, never persisted.
- **Retrieval (Milestone 3A — Evidence Hybrid Retrieval)**:
  - Incident evidence carried in `evidence_events` is embedded using FastEmbed `BAAI/bge-small-en-v1.5` (384-dimensional vector, HNSW cosine distance index) added via forward-only migration `0012_evidence_embeddings`.
  - Deterministic text representations are sanitized during embedding to prevent leaking secrets, credentials, auth tokens, or oversized payloads into vector space.
  - Safe ingestion: evidence events are persisted first; embedding generation runs as a non-blocking step where provider failures or timeouts never roll back or corrupt the evidence record.
  - Operational backfill (`scripts/backfill_evidence_embeddings.py`): idempotent, resumable, tenant-scoped batch backfill tool with dry-run and error isolation.
  - Multi-channel hybrid retrieval combines lexical term overlap, dense semantic vector similarity, and recency ranking fused via Reciprocal Rank Fusion (RRF) with deterministic tie-breaking.
  - Strict tenant and incident isolation is enforced inside SQL queries before ranking: `organization_id == caller_org AND incident_id == requested_incident`.
  - Fail-safe degradation: provider timeouts or dimension mismatches automatically fall back to lexical+recency retrieval without failing investigation jobs.
- **Safety**: evidence quoted as untrusted data; citations validated server-side (unknown/cross-incident/cross-tenant IDs rejected, hypotheses persisted as `rejected`); confidence labels flagged uncalibrated; failures carry safe `error_category` summaries only; correlation disclaimer on every result.

---


---

## 5. The Core Flow (How a Chat Works)

When a user asks a question about their uploaded documents, the data flows through the system as follows:

1. **Request**: The Frontend sends a `POST` request with the user's message to the `app/api/` chat endpoint.
2. **Validation**: The API layer uses Pydantic (`app/schemas/`) to validate the incoming request.
3. **Retrieval (RAG Service)**: The `rag` service takes the user's message and asks the `retrieval` service to find relevant context.
4. **Vector Search**: The `retrieval` service converts the user's message into an embedding and performs a similarity search against the previously embedded `document_chunks` in the database.
5. **Prompt Construction**: The `rag` service gathers the retrieved chunks (context), formats them along with the conversation history into a structured prompt.
6. **LLM Generation**: The prompt is sent to the `llm` service (which talks to an AI provider like OpenAI, Gemini, etc.).
7. **Response & Citations**: The LLM streams back an answer based *only* on the provided context. The `rag` service maps the chunks used back to their source documents to generate citations.
8. **Delivery**: The answer and citations are returned through the API to the Frontend, which renders the markdown response to the user.
