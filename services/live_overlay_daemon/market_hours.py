"""Shared market-hours + daemon health-state helpers."""
from __future__ import annotations

import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    import holidays as _holidays
except Exception:  # pragma: no cover - optional dependency fallback
    _holidays = None


def _is_weekday(dt: datetime.datetime) -> bool:
    return dt.weekday() < 5


def _is_open_between(
    *,
    now_utc: datetime.datetime,
    zone_name: str,
    start_local: datetime.time,
    end_local: datetime.time,
    fallback_start_utc: datetime.time,
    fallback_end_utc: datetime.time,
    holiday_calendar_code: str | None = None,
) -> bool:
    """Return whether local market session is open with UTC fallback."""
    try:
        local_tz = ZoneInfo(zone_name)
        now_local = now_utc.astimezone(local_tz)
    except ZoneInfoNotFoundError:
        if now_utc.weekday() >= 5:
            return False
        current_utc = now_utc.time()
        return fallback_start_utc <= current_utc < fallback_end_utc

    if not _is_weekday(now_local):
        return False
    if holiday_calendar_code and _is_holiday(holiday_calendar_code, now_local.date()):
        return False
    current_local = now_local.time()
    return start_local <= current_local < end_local


@lru_cache(maxsize=64)
def _holiday_dates_for_year(calendar_code: str, year: int) -> frozenset[datetime.date]:
    """Return holiday dates for a calendar/year pair (or empty set on fallback)."""
    if _holidays is None:
        return frozenset()

    try:
        if calendar_code == "NYSE":
            calendar = _holidays.financial_holidays("NYSE", years=year)
        else:
            calendar = _holidays.country_holidays(calendar_code, years=year)
    except Exception:
        return frozenset()

    return frozenset(calendar.keys())


def _is_holiday(calendar_code: str, local_date: datetime.date) -> bool:
    """Return True when local_date is a holiday in the selected calendar."""
    return local_date in _holiday_dates_for_year(calendar_code, local_date.year)


def is_us_regular_session_open(now_utc: datetime.datetime | None = None) -> bool:
    """Return True during regular US equities session (Mon-Fri, 09:30-16:00 ET)."""
    now_utc = now_utc or datetime.datetime.now(datetime.UTC)
    return _is_open_between(
        now_utc=now_utc,
        zone_name="America/New_York",
        start_local=datetime.time(9, 30),
        end_local=datetime.time(16, 0),
        fallback_start_utc=datetime.time(13, 30),
        fallback_end_utc=datetime.time(20, 0),
        holiday_calendar_code="NYSE",
    )


def is_europe_regular_session_open(now_utc: datetime.datetime | None = None) -> bool:
    """Return True during regular Europe session proxy (Mon-Fri, 08:00-16:30 London)."""
    now_utc = now_utc or datetime.datetime.now(datetime.UTC)
    return _is_open_between(
        now_utc=now_utc,
        zone_name="Europe/London",
        start_local=datetime.time(8, 0),
        end_local=datetime.time(16, 30),
        fallback_start_utc=datetime.time(8, 0),
        fallback_end_utc=datetime.time(16, 30),
        holiday_calendar_code="GB",
    )


def is_asia_regular_session_open(now_utc: datetime.datetime | None = None) -> bool:
    """Return True during regular Asia session proxy (Mon-Fri, 09:00-15:00 Tokyo)."""
    now_utc = now_utc or datetime.datetime.now(datetime.UTC)
    return _is_open_between(
        now_utc=now_utc,
        zone_name="Asia/Tokyo",
        start_local=datetime.time(9, 0),
        end_local=datetime.time(15, 0),
        fallback_start_utc=datetime.time(0, 0),
        fallback_end_utc=datetime.time(6, 0),
        holiday_calendar_code="JP",
    )


def is_any_regular_session_open(now_utc: datetime.datetime | None = None) -> bool:
    """Return True when any major covered session (US or Europe) is open.

    Used for the operator-facing ``live_overlay_market_open`` display gauge so the
    dashboard does not show MARKET CLOSED while European exchanges trade ahead of
    the US session. Feed/traffic/SLO gating stays bound to the US session via
    ``is_us_regular_session_open`` because the upstream feed is US equities.
    """
    now_utc = now_utc or datetime.datetime.now(datetime.UTC)
    return is_us_regular_session_open(now_utc) or is_europe_regular_session_open(now_utc)


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
