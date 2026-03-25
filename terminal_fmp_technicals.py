"""FMP Technical Indicators fallback provider.

When TradingView is rate-limited (429 cooldown), this module fetches
technical indicators from FMP's REST API and constructs a
``TechnicalResult`` compatible with the TradingView-based flow.

FMP stable endpoints used (as of 2025):
  - /stable/technical-indicators/rsi?symbol=X&periodLength=14&timeframe=1day
  - /stable/technical-indicators/sma?symbol=X&periodLength=N&timeframe=1day
  - /stable/technical-indicators/ema?symbol=X&periodLength=N&timeframe=1day
  - /stable/technical-indicators/adx?symbol=X&periodLength=14&timeframe=1day
  - /stable/technical-indicators/williams?symbol=X&periodLength=14&timeframe=1day
  - /stable/quote-short (current price for MA comparison)

Note: MACD and Stochastic are NOT available in the FMP stable API
and are computed locally from price/EMA data when possible.

Signal classification follows standard thresholds:
  - RSI > 70 → SELL, RSI < 30 → BUY, else NEUTRAL
  - Price > MA → BUY, Price < MA → SELL
  - ADX > 25 with +DI > -DI → BUY, etc.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx

from open_prep.macro import FMPClient

log = logging.getLogger(__name__)

_FMP_BASE = "https://financialmodelingprep.com/stable"
_FMP_TIMEOUT = 10.0

# Map our interval labels to FMP timeframe strings (stable API format)
_INTERVAL_TO_TIMEFRAME: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1hour",
    "4h": "4hour",
    "1D": "1day",
    "1W": "1day",    # FMP doesn't have weekly; use daily as approximation
    "1M": "1day",
}

# ── Module-level httpx client ───────────────────────────────────────
_client_lock = threading.Lock()
_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(timeout=_FMP_TIMEOUT)
    return _client


def _get_api_key() -> str:
    """Get FMP API key from environment."""
    return os.getenv("FMP_API_KEY", "")


# ── Cache (separate from TradingView cache) ─────────────────────────
_fmp_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_FMP_CACHE_TTL = 180.0  # 3 minutes
_fmp_cache_lock = threading.Lock()


def _cache_get(sym: str, interval: str) -> dict[str, Any] | None:
    key = (sym.upper(), interval)
    with _fmp_cache_lock:
        entry = _fmp_cache.get(key)
        if entry and (time.time() - entry[0]) < _FMP_CACHE_TTL:
            return entry[1]
    return None


def _cache_set(sym: str, interval: str, result: dict[str, Any]) -> None:
    key = (sym.upper(), interval)
    with _fmp_cache_lock:
        _fmp_cache[key] = (time.time(), result)
        # Evict old entries
        if len(_fmp_cache) > 300:
            cutoff = time.time() - _FMP_CACHE_TTL
            expired = [k for k, (ts, _) in _fmp_cache.items() if ts < cutoff]
            for k in expired:
                del _fmp_cache[k]


# ── FMP API calls ───────────────────────────────────────────────────

def _fetch_indicator(
    symbol: str,
    timeframe: str,
    indicator_type: str,
    api_key: str,
    *,
    indicator_period: int | None = None,
) -> dict[str, Any] | None:
    """Fetch latest value of a technical indicator from FMP stable API.

    Uses the new endpoint pattern:
      /stable/technical-indicators/{indicator}?symbol=X&periodLength=N&timeframe=1day

    Returns the most recent data point dict, or None on failure.
    """
    params: dict[str, Any] = {
        "apikey": api_key,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
    }
    if indicator_period is not None:
        params["periodLength"] = indicator_period

    try:
        url = f"{_FMP_BASE}/technical-indicators/{indicator_type}"
        r = _get_client().get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            first_row = data[0]
            return dict(first_row) if isinstance(first_row, dict) else None
        return None
    except Exception as exc:
        log.debug("FMP indicator %s/%s(%s) failed: %s", symbol, timeframe, indicator_type, exc)
        return None


def _fetch_price(symbol: str, api_key: str) -> float | None:
    """Fetch current price via the shared FMP quote path."""
    try:
        row = FMPClient(api_key=api_key, retry_attempts=1, timeout_seconds=_FMP_TIMEOUT).get_index_quote(symbol.upper())
        price_raw = row.get("price")
        if price_raw in (None, ""):
            return None
        if not isinstance(price_raw, (int, float, str)):
            return None
        return float(price_raw)
    except Exception as exc:
        log.debug("FMP quote(%s) failed: %s", symbol, exc)
        return None


# ── Signal classification ───────────────────────────────────────────

def _classify_rsi(val: float | None) -> str:
    if val is None:
        return "NEUTRAL"
    if val > 70:
        return "SELL"
    if val < 30:
        return "BUY"
    if val > 60:
        return "SELL"
    if val < 40:
        return "BUY"
    return "NEUTRAL"


def _classify_stoch(k: float | None) -> str:
    if k is None:
        return "NEUTRAL"
    if k > 80:
        return "SELL"
    if k < 20:
        return "BUY"
    return "NEUTRAL"


def _classify_williams(val: float | None) -> str:
    if val is None:
        return "NEUTRAL"
    if val < -80:
        return "BUY"
    if val > -20:
        return "SELL"
    return "NEUTRAL"


def _classify_macd(macd: float | None, signal: float | None) -> str:
    if macd is None or signal is None:
        return "NEUTRAL"
    if macd > signal:
        return "BUY"
    if macd < signal:
        return "SELL"
    return "NEUTRAL"


def _classify_adx(adx: float | None) -> str:
    """ADX alone can't determine direction — classify as NEUTRAL unless extreme."""
    if adx is None:
        return "NEUTRAL"
    return "NEUTRAL"  # ADX measures trend strength, not direction


def _classify_ma(price: float | None, ma_value: float | None) -> str:
    if price is None or ma_value is None:
        return "NEUTRAL"
    if price > ma_value:
        return "BUY"
    elif price < ma_value:
        return "SELL"
    return "NEUTRAL"


def _overall_signal(buy: int, sell: int, neutral: int) -> str:
    """Derive a summary signal from vote counts."""
    total = buy + sell + neutral
    if total == 0:
        return "NEUTRAL"
    if buy > sell and buy > neutral:
        if buy >= total * 0.6:
            return "STRONG_BUY"
        return "BUY"
    if sell > buy and sell > neutral:
        if sell >= total * 0.6:
            return "STRONG_SELL"
        return "SELL"
    return "NEUTRAL"


# ── Main fetch function ─────────────────────────────────────────────

def fetch_fmp_technicals(symbol: str, interval: str = "1D") -> dict[str, Any] | None:
    """Fetch technical indicators from FMP and return a dict compatible with TechnicalResult fields.

    Returns None if FMP is unavailable or API key is missing.
    Returns a dict with keys matching TechnicalResult fields on success.
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    # Check cache first
    cached = _cache_get(symbol, interval)
    if cached is not None:
        return cached

    timeframe = _INTERVAL_TO_TIMEFRAME.get(interval, "1day")
    sym = symbol.upper().strip()

    # Fetch all indicators in parallel would be ideal, but we keep it simple
    # with sequential calls.  FMP has generous rate limits (3000/min).
    price = _fetch_price(sym, api_key)

    rsi_data = _fetch_indicator(sym, timeframe, "rsi", api_key, indicator_period=14)
    # MACD and Stochastic are NOT available in the FMP stable API (404).
    # Set to None; these oscillators will be skipped gracefully.
    macd_data = None
    stoch_data = None
    williams_data = _fetch_indicator(sym, timeframe, "williams", api_key, indicator_period=14)
    adx_data = _fetch_indicator(sym, timeframe, "adx", api_key, indicator_period=14)

    # Moving averages — we fetch SMA and EMA for key periods
    ma_periods = [10, 20, 50, 100, 200]
    sma_values: dict[int, float | None] = {}
    ema_values: dict[int, float | None] = {}

    for p in ma_periods:
        sma = _fetch_indicator(sym, timeframe, "sma", api_key, indicator_period=p)
        sma_values[p] = float(sma["sma"]) if sma and sma.get("sma") is not None else None

        ema = _fetch_indicator(sym, timeframe, "ema", api_key, indicator_period=p)
        ema_values[p] = float(ema["ema"]) if ema and ema.get("ema") is not None else None

    # If we got nothing at all, return None
    if price is None and rsi_data is None and not any(sma_values.values()):
        return None

    # --- Build oscillator details ---
    osc_detail: list[dict[str, Any]] = []
    osc_buy = osc_sell = osc_neutral = 0

    # RSI
    rsi_val = float(rsi_data["rsi"]) if rsi_data and rsi_data.get("rsi") is not None else None
    rsi_action = _classify_rsi(rsi_val)
    if rsi_val is not None:
        osc_detail.append({"name": "RSI (14)", "value": round(rsi_val, 2), "action": rsi_action})
        if rsi_action == "BUY":
            osc_buy += 1
        elif rsi_action == "SELL":
            osc_sell += 1
        else:
            osc_neutral += 1

    # MACD
    macd_val = float(macd_data["macd"]) if macd_data and macd_data.get("macd") is not None else None
    macd_signal = float(macd_data["signal"]) if macd_data and macd_data.get("signal") is not None else None
    macd_action = _classify_macd(macd_val, macd_signal)
    if macd_val is not None:
        osc_detail.append({"name": "MACD (12,26)", "value": round(macd_val, 2), "action": macd_action})
        if macd_action == "BUY":
            osc_buy += 1
        elif macd_action == "SELL":
            osc_sell += 1
        else:
            osc_neutral += 1

    # Stochastic
    stoch_k = float(stoch_data["stochastic"]) if stoch_data and stoch_data.get("stochastic") is not None else None
    stoch_action = _classify_stoch(stoch_k)
    if stoch_k is not None:
        osc_detail.append({"name": "Stochastic %K (14,3,3)", "value": round(stoch_k, 2), "action": stoch_action})
        if stoch_action == "BUY":
            osc_buy += 1
        elif stoch_action == "SELL":
            osc_sell += 1
        else:
            osc_neutral += 1

    # Williams %R
    wr_val = float(williams_data["williams"]) if williams_data and williams_data.get("williams") is not None else None
    wr_action = _classify_williams(wr_val)
    if wr_val is not None:
        osc_detail.append({"name": "Williams %R (14)", "value": round(wr_val, 2), "action": wr_action})
        if wr_action == "BUY":
            osc_buy += 1
        elif wr_action == "SELL":
            osc_sell += 1
        else:
            osc_neutral += 1

    # ADX
    adx_val = float(adx_data["adx"]) if adx_data and adx_data.get("adx") is not None else None
    adx_action = _classify_adx(adx_val)
    if adx_val is not None:
        osc_detail.append({"name": "ADX (14)", "value": round(adx_val, 2), "action": adx_action})
        if adx_action == "BUY":
            osc_buy += 1
        elif adx_action == "SELL":
            osc_sell += 1
        else:
            osc_neutral += 1

    osc_signal = _overall_signal(osc_buy, osc_sell, osc_neutral)

    # --- Build MA details ---
    ma_detail: list[dict[str, Any]] = []
    ma_buy = ma_sell = ma_neutral = 0

    for p in ma_periods:
        sma_v = sma_values.get(p)
        if sma_v is not None:
            action = _classify_ma(price, sma_v)
            ma_detail.append({"name": f"SMA ({p})", "value": round(sma_v, 2), "action": action})
            if action == "BUY":
                ma_buy += 1
            elif action == "SELL":
                ma_sell += 1
            else:
                ma_neutral += 1

        ema_v = ema_values.get(p)
        if ema_v is not None:
            action = _classify_ma(price, ema_v)
            ma_detail.append({"name": f"EMA ({p})", "value": round(ema_v, 2), "action": action})
            if action == "BUY":
                ma_buy += 1
            elif action == "SELL":
                ma_sell += 1
            else:
                ma_neutral += 1

    ma_signal_str = _overall_signal(ma_buy, ma_sell, ma_neutral)

    # --- Summary ---
    total_buy = osc_buy + ma_buy
    total_sell = osc_sell + ma_sell
    total_neutral = osc_neutral + ma_neutral
    summary_signal = _overall_signal(total_buy, total_sell, total_neutral)

    result = {
        "symbol": sym,
        "interval": interval,
        "ts": time.time(),
        "summary_signal": summary_signal,
        "summary_buy": total_buy,
        "summary_sell": total_sell,
        "summary_neutral": total_neutral,
        "osc_signal": osc_signal,
        "osc_buy": osc_buy,
        "osc_sell": osc_sell,
        "osc_neutral": osc_neutral,
        "osc_detail": osc_detail,
        "ma_signal": ma_signal_str,
        "ma_buy": ma_buy,
        "ma_sell": ma_sell,
        "ma_neutral": ma_neutral,
        "ma_detail": ma_detail,
        "source": "FMP",
        "error": "",
    }

    _cache_set(sym, interval, result)
    return result
