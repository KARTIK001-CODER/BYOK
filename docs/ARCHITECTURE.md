# RAGForge Architecture Documentation

RAGForge is a production-grade, modular Retrieval-Augmented Generation (RAG) platform designed for reliability, scalability, multi-tenancy, and strict security compliance.

---

## Phase 3 Implemented Architecture: Knowledge Bases & Document Management

```text
                    Organization
                         │
             ┌───────────┴───────────┐
             │                       │
             ▼                       ▼
      Knowledge Base A       Knowledge Base B
             │                       │
             ▼                       ▼
        Documents               Documents
             │
             ▼
       Object Storage
             │
             ▼
     (Future Ingestion)
             │
       ┌─────┴─────┐
       ▼           ▼
     Chunks     Embeddings
                    │
                    ▼
                pgvector
```

---

## Data Model & Tenancy Scoping

```
┌──────────────────────────┐         ┌──────────────────────────┐
│          users           │         │      organizations       │
├──────────────────────────┤         ├──────────────────────────┤
│ id (PK, UUID)            │◄──┐ ┌──►│ id (PK, UUID)            │
│ email (UNIQUE, INDEX)    │   │ │   │ name                     │
│ password_hash            │   │ │   │ slug (UNIQUE, INDEX)     │
└────────────┬─────────────┘   │ │   └─────────────┬────────────┘
             │                 │ │                 │
             │                 │ │                 │ 1:N (CASCADE)
             │                 │ │                 ▼
             │                 │ │   ┌──────────────────────────┐
             │                 │ │   │     knowledge_bases      │
             │                 │ │   ├──────────────────────────┤
             │                 │ │   │ id (PK, UUID)            │
             │                 │ │   │ organization_id (FK)     │
             │                 │ │   │ name                     │
             │                 │ │   │ slug (INDEX)             │
             │                 │ │   │ description              │
             │                 │ │   │ is_active                │
             │                 │ │   │ created_by (FK -> users) │
             │                 │ │   │ UQ(org_id, slug)         │
             │                 │ │   └─────────────┬────────────┘
             │                 │ │                 │
             │                 │ │                 │ 1:N (CASCADE)
             │                 │ │                 ▼
             │                 │ │   ┌──────────────────────────┐
             │                 │ └───┤        documents         │
             │                 │     ├──────────────────────────┤
             │                 │     │ id (PK, UUID)            │
             │                 │     │ knowledge_base_id (FK)   │
             │                 └────►│ organization_id (FK)     │
             │                       │ uploaded_by (FK -> users)│
             │                       │ name                     │
             │                       │ original_filename        │
             │                       │ content_type, file_size  │
             │                       │ storage_key              │
             │                       │ checksum (SHA-256, INDEX)│
             │                       │ status (UPLOADED, etc.)  │
             │                       │ current_version (INT)    │
             │                       │ deleted_at (TIMESTAMP)   │
             │                       └─────────────┬────────────┘
             │                                     │
             │                                     │ 1:N (CASCADE)
             │                                     ▼
             │                       ┌──────────────────────────┐
             │                       │    document_versions     │
             │                       ├──────────────────────────┤
             │                       │ id (PK, UUID)            │
             │                       │ document_id (FK)         │
             │                       │ version_number (INT)     │
             │                       │ storage_key              │
             │                       │ checksum (SHA-256)       │
             │                       │ file_size, content_type  │
             │                       │ uploaded_by (FK -> users)│
             │                       │ UQ(doc_id, version_num)  │
             └──────────────────────►└──────────────────────────┘
```

---

## Storage & Database Boundary

1. **PostgreSQL / Neon PostgreSQL**:
   - Stores metadata, structured records, foreign keys, timestamps, cryptographic SHA-256 checksums, and storage references (`storage_key`).
   - Never stores raw binary file contents.
2. **Object Storage (`StorageService`)**:
   - Stores binary file contents under deterministic, structured keys:
     `org/{org_id}/kb/{kb_id}/documents/{document_id}/v{version_number}/{sanitized_filename}`
   - Abstract protocol currently implemented as `LocalStorageService` for local dev/testing, with path traversal prevention.
   - Future cloud drivers (AWS S3, Cloudflare R2, Google Cloud Storage) implement the same interface without altering domain business logic.

---

## Document Lifecycle State Machine

```text
Upload ➔ Validate ➔ Checksum ➔ Stored
                                  ↓
                              UPLOADED ◄── (Phase 3 Terminal State)
                                  ↓
                        (Phase 4: Ingestion)
                                  ↓
                              PROCESSING
                                ┌──┴──┐
                                ▼     ▼
                              READY  FAILED
                                │
                                ▼
                             ARCHIVED
```

---

## Security Decisions

1. **Strict Multi-Tenant Scoping**: All Knowledge Bases and Documents are bound to `organization_id`. Route dependencies reject cross-tenant access (`403 Forbidden` / `404 Not Found`).
2. **Magic Bytes Inspection**: Files are validated not only by extension and headers, but by inspectable binary headers (`%PDF` for PDF, `PK\x03\x04` for DOCX).
3. **Cryptographic Checksumming**: SHA-256 digest is generated for each uploaded document. Duplicates in the same Knowledge Base are detected and rejected (`409 Conflict`).
4. **Path Traversal Protection**: User-supplied filenames are sanitized (`sanitize_filename`), removing `..`, `/`, and dangerous characters before generating storage keys.
5. **Configurable Limits**: Upload file size is strictly capped by `MAX_UPLOAD_SIZE_MB` (default: 25MB).
