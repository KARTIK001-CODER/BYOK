from app.services.verification.evidence_selection import EvidenceSelector
from app.services.verification.schemas import Claim, Evidence


def test_evidence_selection_basic():
    claim = Claim(claim_id="c1", text="Refund within 30 days")
    evidences = [
        Evidence(evidence_id="ev1", chunk_id="c1", document_id="d1", content="Refund policy: Users may request a refund within 30 days.", retrieval_rank=1),
        Evidence(evidence_id="ev2", chunk_id="c2", document_id="d2", content="Pricing: Maximum file size 25 MB.", retrieval_rank=2),
        Evidence(evidence_id="ev3", chunk_id="c3", document_id="d3", content="Company handbook: hybrid work.", retrieval_rank=3),
    ]
    selected, ms = EvidenceSelector.select(claim, evidences, top_k=1)
    assert len(selected) == 1
    assert selected[0].chunk_id == "c1"
    assert ms >= 0


def test_evidence_selection_top_k():
    claim = Claim(claim_id="c1", text="test")
    evidences = [Evidence(evidence_id=f"ev{i}", chunk_id=f"c{i}", document_id="d1", content=f"content {i}", retrieval_rank=i) for i in range(10)]
    selected, _ = EvidenceSelector.select(claim, evidences, top_k=3)
    assert len(selected) == 3

def test_evidence_selection_empty():
    claim = Claim(claim_id="c1", text="test")
    selected, ms = EvidenceSelector.select(claim, [], top_k=3)
    assert selected == []
