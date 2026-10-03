"""
Tests for SSE Streaming and Event Timeline Ordering.
Verifies event timeline ordering:
  request -> retrieval -> llm_request -> first_token -> last_token -> persistence -> done
"""

from app.core.tracing import RequestTrace


def test_timeline_event_ordering():
    trace = RequestTrace()
    # Sequence of events occurring during streaming
    events = [
        "request_received",
        "retrieval_started",
        "retrieval_complete",
        "llm_request_started",
        "first_token_received",
        "first_token_sent",
        "last_token_received",
        "last_token_sent",
        "persistence_completed",
        "done_sent",
        "request_completed",
    ]

    for ev in events:
        trace.mark(ev)

    recorded_event_names = [e["event"] for e in trace.timeline]
    assert recorded_event_names == events

    # Ensure timestamps are non-decreasing
    timestamps = [e["timestamp_ms"] for e in trace.timeline]
    for i in range(len(timestamps) - 1):
        assert timestamps[i] <= timestamps[i + 1]


def test_sse_gap_timing():
    trace = RequestTrace()
    trace.record("sse_first_token_gap_ms", 1.25)
    trace.record("sse_last_token_gap_ms", 0.85)
    trace.record("sse_done_gap_ms", 0.45)

    assert trace.stages["sse_first_token_gap_ms"] >= 0.0
    assert trace.stages["sse_last_token_gap_ms"] >= 0.0
    assert trace.stages["sse_done_gap_ms"] >= 0.0
