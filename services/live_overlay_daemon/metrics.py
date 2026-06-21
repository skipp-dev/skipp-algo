"""Lightweight Prometheus text-format renderer.

Exposes all in-process counters from observability._counters plus feed health
counters, overlay state gauges, and timing metrics without pulling in the
heavyweight prometheus_client dependency.

Single-worker deployment (uvicorn --workers 1) guarantees these in-process
values are consistent and complete.
"""
from __future__ import annotations

import math
import time

from . import cache, config, feed, observability
from .market_hours import compute_daemon_health_status, is_us_regular_session_open


def _sanitize_name(name: str) -> str:
    """Convert dotted metric names to Prometheus-safe underscore format."""
    return name.replace(".", "_").replace("-", "_")


def _prom_numeric_value(raw: object) -> float:
    """Coerce metric value to a Prometheus-safe finite number (fallback: NaN)."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float("nan")
    return value if math.isfinite(value) else float("nan")


def render_metrics(startup_ts: float) -> str:
    """Return Prometheus text-format exposition of all daemon metrics."""
    lines: list[str] = []

    # --- Counters from observability ---
    with observability._counter_lock:
        counters = dict(observability._counters)

    for name, value in sorted(counters.items()):
        prom_name = _sanitize_name(name)
        lines.append(f"# TYPE {prom_name} counter")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    # --- Feed counters ---
    feed_metrics = feed.metrics_snapshot()
    for name, value in sorted(feed_metrics.items()):
        prom_name = f"live_overlay_feed_{_sanitize_name(name)}"
        lines.append(f"# TYPE {prom_name} counter")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    # --- Gauges: overlay health state ---
    uptime = time.monotonic() - startup_ts if startup_ts > 0 else 0
    lines.append("# TYPE live_overlay_uptime_seconds gauge")
    lines.append(f"live_overlay_uptime_seconds {uptime:.1f}")

    overlay_symbols = cache.overlay_symbol_count()
    lines.append("# TYPE live_overlay_overlay_symbols gauge")
    lines.append(f"live_overlay_overlay_symbols {overlay_symbols}")

    bar_symbols = cache.bar_symbol_count()
    lines.append("# TYPE live_overlay_bar_symbols gauge")
    lines.append(f"live_overlay_bar_symbols {bar_symbols}")

    bar_count = cache.total_bar_count()
    lines.append("# TYPE live_overlay_bar_count gauge")
    lines.append(f"live_overlay_bar_count {bar_count}")

    overlay_age = cache.overlay_age_secs()
    if overlay_age != float("inf"):
        lines.append("# TYPE live_overlay_overlay_age_seconds gauge")
        lines.append(f"live_overlay_overlay_age_seconds {overlay_age:.1f}")

    bar_age = feed.last_bar_age_secs()
    if bar_age is not None:
        lines.append("# TYPE live_overlay_last_bar_age_seconds gauge")
        lines.append(f"live_overlay_last_bar_age_seconds {bar_age:.1f}")

    feed_healthy = 1 if feed.is_ready() else 0
    lines.append("# TYPE live_overlay_feed_healthy gauge")
    lines.append(f"live_overlay_feed_healthy {feed_healthy}")

    workers = feed.worker_liveness()
    workers_healthy = 1 if all(workers.values()) else 0
    lines.append("# TYPE live_overlay_workers_healthy gauge")
    lines.append(f"live_overlay_workers_healthy {workers_healthy}")

    # Market/session-aware daemon health state mirrors /health status logic.
    market_open = is_us_regular_session_open()
    max_stale = config.max_stale_secs()
    lines.append("# TYPE live_overlay_max_stale_seconds gauge")
    lines.append(f"live_overlay_max_stale_seconds {max_stale}")
    overlay_fresh = (
        overlay_symbols > 0
        and overlay_age != float("inf")
        and overlay_age <= max_stale
    )
    lines.append("# TYPE live_overlay_overlay_fresh gauge")
    lines.append(f"live_overlay_overlay_fresh {1 if overlay_fresh else 0}")
    status = compute_daemon_health_status(
        feed_healthy=bool(feed_healthy),
        workers_healthy=bool(workers_healthy),
        overlay_fresh=overlay_fresh,
        market_open=market_open,
        bar_count=bar_count,
    )

    lines.append("# TYPE live_overlay_market_open gauge")
    lines.append(f"live_overlay_market_open {1 if market_open else 0}")
    lines.append("# TYPE live_overlay_max_stale_seconds gauge")
    lines.append(f"live_overlay_max_stale_seconds {max_stale}")
    lines.append("# TYPE live_overlay_health_status_ok gauge")
    lines.append(f"live_overlay_health_status_ok {1 if status == 'ok' else 0}")
    lines.append("# TYPE live_overlay_health_status_starting gauge")
    lines.append(f"live_overlay_health_status_starting {1 if status == 'starting' else 0}")
    lines.append("# TYPE live_overlay_health_status_idle_market_closed gauge")
    lines.append(f"live_overlay_health_status_idle_market_closed {1 if status == 'idle_market_closed' else 0}")

    for worker_name, alive in workers.items():
        prom_worker = _sanitize_name(worker_name)
        lines.append(f"# TYPE live_overlay_worker_{prom_worker}_alive gauge")
        lines.append(f"live_overlay_worker_{prom_worker}_alive {1 if alive else 0}")

    lines.append("")  # trailing newline
    return "\n".join(lines)
