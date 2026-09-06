"""Groundedness aggregation — weighted scoring and answer-level status."""

from __future__ import annotations

from app.services.verification.schemas import (
    AnswerStatus,
    ClaimVerificationResult,
    GroundednessResult,
    HallucinationRisk,
    VerificationStatus,
)


def aggregate_groundedness(
    results: list[ClaimVerificationResult],
    high_threshold: float = 0.85,
    medium_threshold: float = 0.6,
) -> GroundednessResult:
    total = len(results)
    supported = sum(1 for r in results if r.status == VerificationStatus.SUPPORTED)
    partial = sum(1 for r in results if r.status == VerificationStatus.PARTIALLY_SUPPORTED)
    unsupported = sum(1 for r in results if r.status == VerificationStatus.UNSUPPORTED)
    contradicted = sum(1 for r in results if r.status == VerificationStatus.CONTRADICTED)
    uncertain = sum(1 for r in results if r.status == VerificationStatus.UNCERTAIN)
    non_verifiable = sum(1 for r in results if r.status == VerificationStatus.NON_VERIFIABLE)

    # Groundedness score: supported=1, partial=0.5, others 0, exclude uncertain/non_verifiable
    verifiable = [r for r in results if r.status not in (VerificationStatus.UNCERTAIN, VerificationStatus.NON_VERIFIABLE)]
    denom = len(verifiable) if verifiable else 1
    score = (supported * 1.0 + partial * 0.5) / denom if verifiable else 1.0
    # If all are non_verifiable, score 1.0 (no hallucination)
    if total > 0 and non_verifiable == total:
        score = 1.0

    # Rates
    unsupported_rate = unsupported / total if total else 0.0
    contradiction_rate = contradicted / total if total else 0.0

    # Answer status thresholds
    if contradicted > 0:
        status = AnswerStatus.CONTRADICTED if contradicted >= 2 or contradiction_rate >= 0.2 else AnswerStatus.LOW_GROUNDEDNESS
    elif score >= high_threshold:
        status = AnswerStatus.HIGHLY_GROUNDED
    elif score >= medium_threshold:
        status = AnswerStatus.MOSTLY_GROUNDED
    elif score >= 0.4:
        status = AnswerStatus.PARTIALLY_GROUNDED
    elif score > 0:
        status = AnswerStatus.LOW_GROUNDEDNESS
    else:
        status = AnswerStatus.UNCERTAIN if uncertain > 0 else AnswerStatus.LOW_GROUNDEDNESS

    # Hallucination risk
    if contradicted >= 2 or contradiction_rate >= 0.2:
        risk = HallucinationRisk.HIGH
    elif contradicted == 1 or unsupported >= 2 or unsupported_rate >= 0.3:
        risk = HallucinationRisk.MEDIUM
    elif unsupported == 1 or partial > 0:
        risk = HallucinationRisk.LOW
    else:
        risk = HallucinationRisk.LOW

    if contradicted == 0 and unsupported == 0 and partial == 0:
        risk = HallucinationRisk.LOW

    return GroundednessResult(
        total_claims=total,
        supported_claims=supported,
        partially_supported_claims=partial,
        unsupported_claims=unsupported,
        contradicted_claims=contradicted,
        uncertain_claims=uncertain,
        non_verifiable_claims=non_verifiable,
        groundedness_score=round(score, 3),
        hallucination_risk=risk,
        answer_status=status,
        unsupported_rate=round(unsupported_rate, 3),
        contradiction_rate=round(contradiction_rate, 3),
        claim_results=results,
    )
