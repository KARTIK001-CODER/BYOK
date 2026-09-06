import pytest
from app.services.reranking.providers.mock import MockReranker
from app.services.reranking.factory import RerankerFactory
from app.services.reranking.service import RerankingService


@pytest.mark.asyncio
async def test_mock_reranker_deterministic():
    mock = MockReranker()
    cands = [
        {"chunk_id": "c1", "content": "refund policy money back", "retrieval_rank": 3},
        {"chunk_id": "c2", "content": "pricing plans", "retrieval_rank": 1},
        {"chunk_id": "c3", "content": "refund policy details", "retrieval_rank": 2},
    ]
    # Query about refund should rank c1/c3 higher than c2
    res = await mock.rerank("refund policy", cands, top_k=3)
    assert res[0]["chunk_id"] in ("c1", "c3")
    assert "rerank_score" in res[0]
    assert "rerank_rank" in res[0]
    # deterministic
    res2 = await mock.rerank("refund policy", cands, top_k=3)
    assert res == res2


@pytest.mark.asyncio
async def test_reranking_top_k():
    mock = MockReranker()
    cands = [{"chunk_id": f"c{i}", "content": f"content {i}", "retrieval_rank": i} for i in range(1, 11)]
    res = await mock.rerank("test", cands, top_k=3)
    assert len(res) == 3
    assert res[0]["rerank_rank"] == 1


def test_factory():
    mock = RerankerFactory.create(provider="mock")
    assert mock.name == "mock"
    local = RerankerFactory.create(provider="local")
    # local may fallback to mock if sentence_transformers missing, but should not crash
    assert local.name in ("local", "mock")


@pytest.mark.asyncio
async def test_reranking_service_dedup():
    cands = [
        {"chunk_id": "c1", "content": "hello world", "retrieval_rank": 1},
        {"chunk_id": "c1", "content": "hello world", "retrieval_rank": 2},  # duplicate
        {"chunk_id": "c2", "content": "foo bar", "retrieval_rank": 3},
    ]
    # Enable reranking for test
    from app.core.config import get_settings
    orig = get_settings().ENABLE_RERANKING
    get_settings().ENABLE_RERANKING = True
    try:
        result, trace = await RerankingService.rerank("hello", cands, top_k=5, candidate_k=30)
        # dedup should remove duplicate c1
        assert len([r for r in result if r["chunk_id"] == "c1"]) <= 1
        assert trace.candidate_count == 2  # deduped
    finally:
        get_settings().ENABLE_RERANKING = orig


@pytest.mark.asyncio
async def test_reranking_fallback_disabled():
    cands = [{"chunk_id": "c1", "content": "hello", "retrieval_rank": 1}]
    from app.core.config import get_settings
    orig = get_settings().ENABLE_RERANKING
    get_settings().ENABLE_RERANKING = False
    try:
        result, trace = await RerankingService.rerank("hello", cands, top_k=5)
        assert trace.enabled is False
        assert trace.fallback is True
        assert len(result) == 1
    finally:
        get_settings().ENABLE_RERANKING = orig


@pytest.mark.asyncio
async def test_reranking_empty():
    from app.core.config import get_settings
    orig = get_settings().ENABLE_RERANKING
    get_settings().ENABLE_RERANKING = True
    try:
        result, trace = await RerankingService.rerank("hello", [], top_k=5)
        assert result == []
        assert trace.candidate_count == 0
    finally:
        get_settings().ENABLE_RERANKING = orig


@pytest.mark.asyncio
async def test_reranking_timeout():
    # Use very small timeout to trigger fallback
    cands = [{"chunk_id": f"c{i}", "content": "content", "retrieval_rank": i} for i in range(10)]
    # Mock reranker that sleeps
    class SlowMock(MockReranker):
        async def rerank(self, query, candidates, top_k=5):
            import asyncio
            await asyncio.sleep(1)
            return await super().rerank(query, candidates, top_k)

    from app.services.reranking.factory import RerankerFactory
    RerankerFactory.set_mock_provider(SlowMock())
    from app.core.config import get_settings
    orig = get_settings().ENABLE_RERANKING
    get_settings().ENABLE_RERANKING = True
    try:
        result, trace = await RerankingService.rerank("hello", cands, top_k=5, timeout_seconds=0.01, provider="mock")
        assert trace.timeout is True or trace.fallback is True
        # Should fallback to original order
        assert len(result) == 5
    finally:
        get_settings().ENABLE_RERANKING = orig
        RerankerFactory.set_mock_provider(None)
