"""
Tests for Parallel Retrieval Overlap and Efficiency Timing.
Verifies parallel wall time <= sum task times, overlap calculation, and speedup efficiency.
"""

from app.core.tracing import RequestTrace


def test_parallel_overlap_and_efficiency():
    trace = RequestTrace()
    # Task A: Vector Search = 50ms (starts at T+10ms, ends at T+60ms)
    # Task B: Keyword Search = 40ms (starts at T+12ms, ends at T+52ms)
    trace.record("vector_search_ms", 50.0)
    trace.record("keyword_search_ms", 40.0)
    trace.timestamps["vector_search_started"] = 10.0
    trace.timestamps["vector_search_completed"] = 60.0
    trace.timestamps["keyword_search_started"] = 12.0
    trace.timestamps["keyword_search_completed"] = 52.0

    metrics = trace.calculate_parallel_metrics()

    assert metrics["parallel_task_count"] == 2
    assert metrics["parallel_wall_time_ms"] == 50.0  # 60 - 10
    assert metrics["parallel_sum_task_time_ms"] == 90.0  # 50 + 40
    # Overlap: 52 - 12 = 40ms
    assert metrics["parallel_overlap_ms"] == 40.0
    # Efficiency: 90 / 50 = 1.8x
    assert metrics["parallel_efficiency"] == 1.8
    assert metrics["parallel_wall_time_ms"] <= metrics["parallel_sum_task_time_ms"]


def test_critical_path_parallel_handling():
    trace = RequestTrace()
    trace.record("authentication_total_ms", 10.0)
    trace.record("vector_search_ms", 50.0)
    trace.record("keyword_search_ms", 40.0)
    trace.timestamps["vector_search_started"] = 10.0
    trace.timestamps["vector_search_completed"] = 60.0
    trace.timestamps["keyword_search_started"] = 10.0
    trace.timestamps["keyword_search_completed"] = 50.0
    trace.record("persistence_total_ms", 10.0)

    cp = trace.calculate_critical_path()
    # Critical path should NOT sum 50 + 40 = 90. It should take parallel wall time (50ms).
    # Expected: 10 (auth) + 50 (parallel retrieval) + 10 (persistence) = 70ms
    assert cp["critical_path_ms"] == 70.0
