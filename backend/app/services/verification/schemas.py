"""Schemas for groundedness verification — claim, evidence, verification, groundedness, citation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    FACTUAL = "FACTUAL"
    NUMERICAL = "NUMERICAL"
    TEMPORAL = "TEMPORAL"
    POLICY = "POLICY"
    RELATIONAL = "RELATIONAL"
    NON_VERIFIABLE = "NON_VERIFIABLE"


class VerificationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNCERTAIN = "UNCERTAIN"
    NON_VERIFIABLE = "NON_VERIFIABLE"


class CitationStatus(str, Enum):
    VALID = "VALID"
    WEAK = "WEAK"
    INVALID = "INVALID"
    MISSING = "MISSING"


class AnswerStatus(str, Enum):
    HIGHLY_GROUNDED = "HIGHLY_GROUNDED"
    MOSTLY_GROUNDED = "MOSTLY_GROUNDED"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    LOW_GROUNDEDNESS = "LOW_GROUNDEDNESS"
    CONTRADICTED = "CONTRADICTED"
    UNCERTAIN = "UNCERTAIN"


class HallucinationRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Claim(BaseModel):
    claim_id: str
    text: str
    claim_type: ClaimType = ClaimType.FACTUAL
    answer_start: int | None = None
    answer_end: int | None = None
    importance: int = Field(default=1, ge=1, le=3)
    metadata: dict[str, Any] | None = None


class Evidence(BaseModel):
    evidence_id: str
    chunk_id: str
    document_id: str
    document_name: str | None = None
    content: str
    retrieval_rank: int | None = None
    rerank_rank: int | None = None
    citation_metadata: dict[str, Any] | None = None


class ClaimVerificationResult(BaseModel):
    claim: Claim
    status: VerificationStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    provider: str = Field(description="heuristic | llm | mock")
    verification_latency_ms: float = 0.0
    fallback_used: bool = False


class GroundednessResult(BaseModel):
    total_claims: int = 0
    supported_claims: int = 0
    partially_supported_claims: int = 0
    unsupported_claims: int = 0
    contradicted_claims: int = 0
    uncertain_claims: int = 0
    non_verifiable_claims: int = 0
    groundedness_score: float = Field(ge=0.0, le=1.0, default=0.0)
    hallucination_risk: HallucinationRisk = HallucinationRisk.LOW
    answer_status: AnswerStatus = AnswerStatus.HIGHLY_GROUNDED
    unsupported_rate: float = 0.0
    contradiction_rate: float = 0.0
    claim_results: list[ClaimVerificationResult] = Field(default_factory=list)


class CitationValidationResult(BaseModel):
    citation_id: int
    claim_id: str | None = None
    status: CitationStatus
    reason: str | None = None


class VerificationTrace(BaseModel):
    claim_extraction_ms: float = 0.0
    claim_count: int = 0
    verifiable_claim_count: int = 0
    evidence_selection_ms: float = 0.0
    heuristic_verification_ms: float = 0.0
    llm_verification_ms: float = 0.0
    verification_total_ms: float = 0.0
    groundedness_score: float = 0.0
    supported_claims: int = 0
    partially_supported_claims: int = 0
    unsupported_claims: int = 0
    contradicted_claims: int = 0
    uncertain_claims: int = 0
    non_verifiable_claims: int = 0
    llm_verifier_calls: int = 0
    verification_fallbacks: int = 0


class VerificationConfig(BaseModel):
    enabled: bool = False
    provider: str = "heuristic"  # heuristic | llm | mock | heuristic_llm
    enable_llm_fallback: bool = False
    llm_model: str | None = None
    evidence_top_k: int = 3
    timeout_seconds: float = 2.0
    groundedness_high_threshold: float = 0.85
    groundedness_medium_threshold: float = 0.6
