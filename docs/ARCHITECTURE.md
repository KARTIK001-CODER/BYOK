# TracePilot Architecture Documentation

TracePilot is an AI-powered SRE incident investigation and root-cause analysis platform designed for reliability, operational safety, multi-tenancy, and evidence-grounded decision making.

---

## 1. High-Level System Architecture

```text
                     Organization (Tenant Boundary)
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
         ▼                     ▼                     ▼
     Incidents         Evidence Ingestion    Runbooks / Knowledge
         │                     │                     │
         │             ┌───────┴───────┐             │
         │             ▼               ▼             ▼
         │        Single Ingest   Bulk Batch    pgvector + FTS
         │             │               │             │
         │             └───────┬───────┘             │
         │                     ▼                     │
         │              Deduplication                │
         │                     │                     │
         ▼                     ▼                     │
   ┌──────────────────────────────────────────┐      │
   │      Deterministic Incident Timeline     │◄─────┘
   └───────────────────┬──────────────────────┘
                       │
                       ▼
       ┌───────────────────────────────┐
       │   Background Investigation    │ (Worker with Heartbeats)
       │           Engine              │
       └───────────────┬───────────────┘
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
  Root-Cause Hypotheses      Groundedness & Uncertainty
  (with Evidence Citations)  Evaluator (Deterministic NLI)
         │                           │
         └─────────────┬─────────────┘
                       ▼
       ┌───────────────────────────────┐
       │   Remediation Review Center   │
       │   (Human-in-the-Loop Review)  │
       └───────────────┬───────────────┘
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
   Deterministic Risk          Policy Enforcement
   Assessment (Blast Radius)   (Separation of Duties)
         │                           │
         └─────────────┬─────────────┘
                       ▼
       ┌───────────────────────────────┐
       │     Safe Execution Boundary   │
       │   (Automated Execution 403)   │
       └───────────────────────────────┘
                       │
                       ▼
         Immutable Audit Trail & Export
```

---

## 2. Core Architectural Pillars

### 2.1 Multi-Tenant Isolation
- Strict organization-level scoping enforced across all API endpoints, database queries, and background jobs.
- All entities (`incidents`, `evidence_events`, `investigation_jobs`, `remediation_proposals`, `audit_events`, `knowledge_bases`, `documents`) are scoped by `organization_id`.
- Cross-tenant data leakage is prevented at both ORM and query level.

### 2.2 Evidence Pipeline & Timeline Reconstruction
- Ingests multi-source telemetry: `metrics`, `logs`, `traces`, `alerts`, `deployments`, `config_changes`, and `notes`.
- Supported via single ingestion (`POST /api/v1/evidence/events`) and batch ingestion (`POST /api/v1/evidence/batch`).
- Deterministic deduplication enforced via `deduplication_key` unique constraints per incident.
- Chronological timeline reconstruction with sub-second ordering, severity filters, and source categorizations.

### 2.3 Hybrid Retrieval & Contextual Runbook Search
- Dual-branch search combining dense vector embeddings (pgvector cosine similarity with `BAAI/bge-small-en-v1.5`) and PostgreSQL Full-Text Search (`tsvector` + GIN indexing).
- Reciprocal Rank Fusion (RRF $k=60$) balances semantic relevance and exact keyword matching.
- Automatically correlates active incident symptoms with operational runbooks, post-mortems, and architectural documentation.

### 2.4 Investigation Engine & SSE Streaming
- Asynchronous background worker processes investigations decoupled from the HTTP API.
- Real-time investigation progress streaming via Server-Sent Events (SSE) with stage tracking (`analyzing_timeline`, `evaluating_hypotheses`, `scoring_groundedness`, `synthesizing_remediation`).
- Reconnection support with `Last-Event-ID` header and replay buffers.
- Periodic worker heartbeats and stale job reclamation ensure zero orphaned investigations if workers restart.

### 2.5 Groundedness & Uncertainty Evaluation
- Every generated hypothesis must cite specific evidence IDs.
- Deterministic Natural Language Inference (NLI) scoring measures factual alignment between claims and cited evidence.
- Flags contradictory evidence, ungrounded extrapolations, and missing telemetry to prevent hallucinated conclusions.

### 2.6 Remediation Governance & Safety Boundary
- Proposes structured, advisory action plans with deterministic risk scoring (blast radius, reversibility, environment severity).
- Human-in-the-loop review enforcing strict separation of duties (authors cannot self-approve; high-risk actions require elevated roles).
- **Non-Execution Safety Boundary**: Automated infrastructure execution remains strictly disabled (`POST /api/v1/remediations/{id}/execute` unconditionally returns `HTTP 403 Forbidden`). All commands are read-only advisory.
- Comprehensive audit trails record proposal lifecycle, risk assessments, reviewer decisions, and tamper-resistant audit logs.

---

## 3. Database Schema & Migration Chain

The schema is managed with Alembic migrations:

1. `0001_enable_pgvector`: Enables pgvector PostgreSQL extension.
2. `0002_auth_and_multitenancy`: Core auth, organizations, memberships, users, refresh tokens, provider credentials.
3. `0003_knowledge_bases_and_documents`: Knowledge bases, documents, and document versions.
4. `0004_ingestion_jobs_and_chunks`: Ingestion jobs and document chunks.
5. `0005_embeddings_and_vector_storage`: FastEmbed vectors, embedding jobs, HNSW indexing.
6. `0006_retrieval_and_full_text_search`: TSVECTOR search columns, GIN index, composite retrieval indexes.
7. `0007_conversations_and_messages`: Conversation sessions and message provenance.
8. `0008_incident_foundation`: Incidents table and evidence events table.
9. `0009_evidence_dedup_idempotency`: Deduplication key constraints and source indexing.
10. `0010_investigation_jobs`: Investigation jobs, hypotheses, and citation tracking.
11. `0011_runbook_indices`: Operational runbook linking and search indexes.
12. `0012_evaluations`: Groundedness evaluation runs and test benchmarks.
13. `0013_batch_ingestion_jobs`: High-throughput batch telemetry ingestion jobs.
14. `0014_remediation_proposals`: Remediation proposals and risk assessment metadata.
15. `0015_audit_events`: Append-only audit logs for remediation and governance decisions.
16. `0016_worker_heartbeats`: Background worker heartbeat monitoring and liveness tracking.

---

## 4. Frontend Workspace Architecture

The frontend is an SRE incident investigation workspace built with React 19, TypeScript, and Vite:
- **Incident Dashboard (`IncidentDashboard.tsx`)**: High-level overview of active incidents, MTTR metrics, severity breakdowns, and quick creation.
- **Incident Workspace (`IncidentDetailModal.tsx`)**: Unified investigation command center containing:
  - Incident timeline and evidence inspection.
  - Runbook search and discovery.
  - Streaming investigation progress and hypothesis evaluation.
  - Direct links to remediation review.
- **Remediation Review Center (`RemediationReviewCenter.tsx`)**: Human approval workspace displaying risk breakdowns, policy compliance, dry-run validations, and audit logs.
- **Telemetry Ingestion Modal (`EvidenceIngestModal.tsx`)**: Form-based and raw JSON/batch operational evidence ingestion.
