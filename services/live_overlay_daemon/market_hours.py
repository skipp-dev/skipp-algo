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
    holiday_calendar_code: str | None = None,
) -> bool:
    """Return whether a local-clock market session is open.

    Market hours must fail closed when IANA timezone data is unavailable. A
    fixed UTC fallback is wrong during part of every year and is especially
    dangerous while US and European DST calendars are temporarily out of
    sync.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    try:
        local_tz = ZoneInfo(zone_name)
        now_local = now_utc.astimezone(local_tz)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(
            f"IANA timezone {zone_name!r} is unavailable; install tzdata. "
            "Refusing a fixed UTC market-hours fallback because DST rules differ by region."
        ) from exc

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
    """Return True during regular US equities session (Mon-Fri 09:30-16:00 ET). Known limitation: NYSE early-close half-days (~3/yr) are treated as full sessions — the gauge stays 1 until 16:00, so US-gated staleness alerts can fire on those afternoons."""
    now_utc = now_utc or datetime.datetime.now(datetime.UTC)
    return _is_open_between(
        now_utc=now_utc,
        zone_name="America/New_York",
        start_local=datetime.time(9, 30),
        end_local=datetime.time(16, 0),
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
        holiday_calendar_code="JP",
    )


def compute_daemon_health_status(
    *,
    feed_healthy: bool,
    workers_healthy: bool,
    overlay_fresh: bool,
    market_open: bool,
    bar_count: int,
) -> str:
    """Compute daemon status string used by /ready and /metrics gauges."""
    if feed_healthy and workers_healthy and overlay_fresh:
        return "ok"
    if (not market_open) and workers_healthy and (not feed_healthy) and bar_count == 0:
        # Expected idle state outside regular market session before first bar.
        return "idle_market_closed"
    return "starting"
