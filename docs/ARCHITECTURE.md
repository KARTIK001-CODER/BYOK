# RAGForge Architecture Documentation

RAGForge is a production-grade, modular Retrieval-Augmented Generation (RAG) platform designed for reliability, scalability, multi-tenancy, and strict security compliance.

---

## Phase 2 Implemented Architecture: Authentication & Multi-Tenancy

Phase 2 establishes the secure identity, multi-tenant isolation, and authorization foundation for RAGForge.

```
Client (HTTP / REST)
       │
       ▼ [Authorization: Bearer <JWT>] [X-Request-ID Header]
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
│                 Authentication & RBAC Layer               │
│                                                           │
│  ├── get_current_user (JWT Validation: sub, exp, type)    │
│  ├── require_organization_membership (Tenant Isolation)   │
│  └── require_role (RBAC: OWNER > ADMIN > MEMBER)          │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────┐
│                      API Layer (/api/v1)                  │
│                                                           │
│  ├── /auth/register   (User + Default Workspace creation)│
│  ├── /auth/login      (Argon2id verification + Tokens)   │
│  ├── /auth/refresh    (Rotating Refresh Token + Reuse Det)│
│  ├── /auth/logout     (Idempotent Token Revocation)       │
│  ├── /auth/me         (Safe profile info)                 │
│  ├── /organizations   (List & Create Tenant Workspaces)   │
│  └── /health, /ready  (Infrastructure probes)             │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────┐
│                      Service Layer                        │
│                                                           │
│  ├── AuthService        (Registration, Login, Tokens)     │
│  ├── UserService        (User lookup, email normalization)│
│  ├── OrganizationService(Slug generation, memberships)    │
│  ├── TokenService       (Rotation, SHA-256 hash, reuse)   │
│  └── PasswordService    (Argon2id hashing & verification) │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────┐
│                      Database Layer                       │
│                                                           │
│  ├── users (UUID PK, normalized email, password_hash)     │
│  ├── organizations (UUID PK, unique slug, tenant root)    │
│  ├── organization_memberships (User <-> Org, RBAC role)   │
│  ├── refresh_tokens (SHA-256 hash, rotation linkage)      │
│  └── provider_credentials (BYOK DB ciphertext preparation)│
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────┐
│                   PostgreSQL 16 + pgvector                │
└───────────────────────────────────────────────────────────┘
```

---

## Multi-Tenancy & Tenant Isolation

Multi-tenancy in RAGForge is structured around the `Organization` entity:

```text
User
 │
 ├── Organization A (Role: OWNER)
 │      ├── Knowledge Bases (Future)
 │      ├── Documents (Future)
 │      └── Provider Credentials (BYOK DB Ready)
 │
 └── Organization B (Role: MEMBER)
        ├── Knowledge Bases (Future)
        ├── Documents (Future)
        └── Provider Credentials (BYOK DB Ready)
```

### Invariants:
1. **Server-Side Verification**: Route handlers never rely on client-supplied organization identifiers without executing `require_organization_membership`.
2. **Access Rejection**: If a user attempts to read or modify resources in an organization they do not belong to, the request is immediately rejected (`403 Forbidden` / `404 Not Found`).
3. **Cascading Deletions**: Deleting an organization cascades to all memberships, knowledge bases, documents, and credentials associated with that organization.

---

## Authentication & Token Lifecycle

### 1. Registration Flow
1. User provides `email`, `password`, `full_name`.
2. Email is normalized to lowercase and checked for uniqueness.
3. Password is validated for minimum strength and hashed using Argon2id.
4. An `Organization` is created with a unique slug (e.g. `user-workspace`).
5. An `OrganizationMembership` is created with `Role.OWNER`.
6. Access token (15m) and rotating refresh token (7d) are issued.
7. Atomic commit; on failure, transaction is rolled back completely.

### 2. Refresh Token Rotation & Reuse Detection
- Raw refresh tokens are 64-character cryptographically secure random strings.
- Only the SHA-256 digest (`token_hash`) is stored in the database.
- Upon refresh:
  - If valid: Old token is revoked (`revoked_at = now()`), new token is issued, and `old_token.replaced_by_token_id = new_token.id`.
  - If a revoked token is presented again (indicating token compromise or replay): The server logs `[SECURITY_EVENT] Refresh token reuse detected` and revokes all active refresh tokens for the user.

---

## Bring Your Own Key (BYOK) Database Foundation

The `provider_credentials` table prepares the database for future multi-provider AI credentials (Groq, OpenAI, Gemini, Cohere):
- Scoped strictly per `organization_id`.
- Stores `encrypted_api_key` (reserved for future AES-256-GCM ciphertext).
- Encryption key will use `API_KEY_ENCRYPTION_KEY`, completely separated from `JWT_SECRET_KEY`.
- *Note: Actual key submission, encryption/decryption, and model provider SDKs are intentionally deferred to future phases.*
