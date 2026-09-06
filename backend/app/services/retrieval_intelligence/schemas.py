"""Schemas for retrieval intelligence — complexity, expansion, decomposition, adaptive retrieval."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class QueryComplexity(str, Enum):
    SIMPLE = "SIMPLE"
    MODERATE = "MODERATE"
    COMPLEX = "COMPLEX"
    MULTI_HOP = "MULTI_HOP"


class RetrievalStrategyType(str, Enum):
    DIRECT = "DIRECT"
    HYBRID = "HYBRID"
    EXPANDED = "EXPANDED"
    MULTI_QUERY = "MULTI_QUERY"
    DECOMPOSED = "DECOMPOSED"
    NO_RETRIEVAL = "NO_RETRIEVAL"


class QueryAnalysisExtended(BaseModel):
    query: str
    normalized_query: str
    query_length: int
    word_count: int
    complexity: QueryComplexity
    intent: str | None = None
    ambiguity_score: float = 0.0
    contains_multiple_questions: bool = False
    contains_entities: bool = False
    contains_numbers: bool = False
    contains_dates: bool = False
    retrieval_risk: str = "LOW"  # LOW, MEDIUM, HIGH
    recommended_strategy: RetrievalStrategyType = RetrievalStrategyType.DIRECT
    confidence: float = 0.0
    signals: list[str] = Field(default_factory=list)


class DecomposedQuery(BaseModel):
    original_query: str
    sub_queries: list[str]
    reason: str
    provider: str = "rule_based"
    confidence: float = 0.0


class ExpandedQuery(BaseModel):
    original_query: str
    expanded_terms: list[str]
    expanded_query: str
    provider: str = "rule_based"


class RetrievalConfidenceResult(BaseModel):
    confidence: float
    top_score: float | None = None
    score_gap: float | None = None
    result_count: int = 0
    strategy: str
    reason: str


class AdaptiveRetrievalConfig(BaseModel):
    enabled: bool = False
    enable_query_analysis: bool = True
    enable_query_expansion: bool = False
    enable_multi_query: bool = False
    enable_decomposition: bool = False
    enable_adaptive_retrieval: bool = False
    enable_failure_detection: bool = False
    simple_top_k: int = 5
    complex_top_k: int = 8
    simple_candidate_k: int = 20
    complex_candidate_k: int = 50
    max_expanded_queries: int = 3
    max_sub_queries: int = 3
    max_retrieval_attempts: int = 2
    max_total_candidates: int = 100


class RetrievalIntelligenceResult(BaseModel):
    original_query: str
    strategy: RetrievalStrategyType
    query_variants: list[str] = Field(default_factory=list)
    sub_query_count: int = 0
    retrieval_attempts: int = 1
    candidate_count: int = 0
    final_result_count: int = 0
    retrieval_confidence: RetrievalConfidenceResult | None = None
    fallback_used: bool = False
    query_analysis: QueryAnalysisExtended | None = None
    timings: dict[str, float] = Field(default_factory=dict)
