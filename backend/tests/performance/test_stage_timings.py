"""
Tests for Request Stage Timings.
Verifies all stage durations are >= 0 and no negative timings exist.
"""

from app.core.tracing import RequestTrace


def test_stage_timings_non_negative():
    trace = RequestTrace()
    stages = [
        ("authentication_total_ms", 3.2),
        ("authorization_total_ms", 1.8),
        ("query_intelligence_total_ms", 1.2),
        ("embedding_total_ms", 12.5),
        ("vector_search_ms", 45.0),
        ("keyword_search_ms", 38.0),
        ("parallel_wall_time_ms", 46.0),
        ("parallel_sum_task_time_ms", 83.0),
        ("fusion_total_ms", 0.8),
        ("context_selection_ms", 1.5),
        ("prompt_construction_ms", 0.5),
        ("time_to_first_token_ms", 150.0),
        ("token_generation_ms", 300.0),
        ("persistence_total_ms", 4.2),
        ("request_total_ms", 520.0),
    ]

    for st, val in stages:
        trace.record(st, val)

    for st, val in trace.stages.items():
        assert val >= 0.0, f"Stage {st} duration {val} is negative"

    export_dict = trace.to_export_dict()
    assert export_dict["request"]["total_ms"] >= 0.0
    assert export_dict["stages"]["authentication"]["total_ms"] >= 0.0
    assert export_dict["stages"]["retrieval"]["total_ms"] >= 0.0
    assert export_dict["stages"]["persistence"]["total_ms"] >= 0.0
