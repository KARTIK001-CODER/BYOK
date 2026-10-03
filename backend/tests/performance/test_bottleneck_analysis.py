"""
Tests for Bottleneck Analysis and Classification.
Verifies severity threshold heuristics and bottleneck ranking.
"""

from scripts.analyze_bottlenecks import analyze_bottlenecks_data, classify_severity


def test_severity_classification():
    assert classify_severity(45.0) == "CRITICAL"
    assert classify_severity(40.0) == "CRITICAL"
    assert classify_severity(30.0) == "HIGH"
    assert classify_severity(20.0) == "HIGH"
    assert classify_severity(15.0) == "MEDIUM"
    assert classify_severity(5.0) == "MEDIUM"
    assert classify_severity(2.5) == "LOW"


def test_bottleneck_ranking():
    mock_benchmark = {
        "results": {
            "e2e": {
                "warm_summary": {
                    "end_to_end": {"average": 1000.0},
                    "stages": {
                        "llm_request_ms": {
                            "average": 500.0,
                            "p50": 500.0,
                            "p95": 600.0,
                            "p99": 650.0,
                            "percentage_of_total": 50.0,
                        },
                        "vector_search_ms": {
                            "average": 250.0,
                            "p50": 250.0,
                            "p95": 300.0,
                            "p99": 320.0,
                            "percentage_of_total": 25.0,
                        },
                        "persistence_total_ms": {
                            "average": 150.0,
                            "p50": 150.0,
                            "p95": 180.0,
                            "p99": 200.0,
                            "percentage_of_total": 15.0,
                        },
                        "embedding_total_ms": {
                            "average": 80.0,
                            "p50": 80.0,
                            "p95": 90.0,
                            "p99": 95.0,
                            "percentage_of_total": 8.0,
                        },
                        "authentication_total_ms": {
                            "average": 20.0,
                            "p50": 20.0,
                            "p95": 25.0,
                            "p99": 28.0,
                            "percentage_of_total": 2.0,
                        },
                    },
                }
            }
        }
    }

    res = analyze_bottlenecks_data(mock_benchmark)
    top_b = res["top_bottlenecks"]

    assert len(top_b) == 5
    assert top_b[0]["stage"] == "llm_request_ms"
    assert top_b[0]["severity"] == "CRITICAL"
    assert top_b[1]["stage"] == "vector_search_ms"
    assert top_b[1]["severity"] == "HIGH"
    assert top_b[2]["stage"] == "persistence_total_ms"
    assert top_b[2]["severity"] == "MEDIUM"
    assert top_b[4]["stage"] == "authentication_total_ms"
    assert top_b[4]["severity"] == "LOW"
