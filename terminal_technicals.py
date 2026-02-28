"""TradingView Technical Analysis helper for the Streamlit terminal.

Fetches oscillator & moving-average summaries plus indicator values
from TradingView via the ``tradingview_ta`` library.  Results are
cached per (symbol, interval) with a configurable TTL to avoid
hammering TradingView's scanner endpoint.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

try:
    from tradingview_ta import TA_Handler, Interval  # type: ignore[import-untyped]

    _TV_AVAILABLE = True
except ImportError:
    _TV_AVAILABLE = False

# ── Interval labels (German matching TradingView UI) ─────────────────
INTERVAL_MAP: dict[str, str] = {}
if _TV_AVAILABLE:
    INTERVAL_MAP = {
        "1m": Interval.INTERVAL_1_MINUTE,
        "5m": Interval.INTERVAL_5_MINUTES,
        "15m": Interval.INTERVAL_15_MINUTES,
        "30m": Interval.INTERVAL_30_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "2h": Interval.INTERVAL_2_HOURS,
        "4h": Interval.INTERVAL_4_HOURS,
        "1D": Interval.INTERVAL_1_DAY,
        "1W": Interval.INTERVAL_1_WEEK,
        "1M": Interval.INTERVAL_1_MONTH,
    }

# Default interval for the quick summary badge
DEFAULT_INTERVAL = "1D"

# Signal → emoji mapping
_SIGNAL_ICON: dict[str, str] = {
    "STRONG_BUY": "🟢🟢",
    "BUY": "🟢",
    "NEUTRAL": "🟡",
    "SELL": "🔴",
    "STRONG_SELL": "🔴🔴",
}

_SIGNAL_LABEL: dict[str, str] = {
    "STRONG_BUY": "Strong Buy",
    "BUY": "Buy",
    "NEUTRAL": "Neutral",
    "SELL": "Sell",
    "STRONG_SELL": "Strong Sell",
}

# Oscillator & MA display names
_OSC_NAMES: dict[str, str] = {
    "RSI": "RSI (14)",
    "STOCH.K": "Stochastic %K (14,3,3)",
    "CCI": "CCI (20)",
    "ADX": "ADX (14)",
    "AO": "Awesome Oscillator",
    "Mom": "Momentum (10)",
    "MACD": "MACD (12,26)",
    "Stoch.RSI": "Stochastic RSI (3,3,14,14)",
    "W%R": "Williams %R (14)",
    "BBP": "Bull Bear Power",
    "UO": "Ultimate Oscillator (7,14,28)",
}

_MA_NAMES: dict[str, str] = {
    "EMA10": "EMA (10)",
    "SMA10": "SMA (10)",
    "EMA20": "EMA (20)",
    "SMA20": "SMA (20)",
    "EMA30": "EMA (30)",
    "SMA30": "SMA (30)",
    "EMA50": "EMA (50)",
    "SMA50": "SMA (50)",
    "EMA100": "EMA (100)",
    "SMA100": "SMA (100)",
    "EMA200": "EMA (200)",
    "SMA200": "SMA (200)",
    "Ichimoku": "Ichimoku Base Line (9,26,52,26)",
    "VWMA": "VWMA (20)",
    "HullMA": "Hull MA (9)",
}

# Raw indicator key → value key in a.indicators
_OSC_VALUE_KEY: dict[str, str] = {
    "RSI": "RSI",
    "STOCH.K": "Stoch.K",
    "CCI": "CCI20",
    "ADX": "ADX",
    "AO": "AO",
    "Mom": "Mom",
    "MACD": "MACD.macd",
    "Stoch.RSI": "Stoch.RSI.K",
    "W%R": "W.R",
    "BBP": "BBPower",
    "UO": "UO",
}

_MA_VALUE_KEY: dict[str, str] = {
    "EMA10": "EMA10",
    "SMA10": "SMA10",
    "EMA20": "EMA20",
    "SMA20": "SMA20",
    "EMA30": "EMA30",
    "SMA30": "SMA30",
    "EMA50": "EMA50",
    "SMA50": "SMA50",
    "EMA100": "EMA100",
    "SMA100": "SMA100",
    "EMA200": "EMA200",
    "SMA200": "SMA200",
    "Ichimoku": "Ichimoku.BLine",
    "VWMA": "VWMA",
    "HullMA": "HullMA9",
}


@dataclass
class TechnicalResult:
    """Holds TradingView technical analysis for one symbol + interval."""

    symbol: str
    interval: str  # label key like "1D"
    ts: float = 0.0  # fetch timestamp

    # Summary
    summary_signal: str = ""  # e.g. "BUY", "SELL", "STRONG_BUY", ...
    summary_buy: int = 0
    summary_sell: int = 0
    summary_neutral: int = 0

    # Oscillators
    osc_signal: str = ""
    osc_buy: int = 0
    osc_sell: int = 0
    osc_neutral: int = 0
    osc_detail: list[dict[str, Any]] = field(default_factory=list)  # [{name, value, action}, ...]

    # Moving Averages
    ma_signal: str = ""
    ma_buy: int = 0
    ma_sell: int = 0
    ma_neutral: int = 0
    ma_detail: list[dict[str, Any]] = field(default_factory=list)

    error: str = ""


# ── In-memory cache ──────────────────────────────────────────────────
_cache: dict[tuple[str, str], TechnicalResult] = {}
_CACHE_TTL_S = 300.0  # 5 minutes (avoid TradingView 429 rate limits)
_CACHE_ERROR_TTL_S = 600.0  # 10 minutes for 429 errors (longer backoff)
_CACHE_MAX_SIZE = 500  # evict expired entries when exceeded
_cache_lock = threading.Lock()

# ── Global TradingView rate limiter ──────────────────────────────────
_TV_MIN_CALL_SPACING = 1.5  # minimum seconds between TradingView API calls
_tv_last_call_ts: float = 0.0
_tv_rate_lock = threading.Lock()

# 429 cooldown: after a 429 response, block ALL TradingView calls for a period
_tv_cooldown_until: float = 0.0
_tv_consecutive_429s: int = 0
_TV_COOLDOWN_BASE = 60.0   # base cooldown: 60 seconds
_TV_COOLDOWN_MAX = 300.0   # max cooldown: 5 minutes


def _tv_is_cooling_down() -> bool:
    """Return True if we are in a 429 cooldown period."""
    with _tv_rate_lock:
        deadline = _tv_cooldown_until
    return time.time() < deadline


def _tv_cooldown_remaining() -> float:
    """Return seconds remaining in the 429 cooldown, or 0 if not cooling down."""
    with _tv_rate_lock:
        deadline = _tv_cooldown_until
    return max(0.0, deadline - time.time())


def _tv_register_429() -> None:
    """Register a 429 response and set a cooldown period."""
    global _tv_cooldown_until, _tv_consecutive_429s
    with _tv_rate_lock:
        _tv_consecutive_429s += 1
        cooldown = min(_TV_COOLDOWN_BASE * (2 ** (_tv_consecutive_429s - 1)), _TV_COOLDOWN_MAX)
        _tv_cooldown_until = time.time() + cooldown
        log.warning(
            "TradingView 429 — cooldown %.0fs (consecutive: %d)",
            cooldown, _tv_consecutive_429s,
        )


def _tv_register_success() -> None:
    """Reset 429 counter on successful call."""
    global _tv_consecutive_429s
    with _tv_rate_lock:
        _tv_consecutive_429s = 0


def _tv_throttle() -> None:
    """Enforce minimum spacing between TradingView API calls."""
    global _tv_last_call_ts
    with _tv_rate_lock:
        now = time.time()
        elapsed = now - _tv_last_call_ts
        if elapsed < _TV_MIN_CALL_SPACING:
            time.sleep(_TV_MIN_CALL_SPACING - elapsed)
        _tv_last_call_ts = time.time()


def _cache_key(symbol: str, interval: str) -> tuple[str, str]:
    return (symbol.upper().strip(), interval)


def _try_exchanges(symbol: str, interval_val: str) -> Any | None:
    """Try common US exchanges in priority order, with retry on 429."""
    import time as _time  # local import to avoid circular

    _MAX_RETRIES = 2
    _BASE_BACKOFF = 4.0  # seconds

    for attempt in range(_MAX_RETRIES + 1):
        for exchange in ("NASDAQ", "NYSE", "AMEX"):
            try:
                _tv_throttle()  # enforce spacing
                h = TA_Handler(
                    symbol=symbol,
                    screener="america",
                    exchange=exchange,
                    interval=interval_val,
                )
                analysis = h.get_analysis()
                if analysis and analysis.summary:
                    _tv_register_success()
                    return analysis
            except Exception as exc:
                _msg = str(exc)
                if "429" in _msg:
                    _tv_register_429()
                    if attempt < _MAX_RETRIES:
                        _sleep = _BASE_BACKOFF * (2 ** attempt)
                        log.info(
                            "TradingView 429 for %s/%s — retry %d/%d after %.1fs",
                            symbol, exchange, attempt + 1, _MAX_RETRIES, _sleep,
                        )
                        _time.sleep(_sleep)
                        break  # break inner exchange loop → retry all exchanges
                    # last attempt — propagate so caller can display it
                    raise
                continue
        else:
            # inner loop completed without break → no 429, all exchanges tried
            return None
    return None


def fetch_technicals(
    symbol: str,
    interval: str = DEFAULT_INTERVAL,
    *,
    force: bool = False,
) -> TechnicalResult:
    """Fetch technicals for *symbol* at *interval*.

    Returns a cached result if younger than ``_CACHE_TTL_S`` unless
    *force* is True.

    Parameters
    ----------
    symbol:
        US stock/ETF ticker (e.g. ``"AAPL"``).
    interval:
        One of the keys in ``INTERVAL_MAP`` (``"1m"`` … ``"1M"``).
    force:
        Bypass cache and fetch fresh data.
    """
    if not _TV_AVAILABLE:
        return TechnicalResult(symbol=symbol, interval=interval, error="tradingview_ta not installed")

    sym = symbol.upper().strip()
    key = _cache_key(sym, interval)
    now = time.time()

    if not force:
        with _cache_lock:
            cached = _cache.get(key)
            if cached:
                # Use longer TTL for 429 errors to avoid hammering TradingView
                ttl = _CACHE_ERROR_TTL_S if (cached.error and "429" in cached.error) else _CACHE_TTL_S
                if (now - cached.ts) < ttl:
                    return cached

    # Check 429 cooldown — return stale cache or error without hitting API
    if _tv_is_cooling_down():
        with _cache_lock:
            cached = _cache.get(key)
            if cached:
                return cached
        remaining = _tv_cooldown_until - now
        log.debug("TradingView cooldown active (%.0fs remaining), skipping %s", remaining, sym)
        return TechnicalResult(symbol=sym, interval=interval, ts=now, error="Rate limited — cooldown active")

    interval_val = INTERVAL_MAP.get(interval)
    if not interval_val:
        return TechnicalResult(symbol=sym, interval=interval, error=f"Unknown interval: {interval}")

    try:
        analysis = _try_exchanges(sym, interval_val)
        if analysis is None:
            result = TechnicalResult(symbol=sym, interval=interval, ts=now, error="Symbol not found on TradingView")
            with _cache_lock:
                _cache[key] = result
            return result

        s = analysis.summary or {}
        o = analysis.oscillators or {}
        m = analysis.moving_averages or {}
        ind = analysis.indicators or {}

        # Build oscillator details
        osc_compute = o.get("COMPUTE", {})
        osc_detail: list[dict[str, Any]] = []
        for osc_key, label in _OSC_NAMES.items():
            action = osc_compute.get(osc_key)
            if action is None:
                continue
            raw_key = _OSC_VALUE_KEY.get(osc_key, osc_key)
            value = ind.get(raw_key)
            osc_detail.append({
                "name": label,
                "value": round(value, 2) if isinstance(value, (int, float)) and value is not None else value,
                "action": action,
            })

        # Build MA details
        ma_compute = m.get("COMPUTE", {})
        ma_detail: list[dict[str, Any]] = []
        for ma_key, label in _MA_NAMES.items():
            action = ma_compute.get(ma_key)
            if action is None:
                continue
            raw_key = _MA_VALUE_KEY.get(ma_key, ma_key)
            value = ind.get(raw_key)
            ma_detail.append({
                "name": label,
                "value": round(value, 2) if isinstance(value, (int, float)) and value is not None else value,
                "action": action,
            })

        result = TechnicalResult(
            symbol=sym,
            interval=interval,
            ts=now,
            summary_signal=s.get("RECOMMENDATION", ""),
            summary_buy=s.get("BUY", 0),
            summary_sell=s.get("SELL", 0),
            summary_neutral=s.get("NEUTRAL", 0),
            osc_signal=o.get("RECOMMENDATION", ""),
            osc_buy=o.get("BUY", 0),
            osc_sell=o.get("SELL", 0),
            osc_neutral=o.get("NEUTRAL", 0),
            osc_detail=osc_detail,
            ma_signal=m.get("RECOMMENDATION", ""),
            ma_buy=m.get("BUY", 0),
            ma_sell=m.get("SELL", 0),
            ma_neutral=m.get("NEUTRAL", 0),
            ma_detail=ma_detail,
        )
        with _cache_lock:
            _cache[key] = result
            # Evict expired when cache grows beyond limit
            if len(_cache) > _CACHE_MAX_SIZE:
                expired_keys = [k for k, v in _cache.items() if now - v.ts > _CACHE_TTL_S]
                for k in expired_keys:
                    del _cache[k]
        return result

    except Exception as exc:
        _msg = str(exc)
        if "429" in _msg:
            _tv_register_429()
        log.warning("TradingView technicals fetch failed for %s: %s", sym, exc)
        result = TechnicalResult(symbol=sym, interval=interval, ts=now, error=_msg)
        with _cache_lock:
            _cache[key] = result
        return result


def fetch_multi_interval(
    symbol: str,
    intervals: list[str] | None = None,
) -> dict[str, TechnicalResult]:
    """Fetch technicals across multiple timeframes for one symbol.

    Returns a dict keyed by interval label.
    """
    if intervals is None:
        intervals = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1D", "1W", "1M"]
    return {iv: fetch_technicals(symbol, iv) for iv in intervals}


def summary_badge(symbol: str, interval: str = DEFAULT_INTERVAL) -> str:
    """Return a compact badge string like '🟢 Buy (B:8 N:4 S:2)'.

    Suitable for inline display in dataframe cells.
    """
    r = fetch_technicals(symbol, interval)
    if r.error:
        return "—"
    icon = _SIGNAL_ICON.get(r.summary_signal, "")
    label = _SIGNAL_LABEL.get(r.summary_signal, r.summary_signal)
    return f"{icon} {label} (B:{r.summary_buy} N:{r.summary_neutral} S:{r.summary_sell})"


def signal_icon(signal: str) -> str:
    """Map a signal string to emoji."""
    return _SIGNAL_ICON.get(signal, "")


def signal_label(signal: str) -> str:
    """Map a signal string to human-readable label."""
    return _SIGNAL_LABEL.get(signal, signal)
