"""Lightweight observability primitives for live_overlay_daemon.

This module intentionally uses structured log lines as the transport so tests
can assert behavior via pytest's caplog without introducing external telemetry
dependencies.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_counter_lock = threading.Lock()
_counters: dict[str, float] = {}


def _kv(fields: dict[str, Any]) -> str:
    if not fields:
        return ""
    parts = [f"{k}={fields[k]}" for k in sorted(fields)]
    return " ".join(parts)


def metric_counter(name: str, value: float = 1.0, **fields: Any) -> float:
    """Record a counter metric and emit a structured log line."""
    with _counter_lock:
        total = _counters.get(name, 0.0) + float(value)
        _counters[name] = total
    extra = _kv(fields)
    logger.info(
        "metric kind=counter name=%s value=%s total=%s%s%s",
        name,
        value,
        total,
        " " if extra else "",
        extra,
    )
    return total


def metric_gauge(name: str, value: float, **fields: Any) -> None:
    """Record a gauge metric via structured logging."""
    extra = _kv(fields)
    logger.info(
        "metric kind=gauge name=%s value=%s%s%s",
        name,
        value,
        " " if extra else "",
        extra,
    )


def metric_timing_ms(name: str, value_ms: float, **fields: Any) -> None:
    """Record a duration metric in milliseconds via structured logging."""
    extra = _kv(fields)
    logger.info(
        "metric kind=timing_ms name=%s value=%0.3f%s%s",
        name,
        value_ms,
        " " if extra else "",
        extra,
    )


def trace_event(name: str, phase: str, trace_id: str | None = None, **fields: Any) -> str:
    """Emit a trace event and return the trace id used for the event."""
    tid = trace_id or uuid.uuid4().hex[:16]
    payload = {"trace_id": tid, **fields}
    extra = _kv(payload)
    logger.info("trace name=%s phase=%s%s%s", name, phase, " " if extra else "", extra)
    return tid


def audit_event(event: str, outcome: str, **fields: Any) -> None:
    """Emit an audit event as a structured log line."""
    extra = _kv(fields)
    logger.info(
        "audit event=%s outcome=%s%s%s",
        event,
        outcome,
        " " if extra else "",
        extra,
    )


@contextmanager
def trace_span(name: str, **fields: Any) -> Iterator[str]:
    """Context manager that emits trace start/end and timing metric."""
    trace_id = trace_event(name, "start", **fields)
    t0 = time.monotonic()
    outcome = "ok"
    try:
        yield trace_id
    except Exception:
        outcome = "error"
        raise
    finally:
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        metric_timing_ms(f"{name}.duration_ms", elapsed_ms, outcome=outcome)
        trace_event(name, "end", trace_id=trace_id, outcome=outcome)
