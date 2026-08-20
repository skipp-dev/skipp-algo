"""Shared market-hours + daemon health-state helpers."""
from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

try:
    import holidays as _holidays
except Exception:  # pragma: no cover - optional dependency fallback
    _holidays = None

# Set the moment a holiday lookup falls back to "no holidays". The fallback is
# deliberate — a missing calendar must not crash the daemon — but it is
# fail-OPEN: an empty calendar makes Christmas look like a trading day. That
# matters because the session predicates gate the self-heal supervisor, whose
# escalation is os._exit and whose platform budget is three restarts: a wrong
# "market open" can walk the daemon into a nightly outage. So the fallback
# stays, and this flag makes it audible.
# Ein Dict statt eines Modul-Skalars: der Zustand wird aus einer Funktion
# heraus gesetzt, und `global` waere hier eine Ledger-Eintragung wert, die sich
# durch einen Container vermeiden laesst.
_holiday_calendar_state = {"degraded": False}


def holiday_calendar_loaded() -> bool:
    """False once any holiday lookup has fallen back to an empty calendar."""
    return not _holiday_calendar_state["degraded"]


def _note_holiday_calendar_fallback(reason: str) -> None:
    if not _holiday_calendar_state["degraded"]:
        logger.warning(
            "Holiday calendar unavailable (%s) — sessions will treat holidays as "
            "trading days until this is fixed.",
            reason,
        )
    _holiday_calendar_state["degraded"] = True


def _is_weekday(dt: datetime.datetime) -> bool:
    return dt.weekday() < 5


def _is_open_between(
    *,
    now_utc: datetime.datetime,
    zone_name: str,
    start_local: datetime.time,
    end_local: datetime.time,
    holiday_calendar_code: str | None = None,
    early_close_end_local: datetime.time | None = None,
    is_early_close: Callable[[datetime.date], bool] | None = None,
) -> bool:
    """Return whether a local-clock market session is open.

    Market hours must fail closed when IANA timezone data is unavailable. A
    fixed UTC fallback is wrong during part of every year and is especially
    dangerous while US and European DST calendars are temporarily out of
    sync.

    When both ``early_close_end_local`` and ``is_early_close`` are given and
    the local date is an early-close day, the session ends at
    ``early_close_end_local`` instead of ``end_local``.
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
    effective_end = end_local
    if (
        early_close_end_local is not None
        and is_early_close is not None
        and is_early_close(now_local.date())
    ):
        effective_end = early_close_end_local
    current_local = now_local.time()
    return start_local <= current_local < effective_end


@lru_cache(maxsize=64)
def _holiday_dates_for_year(calendar_code: str, year: int) -> frozenset[datetime.date]:
    """Return holiday dates for a calendar/year pair (or empty set on fallback)."""
    if _holidays is None:
        _note_holiday_calendar_fallback("package not importable")
        return frozenset()

    try:
        if calendar_code == "NYSE":
            calendar = _holidays.financial_holidays("NYSE", years=year)
        else:
            calendar = _holidays.country_holidays(calendar_code, years=year)
    except Exception:
        _note_holiday_calendar_fallback(f"lookup failed for {calendar_code}/{year}")
        return frozenset()

    return frozenset(calendar.keys())


def _is_holiday(calendar_code: str, local_date: datetime.date) -> bool:
    """Return True when local_date is a holiday in the selected calendar."""
    return local_date in _holiday_dates_for_year(calendar_code, local_date.year)


# NYSE half-days close at 13:00 ET.
_US_EARLY_CLOSE_LOCAL = datetime.time(13, 0)


def _is_us_early_close(local_date: datetime.date) -> bool:
    """Return True on NYSE 13:00-ET early-close half-days (~3/yr).

    Recurring rule set: July 3, the day after Thanksgiving (always a Friday),
    and December 24 — each only when it falls on a weekday and is not itself
    an observed full holiday. The holiday exclusion handles the shifted
    years: July 4 on a Saturday makes July 3 the observed FULL holiday
    (e.g. 2026), and Christmas on a Saturday does the same to December 24.
    Deliberately NOT lru_cached: it routes through the cached
    _holiday_dates_for_year, and an own cache would freeze monkeypatched
    holiday sets across tests.
    """
    if local_date.weekday() >= 5:
        return False
    year = local_date.year
    if local_date not in (datetime.date(year, 7, 3), datetime.date(year, 12, 24)):
        november_first = datetime.date(year, 11, 1)
        first_thursday = november_first + datetime.timedelta(
            days=(3 - november_first.weekday()) % 7
        )
        thanksgiving = first_thursday + datetime.timedelta(weeks=3)
        if local_date != thanksgiving + datetime.timedelta(days=1):
            return False
    return not _is_holiday("NYSE", local_date)


def us_regular_session_end(local_date: datetime.date) -> datetime.time | None:
    """Return the NYSE regular-session close for a trading date.

    ``None`` means the exchange is closed for the full date. Consumers that
    aggregate exchange-session bars use this alongside the live-open probe so
    holidays and half-days cannot diverge across serving paths.
    """

    if local_date.weekday() >= 5 or _is_holiday("NYSE", local_date):
        return None
    return _US_EARLY_CLOSE_LOCAL if _is_us_early_close(local_date) else datetime.time(16, 0)


def is_us_regular_session_open(now_utc: datetime.datetime | None = None) -> bool:
    """Return True during regular US equities session (Mon-Fri 09:30-16:00 ET).

    NYSE early-close half-days (July 3, day after Thanksgiving, Dec 24 —
    ~3/yr) end at 13:00 ET, so US-gated staleness alerts stand down after the
    real close instead of false-firing until 16:00 (truth-audit 2026-07-22 F-4).
    """
    now_utc = now_utc or datetime.datetime.now(datetime.UTC)
    return _is_open_between(
        now_utc=now_utc,
        zone_name="America/New_York",
        start_local=datetime.time(9, 30),
        end_local=datetime.time(16, 0),
        holiday_calendar_code="NYSE",
        early_close_end_local=_US_EARLY_CLOSE_LOCAL,
        is_early_close=_is_us_early_close,
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


# A non-ok, non-idle state only counts as "starting" while the daemon can
# plausibly still be warming up. 900s is comfortably past a healthy boot (the
# feed connects within seconds; the first full compute is staggered <= 60s
# after start), so a failure that persists beyond it during an open US
# session is a sustained outage, not boot noise.
_DEGRADED_MIN_UPTIME_SECS = 900.0


def compute_daemon_health_status(
    *,
    feed_healthy: bool,
    workers_healthy: bool,
    overlay_fresh: bool,
    market_open: bool,
    bar_count: int,
    uptime_secs: float | None = None,
) -> str:
    """Compute daemon status string used by /ready and /metrics gauges.

    ``uptime_secs=None`` (uptime unknown) never yields "degraded": a caller
    that cannot say how long the daemon has been up keeps the conservative
    "starting" label instead of reporting a fresh boot as an outage.
    """
    if feed_healthy and workers_healthy and overlay_fresh:
        return "ok"
    if (not market_open) and workers_healthy and (not feed_healthy) and bar_count == 0:
        # Expected idle state outside regular market session before first bar.
        return "idle_market_closed"
    if (
        market_open
        and uptime_secs is not None
        and uptime_secs >= _DEGRADED_MIN_UPTIME_SECS
    ):
        # Long past warmup during an open US session: a dead feed, stale
        # overlay or dead worker at this point is a sustained outage. Before
        # this state existed, a multi-hour market-open outage read as a
        # perpetual "starting" on every dashboard (truth-audit 2026-07-22 F-3).
        return "degraded"
    return "starting"
