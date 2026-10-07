"""Deterministic evidence text representation and safe embedding generation for TracePilot.

Evidence texts are sanitized to ensure secrets, tokens, credentials, and noisy
payloads are never embedded into vector space. All generation paths are non-blocking
and fail-safe: embedding errors never abort evidence ingestion or investigation jobs.
"""

import asyncio
import logging
from typing import Any

from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.providers import get_embedding_provider

logger = logging.getLogger("app.services.investigations.evidence_embedding")

_SENSITIVE_KEY_MARKERS = {
    "token",
    "secret",
    "password",
    "passwd",
    "key",
    "authorization",
    "auth",
    "credential",
    "cookie",
    "cert",
    "private",
    "session",
    "jwt",
    "api_key",
    "bearer",
}

_MAX_EMBEDDING_TEXT_LENGTH = 1000
_MAX_PAYLOAD_VALUE_LENGTH = 120
_SERVICE_KEYS = ("service", "service_name", "app", "application", "component")


def is_sensitive_key(key: str) -> bool:
    """Check whether a dictionary key might hold confidential/sensitive data."""
    lowered = key.lower().replace("-", "_")
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def sanitize_payload(payload: dict[str, Any] | None) -> dict[str, str]:
    """Extract and sanitize safe, deterministic scalar fields from normalized_payload."""
    if not payload or not isinstance(payload, dict):
        return {}

    sanitized: dict[str, str] = {}
    for key in sorted(payload.keys()):
        if not isinstance(key, str) or is_sensitive_key(key):
            continue
        val = payload[key]
        if val is None:
            continue
        # Only embed scalar / flat values (int, float, bool, short str)
        if isinstance(val, (bool, int, float)):
            sanitized[key] = str(val)
        elif isinstance(val, str):
            clean_val = val.strip()
            if clean_val and not any(marker in clean_val.lower() for marker in ("bearer ", "eyj")):
                sanitized[key] = clean_val[:_MAX_PAYLOAD_VALUE_LENGTH]
    return sanitized


def build_evidence_embedding_text(
    source_type: str,
    event_type: str,
    summary: str,
    normalized_payload: dict[str, Any] | None = None,
    source_reference: str | None = None,
) -> str:
    """Create a deterministic, secret-safe text representation for vector embedding."""
    lines: list[str] = [
        f"source_type: {source_type.strip()}",
        f"event_type: {event_type.strip()}",
    ]

    safe_payload = sanitize_payload(normalized_payload)
    # Check for service/app name
    service_name: str | None = None
    for sk in _SERVICE_KEYS:
        if sk in safe_payload:
            service_name = safe_payload.pop(sk)
            break
    if service_name:
        lines.append(f"service: {service_name}")

    clean_summary = summary.strip()
    if clean_summary:
        lines.append(f"summary: {clean_summary}")

    if safe_payload:
        payload_parts = [f"{k}={v}" for k, v in sorted(safe_payload.items())]
        lines.append(f"payload: {', '.join(payload_parts)}")

    if source_reference and not is_sensitive_key(source_reference):
        clean_ref = source_reference.strip()
        if clean_ref:
            lines.append(f"reference: {clean_ref[:_MAX_PAYLOAD_VALUE_LENGTH]}")

    full_text = "\n".join(lines)
    return full_text[:_MAX_EMBEDDING_TEXT_LENGTH]


async def generate_evidence_embedding(
    text: str,
    provider: BaseEmbeddingProvider | None = None,
) -> list[float] | None:
    """Generate embedding vector for evidence text safely.

    Never raises: returns None on any provider failure, timeout, or dimension mismatch.
    """
    if not text or not text.strip():
        return None

    try:
        embed_provider = provider or get_embedding_provider()
        vectors = await asyncio.to_thread(embed_provider.embed_documents, [text])
        if vectors and len(vectors) == 1:
            vec = vectors[0]
            if len(vec) == embed_provider.dimension:
                return vec
            logger.warning(
                "Embedding dimension mismatch: got %d, expected %d",
                len(vec),
                embed_provider.dimension,
            )
            return None
        return None
    except Exception as exc:
        logger.warning(
            "Evidence embedding generation failed (safe fallback to None): %s",
            type(exc).__name__,
        )
        return None


async def generate_query_embedding(
    query: str,
    provider: BaseEmbeddingProvider | None = None,
) -> list[float] | None:
    """Generate query embedding vector safely.

    Never raises: returns None on any failure so hybrid retrieval falls back to lexical+recency.
    """
    clean_query = query.strip() if query else ""
    if not clean_query:
        return None

    try:
        embed_provider = provider or get_embedding_provider()
        vec = await asyncio.to_thread(embed_provider.embed_query, clean_query)
        if vec and len(vec) == embed_provider.dimension:
            return vec
        logger.warning(
            "Query embedding dimension mismatch: got %d, expected %d",
            len(vec) if vec else 0,
            embed_provider.dimension,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Query embedding generation failed (safe fallback to None): %s",
            type(exc).__name__,
        )
        return None
