"""
Benchmark Query Intelligence performance — no DB, no LLM.

Measures feature extraction, classification, ambiguity, strategy, total.

Target: P50 <5ms, preferred <2ms.
"""
import time
import statistics
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.query_intelligence.analyzer import QueryAnalyzer

SAMPLE_QUERIES = [
    "What is the refund policy?",
    "cancellation_fee",
    "How does it work?",
    "What is the maximum file size allowed for uploads?",
    "If I buy annual and cancel after 20 days with 30% usage, what refund and fee apply?",
    "vector_cosine_ops",
    "Tell me about pricing",
    "What are the HNSW index parameters m and ef_construction?",
    "How do I get my money back after buying a plan?",
    "pool_size=10",
]

def benchmark(iterations: int = 1000):
    # Warmup
    for q in SAMPLE_QUERIES:
        QueryAnalyzer.analyze(q)

    timings: dict[str, list[float]] = {
        "feature_extraction_ms": [],
        "classification_ms": [],
        "ambiguity_analysis_ms": [],
        "strategy_selection_ms": [],
        "query_analysis_ms": [],
    }
    # Use analyze_with_timings to get per-stage
    for _ in range(iterations):
        for q in SAMPLE_QUERIES:
            _, t = QueryAnalyzer.analyze_with_timings(q)
            for k in timings:
                timings[k].append(t[k])

    def stats(arr):
        arr_sorted = sorted(arr)
        return {
            "p50": arr_sorted[len(arr_sorted)//2],
            "p95": arr_sorted[int(len(arr_sorted)*0.95)],
            "p99": arr_sorted[int(len(arr_sorted)*0.99)],
            "avg": statistics.mean(arr),
            "min": min(arr),
            "max": max(arr),
        }

    print(f"Iterations: {iterations} * {len(SAMPLE_QUERIES)} queries = {iterations*len(SAMPLE_QUERIES)} analyses")
    print("Per-stage timings (ms):")
    for stage, arr in timings.items():
        s = stats(arr)
        print(f"  {stage:25s} P50 {s['p50']:.3f} P95 {s['p95']:.3f} P99 {s['p99']:.3f} avg {s['avg']:.3f} max {s['max']:.3f}")

    # Overall assessment
    p50_total = stats(timings["query_analysis_ms"])["p50"]
    if p50_total < 2:
        print(f"\n✓ P50 total {p50_total:.3f}ms <2ms target (preferred)")
    elif p50_total < 5:
        print(f"\n✓ P50 total {p50_total:.3f}ms <5ms target")
    else:
        print(f"\n✗ P50 total {p50_total:.3f}ms exceeds 5ms budget")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1000, help="Iterations per query (total = iterations * 10)")
    args = parser.parse_args()
    benchmark(args.iterations)
