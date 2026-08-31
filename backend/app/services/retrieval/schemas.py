import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchMode(enum.StrEnum):
    """Supported retrieval search modes."""

    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


class RetrievalFilter(BaseModel):
    """Granular metadata filters applied before candidate retrieval."""

    model_config = ConfigDict(extra="forbid")

    knowledge_base_ids: list[str] | None = Field(
        default=None,
        description="Filter retrieval candidates to specific knowledge bases.",
    )
    document_ids: list[str] | None = Field(
        default=None,
        description="Filter retrieval candidates to specific documents.",
    )
    document_version_ids: list[str] | None = Field(
        default=None,
        description="Filter retrieval candidates to specific document version IDs.",
    )


class RetrievalRequest(BaseModel):
    """Schema for search and retrieval queries."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User search query string.",
    )
    knowledge_base_ids: list[str] | None = Field(
        default=None,
        description="Optional list of Knowledge Base IDs to restrict search scope.",
    )
    document_ids: list[str] | None = Field(
        default=None,
        description="Optional list of Document IDs to restrict search scope.",
    )
    top_k: int = Field(
        default=10,
        gt=0,
        le=100,
        description="Maximum number of ranked chunks to return.",
    )
    candidate_k: int = Field(
        default=50,
        gt=0,
        le=500,
        description="Number of candidate chunks to fetch from each retriever before fusion.",
    )
    search_mode: SearchMode = Field(
        default=SearchMode.HYBRID,
        description="Retrieval search strategy ('vector', 'keyword', or 'hybrid').",
    )
    filters: RetrievalFilter | None = Field(
        default=None,
        description="Structured metadata filters for granular candidate scoping.",
    )
    debug: bool = Field(
        default=False,
        description="Whether to include internal diagnostic trace and per-branch scores.",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Query string cannot be empty or whitespace only.")
        return trimmed

    @field_validator("candidate_k")
    @classmethod
    def validate_candidate_k(cls, v: int, info) -> int:
        top_k = info.data.get("top_k", 10)
        if v < top_k:
            raise ValueError(f"candidate_k ({v}) must be greater than or equal to top_k ({top_k}).")
        return v


class ChunkProvenance(BaseModel):
    """Complete provenance and audit trail for a retrieved chunk."""

    model_config = ConfigDict(from_attributes=True)

    organization_id: str
    knowledge_base_id: str
    document_id: str
    document_version_id: str
    chunk_id: str
    chunk_index: int
    page_number: int | None = None
    section_title: str | None = None
    metadata: dict[str, Any] | None = None


class RetrievalResult(BaseModel):
    """A single ranked retrieved chunk item with score breakdown and provenance."""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: str
    document_id: str
    document_version_id: str
    knowledge_base_id: str
    content: str
    score: float = Field(
        description="Final ranking score (e.g. RRF score in hybrid, cosine sim in vector)."
    )
    rank: int = Field(description="1-indexed final ranking position.")
    source: str = Field(description="Origin of candidate match ('vector', 'keyword', or 'hybrid').")
    vector_score: float | None = Field(
        default=None,
        description="Cosine similarity score from vector retriever if matched.",
    )
    keyword_score: float | None = Field(
        default=None,
        description="PostgreSQL FTS rank score from keyword retriever if matched.",
    )
    rrf_score: float | None = Field(
        default=None,
        description="Reciprocal Rank Fusion score if hybrid search was used.",
    )
    page_number: int | None = None
    section_title: str | None = None
    metadata: dict[str, Any] | None = None
    provenance: ChunkProvenance


class RetrievalTrace(BaseModel):
    """Diagnostic trace metadata for retrieval execution."""

    query_hash: str
    search_mode: str
    vector_candidate_count: int = 0
    keyword_candidate_count: int = 0
    fused_candidate_count: int = 0
    final_result_count: int = 0
    query_embedding_duration_ms: float = 0.0
    vector_search_duration_ms: float = 0.0
    keyword_search_duration_ms: float = 0.0
    fusion_duration_ms: float = 0.0
    total_duration_ms: float = 0.0
    partial_failure: bool = False
    partial_failure_reason: str | None = None


class RetrievalResponse(BaseModel):
    """Response envelope for search and retrieval queries."""

    query: str
    search_mode: SearchMode
    total_results: int
    results: list[RetrievalResult]
    trace: RetrievalTrace | None = None
