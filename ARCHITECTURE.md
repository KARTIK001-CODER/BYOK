# TracePilot Platform Architecture

This document provides a high-level overview of the TracePilot platform's architecture, including the technologies used and the core flow of data across the system.

## 1. System Overview

TracePilot is an AI-powered SRE incident investigation and root-cause analysis platform. It enables engineering teams to triage incidents, reconstruct deterministic timelines from multi-source telemetry, evaluate evidence-grounded hypotheses, discover operational runbooks, and govern remediation proposals with human-in-the-loop approvals.

The project is structured as a full-stack application with a clear separation of concerns:
- **Frontend (Client)**: A modern SRE investigation workspace built with React 19, TypeScript, and Vite for incident triage, timeline exploration, investigation monitoring, and remediation review.
- **Backend (API Layer & Business Logic)**: A robust asynchronous FastAPI application handling multi-tenant isolation, telemetry ingestion, hybrid retrieval (pgvector + FTS), asynchronous investigation workers, deterministic groundedness scoring, and remediation governance.
- **Data Persistence**: A single PostgreSQL 16 + pgvector database (structured tables + `Vector(384)` HNSW + `TSVECTOR` GIN FTS) plus local filesystem object storage. No separate vector DB.

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

## 4c. TracePilot Real-Time Investigation Streaming (Milestone 3B)

Real-time investigation progress streaming via Server-Sent Events (SSE):

- **Architecture Principle**: **SSE is a delivery mechanism only. InvestigationJob state remains persisted in PostgreSQL.** PostgreSQL is the sole authoritative source of truth. Investigation jobs execute asynchronously on workers independently of active SSE streams.
- **Endpoint**:
  `GET /api/v1/investigations/{job_id}/stream`
  - Requires standard JWT authentication (`Authorization: Bearer <token>`) and organization header (`X-Organization-ID: <org_id>`).
  - Strict tenant isolation: checks organization membership and returns a 404 with no state leak for non-existent or cross-tenant jobs.
- **Event Contract**:
  - `investigation.connected`: Emitted immediately upon connection handshake.
  - `investigation.snapshot`: Initial authoritative state payload reconstructed directly from PostgreSQL.
  - `investigation.progress`: Emitted whenever meaningful status, stage, or progress changes occur.
  - `investigation.completed`: Terminal event emitted when the job succeeds; includes sanitized `result_summary`. Stream terminates immediately.
  - `investigation.failed`: Terminal event emitted when the job fails; includes sanitized `error_summary` and `error_category`. Stream terminates immediately.
  - `investigation.cancelled`: Terminal event emitted when the job is cancelled. Stream terminates immediately.
- **Keepalive Heartbeats**:
  - Server emits periodic SSE comments (`: heartbeat\n\n`) at configurable intervals (`INVESTIGATION_SSE_HEARTBEAT_INTERVAL`, default 15s) to prevent intermediate proxies or clients from timing out idle connections. Heartbeats do not trigger client state transitions.
- **Database Session Lifecycle**:
  - The SSE endpoint does NOT hold open a long-lived database transaction or connection.
  - Each change-detection poll uses a dedicated short-lived async session that is immediately closed before sleeping (`INVESTIGATION_SSE_POLL_INTERVAL`, default 0.5s). This prevents database connection pool starvation under concurrent streams.
- **Client Disconnect & Failure Handling**:
  - Client disconnects (closing tab, network loss) cleanly exit the server streaming loop without logging application errors.
  - **Client disconnect never cancels, fails, or mutates the underlying `InvestigationJob`**; the job continues executing in PostgreSQL.
- **Frontend Integration (`useInvestigationStream`)**:
  - Reusable React hook exposing `status`, `stage`, `progress`, `resultSummary`, `errorSummary`, `connected`, `isTerminal`, and `refresh`.
  - Automatic reconnection with bounded exponential backoff.
  - Fail-safe REST polling fallback: If SSE connection attempts exceed the retry threshold (`maxReconnectAttempts`), the hook seamlessly degrades to polling `GET /api/v1/investigations/{job_id}` without interrupting the UI.
- **Known Limitations**:
  - Event delivery relies on short-interval database polling rather than Redis pub/sub or PostgreSQL LISTEN/NOTIFY, which is intentionally chosen to preserve zero-external-broker simplicity for this milestone.
  - High numbers of concurrent streams scale with database query throughput; connection pooling and short sessions prevent pool exhaustion.

---

## 4d. TracePilot Hypothesis Groundedness Assessment & Calibration (Milestone 4)

Deterministic, explainable evidence-groundedness evaluation and confidence calibration (`root_cause_hypotheses` columns; migration `0013_hypothesis_groundedness_assessment`):

- **Core Architectural Principles**:
  - **LLM confidence is untrusted**: Provider-reported confidence scores are subjective self-assessments. System confidence is computed deterministically from empirical evidence quality.
  - **Evidence-quality scoring, not probability**: System confidence represents evidence support strength, not statistical probability.
  - **Zero credit for invalid citations**: Foreign, invalid, or cross-tenant evidence citations receive zero grounding credit and cannot validate hypotheses.
  - **Temporal correlation is not causality**: Temporal sequence compatibility represents consistency, never absolute proof of causality.
  - **Contradictions are never suppressed**: Contradictory evidence monotonically discounts groundedness and system confidence scores.
- **Evaluator Components (`GroundednessEvaluator`)**:
  - **Citation Validity**: Strict boundary check against retrieved evidence for the specific incident and tenant.
  - **Evidence Diversity & Duplicate Damping**: Rewards corroboration across independent source types (`metric`, `log`, `alert`, `trace`, `deployment`); damps score inflation from repeated/identical log events.
  - **Temporal Sequence Compatibility**: Verifies that alleged causal triggers preceded initial symptom telemetry.
  - **Contradiction Penalty**: Applies monotonic penalties for cited counter-evidence.
  - **Unsupported Claim Detection**: Cross-checks failure mechanism assertions (e.g., connection pool exhaustion, memory leak, CPU throttling) against corroborating terms in cited evidence.
- **Persistence & API**:
  - Persisted directly on `root_cause_hypotheses`: `groundedness_score`, `system_confidence_score`, `system_confidence` (`low`/`medium`/`high`), `groundedness_status` (`well_supported`/`partially_supported`/`weakly_supported`/`contested`/`rejected`), `assessment_version`, and full `assessment_details` (JSONB).
  - Endpoint: `GET /api/v1/hypotheses/{id}/assessment`.
- **Evaluation Suite**:
  - Benchmark dataset: `backend/evaluation/groundedness/datasets/milestone4_groundedness_cases.json`.
  - Runner: `backend/evaluation/groundedness/evaluate.py`.
  - Verified benchmark results: 100% determinism, 100% unsupported claim detection rate, 100% contradiction detection rate, 100% invalid citation protection.

---

## 4e. TracePilot Remediation Proposals & Risk Assessment (Milestone 5A)

Structured, risk-assessed remediation proposals linked to verified hypotheses (`remediation_proposals`; migration `0014_remediation_proposals`):

- **Core Architectural Principles**:
  - **Non-executable advisory restrictions**: TracePilot remediation proposals are strictly advisory specifications and are non-executable (`is_executable = False`). The system prohibits automated or unattended execution in this phase.
  - **Mandatory human approval**: Mutating and high-impact operational steps (e.g., restarts, rollbacks, configuration changes, scale operations) strictly enforce `requires_human_approval = True`.
  - **Tenant isolation**: All proposals and action evaluations are strictly filtered by `organization_id`; cross-tenant lookups return 404 with zero existence leak.
- **Risk Assessment Engine (`RiskEvaluator`)**:
  - Evaluates action types, destructive keywords (`drop`, `delete`, `truncate`, `rm -rf`), reversibility, and blast radius (critical infrastructure like database, ingress, gateway vs. isolated services).
  - **Groundedness alignment**: Connects remediation risk to hypothesis grounding. Weakly grounded, contested, or low-confidence hypotheses trigger elevated risk ratings and explicit warnings.
  - Outputs overall risk level (`low`, `medium`, `high`, `critical`), composite risk score (0.0 to 1.0), and explainable risk factors.
- **Lifecycle State Machine**:
  - Valid transitions: `draft -> proposed -> reviewed -> rejected / superseded / cancelled`.
  - Terminal states (`rejected`, `superseded`, `cancelled`) cannot transition further.
  - Illegal transitions are rejected with HTTP 409 Conflict.
- **Endpoints (`/api/v1`)**:
  - `POST /incidents/{incident_id}/remediations`: Manually create a structured remediation proposal.
  - `POST /incidents/{incident_id}/remediations/generate`: Synthesize a tailored proposal from root-cause hypotheses.
  - `GET /incidents/{incident_id}/remediations`: List proposals with optional status filtering.
  - `GET /remediations/{remediation_id}`: Retrieve detailed proposal and action steps.
  - `PATCH /remediations/{remediation_id}/status`: Transition proposal lifecycle state.
  - `POST /remediations/{remediation_id}/risk-assessment`: Recalculate explainable risk assessment.
  - `POST /remediations/{remediation_id}/execute`: Always returns HTTP 403 Forbidden with security restriction notice.

---

## 4f. TracePilot Human Approval, Policy Enforcement & Audit Trail (Milestone 5B)

Production-minded human approval lifecycle, policy enforcement, and append-only audit trail (`remediation_approvals`, `remediation_audit_events`, `remediation_proposals` approval columns; migration `0015_remediation_approval_and_audit`):

- **Approval Policy & Deterministic Rules (`ApprovalPolicyService`)**:
  - **Tiered Role Authorization**:
    - **Low & Medium Risk**: Requires an authorized human reviewer (`MEMBER`, `ADMIN`, or `OWNER`).
    - **High & Critical Risk**: Requires an authorized `ADMIN` or `OWNER`. `MEMBER` approval attempts are strictly rejected (HTTP 403).
  - **Separation of Duties**: The proposal creator cannot approve their own proposal (`creator_self_approval_disallowed`, HTTP 403).
  - **Tenant Isolation**: Reviewer must belong to the proposal's organization. Cross-tenant lookups strictly return HTTP 404 (zero existence leakage).
  - **Terminal Proposal Protection**: Proposals in terminal states (`rejected`, `superseded`, `cancelled`, or `expired`) cannot be approved (HTTP 409 Conflict).
  - **Risk Assessment Freshness**: Approval requires a valid, completed risk assessment. Missing or stale assessments fail evaluation.
  - **Mutation Invalidation**: Any post-approval mutation to the proposal (such as risk recalculation or status adjustment) invalidates prior approval, increments proposal `version`, resets approval metadata, and emits an `approval_invalidated` audit event.
- **Durable Approval Records & Append-Only Audit Trail**:
  - **Durable Approval Records (`RemediationApproval`)**: Persists decision (`approved` or `rejected`), rationale, risk level at decision time, reviewer identity, policy version (`1.0.0`), proposal snapshot (`proposal_version`), and groundedness/evidence references. Database unique constraint `UNIQUE(proposal_id, proposal_version)` prevents duplicate decisions for the same proposal revision.
  - **Append-Only Audit Log (`RemediationAuditEvent`)**: Immutable chronological event stream tracking all lifecycle actions (`proposal_created`, `proposal_generated`, `risk_assessed`, `proposal_submitted`, `proposal_approved`, `proposal_rejected`, `approval_invalidated`, `status_changed`).
  - **Privacy & Safety**: Audit payloads sanitize tokens, secrets, credentials, and unrestricted raw prompts. Telemetry snapshots record only existing persisted incident metadata.
  - **Concurrency Safety**: Atomic `SELECT ... FOR UPDATE` row locks guard against concurrent approve/reject race conditions.
- **Safe Policy-Validation Dry-Run Design (`/dry-run`)**:
  - **Local Validation Only**: Evaluates proposal schema, evidence references, risk freshness, and reviewer role eligibility.
  - **No Infrastructure Contact**: Never runs shell commands, accesses Kubernetes/cloud/database APIs, or applies infrastructure changes. Output is explicitly labelled as local policy verification.
- **Execution Safety Boundary**:
  - **Forbidden Remediation Execution**: `POST /api/v1/remediations/{id}/execute` remains strictly disabled and unconditionally returns HTTP 403 Forbidden. Approval certifies policy compliance only; it never authorizes or triggers automated execution.
- **Endpoints (`/api/v1`)**:
  - `GET /remediations`: List remediation proposals across incidents with optional status and incident filters.
  - `POST /remediations/{remediation_id}/approve`: Submit human approval with mandatory rationale.
  - `POST /remediations/{remediation_id}/reject`: Submit rejection with rationale.
  - `GET /remediations/{remediation_id}/approvals`: Retrieve append-only approval and rejection decision history.
  - `GET /remediations/{remediation_id}/audit`: Retrieve comprehensive lifecycle audit trail.
  - `POST /remediations/{remediation_id}/dry-run`: Execute local policy validation dry-run without mutating state.

---

## 4g. TracePilot Remediation Review UX & Policy Visibility (Milestone 5C)

Production-minded SRE investigation frontend for human approval lifecycle, policy visibility, and audit trail inspection (`RemediationReviewCenter`, `ProposalDetailView`, `RiskAssessmentView`, `ActionStepsList`, `EvidenceProvenanceView`, `PolicyExplanationCard`, `ApprovalWorkflowModal`, `AuditTrailTimeline`, `DryRunModal`):

- **Remediation Review Center & Navigation**:
  - **First-Class SRE Navigation**: Integrated `"remediations"` view in `Navbar` and `Sidebar` with incident context switching.
  - **Master-Detail Workspace**: Filterable master list (status, risk level, keyword search) and comprehensive proposal detail pane.
- **Explainable Risk & Policy Visibility**:
  - **Deterministic Risk Breakdown**: Visual hierarchy for risk levels (`low`, `medium`, `high`, `critical`), composite risk meters, blast radius, reversibility, and heuristic safety disclaimers.
  - **Policy Explanation & Separation of Duties**: Explains authorization rules directly in the UI (creator self-approval prohibited, role tier requirements for high/critical risks, terminal state constraints, and risk freshness).
- **Authorized Approval & Rejection Workflow**:
  - **Interactive Decision Modals**: Confirmation dialogs enforcing required rationales (with validation).
  - **Concurrency & Stale State Handling**: Safe handling of HTTP 409 conflict errors that automatically refresh authoritative server state without discarding user input. Duplicate submissions prevented while requests are in flight.
- **Evidence Provenance & Telemetry Grounding**:
  - Distinguishes observed empirical incident telemetry from inferred hypotheses and advisory recommendations.
- **Local Policy Dry-Run Visibility**:
  - Interactive "Validate Proposal" action displaying local simulation results with explicit disclaimers confirming zero infrastructure APIs were contacted.
- **Execution Safety Guarantee**:
  - Persistent Safe Execution Barrier banners throughout the UI; all proposed commands labeled read-only advisory. Remediation execution actions remain completely disabled.

---

## 4h. TracePilot Operational Readiness, Sandbox Validation & Audit Export (Milestone 6)

Hardening operational reliability, structured observability, local sandbox simulation, and exportable audit trails:

- **Operational Health and Readiness Probes**:
  - **Liveness Probes (`/health`, `/health/live`, `/api/v1/health`)**: Ultra-lightweight process checks verifying FastAPI web server execution without database roundtrips.
  - **Readiness Probes (`/ready`, `/health/ready`)**: Evaluates essential dependencies (PostgreSQL database probe via `SELECT 1` bounded by 2.0s timeout, pgvector extension check on PostgreSQL dialects) and background worker operational state. Returns HTTP 200 with `status: "ready"` (or `"degraded"` if optional components are absent) and HTTP 503 with `status: "unhealthy"` if database connectivity fails.
  - **Worker Status Probes (`/health/worker`, `/api/v1/health/worker`)**: Tracks worker operational liveness, heartbeat timestamps, and backlog metrics.
- **Durable Worker Heartbeats & Investigation Reliability**:
  - **Worker Heartbeat Tracking (`WorkerHeartbeat`, migration `0016_worker_heartbeats`)**: Worker processes periodically persist heartbeats (`last_heartbeat_at`, `status`, `completed_jobs_count`, `worker_metadata`). Heartbeats within 120s are classified as `active`, older heartbeats as `stale`, and zero heartbeats with no running jobs as `idle`.
  - **Stale Job Reclamation (`InvestigationService.requeue_stale_running`)**: Recovers abandoned running jobs if worker crashes or terminates. Jobs exceeding `max_attempts` transition to `failed` with safe error summaries; otherwise safely re-queued.
  - **Terminal Protection & Concurrency**: Atomic conditional updates prevent duplicate execution or invalid state transitions (e.g. attempting to cancel or complete an already terminal job yields HTTP 409).
- **Deterministic Sandbox Simulation (`TracePilotSandboxSimulator`)**:
  - **Local Deterministic Scenarios (`/api/v1/remediations/sandbox/scenarios`, `/api/v1/remediations/sandbox/simulate`)**: Predefined synthetic scenarios validating the complete remediation governance lifecycle without external infrastructure mutations:
    - `SCENARIO-HEALTHY-01`: Low-risk proposal on healthy service evaluated by authorized SRE.
    - `SCENARIO-DEGRADED-02`: Degraded telemetry and stale evidence triggering risk escalation.
    - `SCENARIO-ELEVATED-RISK-03`: High-blast-radius irreversible proposal requiring admin credentials.
    - `SCENARIO-UNAUTHORIZED-REVIEWER-04`: Standard member rejected for high-risk action approval.
    - `SCENARIO-CREATOR-SELF-APPROVAL-05`: Separation of duties enforcement preventing self-approval.
    - `SCENARIO-EXPIRED-PROPOSAL-06`: Expired proposal rejected by lifecycle transition rules.
    - `SCENARIO-CONFLICTING-APPROVAL-07`: Conflicting decisions on terminal proposals rejected.
    - `SCENARIO-INVESTIGATION-RECOVERY-08`: Worker crash recovery with bounded retry backoff.
  - **Strict Non-Execution Boundary**: Every simulation clearly distinguishes observed fixture data, simulated conditions, policy results, expected outcome, and actual outcome. Explicitly verified `execution_performed: false` with zero shell or cloud commands executed.
- **Exportable Audit Reports (`GET /api/v1/remediations/{remediation_id}/export`)**:
  - **Stable JSON Audit Schema (`1.0.0`)**: Exports comprehensive proposal provenance including incident identifiers, proposal version, risk assessment version, policy version (`v1`), chronological approval/rejection decisions with reviewer identities and rationales, append-only audit events, linked root cause hypothesis and citation reference IDs, groundedness scores, and local dry-run validation results.
  - **Tenant Isolation**: Cross-tenant export requests return HTTP 404 with no data leak. Sensitive secrets, tokens, and raw credentials are sanitized from export payloads.
- **Execution Safety Boundary**:
  - Automated remediation execution remains strictly prohibited (`POST /api/v1/remediations/{id}/execute` unconditionally returns HTTP 403 Forbidden).
- **Configuration & Deployment Hardening**:
  - Settings validator ensures production mode (`APP_ENV="production"`) rejects `DEFAULT_LLM_PROVIDER="mock"`, rejects `DEBUG=True`, and rejects default `JWT_SECRET_KEY` and `API_KEY_ENCRYPTION_KEY`.

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
