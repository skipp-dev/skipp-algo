"""Technical-analysis helper for the Streamlit terminal.

Consumers keep the historical ``TechnicalResult`` contract, but live requests
use only the FMP adapter and fail closed when FMP is unavailable.

"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# Public interval labels used by the terminal controls.  Values are kept
# human-readable because the FMP adapter owns provider-specific mappings.
INTERVAL_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1D": "1D",
    "1W": "1W",
    "1M": "1M",
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
    """Holds provider technical analysis for one symbol + interval."""

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

    # Disclosed so consumers can weight signals by provenance (audit #2670 W3).
    source: str = "unknown"


# ── In-memory cache ──────────────────────────────────────────────────
_cache: dict[tuple[str, str], TechnicalResult] = {}
_CACHE_TTL_S = 180.0  # 3 minutes — keep data fresh for AI & tab displays
_CACHE_NOT_FOUND_TTL_S = 3600.0  # 1 hour for symbols not found on any exchange
_CACHE_MAX_SIZE = 500  # evict expired entries when exceeded
_cache_lock = threading.Lock()

def _cache_key(symbol: str, interval: str) -> tuple[str, str]:
    return (symbol.upper().strip(), interval)


def _fmp_fallback(symbol: str, interval: str, ts: float) -> TechnicalResult | None:
    """Fetch the sole technical provider and normalize its result."""
    try:
        from terminal_fmp_technicals import fetch_fmp_technicals
    except ImportError:
        return None

    data = fetch_fmp_technicals(symbol, interval)
    if data is None or data.get("error"):
        return None

    result = TechnicalResult(
        symbol=data.get("symbol", symbol),
        interval=data.get("interval", interval),
        ts=ts,
        summary_signal=data.get("summary_signal", ""),
        summary_buy=data.get("summary_buy", 0),
        summary_sell=data.get("summary_sell", 0),
        summary_neutral=data.get("summary_neutral", 0),
        osc_signal=data.get("osc_signal", ""),
        osc_buy=data.get("osc_buy", 0),
        osc_sell=data.get("osc_sell", 0),
        osc_neutral=data.get("osc_neutral", 0),
        osc_detail=data.get("osc_detail", []),
        ma_signal=data.get("ma_signal", ""),
        ma_buy=data.get("ma_buy", 0),
        ma_sell=data.get("ma_sell", 0),
        ma_neutral=data.get("ma_neutral", 0),
        ma_detail=data.get("ma_detail", []),
        source="fmp",
    )
    log.info("FMP provided technicals for %s/%s", symbol, interval)
    key = _cache_key(symbol, interval)
    with _cache_lock:
        _cache[key] = result
    return result


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
    sym = symbol.upper().strip()
    key = _cache_key(sym, interval)
    now = time.time()

    if not force:
        with _cache_lock:
            cached = _cache.get(key)
            if cached and (now - cached.ts) < _CACHE_TTL_S:
                return cached
    if interval not in INTERVAL_MAP:
        return TechnicalResult(symbol=sym, interval=interval, error=f"Unknown interval: {interval}")

    result = _fmp_fallback(sym, interval, now)
    if result is None:
        result = TechnicalResult(
            symbol=sym,
            interval=interval,
            ts=now,
            source="fmp",
            error="FMP technicals unavailable",
        )
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
        intervals = list(INTERVAL_MAP)
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
