from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.investigation import (
    HypothesisConfidence,
    HypothesisStatus,
    InvestigationErrorCategory,
    InvestigationStatus,
)
from app.schemas.common import PaginatedResponse


class InvestigationCreate(BaseModel):
    """Payload to request a new investigation for an incident."""

    idempotency_key: str | None = Field(
        default=None,
        max_length=255,
        description="Client-supplied key making duplicate submissions safe",
    )
    result_limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum evidence items assembled for the investigation",
    )


class InvestigationJobResponse(BaseModel):
    """Durable investigation job state. Poll this resource for progress."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    incident_id: str
    organization_id: str
    status: InvestigationStatus
    stage: str
    progress: int = Field(ge=0, le=100)
    attempt_count: int
    max_attempts: int
    requested_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_category: InvestigationErrorCategory
    error_summary: str | None = None
    provider: str | None = None
    model: str | None = None
    app_version: str | None = None
    result_summary: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


InvestigationJobListResponse = PaginatedResponse[InvestigationJobResponse]


class EvidenceProvenanceItem(BaseModel):
    """Provenance for one retrieved evidence item. Every factual claim links here."""

    evidence_id: str
    source_type: str
    event_type: str
    event_timestamp: datetime
    summary: str
    source_reference: str | None = None
    retrieval_method: Literal["lexical", "keyword", "vector", "hybrid"]
    score: float | None = None
    rank: int | None = None


class EvidenceLinkResponse(BaseModel):
    """One hypothesis-to-evidence link (supports or contradicts)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    hypothesis_id: str
    evidence_event_id: str
    link_type: Literal["supports", "contradicts"]
    excerpt: str | None = None


class HypothesisResponse(BaseModel):
    """An inferred root-cause hypothesis with explicit supporting/contradicting evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    investigation_job_id: str
    incident_id: str
    organization_id: str
    claim: str
    rationale: str
    confidence: HypothesisConfidence
    confidence_score: float | None = None
    confidence_note: str = (
        "Model-reported confidence is an uncalibrated self-assessment, "
        "not a statistically calibrated probability."
    )
    status: HypothesisStatus
    rejection_reason: str | None = None
    provider: str | None = None
    model: str | None = None
    created_at: datetime
    supporting_evidence: list[EvidenceLinkResponse] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceLinkResponse] = Field(default_factory=list)


HypothesisListResponse = PaginatedResponse[HypothesisResponse]


# ─── Structured LLM output (validated server-side before persistence) ─────────


class LLMHypothesisDraft(BaseModel):
    """Single hypothesis draft as returned by the model."""

    claim: str = Field(..., min_length=1, max_length=2000)
    rationale: str = Field(..., min_length=1, max_length=4000)
    confidence: HypothesisConfidence = HypothesisConfidence.MEDIUM
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)


class LLMNextStep(BaseModel):
    """One diagnostic next step. Diagnostic only; risky actions need human approval."""

    action: str = Field(..., min_length=1, max_length=1000)
    requires_human_approval: bool = True
    rationale: str | None = Field(default=None, max_length=1000)


class LLMInvestigationOutput(BaseModel):
    """Structured investigation output the model must return."""

    hypotheses: list[LLMHypothesisDraft] = Field(default_factory=list, max_length=5)
    observed_facts: list[str] = Field(default_factory=list, max_length=20)
    uncertainty_notes: list[str] = Field(default_factory=list, max_length=20)
    recommended_next_steps: list[LLMNextStep] = Field(default_factory=list, max_length=10)
