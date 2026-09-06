from app.services.verification.aggregation import aggregate_groundedness
from app.services.verification.schemas import Claim, ClaimVerificationResult, VerificationStatus


def make_result(status, claim_id="c1"):
    claim = Claim(claim_id=claim_id, text="test")
    return ClaimVerificationResult(claim=claim, status=status, confidence=0.9, evidence=[], provider="heuristic")


def test_groundedness_score():
    # 8 supported, 2 partial, 1 unsupported out of 11 verifiable
    results = [make_result(VerificationStatus.SUPPORTED) for _ in range(8)]
    results += [make_result(VerificationStatus.PARTIALLY_SUPPORTED) for _ in range(2)]
    results += [make_result(VerificationStatus.UNSUPPORTED)]
    agg = aggregate_groundedness(results)
    assert agg.total_claims == 11
    assert agg.supported_claims == 8
    assert agg.partially_supported_claims == 2
    assert agg.unsupported_claims == 1
    # score = (8*1 +2*0.5)/11 =9/11=0.818
    assert agg.groundedness_score == 0.818
    assert agg.answer_status.value in ["HIGHLY_GROUNDED", "MOSTLY_GROUNDED"]


def test_non_verifiable_excluded():
    results = [make_result(VerificationStatus.NON_VERIFIABLE) for _ in range(5)]
    agg = aggregate_groundedness(results)
    assert agg.groundedness_score == 1.0  # all non_verifiable -> 1.0
    assert agg.non_verifiable_claims == 5


def test_contradicted_status():
    results = [make_result(VerificationStatus.CONTRADICTED), make_result(VerificationStatus.CONTRADICTED), make_result(VerificationStatus.SUPPORTED)]
    agg = aggregate_groundedness(results)
    assert agg.contradicted_claims == 2
    assert agg.answer_status.value == "CONTRADICTED" or agg.answer_status.value == "LOW_GROUNDEDNESS"
    assert agg.hallucination_risk.value == "HIGH"


def test_importance_weighting_current_uniform():
    # Currently all importance=1, but aggregation should still work
    results = [make_result(VerificationStatus.SUPPORTED), make_result(VerificationStatus.SUPPORTED)]
    agg = aggregate_groundedness(results)
    assert agg.groundedness_score == 1.0
