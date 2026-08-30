# RAGForge Architecture Documentation

RAGForge is a production-grade, modular Retrieval-Augmented Generation (RAG) platform designed for reliability, scalability, and strict security compliance.

---

## Phase 1 Implemented Architecture

Phase 1 establishes the clean engineering foundation, API routing, database layer, configuration management, structured logging, and health checking mechanisms.

```
Client (HTTP / REST)
       │
       ▼ [X-Request-ID Header]
┌───────────────────────────────────────────────────────────┐
│                      FastAPI Gateway                      │
│                                                           │
│  ├── Request ID & Access Logging Middleware               │
│  ├── Configurable CORS Middleware                         │
│  └── Centralized Exception Handling                       │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────┐
│                      API Layer (/api/v1)                  │
│                                                           │
│  ├── /health (Liveness Probe)                             │
│  ├── /ready  (Readiness Probe)                            │
│  └── /info   (System Metadata)                            │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────┐
│                      Service Layer                        │
│                                                           │
│  └── HealthService (Infrastructure verification)          │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────┐
│                      Database Layer                       │
│                                                           │
│  ├── SQLAlchemy 2.0 Async Session Management              │
│  ├── Connection Pooling (asyncpg)                         │
│  └── Alembic Migrations                                   │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────┐
│                   PostgreSQL 16 + pgvector                │
│                                                           │
│  ├── vector extension                                     │
│  └── uuid-ossp extension                                  │
└───────────────────────────────────────────────────────────┘
```

---

## Future Target Architecture (Planned - Phases 2+)

> [!NOTE]
> The following diagram represents the planned evolution for upcoming phases. These components (Ingestion, Hybrid Retrieval, Reranker, LLM Gateway, BYOK Secret Store, Redis, Workers) are intentionally **not** implemented in Phase 1.

```
                    ┌────────────────────────┐
                    │     Frontend (SPA)     │
                    └───────────┬────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                             FastAPI Gateway                              │
│                                                                          │
│  ├── Auth & Organization RBAC                                            │
│  ├── Rate Limiting & Audit Logging                                       │
│  └── BYOK Secret Decryption (In-Memory Session)                          │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           RAG Orchestrator                               │
│                                                                          │
│  ├── 1. Query Processing (Decomposition, Rewriting, HyDE)                │
│  ├── 2. Hybrid Retrieval (Dense Vector + Sparse Full-Text BM25)          │
│  ├── 3. Reranking (Cross-Encoder / Cohere Rerank)                        │
│  ├── 4. Context Window Assembly & Token Budgeting                        │
│  ├── 5. Multi-Provider LLM Gateway (Groq, OpenAI, Anthropic, Gemini)    │
│  └── 6. Grounding & Citation Verification (Faithfulness check)           │
└──────────────┬────────────────────┬───────────────────────┬──────────────┘
               │                    │                       │
               ▼                    ▼                       ▼
    ┌──────────────────┐  ┌──────────────────┐   ┌──────────────────────┐
    │  PostgreSQL 16   │  │   Redis Cache    │   │  Background Workers  │
    │    + pgvector    │  │ (Query Cache &   │   │ (Document ingestion, │
    │ (Vectors & Rel)  │  │  Session Store)  │   │  chunking, embed)    │
    └──────────────────┘  └──────────────────┘   └──────────────────────┘
```

---

## Bring Your Own Key (BYOK) Security Architecture

A core architectural tenet of RAGForge is zero plaintext exposure of user LLM API keys:

1. **Server Environment Separation**: Server `.env` files contain **only** server operational configuration (`APP_ENV`, `DATABASE_URL`, `LOG_LEVEL`, `CORS_ORIGINS`).
2. **Encrypted Vault Storage**: User API keys for model providers (OpenAI, Groq, Anthropic, Google) are supplied per user/organization and encrypted before storing in the database using strong encryption (AES-256-GCM).
3. **In-Memory Decryption**: Keys are decrypted exclusively in ephemeral worker/request memory at the point of dispatching an inference call, ensuring they are never logged or committed to disk.

---

## Architectural Invariants
- **Non-blocking I/O**: All database access and network calls use asynchronous programming (`async`/`await`, `asyncpg`, `AsyncSession`).
- **Traceability**: Every HTTP request receives an `X-Request-ID` attached to structured log outputs.
- **Fail-Safe Centralized Error Handling**: Internal stack traces and credentials are never returned in public HTTP responses.
