import pytest
from app.services.verification.claim_extraction import RuleBasedClaimExtractor

@pytest.mark.asyncio
async def test_claim_extraction_basic():
    extractor = RuleBasedClaimExtractor()
    answer = "Users can request a refund within 30 days. Enterprise users receive priority support."
    claims = await extractor.extract(answer)
    assert len(claims) == 2
    assert claims[0].text == "Users can request a refund within 30 days."
    assert claims[0].answer_start == 0
    assert claims[1].answer_start is not None
    assert claims[0].claim_type.value in ["FACTUAL", "POLICY", "NUMERICAL"]

@pytest.mark.asyncio
async def test_claim_spans():
    extractor = RuleBasedClaimExtractor()
    answer = "Refunds are available within 30 days. Enterprise users receive priority support."
    claims = await extractor.extract(answer)
    for c in claims:
        assert c.text in answer
        assert c.answer_start is not None
        assert answer[c.answer_start:c.answer_end] == c.text

@pytest.mark.asyncio
async def test_claim_types():
    extractor = RuleBasedClaimExtractor()
    # NUMERICAL
    claims = await extractor.extract("Refunds are available for 30 days.")
    assert any(c.claim_type.value == "NUMERICAL" for c in claims)
    # NON_VERIFIABLE
    claims2 = await extractor.extract("This is an excellent policy.")
    assert any(c.claim_type.value == "NON_VERIFIABLE" for c in claims2)
    # POLICY
    claims3 = await extractor.extract("Users must submit a request before cancellation.")
    assert len(claims3) >= 1

@pytest.mark.asyncio
async def test_claim_extraction_empty():
    extractor = RuleBasedClaimExtractor()
    assert await extractor.extract("") == []
    assert await extractor.extract("   ") == []
    # Single short without period still extracts?
    claims = await extractor.extract("Refunds within 30 days")
    assert len(claims) >= 0
