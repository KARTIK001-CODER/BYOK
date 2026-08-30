# Changelog

All notable changes to the **RAGForge** platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] - Phase 2: Authentication & Multi-Tenancy - 2026-08-30

### Added
- **User Authentication**:
  - Secure password hashing using Argon2id (`argon2-cffi`).
  - Short-lived JWT access tokens (15-minute expiration) containing minimal claims (`sub`, `type`, `jti`, `iat`, `exp`).
  - Rotating refresh tokens (7-day expiration) stored as SHA-256 hashes in the database.
  - Automatic refresh token reuse detection: replaying a revoked refresh token triggers security alarms and invalidates all active tokens for that user account.
  - Generic authentication error messages to prevent user enumeration.
  - Case-insensitive email normalization.
  - Public profile endpoint (`GET /api/v1/auth/me`).
  - Idempotent logout endpoint (`POST /api/v1/auth/logout`) revoking stored refresh tokens.
- **Multi-Tenancy & Organizations**:
  - `Organization` tenant boundary model with collision-safe unique slug generation.
  - Automatic default organization provisioning upon user registration (e.g. `User's Workspace`).
  - `OrganizationMembership` model with centralized Role-Based Access Control (RBAC): `OWNER`, `ADMIN`, `MEMBER`.
  - Multi-tenant isolation dependency (`require_organization_membership`) and role authorization (`require_role`).
  - Regression tests proving strict tenant isolation (cross-tenant access denied).
- **BYOK-Ready Database Schema**:
  - `ProviderCredential` model and database table establishing organization-scoped ciphertext storage for future multi-provider AI keys (Groq, OpenAI, Gemini, etc.).
  - Database schema preparation strictly separate from JWT secrets.
- **Database Migrations**:
  - Alembic migration `0002_auth_and_multitenancy.py` creating `users`, `organizations`, `organization_memberships`, `refresh_tokens`, and `provider_credentials` with cascading foreign keys, indexes, and unique constraints.
- **Automated Test Suite**:
  - 25+ automated tests covering Argon2id hashing, user registration, login, token rotation, reuse detection, logout, RBAC role hierarchy, tenant isolation, and sensitive data leakage regression.

---

## [0.1.0] - Phase 1: Project Foundation - 2026-08-30

### Added
- Initial async FastAPI application factory with lifespan management and router structure.
- Async SQLAlchemy 2.0 engine, connection pool, and PostgreSQL + pgvector support.
- Initial Alembic migration enabling `vector` and `uuid-ossp` extensions.
- Structured logging with `X-Request-ID` correlation context and sensitive data filtering.
- Centralized exception handling with standardized API error payloads.
- Liveness (`/health`) and Readiness (`/ready`) endpoints.
- Multi-container Docker Compose configuration with healthchecks.
- Pytest test suite and Ruff linting/formatting configuration.
- Project documentation (`README.md`, `ARCHITECTURE.md`, `DEVELOPMENT.md`).
