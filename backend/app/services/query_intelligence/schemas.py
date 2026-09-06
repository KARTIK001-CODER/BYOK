"""Pydantic schemas for Query Intelligence pipeline — inspectable, versioned."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    definition = "definition"
    procedure = "procedure"
    factual = "factual"
    comparison = "comparison"
    policy = "policy"
    troubleshooting = "troubleshooting"
    unknown = "unknown"


class QueryCategory(str, Enum):
    semantic = "semantic"
    keyword = "keyword"
    factual = "factual"
    multi_hop = "multi_hop"
    ambiguous = "ambiguous"
    unknown = "unknown"


class RetrievalStrategy(str, Enum):
    VECTOR = "VECTOR"
    KEYWORD = "KEYWORD"
    HYBRID = "HYBRID"
    HYBRID_WIDE = "HYBRID_WIDE"


class QueryFeatures(BaseModel):
    original_query: str
    normalized_query: str
    character_count: int
    token_count: int
    word_count: int
    contains_quotes: bool = False
    contains_backticks: bool = False
    contains_numbers: bool = False
    contains_identifier: bool = False
    identifier_candidates: list[str] = Field(default_factory=list)
    contains_exact_phrase: bool = False
    contains_special_terms: bool = False
    contains_question_word: bool = False
    question_type: QuestionType = QuestionType.unknown
    punctuation_count: int = 0
    capitalized_terms: list[str] = Field(default_factory=list)
    uppercase_terms: list[str] = Field(default_factory=list)
    rare_term_candidates: list[str] = Field(default_factory=list)
    # signals for downstream
    has_snake_case: bool = False
    has_camel_case: bool = False
    has_upper_case: bool = False
    has_version_pattern: bool = False
    word_count_raw: int = 0

    model_config = {"extra": "forbid"}


class QueryClassification(BaseModel):
    primary_class: QueryCategory = QueryCategory.unknown
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    signals: list[str] = Field(default_factory=list)
    all_scores: dict[str, float] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class AmbiguityAnalysis(BaseModel):
    is_ambiguous: bool = False
    ambiguity_score: float = Field(ge=0.0, le=1.0, default=0.0)
    signals: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class RetrievalStrategyDecision(BaseModel):
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID
    reason: str = "fallback_hybrid"
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    signals: list[str] = Field(default_factory=list)
    # explainability
    classification: QueryCategory | None = None
    ambiguity_score: float | None = None

    model_config = {"extra": "forbid"}


class QueryAnalysis(BaseModel):
    """Root — every query analyzed before retrieval."""

    features: QueryFeatures
    classification: QueryClassification
    ambiguity: AmbiguityAnalysis
    strategy: RetrievalStrategyDecision
    # optional context
    duration_ms: float = 0.0
    version: str = "1.0"

    model_config = {"extra": "forbid"}
