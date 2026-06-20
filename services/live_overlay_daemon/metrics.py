"""Lightweight Prometheus text-format renderer.

Exposes all in-process counters from observability._counters plus feed health
counters, overlay state gauges, and timing metrics without pulling in the
heavyweight prometheus_client dependency.

Single-worker deployment (uvicorn --workers 1) guarantees these in-process
values are consistent and complete.
"""
from __future__ import annotations

import datetime
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import cache, config, feed, observability


def _sanitize_name(name: str) -> str:
    """Convert dotted metric names to Prometheus-safe underscore format."""
    return name.replace(".", "_").replace("-", "_")


def _is_us_regular_session_open(now_utc: datetime.datetime | None = None) -> bool:
    """Return True during regular US equities session (Mon-Fri, 09:30-16:00 ET)."""
    now_utc = now_utc or datetime.datetime.now(datetime.UTC)
    try:
        ny_tz = ZoneInfo("America/New_York")
        now_ny = now_utc.astimezone(ny_tz)
    except ZoneInfoNotFoundError:
        # Conservative UTC fallback if timezone database is unavailable.
        # 13:30-20:00 UTC approximates 09:30-16:00 ET during DST.
        if now_utc.weekday() >= 5:
            return False
        current_utc = now_utc.time()
        return datetime.time(13, 30) <= current_utc < datetime.time(20, 0)

    if now_ny.weekday() >= 5:
        return False
    current_ny = now_ny.time()
    return datetime.time(9, 30) <= current_ny < datetime.time(16, 0)


def render_metrics(startup_ts: float) -> str:
    """Return Prometheus text-format exposition of all daemon metrics."""
    lines: list[str] = []

    # --- Counters from observability ---
    with observability._counter_lock:
        counters = dict(observability._counters)

    for name, value in sorted(counters.items()):
        prom_name = _sanitize_name(name)
        lines.append(f"# TYPE {prom_name} counter")
        lines.append(f"{prom_name} {value}")

    # --- Feed counters ---
    feed_metrics = feed.metrics_snapshot()
    for name, value in sorted(feed_metrics.items()):
        prom_name = f"live_overlay_feed_{_sanitize_name(name)}"
        lines.append(f"# TYPE {prom_name} counter")
        lines.append(f"{prom_name} {value}")

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
    market_open = _is_us_regular_session_open()
    max_stale = config.max_stale_secs()
    overlay_fresh = (
        overlay_symbols > 0
        and overlay_age != float("inf")
        and overlay_age <= max_stale
    )
    if feed_healthy and workers_healthy and overlay_fresh:
        status = "ok"
    elif (not market_open) and workers_healthy and (not feed_healthy) and bar_count == 0:
        status = "idle_market_closed"
    else:
        status = "starting"

    lines.append("# TYPE live_overlay_market_open gauge")
    lines.append(f"live_overlay_market_open {1 if market_open else 0}")
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
