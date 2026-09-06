"""Strongly typed Pydantic schemas for evaluation domain — supports graded relevance future."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class EvaluationCategory(str, Enum):
    semantic = "semantic"
    keyword = "keyword"
    factual = "factual"
    multi_hop = "multi_hop"
    ambiguous = "ambiguous"


class EvaluationDifficulty(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class RelevanceGrade(int, Enum):
    """Graded relevance (future). Current binary: 0=irrelevant, 1=relevant. Supports 0-3."""

    irrelevant = 0
    partially_relevant = 1
    relevant = 2
    highly_relevant = 3


class ExpectedResult(BaseModel):
    """Stable identifier for relevance — uses document_name/slug, not volatile DB IDs."""

    document_name: str | None = Field(default=None, description="Stable document name/slug")
    document_slug: str | None = Field(default=None)
    chunk_content_snippet: str | None = Field(default=None, description="Unique content snippet for chunk-level match")
    relevance_grade: int = Field(default=1, ge=0, le=3, description="Graded relevance, default 1 = relevant")

    model_config = {"extra": "forbid"}


class EvaluationCase(BaseModel):
    """Single evaluation case — deterministic, versioned."""

    id: str = Field(..., description="Stable case ID e.g. eval_001")
    query: str = Field(..., min_length=3)
    category: EvaluationCategory = Field(...)
    difficulty: EvaluationDifficulty = Field(default=EvaluationDifficulty.medium)
    expected: list[ExpectedResult] = Field(..., min_length=1, description="At least one relevant expectation")
    notes: str | None = Field(default=None)
    tags: list[str] | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        t = v.strip()
        if len(t) < 3:
            raise ValueError("Query must be >=3 chars")
        return t

    model_config = {"extra": "forbid"}


class EvaluationDatasetMetadata(BaseModel):
    version: str = Field(default="1.0")
    created_at: str | None = None
    description: str | None = None
    total_cases: int | None = None

    model_config = {"extra": "allow"}


class EvaluationDataset(BaseModel):
    """Root dataset model — versioned, reproducible."""

    version: str = Field(default="1.0")
    description: str | None = None
    created_at: str | None = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cases: list[EvaluationCase] = Field(..., min_length=1)
    metadata: dict[str, Any] | None = None

    @field_validator("cases")
    @classmethod
    def validate_unique_ids(cls, v: list[EvaluationCase]) -> list[EvaluationCase]:
        ids = [c.id for c in v]
        if len(ids) != len(set(ids)):
            dup = [x for x in ids if ids.count(x) > 1]
            raise ValueError(f"Duplicate evaluation IDs: {set(dup)}")
        return v

    model_config = {"extra": "forbid"}


# --- Runtime results ---

class RetrievedResult(BaseModel):
    rank: int
    chunk_id: str
    document_id: str
    document_name: str | None = None
    score: float | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rrf_score: float | None = None
    is_relevant: bool = False
    relevance_grade: int = 0


class CaseResult(BaseModel):
    case_id: str
    query: str
    category: EvaluationCategory
    difficulty: EvaluationDifficulty
    expected: list[ExpectedResult]
    retrieved: list[RetrievedResult]
    top_k: int
    hit_at_k: dict[str, bool] = Field(default_factory=dict)  # e.g. {"1": true, "3": true}
    mrr: float = 0.0
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    first_relevant_rank: int | None = None
    status: str = Field(default="miss", description="hit | miss | partial")
    duration_ms: float = 0.0


class MetricResult(BaseModel):
    hit_at_1: float = 0.0
    hit_at_3: float = 0.0
    hit_at_5: float = 0.0
    hit_at_10: float | None = None
    mrr: float = 0.0
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    total_cases: int = 0
    top_k: int = 5


class CategoryMetrics(BaseModel):
    category: EvaluationCategory
    metrics: MetricResult


class EvaluationConfigSnapshot(BaseModel):
    evaluation_version: str = "1.0"
    dataset_version: str = "1.0"
    retriever_type: str = Field(..., description="vector | keyword | hybrid | hybrid_reranked ...")
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    top_k: int = 5
    candidate_k: int = 50
    fusion_method: str = "rrf"
    rrf_k: int = 60
    extra: dict[str, Any] | None = None


class EvaluationReport(BaseModel):
    evaluation_id: str
    timestamp: str
    dataset_version: str
    dataset_path: str
    retriever: str
    top_k: int
    config: EvaluationConfigSnapshot
    overall: MetricResult
    by_category: dict[str, MetricResult] = Field(default_factory=dict)
    by_difficulty: dict[str, MetricResult] | None = None
    cases: list[CaseResult] = Field(default_factory=list)
    failures: list[CaseResult] = Field(default_factory=list)
    worst_queries: list[CaseResult] = Field(default_factory=list)
    git_commit: str | None = None


class BaselineRecord(BaseModel):
    baseline_id: str
    created_at: str
    dataset_version: str
    retriever: str
    top_k: int
    config: EvaluationConfigSnapshot
    overall: MetricResult
    by_category: dict[str, MetricResult] = Field(default_factory=dict)
    git_commit: str | None = None


class RegressionThresholds(BaseModel):
    mrr_max_regression: float = 0.02  # 2%
    hit_at_5_max_regression: float = 0.02
    hit_at_1_max_regression: float = 0.05


class RegressionResult(BaseModel):
    baseline_id: str
    current_id: str
    metric: str
    baseline_value: float
    current_value: float
    delta: float
    delta_pct: float
    status: str = Field(..., description="PASS | WARNING | FAIL")
    threshold: float
