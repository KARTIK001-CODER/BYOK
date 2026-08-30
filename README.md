# RAGForge

RAGForge is a production-oriented, multi-tenant Retrieval-Augmented Generation (RAG) platform built with **FastAPI**, **PostgreSQL + pgvector / Neon PostgreSQL**, and a modular, provider-agnostic AI pipeline.

---

## Current Architecture Roadmap

- [x] **Phase 1: Project Foundation** (FastAPI, PostgreSQL 16 + pgvector, Async SQLAlchemy 2.0, Alembic, Docker, Structured Logging, Health Probes)
- [x] **Phase 2: Auth, Multi-Tenancy & BYOK Schema** (Argon2id, JWT + Refresh Token Rotation, Organizations, RBAC `OWNER > ADMIN > MEMBER`, BYOK Schema)
- [x] **Phase 3: Knowledge Bases & Document Management** (Knowledge Bases, Document Lifecycle `UPLOADED ➔ PROCESSING ➔ READY ➔ FAILED ➔ ARCHIVED`, Storage Abstraction, Magic Byte Inspection, Duplicate Detection)
- [x] **Phase 4: Document Ingestion & Processing Pipeline** (Multi-Format Extraction [PDF, TXT, MD, DOCX], Text Normalization, Recursive Chunking, Ingestion Jobs, Provenance Chunks)
- [x] **Phase 5: Embeddings & Vector Storage** (Embedding Provider Abstraction, FastEmbed `BAAI/bge-small-en-v1.5`, Native `pgvector` Vector Storage, HNSW Cosine Index, Resumable Batching)
- [ ] **Phase 6: Retrieval & Reranking Engine** (Vector Search, BM25 Hybrid Retrieval, RRF, Cross-Encoder Reranking)
- [ ] **Phase 7: RAG Generation & LLM Orchestration** (Prompt Engineering, Context Synthesis, Grounding & Citations)
- [ ] **Phase 8: BYOK Vault & Provider Integrations** (AES-256-GCM Key Vault, Groq, OpenAI, Anthropic, Gemini)

---

## End-to-End Pipeline (Phases 1–5)

```text
Uploaded File (PDF / TXT / MD / DOCX)
     │
     ▼
Validation & Magic Bytes Inspection
     │
     ▼
Format-Specific Extractor (PDF, DOCX, Markdown, Text)
     │
     ▼
Text Normalization (Control chars, line endings, excess whitespace)
     │
     ▼
Recursive Text Chunking (Hierarchy: \n\n ➔ \n ➔ Sentence ➔ Word ➔ Char)
     │
     ▼
Provenance Attachment (chunk_index, page_number, section_title, character/word count)
     │
     ▼
Document Chunks in PostgreSQL / Neon
     │
     ▼
Embedding Generation (BAAI/bge-small-en-v1.5, 384 dimensions)
     │
     ▼
Dense Vector Storage in pgvector (HNSW Cosine Vector Index)
```

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
pytest -v
ruff check .
ruff format --check .
```
