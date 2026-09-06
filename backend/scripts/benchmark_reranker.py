"""
Benchmark reranker — cold vs warm, candidate sizes, top-k, concurrency, memory.

Measures:
- Model initialization (cold)
- Candidate preparation
- Reranking inference (warm) for candidate sizes 5,10,20,30,50
- Sorting + total
- Memory delta (approx via psutil)
"""
import asyncio
import time
import statistics
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.reranking.service import RerankingService
from app.services.reranking.providers.local import LocalReranker

SAMPLE_QUERY = "What is the refund policy for annual subscriptions?"
SAMPLE_CANDIDATES = [
    {"chunk_id": f"c{i}", "document_id": f"d{i%3}", "document_name": f"Doc {i%3}", "content": f"Content about refund policy and pricing and technical details chunk {i} with some text to simulate document content for reranking evaluation. " * 3, "retrieval_score": 0.8 - i*0.01, "retrieval_rank": i+1}
    for i in range(50)
]

async def measure_cold_warm():
    # Force cold by resetting global
    import app.services.reranking.providers.local as local_mod
    local_mod._GLOBAL_RERANKER_MODEL = None
    local_mod._GLOBAL_RERANKER_MODEL_NAME = None

    t0 = time.perf_counter()
    # Cold init + first rerank (will load model)
    _, trace_cold = await RerankingService.rerank(SAMPLE_QUERY, SAMPLE_CANDIDATES[:20], top_k=5, candidate_k=20)
    cold_total = (time.perf_counter() - t0)*1000
    # Warm
    t1 = time.perf_counter()
    _, trace_warm = await RerankingService.rerank(SAMPLE_QUERY, SAMPLE_CANDIDATES[:20], top_k=5, candidate_k=20)
    warm_total = (time.perf_counter() - t1)*1000

    print("Cold vs Warm:")
    print(f"  Cold total: {cold_total:.2f} ms (init {trace_cold.initialization_ms} ms, inference {trace_cold.inference_ms} ms, warm={trace_cold.is_warm})")
    print(f"  Warm total: {warm_total:.2f} ms (init {trace_warm.initialization_ms} ms, inference {trace_warm.inference_ms} ms, warm={trace_warm.is_warm})")
    return trace_cold, trace_warm

async def benchmark_candidate_sizes():
    print("\nCandidate size experiment (warm model):")
    # Ensure warm
    await RerankingService.rerank(SAMPLE_QUERY, SAMPLE_CANDIDATES[:5], top_k=5)
    for k in [5, 10, 20, 30, 50]:
        cands = SAMPLE_CANDIDATES[:k]
        # Need to enable reranking; currently default false, so temporarily enable
        from app.core.config import get_settings
        orig = get_settings().ENABLE_RERANKING
        get_settings().ENABLE_RERANKING = True
        try:
            t0 = time.perf_counter()
            _, trace = await RerankingService.rerank(SAMPLE_QUERY, cands, top_k=5, candidate_k=k)
            ms = (time.perf_counter() - t0)*1000
            print(f"  candidate_k={k:2d} -> total {ms:6.2f} ms (prep {trace.candidate_preparation_ms:.1f} inference {trace.inference_ms:.1f} sorting {trace.sorting_ms:.1f})")
        finally:
            get_settings().ENABLE_RERANKING = orig

async def benchmark_concurrency():
    print("\nConcurrency (5 and 10 parallel reranks, warm):")
    from app.core.config import get_settings
    orig = get_settings().ENABLE_RERANKING
    get_settings().ENABLE_RERANKING = True
    try:
        await RerankingService.rerank(SAMPLE_QUERY, SAMPLE_CANDIDATES[:20], top_k=5)
        for n in [1, 5, 10]:
            t0 = time.perf_counter()
            tasks = [RerankingService.rerank(SAMPLE_QUERY, SAMPLE_CANDIDATES[:20], top_k=5) for _ in range(n)]
            results = await asyncio.gather(*tasks)
            ms = (time.perf_counter() - t0)*1000
            avg = ms / n
            print(f"  {n} concurrent: total {ms:.2f} ms avg {avg:.2f} ms per request, errors {sum(1 for _, tr in results if tr.fallback)}")
    finally:
        get_settings().ENABLE_RERANKING = orig

async def benchmark_memory():
    print("\nMemory (approx):")
    try:
        import psutil, os
        proc = psutil.Process(os.getpid())
        mem_before = proc.memory_info().rss / 1024 / 1024
        # Ensure model loaded
        from app.core.config import get_settings
        orig = get_settings().ENABLE_RERANKING
        get_settings().ENABLE_RERANKING = True
        await RerankingService.rerank(SAMPLE_QUERY, SAMPLE_CANDIDATES[:20], top_k=5)
        mem_after = proc.memory_info().rss / 1024 / 1024
        print(f"  RSS before: {mem_before:.1f} MB")
        print(f"  RSS after warm reranker: {mem_after:.1f} MB")
        print(f"  Delta: {mem_after - mem_before:.1f} MB (model ~80MB for MiniLM-L-6)")
        get_settings().ENABLE_RERANKING = orig
    except Exception as e:
        print(f"  Memory measurement failed: {e}")

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Reranker benchmark (Phase 2.2)")
    parser.add_argument("--candidate-k", type=int, nargs="*", default=[5,10,20,30,50], help="Candidate Ks to test")
    args = parser.parse_args()

    print("Reranker Benchmark — Phase 2.2")
    print("="*60)
    # Enable for benchmark
    from app.core.config import get_settings
    orig_flag = get_settings().ENABLE_RERANKING
    get_settings().ENABLE_RERANKING = True
    try:
        await measure_cold_warm()
        await benchmark_candidate_sizes()
        await benchmark_concurrency()
        await benchmark_memory()

        # Latency percentiles for warm reranking only
        print("\nLatency percentiles (warm, 100 runs, candidate_k=30):")
        await RerankingService.rerank(SAMPLE_QUERY, SAMPLE_CANDIDATES[:30], top_k=5)  # warm
        times = []
        for _ in range(100):
            t0 = time.perf_counter()
            await RerankingService.rerank(SAMPLE_QUERY, SAMPLE_CANDIDATES[:30], top_k=5)
            times.append((time.perf_counter() - t0)*1000)
        times_sorted = sorted(times)
        def pct(p): return times_sorted[int(len(times_sorted)*p)]
        print(f"  P50 {pct(0.5):.2f} ms P95 {pct(0.95):.2f} ms P99 {pct(0.99):.2f} ms avg {statistics.mean(times):.2f} ms")

        # Full pipeline comparison (retrieval vs retrieval+rerank)
        print("\nFull retrieval pipeline (Neon, hybrid) baseline vs reranked would be measured via evaluate_retrieval.py")
    finally:
        get_settings().ENABLE_RERANKING = orig_flag

if __name__ == "__main__":
    asyncio.run(main())
