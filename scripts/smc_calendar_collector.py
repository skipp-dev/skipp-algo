"""Earnings calendar and macro-event collector for SMC micro-profile generation.

Pure stdlib implementation — no open_prep or external dependencies.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

# Macro events considered high-impact
_HIGH_IMPACT_PATTERNS = re.compile(
    r"\b(fomc|cpi|nonfarm|nfp|ppi|ism|gdp|jobless\s+claims|fed\s+chair)\b",
    re.IGNORECASE,
)

_ET = ZoneInfo("America/New_York")


def _parse_date(raw: Any) -> date | None:
    """Best-effort parse of a date string or date object."""
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if not isinstance(raw, str) or not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_event_dt(raw: Any) -> datetime | None:
    """Parse an ISO-ish datetime string to a timezone-aware datetime."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str) or not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _format_et(dt: datetime) -> str:
    """Format a datetime as 'HH:MM ET' using America/New_York (DST-aware)."""
    et = dt.astimezone(_ET)
    return et.strftime("%H:%M ET")


def collect_earnings_and_macro(
    symbols: list[str],
    earnings_data: list[dict[str, Any]] | None = None,
    macro_events: list[dict[str, Any]] | None = None,
    *,
    reference_date: date | None = None,
    next_trading_date: date | None = None,
) -> dict[str, Any]:
    """Collect earnings and macro calendar data for library generation.

    Parameters
    ----------
    symbols:
        Ticker universe — only earnings for these symbols are included.
    earnings_data:
        Rows with ``symbol``, ``date``, ``timing`` (``"bmo"``/``"amc"``).
    macro_events:
        Rows with ``name``, ``time_utc``, ``impact`` (optional).
    reference_date:
        Override "today" for deterministic testing.
    next_trading_date:
        Override the "tomorrow" reference. When omitted, falls back to the
        next US equity trading day after ``reference_date`` (skips weekends
        and US market holidays). The naive ``today + 1 day`` would land on
        Saturday for any Friday call and silently emit an empty
        ``earnings_tomorrow_tickers`` set.
    """
    # Anchor "today" in US/Eastern (the trading-day timezone) instead of the
    # server's local clock. On a UTC server, ``date.today()`` advances at
    # 00:00 UTC — i.e. 20:00 ET (EDT) the previous day — which silently
    # rolls earnings into ``earnings_tomorrow_tickers`` for ~4 hours every
    # night. Tested via ``test_today_anchored_on_us_eastern``.
    today = reference_date or datetime.now(_ET).date()

    if next_trading_date is not None:
        tomorrow = next_trading_date
    else:
        try:
            from newsstack_fmp._market_cal import next_trading_day as _next_td

            tomorrow = _next_td(today)
        except Exception:
            from datetime import timedelta as _td

            tomorrow = today + _td(days=1)
    universe = {s.upper() for s in symbols}

    earnings_today: list[str] = []
    earnings_tomorrow: list[str] = []
    bmo: list[str] = []
    amc: list[str] = []

    for row in earnings_data or []:
        sym = (row.get("symbol") or "").upper()
        if sym not in universe:
            continue
        d = _parse_date(row.get("date"))
        if d is None:
            continue
        timing = (row.get("timing") or "").lower()
        if d == today:
            earnings_today.append(sym)
            if timing == "bmo":
                bmo.append(sym)
            elif timing == "amc":
                amc.append(sym)
        elif d == tomorrow:
            earnings_tomorrow.append(sym)

    # Macro events
    high_impact = False
    macro_name = ""
    macro_time = ""
    nearest_dt: datetime | None = None

    for evt in macro_events or []:
        name = evt.get("name") or ""
        evt_dt = _parse_event_dt(evt.get("time_utc"))
        # Anchor the event date in US/Eastern before comparing with
        # ``today`` (which is also ET). Otherwise an event at 00:30 UTC
        # (= 20:30 ET previous day) would match ``today`` purely by UTC
        # date arithmetic and surface as a "today" event when in trading
        # terms it already happened yesterday.
        if evt_dt is not None and evt_dt.astimezone(_ET).date() != today:
            continue
        is_high = bool(_HIGH_IMPACT_PATTERNS.search(name))
        if not is_high:
            continue
        # Pick the earliest high-impact event today
        if nearest_dt is None or (evt_dt is not None and evt_dt < nearest_dt):
            high_impact = True
            macro_name = name
            nearest_dt = evt_dt
            macro_time = _format_et(evt_dt) if evt_dt else ""

    return {
        "earnings_today_tickers": ",".join(sorted(set(earnings_today))),
        "earnings_tomorrow_tickers": ",".join(sorted(set(earnings_tomorrow))),
        "earnings_bmo_tickers": ",".join(sorted(set(bmo))),
        "earnings_amc_tickers": ",".join(sorted(set(amc))),
        "high_impact_macro_today": high_impact,
        "macro_event_name": macro_name,
        "macro_event_time": macro_time,
    }
