"""
Tests for RequestTrace infrastructure and trace context.
Verifies trace_id, request_id, span timing, timeline event recording, and failure safety.
"""

import time

from app.core.tracing import RequestTrace, get_current_trace, trace_context


def test_trace_creation_and_attributes():
    trace = RequestTrace()
    assert trace.trace_id is not None
    assert len(trace.trace_id) > 0
    assert trace.request_id is not None
    assert len(trace.request_id) > 0
    assert isinstance(trace.stages, dict)
    assert isinstance(trace.timestamps, dict)
    assert isinstance(trace.timeline, list)
    assert isinstance(trace.counters, dict)


def test_span_recording():
    trace = RequestTrace()
    with trace.span("test_stage"):
        time.sleep(0.01)  # 10ms

    assert "test_stage" in trace.stages
    assert trace.stages["test_stage"] >= 5.0  # at least 5ms measured


def test_timeline_events():
    trace = RequestTrace()
    trace.mark("event_one")
    trace.record_event("event_two", data={"key": "val"})

    assert "event_one" in trace.timestamps
    assert "event_two" in trace.timestamps
    assert len(trace.timeline) == 2
    assert trace.timeline[0]["event"] == "event_one"
    assert trace.timeline[1]["event"] == "event_two"
    assert trace.timeline[1]["data"] == {"key": "val"}


def test_trace_context_propagation():
    trace = RequestTrace(trace_id="trace-123", request_id="req-456")
    assert get_current_trace() is None

    with trace_context(trace) as active_trace:
        assert active_trace.trace_id == "trace-123"
        assert get_current_trace() is not None
        assert get_current_trace().trace_id == "trace-123"

    assert get_current_trace() is None


def test_tracing_failure_safety():
    """Verify tracing failures or errors do not crash caller logic."""
    trace = RequestTrace()
    # Invalid duration or error message should be handled safely
    trace.add_error("Simulated trace error")
    assert len(trace.errors) == 1
    assert "Simulated trace error" in trace.errors

    # Export dictionary should not crash on missing stages
    d = trace.to_export_dict()
    assert d["trace_id"] == trace.trace_id
    assert "critical_path" in d
