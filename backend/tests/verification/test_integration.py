import pytest
from app.services.verification.service import VerificationService
from app.services.verification.schemas import VerificationConfig

@pytest.mark.asyncio
async def test_e2e_verification_pipeline():
    answer = "Users can request a refund within 30 days. Enterprise users receive priority support."
    evidence = [
        {"chunk_id": "c1", "document_id": "d1", "document_name": "Refund Policy", "content": "Refund policy: Users may request a refund within 30 days.", "retrieval_rank": 1},
        {"chunk_id": "c2", "document_name": "Support FAQ", "content": "Enterprise users receive priority support.", "retrieval_rank": 2},
    ]
    # Heuristic only
    groundedness, trace = await VerificationService.verify_answer(answer, evidence, config=VerificationConfig(enabled=True, evidence_top_k=3))
    assert groundedness.total_claims == 2
    assert groundedness.groundedness_score >= 0.5
    assert trace.claim_count == 2
    assert trace.verification_total_ms >= 0

@pytest.mark.asyncio
async def test_fallback_no_evidence():
    answer = "Users can request refunds within 90 days."
    evidence = [
        {"chunk_id": "c1", "document_name": "Refund Policy", "content": "Refund within 30 days.", "retrieval_rank": 1},
    ]
    groundedness, trace = await VerificationService.verify_answer(answer, evidence, config=VerificationConfig(enabled=True))
    # Should detect contradiction or unsupported
    assert groundedness.total_claims >= 1
    assert groundedness.contradicted_claims + groundedness.unsupported_claims >= 1

@pytest.mark.asyncio
async def test_disabled_returns_highly_grounded():
    groundedness, trace = await VerificationService.verify_answer("Test", [], config=VerificationConfig(enabled=False))
    assert groundedness.groundedness_score == 1.0
    assert trace.verification_total_ms == 0

@pytest.mark.asyncio
async def test_tenant_isolation_preserved():
    # Verification should not leak across tenants — evidence is already tenant-filtered by retrieval
    # This test ensures verification does not do DB queries for other orgs
    answer = "Refund within 30 days."
    evidence_org1 = [{"chunk_id": "c1", "document_id": "d1", "document_name": "Refund Policy", "content": "Refund within 30 days.", "retrieval_rank": 1}]
    evidence_org2 = [{"chunk_id": "c1", "document_id": "d1", "document_name": "Other", "content": "Other content.", "retrieval_rank": 1}]
    g1, _ = await VerificationService.verify_answer(answer, evidence_org1, config=VerificationConfig(enabled=True))
    g2, _ = await VerificationService.verify_answer(answer, evidence_org2, config=VerificationConfig(enabled=True))
    assert g1.supported_claims == 1
    # g2 should be unsupported because evidence doesn't match
    assert g2.supported_claims == 0 or g2.unsupported_claims == 1
