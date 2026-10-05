"""
Synthetic Benchmark for Query Embedding Cache Optimization (Phase 6).
Measures cold vs warm query embedding latencies, hit rate, and calls avoided.
"""

import asyncio
import statistics
import time

from app.core.config import get_settings
from app.services.embeddings.cache import QueryEmbeddingCache
from app.services.embeddings.providers import get_embedding_provider

REPRESENTATIVE_QUERIES = [
    "What are the role permissions for Organization Admin?",
    "How does Reciprocal Rank Fusion combine vector and keyword scores?",
    "Explain the difference between document processing and re-embedding.",
    "What is the maximum token budget for context assembly in RAGForge?",
    "How are API keys and sensitive tokens filtered from logs?",
]


async def run_benchmark(iterations: int = 10):
    settings = get_settings()
    provider = get_embedding_provider()
    cache = QueryEmbeddingCache(max_size=settings.QUERY_EMBEDDING_CACHE_SIZE)

    print("=" * 70)
    print("RAGForge Query Embedding Cache Synthetic Benchmark")
    print(
        f"Provider: {provider.provider_name} | Model: {provider.model_name} (dim: {provider.dimension})"
    )
    print(f"Configured Capacity: {cache.max_size} entries")
    print(
        f"Unique Queries: {len(REPRESENTATIVE_QUERIES)} | Repetitions: {iterations} | Total Requests: {len(REPRESENTATIVE_QUERIES) * iterations}"
    )
    print("=" * 70)

    cold_latencies = []
    warm_latencies = []

    # Run passes
    for pass_idx in range(iterations):
        for q in REPRESENTATIVE_QUERIES:
            t0 = time.perf_counter()
            vec, is_hit, elapsed_ms = await cache.get_or_compute(
                query=q,
                provider=provider,
                compute_fn=lambda q=q: asyncio.to_thread(provider.embed_query, q),
            )
            total_call_ms = (time.perf_counter() - t0) * 1000.0

            if is_hit:
                warm_latencies.append(total_call_ms)
            else:
                cold_latencies.append(total_call_ms)

    stats = cache.stats

    print("\nBenchmark Results:")
    print("-" * 50)
    print(f"Total Requests:         {stats['hits'] + stats['misses']}")
    print(f"Cache Misses (Cold):    {stats['misses']}")
    print(f"Cache Hits (Warm):      {stats['hits']}")
    print(f"Cache Hit Rate:         {stats['hit_rate'] * 100:.1f}%")
    print(f"Provider Calls Avoided: {stats['calls_avoided']}")
    print(f"Cache Entries Occupied: {stats['entries']} / {stats['max_size']}")
    print("-" * 50)

    avg_cold = statistics.mean(cold_latencies) if cold_latencies else 0.0
    p95_cold = sorted(cold_latencies)[int(len(cold_latencies) * 0.95)] if cold_latencies else 0.0
    avg_warm = statistics.mean(warm_latencies) if warm_latencies else 0.0
    p95_warm = sorted(warm_latencies)[int(len(warm_latencies) * 0.95)] if warm_latencies else 0.0
    speedup = (avg_cold / avg_warm) if avg_warm > 0 else 1.0

    print("Latency Comparison:")
    print(f"  Cold Embedding Latency: avg = {avg_cold:.2f} ms | p95 = {p95_cold:.2f} ms")
    print(f"  Warm Cache-Hit Latency: avg = {avg_warm:.4f} ms | p95 = {p95_warm:.4f} ms")
    print(f"  Speedup Factor:         {speedup:.1f}x faster on repeated queries")
    print(f"  Latency Saved per Hit:  ~{avg_cold - avg_warm:.2f} ms")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
