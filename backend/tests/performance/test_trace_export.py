"""
Tests for Structured Trace Export and Sanitization.
Verifies JSON export schema compliance and sanitization of secrets/keys.
"""

from app.core.tracing import RequestTrace


def test_export_format_schema():
    trace = RequestTrace(trace_id="test-trace-id", request_id="test-req-id")
    trace.record("request_total_ms", 120.0)
    trace.record("jwt_validation_ms", 0.5)
    trace.record("authentication_total_ms", 2.0)
    trace.record("embedding_total_ms", 15.0)
    trace.record("retrieval_total_ms", 45.0)
    trace.record("persistence_total_ms", 5.0)
    trace.set_counter("db_queries", 3)

    export_data = trace.to_export_dict()

    assert export_data["trace_id"] == "test-trace-id"
    assert export_data["request_id"] == "test-req-id"
    assert "request" in export_data
    assert "stages" in export_data
    assert "authentication" in export_data["stages"]
    assert "retrieval" in export_data["stages"]
    assert "persistence" in export_data["stages"]
    assert "counters" in export_data
    assert "critical_path" in export_data
    assert "timeline" in export_data


def test_export_secret_sanitization():
    trace = RequestTrace()
    # Add sensitive counters
    trace.set_counter("safe_counter", 42)
    trace.set_counter("groq_api_key", "gsk_123456789")
    trace.set_counter("user_password", "super_secret")
    trace.set_counter("jwt_token_secret", "secret_value")

    export_data = trace.to_export_dict()
    counters = export_data["counters"]

    assert "safe_counter" in counters
    assert "groq_api_key" not in counters
    assert "user_password" not in counters
    assert "jwt_token_secret" not in counters
