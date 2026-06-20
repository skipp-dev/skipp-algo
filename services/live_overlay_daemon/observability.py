"""Lightweight observability primitives for live_overlay_daemon.

This module intentionally uses structured log lines as the transport so tests
can assert behavior via pytest's caplog without introducing external telemetry
dependencies.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_counter_lock = threading.Lock()
_counters: dict[str, float] = {}
_HISTOGRAM_DEFAULT_BUCKETS_MS: tuple[float, ...] = (
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1000.0,
    2500.0,
    5000.0,
)


def _kv(fields: dict[str, Any]) -> str:
    if not fields:
        return ""
    parts = [f"{k}={_field_value(fields[k])}" for k in sorted(fields)]
    return " ".join(parts)


def _field_value(value: Any) -> str:
    """Return a single-token field value for space-delimited structured logs."""
    text = str(value)
    return (
        text.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace(" ", "\\s")
    )


def _coerce_finite_metric_value(value: float, *, metric_name: str) -> float:
    """Coerce to float and reject non-finite metric values."""
    coerced = float(value)
    if not math.isfinite(coerced):
        raise ValueError(f"metric '{metric_name}' value must be finite, got {coerced!r}")
    return coerced


def _bucket_suffix(value: float) -> str:
    """Return a Prometheus-safe bucket suffix for metric key names."""
    text = f"{value:.9f}".rstrip("0").rstrip(".")
    if not text:
        text = "0"
    text = text.replace(".", "_")
    return re.sub(r"[^0-9_]", "_", text)


def metric_counter(name: str, value: float = 1.0, **fields: Any) -> float:
    """Record a counter metric and emit a structured log line."""
    inc = _coerce_finite_metric_value(value, metric_name=name)
    with _counter_lock:
        base = _coerce_finite_metric_value(_counters.get(name, 0.0), metric_name=name)
        total = _coerce_finite_metric_value(base + inc, metric_name=name)
        _counters[name] = total
    extra = _kv(fields)
    logger.info(
        "metric kind=counter name=%s value=%s total=%s%s%s",
        name,
        inc,
        total,
        " " if extra else "",
        extra,
    )
    return total


def metric_histogram_ms(
    name: str,
    value_ms: float,
    *,
    buckets_ms: tuple[float, ...] | None = None,
    **fields: Any,
) -> None:
    """Record a histogram-like metric using cumulative counter series.

    The lightweight renderer exposes only flat counter names (no label sets),
    so buckets are represented as suffixed counters:
      - ``{name}.count``
      - ``{name}.sum_ms``
      - ``{name}.bucket_le_<N>`` (cumulative)
      - ``{name}.bucket_le_inf``
    """
    finite_ms = _coerce_finite_metric_value(value_ms, metric_name=name)
    chosen = buckets_ms or _HISTOGRAM_DEFAULT_BUCKETS_MS
    finite_bucket_set: set[float] = set()
    for bucket in chosen:
        coerced_bucket = _coerce_finite_metric_value(bucket, metric_name=f"{name}.bucket")
        if coerced_bucket >= 0.0:
            finite_bucket_set.add(coerced_bucket)
    finite_buckets = tuple(sorted(finite_bucket_set))

    with _counter_lock:
        _counters[f"{name}.count"] = _coerce_finite_metric_value(
            _counters.get(f"{name}.count", 0.0) + 1.0,
            metric_name=f"{name}.count",
        )
        _counters[f"{name}.sum_ms"] = _coerce_finite_metric_value(
            _counters.get(f"{name}.sum_ms", 0.0) + finite_ms,
            metric_name=f"{name}.sum_ms",
        )
        for bucket in finite_buckets:
            if finite_ms <= bucket:
                suffix = _bucket_suffix(bucket)
                key = f"{name}.bucket_le_{suffix}"
                _counters[key] = _coerce_finite_metric_value(
                    _counters.get(key, 0.0) + 1.0,
                    metric_name=key,
                )
        inf_key = f"{name}.bucket_le_inf"
        _counters[inf_key] = _coerce_finite_metric_value(
            _counters.get(inf_key, 0.0) + 1.0,
            metric_name=inf_key,
        )

    extra = _kv(fields)
    logger.info(
        "metric kind=histogram_ms name=%s value=%0.3f%s%s",
        name,
        finite_ms,
        " " if extra else "",
        extra,
    )


def metric_gauge(name: str, value: float, **fields: Any) -> None:
    """Record a gauge metric via structured logging."""
    finite_value = _coerce_finite_metric_value(value, metric_name=name)
    extra = _kv(fields)
    logger.info(
        "metric kind=gauge name=%s value=%s%s%s",
        name,
        finite_value,
        " " if extra else "",
        extra,
    )


def metric_timing_ms(name: str, value_ms: float, **fields: Any) -> None:
    """Record a duration metric in milliseconds via structured logging."""
    finite_ms = _coerce_finite_metric_value(value_ms, metric_name=name)
    extra = _kv(fields)
    logger.info(
        "metric kind=timing_ms name=%s value=%0.3f%s%s",
        name,
        finite_ms,
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
