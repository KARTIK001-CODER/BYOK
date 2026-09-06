"""Request-level latency tracing infrastructure for Phase 1.5 deep tracing."""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("app.tracing")

# ── Context variables (re-exported from logging to keep single source of truth) ─
from app.core.logging import (  # noqa: E402  (circular-safe: logging has no dep on tracing)
    get_request_id,
    get_trace_id,
    request_id_ctx_var,
    set_request_id,
    set_trace_id,
    trace_id_ctx_var,
)


# ── Trace collector ───────────────────────────────────────────────────────

@dataclass
class RequestTrace:
    """Collects per-request stage timings; serialised as JSON at the end."""

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    _start: float = field(default_factory=time.perf_counter)
    stages: dict[str, float] = field(default_factory=dict)
    timestamps: dict[str, float] = field(default_factory=dict)
    counters: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def mark(self, name: str) -> None:
        """Record absolute timestamp (ms since trace start) for concurrency checks."""
        self.timestamps[name] = (time.perf_counter() - self._start) * 1000.0

    def record(self, stage: str, duration_ms: float) -> None:
        self.stages[stage] = round(float(duration_ms), 2)

    def set_counter(self, key: str, value: Any) -> None:
        self.counters[key] = value

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    @contextmanager
    def span(self, stage: str):
        """Context-manager that measures elapsed ms and records automatically."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.record(stage, (time.perf_counter() - t0) * 1000.0)

    def to_dict(self) -> dict[str, Any]:
        total = (time.perf_counter() - self._start) * 1000.0
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "total_ms": round(total, 2),
            "stages": dict(self.stages),
            "timestamps": dict(self.timestamps),
            "counters": dict(self.counters),
            "errors": list(self.errors),
        }

    def log_summary(self) -> None:
        """Emit structured trace summary via logger at INFO level."""
        d = self.to_dict()
        # Build compact ASCII waterfall for human-readable
        stages_sorted = sorted(d["stages"].items(), key=lambda x: -x[1])
        total = d["total_ms"] or 1.0
        lines = [f"TRACE {d['trace_id']} req={d['request_id']} total={d['total_ms']:.1f}ms"]
        for name, ms in stages_sorted:
            pct = (ms / total) * 100
            lines.append(f"  {name:40s} {ms:8.2f} ms  ({pct:4.1f}%)")
        if d["timestamps"]:
            lines.append("  --- timestamps (ms since request_start) ---")
            for k, v in sorted(d["timestamps"].items(), key=lambda x: x[1]):
                lines.append(f"    {k:40s} {v:8.2f} ms")
        if d["counters"]:
            lines.append(f"  counters: {d['counters']}")
        logger.info("\n".join(lines))

    def as_header_dict(self) -> dict[str, str]:
        return {"X-Trace-ID": self.trace_id, "X-Request-ID": self.request_id}


# Single context-var holding the *current* RequestTrace for implicit access
_current_trace_ctx: contextvars.ContextVar[RequestTrace | None] = contextvars.ContextVar(
    "_current_trace", default=None
)


def get_current_trace() -> RequestTrace | None:
    return _current_trace_ctx.get()


def set_current_trace(trace: RequestTrace | None) -> contextvars.Token[RequestTrace | None]:
    return _current_trace_ctx.set(trace)


@contextmanager
def trace_context(trace: RequestTrace):
    tok = set_current_trace(trace)
    tid_tok = set_trace_id(trace.trace_id)
    rid_tok = set_request_id(trace.request_id)
    try:
        yield trace
    finally:
        set_current_trace(None)
        trace_id_ctx_var.reset(tid_tok)
        request_id_ctx_var.reset(rid_tok)
