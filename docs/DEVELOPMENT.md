# RAGForge Development Guide

This guide details the local setup, tooling, testing, and migration workflows for RAGForge.

---

## 1. Prerequisites

- **Python**: Version 3.12 or 3.13
- **Docker & Docker Compose**: For local PostgreSQL + pgvector container
- **Git**: For version control

---

## 2. Local Environment Setup

### Option A: Running with Docker Compose (Recommended for Full Stack)

1. Clone repository and copy environment configuration:
   ```bash
   cp .env.example .env
   ```

2. Build and launch containers:
   ```bash
   docker compose up --build
   ```

3. The backend API will be available at `http://localhost:8000`.
   - OpenAPI Docs: `http://localhost:8000/docs`
   - Liveness Check: `http://localhost:8000/health`
   - Readiness Check: `http://localhost:8000/ready`

---

### Option B: Local Python Virtual Environment

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Create and activate a virtual environment:
   ```bash
   # On macOS/Linux:
   python3 -m venv .venv
   source .venv/bin/activate

   # On Windows (PowerShell):
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

3. Install project dependencies and development tools:
   ```bash
   pip install --upgrade pip
   pip install -e ".[dev]"
   ```

4. Start the local PostgreSQL + pgvector database:
   ```bash
   # From root directory:
   docker compose up -d postgres
   ```

5. Run database migrations:
   ```bash
   alembic upgrade head
   ```

6. Start the development server with auto-reload:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

---

## 3. Database Migrations (Alembic)

Alembic is configured for asynchronous PostgreSQL migrations.

- **Apply all migrations:**
  ```bash
  alembic upgrade head
  ```

- **Roll back the last migration:**
  ```bash
  alembic downgrade -1
  ```

- **Generate a new migration:**
  ```bash
  alembic revision --autogenerate -m "describe_changes"
  ```

---

## 4. Testing

Run the test suite with pytest:

```bash
# Run all tests
pytest -v

# Run with coverage report
pytest --cov=app tests/

# Run a specific test file
pytest -v tests/test_health.py
```

---

## 5. Code Quality & Formatting

Ruff is used for both linting and formatting.

- **Check lint rules:**
  ```bash
  ruff check .
  ```

- **Apply automatic lint fixes:**
  ```bash
  ruff check --fix .
  ```

- **Check code formatting:**
  ```bash
  ruff format --check .
  ```

- **Format codebase:**
  ```bash
  ruff format .
  ```

---

## 6. Makefile Shortcuts

A `Makefile` is available at the project root with standard targets:

| Command | Description |
|---|---|
| `make up` | Start all Docker Compose services in background |
| `make down` | Stop all Docker Compose services |
| `make test` | Run pytest suite |
| `make lint` | Run ruff lint check |
| `make format` | Run ruff code formatter |
| `make migrate`| Run Alembic database migrations |
| `make dev` | Run local Uvicorn development server |
