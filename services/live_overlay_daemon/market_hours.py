"""Shared market-hours + daemon health-state helpers."""
from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def is_us_regular_session_open(now_utc: datetime.datetime | None = None) -> bool:
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


def compute_daemon_health_status(
    *,
    feed_healthy: bool,
    workers_healthy: bool,
    overlay_fresh: bool,
    market_open: bool,
    bar_count: int,
) -> str:
    """Compute daemon status string used by /health and /metrics gauges."""
    if feed_healthy and workers_healthy and overlay_fresh:
        return "ok"
    if (not market_open) and workers_healthy and (not feed_healthy) and bar_count == 0:
        # Expected idle state outside regular market session before first bar.
        return "idle_market_closed"
    return "starting"
