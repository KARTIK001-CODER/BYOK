import pytest
from app.services.verification.providers.heuristic import HeuristicVerifier
from app.services.verification.schemas import Claim, Evidence, VerificationStatus


@pytest.mark.asyncio
async def test_numerical_contradiction():
    verifier = HeuristicVerifier()
    claim = Claim(claim_id="c1", text="Refunds are available within 90 days.", claim_type="NUMERICAL")
    evidence = [Evidence(evidence_id="ev1", chunk_id="c1", document_id="d1", content="Refund period is 30 days.", retrieval_rank=1)]
    result = await verifier.verify(claim, evidence)
    assert result.status == VerificationStatus.CONTRADICTED


@pytest.mark.asyncio
async def test_negation_contradiction():
    verifier = HeuristicVerifier()
    claim = Claim(claim_id="c1", text="Users can request refunds after 30 days.")
    evidence = [Evidence(evidence_id="ev1", chunk_id="c1", document_id="d1", content="Users cannot request refunds after 30 days.", retrieval_rank=1)]
    result = await verifier.verify(claim, evidence)
    assert result.status == VerificationStatus.CONTRADICTED


@pytest.mark.asyncio
async def test_supported():
    verifier = HeuristicVerifier()
    claim = Claim(claim_id="c1", text="Users can request a refund within 30 days.")
    evidence = [Evidence(evidence_id="ev1", chunk_id="c1", document_id="d1", content="Users may request a refund within 30 days.", retrieval_rank=1)]
    result = await verifier.verify(claim, evidence)
    assert result.status in [VerificationStatus.SUPPORTED, VerificationStatus.PARTIALLY_SUPPORTED]
    assert result.confidence >= 0.5


@pytest.mark.asyncio
async def test_unsupported():
    verifier = HeuristicVerifier()
    claim = Claim(claim_id="c1", text="Refunds include free shipping.")
    evidence = [Evidence(evidence_id="ev1", chunk_id="c1", document_id="d1", content="Refund policy: Users may request a refund within 30 days.", retrieval_rank=1)]
    result = await verifier.verify(claim, evidence)
    assert result.status in [VerificationStatus.UNSUPPORTED, VerificationStatus.UNCERTAIN]


@pytest.mark.asyncio
async def test_non_verifiable():
    verifier = HeuristicVerifier()
    claim = Claim(claim_id="c1", text="This is an excellent policy.", claim_type="NON_VERIFIABLE")
    evidence = [Evidence(evidence_id="ev1", chunk_id="c1", document_id="d1", content="Refund within 30 days.", retrieval_rank=1)]
    result = await verifier.verify(claim, evidence)
    assert result.status == VerificationStatus.NON_VERIFIABLE


@pytest.mark.asyncio
async def test_empty_evidence():
    verifier = HeuristicVerifier()
    claim = Claim(claim_id="c1", text="Test claim")
    result = await verifier.verify(claim, [])
    assert result.status == VerificationStatus.UNSUPPORTED
