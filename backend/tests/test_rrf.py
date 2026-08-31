import pytest

from app.models.document_chunk import DocumentChunk
from app.services.retrieval.fusion import CandidateMatch, ReciprocalRankFusion


def create_fake_chunk(
    chunk_id: str, doc_id: str = "doc-1", content: str = "test content"
) -> DocumentChunk:
    chunk = DocumentChunk(
        id=chunk_id,
        document_id=doc_id,
        document_version_id="ver-1",
        organization_id="org-1",
        knowledge_base_id="kb-1",
        chunk_index=0,
        content=content,
        character_count=len(content),
        word_count=len(content.split()),
    )
    return chunk


def test_rrf_mathematical_calculation() -> None:
    """
    Verify exact RRF score calculation.
    Given:
        k = 60
        Vector: A (rank 1), B (rank 2), C (rank 3)
        Keyword: B (rank 1), D (rank 2), A (rank 3)

    Expected scores:
        A = 1/(60+1) + 1/(60+3) = 1/61 + 1/63 ≈ 0.01639344 + 0.01587301 ≈ 0.032266
        B = 1/(60+2) + 1/(60+1) = 1/62 + 1/61 ≈ 0.01612903 + 0.01639344 ≈ 0.032522
        C = 1/(60+3) = 1/63 ≈ 0.015873
        D = 1/(60+2) = 1/62 ≈ 0.016129

    Rank order: B (rank 1), A (rank 2), D (rank 3), C (rank 4)
    """
    chunk_a = create_fake_chunk("chunk-A")
    chunk_b = create_fake_chunk("chunk-B")
    chunk_c = create_fake_chunk("chunk-C")
    chunk_d = create_fake_chunk("chunk-D")

    vec_candidates = [
        CandidateMatch(chunk=chunk_a, score=0.95, rank=1, source="vector"),
        CandidateMatch(chunk=chunk_b, score=0.85, rank=2, source="vector"),
        CandidateMatch(chunk=chunk_c, score=0.75, rank=3, source="vector"),
    ]

    kw_candidates = [
        CandidateMatch(chunk=chunk_b, score=0.90, rank=1, source="keyword"),
        CandidateMatch(chunk=chunk_d, score=0.80, rank=2, source="keyword"),
        CandidateMatch(chunk=chunk_a, score=0.70, rank=3, source="keyword"),
    ]

    rrf = ReciprocalRankFusion(rrf_k=60)
    results = rrf.fuse(vec_candidates, kw_candidates, top_k=10)

    assert len(results) == 4

    # Rank 1: B
    assert results[0].chunk_id == "chunk-B"
    assert results[0].rank == 1
    assert results[0].source == "hybrid"
    assert results[0].score == pytest.approx(1 / 62 + 1 / 61, abs=1e-5)
    assert results[0].vector_score == 0.85
    assert results[0].keyword_score == 0.90

    # Rank 2: A
    assert results[1].chunk_id == "chunk-A"
    assert results[1].rank == 2
    assert results[1].source == "hybrid"
    assert results[1].score == pytest.approx(1 / 61 + 1 / 63, abs=1e-5)
    assert results[1].vector_score == 0.95
    assert results[1].keyword_score == 0.70

    # Rank 3: D
    assert results[2].chunk_id == "chunk-D"
    assert results[2].rank == 3
    assert results[2].source == "keyword"
    assert results[2].score == pytest.approx(1 / 62, abs=1e-5)
    assert results[2].vector_score is None
    assert results[2].keyword_score == 0.80

    # Rank 4: C
    assert results[3].chunk_id == "chunk-C"
    assert results[3].rank == 4
    assert results[3].source == "vector"
    assert results[3].score == pytest.approx(1 / 63, abs=1e-5)
    assert results[3].vector_score == 0.75
    assert results[3].keyword_score is None


def test_rrf_empty_candidates() -> None:
    """Verify behavior when one or both candidate lists are empty."""
    rrf = ReciprocalRankFusion(rrf_k=60)

    # Both empty
    assert rrf.fuse([], [], top_k=5) == []

    # Only vector
    chunk_a = create_fake_chunk("chunk-A")
    vec_cands = [CandidateMatch(chunk=chunk_a, score=0.9, rank=1, source="vector")]
    results = rrf.fuse(vec_cands, [], top_k=5)
    assert len(results) == 1
    assert results[0].chunk_id == "chunk-A"
    assert results[0].source == "vector"
    assert results[0].score == pytest.approx(1 / 61, abs=1e-5)


def test_rrf_top_k_truncation() -> None:
    """Verify top_k truncation limits output size."""
    chunks = [create_fake_chunk(f"chunk-{i}") for i in range(10)]
    vec_cands = [
        CandidateMatch(chunk=chunks[i], score=1.0 - i * 0.1, rank=i + 1, source="vector")
        for i in range(10)
    ]

    rrf = ReciprocalRankFusion(rrf_k=60)
    results = rrf.fuse(vec_cands, [], top_k=3)
    assert len(results) == 3
    assert [r.chunk_id for r in results] == ["chunk-0", "chunk-1", "chunk-2"]
    assert [r.rank for r in results] == [1, 2, 3]


def test_rrf_invalid_k() -> None:
    """Verify exception when invalid rrf_k is supplied."""
    with pytest.raises(ValueError, match="RRF smoothing constant k must be positive"):
        ReciprocalRankFusion(rrf_k=0)
