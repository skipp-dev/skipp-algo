from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from .trade_cards import build_trade_cards
from .bea import build_bea_audit_payload
from .macro import (
    FMPClient,
    dedupe_events,
    filter_us_events,
    filter_us_high_impact_events,
    filter_us_mid_impact_events,
    get_consensus,
    macro_bias_with_components,
)
from .news import build_news_scores
from .screen import rank_candidates
from .utils import to_float as _to_float

logger = logging.getLogger("open_prep.run")

DEFAULT_UNIVERSE = [
    "NVDA",
    "PLTR",
    "PWR",
    "TSLA",
    "AMD",
    "META",
    "MSFT",
    "AMZN",
    "GOOGL",
    "SMCI",
]

PREFERRED_US_OPEN_UTC_TIMES: tuple[str, ...] = ("13:30:00", "14:30:00", "15:00:00")
US_EASTERN_TZ = ZoneInfo("America/New_York")
HVB_MULTIPLIER = 1.5
GAP_MODE_RTH_OPEN = "RTH_OPEN"
GAP_MODE_PREMARKET_INDICATIVE = "PREMARKET_INDICATIVE"
GAP_MODE_OFF = "OFF"
GAP_MODE_CHOICES: tuple[str, ...] = (
    GAP_MODE_RTH_OPEN,
    GAP_MODE_PREMARKET_INDICATIVE,
    GAP_MODE_OFF,
)


@dataclass(frozen=True)
class OpenPrepConfig:
    symbols: list[str]
    days_ahead: int = 3
    top: int = 10
    trade_cards: int = 5
    max_macro_events: int = 15
    pre_open_only: bool = False
    pre_open_cutoff_utc: str = "16:00:00"
    gap_mode: str = GAP_MODE_PREMARKET_INDICATIVE
    atr_lookback_days: int = 250
    atr_period: int = 14
    atr_parallel_workers: int = 5


def _extract_time_str(event_date: str) -> str:
    """Extract HH:MM:SS time component from a date string.

    Handles both space-separated ("YYYY-MM-DD HH:MM:SS") and
    ISO-8601 T-separated ("YYYY-MM-DDTHH:MM:SS") formats.
    Returns "99:99:99" when no time component is found (whole-day events).
    """
    for sep in (" ", "T"):
        idx = event_date.find(sep)
        if idx != -1:
            time_part = event_date[idx + 1 :].strip()
            match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?", time_part)
            if not match:
                continue

            hour = int(match.group(1))
            minute = int(match.group(2))
            second_str = match.group(3)
            second = int(second_str) if second_str is not None else 0
            if 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59:
                return f"{hour:02d}:{minute:02d}:{second:02d}"
    return "99:99:99"


def _macro_relevance_score(event_name: str) -> int:
    name = event_name.lower()
    score = 0

    # Rates/inflation/labor shocks first.
    if any(token in name for token in ("cpi", "ppi", "pce", "nonfarm payroll", "jobless claims")):
        score += 30
    # Growth pulse tier.
    elif any(token in name for token in ("gdp", "ism", "retail sales", "consumer sentiment")):
        score += 20
    # Housing and secondary surveys.
    elif any(token in name for token in ("home sales", "housing", "durable goods", "factory orders")):
        score += 10

    return score


def _sort_macro_events(events: list[dict]) -> list[dict]:
    def key_fn(event: dict) -> tuple[int, int, int, str, str]:
        impact_raw = str(event.get("impact", event.get("importance", event.get("priority"))) or "").lower()
        impact_rank = 2 if impact_raw == "high" else 1 if impact_raw in {"medium", "mid", "moderate"} else 0

        date_str = str(event.get("date") or "")
        time_str = _extract_time_str(date_str)
        open_time_rank = 1 if time_str in PREFERRED_US_OPEN_UTC_TIMES else 0

        name = str(event.get("event") or event.get("name") or "")
        relevance = _macro_relevance_score(name)

        # Desc for impact/open-time/relevance, asc for date+name (stable tiebreaker).
        return (-impact_rank, -open_time_rank, -relevance, date_str, name.lower())

    return sorted(events, key=key_fn)


def _filter_events_by_cutoff_utc(
    events: list[dict], cutoff_utc: str, include_untimed: bool = True
) -> list[dict]:
    """Keep events whose time component is <= cutoff_utc (HH:MM:SS).

    Events without a time component in their date field are treated as
    whole-day releases and included by default (include_untimed=True),
    so day-scope macro announcements are never silently dropped.
    Both space-separated and ISO T-separated date strings are handled.
    """
    out: list[dict] = []
    cutoff = _normalize_cutoff_utc(cutoff_utc)

    for event in events:
        date_str = str(event.get("date") or "")
        time_str = _extract_time_str(date_str)
        if time_str == "99:99:99":
            # No intraday timestamp — treat as a whole-day release.
            if include_untimed:
                out.append(event)
            continue
        if time_str <= cutoff:
            out.append(event)
    return out


def _normalize_cutoff_utc(cutoff_utc: str) -> str:
    """Validate and normalize cutoff time to HH:MM:SS."""
    raw = str(cutoff_utc or "").strip()
    parts = raw.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError("Expected HH:MM or HH:MM:SS")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError as exc:
        raise ValueError("Expected numeric HH:MM or HH:MM:SS") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError("Time parts out of range (HH 0-23, MM/SS 0-59)")

    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build macro-aware long-breakout candidates ahead of US open."
    )
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_UNIVERSE),
        help="Comma-separated ticker universe.",
    )
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=3,
        help="How many calendar days to scan for macro events.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many ranked candidates to keep.",
    )
    parser.add_argument(
        "--trade-cards",
        type=int,
        default=5,
        help="How many trade cards to generate from top ranked names.",
    )
    parser.add_argument(
        "--max-macro-events",
        type=int,
        default=15,
        help="Maximum number of macro events to include per output list.",
    )
    parser.add_argument(
        "--pre-open-only",
        action="store_true",
        help="If set, only include today's events up to the cutoff UTC time.",
    )
    parser.add_argument(
        "--pre-open-cutoff-utc",
        type=str,
        default="16:00:00",
        help="UTC cutoff (HH:MM:SS) used with --pre-open-only, default 16:00:00.",
    )
    parser.add_argument(
        "--gap-mode",
        type=str,
        choices=list(GAP_MODE_CHOICES),
        default=GAP_MODE_PREMARKET_INDICATIVE,
        help=(
            "How to compute Monday gap: RTH_OPEN (official Monday RTH open only), "
            "PREMARKET_INDICATIVE (Monday premarket indication), OFF (no Monday gap)."
        ),
    )
    parser.add_argument(
        "--atr-lookback-days",
        type=int,
        default=250,
        help="How many calendar days of EOD data to request for ATR calculation.",
    )
    parser.add_argument(
        "--atr-period",
        type=int,
        default=14,
        help="ATR period used for Wilder RMA ATR calculation.",
    )
    parser.add_argument(
        "--atr-parallel-workers",
        type=int,
        default=5,
        help="Maximum parallel workers for ATR historical fetch requests.",
    )
    return parser.parse_args()


def _event_is_today(event: dict, today: date) -> bool:
    """Match an event to today regardless of whether FMP returns ISO or US-style dates."""
    date_str = str(event.get("date") or "")
    # ISO: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS...
    if date_str.startswith(today.isoformat()):
        return True
    # US format: MM/DD/YYYY [HH:MM:SS]
    date_part = date_str.split(" ")[0]
    parts = date_part.split("/")
    if len(parts) == 3:
        try:
            year = int(parts[2])
            if year < 100:
                year += 2000
            return date(year, int(parts[0]), int(parts[1])) == today
        except ValueError:
            pass
    return False


def _format_macro_events(events: list[dict], max_events: int) -> list[dict]:
    out: list[dict] = []
    for event in _sort_macro_events(events)[: max(max_events, 0)]:
        consensus_value, consensus_field = get_consensus(event)
        # Compute quality flags inline (same logic as macro._annotate_event_quality)
        # to avoid depending on mutation side-effects.
        quality_flags: list[str] = []
        if event.get("actual") is None:
            quality_flags.append("missing_actual")
        if consensus_value is None:
            quality_flags.append("missing_consensus")
        if not event.get("unit"):
            quality_flags.append("missing_unit")
        out.append(
            {
                "date": event.get("date"),
                "event": event.get("event") or event.get("name"),
                "canonical_event": event.get("canonical_event"),
                "impact": event.get("impact", event.get("importance", event.get("priority"))),
                "actual": event.get("actual"),
                "consensus": consensus_value,
                "consensus_field": consensus_field,
                "previous": event.get("previous"),
                "unit": event.get("unit"),
                "data_quality_flags": quality_flags,
                "dedup": event.get("dedup"),
                "country": event.get("country"),
                "currency": event.get("currency"),
            }
        )
    return out


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (n - 1) * 7)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:  # Saturday -> observed Friday
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:  # Sunday -> observed Monday
        return holiday + timedelta(days=1)
    return holiday


def _easter_sunday(year: int) -> date:
    """Return Gregorian Easter Sunday for year (Meeus/Jones/Butcher algorithm)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=16)
def _us_equity_market_holidays(year: int) -> set[date]:
    """NYSE full-day holiday set (core schedule, excludes special closures)."""
    good_friday = _easter_sunday(year) - timedelta(days=2)
    return {
        _observed_fixed_holiday(year, 1, 1),      # New Year's Day
        _nth_weekday_of_month(year, 1, 0, 3),     # Martin Luther King Jr. Day
        _nth_weekday_of_month(year, 2, 0, 3),     # Presidents Day
        good_friday,
        _last_weekday_of_month(year, 5, 0),       # Memorial Day
        _observed_fixed_holiday(year, 6, 19),     # Juneteenth
        _observed_fixed_holiday(year, 7, 4),      # Independence Day
        _nth_weekday_of_month(year, 9, 0, 1),     # Labor Day
        _nth_weekday_of_month(year, 11, 3, 4),    # Thanksgiving
        _observed_fixed_holiday(year, 12, 25),    # Christmas Day
    }


def _is_us_equity_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in _us_equity_market_holidays(d.year)


def _prev_trading_day(d: date) -> date:
    cur = d - timedelta(days=1)
    while not _is_us_equity_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def _is_first_session_after_non_trading_stretch(d: date) -> bool:
    if not _is_us_equity_trading_day(d):
        return False
    prev_day = _prev_trading_day(d)
    return (d - prev_day).days > 1


def _to_iso_utc_from_epoch(value: Any) -> str | None:
    try:
        if value is None:
            return None
        ts = float(value)
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _classify_session(run_dt_utc: datetime) -> str:
    ny_now = run_dt_utc.astimezone(US_EASTERN_TZ)
    t = ny_now.hour * 60 + ny_now.minute
    if 570 <= t < 630:   # 09:30–10:30
        return "NY_AM_PRIME"
    if 780 <= t < 840:   # 13:00–14:00
        return "NY_LUNCH"
    if 810 <= t < 960:   # 13:30–16:00
        return "NY_PM"
    if 120 <= t < 300:   # 02:00–05:00
        return "LONDON"
    return "OFF_HOURS"


def _momentum_z_score_from_eod(candles: list[dict], period: int = 50) -> float:
    closes: list[float] = []
    rows: list[tuple[str, float]] = []
    for candle in candles:
        d = str(candle.get("date") or "")
        close = _to_float(candle.get("close"), default=float("nan"))
        if d and close == close and close > 0.0:  # NaN-safe check
            rows.append((d, close))
    if len(rows) < 3:
        return 0.0

    rows.sort(key=lambda x: x[0])
    closes = [c for _, c in rows]
    returns: list[float] = []
    for idx in range(1, len(closes)):
        prev = closes[idx - 1]
        cur = closes[idx]
        if prev <= 0.0:
            continue
        returns.append((cur - prev) / prev)

    if len(returns) < 2:
        return 0.0

    window = returns[-max(int(period), 2):]
    if len(window) < 2:
        return 0.0
    mean_ret = sum(window) / float(len(window))
    variance = sum((r - mean_ret) ** 2 for r in window) / float(len(window))
    std_ret = variance**0.5
    if std_ret <= 0.0:
        return 0.0

    z = (window[-1] - mean_ret) / std_ret
    return round(max(min(z, 5.0), -5.0), 4)


def _enrich_quote_with_hvb(quote: dict[str, Any], hvb_multiplier: float = HVB_MULTIPLIER) -> None:
    avg_vol = _to_float(quote.get("avgVolume"), default=0.0)
    current_vol = _to_float(quote.get("volume"), default=0.0)
    ratio = (current_vol / avg_vol) if avg_vol > 0.0 else 0.0
    quote["volume_ratio"] = round(ratio, 4)
    quote["is_hvb"] = bool(avg_vol > 0.0 and current_vol > (hvb_multiplier * avg_vol))


def _add_pdh_pdl_context(quote: dict[str, Any]) -> None:
    price = _to_float(quote.get("price"), default=0.0)
    atr = _to_float(quote.get("atr"), default=0.0)

    pdh_source = next(
        (k for k in ("previousDayHigh", "prevDayHigh", "pdh", "dayHigh") if _to_float(quote.get(k), default=0.0) > 0.0),
        None,
    )
    pdl_source = next(
        (k for k in ("previousDayLow", "prevDayLow", "pdl", "dayLow") if _to_float(quote.get(k), default=0.0) > 0.0),
        None,
    )
    pdh = _to_float(quote.get(pdh_source), default=0.0) if pdh_source else 0.0
    pdl = _to_float(quote.get(pdl_source), default=0.0) if pdl_source else 0.0

    quote["pdh"] = round(pdh, 4) if pdh > 0.0 else None
    quote["pdl"] = round(pdl, 4) if pdl > 0.0 else None
    quote["pdh_source"] = pdh_source
    quote["pdl_source"] = pdl_source

    if price > 0.0 and atr > 0.0 and pdh > 0.0:
        quote["dist_to_pdh_atr"] = round(abs(price - pdh) / atr, 4)
    else:
        quote["dist_to_pdh_atr"] = None
    if price > 0.0 and atr > 0.0 and pdl > 0.0:
        quote["dist_to_pdl_atr"] = round(abs(price - pdl) / atr, 4)
    else:
        quote["dist_to_pdl_atr"] = None


def _fetch_earnings_today(client: FMPClient, today: date) -> dict[str, str]:
    """Return {SYMBOL: timing} for today's earnings.  timing is 'bmo', 'amc', or ''."""
    data = client.get_earnings_calendar(today, today)
    result: dict[str, str] = {}
    for item in data:
        sym = str(item.get("symbol") or "").strip().upper()
        if not sym:
            continue
        raw_time = str(item.get("time") or "").strip().lower()
        result[sym] = raw_time  # "bmo", "amc", "" etc.
    return result


def _fetch_premarket_context(
    *,
    client: FMPClient,
    symbols: list[str],
    today: date,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Fetch pre-market enrichment data: earnings timing + premarket movers.

    Returns (premarket_by_symbol, error_message_or_none).
    """
    premarket: dict[str, dict[str, Any]] = {sym: {} for sym in symbols}
    errors: list[str] = []

    # --- Earnings calendar (BMO is the strongest pre-market catalyst) ---
    try:
        earnings_today = _fetch_earnings_today(client, today)
        for sym in symbols:
            timing = earnings_today.get(sym)
            premarket[sym]["earnings_today"] = timing is not None
            premarket[sym]["earnings_timing"] = timing  # "bmo", "amc", "" or None
    except Exception as exc:
        logger.warning("Earnings calendar fetch failed: %s", exc)
        errors.append(f"earnings_calendar: {exc}")
        for sym in symbols:
            premarket[sym]["earnings_today"] = False
            premarket[sym]["earnings_timing"] = None

    # --- Pre-Market Movers via FMP v4 ---
    try:
        movers = client.get_premarket_movers()
        mover_map: dict[str, dict] = {}
        for m in movers:
            ticker = str(m.get("ticker") or m.get("symbol") or "").strip().upper()
            if ticker:
                mover_map[ticker] = m
        for sym in symbols:
            if sym in mover_map:
                premarket[sym]["is_premarket_mover"] = True
                raw_change = mover_map[sym].get("changesPercentage")
                raw_price = mover_map[sym].get("price")
                raw_volume = mover_map[sym].get("volume")

                change_pct = _to_float(raw_change, default=float("nan"))
                price = _to_float(raw_price, default=float("nan"))
                volume = _to_float(raw_volume, default=float("nan"))

                premarket[sym]["premarket_change_pct"] = None if change_pct != change_pct else change_pct
                premarket[sym]["premarket_price"] = None if price != price else price
                premarket[sym]["premarket_volume"] = None if volume != volume else volume
            else:
                premarket[sym].setdefault("is_premarket_mover", False)
    except Exception as exc:
        logger.warning("Premarket movers fetch failed: %s", exc)
        errors.append(f"premarket_movers: {exc}")
        for sym in symbols:
            premarket[sym].setdefault("is_premarket_mover", False)

    error_msg = "; ".join(errors) if errors else None
    return premarket, error_msg


def _quote_timestamp_iso_utc(quote: dict[str, Any]) -> str | None:
    for key in ("timestamp", "lastUpdated", "lastUpdatedAt", "quoteTimestamp"):
        if key in quote:
            iso = _to_iso_utc_from_epoch(quote.get(key))
            if iso:
                return iso
    return None


def _pick_indicative_price(quote: dict[str, Any]) -> tuple[float, str | None]:
    source_map = {
        "preMarketPrice": "premarket",
        "preMarket": "premarket",
        "extendedPrice": "extended",
        "price": "spot",
    }
    for key in ("preMarketPrice", "preMarket", "extendedPrice", "price"):
        px = _to_float(quote.get(key), default=0.0)
        if px > 0.0:
            return px, source_map.get(key, key)
    return 0.0, None


def _compute_gap_for_quote(
    quote: dict[str, Any],
    *,
    run_dt_utc: datetime,
    gap_mode: str,
) -> dict[str, Any]:
    """Compute session-gap value and metadata according to selected mode."""
    ny_now = run_dt_utc.astimezone(US_EASTERN_TZ)
    ny_date = ny_now.date()
    is_gap_session = _is_first_session_after_non_trading_stretch(ny_date)
    prev_day = _prev_trading_day(ny_date)
    gap_from_ts = datetime.combine(prev_day, datetime.min.time(), tzinfo=US_EASTERN_TZ).replace(
        hour=16, minute=0, second=0, microsecond=0
    ).astimezone(UTC).isoformat()

    prev_close = _to_float(quote.get("previousClose"), default=0.0)
    if prev_close <= 0.0:
        fallback_gap = _to_float(
            quote.get("changesPercentage", quote.get("changePercentage")),
            default=0.0,
        )
        return {
            "gap_pct": fallback_gap,
            "gap_type": GAP_MODE_OFF,
            "gap_available": False,
            "gap_from_ts": gap_from_ts,
            "gap_to_ts": None,
            "gap_mode_selected": gap_mode,
            "gap_price_source": None,
            "gap_reason": "missing_previous_close",
        }

    if gap_mode == GAP_MODE_OFF:
        return {
            "gap_pct": 0.0,
            "gap_type": GAP_MODE_OFF,
            "gap_available": False,
            "gap_from_ts": gap_from_ts,
            "gap_to_ts": None,
            "gap_mode_selected": gap_mode,
            "gap_price_source": None,
            "gap_reason": "mode_off",
        }

    if not is_gap_session:
        return {
            "gap_pct": 0.0,
            "gap_type": GAP_MODE_OFF,
            "gap_available": False,
            "gap_from_ts": gap_from_ts,
            "gap_to_ts": None,
            "gap_mode_selected": gap_mode,
            "gap_price_source": None,
            "gap_reason": "not_monday_session",
        }

    if gap_mode == GAP_MODE_RTH_OPEN:
        has_rth_open_window = ny_now.hour > 9 or (ny_now.hour == 9 and ny_now.minute >= 30)
        open_px = _to_float(quote.get("open"), default=0.0)
        if has_rth_open_window and open_px > 0.0:
            gap_pct = ((open_px - prev_close) / prev_close) * 100.0
            rth_open_ts = datetime.combine(
                ny_date,
                datetime.min.time(),
                tzinfo=US_EASTERN_TZ,
            ).replace(hour=9, minute=30, second=0, microsecond=0).astimezone(UTC).isoformat()
            return {
                "gap_pct": round(gap_pct, 6),
                "gap_type": GAP_MODE_RTH_OPEN,
                "gap_available": True,
                "gap_from_ts": gap_from_ts,
                "gap_to_ts": rth_open_ts,
                "gap_mode_selected": gap_mode,
                "gap_price_source": "rth_open",
                "gap_reason": "ok",
            }
        return {
            "gap_pct": 0.0,
            "gap_type": GAP_MODE_OFF,
            "gap_available": False,
            "gap_from_ts": gap_from_ts,
            "gap_to_ts": None,
            "gap_mode_selected": gap_mode,
            "gap_price_source": None,
            "gap_reason": "rth_open_unavailable",
        }

    # PREMARKET_INDICATIVE
    has_premarket_window = ny_now.hour >= 4
    indicative_px, px_source = _pick_indicative_price(quote)
    quote_ts = _quote_timestamp_iso_utc(quote)
    if has_premarket_window and indicative_px > 0.0:
        if px_source in {"premarket", "extended"} and quote_ts is None:
            return {
                "gap_pct": 0.0,
                "gap_type": GAP_MODE_OFF,
                "gap_available": False,
                "gap_from_ts": gap_from_ts,
                "gap_to_ts": None,
                "gap_mode_selected": gap_mode,
                "gap_price_source": px_source,
                "gap_reason": "missing_quote_timestamp",
            }
        # Weekend stale guard: pure "price" fallback on Monday pre-open can still be Friday last.
        if px_source == "spot" and quote_ts is None:
            return {
                "gap_pct": 0.0,
                "gap_type": GAP_MODE_OFF,
                "gap_available": False,
                "gap_from_ts": gap_from_ts,
                "gap_to_ts": None,
                "gap_mode_selected": gap_mode,
                "gap_price_source": px_source,
                "gap_reason": "weekend_last_quote_unknown_timestamp",
            }
        gap_pct = ((indicative_px - prev_close) / prev_close) * 100.0
        return {
            "gap_pct": round(gap_pct, 6),
            "gap_type": GAP_MODE_PREMARKET_INDICATIVE,
            "gap_available": True,
            "gap_from_ts": gap_from_ts,
            "gap_to_ts": quote_ts,
            "gap_mode_selected": gap_mode,
            "gap_price_source": px_source,
            "gap_reason": "ok",
        }

    return {
        "gap_pct": 0.0,
        "gap_type": GAP_MODE_OFF,
        "gap_available": False,
        "gap_from_ts": gap_from_ts,
        "gap_to_ts": None,
        "gap_mode_selected": gap_mode,
        "gap_price_source": px_source,
        "gap_reason": "premarket_unavailable",
    }


def apply_gap_mode_to_quotes(
    quotes: list[dict[str, Any]],
    *,
    run_dt_utc: datetime,
    gap_mode: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mode = str(gap_mode or GAP_MODE_PREMARKET_INDICATIVE).strip().upper()
    if mode not in GAP_MODE_CHOICES:
        raise ValueError(f"Unsupported gap mode: {gap_mode}")

    for quote in quotes:
        row = dict(quote)
        gap_meta = _compute_gap_for_quote(row, run_dt_utc=run_dt_utc, gap_mode=mode)
        row.update(gap_meta)
        out.append(row)
    return out


def _calculate_atr14_from_eod(candles: list[dict], period: int = 14) -> float:
    """Calculate ATR(period) from EOD OHLC using Wilder's Smoothing (RMA).

    Expects each candle to expose high, low, close.
    Standard ATR calculation:
    1. TR = Max(H-L, |H-Cp|, |L-Cp|)
    2. First ATR = SMA(TR, period)
    3. Subsequent ATR = ((Prior ATR * (period-1)) + Current TR) / period
    """
    period_eff = max(int(period), 1)
    parsed: list[tuple[str, float, float, float]] = []
    for c in candles:
        d = str(c.get("date") or "")
        if not d:
            continue
        high = _to_float(c.get("high"), default=float("nan"))
        low = _to_float(c.get("low"), default=float("nan"))
        close = _to_float(c.get("close"), default=float("nan"))
        if any(x != x for x in (high, low, close)):  # NaN check
            continue
        parsed.append((d, high, low, close))

    if len(parsed) < period_eff + 1:  # Need period for first value + 1 prior close
        return 0.0

    parsed.sort(key=lambda row: row[0])
    tr_values: list[float] = []
    prev_close: float | None = None

    for _, high, low, close in parsed:
        if prev_close is None:
            # First bar TR is H-L (no prior close)
            # Standard practice often skips first bar or treats as H-L
            tr = high - low
        else:
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
        tr_values.append(max(tr, 0.0))
        prev_close = close

    # Wilder's Smoothing Initialization: first `period` TRs -> Simple Average
    current_atr = sum(tr_values[:period_eff]) / float(period_eff)

    # Smooth the rest
    for tr in tr_values[period_eff:]:
        current_atr = (current_atr * float(period_eff - 1) + tr) / float(period_eff)

    return round(current_atr, 4)


def _fetch_symbol_atr(
    client: FMPClient,
    symbol: str,
    date_from: date,
    as_of: date,
    atr_period: int,
) -> tuple[str, float, float, str | None]:
    """Fetch historical candles and compute ATR for one symbol.

    Returns: (symbol, atr_value, error_message)
    """
    try:
        candles = client.get_historical_price_eod_full(symbol, date_from, as_of)
        atr_value = _calculate_atr14_from_eod(candles, period=atr_period)
        momentum_z = _momentum_z_score_from_eod(candles, period=50)
        return symbol, atr_value, momentum_z, None
    except RuntimeError as exc:
        return symbol, 0.0, 0.0, str(exc)


def _atr14_by_symbol(
    client: FMPClient,
    symbols: list[str],
    as_of: date,
    lookback_days: int = 250,  # Increased for RMA convergence
    atr_period: int = 14,
    parallel_workers: int = 5,
) -> tuple[dict[str, float], dict[str, float], dict[str, str]]:
    atr_map: dict[str, float] = {}
    momentum_z_map: dict[str, float] = {}
    errors: dict[str, str] = {}
    date_from = as_of - timedelta(days=max(lookback_days, 20))

    workers = max(1, min(int(parallel_workers), max(1, len(symbols))))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                _fetch_symbol_atr,
                client,
                symbol,
                date_from,
                as_of,
                int(atr_period),
            ): symbol
            for symbol in symbols
        }
        for future in as_completed(future_map):
            symbol = future_map[future]
            try:
                sym, atr_value, momentum_z, err = future.result()
                atr_map[sym] = atr_value
                momentum_z_map[sym] = momentum_z
                if err:
                    errors[sym] = err
            except Exception as exc:  # pragma: no cover - defensive catch
                atr_map[symbol] = 0.0
                momentum_z_map[symbol] = 0.0
                errors[symbol] = str(exc)

    # Keep deterministic key presence/order compatibility.
    for symbol in symbols:
        atr_map.setdefault(symbol, 0.0)
        momentum_z_map.setdefault(symbol, 0.0)

    return atr_map, momentum_z_map, errors


def _inputs_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_runtime_status(
    *,
    news_fetch_error: str | None,
    atr_fetch_errors: dict[str, str],
    premarket_fetch_error: str | None = None,
    fatal_stage: str | None = None,
) -> dict[str, Any]:
    """Build a machine-readable run status contract for downstream consumers."""
    warnings: list[dict[str, Any]] = []

    if news_fetch_error:
        warnings.append(
            {
                "stage": "news_fetch",
                "code": "DATA_SOURCE_DEGRADED",
                "message": str(news_fetch_error),
            }
        )

    if atr_fetch_errors:
        symbols = sorted(str(k).upper() for k in atr_fetch_errors.keys() if str(k).strip())
        warnings.append(
            {
                "stage": "atr_fetch",
                "code": "PARTIAL_DATA",
                "message": f"ATR unavailable for {len(symbols)} symbols.",
                "symbols": symbols,
            }
        )

    if premarket_fetch_error:
        warnings.append(
            {
                "stage": "premarket_fetch",
                "code": "DATA_SOURCE_DEGRADED",
                "message": str(premarket_fetch_error),
            }
        )

    return {
        "degraded_mode": bool(warnings),
        "fatal_stage": fatal_stage,
        "warnings": warnings,
    }


def _parse_symbols(raw_symbols: str) -> list[str]:
    symbols = [item.strip().upper() for item in raw_symbols.split(",") if item.strip()]
    if not symbols:
        raise ValueError("No symbols provided. Use --symbols with comma-separated tickers.")
    return symbols


def _fetch_todays_events(
    *,
    client: FMPClient,
    today: date,
    end_date: date,
    pre_open_only: bool,
    pre_open_cutoff_utc: str,
) -> list[dict[str, Any]]:
    try:
        macro_events = client.get_macro_calendar(today, end_date)
    except RuntimeError as exc:
        logger.error("Macro calendar fetch failed: %s", exc)
        raise SystemExit(1) from exc

    todays_events = [event for event in macro_events if _event_is_today(event, today)]
    if not pre_open_only:
        return todays_events

    try:
        return _filter_events_by_cutoff_utc(todays_events, pre_open_cutoff_utc)
    except ValueError as exc:
        logger.error("Invalid --pre-open-cutoff-utc: %s", exc)
        raise SystemExit(1) from exc


def _build_macro_context(
    *,
    todays_events: list[dict[str, Any]],
    max_macro_events: int,
    bea_audit_enabled: bool,
) -> dict[str, Any]:
    todays_us_events = dedupe_events(filter_us_events(todays_events))
    todays_us_high_impact_events = filter_us_high_impact_events(todays_us_events)
    todays_us_mid_impact_events = filter_us_mid_impact_events(todays_us_events)

    macro_analysis = macro_bias_with_components(todays_events)
    bea_audit = build_bea_audit_payload(
        macro_analysis.get("events_for_bias", []),
        enabled=bea_audit_enabled,
    )

    return {
        "macro_analysis": macro_analysis,
        "macro_bias": float(macro_analysis["macro_bias"]),
        "macro_event_count_today": len(todays_events),
        "macro_us_event_count_today": len(todays_us_events),
        "macro_us_high_impact_event_count_today": len(todays_us_high_impact_events),
        "macro_us_mid_impact_event_count_today": len(todays_us_mid_impact_events),
        "macro_events_for_bias": _format_macro_events(
            macro_analysis.get("events_for_bias", []),
            max_macro_events,
        ),
        "macro_us_high_impact_events_today": _format_macro_events(
            todays_us_high_impact_events,
            max_macro_events,
        ),
        "macro_us_mid_impact_events_today": _format_macro_events(
            todays_us_mid_impact_events,
            max_macro_events,
        ),
        "bea_audit": bea_audit,
    }


def _fetch_news_context(
    *,
    client: FMPClient,
    symbols: list[str],
) -> tuple[dict[str, float], dict[str, dict], str | None]:
    news_scores: dict[str, float] = {}
    news_metrics: dict[str, dict] = {}
    news_fetch_error: str | None = None

    # Optional catalyst boost from latest FMP articles (stable endpoint).
    # If news fetch fails, ranking still proceeds with pure market+macro features.
    try:
        articles = client.get_fmp_articles(limit=250)
        news_scores, news_metrics = build_news_scores(symbols=symbols, articles=articles)
    except RuntimeError as exc:
        news_fetch_error = str(exc)
        logger.warning("News fetch failed, continuing without news scores: %s", exc)

    return news_scores, news_metrics, news_fetch_error


def _fetch_quotes_with_atr(
    *,
    client: FMPClient,
    symbols: list[str],
    run_dt_utc: datetime,
    as_of: date,
    gap_mode: str,
    atr_lookback_days: int,
    atr_period: int,
    atr_parallel_workers: int,
) -> tuple[list[dict[str, Any]], dict[str, float], dict[str, float], dict[str, str]]:
    try:
        quotes = client.get_batch_quotes(symbols)
    except RuntimeError as exc:
        logger.error("Quote fetch failed: %s", exc)
        raise SystemExit(1) from exc

    quotes = apply_gap_mode_to_quotes(quotes, run_dt_utc=run_dt_utc, gap_mode=gap_mode)

    atr_by_symbol, momentum_z_by_symbol, atr_fetch_errors = _atr14_by_symbol(
        client=client,
        symbols=symbols,
        as_of=as_of,
        lookback_days=atr_lookback_days,
        atr_period=atr_period,
        parallel_workers=atr_parallel_workers,
    )
    for q in quotes:
        sym = str(q.get("symbol") or "").strip().upper()
        if sym:
            q["atr"] = atr_by_symbol.get(sym, 0.0)
            q["momentum_z_score"] = momentum_z_by_symbol.get(sym, 0.0)
            _enrich_quote_with_hvb(q)
            _add_pdh_pdl_context(q)

    return quotes, atr_by_symbol, momentum_z_by_symbol, atr_fetch_errors


def _build_result_payload(
    *,
    config: OpenPrepConfig,
    now_utc: datetime,
    today: date,
    macro_context: dict[str, Any],
    news_metrics: dict[str, dict],
    news_fetch_error: str | None,
    atr_by_symbol: dict[str, float],
    momentum_z_by_symbol: dict[str, float],
    atr_fetch_errors: dict[str, str],
    premarket_context: dict[str, dict[str, Any]],
    premarket_fetch_error: str | None,
    ranked: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> dict[str, Any]:
    macro_analysis = macro_context["macro_analysis"]
    bias = float(macro_context["macro_bias"])

    return {
        "schema_version": "open_prep_v1",
        "code_version": os.environ.get("OPEN_PREP_CODE_VERSION", os.environ.get("GIT_SHA", "unknown")),
        "inputs_hash": _inputs_hash(
            {
                "run_date_utc": today.isoformat(),
                "symbols": config.symbols,
                "days_ahead": config.days_ahead,
                "top": config.top,
                "trade_cards": config.trade_cards,
                "max_macro_events": config.max_macro_events,
                "pre_open_only": config.pre_open_only,
                "pre_open_cutoff_utc": config.pre_open_cutoff_utc,
                "gap_mode": config.gap_mode,
                "atr_lookback_days": config.atr_lookback_days,
                "atr_period": config.atr_period,
                "atr_parallel_workers": config.atr_parallel_workers,
            }
        ),
        "run_date_utc": today.isoformat(),
        "run_datetime_utc": now_utc.isoformat(),
        "active_session": _classify_session(now_utc),
        "pre_open_only": bool(config.pre_open_only),
        "pre_open_cutoff_utc": config.pre_open_cutoff_utc,
        "gap_mode": config.gap_mode,
        "atr_lookback_days": config.atr_lookback_days,
        "atr_period": config.atr_period,
        "atr_parallel_workers": config.atr_parallel_workers,
        "macro_bias": round(bias, 4),
        "macro_raw_score": round(float(macro_analysis.get("raw_score", 0.0)), 4),
        "macro_event_count_today": macro_context["macro_event_count_today"],
        "macro_us_event_count_today": macro_context["macro_us_event_count_today"],
        "macro_us_high_impact_event_count_today": macro_context["macro_us_high_impact_event_count_today"],
        "macro_us_mid_impact_event_count_today": macro_context["macro_us_mid_impact_event_count_today"],
        "macro_events_for_bias": macro_context["macro_events_for_bias"],
        "macro_score_components": macro_analysis.get("score_components", []),
        "bea_audit": macro_context["bea_audit"],
        "macro_us_high_impact_events_today": macro_context["macro_us_high_impact_events_today"],
        "macro_us_mid_impact_events_today": macro_context["macro_us_mid_impact_events_today"],
        "news_catalyst_by_symbol": news_metrics,
        "news_fetch_error": news_fetch_error,
        "atr14_by_symbol": atr_by_symbol,
        "momentum_z_by_symbol": momentum_z_by_symbol,
        "atr_fetch_errors": atr_fetch_errors,
        "premarket_context": premarket_context,
        "premarket_fetch_error": premarket_fetch_error,
        "run_status": _build_runtime_status(
            news_fetch_error=news_fetch_error,
            atr_fetch_errors=atr_fetch_errors,
            premarket_fetch_error=premarket_fetch_error,
            fatal_stage=None,
        ),
        "ranked_candidates": ranked,
        "trade_cards": cards,
    }


def generate_open_prep_result(
    *,
    symbols: list[str] | None = None,
    days_ahead: int = 3,
    top: int = 10,
    trade_cards: int = 5,
    max_macro_events: int = 15,
    pre_open_only: bool = False,
    pre_open_cutoff_utc: str = "16:00:00",
    gap_mode: str = GAP_MODE_PREMARKET_INDICATIVE,
    atr_lookback_days: int = 250,
    atr_period: int = 14,
    atr_parallel_workers: int = 5,
    now_utc: datetime | None = None,
    client: FMPClient | None = None,
) -> dict[str, Any]:
    """Run the open-prep pipeline and return the structured result payload."""
    run_dt = now_utc or datetime.now(UTC)
    symbol_list = [str(s).strip().upper() for s in (symbols or DEFAULT_UNIVERSE) if str(s).strip()]
    if not symbol_list:
        raise ValueError("No symbols provided. Use at least one ticker symbol.")

    mode = str(gap_mode or GAP_MODE_PREMARKET_INDICATIVE).strip().upper()
    if mode not in GAP_MODE_CHOICES:
        raise ValueError(f"Unsupported gap mode: {gap_mode}")

    config = OpenPrepConfig(
        symbols=symbol_list,
        days_ahead=int(days_ahead),
        top=int(top),
        trade_cards=int(trade_cards),
        max_macro_events=int(max_macro_events),
        pre_open_only=bool(pre_open_only),
        pre_open_cutoff_utc=str(pre_open_cutoff_utc),
        gap_mode=mode,
        atr_lookback_days=max(int(atr_lookback_days), 20),
        atr_period=max(int(atr_period), 1),
        atr_parallel_workers=max(int(atr_parallel_workers), 1),
    )

    today = run_dt.date()
    end_date = today + timedelta(days=max(config.days_ahead, 1))
    data_client = client or FMPClient.from_env()

    bea_audit_enabled = str(os.environ.get("OPEN_PREP_BEA_AUDIT", "1")).strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }

    todays_events = _fetch_todays_events(
        client=data_client,
        today=today,
        end_date=end_date,
        pre_open_only=bool(config.pre_open_only),
        pre_open_cutoff_utc=config.pre_open_cutoff_utc,
    )
    macro_context = _build_macro_context(
        todays_events=todays_events,
        max_macro_events=config.max_macro_events,
        bea_audit_enabled=bea_audit_enabled,
    )
    bias = float(macro_context["macro_bias"])

    news_scores, news_metrics, news_fetch_error = _fetch_news_context(client=data_client, symbols=symbol_list)
    quotes, atr_by_symbol, momentum_z_by_symbol, atr_fetch_errors = _fetch_quotes_with_atr(
        client=data_client,
        symbols=symbol_list,
        run_dt_utc=run_dt,
        as_of=today,
        gap_mode=config.gap_mode,
        atr_lookback_days=config.atr_lookback_days,
        atr_period=config.atr_period,
        atr_parallel_workers=config.atr_parallel_workers,
    )
    premarket_context, premarket_fetch_error = _fetch_premarket_context(
        client=data_client,
        symbols=symbol_list,
        today=today,
    )

    # Merge premarket context into quotes so ranker & trade-card builder see it.
    for q in quotes:
        sym = str(q.get("symbol") or "").strip().upper()
        pm = premarket_context.get(sym, {})
        if pm:
            q["earnings_today"] = pm.get("earnings_today", False)
            q["earnings_timing"] = pm.get("earnings_timing")
            q["is_premarket_mover"] = pm.get("is_premarket_mover", False)
            if pm.get("premarket_change_pct") is not None:
                q["premarket_change_pct"] = pm["premarket_change_pct"]
            if pm.get("premarket_price") is not None:
                q["premarket_price"] = pm["premarket_price"]

    ranked = rank_candidates(
        quotes=quotes,
        bias=bias,
        top_n=max(config.top, 1),
        news_scores=news_scores,
    )
    cards = build_trade_cards(ranked_candidates=ranked, bias=bias, top_n=max(config.trade_cards, 1))

    return _build_result_payload(
        config=config,
        now_utc=run_dt,
        today=today,
        macro_context=macro_context,
        news_metrics=news_metrics,
        news_fetch_error=news_fetch_error,
        atr_by_symbol=atr_by_symbol,
        momentum_z_by_symbol=momentum_z_by_symbol,
        atr_fetch_errors=atr_fetch_errors,
        premarket_context=premarket_context,
        premarket_fetch_error=premarket_fetch_error,
        ranked=ranked,
        cards=cards,
    )


def main() -> None:
    args = _parse_args()
    symbols = _parse_symbols(args.symbols)
    result = generate_open_prep_result(
        symbols=symbols,
        days_ahead=args.days_ahead,
        top=args.top,
        trade_cards=args.trade_cards,
        max_macro_events=args.max_macro_events,
        pre_open_only=bool(args.pre_open_only),
        pre_open_cutoff_utc=args.pre_open_cutoff_utc,
        gap_mode=args.gap_mode,
        atr_lookback_days=args.atr_lookback_days,
        atr_period=args.atr_period,
        atr_parallel_workers=args.atr_parallel_workers,
    )
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("OPEN_PREP_LOG_LEVEL", "INFO").upper(),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    main()
