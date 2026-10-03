"""
Tests for Statistical Calculation.
Verifies percentiles (P50, P95, P99), stddev, min, max, average, and percentages.
"""

from scripts.benchmark_end_to_end import calculate_percentile, compute_statistics


def test_percentile_calculation():
    # Linear dataset 1 to 100
    data = list(range(1, 101))
    p50 = calculate_percentile(data, 50)
    p95 = calculate_percentile(data, 95)
    p99 = calculate_percentile(data, 99)

    assert p50 == 50.5
    assert p95 == 95.05
    assert p99 == 99.01


def test_compute_statistics_full():
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = compute_statistics(data, total_reference=100.0)

    assert stats["count"] == 5
    assert stats["min"] == 10.0
    assert stats["max"] == 50.0
    assert stats["average"] == 30.0
    assert stats["median"] == 30.0
    assert stats["p50"] == 30.0
    assert stats["percentage_of_total"] == 30.0
    assert stats["stddev"] > 0.0


def test_empty_statistics():
    stats = compute_statistics([])
    assert stats["count"] == 0
    assert stats["p50"] == 0.0
    assert stats["p95"] == 0.0
    assert stats["p99"] == 0.0
