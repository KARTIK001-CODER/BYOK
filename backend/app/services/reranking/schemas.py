"""Schemas for reranking — preserve provenance, expose rerank scores."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RerankCandidate(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str | None = None
    content: str
    retrieval_score: float | None = None
    retrieval_rank: int | None = None
    source: str | None = None
    metadata: dict[str, Any] | None = None
    # preserve provenance
    provenance: Any | None = None  # ChunkProvenance or placeholder


class RerankResult(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str | None = None
    content: str
    original_rank: int | None = None
    original_score: float | None = None
    rerank_score: float
    rerank_rank: int
    source: str | None = None
    metadata: dict[str, Any] | None = None
    provenance: Any | None = None


class RerankingConfig(BaseModel):
    enabled: bool = False
    provider: str = "local"
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    candidate_k: int = 30
    top_k: int = 5
    max_document_length: int = 512
    timeout_seconds: float = 2.0


class RerankerTrace(BaseModel):
    enabled: bool = False
    provider: str | None = None
    model: str | None = None
    candidate_count: int = 0
    result_count: int = 0
    candidate_preparation_ms: float = 0.0
    initialization_ms: float = 0.0
    inference_ms: float = 0.0
    sorting_ms: float = 0.0
    total_ms: float = 0.0
    fallback: bool = False
    fallback_reason: str | None = None
    is_warm: bool | None = None
    timeout: bool = False
