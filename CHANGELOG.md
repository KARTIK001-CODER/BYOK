# Changelog

All notable changes to the **RAGForge** platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.0] - Phase 3: Knowledge Bases & Document Management - 2026-08-30

### Added
- **Knowledge Bases**:
  - `KnowledgeBase` model scoped strictly to tenant `Organization` with unique URL-safe slugs.
  - CRUD API endpoints (`/api/v1/knowledge-bases`) with pagination, search, and RBAC (`ADMIN` / `OWNER` for management; `MEMBER` for view).
- **Document Management & Storage Abstraction**:
  - `Document` model with explicit tenant isolation column (`organization_id`) and lifecycle state machine: `UPLOADING`, `UPLOADED` (Phase 3 terminal state), `PROCESSING`, `READY`, `FAILED`, `ARCHIVED`.
  - `DocumentVersion` model tracking immutable revision histories, storage keys, and checksums.
  - Abstract `StorageService` protocol with `LocalStorageService` (path traversal protected, async I/O) ready for S3/R2/GCS cloud providers.
  - Deterministic storage key generator: `org/{org_id}/kb/{kb_id}/documents/{doc_id}/v{version}/{filename}`.
- **File Validation & Integrity**:
  - Multi-format validation for PDF, Plain Text, Markdown, and Microsoft Word (DOCX).
  - Magic byte inspection for binary documents (`%PDF` for PDFs, `PK\x03\x04` for DOCX).
  - Cryptographic SHA-256 checksum calculation for integrity validation.
  - Duplicate document detection per Knowledge Base: rejects duplicate content with `409 ConflictException`.
  - Configurable upload limit (`MAX_UPLOAD_SIZE_MB=25`).
- **Document Endpoints**:
  - `POST /api/v1/knowledge-bases/{kb_id}/documents`: Multipart document upload.
  - `GET /api/v1/knowledge-bases/{kb_id}/documents`: Paginated document listing with status filters and sorting allowlists.
  - `GET /api/v1/documents/{document_id}`: Document metadata retrieval.
  - `PATCH /api/v1/documents/{document_id}`: Document rename and status updates (archiving).
  - `DELETE /api/v1/documents/{document_id}`: Soft deletion of document records.
- **Database Migrations**:
  - Alembic migration `0003_knowledge_bases_and_documents.py` creating `knowledge_bases`, `documents`, and `document_versions` tables with cascading foreign keys and indexes.
- **Automated Test Suite**:
  - 47 automated tests covering full Knowledge Base and Document workflows, magic byte validation, duplicate detection, tenant isolation, RBAC, pagination, and sorting.

---

## [0.2.0] - Phase 2: Authentication & Multi-Tenancy - 2026-08-30

### Added
- **User Authentication**:
  - Secure password hashing using Argon2id (`argon2-cffi`).
  - Short-lived JWT access tokens (15-minute expiration) containing minimal claims.
  - Rotating refresh tokens (7-day expiration) stored as SHA-256 hashes in the database.
  - Automatic refresh token reuse detection: replaying a revoked token triggers security alarms and invalidates all active tokens.
  - Case-insensitive email normalization and sanitized user profile endpoints (`GET /api/v1/auth/me`).
  - Idempotent logout endpoint (`POST /api/v1/auth/logout`).
- **Multi-Tenancy & Organizations**:
  - `Organization` tenant boundary model with collision-safe unique slug generation.
  - Automatic default organization provisioning upon user registration.
  - `OrganizationMembership` model with centralized Role-Based Access Control (RBAC): `OWNER`, `ADMIN`, `MEMBER`.
  - Multi-tenant isolation dependency (`require_organization_membership`) and role authorization (`require_role`).
- **BYOK-Ready Database Schema**:
  - `ProviderCredential` model and database table establishing organization-scoped ciphertext storage for future multi-provider AI keys.
- **Database Migrations**:
  - Alembic migration `0002_auth_and_multitenancy.py`.

---

## [0.1.0] - Phase 1: Project Foundation - 2026-08-30

### Added
- Initial async FastAPI application factory with lifespan management and router structure.
- Async SQLAlchemy 2.0 engine, connection pool, and PostgreSQL + pgvector support.
- Initial Alembic migration `0001_enable_pgvector.py`.
- Structured logging with `X-Request-ID` correlation context and sensitive data filtering.
- Centralized exception handling with standardized API error payloads.
- Liveness (`/health`) and Readiness (`/ready`) endpoints.
- Multi-container Docker Compose configuration with healthchecks.
- Pytest test suite and Ruff linting/formatting configuration.
