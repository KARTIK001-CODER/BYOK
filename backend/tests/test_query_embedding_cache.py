"""
Tests for QueryEmbeddingCache (Phase 5).
Covers hit/miss, LRU eviction, model key differentiation, query normalization,
concurrent stampede deduplication, failure non-caching, cancellation cleanup,
mutation isolation, cache disabled toggle, and trace metrics.
"""

import asyncio
from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.core.tracing import RequestTrace, trace_context
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.cache import QueryEmbeddingCache, get_query_embedding_cache
from app.services.embeddings.errors import EmbeddingErrorCode, EmbeddingException
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService


class DummyProvider(BaseEmbeddingProvider):
    def __init__(self, provider_name="local", model_name="test-model", dimension=4):
        self._provider_name = provider_name
        self._model_name = model_name
        self._dimension = dimension
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] * self._dimension for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        self.call_count += 1
        return [0.1, 0.2, 0.3, 0.4]


@pytest.fixture(autouse=True)
async def clear_cache():
    """Ensure clean global cache before and after every test."""
    cache = get_query_embedding_cache()
    await cache.clear()
    yield
    await cache.clear()


@pytest.mark.asyncio
async def test_cache_miss_then_hit():
    """1. Cache miss on new query, cache hit on repeated identical query."""
    cache = QueryEmbeddingCache(max_size=10)
    provider = DummyProvider()

    async def compute():
        return provider.embed_query("hello world")

    # 1. First call -> Cache Miss
    vec1, is_hit1, lat1 = await cache.get_or_compute("hello world", provider, compute)
    assert is_hit1 is False
    assert vec1 == [0.1, 0.2, 0.3, 0.4]
    assert provider.call_count == 1
    assert cache.stats["hits"] == 0
    assert cache.stats["misses"] == 1
    assert cache.stats["entries"] == 1

    # 2. Second call -> Cache Hit
    vec2, is_hit2, lat2 = await cache.get_or_compute("hello world", provider, compute)
    assert is_hit2 is True
    assert vec2 == [0.1, 0.2, 0.3, 0.4]
    assert provider.call_count == 1  # No extra call to provider
    assert cache.stats["hits"] == 1
    assert cache.stats["misses"] == 1
    assert cache.stats["calls_avoided"] == 1


@pytest.mark.asyncio
async def test_lru_eviction():
    """3. LRU eviction when capacity is exceeded."""
    cache = QueryEmbeddingCache(max_size=2)
    provider = DummyProvider()

    async def compute(q):
        return provider.embed_query(q)

    # Insert q1 and q2
    await cache.get_or_compute("q1", provider, lambda: compute("q1"))
    await cache.get_or_compute("q2", provider, lambda: compute("q2"))
    assert cache.stats["entries"] == 2
    assert cache.stats["evictions"] == 0

    # Access q1 to make it most recently used (q2 becomes LRU)
    await cache.get_or_compute("q1", provider, lambda: compute("q1"))

    # Insert q3 -> Should evict q2
    await cache.get_or_compute("q3", provider, lambda: compute("q3"))
    assert cache.stats["entries"] == 2
    assert cache.stats["evictions"] == 1

    # q1 and q3 should be in cache
    assert await cache.get("q1", provider) is not None
    assert await cache.get("q3", provider) is not None
    # q2 should have been evicted
    assert await cache.get("q2", provider) is None


def test_different_models_produce_different_keys():
    """4. Different models or configurations producing different keys."""
    key1 = QueryEmbeddingCache.generate_cache_key("test query", "local", "model-a", 384)
    key2 = QueryEmbeddingCache.generate_cache_key("test query", "local", "model-b", 384)
    key3 = QueryEmbeddingCache.generate_cache_key("test query", "openai", "model-a", 384)
    key4 = QueryEmbeddingCache.generate_cache_key("test query", "local", "model-a", 768)

    assert key1 != key2
    assert key1 != key3
    assert key1 != key4


def test_query_normalization_behavior():
    """5. Query normalization behavior (whitespace invariance)."""
    key_clean = QueryEmbeddingCache.generate_cache_key("what is byok?", "local", "model-a", 384)
    key_padded = QueryEmbeddingCache.generate_cache_key(
        "   what is byok?  \t\n", "local", "model-a", 384
    )

    assert key_clean == key_padded


@pytest.mark.asyncio
async def test_concurrent_requests_stampede_deduplication():
    """6. Concurrent identical requests: simultaneous misses trigger only 1 computation."""
    cache = QueryEmbeddingCache(max_size=10)
    provider = DummyProvider()

    async def slow_compute():
        await asyncio.sleep(0.05)  # Simulate 50ms ONNX inference
        return provider.embed_query("concurrent query")

    # Launch 5 identical concurrent queries simultaneously
    tasks = [cache.get_or_compute("concurrent query", provider, slow_compute) for _ in range(5)]
    results = await asyncio.gather(*tasks)

    # All 5 return correct vector
    for vec, _, _ in results:
        assert vec == [0.1, 0.2, 0.3, 0.4]

    # Only 1 actual call was made to the provider!
    assert provider.call_count == 1
    assert cache.stats["misses"] == 1
    assert cache.stats["hits"] == 4
    assert cache.stats["calls_avoided"] == 4


@pytest.mark.asyncio
async def test_embedding_failure_not_cached():
    """7. Embedding failure and retry behavior (failed computations do not populate cache)."""
    cache = QueryEmbeddingCache(max_size=10)
    provider = DummyProvider()
    should_fail = True

    async def failing_compute():
        if should_fail:
            raise EmbeddingException(
                message="Temporary ONNX failure",
                code=EmbeddingErrorCode.EMBEDDING_PROVIDER_FAILED,
            )
        return provider.embed_query("failing query")

    # Attempt 1: Fails
    with pytest.raises(EmbeddingException):
        await cache.get_or_compute("failing query", provider, failing_compute)

    assert cache.stats["entries"] == 0
    assert cache.stats["hits"] == 0

    # Attempt 2: Succeeds on retry
    should_fail = False
    vec, is_hit, _ = await cache.get_or_compute("failing query", provider, failing_compute)
    assert is_hit is False
    assert vec == [0.1, 0.2, 0.3, 0.4]
    assert cache.stats["entries"] == 1


@pytest.mark.asyncio
async def test_cancellation_and_in_flight_cleanup():
    """8. Cancellation must not leave corrupted entries or hanging in-flight futures."""
    cache = QueryEmbeddingCache(max_size=10)
    provider = DummyProvider()

    async def hanging_compute():
        await asyncio.sleep(5.0)
        return provider.embed_query("hang")

    task = asyncio.create_task(cache.get_or_compute("hang", provider, hanging_compute))
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Cache should be clean with no in-flight entries left behind
    assert cache.stats["entries"] == 0
    assert cache.stats["in_flight"] == 0


@pytest.mark.asyncio
async def test_vector_mutation_isolation():
    """10. Vector mutation isolation: caller modifying result does not corrupt cache."""
    cache = QueryEmbeddingCache(max_size=10)
    provider = DummyProvider()

    async def compute():
        return [1.0, 2.0, 3.0, 4.0]

    vec1, _, _ = await cache.get_or_compute("mutate_test", provider, compute)
    assert vec1 == [1.0, 2.0, 3.0, 4.0]

    # Mutate the returned vector
    vec1[0] = 999.9

    # Re-fetch from cache
    vec2, is_hit, _ = await cache.get_or_compute("mutate_test", provider, compute)
    assert is_hit is True
    # The cached vector must remain uncorrupted!
    assert vec2[0] == 1.0
    assert vec2 == [1.0, 2.0, 3.0, 4.0]


@pytest.mark.asyncio
async def test_cache_reset_and_invalidation():
    """11. Cache reset and invalidation clears entries and counters."""
    cache = QueryEmbeddingCache(max_size=10)
    provider = DummyProvider()

    await cache.get_or_compute("q1", provider, lambda: asyncio.sleep(0, [0.1, 0.2, 0.3, 0.4]))
    assert cache.stats["entries"] == 1

    await cache.clear()
    assert cache.stats["entries"] == 0
    assert cache.stats["hits"] == 0
    assert cache.stats["misses"] == 0
    assert cache.stats["evictions"] == 0


@pytest.mark.asyncio
async def test_retrieval_service_cache_hit_and_trace_metrics(
    db_session,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """12 & 13. End-to-end RetrievalService integration: cache hit separates latency and updates trace."""
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    req = RetrievalRequest(
        query="What is the architecture of RAGForge?",
        knowledge_base_ids=[test_kb.id],
        top_k=5,
        candidate_k=10,
        search_mode=SearchMode.VECTOR,
    )

    # 1. Cold search -> Cache Miss
    trace1 = RequestTrace(trace_id="trace-cold", request_id="req-cold")
    with trace_context(trace1):
        resp1 = await RetrievalService.search(
            session=db_session,
            organization_id=org.id,
            request=req,
        )
    assert resp1 is not None
    assert trace1.counters.get("embedding_cache_hit") is False
    assert trace1.stages.get("embedding_inference_ms", 0.0) >= 0.0

    # 2. Warm search with same query -> Cache Hit
    trace2 = RequestTrace(trace_id="trace-warm", request_id="req-warm")
    with trace_context(trace2):
        resp2 = await RetrievalService.search(
            session=db_session,
            organization_id=org.id,
            request=req,
        )
    assert resp2 is not None
    # Verify cache hit recorded
    assert trace2.counters.get("embedding_cache_hit") is True
    # Verify provider execution is reported as 0.0ms on hit (not skipped work as execution)
    assert trace2.stages.get("embedding_inference_ms") == 0.0
    # Cache lookup latency is captured separately
    assert "embedding_cache_latency_ms" in trace2.stages
    assert trace2.stages["embedding_cache_latency_ms"] >= 0.0


@pytest.mark.asyncio
async def test_cache_disabled_toggle(
    db_session,
    test_user_and_org: dict,
    test_kb: KnowledgeBase,
):
    """9. When cache is disabled via settings, cache is bypassed and every search computes."""
    org: Organization = test_user_and_org["org"]

    mock_provider = MockLLMProvider()
    LLMProviderFactory.set_mock_provider(mock_provider)

    req = RetrievalRequest(
        query="Disabled cache test query",
        knowledge_base_ids=[test_kb.id],
        top_k=5,
        candidate_k=10,
        search_mode=SearchMode.VECTOR,
    )

    settings = get_settings()
    with patch.object(settings, "ENABLE_QUERY_EMBEDDING_CACHE", False):
        trace1 = RequestTrace(trace_id="trace-dis-1", request_id="req-dis-1")
        with trace_context(trace1):
            resp1 = await RetrievalService.search(
                session=db_session,
                organization_id=org.id,
                request=req,
            )
        assert resp1 is not None
        assert trace1.counters.get("embedding_cache_hit") is False

        trace2 = RequestTrace(trace_id="trace-dis-2", request_id="req-dis-2")
        with trace_context(trace2):
            resp2 = await RetrievalService.search(
                session=db_session,
                organization_id=org.id,
                request=req,
            )
        assert resp2 is not None
        # Cache hit must still be False because cache is disabled
        assert trace2.counters.get("embedding_cache_hit") is False
