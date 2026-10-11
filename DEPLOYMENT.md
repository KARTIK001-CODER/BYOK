# TracePilot — Deployment, Operational Runbook & Release Verification Guide

This guide provides reproducible, tested instructions for installing, configuring, running, and maintaining TracePilot in a controlled deployment environment.

---

## 1. System Requirements & Architecture

- **Operating System**: Linux (Ubuntu 22.04+ / Debian 12+), macOS, or Windows (WSL2 / PowerShell).
- **Runtime**:
  - Python 3.11+ (Python 3.13 validated)
  - Node.js 18+ & npm 9+
- **Database**:
  - PostgreSQL 16 with `pgvector` extension (Docker image: `pgvector/pgvector:pg16`).
- **Core Architecture Components**:
  - **FastAPI Backend**: Serves REST APIs, SSE investigation streams, health/readiness probes.
  - **Investigation Worker**: Polls and executes durable investigation jobs, reporting periodic heartbeats.
  - **Vite React Frontend**: Incident-first investigation workspace, timeline inspector, evidence viewer, and remediation governance interface.

---

## 2. Configuration Audit & Environment Variables

Create `.env` in the `backend/` directory based on the following verified inventory:

| Variable Name | Purpose | Status | Default / Recommendation | Secret Sensitivity |
| :--- | :--- | :--- | :--- | :--- |
| `APP_NAME` | Application identifier | Optional | `TracePilot` | Low |
| `APP_ENV` | Runtime environment (`development`, `staging`, `production`) | **Required** | `production` | Low |
| `DEBUG` | Enable debug logs & reloaders | Optional | `false` (must be `false` in prod) | Low |
| `DATABASE_URL` | PostgreSQL connection string | **Required** | `postgresql+asyncpg://user:pass@localhost:5432/tracepilot` | **High** |
| `SECRET_KEY` | HMAC key for signing JWTs and auth cookies | **Required** | Generated 64-char hex string | **Critical** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Lifetime of access tokens | Optional | `30` | Low |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Lifetime of refresh tokens | Optional | `7` | Low |
| `CORS_ORIGINS` | Permitted cross-origin origins | **Required** | `["https://app.tracepilot.internal"]` | Medium |
| `DEFAULT_LLM_PROVIDER` | Primary AI provider (`groq`, `openai`, `gemini`, `mock`) | **Required** | `groq` | Medium |
| `DEFAULT_LLM_MODEL` | Default model identifier | Optional | `qwen/qwen3.8-27b` (Groq) or `gpt-4o` | Low |
| `GROQ_API_KEY` | API credential for Groq provider | Conditional | Required if provider is `groq` | **Critical** |
| `OPENAI_API_KEY` | API credential for OpenAI provider | Conditional | Required if provider is `openai` | **Critical** |
| `GEMINI_API_KEY` | API credential for Gemini provider | Conditional | Required if provider is `gemini` | **Critical** |
| `EMBEDDING_PROVIDER` | Embedding model provider (`fastembed`, `mock`) | Optional | `fastembed` | Low |
| `EMBEDDING_MODEL` | Embedding model identifier | Optional | `BAAI/bge-small-en-v1.5` | Low |
| `GROUNDING_ENABLED` | Groundedness evaluation for hypotheses | Optional | `true` | Low |
| `WORKER_HEARTBEAT_INTERVAL_SECONDS` | Heartbeat frequency for background worker | Optional | `30` | Low |
| `WORKER_STALE_THRESHOLD_SECONDS` | Heartbeat age before worker considered degraded | Optional | `90` | Low |

> [!WARNING]
> In production environments (`APP_ENV=production`), `SECRET_KEY` must never use default placeholders. `DEBUG` must be set to `false`. Fail-fast validation in `app/core/config.py` enforces these constraints at startup.

---

## 3. Database Initialization & Alembic Migrations

### 3.1 Start PostgreSQL with pgvector
```bash
docker run -d \
  --name tracepilot-pgvector \
  -e POSTGRES_USER=tracepilot \
  -e POSTGRES_PASSWORD=secure_password \
  -e POSTGRES_DB=tracepilot \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

### 3.2 Enable Extensions
Connect to the database and verify `vector` is available:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 3.3 Apply Alembic Migrations
Migrations follow a strictly linear revision chain (`0001` to `0016`):
```bash
cd backend
alembic upgrade head
```
Verify the current head revision:
```bash
alembic heads
# Expected: 0016_worker_heartbeats (head)
```

---

## 4. Backend Service Startup

### 4.1 Dependency Installation
```bash
cd backend
python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 4.2 Start API Server
Run Uvicorn in production mode (bound to internal interface or container port):
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 5. Background Investigation Worker Startup

The background worker continuously claims queued investigation jobs, executes evidence correlation, scores groundedness, and records heartbeats in the `worker_heartbeats` table:

```bash
cd backend
python -m scripts.run_investigation_worker --loop --interval 2
```
Options:
- `--loop`: Run indefinitely polling for queued investigation jobs.
- `--interval <int>`: Poll loop interval in seconds (integer, default: `2`).
- `--organization-id <uuid>`: (Optional) Scopes worker to a specific organization. Omit for multi-tenant worker mode.

---

## 6. Frontend Production Build & Deployment

### 6.1 Install Dependencies
```bash
cd frontend
npm ci
```

### 6.2 Build Production Bundle
```bash
npm run build
```
The output bundle will be generated in `frontend/dist/`.

### 6.3 Serve Production Frontend
Serve static assets through Nginx, Caddy, or Cloudflare Pages with API proxying:
```nginx
server {
    listen 80;
    server_name app.tracepilot.internal;
    root /var/www/tracepilot/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Enable SSE streaming buffering passthrough
    location /api/v1/investigations/ {
        proxy_pass http://localhost:8000;
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
    }
}
```

---

## 7. Operational Health, Readiness & Monitoring Probes

### Kubernetes Probe Configurations

- **Liveness Probe**:
  ```yaml
  livenessProbe:
    httpGet:
      path: /health/live
      port: 8000
    initialDelaySeconds: 5
    periodSeconds: 10
  ```
- **Readiness Probe**:
  ```yaml
  readinessProbe:
    httpGet:
      path: /health/ready
      port: 8000
    initialDelaySeconds: 10
    periodSeconds: 15
  ```

### Health Endpoints Reference

- `GET /health` or `/health/live`: Lightweight process liveness check (`HTTP 200 {"status": "ok"}`).
- `GET /ready` or `/health/ready`: Complete dependency readiness checking:
  - Database connectivity & response latency.
  - pgvector extension availability.
  - Worker heartbeat status and active/stale job metrics.
- `GET /api/v1/health/worker`: Worker status (`idle`, `active`, `stale`, or `unknown`).
- `GET /api/v1/info`: Metadata and capability declarations. Confirms `remediation_execution_enabled: false`.

---

## 8. Backup and Restore Procedures

### 8.1 Database Backup
Create a consistent, point-in-time PostgreSQL dump:
```bash
pg_dump -h localhost -U tracepilot -d tracepilot -Fc -f tracepilot_backup_$(date +%Y%m%d_%H%M%S).dump
```

### 8.2 Database Restore
Restore to a clean database instance:
```bash
# 1. Create target database
createdb -h localhost -U tracepilot tracepilot_restore

# 2. Ensure vector extension exists
psql -h localhost -U tracepilot -d tracepilot_restore -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 3. Restore dump
pg_restore -h localhost -U tracepilot -d tracepilot_restore -v tracepilot_backup_YYYYMMDD_HHMMSS.dump

# 4. Verify Alembic schema head
cd backend
alembic upgrade head
```

---

## 9. Operational Safety Boundary

> [!CAUTION]
> **Automated remediation execution is strictly prohibited and disabled.**
> Any attempt to POST to `/api/v1/remediations/{remediation_id}/execute` returns an absolute `HTTP 403 Forbidden` response.
> Remediation proposals are advisory specifications intended for human-in-the-loop review, sign-off, and manual execution.

---

## 10. Smoke Test Checklist

Following startup, run these commands to verify operational health:

1. **Verify Liveness**: `curl -f http://localhost:8000/health`
2. **Verify Readiness**: `curl -f http://localhost:8000/ready`
3. **Verify Worker Heartbeat**: `curl -f http://localhost:8000/api/v1/health/worker`
4. **Execute Stage E Regression Suite**:
   ```bash
   cd backend
   pytest tests/test_stage_e_e2e_workflow_and_hardening.py -v
   ```
