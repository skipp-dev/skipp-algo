from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from .trade_cards import build_trade_cards
from .bea import build_bea_audit_payload
from .playbook import assign_playbooks
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
from .screen import classify_long_gap, compute_gap_warn_flags, rank_candidates
from .utils import to_float as _to_float

# --- v2 pipeline modules ---
from .scorer import rank_candidates_v2, load_weight_set, save_weight_set
from .regime import classify_regime, apply_regime_adjustments
from .technical_analysis import detect_breakout, detect_consolidation, detect_symbol_regime
from .outcomes import (
    compute_hit_rates,
    get_symbol_hit_rate,
    prepare_outcome_snapshot,
    store_daily_outcomes,
)
from .alerts import dispatch_alerts, alert_regime_change, load_alert_config
from .watchlist import (
    load_watchlist,
    auto_add_high_conviction,
    get_watchlist_symbols,
)
from .diff import (
    compute_diff,
    format_diff_summary,
    load_previous_snapshot,
    save_result_snapshot,
)

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
BERLIN_TZ = ZoneInfo("Europe/Berlin")
HVB_MULTIPLIER = 1.5
GAP_MODE_RTH_OPEN = "RTH_OPEN"
GAP_MODE_PREMARKET_INDICATIVE = "PREMARKET_INDICATIVE"
GAP_MODE_OFF = "OFF"
GAP_MODE_CHOICES: tuple[str, ...] = (
    GAP_MODE_RTH_OPEN,
    GAP_MODE_PREMARKET_INDICATIVE,
    GAP_MODE_OFF,
)
GAP_SCOPE_DAILY = "DAILY"
GAP_SCOPE_STRETCH_ONLY = "STRETCH_ONLY"
GAP_SCOPE_CHOICES: tuple[str, ...] = (GAP_SCOPE_DAILY, GAP_SCOPE_STRETCH_ONLY)
UNIVERSE_SOURCE_STATIC = "STATIC"
UNIVERSE_SOURCE_FMP_US_MID_LARGE = "FMP_US_MID_LARGE"
UNIVERSE_SOURCE_CHOICES: tuple[str, ...] = (
    UNIVERSE_SOURCE_STATIC,
    UNIVERSE_SOURCE_FMP_US_MID_LARGE,
)
DEFAULT_FMP_MIN_MARKET_CAP = 2_000_000_000
DEFAULT_FMP_MAX_SYMBOLS = 800
DEFAULT_MOVER_SEED_MAX_SYMBOLS = 400
MAX_PREMARKET_UNION_SYMBOLS = 1200
PREMARKET_STALE_SECONDS = 30 * 60
CORPORATE_ACTION_WINDOW_DAYS = 3
DEFAULT_ANALYST_CATALYST_LIMIT = 80
ATR_CACHE_DIR = Path("artifacts/open_prep/cache/atr")
PM_CACHE_DIR = Path("artifacts/open_prep/cache/premarket")
CAPABILITY_CACHE_DIR = Path("artifacts/open_prep/cache/capabilities")
CAPABILITY_CACHE_FILE = CAPABILITY_CACHE_DIR / "latest.json"
PM_CACHE_TTL_SECONDS = 120
TOP_N_EXT_FOR_PMH = 50
PM_FETCH_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class OpenPrepConfig:
    symbols: tuple[str, ...]
    universe_source: str = UNIVERSE_SOURCE_FMP_US_MID_LARGE
    fmp_min_market_cap: int = DEFAULT_FMP_MIN_MARKET_CAP
    fmp_max_symbols: int = DEFAULT_FMP_MAX_SYMBOLS
    mover_seed_max_symbols: int = DEFAULT_MOVER_SEED_MAX_SYMBOLS
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
    gap_scope: str = GAP_SCOPE_DAILY
    analyst_catalyst_limit: int = DEFAULT_ANALYST_CATALYST_LIMIT


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
        impact_raw = str(event.get("impact") or event.get("importance") or event.get("priority") or "").lower()
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
        default="",
        help=(
            "Optional comma-separated ticker universe override. "
            "If omitted, the universe is resolved via --universe-source."
        ),
    )
    parser.add_argument(
        "--universe-source",
        type=str,
        choices=[c.lower() for c in UNIVERSE_SOURCE_CHOICES],
        default=UNIVERSE_SOURCE_FMP_US_MID_LARGE.lower(),
        help=(
            "Universe source when --symbols is not provided: "
            "fmp_us_mid_large (default) or static fallback list."
        ),
    )
    parser.add_argument(
        "--fmp-min-market-cap",
        type=int,
        default=DEFAULT_FMP_MIN_MARKET_CAP,
        help="Minimum market cap (USD) for FMP auto-universe, default 2,000,000,000.",
    )
    parser.add_argument(
        "--fmp-max-symbols",
        type=int,
        default=DEFAULT_FMP_MAX_SYMBOLS,
        help="Maximum symbol count for FMP auto-universe.",
    )
    parser.add_argument(
        "--mover-seed-max-symbols",
        type=int,
        default=DEFAULT_MOVER_SEED_MAX_SYMBOLS,
        help=(
            "Maximum number of symbols imported from most-actives/gainers/losers "
            "when building attention-seed universe and premarket context."
        ),
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
        choices=[c.lower() for c in GAP_MODE_CHOICES],
        default=GAP_MODE_PREMARKET_INDICATIVE.lower(),
        help=(
            "How to compute gap price: RTH_OPEN (official RTH open), "
            "PREMARKET_INDICATIVE (premarket indication), OFF (no gap)."
        ),
    )
    parser.add_argument(
        "--gap-scope",
        type=str,
        choices=[c.lower() for c in GAP_SCOPE_CHOICES],
        default=GAP_SCOPE_DAILY.lower(),
        help=(
            "When to compute gaps: DAILY (every trading day, default) or "
            "STRETCH_ONLY (only first session after weekend/holiday)."
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
        default=8,
        help="Maximum parallel workers for ATR historical fetch requests.",
    )
    parser.add_argument(
        "--analyst-catalyst-limit",
        type=int,
        default=DEFAULT_ANALYST_CATALYST_LIMIT,
        help="Maximum symbols to enrich with analyst price-target summaries.",
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
                "impact": event.get("impact") or event.get("importance") or event.get("priority"),
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
    # Safety bound: max 14 iterations covers any realistic holiday stretch
    # (NYSE never has more than ~4-day closures including weekends).
    for _ in range(14):
        if _is_us_equity_trading_day(cur):
            return cur
        cur -= timedelta(days=1)
    # Defensive fallback: return last checked day (cur) rather than d-1
    # because d-1 may be a weekend/holiday.  This can only happen if the
    # holiday calendar is severely wrong (>14 consecutive non-trading days).
    logger.warning(
        "_prev_trading_day: exhausted 14-day lookback from %s, returning %s (may not be a trading day)",
        d,
        cur,
    )
    return cur


def _is_first_session_after_non_trading_stretch(d: date) -> bool:
    if not _is_us_equity_trading_day(d):
        return False
    prev_day = _prev_trading_day(d)
    return (d - prev_day).days > 1


def _is_gap_day(d: date, gap_scope: str) -> bool:
    """Determine whether *d* should produce a gap calculation.

    * DAILY — every US-equity trading day is a gap day.
    * STRETCH_ONLY — only the first session after a non-trading stretch
      (weekends, holidays).
    """
    if gap_scope == GAP_SCOPE_DAILY:
        return _is_us_equity_trading_day(d)
    return _is_first_session_after_non_trading_stretch(d)


def _to_iso_utc_from_epoch(value: Any) -> str | None:
    try:
        if value is None:
            return None
        ts = float(value)
        # Handle both epoch seconds and epoch milliseconds.
        if ts > 10_000_000_000:
            ts /= 1000.0
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
    if 630 <= t < 780:   # 10:30–13:00
        return "NY_MIDDAY"
    if 780 <= t < 960:   # 13:00–16:00
        return "NY_PM"
    if 240 <= t < 570:   # 04:00–09:30 (US pre-market)
        return "US_PREMARKET"
    if 120 <= t < 240:   # 02:00–04:00
        return "LONDON"
    return "OFF_HOURS"


def _minutes_since_midnight(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _in_window(mins: int, start_hm: tuple[int, int], end_hm: tuple[int, int]) -> bool:
    start = start_hm[0] * 60 + start_hm[1]
    end = end_hm[0] * 60 + end_hm[1]
    return start <= mins <= end


def _extract_latest_news_ts_utc(news_metrics_row: dict[str, Any] | None) -> datetime | None:
    """Best-effort: pull a 'latest news timestamp' from build_news_scores() metrics.

    The canonical key emitted by news.build_news_scores() is ``latest_article_utc``
    (ISO-8601 string after serialisation).  We also probe a handful of plausible
    alternative names so the helper stays resilient if the schema evolves.
    Returns a timezone-aware UTC datetime or *None*.
    """
    if not news_metrics_row:
        return None

    candidates = (
        # canonical (news.py stores this as ISO string)
        "latest_article_utc",
        # plausible future / alternative names
        "latest_timestamp_utc",
        "latest_ts_utc",
        "latest_published_at_utc",
        "latest_published_at",
        "latest_datetime_utc",
        "latest_datetime",
        "max_timestamp_utc",
        "max_ts_utc",
        "timestamp_utc",
        "published_at_utc",
        "publishedAt",
    )
    for key in candidates:
        raw = news_metrics_row.get(key)
        if raw is None:
            continue
        # epoch?
        dt = _epoch_to_datetime_utc(raw)
        if dt is not None:
            return dt
        # iso string?
        try:
            s = str(raw).strip()
            if not s:
                continue
            dt2 = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt2.tzinfo is None:
                dt2 = dt2.replace(tzinfo=UTC)
            return dt2.astimezone(UTC)
        except ValueError:
            continue
    return None


def _time_based_warn_flags(
    *,
    q: dict[str, Any],
    run_dt_utc: datetime,
    news_metrics_row: dict[str, Any] | None,
) -> list[str]:
    """Attach purely time-structure warn flags (no gating)."""
    flags: list[str] = []

    ny = run_dt_utc.astimezone(US_EASTERN_TZ)
    ny_mins = _minutes_since_midnight(ny)

    berlin = run_dt_utc.astimezone(BERLIN_TZ)
    berlin_mins = _minutes_since_midnight(berlin)

    # --- 12:00 CET/CEST window tag (observed spike time) ---
    if _in_window(berlin_mins, (11, 50), (12, 10)):
        flags.append("cet_midday_window")

    # --- Classic macro release windows (NY) ---
    # 08:30 ET releases and 10:00 ET releases (small buffers)
    if _in_window(ny_mins, (8, 25), (8, 40)) or _in_window(ny_mins, (9, 55), (10, 5)):
        flags.append("macro_release_window")

    # --- Premarket liquidity step (NY 06:00-08:00) ---
    ext_score = _to_float(q.get("ext_hours_score"), default=0.0)
    ext_vol_ratio = _to_float(q.get("ext_volume_ratio"), default=0.0)
    stale = bool(q.get("premarket_stale", False))
    spread_bps = _to_float(q.get("premarket_spread_bps"), default=float("nan"))

    spread_ok = spread_bps == spread_bps and spread_bps <= 60.0  # NaN-safe; lenient threshold
    if (
        _in_window(ny_mins, (6, 0), (8, 0))
        and not stale
        and spread_ok
        and (ext_score >= 0.75 or ext_vol_ratio >= 0.05)
    ):
        flags.append("premarket_liquidity_step")

    # --- News recency flags (best-effort) ---
    latest_news_dt = _extract_latest_news_ts_utc(news_metrics_row)
    if latest_news_dt is not None:
        age_min = max((run_dt_utc - latest_news_dt).total_seconds() / 60.0, 0.0)
        if age_min <= 30.0:
            flags.append("news_recency_30m")
        elif age_min <= 60.0:
            flags.append("news_recency_60m")

    return flags


def _momentum_z_score_from_eod(candles: list[dict], period: int = 50) -> float:
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
    if len(window) < 5:
        # Need at least 5 observations for a statistically meaningful z-score;
        # Bessel's correction with n<5 can produce extreme values.
        return 0.0
    mean_ret = sum(window) / float(len(window))
    variance = sum((r - mean_ret) ** 2 for r in window) / float(len(window) - 1)
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


def _normalize_symbols(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _extract_symbol_from_row(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").strip().upper()


def _parse_calendar_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    date_part = raw.split("T")[0].split(" ")[0]
    try:
        return date.fromisoformat(date_part)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# US exchange validation helpers
# ---------------------------------------------------------------------------
_US_EXCHANGE_SET: frozenset[str] = frozenset({
    "NASDAQ", "NYSE", "AMEX", "NYSEArca", "NYSEARCA",
    "BATS", "CBOE", "IEX", "NYSEMKT", "NYSE MKT",
    "NEW YORK STOCK EXCHANGE", "NASDAQ GLOBAL SELECT",
    "NASDAQ GLOBAL MARKET", "NASDAQ CAPITAL MARKET",
    "NYSE ARCA", "NYSE AMERICAN", "NYSEAMERICAN",
})

_LIKELY_US_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")


def _is_likely_us_equity_symbol(sym: str) -> bool:
    """Heuristic: reject symbols that are obviously non-US equity tickers.

    US equity tickers are 1-5 uppercase letters optionally followed by a dot
    and 1-2 letter share class (e.g. BRK.B, BF.A).
    """
    return bool(_LIKELY_US_SYMBOL_RE.fullmatch(sym))


def _epoch_to_datetime_utc(value: Any) -> datetime | None:
    try:
        if value is None:
            return None
        ts = float(value)
        if ts > 10_000_000_000:  # likely ms epoch
            ts /= 1000.0
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _build_mover_seed(client: FMPClient, max_symbols: int) -> list[str]:
    safe_limit = max(0, int(max_symbols))
    if safe_limit == 0:
        return []
    rows: list[dict[str, Any]] = []
    rows.extend(client.get_premarket_movers())
    rows.extend(client.get_biggest_gainers())
    rows.extend(client.get_biggest_losers())
    # Filter to US exchanges only.  Mover endpoints may include OTC/foreign
    # ADRs.  If the response carries an exchange field we validate it; if not,
    # we accept the symbol (fail-open) but reject obviously non-US patterns.
    filtered: list[str] = []
    for row in rows:
        exchange = str(row.get("exchange") or row.get("exchangeShortName") or "").strip().upper()
        if exchange and exchange not in _US_EXCHANGE_SET:
            continue
        sym = _extract_symbol_from_row(row)
        if not sym:
            continue
        # Reject symbols with digits (ETN notes like "X26") or > 5 chars without
        # a dot (share class markers like BRK.B are fine).
        if not _is_likely_us_equity_symbol(sym):
            continue
        filtered.append(sym)
    symbols = _normalize_symbols(filtered)
    return symbols[:safe_limit]


def _compute_ext_hours_score(
    *,
    ext_change_pct: float | None,
    ext_vol_ratio: float,
    freshness_sec: float | None,
    spread_bps: float | None,
) -> float:
    change = 0.0 if ext_change_pct is None else max(min(ext_change_pct / 5.0, 3.0), -3.0)
    vol = max(min(ext_vol_ratio, 5.0), 0.0)
    if freshness_sec is None:
        freshness = -0.25
    else:
        freshness = max(min((PREMARKET_STALE_SECONDS - freshness_sec) / PREMARKET_STALE_SECONDS, 1.0), -1.0)
    spread_penalty = 0.0 if spread_bps is None else min(max(spread_bps / 25.0, 0.0), 2.0)
    # Normalized weights (sum to 1.0 before penalty deduction)
    score = (0.40 * change) + (0.30 * vol) + (0.30 * freshness) - (0.25 * spread_penalty)
    return round(max(min(score, 5.0), -5.0), 4)


def _fetch_earnings_today(client: FMPClient, today: date) -> dict[str, dict[str, Any]]:
    """Return today's earnings enrichment keyed by symbol.

    Stable earnings-calendar no longer guarantees a timing field (bmo/amc),
    so timing may be None. This helper also captures EPS/revenue estimate
    and actual values for surprise-based event-risk features.
    """
    data = client.get_earnings_calendar(today, today)
    result: dict[str, dict[str, Any]] = {}
    for item in data:
        sym = str(item.get("symbol") or "").strip().upper()
        if not sym:
            continue
        raw_time = str(item.get("time") or item.get("releaseTime") or "").strip().lower()
        eps_actual = _to_float(item.get("epsActual"), default=float("nan"))
        eps_estimate = _to_float(item.get("epsEstimated"), default=float("nan"))
        rev_actual = _to_float(item.get("revenueActual"), default=float("nan"))
        rev_estimate = _to_float(item.get("revenueEstimated"), default=float("nan"))

        eps_surprise_pct: float | None = None
        if eps_actual == eps_actual and eps_estimate == eps_estimate and abs(eps_estimate) > 0.0:
            eps_surprise_pct = ((eps_actual - eps_estimate) / abs(eps_estimate)) * 100.0

        rev_surprise_pct: float | None = None
        if rev_actual == rev_actual and rev_estimate == rev_estimate and abs(rev_estimate) > 0.0:
            rev_surprise_pct = ((rev_actual - rev_estimate) / abs(rev_estimate)) * 100.0

        result[sym] = {
            "earnings_timing": raw_time or None,
            "eps_actual": None if eps_actual != eps_actual else eps_actual,
            "eps_estimate": None if eps_estimate != eps_estimate else eps_estimate,
            "eps_surprise_pct": eps_surprise_pct,
            "revenue_actual": None if rev_actual != rev_actual else rev_actual,
            "revenue_estimate": None if rev_estimate != rev_estimate else rev_estimate,
            "revenue_surprise_pct": rev_surprise_pct,
        }
    return result


def _fetch_corporate_action_flags(
    *,
    client: FMPClient,
    symbols: list[str],
    today: date,
    window_days: int = CORPORATE_ACTION_WINDOW_DAYS,
) -> dict[str, dict[str, Any]]:
    start = today - timedelta(days=max(int(window_days), 0))
    end = today + timedelta(days=max(int(window_days), 0))
    out: dict[str, dict[str, Any]] = {
        sym: {
            "split_today": False,
            "dividend_today": False,
            "ipo_window": False,
            "corporate_action_penalty": 0.0,
        }
        for sym in symbols
    }

    splits = client.get_splits_calendar(start, end)
    split_symbols_today: set[str] = set()
    for row in splits:
        sym = _extract_symbol_from_row(row)
        d = _parse_calendar_date(row.get("date"))
        if sym and d == today:
            split_symbols_today.add(sym)

    dividends = client.get_dividends_calendar(start, end)
    dividend_symbols_today: set[str] = set()
    for row in dividends:
        sym = _extract_symbol_from_row(row)
        d = _parse_calendar_date(row.get("date"))
        if sym and d == today:
            dividend_symbols_today.add(sym)

    ipos = client.get_ipos_calendar(start, end)
    ipo_window_symbols: set[str] = set()
    for row in ipos:
        sym = _extract_symbol_from_row(row)
        if sym:
            ipo_window_symbols.add(sym)

    for sym in symbols:
        split_today = sym in split_symbols_today
        dividend_today = sym in dividend_symbols_today
        ipo_window = sym in ipo_window_symbols
        penalty = 0.0
        if split_today:
            penalty += 1.25
        if dividend_today:
            penalty += 0.35
        if ipo_window:
            penalty += 0.85
        out[sym] = {
            "split_today": split_today,
            "dividend_today": dividend_today,
            "ipo_window": ipo_window,
            "corporate_action_penalty": round(penalty, 4),
        }

    return out


def _classify_upgrade_downgrade_action(action: str) -> tuple[str, str]:
    """Classify an analyst action into (emoji, label).

    Returns:
        🟢  for upgrades / positive revisions
        🟡  for maintains / reiterates / initiates (neutral)
        🔴  for downgrades / negative revisions
    """
    normalized = str(action or "").strip().lower()
    if normalized in {
        "upgrade",
        "upgraded",
        "raises",
        "raised",
        "boost",
        "boosted",
        "positive",
    }:
        return "🟢", "upgrade"
    if normalized in {
        "downgrade",
        "downgraded",
        "lowers",
        "lowered",
        "reduces",
        "reduced",
        "negative",
    }:
        return "🔴", "downgrade"
    # Neutral / hold actions
    return "🟡", "neutral"


def _fetch_upgrades_downgrades(
    *,
    client: FMPClient,
    symbols: list[str],
    today: date,
    lookback_days: int = 3,
) -> dict[str, dict[str, Any]]:
    """Fetch recent analyst upgrades/downgrades and classify per symbol.

    Returns a dict keyed by symbol with the most recent action per symbol.
    Only symbols in the provided universe are returned.
    """
    date_from = today - timedelta(days=max(int(lookback_days), 1))
    try:
        raw = client.get_upgrades_downgrades(date_from=date_from, date_to=today)
    except Exception as exc:
        logger.warning("Upgrades/downgrades fetch failed: %s", exc)
        return {}

    universe_set = {s.upper() for s in symbols}
    # Group by symbol, keep chronological order (newest first)
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in raw:
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym or sym not in universe_set:
            continue
        by_symbol.setdefault(sym, []).append(row)

    result: dict[str, dict[str, Any]] = {}
    for sym, rows in by_symbol.items():
        # Take the most recent entry (FMP returns newest first)
        latest = rows[0]
        action = str(latest.get("action") or latest.get("newGrade") or "").strip()
        emoji, label = _classify_upgrade_downgrade_action(action)
        result[sym] = {
            "upgrade_downgrade_emoji": emoji,
            "upgrade_downgrade_label": label,
            "upgrade_downgrade_action": action,
            "upgrade_downgrade_firm": str(latest.get("gradingCompany") or latest.get("company") or "").strip(),
            "upgrade_downgrade_prev_grade": str(latest.get("previousGrade") or "").strip() or None,
            "upgrade_downgrade_new_grade": str(latest.get("newGrade") or "").strip() or None,
            "upgrade_downgrade_date": str(latest.get("publishedDate") or latest.get("date") or "").strip() or None,
            "upgrade_downgrade_count": len(rows),
        }
    return result


def _fetch_sector_performance(client: FMPClient) -> list[dict[str, Any]]:
    """Fetch sector performance and sort by changesPercentage (desc).

    Returns list of dicts with: sector, changesPercentage, sector_emoji.
    """
    try:
        raw = client.get_sector_performance()
    except Exception as exc:
        logger.warning("Sector performance fetch failed: %s", exc)
        return []

    sectors: list[dict[str, Any]] = []
    for row in raw:
        sector = str(row.get("sector") or "").strip()
        change_pct = _to_float(row.get("changesPercentage"), default=0.0)
        if not sector:
            continue
        if change_pct > 0.5:
            emoji = "🟢"
        elif change_pct < -0.5:
            emoji = "🔴"
        else:
            emoji = "🟡"
        sectors.append({
            "sector": sector,
            "changesPercentage": round(change_pct, 4),
            "sector_emoji": emoji,
        })

    sectors.sort(key=lambda r: r.get("changesPercentage", 0.0), reverse=True)
    return sectors


# ---------------------------------------------------------------------------
# Insider trading enrichment (Ultimate-tier)
# ---------------------------------------------------------------------------

def _fetch_insider_trading(
    *,
    client: FMPClient,
    symbols: list[str],
    limit_per_symbol: int = 5,
) -> dict[str, dict[str, Any]]:
    """Fetch recent insider trades, aggregate buy/sell by symbol.

    Returns a dict keyed by symbol with insider-trade summary fields.
    Only symbols in the provided universe are returned.
    """
    universe_set = {s.upper() for s in symbols}
    result: dict[str, dict[str, Any]] = {}

    # Fetch broad market activity first (faster than per-symbol)
    try:
        raw = client.get_insider_trading_latest(limit=500)
    except Exception as exc:
        logger.warning("Insider trading fetch failed: %s", exc)
        return {}

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in raw:
        sym = str(row.get("symbol") or "").strip().upper()
        if sym and sym in universe_set:
            by_symbol.setdefault(sym, []).append(row)

    for sym, rows in by_symbol.items():
        buys = sum(
            1 for r in rows
            if str(r.get("transactionType") or "").lower() in ("p-purchase", "purchase", "p")
        )
        sells = sum(
            1 for r in rows
            if str(r.get("transactionType") or "").lower() in ("s-sale", "sale", "s")
        )
        total_value_bought = sum(
            _to_float(r.get("securitiesTransacted")) * _to_float(r.get("price"))
            for r in rows
            if str(r.get("transactionType") or "").lower() in ("p-purchase", "purchase", "p")
        )
        total_value_sold = sum(
            _to_float(r.get("securitiesTransacted")) * _to_float(r.get("price"))
            for r in rows
            if str(r.get("transactionType") or "").lower() in ("s-sale", "sale", "s")
        )

        if buys > sells:
            emoji = "🟢"
            sentiment = "net_buy"
        elif sells > buys:
            emoji = "🔴"
            sentiment = "net_sell"
        else:
            emoji = "🟡"
            sentiment = "neutral"

        result[sym] = {
            "insider_buys": buys,
            "insider_sells": sells,
            "insider_net": buys - sells,
            "insider_sentiment": sentiment,
            "insider_emoji": emoji,
            "insider_total_bought_value": round(total_value_bought, 2),
            "insider_total_sold_value": round(total_value_sold, 2),
            "insider_trade_count": len(rows),
        }

    return result


# ---------------------------------------------------------------------------
# Institutional ownership enrichment (Ultimate-tier, 13F)
# ---------------------------------------------------------------------------
_MAX_INST_OWNERSHIP_LOOKUPS = 30  # Cap API calls for institutional data


def _fetch_institutional_ownership(
    *,
    client: FMPClient,
    symbols: list[str],
    limit_per_symbol: int = 5,
) -> dict[str, dict[str, Any]]:
    """Fetch institutional ownership (13F) data for top symbols.

    Returns dict keyed by symbol with ownership fields.
    """
    result: dict[str, dict[str, Any]] = {}
    cap = min(len(symbols), _MAX_INST_OWNERSHIP_LOOKUPS)

    for sym in symbols[:cap]:
        sym = str(sym).strip().upper()
        if not sym:
            continue
        try:
            rows = client.get_institutional_ownership(sym, limit=limit_per_symbol)
        except Exception as exc:
            logger.debug("Institutional ownership fetch failed for %s: %s", sym, exc)
            continue
        if not rows:
            continue

        # Calculate aggregate metrics from most recent filings
        total_shares = sum(int(r.get("shares", 0) or 0) for r in rows)
        top_holders = [
            str(r.get("investorName") or r.get("holderName") or "").strip()
            for r in rows[:3]
            if r.get("investorName") or r.get("holderName")
        ]

        result[sym] = {
            "inst_ownership_holders": len(rows),
            "inst_ownership_total_shares": total_shares,
            "inst_ownership_top_holders": top_holders,
        }

    return result


# ---------------------------------------------------------------------------
# Symbol → Sector enrichment (profile fallback for mover-seeded symbols)
# ---------------------------------------------------------------------------
_MIN_GAP_FOR_SECTOR_LOOKUP = 0.3  # Only fetch profiles for symbols gapping ≥ 0.3 %
_MAX_SECTOR_PROFILE_LOOKUPS = 80  # Cap to avoid excessive API usage
_SECTOR_PROFILE_WORKERS = 10  # Parallel workers for profile lookups


def _enrich_symbol_sectors_from_profiles(
    *,
    client: FMPClient,
    quotes: list[dict[str, Any]],
    symbol_sectors: dict[str, str],
) -> None:
    """Fill gaps in *symbol_sectors* by fetching company profiles.

    Only symbols that already appear in *quotes* with a meaningful gap
    percentage (and whose sector is unknown) are looked up.  Candidates are
    sorted by absolute gap (largest first) so the most likely scored
    candidates get sector data within the lookup cap.  *symbol_sectors* is
    mutated in-place.
    """
    candidates: list[tuple[float, str]] = []
    for q in quotes:
        sym = str(q.get("symbol") or "").strip().upper()
        if not sym or sym in symbol_sectors:
            continue
        # Use enriched gap_pct (set by apply_gap_mode_to_quotes) if available,
        # fall back to raw changesPercentage from the quote.
        gap = abs(_to_float(
            q.get("gap_pct") or q.get("changesPercentage"),
            default=0.0,
        ))
        if gap >= _MIN_GAP_FOR_SECTOR_LOOKUP:
            candidates.append((gap, sym))

    if not candidates:
        return

    # Sort by absolute gap descending so the biggest movers (most likely to
    # be scored) get sector data first, in case we hit the cap.
    candidates.sort(reverse=True)
    lookup = [sym for _, sym in candidates[:_MAX_SECTOR_PROFILE_LOOKUPS]]

    def _fetch_one(sym: str) -> tuple[str, str | None]:
        try:
            profile = client.get_company_profile(sym)
            sector = str(profile.get("sector") or "").strip()
            return sym, sector if sector else None
        except Exception:
            return sym, None

    fetched = 0
    workers = max(1, min(_SECTOR_PROFILE_WORKERS, len(lookup)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for sym, sector in executor.map(_fetch_one, lookup):
            if sector:
                symbol_sectors[sym] = sector
                fetched += 1

    if fetched:
        logger.info(
            "Enriched %d/%d mover symbol(s) with sector from profile lookups.",
            fetched,
            len(lookup),
        )


def _extract_http_status_code(error_message: str) -> int | None:
    match = re.search(r"HTTP\s+(\d{3})", str(error_message or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _probe_fmp_endpoint(
    *,
    probe_client: FMPClient,
    feature: str,
    path: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Probe a single FMP endpoint and return normalized capability status.

    Expects a dedicated *probe_client* with ``retry_attempts=1`` to avoid
    full retry+backoff on endpoints that may be plan-limited or absent.
    This keeps the shared production client's state untouched (thread-safe).
    """
    try:
        probe_client._get(path, params)  # noqa: SLF001 - intentional internal probe
        return {
            "feature": feature,
            "status": "available",
            "http_status": 200,
            "detail": "Endpoint reachable",
        }
    except Exception as exc:
        msg = str(exc)
        code = _extract_http_status_code(msg)
        if code in {401, 402, 403}:
            status = "plan_limited"
        elif code == 404:
            status = "not_available"
        elif code is None:
            status = "error"
        else:
            status = "error"
        return {
            "feature": feature,
            "status": status,
            "http_status": code,
            "detail": msg,
        }


def _probe_data_capabilities(*, client: FMPClient, today: date) -> dict[str, dict[str, Any]]:
    """Probe optional/premium endpoints and return a capability map for UI."""
    ttl_seconds = max(
        int(_to_float(os.environ.get("OPEN_PREP_CAPABILITY_CACHE_TTL_SECONDS"), default=900.0)),
        0,
    )

    if ttl_seconds > 0 and CAPABILITY_CACHE_FILE.exists():
        try:
            payload = json.loads(CAPABILITY_CACHE_FILE.read_text(encoding="utf-8"))
            ts_raw = str(payload.get("cached_at_utc") or "")
            cached_at = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=UTC)
            age_seconds = max(int((datetime.now(UTC) - cached_at).total_seconds()), 0)
            cached_data = payload.get("data")
            if age_seconds <= ttl_seconds and isinstance(cached_data, dict):
                return cached_data
        except Exception:
            pass

    probes: list[tuple[str, str, dict[str, Any]]] = [
        ("eod_bulk", "/stable/eod-bulk", {"date": today.isoformat(), "datatype": "json"}),
        (
            "upgrades_downgrades",
            "/stable/grades",
            {"symbol": "AAPL"},
        ),
        ("sector_performance", "/stable/sector-performance-snapshot", {}),
        ("vix_quote", "/stable/quote", {"symbol": "^VIX"}),
        ("income_statement", "/stable/income-statement", {"symbol": "AAPL", "limit": 1}),
    ]

    out: dict[str, dict[str, Any]] = {}
    # Create a dedicated single-attempt client for probing so the shared
    # production client's retry_attempts field is never mutated.
    probe_client = FMPClient(
        api_key=client.api_key,
        base_url=client.base_url,
        timeout_seconds=client.timeout_seconds,
        retry_attempts=1,
    )
    for feature, path, params in probes:
        out[feature] = _probe_fmp_endpoint(
            probe_client=probe_client,
            feature=feature,
            path=path,
            params=params,
        )

    try:
        CAPABILITY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        import tempfile as _tempfile
        content = json.dumps(
            {
                "cached_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "ttl_seconds": ttl_seconds,
                "data": out,
            },
            sort_keys=True,
        )
        fd, tmp = _tempfile.mkstemp(dir=str(CAPABILITY_CACHE_DIR), suffix=".tmp")
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            fd = -1
            os.replace(tmp, str(CAPABILITY_CACHE_FILE))
        except BaseException:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        pass

    return out


def _summarize_data_capabilities(data_capabilities: dict[str, dict[str, Any]]) -> dict[str, Any]:
    statuses = [str((v or {}).get("status") or "error") for v in data_capabilities.values()]
    total = len(statuses)
    available = sum(1 for s in statuses if s == "available")
    plan_limited = sum(1 for s in statuses if s == "plan_limited")
    not_available = sum(1 for s in statuses if s == "not_available")
    errors = sum(1 for s in statuses if s == "error")
    unavailable = total - available
    return {
        "total": total,
        "available": available,
        "unavailable": unavailable,
        "plan_limited": plan_limited,
        "not_available": not_available,
        "errors": errors,
        "coverage_ratio": round((available / total), 4) if total > 0 else 0.0,
    }


def _fetch_analyst_catalyst(
    *,
    client: FMPClient,
    symbols: list[str],
    limit: int,
) -> dict[str, dict[str, Any]]:
    safe_limit = max(0, min(int(limit), len(symbols)))
    if safe_limit == 0:
        return {}

    batch = symbols[:safe_limit]

    def _single(sym: str) -> tuple[str, dict[str, Any] | None]:
        try:
            row = client.get_price_target_summary(sym)
            if not row:
                return sym, None
            avg_target = _to_float(
                row.get("lastQuarterAvgPriceTarget") or row.get("lastYearAvgPriceTarget"),
                default=float("nan"),
            )
            coverage = _to_float(
                row.get("lastQuarterCount") or row.get("lastYearCount") or row.get("allTimeCount"),
                default=0.0,
            )
            catalyst = 0.0
            if avg_target == avg_target and coverage > 0.0:
                catalyst = min(max((coverage / 10.0), 0.0), 2.0)
            return sym, {
                "analyst_price_target": None if avg_target != avg_target else avg_target,
                "analyst_coverage_count": int(max(coverage, 0.0)),
                "analyst_catalyst_score": round(catalyst, 4),
            }
        except Exception:
            return sym, None

    result: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        for sym, data in executor.map(lambda s: _single(s), batch):
            if data is not None:
                result[sym] = data

    return result


def _fetch_earnings_distance_features(
    *,
    client: FMPClient,
    symbols: list[str],
    today: date,
    max_symbols: int = 120,
) -> dict[str, dict[str, Any]]:
    safe_max = max(0, min(int(max_symbols), len(symbols)))
    if safe_max == 0:
        return {}

    batch = symbols[:safe_max]

    def _single(sym: str) -> tuple[str, dict[str, Any] | None]:
        try:
            rows = client.get_earnings_report(sym, limit=12)
            dates: list[date] = []
            for row in rows:
                d = _parse_calendar_date(row.get("date"))
                if d is not None:
                    dates.append(d)
            if not dates:
                return sym, None
            past = sorted([d for d in dates if d <= today])
            future = sorted([d for d in dates if d > today])

            days_since_last = (today - past[-1]).days if past else None
            days_to_next = (future[0] - today).days if future else None
            earnings_risk = False
            if days_since_last is not None and days_since_last <= 1:
                earnings_risk = True
            if days_to_next is not None and days_to_next <= 1:
                earnings_risk = True

            return sym, {
                "days_since_last_earnings": days_since_last,
                "days_to_next_earnings": days_to_next,
                "earnings_risk_window": earnings_risk,
            }
        except Exception:
            return sym, None

    out: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        for sym, data in executor.map(lambda s: _single(s), batch):
            if data is not None:
                out[sym] = data
    return out


def _fetch_premarket_context(
    *,
    client: FMPClient,
    symbols: list[str],
    today: date,
    run_dt_utc: datetime,
    mover_seed_max_symbols: int,
    analyst_catalyst_limit: int,
    cached_mover_seed: list[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Fetch pre-market enrichment data: earnings timing + premarket movers.

    If *cached_mover_seed* is provided (non-empty), skip the expensive
    re-fetch of mover endpoints (saves 3 API calls / ~6s).

    Returns (premarket_by_symbol, error_message_or_none).
    """
    premarket: dict[str, dict[str, Any]] = {sym: {} for sym in symbols}
    errors: list[str] = []

    # --- Earnings calendar ---
    try:
        earnings_today = _fetch_earnings_today(client, today)
        for sym in symbols:
            event = earnings_today.get(sym, {})
            timing = event.get("earnings_timing")
            premarket[sym]["earnings_today"] = bool(event)
            premarket[sym]["earnings_timing"] = timing
            premarket[sym]["eps_actual"] = event.get("eps_actual")
            premarket[sym]["eps_estimate"] = event.get("eps_estimate")
            premarket[sym]["eps_surprise_pct"] = event.get("eps_surprise_pct")
            premarket[sym]["revenue_actual"] = event.get("revenue_actual")
            premarket[sym]["revenue_estimate"] = event.get("revenue_estimate")
            premarket[sym]["revenue_surprise_pct"] = event.get("revenue_surprise_pct")
    except Exception as exc:
        logger.warning("Earnings calendar fetch failed: %s", exc)
        errors.append(f"earnings_calendar: {exc}")
        for sym in symbols:
            premarket[sym]["earnings_today"] = False
            premarket[sym]["earnings_timing"] = None

    try:
        earnings_distance = _fetch_earnings_distance_features(
            client=client,
            symbols=symbols,
            today=today,
            max_symbols=max(analyst_catalyst_limit, 0),
        )
        for sym in symbols:
            premarket[sym].update(
                earnings_distance.get(
                    sym,
                    {
                        "days_since_last_earnings": None,
                        "days_to_next_earnings": None,
                        "earnings_risk_window": False,
                    },
                )
            )
    except Exception as exc:
        logger.warning("Earnings-distance fetch failed: %s", exc)
        errors.append(f"earnings_distance: {exc}")
        for sym in symbols:
            premarket[sym].setdefault("days_since_last_earnings", None)
            premarket[sym].setdefault("days_to_next_earnings", None)
            premarket[sym].setdefault("earnings_risk_window", False)

    # --- Corporate action event-risk (splits/dividends/IPO window) ---
    try:
        corp = _fetch_corporate_action_flags(
            client=client,
            symbols=symbols,
            today=today,
            window_days=CORPORATE_ACTION_WINDOW_DAYS,
        )
        for sym in symbols:
            premarket[sym].update(corp.get(sym, {}))
    except Exception as exc:
        logger.warning("Corporate-action fetch failed: %s", exc)
        errors.append(f"corporate_actions: {exc}")
        for sym in symbols:
            premarket[sym].setdefault("split_today", False)
            premarket[sym].setdefault("dividend_today", False)
            premarket[sym].setdefault("ipo_window", False)
            premarket[sym].setdefault("corporate_action_penalty", 0.0)

    # --- Analyst catalyst ---
    try:
        analyst = _fetch_analyst_catalyst(
            client=client,
            symbols=symbols,
            limit=analyst_catalyst_limit,
        )
        for sym in symbols:
            premarket[sym].update(
                analyst.get(
                    sym,
                    {
                        "analyst_price_target": None,
                        "analyst_coverage_count": 0,
                        "analyst_catalyst_score": 0.0,
                    },
                )
            )
    except Exception as exc:
        logger.warning("Analyst catalyst fetch failed: %s", exc)
        errors.append(f"analyst_catalyst: {exc}")
        for sym in symbols:
            premarket[sym].setdefault("analyst_price_target", None)
            premarket[sym].setdefault("analyst_coverage_count", 0)
            premarket[sym].setdefault("analyst_catalyst_score", 0.0)

    # --- Extended-hours activity via stable endpoints ---
    try:
        # Reuse cached mover seed if available to avoid 3 redundant API calls.
        if cached_mover_seed:
            mover_seed = cached_mover_seed
        else:
            mover_seed = _build_mover_seed(client, mover_seed_max_symbols)
        mover_seed_set = set(mover_seed)
        union_symbols = _normalize_symbols(symbols + mover_seed)
        if len(union_symbols) > MAX_PREMARKET_UNION_SYMBOLS:
            union_symbols = union_symbols[:MAX_PREMARKET_UNION_SYMBOLS]

        after_quotes = client.get_batch_aftermarket_quote(union_symbols)
        after_map: dict[str, dict[str, Any]] = {}
        for row in after_quotes:
            sym = str(row.get("symbol") or "").strip().upper()
            if sym:
                after_map[sym] = row

        after_trades = client.get_batch_aftermarket_trade(union_symbols)
        trade_map: dict[str, dict[str, Any]] = {}
        for row in after_trades:
            sym = str(row.get("symbol") or "").strip().upper()
            if sym:
                trade_map[sym] = row

        # Fetch spot quotes to derive change % against previousClose.
        spot_quotes = client.get_batch_quotes(union_symbols)
        prev_close_map: dict[str, float] = {}
        avg_volume_map: dict[str, float] = {}
        for row in spot_quotes:
            sym = str(row.get("symbol") or "").strip().upper()
            if not sym:
                continue
            prev_close_map[sym] = _to_float(row.get("previousClose"), default=0.0)
            avg_volume_map[sym] = _to_float(row.get("avgVolume"), default=0.0)

        for sym in symbols:
            aq = after_map.get(sym, {})
            at = trade_map.get(sym, {})

            bid = _to_float(aq.get("bidPrice"), default=0.0)
            ask = _to_float(aq.get("askPrice"), default=0.0)
            quote_volume = _to_float(aq.get("volume"), default=float("nan"))
            trade_size = _to_float(at.get("tradeSize"), default=float("nan"))

            quote_ts = _epoch_to_datetime_utc(aq.get("timestamp"))
            trade_ts = _epoch_to_datetime_utc(at.get("timestamp"))
            last_trade_ts = trade_ts or quote_ts
            freshness_sec: float | None = None
            if last_trade_ts is not None:
                freshness_sec = max((run_dt_utc - last_trade_ts).total_seconds(), 0.0)

            stale = freshness_sec is not None and freshness_sec > PREMARKET_STALE_SECONDS

            trade_price = _to_float(at.get("price"), default=0.0)
            if bid > 0.0 and ask > 0.0:
                mid_px = (bid + ask) / 2.0
                spread_bps: float | None = ((ask - bid) / mid_px) * 10_000.0 if mid_px > 0.0 else None
            else:
                mid_px = ask if ask > 0.0 else bid if bid > 0.0 else 0.0
                spread_bps = None

            after_px_raw = trade_price if trade_price > 0.0 else mid_px
            after_px = 0.0 if stale else after_px_raw

            ext_volume = 0.0
            if quote_volume == quote_volume and quote_volume > 0.0:
                ext_volume = max(ext_volume, quote_volume)
            if trade_size == trade_size and trade_size > 0.0:
                ext_volume = max(ext_volume, trade_size)

            prev_close = prev_close_map.get(sym, 0.0)
            avg_volume = avg_volume_map.get(sym, 0.0)
            change_pct: float | None = None
            if after_px > 0.0 and prev_close > 0.0:
                change_pct = ((after_px - prev_close) / prev_close) * 100.0

            ext_vol_ratio = (ext_volume / avg_volume) if avg_volume > 0.0 else 0.0
            ext_hours_score = _compute_ext_hours_score(
                ext_change_pct=change_pct,
                ext_vol_ratio=ext_vol_ratio,
                freshness_sec=freshness_sec,
                spread_bps=spread_bps,
            )

            is_active = sym in mover_seed_set
            has_ext_activity = after_px > 0.0 or ext_volume > 0.0
            premarket[sym]["mover_seed_hit"] = is_active
            premarket[sym]["premarket_stale"] = bool(stale)
            premarket[sym]["is_premarket_mover"] = bool(
                is_active
                or (has_ext_activity and not stale)
                or ext_vol_ratio >= 0.10
            )
            premarket[sym]["premarket_change_pct"] = change_pct
            premarket[sym]["premarket_price"] = after_px if after_px > 0.0 else None
            premarket[sym]["premarket_price_raw"] = after_px_raw if after_px_raw > 0.0 else None
            premarket[sym]["premarket_volume"] = ext_volume if ext_volume > 0.0 else None
            premarket[sym]["premarket_trade_price"] = trade_price if trade_price > 0.0 else None
            premarket[sym]["premarket_last_trade_ts_utc"] = (
                None if last_trade_ts is None else last_trade_ts.isoformat()
            )
            premarket[sym]["premarket_freshness_sec"] = None if freshness_sec is None else round(freshness_sec, 2)
            premarket[sym]["premarket_spread_bps"] = None if spread_bps is None else round(spread_bps, 4)
            premarket[sym]["ext_volume_ratio"] = round(ext_vol_ratio, 6)
            premarket[sym]["ext_hours_score"] = ext_hours_score
    except Exception as exc:
        logger.warning("Premarket movers fetch failed: %s", exc)
        errors.append(f"premarket_movers: {exc}")
        for sym in symbols:
            premarket[sym].setdefault("is_premarket_mover", False)
            premarket[sym].setdefault("mover_seed_hit", False)
            premarket[sym].setdefault("premarket_stale", False)
            premarket[sym].setdefault("premarket_freshness_sec", None)
            premarket[sym].setdefault("premarket_spread_bps", None)
            premarket[sym].setdefault("ext_volume_ratio", 0.0)
            premarket[sym].setdefault("ext_hours_score", 0.0)

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
    gap_scope: str = GAP_SCOPE_DAILY,
) -> dict[str, Any]:
    """Compute session-gap value and metadata according to selected mode."""
    ny_now = run_dt_utc.astimezone(US_EASTERN_TZ)
    ny_date = ny_now.date()
    is_gap_session = _is_gap_day(ny_date, gap_scope)
    is_stretch_session = _is_first_session_after_non_trading_stretch(ny_date)
    prev_day = _prev_trading_day(ny_date)
    gap_from_ts = datetime.combine(prev_day, datetime.min.time(), tzinfo=US_EASTERN_TZ).replace(
        hour=16, minute=0, second=0, microsecond=0
    ).astimezone(UTC).isoformat()

    prev_close = _to_float(quote.get("previousClose"), default=0.0)
    if prev_close <= 0.0:
        fallback_gap = _to_float(
            quote.get("changesPercentage") or quote.get("changePercentage"),
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
            "gap_scope": gap_scope,
            "is_stretch_session": is_stretch_session,
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
            "gap_scope": gap_scope,
            "is_stretch_session": is_stretch_session,
        }

    if not is_gap_session:
        # Compute overnight gap for reference even on non-gap sessions.
        overnight_gap_pct: float | None = None
        overnight_gap_source: str | None = None
        if prev_close > 0.0:
            _ind_px, _ind_src = _pick_indicative_price(quote)
            if _ind_px > 0.0:
                overnight_gap_pct = round(((_ind_px - prev_close) / prev_close) * 100.0, 6)
                overnight_gap_source = _ind_src
        reason = "not_trading_day" if not _is_us_equity_trading_day(ny_date) else "scope_stretch_only"
        return {
            "gap_pct": 0.0,
            "gap_type": GAP_MODE_OFF,
            "gap_available": False,
            "gap_from_ts": gap_from_ts,
            "gap_to_ts": None,
            "gap_mode_selected": gap_mode,
            "gap_price_source": None,
            "gap_reason": reason,
            "gap_scope": gap_scope,
            "is_stretch_session": is_stretch_session,
            "overnight_gap_pct": overnight_gap_pct,
            "overnight_gap_source": overnight_gap_source,
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
                "gap_scope": gap_scope,
                "is_stretch_session": is_stretch_session,
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
            "gap_scope": gap_scope,
            "is_stretch_session": is_stretch_session,
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
                "gap_scope": gap_scope,
                "is_stretch_session": is_stretch_session,
            }
        # Stale guard: pure "price" fallback without timestamp may be stale.
        if px_source == "spot" and quote_ts is None:
            return {
                "gap_pct": 0.0,
                "gap_type": GAP_MODE_OFF,
                "gap_available": False,
                "gap_from_ts": gap_from_ts,
                "gap_to_ts": None,
                "gap_mode_selected": gap_mode,
                "gap_price_source": px_source,
                "gap_reason": "stale_quote_unknown_timestamp",
                "gap_scope": gap_scope,
                "is_stretch_session": is_stretch_session,
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
            "gap_scope": gap_scope,
            "is_stretch_session": is_stretch_session,
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
        "gap_scope": gap_scope,
        "is_stretch_session": is_stretch_session,
    }


def apply_gap_mode_to_quotes(
    quotes: list[dict[str, Any]],
    *,
    run_dt_utc: datetime,
    gap_mode: str,
    gap_scope: str = GAP_SCOPE_DAILY,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mode = str(gap_mode or GAP_MODE_PREMARKET_INDICATIVE).strip().upper()
    if mode not in GAP_MODE_CHOICES:
        raise ValueError(f"Unsupported gap mode: {gap_mode}")
    scope = str(gap_scope or GAP_SCOPE_DAILY).strip().upper()
    if scope not in GAP_SCOPE_CHOICES:
        raise ValueError(f"Unsupported gap scope: {gap_scope}")

    for quote in quotes:
        row = dict(quote)
        gap_meta = _compute_gap_for_quote(row, run_dt_utc=run_dt_utc, gap_mode=mode, gap_scope=scope)
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

    if len(parsed) < period_eff:  # Need at least `period` bars for first ATR seed
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


def _atr_cache_file(as_of: date, period: int) -> Path:
    return ATR_CACHE_DIR / f"{as_of.isoformat()}_p{max(int(period),1)}.json"


def _load_atr_cache(as_of: date, period: int) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    path = _atr_cache_file(as_of, period)
    if not path.exists():
        return {}, {}, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        atr_map = {
            str(k).upper(): val
            for k, v in dict(payload.get("atr14_by_symbol", {})).items()
            if (val := _to_float(v, default=0.0)) > 0.0
        }
        momentum_map = {
            str(k).upper(): _to_float(v, default=0.0)
            for k, v in dict(payload.get("momentum_z_by_symbol", {})).items()
            if str(k).upper() in atr_map
        }
        prev_close_map = {
            str(k).upper(): _to_float(v, default=0.0)
            for k, v in dict(payload.get("prev_close_by_symbol", {})).items()
            if str(k).upper() in atr_map
        }
        return atr_map, momentum_map, prev_close_map
    except Exception:
        return {}, {}, {}


def _evict_stale_cache_files(cache_dir: Path, *, max_age_days: int = 7) -> None:
    """Remove cache files older than *max_age_days* to prevent unbounded disk growth."""
    import time as _time_mod
    cutoff = _time_mod.time() - max_age_days * 86400
    try:
        for entry in cache_dir.iterdir():
            if entry.suffix in {".json", ".tmp"} and entry.is_file():
                try:
                    if entry.stat().st_mtime < cutoff:
                        entry.unlink(missing_ok=True)
                except OSError:
                    pass
    except OSError:
        pass


def _save_atr_cache(
    *,
    as_of: date,
    period: int,
    atr_map: dict[str, float],
    momentum_map: dict[str, float],
    prev_close_map: dict[str, float],
) -> None:
    try:
        ATR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        clean_atr_map = {
            str(k).upper(): _to_float(v, default=0.0)
            for k, v in atr_map.items()
            if _to_float(v, default=0.0) > 0.0
        }
        clean_momentum_map = {
            str(k).upper(): _to_float(momentum_map.get(k), default=0.0)
            for k in clean_atr_map
        }
        clean_prev_close_map = {
            str(k).upper(): _to_float(prev_close_map.get(k), default=0.0)
            for k in clean_atr_map
        }

        payload = {
            "as_of": as_of.isoformat(),
            "atr_period": int(period),
            "atr14_by_symbol": clean_atr_map,
            "momentum_z_by_symbol": clean_momentum_map,
            "prev_close_by_symbol": clean_prev_close_map,
        }
        target = _atr_cache_file(as_of, period)
        import tempfile as _tempfile
        fd, tmp = _tempfile.mkstemp(dir=str(ATR_CACHE_DIR), suffix=".tmp")
        try:
            os.write(fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
            os.close(fd)
            fd = -1  # mark as closed
            os.replace(tmp, str(target))
        except BaseException:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # Evict stale cache files (> 7 days old) to prevent unbounded growth.
        _evict_stale_cache_files(ATR_CACHE_DIR, max_age_days=7)
    except Exception:
        # Cache is an optimization. Never break pipeline on cache I/O errors.
        return


def _incremental_atr_from_eod_bulk(
    *,
    client: FMPClient,
    symbols: list[str],
    as_of: date,
    atr_period: int,
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    prev_day = _prev_trading_day(as_of)
    prev_atr_map, prev_momentum_map, prev_close_map = _load_atr_cache(prev_day, atr_period)
    if not prev_atr_map or not prev_close_map:
        return {}, {}, {}

    eod_rows = client.get_eod_bulk(as_of)
    by_symbol: dict[str, dict[str, Any]] = {}
    for row_eod in eod_rows:
        sym = str(row_eod.get("symbol") or "").strip().upper()
        if sym:
            by_symbol[sym] = row_eod

    atr_map: dict[str, float] = {}
    momentum_map: dict[str, float] = {}
    close_map: dict[str, float] = {}
    n = max(int(atr_period), 1)

    for sym in symbols:
        prev_atr = _to_float(prev_atr_map.get(sym), default=0.0)
        prev_close = _to_float(prev_close_map.get(sym), default=0.0)
        eod_row = by_symbol.get(sym)
        if not eod_row or prev_atr <= 0.0 or prev_close <= 0.0:
            continue

        high = _to_float(eod_row.get("high"), default=float("nan"))
        low = _to_float(eod_row.get("low"), default=float("nan"))
        close = _to_float(eod_row.get("close"), default=float("nan"))
        if high != high or low != low or close != close:
            continue

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        atr = ((prev_atr * float(n - 1)) + max(tr, 0.0)) / float(n)
        atr_map[sym] = round(atr, 4)
        # NOTE: momentum_z carries over from prior-day cache (not re-calculated
        # intra-day).  This is acceptable for ranking but may lag by ~1 session.
        momentum_map[sym] = round(_to_float(prev_momentum_map.get(sym), default=0.0), 4)
        close_map[sym] = close

    return atr_map, momentum_map, close_map


def _fetch_symbol_atr(
    client: FMPClient,
    symbol: str,
    date_from: date,
    as_of: date,
    atr_period: int,
) -> tuple[str, float, float, float | None, str | None]:
    """Fetch historical candles and compute ATR for one symbol.

    Returns: (symbol, atr_value, momentum_z, vwap_or_none, error_message)
    """
    try:
        candles_raw = client.get_historical_price_eod_full(symbol, date_from, as_of)
        if isinstance(candles_raw, dict):
            maybe_hist = candles_raw.get("historical")
            candles = maybe_hist if isinstance(maybe_hist, list) else []
        elif isinstance(candles_raw, list):
            candles = candles_raw
        else:
            candles = []

        atr_value = _calculate_atr14_from_eod(candles, period=atr_period)
        momentum_z = _momentum_z_score_from_eod(candles, period=50)
        latest_vwap: float | None = None
        rows = [c for c in candles if str(c.get("date") or "")]
        if rows:
            rows.sort(key=lambda c: str(c.get("date") or ""))
            vwap_raw = _to_float(rows[-1].get("vwap"), default=0.0)
            latest_vwap = vwap_raw if vwap_raw > 0.0 else None
        if atr_value <= 0.0:
            return symbol, 0.0, momentum_z, latest_vwap, "atr_zero_or_insufficient_bars"
        return symbol, atr_value, momentum_z, latest_vwap, None
    except RuntimeError as exc:
        return symbol, 0.0, 0.0, None, str(exc)


def _atr14_by_symbol(
    client: FMPClient,
    symbols: list[str],
    as_of: date,
    lookback_days: int = 250,  # Increased for RMA convergence
    atr_period: int = 14,
    parallel_workers: int = 5,
) -> tuple[dict[str, float], dict[str, float], dict[str, float | None], dict[str, str]]:
    atr_map: dict[str, float] = {}
    momentum_z_map: dict[str, float] = {}
    vwap_map: dict[str, float | None] = {}
    errors: dict[str, str] = {}
    date_from = as_of - timedelta(days=max(lookback_days, 20))

    cached_atr, cached_momentum, cached_prev_close = _load_atr_cache(as_of, atr_period)
    if cached_atr:
        # Only populate symbols that actually have a positive cached ATR.
        # Do NOT set 0.0 for uncached symbols — that would prevent the
        # per-symbol fallback from recognising them as missing.
        for symbol in symbols:
            cached_val = cached_atr.get(symbol)
            if cached_val is not None and cached_val > 0.0:
                atr_map[symbol] = round(cached_val, 4)
                momentum_z_map[symbol] = round(
                    _to_float(cached_momentum.get(symbol), default=0.0), 4,
                )
        if all(sym in atr_map for sym in symbols):
            for symbol in symbols:
                vwap_map.setdefault(symbol, None)
            return atr_map, momentum_z_map, vwap_map, errors

    incremental_atr, incremental_momentum, incremental_close = _incremental_atr_from_eod_bulk(
        client=client,
        symbols=symbols,
        as_of=as_of,
        atr_period=atr_period,
    )
    atr_map.update(incremental_atr)
    momentum_z_map.update(incremental_momentum)

    missing_symbols = [sym for sym in symbols if sym not in atr_map]
    if missing_symbols:
        workers = max(1, min(int(parallel_workers), max(1, len(missing_symbols))))
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
                for symbol in missing_symbols
            }
            for future in as_completed(future_map):
                symbol = future_map[future]
                try:
                    sym, atr_value, momentum_z, vwap_value, err = future.result()
                    atr_map[sym] = atr_value
                    momentum_z_map[sym] = momentum_z
                    vwap_map[sym] = vwap_value
                    if err:
                        errors[sym] = err
                except Exception as exc:  # pragma: no cover - defensive catch
                    atr_map[symbol] = 0.0
                    momentum_z_map[symbol] = 0.0
                    vwap_map[symbol] = None
                    errors[symbol] = str(exc)

    # Keep deterministic key presence/order compatibility.
    for symbol in symbols:
        atr_map.setdefault(symbol, 0.0)
        momentum_z_map.setdefault(symbol, 0.0)
        vwap_map.setdefault(symbol, None)

    # Save same-day cache to accelerate subsequent pre-open runs.
    prev_close_snapshot: dict[str, float] = dict(cached_prev_close)
    prev_close_snapshot.update(incremental_close)
    if len(prev_close_snapshot) < len(symbols):
        try:
            batch_quotes = client.get_batch_quotes(symbols)
            for row in batch_quotes:
                sym = str(row.get("symbol") or "").strip().upper()
                if not sym:
                    continue
                prev_close_snapshot[sym] = _to_float(row.get("previousClose"), default=0.0)
        except Exception:
            pass

    _save_atr_cache(
        as_of=as_of,
        period=atr_period,
        atr_map=atr_map,
        momentum_map=momentum_z_map,
        prev_close_map=prev_close_snapshot,
    )

    return atr_map, momentum_z_map, vwap_map, errors


# ---------------------------------------------------------------------------
# Premarket High/Low (PMH/PML) from intraday bars
# ---------------------------------------------------------------------------

def _parse_bar_dt_utc(bar: dict[str, Any]) -> datetime | None:
    """Parse an intraday bar's date/datetime field → UTC datetime."""
    raw = str(bar.get("date") or bar.get("datetime") or "").strip()
    if not raw:
        return None
    # ISO first
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            naive_mode = str(os.environ.get("OPEN_PREP_INTRADAY_NAIVE_TZ", "NY")).strip().upper()
            if naive_mode in {"UTC", "Z"}:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.replace(tzinfo=US_EASTERN_TZ)
        return dt.astimezone(UTC)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            naive_mode = str(os.environ.get("OPEN_PREP_INTRADAY_NAIVE_TZ", "NY")).strip().upper()
            if naive_mode in {"UTC", "Z"}:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.replace(tzinfo=US_EASTERN_TZ)
            return dt.astimezone(UTC)
        except ValueError:
            continue
    return None


def compute_premarket_high_low(
    bars: list[dict[str, Any]],
    session_day_ny: date,
) -> tuple[float | None, float | None]:
    """Aggregate premarket high/low from 04:00–09:29:59 NY window.

    Returns (pm_high, pm_low).
    """
    from datetime import time as _time

    start_ny = datetime.combine(session_day_ny, _time(4, 0), tzinfo=US_EASTERN_TZ).astimezone(UTC)
    end_ny = datetime.combine(session_day_ny, _time(9, 30), tzinfo=US_EASTERN_TZ).astimezone(UTC)

    pm_high: float | None = None
    pm_low: float | None = None

    for bar in bars:
        dt_utc = _parse_bar_dt_utc(bar)
        if dt_utc is None:
            continue
        if not (start_ny <= dt_utc < end_ny):
            continue
        try:
            hi = _to_float(bar.get("high"), default=0.0)
            lo = _to_float(bar.get("low"), default=0.0)
        except (TypeError, ValueError):
            continue
        if hi <= 0 or lo <= 0:
            continue
        pm_high = hi if pm_high is None else max(pm_high, hi)
        pm_low = lo if pm_low is None else min(pm_low, lo)

    return pm_high, pm_low


def _pm_cache_file(symbol: str, session_day_ny: date, interval: str) -> Path:
    return PM_CACHE_DIR / f"{session_day_ny.isoformat()}_{interval}_{symbol.upper()}.json"


def _pm_cache_load(symbol: str, session_day_ny: date, interval: str) -> tuple[float | None, float | None] | None:
    path = _pm_cache_file(symbol, session_day_ny, interval)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ts = str(payload.get("cached_at_utc") or "")
        cached_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - cached_at).total_seconds()
        if age > PM_CACHE_TTL_SECONDS:
            return None
        return payload.get("pm_high"), payload.get("pm_low")
    except Exception:
        return None


def _pm_cache_save(
    symbol: str,
    session_day_ny: date,
    interval: str,
    pm_high: float | None,
    pm_low: float | None,
) -> None:
    try:
        PM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "symbol": symbol.upper(),
            "session_day_ny": session_day_ny.isoformat(),
            "interval": interval,
            "pm_high": pm_high,
            "pm_low": pm_low,
            "cached_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
        target = _pm_cache_file(symbol, session_day_ny, interval)
        import tempfile as _tempfile
        fd, tmp = _tempfile.mkstemp(dir=str(PM_CACHE_DIR), suffix=".tmp")
        try:
            os.write(fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
            os.close(fd)
            fd = -1
            os.replace(tmp, str(target))
        except BaseException:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # Evict stale PM cache files (> 2 days old).
        _evict_stale_cache_files(PM_CACHE_DIR, max_age_days=2)
    except Exception:
        return


def _pick_symbols_for_pmh(
    symbols: list[str],
    premarket_context: dict[str, dict[str, Any]],
    top_n_ext: int = TOP_N_EXT_FOR_PMH,
) -> list[str]:
    """Pick attention symbols that should receive PMH/PML (movers + top ext_hours_score).

    Returns at most *max_attention* symbols to prevent per-symbol intraday
    fetches from dominating pipeline run-time.  Symbols are prioritised by
    ext_hours_score so the most active movers always get PMH/PML data.
    """
    MAX_ATTENTION = 80  # Hard cap to keep PMH/PML stage < 20s
    cap = min(top_n_ext, MAX_ATTENTION)
    rows: list[tuple[str, float]] = []
    for sym in symbols:
        pm = premarket_context.get(sym, {})
        score = float(pm.get("ext_hours_score") or 0.0)
        is_mover = bool(pm.get("is_premarket_mover"))
        # Give movers a sorting boost so they appear first
        rows.append((sym, score + (100.0 if is_mover else 0.0)))
    rows.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in rows[:cap]]


def _fetch_premarket_high_low_bulk(
    *,
    client: FMPClient,
    symbols: list[str],
    run_dt_utc: datetime,
    interval: str = "5min",
    parallel_workers: int = 6,
    fetch_timeout_seconds: float = PM_FETCH_TIMEOUT_SECONDS,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Fetch PMH/PML for symbols via intraday bars with caching.

    Returns {SYMBOL: {"premarket_high": x, "premarket_low": y}}.
    """
    ny_day = run_dt_utc.astimezone(US_EASTERN_TZ).date()
    out: dict[str, dict[str, Any]] = {}
    timeout_msg: str | None = None

    def _one(sym: str) -> tuple[str, float | None, float | None]:
        cached = _pm_cache_load(sym, ny_day, interval)
        if cached is not None:
            return sym, cached[0], cached[1]
        bars = client.get_intraday_chart(sym, interval=interval, day=ny_day, limit=5000)
        pm_high, pm_low = compute_premarket_high_low(bars, session_day_ny=ny_day)
        _pm_cache_save(sym, ny_day, interval, pm_high, pm_low)
        return sym, pm_high, pm_low

    workers = max(1, min(int(parallel_workers), max(1, len(symbols))))
    timeout_eff = max(float(fetch_timeout_seconds), 0.0)
    timeout_arg: float | None = timeout_eff if timeout_eff > 0.0 else None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, sym): sym for sym in symbols}
        try:
            for fut in as_completed(futs, timeout=timeout_arg):
                sym = futs[fut]
                try:
                    s, pmh, pml = fut.result()
                    out[s] = {"premarket_high": pmh, "premarket_low": pml}
                except Exception:
                    out[sym] = {"premarket_high": None, "premarket_low": None}
        except FuturesTimeoutError:
            timeout_msg = (
                f"pmh_pml_fetch_timeout_{timeout_eff:.1f}s"
                if timeout_eff > 0.0
                else "pmh_pml_fetch_timeout"
            )
            logger.warning(
                "PMH/PML fetch timed out after %.1fs; continuing with partial results.",
                timeout_eff,
            )
            for fut in futs:
                if not fut.done():
                    fut.cancel()

    for sym in symbols:
        out.setdefault(sym, {"premarket_high": None, "premarket_low": None})
    return out, timeout_msg


def _inputs_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Tomorrow outlook — next-trading-day traffic light
# ---------------------------------------------------------------------------

def _compute_tomorrow_outlook(
    *,
    today: date,
    macro_bias: float,
    earnings_calendar: list[dict[str, Any]],
    ranked: list[dict[str, Any]],
    all_range_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute a next-trading-day outlook signal (🟢 / 🟡 / 🔴).

    Factors:
    - Macro bias direction and magnitude
    - High-impact macro events scheduled for tomorrow
    - Number of earnings reports tomorrow (BMO especially)
    - Current risk-off conditions
    """
    next_td = today + timedelta(days=1)
    # Skip weekends AND US equity market holidays.
    while not _is_us_equity_trading_day(next_td):
        next_td += timedelta(days=1)
    next_td_iso = next_td.isoformat()

    # Count tomorrow's earnings
    earnings_tomorrow = [
        e for e in earnings_calendar
        if str(e.get("date") or "").startswith(next_td_iso)
    ]
    earnings_bmo_tomorrow = [
        e for e in earnings_tomorrow
        if str(e.get("earnings_timing") or "").lower() in {"bmo", "before market open"}
    ]

    # Count high-impact macro events for tomorrow from full range calendar
    tomorrow_events = [
        e for e in all_range_events
        if str(e.get("date") or "").startswith(next_td_iso)
    ]
    high_impact_tomorrow = [
        e for e in tomorrow_events
        if str(e.get("impact") or e.get("importance") or e.get("priority") or "").lower() == "high"
    ]

    # Score
    outlook_score = 0.0
    reasons: list[str] = []

    # Macro bias contribution
    if macro_bias >= 0.25:
        outlook_score += 1.0
        reasons.append("macro_bias_positive")
    elif macro_bias <= -0.50:
        outlook_score -= 2.0
        reasons.append("macro_bias_strongly_negative")
    elif macro_bias <= -0.25:
        outlook_score -= 1.0
        reasons.append("macro_bias_negative")
    else:
        reasons.append("macro_bias_neutral")

    # High-impact events increase uncertainty
    if len(high_impact_tomorrow) >= 2:
        outlook_score -= 1.0
        reasons.append(f"high_impact_events_{len(high_impact_tomorrow)}")
    elif len(high_impact_tomorrow) == 1:
        outlook_score -= 0.5
        reasons.append("high_impact_event_1")

    # Many earnings reports = higher volatility
    if len(earnings_bmo_tomorrow) >= 10:
        outlook_score += 0.5  # heavy earnings = high activity = opportunities
        reasons.append(f"heavy_earnings_bmo_{len(earnings_bmo_tomorrow)}")
    elif len(earnings_tomorrow) >= 20:
        outlook_score += 0.25
        reasons.append(f"earnings_dense_{len(earnings_tomorrow)}")

    # Current risk-off conditions (many no-trade reasons in ranked)
    risk_off_count = sum(
        1 for r in ranked
        if not r.get("long_allowed", True)
    )
    if risk_off_count > len(ranked) * 0.6:
        outlook_score -= 0.5
        reasons.append("current_risk_off_majority")

    # Map score to traffic light
    if outlook_score >= 0.5:
        label = "🟢 POSITIVE"
        color = "green"
    elif outlook_score <= -1.0:
        label = "🔴 CAUTION"
        color = "red"
    else:
        label = "🟡 NEUTRAL"
        color = "orange"

    return {
        "next_trading_day": next_td_iso,
        "outlook_label": label,
        "outlook_color": color,
        "outlook_score": round(outlook_score, 2),
        "reasons": reasons,
        "earnings_tomorrow_count": len(earnings_tomorrow),
        "earnings_bmo_tomorrow_count": len(earnings_bmo_tomorrow),
        "high_impact_events_tomorrow": len(high_impact_tomorrow),
    }


def _build_runtime_status(
    *,
    news_fetch_error: str | None,
    atr_fetch_errors: dict[str, str],
    atr_candidate_symbols: list[str] | None = None,
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

    atr_candidate_set = {
        str(s).strip().upper()
        for s in (atr_candidate_symbols or [])
        if str(s).strip()
    }
    atr_missing_symbols = sorted(
        {
            str(k).strip().upper()
            for k in atr_fetch_errors.keys()
            if str(k).strip() and not str(k).strip().startswith("__")
        }
    )

    if atr_missing_symbols:
        warnings.append(
            {
                "stage": "atr_fetch",
                "code": "PARTIAL_DATA",
                "message": f"ATR unavailable for {len(atr_missing_symbols)} symbols.",
                "symbols": atr_missing_symbols,
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

    # Promote rate-limit errors to a dedicated code for UI detection.
    for w in warnings:
        msg_lower = str(w.get("message", "")).lower()
        if "429" in msg_lower or "rate limit" in msg_lower or "rate_limit" in msg_lower:
            w["code"] = "RATE_LIMIT"

    atr_attempted_count = len(atr_candidate_set)
    atr_missing_count = len(atr_missing_symbols)
    atr_available_count = max(atr_attempted_count - atr_missing_count, 0)
    atr_missing_rate_pct = round((atr_missing_count / atr_attempted_count) * 100.0, 2) if atr_attempted_count > 0 else 0.0

    return {
        "degraded_mode": bool(warnings),
        "fatal_stage": fatal_stage,
        "warnings": warnings,
        "atr_telemetry": {
            "atr_candidate_symbols": sorted(atr_candidate_set),
            "atr_candidate_count": atr_attempted_count,
            "atr_missing_symbols": atr_missing_symbols,
            "atr_missing_count": atr_missing_count,
            "atr_available_count": atr_available_count,
            "atr_missing_rate_pct": atr_missing_rate_pct,
        },
    }


def _parse_symbols(raw_symbols: str) -> list[str]:
    symbols = [item.strip().upper() for item in str(raw_symbols or "").split(",") if item.strip()]
    if not symbols:
        return []
    deduped: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        if symbol not in seen:
            deduped.append(symbol)
            seen.add(symbol)
    return deduped


def _fetch_fmp_us_mid_large_universe(
    *,
    client: FMPClient,
    min_market_cap: int,
    max_symbols: int,
) -> tuple[list[str], dict[str, str]]:
    """Return ``(symbols, sector_map)``.

    *sector_map* maps each screened symbol to its GICS-like sector string
    (e.g. ``"Technology"``) as reported by FMP.  This is harvested for free
    from the screener rows — no additional API call needed.
    """
    safe_max_symbols = max(int(max_symbols), 1)
    safe_min_market_cap = max(int(min_market_cap), 1)
    symbols: list[str] = []
    sector_map: dict[str, str] = {}
    seen: set[str] = set()
    page = 0

    while len(symbols) < safe_max_symbols:
        remaining = safe_max_symbols - len(symbols)
        batch = client.get_company_screener(
            country="US",
            exchange="NASDAQ,NYSE,AMEX",
            market_cap_more_than=safe_min_market_cap,
            is_etf=False,
            is_fund=False,
            limit=min(remaining, 1000),
            page=page,
        )
        if not batch:
            break

        batch_sorted = sorted(
            batch,
            key=lambda row: _to_float(row.get("marketCap"), default=0.0),
            reverse=True,
        )

        for row in batch_sorted:
            market_cap = _to_float(row.get("marketCap"), default=0.0)
            if market_cap < safe_min_market_cap:
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
            # Capture sector reported by FMP screener (e.g. "Technology").
            sector = str(row.get("sector") or "").strip()
            if sector:
                sector_map[symbol] = sector
            if len(symbols) >= safe_max_symbols:
                break

        if len(batch) < min(remaining, 1000):
            break
        page += 1
        if page > 50:
            # Safety guard against accidental endless paging.
            break

    return symbols, sector_map


def _resolve_symbol_universe(
    *,
    provided_symbols: list[str],
    universe_source: str,
    fmp_min_market_cap: int,
    fmp_max_symbols: int,
    mover_seed_max_symbols: int,
    client: FMPClient,
) -> tuple[list[str], list[str], dict[str, str]]:
    """Return ``(symbol_list, mover_seed, sector_map)``.

    *sector_map* maps screened symbols to their GICS-like sector string
    as reported by the FMP company screener.  When the static fallback
    universe is used, the map is empty (sector-relative scoring falls
    back to neutral 0.0).
    """
    if provided_symbols:
        return provided_symbols, [], {}

    mode = str(universe_source or UNIVERSE_SOURCE_FMP_US_MID_LARGE).strip().upper()
    if mode == UNIVERSE_SOURCE_STATIC:
        return list(DEFAULT_UNIVERSE), [], {}

    if mode == UNIVERSE_SOURCE_FMP_US_MID_LARGE:
        sector_map: dict[str, str] = {}
        try:
            auto_symbols, sector_map = _fetch_fmp_us_mid_large_universe(
                client=client,
                min_market_cap=fmp_min_market_cap,
                max_symbols=fmp_max_symbols,
            )
            mover_seed = _build_mover_seed(client, mover_seed_max_symbols)
        except RuntimeError as exc:
            logger.warning("FMP auto-universe fetch failed; using static fallback: %s", exc)
            auto_symbols = []
            mover_seed = []

        blended = _normalize_symbols(auto_symbols + mover_seed)
        if len(blended) > MAX_PREMARKET_UNION_SYMBOLS:
            blended = blended[:MAX_PREMARKET_UNION_SYMBOLS]

        if blended:
            logger.info(
                "Using blended FMP universe with %d symbols (screener=%d, movers=%d, min_market_cap=%d, sectors=%d).",
                len(blended),
                len(auto_symbols),
                len(mover_seed),
                max(int(fmp_min_market_cap), 1),
                len(sector_map),
            )
            return blended, mover_seed, sector_map

        logger.warning("FMP auto-universe returned no symbols; using static fallback list.")
        return list(DEFAULT_UNIVERSE), [], {}

    logger.warning("Unknown universe source '%s'; using static fallback list.", mode)
    return list(DEFAULT_UNIVERSE), [], {}


def _fetch_todays_events(
    *,
    client: FMPClient,
    today: date,
    end_date: date,
    pre_open_only: bool,
    pre_open_cutoff_utc: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (todays_events, all_range_events) from macro calendar.

    ``todays_events`` are filtered to *today*  (optionally cutoff-limited).
    ``all_range_events`` is the full today→end_date range, required by
    :func:`_compute_tomorrow_outlook` to find tomorrow's high-impact events.
    """
    try:
        macro_events = client.get_macro_calendar(today, end_date)
    except RuntimeError as exc:
        # Fail-open: macro calendar is enrichment, not a prerequisite.
        # Pipeline continues with empty events; macro_bias defaults to 0.0.
        logger.error("Macro calendar fetch failed (fail-open, continuing with empty events): %s", exc)
        return [], []

    todays_events = [event for event in macro_events if _event_is_today(event, today)]
    if not pre_open_only:
        return todays_events, macro_events

    try:
        filtered = _filter_events_by_cutoff_utc(todays_events, pre_open_cutoff_utc)
        return filtered, macro_events
    except ValueError as exc:
        # Fail-open: invalid cutoff format should not crash the pipeline.
        # Fall back to unfiltered events.
        logger.error("Invalid --pre-open-cutoff-utc (fail-open, using unfiltered events): %s", exc)
        return todays_events, macro_events


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
    gap_scope: str = GAP_SCOPE_DAILY,
    atr_lookback_days: int,
    atr_period: int,
    atr_parallel_workers: int,
) -> tuple[list[dict[str, Any]], dict[str, float], dict[str, float], dict[str, float | None], dict[str, str]]:
    try:
        quotes = client.get_batch_quotes(symbols)
    except RuntimeError as exc:
        # Fail-open: quote fetch failure is critical but must not crash.
        # Return empty quotes so pipeline produces a degraded result with
        # runtime_status explaining the failure, rather than SystemExit.
        logger.error("Quote fetch failed (fail-open, returning empty quotes): %s", exc)
        return [], {}, {}, {}, {"__batch__": str(exc)}

    # Filter to US exchanges only — the batch-quote response may contain
    # entries for symbols that are listed on non-US exchanges (e.g. OTC,
    # foreign ADRs without a primary US listing).
    filtered_quotes: list[dict[str, Any]] = []
    for q in quotes:
        exchange = str(q.get("exchange") or q.get("exchangeShortName") or "").strip().upper()
        # Accept if exchange field is absent (fail-open) or matches a known US exchange.
        if not exchange or exchange in _US_EXCHANGE_SET:
            filtered_quotes.append(q)
        else:
            sym = str(q.get("symbol") or "").strip().upper()
            logger.debug("Dropped non-US exchange quote: %s (exchange=%s)", sym, exchange)
    quotes = filtered_quotes

    quotes = apply_gap_mode_to_quotes(quotes, run_dt_utc=run_dt_utc, gap_mode=gap_mode, gap_scope=gap_scope)

    # ATR should only be computed for symbols that actually produced a quote.
    # The blended universe can contain stale/delisted movers which do not
    # return quote rows; requesting ATR for those inflates PARTIAL_DATA warnings
    # without improving ranking quality.
    atr_symbols = _normalize_symbols(
        [
            str(q.get("symbol") or "").strip().upper()
            for q in quotes
            if q.get("symbol") and _to_float(q.get("previousClose"), default=0.0) > 0.0
        ]
    )

    atr_by_symbol, momentum_z_by_symbol, vwap_by_symbol, atr_fetch_errors = _atr14_by_symbol(
        client=client,
        symbols=atr_symbols,
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
            q["vwap"] = vwap_by_symbol.get(sym)
            _enrich_quote_with_hvb(q)
            _add_pdh_pdl_context(q)

    return quotes, atr_by_symbol, momentum_z_by_symbol, vwap_by_symbol, atr_fetch_errors


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
    vwap_by_symbol: dict[str, float | None],
    atr_fetch_errors: dict[str, str],
    atr_candidate_symbols: list[str],
    premarket_context: dict[str, dict[str, Any]],
    premarket_fetch_error: str | None,
    ranked: list[dict[str, Any]],
    ranked_gap_go: list[dict[str, Any]],
    ranked_gap_watch: list[dict[str, Any]],
    ranked_gap_go_earnings: list[dict[str, Any]],
    earnings_calendar: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    cards_v2: list[dict[str, Any]] | None = None,
    tomorrow_outlook: dict[str, Any] | None = None,
    sector_performance: list[dict[str, Any]] | None = None,
    upgrades_downgrades: dict[str, dict[str, Any]] | None = None,
    insider_trading: dict[str, dict[str, Any]] | None = None,
    institutional_ownership: dict[str, dict[str, Any]] | None = None,
    enriched_quotes: list[dict[str, Any]] | None = None,
    # v2 pipeline outputs
    ranked_v2: list[dict[str, Any]] | None = None,
    filtered_out_v2: list[dict[str, Any]] | None = None,
    regime_snapshot: Any | None = None,
    run_diff: dict[str, Any] | None = None,
    diff_summary: str | None = None,
    watchlist: list[dict[str, Any]] | None = None,
    alert_results: list[dict[str, Any]] | None = None,
    hit_rates: dict[str, dict[str, Any]] | None = None,
    vix_level: float | None = None,
    data_capabilities: dict[str, dict[str, Any]] | None = None,
    data_capabilities_summary: dict[str, Any] | None = None,
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
                "universe_source": config.universe_source,
                "fmp_min_market_cap": config.fmp_min_market_cap,
                "fmp_max_symbols": config.fmp_max_symbols,
                "mover_seed_max_symbols": config.mover_seed_max_symbols,
                "days_ahead": config.days_ahead,
                "top": config.top,
                "trade_cards": config.trade_cards,
                "max_macro_events": config.max_macro_events,
                "pre_open_only": config.pre_open_only,
                "pre_open_cutoff_utc": config.pre_open_cutoff_utc,
                "gap_mode": config.gap_mode,
                "gap_scope": config.gap_scope,
                "atr_lookback_days": config.atr_lookback_days,
                "atr_period": config.atr_period,
                "atr_parallel_workers": config.atr_parallel_workers,
                "analyst_catalyst_limit": config.analyst_catalyst_limit,
            }
        ),
        "run_date_utc": today.isoformat(),
        "run_datetime_utc": now_utc.isoformat(),
        "symbols": config.symbols,
        "universe_source": config.universe_source,
        "fmp_min_market_cap": config.fmp_min_market_cap,
        "fmp_max_symbols": config.fmp_max_symbols,
        "mover_seed_max_symbols": config.mover_seed_max_symbols,
        "active_session": _classify_session(now_utc),
        "pre_open_only": bool(config.pre_open_only),
        "pre_open_cutoff_utc": config.pre_open_cutoff_utc,
        "gap_mode": config.gap_mode,
        "gap_scope": config.gap_scope,
        "atr_lookback_days": config.atr_lookback_days,
        "atr_period": config.atr_period,
        "atr_parallel_workers": config.atr_parallel_workers,
        "analyst_catalyst_limit": config.analyst_catalyst_limit,
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
        "vwap_by_symbol": vwap_by_symbol,
        "atr_fetch_errors": atr_fetch_errors,
        "premarket_context": premarket_context,
        "premarket_fetch_error": premarket_fetch_error,
        "run_status": _build_runtime_status(
            news_fetch_error=news_fetch_error,
            atr_fetch_errors=atr_fetch_errors,
            atr_candidate_symbols=atr_candidate_symbols,
            premarket_fetch_error=premarket_fetch_error,
            fatal_stage=None,
        ),
        "ranked_candidates": ranked,
        "ranked_gap_go": ranked_gap_go,
        "ranked_gap_watch": ranked_gap_watch,
        "ranked_gap_go_earnings": ranked_gap_go_earnings,
        "earnings_calendar": earnings_calendar,
        "trade_cards": cards,
        "trade_cards_v2": cards_v2 or [],
        "tomorrow_outlook": tomorrow_outlook,
        "sector_performance": sector_performance or [],
        "upgrades_downgrades": upgrades_downgrades or {},
        "insider_trading": insider_trading or {},
        "institutional_ownership": institutional_ownership or {},
        "enriched_quotes": enriched_quotes or [],
        # --- v2 pipeline outputs ---
        "ranked_v2": ranked_v2 or [],
        "filtered_out_v2": filtered_out_v2 or [],
        "regime": {
            "regime": regime_snapshot.regime if regime_snapshot else "NEUTRAL",
            "vix_level": vix_level,
            "macro_bias": regime_snapshot.macro_bias if regime_snapshot else bias,
            "sector_breadth": regime_snapshot.sector_breadth if regime_snapshot else 0.0,
            "weight_adjustments": regime_snapshot.weight_adjustments if regime_snapshot else {},
            "reasons": regime_snapshot.reasons if regime_snapshot else [],
        } if regime_snapshot else None,
        "diff": run_diff,
        "diff_summary": diff_summary,
        "watchlist": watchlist or [],
        "alert_results": alert_results or [],
        "historical_hit_rates": hit_rates or {},
        "data_capabilities": data_capabilities or {},
        "data_capabilities_summary": data_capabilities_summary or {},
    }


def generate_open_prep_result(
    *,
    symbols: list[str] | None = None,
    universe_source: str = UNIVERSE_SOURCE_FMP_US_MID_LARGE,
    fmp_min_market_cap: int = DEFAULT_FMP_MIN_MARKET_CAP,
    fmp_max_symbols: int = DEFAULT_FMP_MAX_SYMBOLS,
    mover_seed_max_symbols: int = DEFAULT_MOVER_SEED_MAX_SYMBOLS,
    days_ahead: int = 3,
    top: int = 10,
    trade_cards: int = 5,
    max_macro_events: int = 15,
    pre_open_only: bool = False,
    pre_open_cutoff_utc: str = "16:00:00",
    gap_mode: str = GAP_MODE_PREMARKET_INDICATIVE,
    gap_scope: str = GAP_SCOPE_DAILY,
    atr_lookback_days: int = 250,
    atr_period: int = 14,
    atr_parallel_workers: int = 8,
    analyst_catalyst_limit: int = DEFAULT_ANALYST_CATALYST_LIMIT,
    now_utc: datetime | None = None,
    client: FMPClient | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Run the open-prep pipeline and return the structured result payload.

    *progress_callback*, when provided, is called as ``callback(stage, total)``
    with a 1-based stage index for UI progress reporting.
    """

    def _progress(stage: int, total: int, label: str) -> None:
        if progress_callback is not None:
            try:
                progress_callback(stage, total, label)
            except Exception:
                pass

    TOTAL_STAGES = 12
    run_dt = now_utc or datetime.now(UTC)
    data_client = client or FMPClient.from_env()
    provided_symbols = [str(s).strip().upper() for s in (symbols or []) if str(s).strip()]
    _progress(1, TOTAL_STAGES, "Universum auflösen …")
    symbol_list, cached_mover_seed, symbol_sectors = _resolve_symbol_universe(
        provided_symbols=provided_symbols,
        universe_source=universe_source,
        fmp_min_market_cap=max(int(fmp_min_market_cap), 1),
        fmp_max_symbols=max(int(fmp_max_symbols), 1),
        mover_seed_max_symbols=max(int(mover_seed_max_symbols), 0),
        client=data_client,
    )
    if not symbol_list:
        raise ValueError("No symbols provided. Use at least one ticker symbol.")

    mode = str(gap_mode or GAP_MODE_PREMARKET_INDICATIVE).strip().upper()
    if mode not in GAP_MODE_CHOICES:
        raise ValueError(f"Unsupported gap mode: {gap_mode}")
    scope = str(gap_scope or GAP_SCOPE_DAILY).strip().upper()
    if scope not in GAP_SCOPE_CHOICES:
        raise ValueError(f"Unsupported gap scope: {gap_scope}")

    config = OpenPrepConfig(
        symbols=tuple(symbol_list),
        universe_source=str(universe_source or UNIVERSE_SOURCE_FMP_US_MID_LARGE).strip().upper(),
        fmp_min_market_cap=max(int(fmp_min_market_cap), 1),
        fmp_max_symbols=max(int(fmp_max_symbols), 1),
        mover_seed_max_symbols=max(int(mover_seed_max_symbols), 0),
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
        gap_scope=scope,
        analyst_catalyst_limit=max(int(analyst_catalyst_limit), 0),
    )

    today = run_dt.astimezone(US_EASTERN_TZ).date()
    end_date = today + timedelta(days=max(config.days_ahead, 1))

    _progress(2, TOTAL_STAGES, "Endpoint-Capabilities prüfen …")
    data_capabilities = _probe_data_capabilities(client=data_client, today=today)
    data_capabilities_summary = _summarize_data_capabilities(data_capabilities)

    bea_audit_enabled = str(os.environ.get("OPEN_PREP_BEA_AUDIT", "1")).strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }

    _progress(3, TOTAL_STAGES, "Makro-Events laden …")
    todays_events, all_range_events = _fetch_todays_events(
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

    _progress(4, TOTAL_STAGES, f"News für {len(symbol_list)} Symbole laden …")
    news_scores, news_metrics, news_fetch_error = _fetch_news_context(client=data_client, symbols=symbol_list)
    _progress(5, TOTAL_STAGES, f"Quotes + ATR für {len(symbol_list)} Symbole laden …")
    quotes, atr_by_symbol, momentum_z_by_symbol, vwap_by_symbol, atr_fetch_errors = _fetch_quotes_with_atr(
        client=data_client,
        symbols=symbol_list,
        run_dt_utc=run_dt,
        as_of=today,
        gap_mode=config.gap_mode,
        gap_scope=config.gap_scope,
        atr_lookback_days=config.atr_lookback_days,
        atr_period=config.atr_period,
        atr_parallel_workers=config.atr_parallel_workers,
    )
    atr_candidate_symbols = _normalize_symbols(
        [
            str(q.get("symbol") or "").strip().upper()
            for q in quotes
            if q.get("symbol") and _to_float(q.get("previousClose"), default=0.0) > 0.0
        ]
    )
    _progress(6, TOTAL_STAGES, "Premarket-Kontext laden …")
    premarket_context, premarket_fetch_error = _fetch_premarket_context(
        client=data_client,
        symbols=symbol_list,
        today=today,
        run_dt_utc=run_dt,
        mover_seed_max_symbols=config.mover_seed_max_symbols,
        analyst_catalyst_limit=config.analyst_catalyst_limit,
        cached_mover_seed=cached_mover_seed,
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
            q["ext_hours_score"] = pm.get("ext_hours_score", 0.0)
            q["ext_volume_ratio"] = pm.get("ext_volume_ratio", 0.0)
            q["premarket_stale"] = pm.get("premarket_stale", False)
            q["premarket_spread_bps"] = pm.get("premarket_spread_bps")
            q["mover_seed_hit"] = pm.get("mover_seed_hit", False)
            q["split_today"] = pm.get("split_today", False)
            q["dividend_today"] = pm.get("dividend_today", False)
            q["ipo_window"] = pm.get("ipo_window", False)
            q["corporate_action_penalty"] = pm.get("corporate_action_penalty", 0.0)
            q["analyst_catalyst_score"] = pm.get("analyst_catalyst_score", 0.0)
            q["days_since_last_earnings"] = pm.get("days_since_last_earnings")
            q["days_to_next_earnings"] = pm.get("days_to_next_earnings")
            q["earnings_risk_window"] = pm.get("earnings_risk_window", False)
            q["eps_surprise_pct"] = pm.get("eps_surprise_pct")
            q["revenue_surprise_pct"] = pm.get("revenue_surprise_pct")

    # --- Upgrades/Downgrades (last 3 days) ---
    _progress(7, TOTAL_STAGES, "Upgrades/Downgrades laden …")
    upgrades_downgrades: dict[str, dict[str, Any]] = {}
    try:
        upgrades_downgrades = _fetch_upgrades_downgrades(
            client=data_client,
            symbols=symbol_list,
            today=today,
            lookback_days=3,
        )
    except Exception as exc:
        logger.warning("Upgrades/downgrades fetch failed: %s", exc)

    # Merge upgrade/downgrade data into quotes
    for q in quotes:
        sym = str(q.get("symbol") or "").strip().upper()
        ud = upgrades_downgrades.get(sym, {})
        q["upgrade_downgrade_emoji"] = ud.get("upgrade_downgrade_emoji", "")
        q["upgrade_downgrade_label"] = ud.get("upgrade_downgrade_label", "")
        q["upgrade_downgrade_action"] = ud.get("upgrade_downgrade_action", "")
        q["upgrade_downgrade_firm"] = ud.get("upgrade_downgrade_firm", "")
        q["upgrade_downgrade_date"] = ud.get("upgrade_downgrade_date")

    # --- Sector Performance ---
    _progress(8, TOTAL_STAGES, "Sektor-Performance laden …")
    sector_performance: list[dict[str, Any]] = []
    try:
        sector_performance = _fetch_sector_performance(data_client)
    except Exception as exc:
        logger.warning("Sector performance fetch failed: %s", exc)

    # --- Insider Trading (Ultimate-tier) ---
    insider_trading: dict[str, dict[str, Any]] = {}
    try:
        insider_trading = _fetch_insider_trading(
            client=data_client,
            symbols=symbol_list,
        )
        if insider_trading:
            logger.info("Insider trading: %d symbols with activity", len(insider_trading))
    except Exception as exc:
        logger.warning("Insider trading fetch failed: %s", exc)

    # Merge insider trading data into quotes
    for q in quotes:
        sym = str(q.get("symbol") or "").strip().upper()
        it = insider_trading.get(sym, {})
        q["insider_sentiment"] = it.get("insider_sentiment", "")
        q["insider_emoji"] = it.get("insider_emoji", "")
        q["insider_buys"] = it.get("insider_buys", 0)
        q["insider_sells"] = it.get("insider_sells", 0)
        q["insider_net"] = it.get("insider_net", 0)

    # --- Institutional Ownership (Ultimate-tier, 13F) ---
    institutional_ownership: dict[str, dict[str, Any]] = {}
    try:
        institutional_ownership = _fetch_institutional_ownership(
            client=data_client,
            symbols=symbol_list,
        )
        if institutional_ownership:
            logger.info("Institutional ownership: %d symbols enriched", len(institutional_ownership))
    except Exception as exc:
        logger.warning("Institutional ownership fetch failed: %s", exc)

    # Merge institutional ownership data into quotes
    for q in quotes:
        sym = str(q.get("symbol") or "").strip().upper()
        io_data = institutional_ownership.get(sym, {})
        q["inst_ownership_holders"] = io_data.get("inst_ownership_holders", 0)
        q["inst_ownership_top_holders"] = io_data.get("inst_ownership_top_holders", [])

    # --- Premarket High/Low (PMH/PML) for attention names ---
    _progress(9, TOTAL_STAGES, "PMH/PML-Daten laden …")
    pmh_fetch_error: str | None = None
    pm_fetch_timeout_seconds = _to_float(
        os.environ.get("OPEN_PREP_PMH_FETCH_TIMEOUT_SECONDS"),
        default=PM_FETCH_TIMEOUT_SECONDS,
    )
    pm_fetch_timeout_seconds = max(pm_fetch_timeout_seconds, 0.0)
    try:
        attention = _pick_symbols_for_pmh(symbol_list, premarket_context)
        # Scale timeout based on attention list size: base + 0.5s per symbol
        # But if env var is explicitly set, honour the explicit override.
        pmh_env_override = os.environ.get("OPEN_PREP_PMH_FETCH_TIMEOUT_SECONDS")
        if pmh_env_override:
            scaled_timeout = pm_fetch_timeout_seconds
        else:
            scaled_timeout = max(pm_fetch_timeout_seconds, PM_FETCH_TIMEOUT_SECONDS + len(attention) * 0.5)
        pm_levels, pmh_fetch_error = _fetch_premarket_high_low_bulk(
            client=data_client,
            symbols=attention,
            run_dt_utc=run_dt,
            interval="5min",
            parallel_workers=6,
            fetch_timeout_seconds=scaled_timeout,
        )
    except Exception as exc:
        logger.warning("PMH/PML fetch failed, continuing without it: %s", exc)
        pmh_fetch_error = str(exc)
        pm_levels = {}

    if pmh_fetch_error:
        premarket_fetch_error = "; ".join(
            part for part in (premarket_fetch_error, f"pmh_pml: {pmh_fetch_error}") if part
        )

    for q in quotes:
        sym = str(q.get("symbol") or "").strip().upper()
        lvl = pm_levels.get(sym)
        if lvl:
            q["premarket_high"] = lvl.get("premarket_high")
            q["premarket_low"] = lvl.get("premarket_low")
        else:
            q.setdefault("premarket_high", None)
            q.setdefault("premarket_low", None)
        # Keep premarket_context and ranked-candidate views aligned.
        premarket_context.setdefault(sym, {})["premarket_high"] = q.get("premarket_high")
        premarket_context.setdefault(sym, {})["premarket_low"] = q.get("premarket_low")
        # ATR% normalisation
        atr_val = _to_float(q.get("atr"), default=0.0)
        prev_c = _to_float(q.get("previousClose"), default=0.0)
        q["atr_pct"] = round((atr_val / prev_c) * 100.0, 4) if atr_val > 0 and prev_c > 0 else None

    # --- GAP-GO / GAP-WATCH classification (long only) ---
    _progress(10, TOTAL_STAGES, "Ranking + Gap-Klassifizierung …")
    for q in quotes:
        meta = classify_long_gap(q, bias=bias)
        q["gap_bucket"] = meta["bucket"]
        q["no_trade_reason"] = meta["no_trade_reason"]

        # Compute gap warn-flags and merge with classifier warn_flags
        gap_wf = compute_gap_warn_flags(q)
        classifier_wf = [w for w in meta["warn_flags"].split(";") if w]

        sym = str(q.get("symbol") or "").strip().upper()
        news_row = news_metrics.get(sym) if isinstance(news_metrics, dict) else None
        time_wf = _time_based_warn_flags(q=q, run_dt_utc=run_dt, news_metrics_row=news_row)

        merged_wf = list(dict.fromkeys(classifier_wf + gap_wf + time_wf))  # dedupe, preserve order
        q["warn_flags"] = ";".join(merged_wf)
        q["gap_grade"] = meta["gap_grade"]

    gap_go_universe = [q for q in quotes if q.get("gap_bucket") == "GO"]
    gap_watch_universe = [q for q in quotes if q.get("gap_bucket") == "WATCH"]

    ranked = rank_candidates(
        quotes=quotes,
        bias=bias,
        top_n=max(config.top, 1),
        news_scores=news_scores,
        news_metrics=news_metrics,
    )
    ranked_gap_go = rank_candidates(
        quotes=gap_go_universe,
        bias=bias,
        top_n=max(config.top, 1),
        news_scores=news_scores,
        news_metrics=news_metrics,
    )
    ranked_gap_watch = rank_candidates(
        quotes=gap_watch_universe,
        bias=bias,
        top_n=max(config.top, 1),
        news_scores=news_scores,
        news_metrics=news_metrics,
    )
    # Subset: GO candidates that carry earnings warnings
    ranked_gap_go_earnings = [
        r for r in ranked_gap_go
        if "earnings_risk_window" in str(r.get("warn_flags", ""))
    ]
    # Also include any ranked candidate with earnings_today (independent of GAP-GO)
    earnings_symbols_in_go = {r.get("symbol") for r in ranked_gap_go_earnings}
    for r in ranked:
        if r.get("earnings_today") and r.get("symbol") not in earnings_symbols_in_go:
            ranked_gap_go_earnings.append(r)
            earnings_symbols_in_go.add(r.get("symbol"))

    # --- Earnings calendar screening (today + 5 days, US symbols only) ---
    universe_set = set(symbol_list)
    earnings_calendar: list[dict[str, Any]] = []
    try:
        earnings_end = today + timedelta(days=5)
        raw_earnings = data_client.get_earnings_calendar(today, earnings_end)
        for item in raw_earnings:
            sym = str(item.get("symbol") or "").strip().upper()
            if not sym:
                continue
            # Only include symbols that pass the US-equity heuristic or are
            # already in our screened universe (which is US-exchange filtered).
            if sym not in universe_set and not _is_likely_us_equity_symbol(sym):
                continue
            # Also reject if exchange field is present and clearly non-US.
            earn_exchange = str(item.get("exchange") or item.get("exchangeShortName") or "").strip().upper()
            if earn_exchange and earn_exchange not in _US_EXCHANGE_SET and sym not in universe_set:
                continue
            earn_date = str(item.get("date") or "")
            timing = str(item.get("time") or item.get("releaseTime") or "").strip().lower() or None
            earnings_calendar.append({
                "symbol": sym,
                "date": earn_date,
                "earnings_timing": timing,
                "eps_estimate": item.get("epsEstimated"),
                "revenue_estimate": item.get("revenueEstimated"),
                "eps_actual": item.get("epsActual"),
                "revenue_actual": item.get("revenueActual"),
            })
        earnings_calendar.sort(key=lambda x: (x.get("date") or "", x.get("symbol") or ""))
    except Exception as exc:
        logger.warning("Earnings calendar (6-day) fetch failed: %s", exc)

    # ===================================================================
    # v2 pipeline: VIX → regime → sector-relative → v2 scorer → outcomes
    _progress(11, TOTAL_STAGES, "v2-Pipeline (Regime, Scoring) …")
    # ===================================================================
    vix_level: float | None = None
    try:
        vix_quote = data_client.get_index_quote("^VIX")
        vix_level = _to_float(vix_quote.get("price"), default=0.0) or None
        logger.info("VIX level: %s", vix_level)
    except Exception as exc:
        logger.warning("VIX fetch failed: %s", exc)

    # Enrich symbol_sectors with profile lookups for symbols missing sector
    # info (typically mover-seeded symbols not from the screener).  Only
    # fetch profiles for symbols that have a gap (likely v2 candidates)
    # to minimise API calls.  Must run BEFORE the sector-change fallback
    # so the fallback has sector labels for all symbols.
    _enrich_symbol_sectors_from_profiles(
        client=data_client,
        quotes=quotes,
        symbol_sectors=symbol_sectors,
    )

    # Build sector change map from sector performance
    sector_changes_map: dict[str, float] = {}
    for sp in sector_performance:
        sector_name = str(sp.get("sector") or "").strip()
        change_pct = _to_float(sp.get("changesPercentage"), default=0.0)
        if sector_name:
            sector_changes_map[sector_name] = change_pct

    # Fallback: if the dedicated sector-performance endpoint returned nothing
    # (e.g. 404 / plan-limited), derive sector averages from the batch quotes
    # we already have.  Each quote carries a changesPercentage and we know
    # its sector from symbol_sectors.
    if not sector_changes_map and quotes and symbol_sectors:
        _sector_sums: dict[str, float] = {}
        _sector_counts: dict[str, int] = {}
        for q in quotes:
            sym = str(q.get("symbol") or "").strip().upper()
            sec = symbol_sectors.get(sym, "").strip()
            if not sec:
                continue
            chg = _to_float(
                q.get("changesPercentage") or q.get("changePercentage") or q.get("gap_pct"),
                default=0.0,
            )
            _sector_sums[sec] = _sector_sums.get(sec, 0.0) + chg
            _sector_counts[sec] = _sector_counts.get(sec, 0) + 1
        for sec, total in _sector_sums.items():
            cnt = _sector_counts[sec]
            avg_chg = round(total / cnt, 4) if cnt > 0 else 0.0
            sector_changes_map[sec] = avg_chg
        if sector_changes_map:
            logger.info(
                "Derived sector changes from %d quotes across %d sectors (FMP endpoint unavailable)",
                len(quotes), len(sector_changes_map),
            )
            # Also build a synthetic sector_performance list for the UI
            for sec, avg_chg in sorted(sector_changes_map.items(), key=lambda x: -x[1]):
                if avg_chg > 0.5:
                    emoji = "🟢"
                elif avg_chg < -0.5:
                    emoji = "🔴"
                else:
                    emoji = "🟡"
                sector_performance.append({
                    "sector": sec,
                    "changesPercentage": avg_chg,
                    "sector_emoji": emoji,
                    "source": "derived_from_quotes",
                })

    # Classify market regime
    regime_snapshot = classify_regime(
        macro_bias=bias,
        vix_level=vix_level,
        sector_performance=sector_performance,
    )
    logger.info("Market regime: %s (reasons: %s)", regime_snapshot.regime, regime_snapshot.reasons)

    # Load base weights and apply regime adjustments
    base_weights = load_weight_set()
    adjusted_weights = apply_regime_adjustments(base_weights, regime_snapshot)

    # Save regime-adjusted weights for this run (so scorer picks them up)
    save_weight_set("_regime_adjusted", adjusted_weights)

    # Compute historical hit rates for backward validation
    hit_rates = compute_hit_rates(lookback_days=20)

    # Run v2 two-stage pipeline (filter → score → tier)
    ranked_v2, filtered_out_v2 = rank_candidates_v2(
        quotes=quotes,
        bias=bias,
        top_n=max(config.top, 1),
        news_scores=news_scores,
        news_metrics=news_metrics,
        sector_changes=sector_changes_map,
        symbol_sectors=symbol_sectors,
        weight_label="_regime_adjusted",
    )

    # Enrich v2 candidates with historical hit rates + regime
    for row in ranked_v2:
        gap_pct = _to_float(row.get("gap_pct"), default=0.0)
        rvol_ratio = _to_float(row.get("volume_ratio"), default=0.0)
        hr = get_symbol_hit_rate(row.get("symbol", ""), gap_pct, rvol_ratio, hit_rates)
        row["historical_hit_rate"] = hr.get("historical_hit_rate")
        row["historical_sample_size"] = hr.get("historical_sample_size", 0)
        row["regime"] = regime_snapshot.regime

    # --- Breakout & Consolidation enrichment (#6, #7) ---
    # Fetch daily bars for top-N v2 candidates and run detection
    _daily_bars_cache: dict[str, list[dict[str, Any]]] = {}
    if ranked_v2 and data_client is not None:
        lookback_from = today - timedelta(days=120)
        v2_symbols = [str(r.get("symbol", "")).strip().upper() for r in ranked_v2 if r.get("symbol")]

        def _fetch_daily_bars(sym: str) -> tuple[str, list[dict[str, Any]]]:
            try:
                bars_raw = data_client.get_historical_price_eod_full(sym, lookback_from, today)
                if isinstance(bars_raw, dict):
                    maybe_hist = bars_raw.get("historical")
                    bars_raw = maybe_hist if isinstance(maybe_hist, list) else []
                if isinstance(bars_raw, list) and len(bars_raw) >= 10:
                    bars_sorted = sorted(bars_raw, key=lambda b: str(b.get("date", "")))
                    return sym, bars_sorted
            except Exception as exc:
                logger.debug("Breakout enrichment: failed to fetch bars for %s: %s", sym, exc)
            return sym, []

        with ThreadPoolExecutor(max_workers=min(5, len(v2_symbols))) as pool:
            for sym, bars_list in pool.map(_fetch_daily_bars, v2_symbols):
                if bars_list:
                    _daily_bars_cache[sym] = bars_list

    for row in ranked_v2:
        sym = str(row.get("symbol", "")).strip().upper()
        bars = _daily_bars_cache.get(sym, [])

        # Breakout detection
        bo = detect_breakout(bars) if bars else {"direction": None, "pattern": "no_data", "details": {}}
        row["breakout_direction"] = bo.get("direction")
        row["breakout_pattern"] = bo.get("pattern", "no_data")
        row["breakout_details"] = bo.get("details", {})

        # Consolidation detection (use ATR% and a rough BB-width / ADX proxy)
        atr_pct = _to_float(row.get("atr_pct_computed") or row.get("atr_pct"), default=0.0)
        # Without live ADX/BB data, use ATR%-based approximation:
        # Low ATR% ≈ tight bands ≈ possible consolidation
        approx_bb_width = max(atr_pct * 2.5, 0.1)  # rough proxy
        approx_adx = min(max(atr_pct * 8.0, 5.0), 60.0)  # rough proxy
        consol = detect_consolidation(bb_width_pct=approx_bb_width, adx=approx_adx)
        row["consolidation"] = consol
        row["is_consolidating"] = consol.get("is_consolidating", False)
        row["consolidation_score"] = consol.get("score", 0.0)

        # Symbol-level regime (#12) — ATR%-based approximation
        sym_regime = detect_symbol_regime(adx=approx_adx, bb_width_pct=approx_bb_width)
        row["symbol_regime"] = sym_regime

    # --- Playbook assignment (6-step professional news-trading engine) ---
    playbook_results = assign_playbooks(
        candidates=ranked_v2,
        regime=regime_snapshot.regime,
        sector_breadth=regime_snapshot.sector_breadth,
        news_metrics=news_metrics,
        now_utc=run_dt,
    )
    # Merge playbook data into each v2 candidate row
    for row, pb in zip(ranked_v2, playbook_results):
        row["playbook"] = pb.to_dict()
    logger.info(
        "Playbook assignment: %s",
        {pb.symbol: pb.playbook for pb in playbook_results},
    )

    # Diff view: compare with previous run
    prev_snapshot = load_previous_snapshot()
    diff_current = {
        "generated_at": run_dt.isoformat(),
        "regime": regime_snapshot.regime,
        "candidates": ranked_v2,
    }
    run_diff = compute_diff(prev_snapshot, diff_current)
    diff_summary = format_diff_summary(run_diff)
    logger.info("Diff summary: %s", diff_summary)

    # Alert dispatch
    alert_config = load_alert_config()
    alert_results: list[dict[str, Any]] = []
    try:
        # Regime change alert
        prev_regime = prev_snapshot.get("regime") if prev_snapshot else None
        alert_results.extend(alert_regime_change(prev_regime, regime_snapshot.regime, alert_config))
        # Candidate alerts
        alert_results.extend(dispatch_alerts(ranked_v2, regime=regime_snapshot.regime, config=alert_config))
    except Exception as exc:
        logger.warning("Alert dispatch error: %s", exc)

    # Auto-add high conviction to watchlist
    try:
        n_added = auto_add_high_conviction(ranked_v2, min_tier="HIGH_CONVICTION")
        if n_added:
            logger.info("Auto-added %d HIGH_CONVICTION symbols to watchlist", n_added)
    except Exception as exc:
        logger.warning("Watchlist auto-add error: %s", exc)

    # Store outcome snapshot for backward validation (profitable_30m backfilled later)
    try:
        outcome_records = prepare_outcome_snapshot(ranked_v2, today)
        store_daily_outcomes(today, outcome_records)
    except Exception as exc:
        logger.warning("Outcome storage error: %s", exc)

    # Save current snapshot for next run's diff
    try:
        save_result_snapshot(diff_current)
    except Exception as exc:
        logger.warning("Result snapshot save error: %s", exc)

    # Load watchlist for payload
    _progress(12, TOTAL_STAGES, "Ergebnis zusammenbauen …")
    watchlist = load_watchlist()
    watchlist_symbols = get_watchlist_symbols()

    cards = build_trade_cards(ranked_candidates=ranked, bias=bias, top_n=max(config.trade_cards, 1))
    # v2 trade cards use playbook-enriched candidates + daily bars for S/R targets
    cards_v2 = build_trade_cards(
        ranked_candidates=ranked_v2, bias=bias,
        top_n=max(config.trade_cards, 1),
        daily_bars=_daily_bars_cache if _daily_bars_cache else None,
    )

    # --- Tomorrow outlook (next trading-day assessment) ---
    tomorrow_outlook = _compute_tomorrow_outlook(
        today=today,
        macro_bias=bias,
        earnings_calendar=earnings_calendar,
        ranked=ranked,
        all_range_events=all_range_events,
    )

    result = _build_result_payload(
        config=config,
        now_utc=run_dt,
        today=today,
        macro_context=macro_context,
        news_metrics=news_metrics,
        news_fetch_error=news_fetch_error,
        atr_by_symbol=atr_by_symbol,
        momentum_z_by_symbol=momentum_z_by_symbol,
        vwap_by_symbol=vwap_by_symbol,
        atr_fetch_errors=atr_fetch_errors,
        atr_candidate_symbols=atr_candidate_symbols,
        premarket_context=premarket_context,
        premarket_fetch_error=premarket_fetch_error,
        ranked=ranked,
        ranked_gap_go=ranked_gap_go,
        ranked_gap_watch=ranked_gap_watch,
        ranked_gap_go_earnings=ranked_gap_go_earnings,
        earnings_calendar=earnings_calendar,
        tomorrow_outlook=tomorrow_outlook,
        cards=cards,
        cards_v2=cards_v2,
        sector_performance=sector_performance,
        upgrades_downgrades=upgrades_downgrades,
        insider_trading=insider_trading,
        institutional_ownership=institutional_ownership,
        enriched_quotes=quotes,
        # v2 pipeline outputs
        ranked_v2=ranked_v2,
        filtered_out_v2=filtered_out_v2,
        regime_snapshot=regime_snapshot,
        run_diff=run_diff,
        diff_summary=diff_summary,
        watchlist=watchlist,
        alert_results=alert_results,
        hit_rates=hit_rates,
        vix_level=vix_level,
        data_capabilities=data_capabilities,
        data_capabilities_summary=data_capabilities_summary,
    )

    # Persist latest result to JSON so CLI dashboards (vd_watch.sh) always
    # see fresh data — regardless of whether the caller is Streamlit or CLI.
    try:
        import json as _json
        import tempfile as _tmp_latest
        _latest_dir = Path("artifacts/open_prep/latest")
        _latest_dir.mkdir(parents=True, exist_ok=True)
        _latest_path = _latest_dir / "latest_open_prep_run.json"
        _content = (_json.dumps(result, indent=2, default=str) + "\n").encode("utf-8")
        _fd, _tmp_name = _tmp_latest.mkstemp(dir=str(_latest_dir), suffix=".tmp")
        try:
            os.write(_fd, _content)
            os.close(_fd)
            _fd = -1
            os.replace(_tmp_name, str(_latest_path))
        except BaseException:
            if _fd >= 0:
                os.close(_fd)
            try:
                os.unlink(_tmp_name)
            except OSError:
                pass
            raise
        # Backward-compat symlink so existing callers (vd_watch.sh, start_open_prep_suite.py)
        # that look in the package dir still find the file.
        _compat_link = Path(__file__).resolve().parent / "latest_open_prep_run.json"
        try:
            _compat_link.unlink(missing_ok=True)
            _compat_link.symlink_to(_latest_path.resolve())
        except OSError:
            pass
    except OSError:
        pass

    return result


def build_gap_scanner(
    quotes: list[dict[str, Any]],
    *,
    min_gap_pct: float = 1.5,
    max_spread_bps: float = 40.0,
    min_ext_volume_ratio: float = 0.05,
    require_fresh: bool = True,
    top_n: int = 50,
) -> list[dict[str, Any]]:
    """Build a filtered + ranked gap-scanner list from enriched quotes.

    Suitable for both premarket (PREMARKET_INDICATIVE) and RTH (RTH_OPEN)
    runs.  Caller determines which quotes go in; this function applies
    quality filters, attaches human-readable *reason_tags*, and returns up
    to *top_n* rows sorted by ``abs(gap_pct)`` descending.
    """
    candidates: list[dict[str, Any]] = []
    for q in quotes:
        gap_pct = _to_float(q.get("gap_pct"), default=0.0)
        gap_available = bool(q.get("gap_available", False))

        # Use overnight_gap_pct when the formal gap is unavailable (non-gap-scope days).
        effective_gap = gap_pct if gap_available else _to_float(q.get("overnight_gap_pct"), default=0.0)
        if abs(effective_gap) < min_gap_pct:
            continue

        tags: list[str] = []
        tags.append(f"gap>={min_gap_pct}%")

        # Freshness gate
        stale = bool(q.get("premarket_stale", False))
        if require_fresh and stale:
            continue
        if not stale:
            tags.append("fresh")

        # Spread quality
        spread_bps = _to_float(q.get("premarket_spread_bps"), default=float("nan"))
        if spread_bps == spread_bps and spread_bps <= max_spread_bps:
            tags.append("spread_ok")
        elif spread_bps == spread_bps:
            continue  # spread too wide

        # Extended-hours volume ratio
        ext_vol_ratio = _to_float(q.get("ext_volume_ratio"), default=0.0)
        if ext_vol_ratio >= min_ext_volume_ratio:
            tags.append("extvol_ok")

        # Event-risk flags
        if q.get("earnings_today") or q.get("earnings_risk_window"):
            tags.append("earnings_risk")
        if q.get("split_today"):
            tags.append("split_risk")
        if q.get("ipo_window"):
            tags.append("ipo_risk")

        candidates.append({
            "symbol": q.get("symbol"),
            "gap_pct": round(effective_gap, 4),
            "gap_available": gap_available,
            "gap_type": q.get("gap_type"),
            "gap_scope": q.get("gap_scope"),
            "is_stretch_session": q.get("is_stretch_session"),
            "ext_hours_score": q.get("ext_hours_score"),
            "ext_volume_ratio": round(ext_vol_ratio, 6),
            "premarket_spread_bps": q.get("premarket_spread_bps"),
            "premarket_stale": stale,
            "price": q.get("price"),
            "atr": q.get("atr"),
            "reason_tags": tags,
        })

    candidates.sort(key=lambda r: abs(r.get("gap_pct", 0.0)), reverse=True)
    return candidates[:max(top_n, 0)]


def main() -> None:
    args = _parse_args()
    symbols = _parse_symbols(args.symbols)
    result = generate_open_prep_result(
        symbols=symbols,
        universe_source=str(args.universe_source).strip().upper(),
        fmp_min_market_cap=max(int(args.fmp_min_market_cap), 1),
        fmp_max_symbols=max(int(args.fmp_max_symbols), 1),
        mover_seed_max_symbols=max(int(args.mover_seed_max_symbols), 0),
        days_ahead=args.days_ahead,
        top=args.top,
        trade_cards=args.trade_cards,
        max_macro_events=args.max_macro_events,
        pre_open_only=bool(args.pre_open_only),
        pre_open_cutoff_utc=args.pre_open_cutoff_utc,
        gap_mode=args.gap_mode,
        gap_scope=str(args.gap_scope).strip().upper(),
        atr_lookback_days=args.atr_lookback_days,
        atr_period=args.atr_period,
        atr_parallel_workers=args.atr_parallel_workers,
        analyst_catalyst_limit=max(int(args.analyst_catalyst_limit), 0),
    )
    rendered = json.dumps(result, indent=2, default=str)
    sys.stdout.write(rendered + "\n")
    # Note: latest_open_prep_run.json is already written inside
    # generate_open_prep_result() with default=str.  No second write needed.


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("OPEN_PREP_LOG_LEVEL", "INFO").upper(),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    main()
