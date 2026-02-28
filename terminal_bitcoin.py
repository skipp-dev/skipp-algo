"""Bitcoin data module for the Streamlit terminal.

Provides comprehensive Bitcoin market data from multiple sources:
1. **Real-time price/quote** — FMP cryptocurrency quote
2. **Historical OHLCV** — FMP + yfinance for candlestick charts
3. **Technical analysis** — TradingView via tradingview_ta (screener=crypto)
4. **News/sentiment** — NewsAPI.ai + FMP articles filtered for Bitcoin
5. **Social sentiment** — Finnhub social sentiment for crypto
6. **Market cap / supply** — yfinance BTC-USD info
7. **Fear & Greed index** — FMP fear-and-greed endpoint
8. **Crypto movers** — FMP cryptocurrency gainers/losers
9. **Exchange listings** — FMP cryptocurrency list
10. **Tomorrow outlook** — Composite analysis from technicals + sentiment + F&G

Bitcoin markets are 24/7 — no market-hours restrictions apply.

Primary source: FMP (``FMP_API_KEY``).
Fallback/supplementary: yfinance, TradingView, NewsAPI.ai, Finnhub.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

# ── Optional dependencies ────────────────────────────────────────

try:
    import httpx
    _HTTPX = True
except ImportError:
    _HTTPX = False

try:
    import yfinance as yf  # type: ignore[import-untyped]
    _YF = True
except ImportError:
    _YF = False

try:
    from tradingview_ta import TA_Handler, Interval  # type: ignore[import-untyped]
    _TV = True
except ImportError:
    _TV = False

try:
    import pandas as pd  # type: ignore[import-untyped]  # noqa: F811,F401 — only _PD flag used
    _PD = True
except ImportError:
    _PD = False

# ── Config ───────────────────────────────────────────────────────

_FMP_BASE = "https://financialmodelingprep.com/stable"


def _fmp_key() -> str:
    return os.environ.get("FMP_API_KEY", "")


# ── HTTP client singleton ────────────────────────────────────────

_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client | None:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        if not _HTTPX:
            return None
        _client = httpx.Client(timeout=15.0)
        return _client


# ── Cache ────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _get_cached(key: str, ttl: float) -> Any:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if time.time() - ts > ttl:
            del _cache[key]
            return None
        return val


def _set_cached(key: str, val: Any) -> None:
    now = time.time()
    with _cache_lock:
        _cache[key] = (now, val)
        # Evict expired entries when cache grows large
        if len(_cache) > 200:
            max_ttl = 600
            expired = [k for k, (ts, _) in _cache.items() if now - ts > max_ttl]
            for k in expired:
                del _cache[k]


# TTLs (seconds) — Bitcoin is 24/7 so we can be more aggressive
_QUOTE_TTL = 30       # 30s for real-time price
_OHLCV_TTL = 120      # 2 min for historical data
_TECHNICALS_TTL = 600  # 10 min for TradingView (avoid 429 rate limits)
_TECHNICALS_429_TTL = 900  # 15 min cache for 429 errors (don't retry quickly)
_FG_TTL = 300          # 5 min for Fear & Greed
_MOVERS_TTL = 120      # 2 min for crypto movers
_LISTINGS_TTL = 3600   # 1h for exchange listings
_SUPPLY_TTL = 300      # 5 min for market cap/supply
_NEWS_TTL = 120        # 2 min for news
_OUTLOOK_TTL = 300     # 5 min for tomorrow outlook

_APIKEY_RE = re.compile(r"(apikey|token)=[^&\s]+", re.IGNORECASE)

# ── Global TradingView rate limiter (BTC crypto calls) ────────────
_TV_MIN_CALL_SPACING = 2.0  # minimum seconds between TradingView API calls
_tv_last_call_ts: float = 0.0
_tv_rate_lock = threading.Lock()

# 429 cooldown: after a 429 response, block ALL TradingView calls for a period
_tv_cooldown_until: float = 0.0
_tv_consecutive_429s: int = 0
_TV_COOLDOWN_BASE = 60.0   # base cooldown: 60 seconds
_TV_COOLDOWN_MAX = 300.0   # max cooldown: 5 minutes


def _tv_is_cooling_down() -> bool:
    """Return True if we are in a 429 cooldown period."""
    return time.time() < _tv_cooldown_until


def _tv_register_429() -> None:
    """Register a 429 response and set a cooldown period."""
    global _tv_cooldown_until, _tv_consecutive_429s
    with _tv_rate_lock:
        _tv_consecutive_429s += 1
        cooldown = min(_TV_COOLDOWN_BASE * (2 ** (_tv_consecutive_429s - 1)), _TV_COOLDOWN_MAX)
        _tv_cooldown_until = time.time() + cooldown
        log.warning(
            "TradingView BTC 429 — cooldown %.0fs (consecutive: %d)",
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


# ── FMP helper ───────────────────────────────────────────────────

def _fmp_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET from FMP stable API. Returns parsed JSON or None on error."""
    key = _fmp_key()
    if not key:
        log.debug("FMP_API_KEY not set")
        return None
    client = _get_client()
    if client is None:
        log.debug("httpx not available")
        return None
    p: dict[str, Any] = dict(params or {})
    p["apikey"] = key
    try:
        r = client.get(f"{_FMP_BASE}/{path}", params=p)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        log.warning("FMP %s failed: %s", path, _APIKEY_RE.sub(r"\1=***", str(exc)))
        return None
    except Exception as exc:
        log.warning("FMP %s unexpected error: %s", path, _APIKEY_RE.sub(r"\1=***", str(exc)), exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════

@dataclass
class BTCQuote:
    """Real-time Bitcoin quote."""
    price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    year_high: float = 0.0
    year_low: float = 0.0
    volume: float = 0.0
    avg_volume: float = 0.0
    market_cap: float = 0.0
    open_price: float = 0.0
    prev_close: float = 0.0
    timestamp: str = ""
    name: str = "Bitcoin"
    exchange: str = ""

    @property
    def change_icon(self) -> str:
        if self.change_pct > 1:
            return "🟢"
        if self.change_pct < -1:
            return "🔴"
        return "⚪"


@dataclass
class FearGreed:
    """CNN-style Fear & Greed index."""
    value: float = 0.0
    label: str = ""
    timestamp: str = ""

    @property
    def icon(self) -> str:
        if self.value >= 75:
            return "🟢"  # Extreme Greed
        if self.value >= 55:
            return "🟡"  # Greed
        if self.value >= 45:
            return "⚪"  # Neutral
        if self.value >= 25:
            return "🟠"  # Fear
        return "🔴"  # Extreme Fear

    @property
    def color(self) -> str:
        if self.value >= 75:
            return "green"
        if self.value >= 55:
            return "olive"
        if self.value >= 45:
            return "gray"
        if self.value >= 25:
            return "orange"
        return "red"


@dataclass
class CryptoMover:
    """A crypto gainer or loser."""
    symbol: str = ""
    name: str = ""
    price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0


@dataclass
class CryptoListing:
    """A cryptocurrency listing."""
    symbol: str = ""
    name: str = ""
    currency: str = ""
    exchange: str = ""


@dataclass
class BTCTechnicals:
    """TradingView technical analysis for BTC."""
    summary: str = ""  # BUY / SELL / NEUTRAL / STRONG_BUY / STRONG_SELL
    buy: int = 0
    sell: int = 0
    neutral: int = 0
    osc_signal: str = ""
    osc_buy: int = 0
    osc_sell: int = 0
    osc_neutral: int = 0
    ma_signal: str = ""
    ma_buy: int = 0
    ma_sell: int = 0
    ma_neutral: int = 0
    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    stoch_k: float | None = None
    adx: float | None = None
    cci: float | None = None
    interval: str = "1h"
    error: str = ""

    @property
    def signal_icon(self) -> str:
        return {
            "STRONG_BUY": "🟢", "BUY": "🟢",
            "STRONG_SELL": "🔴", "SELL": "🔴",
            "NEUTRAL": "⚪",
        }.get(self.summary, "⚪")


@dataclass
class BTCSupply:
    """Bitcoin market cap and supply info from yfinance."""
    market_cap: float = 0.0
    circulating_supply: float = 0.0
    total_supply: float = 21_000_000.0  # fixed max
    volume_24h: float = 0.0
    avg_volume_10d: float = 0.0
    fifty_day_avg: float = 0.0
    two_hundred_day_avg: float = 0.0
    # Dominance is not directly available from yfinance but can be added


@dataclass
class BTCOutlook:
    """Tomorrow outlook composite for Bitcoin."""
    trend_label: str = ""  # Bullish / Bearish / Neutral
    trend_icon: str = "⚪"
    fear_greed: FearGreed | None = None
    technicals_1h: BTCTechnicals | None = None
    technicals_4h: BTCTechnicals | None = None
    technicals_1d: BTCTechnicals | None = None
    price: float = 0.0
    support: float = 0.0
    resistance: float = 0.0
    rsi: float | None = None
    summary_text: str = ""
    error: str = ""  # non-empty when all data sources failed


# ═══════════════════════════════════════════════════════════════════
# Fetch functions
# ═══════════════════════════════════════════════════════════════════

def fetch_btc_quote() -> BTCQuote | None:
    """Fetch real-time Bitcoin quote from FMP."""
    cached = _get_cached("btc_quote", _QUOTE_TTL)
    if cached is not None:
        return cached  # type: ignore

    data = _fmp_get("quote", {"symbol": "BTCUSD"})
    if not data:
        # Fallback: yfinance
        return _btc_quote_yfinance()

    rows = data if isinstance(data, list) else [data]
    if not rows:
        return _btc_quote_yfinance()

    d = rows[0] if isinstance(rows[0], dict) else {}
    quote = BTCQuote(
        price=float(d.get("price", 0)),
        change=float(d.get("change", 0)),
        change_pct=float(d.get("changePercentage", d.get("changesPercentage", 0))),
        day_high=float(d.get("dayHigh", 0)),
        day_low=float(d.get("dayLow", 0)),
        year_high=float(d.get("yearHigh", 0)),
        year_low=float(d.get("yearLow", 0)),
        volume=float(d.get("volume", 0)),
        avg_volume=float(d.get("avgVolume", 0)),
        market_cap=float(d.get("marketCap", 0)),
        open_price=float(d.get("open", 0)),
        prev_close=float(d.get("previousClose", 0)),
        timestamp=str(d.get("timestamp", "")),
        name=d.get("name", "Bitcoin"),
        exchange=d.get("exchange", ""),
    )
    _set_cached("btc_quote", quote)
    return quote


def _btc_quote_yfinance() -> BTCQuote | None:
    """Fallback: get BTC quote from yfinance."""
    if not _YF:
        return None
    try:
        t = yf.Ticker("BTC-USD")
        info = t.info or {}
        quote = BTCQuote(
            price=float(info.get("regularMarketPrice", 0) or info.get("currentPrice", 0) or 0),
            change=float(info.get("regularMarketChange", 0) or 0),
            change_pct=float(info.get("regularMarketChangePercent", 0) or 0),
            day_high=float(info.get("dayHigh", 0) or 0),
            day_low=float(info.get("dayLow", 0) or 0),
            year_high=float(info.get("fiftyTwoWeekHigh", 0) or 0),
            year_low=float(info.get("fiftyTwoWeekLow", 0) or 0),
            volume=float(info.get("volume", 0) or 0),
            avg_volume=float(info.get("averageVolume", 0) or 0),
            market_cap=float(info.get("marketCap", 0) or 0),
            open_price=float(info.get("open", 0) or 0),
            prev_close=float(info.get("previousClose", 0) or 0),
            name="Bitcoin",
        )
        _set_cached("btc_quote", quote)
        return quote
    except Exception as exc:
        log.warning("yfinance BTC quote failed: %s", exc)
        return None


def fetch_btc_ohlcv(
    period: str = "60d",
    interval: str = "1h",
) -> list[dict[str, Any]]:
    """Fetch Bitcoin OHLCV data for charting.

    Uses yfinance for intraday intervals (1m, 5m, 15m, 30m, 1h)
    and FMP for daily data.

    Returns list of dicts with keys: date, open, high, low, close, volume.
    """
    cache_key = f"btc_ohlcv:{period}:{interval}"
    cached = _get_cached(cache_key, _OHLCV_TTL)
    if cached is not None:
        return cached  # type: ignore

    # For intraday, yfinance is the best free source
    if _YF and interval in ("1m", "5m", "15m", "30m", "1h", "90m"):
        try:
            t = yf.Ticker("BTC-USD")
            hist = t.history(period=period, interval=interval)
            if hist is not None and not hist.empty:
                rows: list[dict[str, Any]] = []
                for idx, row in hist.iterrows():
                    ts = idx
                    if hasattr(ts, "isoformat"):
                        ts_str = ts.isoformat()
                    else:
                        ts_str = str(ts)
                    rows.append({
                        "date": ts_str,
                        "open": float(row.get("Open", 0)),
                        "high": float(row.get("High", 0)),
                        "low": float(row.get("Low", 0)),
                        "close": float(row.get("Close", 0)),
                        "volume": float(row.get("Volume", 0)),
                    })
                _set_cached(cache_key, rows)
                return rows
        except Exception as exc:
            log.warning("yfinance BTC OHLCV failed: %s", exc)

    # For daily, try FMP first
    data = _fmp_get("cryptocurrency-historical-price", {"symbol": "BTCUSD"})
    if data and isinstance(data, list):
        rows = []
        for d in data[:365]:  # limit to 1 year
            if isinstance(d, dict):
                rows.append({
                    "date": d.get("date", ""),
                    "open": float(d.get("open", 0)),
                    "high": float(d.get("high", 0)),
                    "low": float(d.get("low", 0)),
                    "close": float(d.get("close", 0)),
                    "volume": float(d.get("volume", 0)),
                })
        if rows:
            rows.sort(key=lambda r: r["date"])
            _set_cached(cache_key, rows)
            return rows

    # Final fallback: yfinance daily
    if _YF:
        try:
            t = yf.Ticker("BTC-USD")
            hist = t.history(period="60d", interval="1d")
            if hist is not None and not hist.empty:
                rows = []
                for idx, row in hist.iterrows():
                    ts = idx
                    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                    rows.append({
                        "date": ts_str,
                        "open": float(row.get("Open", 0)),
                        "high": float(row.get("High", 0)),
                        "low": float(row.get("Low", 0)),
                        "close": float(row.get("Close", 0)),
                        "volume": float(row.get("Volume", 0)),
                    })
                _set_cached(cache_key, rows)
                return rows
        except Exception as exc:
            log.warning("yfinance BTC daily OHLCV failed: %s", exc)

    return []


def fetch_btc_ohlcv_10min(hours: int = 48) -> list[dict[str, Any]]:
    """Fetch 10-minute aggregated BTC OHLCV for volume analysis.

    Uses yfinance 5m data aggregated to 10m buckets for the last *hours*.
    """
    cache_key = f"btc_ohlcv_10m:{hours}"
    cached = _get_cached(cache_key, 60)  # 1 min cache for near-realtime
    if cached is not None:
        return cached  # type: ignore

    if not _YF or not _PD:
        return []

    try:
        t = yf.Ticker("BTC-USD")
        # yfinance max period for 5m is 60d
        period_str = f"{min(hours // 24 + 1, 60)}d"
        hist = t.history(period=period_str, interval="5m")
        if hist is None or hist.empty:
            return []

        # Resample to 10-minute buckets
        hist_10m = hist.resample("10min").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).dropna()

        # Filter to last N hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        if hist_10m.index.tz is None:
            hist_10m.index = hist_10m.index.tz_localize("UTC")
        else:
            hist_10m.index = hist_10m.index.tz_convert("UTC")
        hist_10m = hist_10m[hist_10m.index >= cutoff]

        rows: list[dict[str, Any]] = []
        for idx, row in hist_10m.iterrows():
            ts_str = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
            rows.append({
                "date": ts_str,
                "open": float(row.get("Open", 0)),
                "high": float(row.get("High", 0)),
                "low": float(row.get("Low", 0)),
                "close": float(row.get("Close", 0)),
                "volume": float(row.get("Volume", 0)),
            })
        _set_cached(cache_key, rows)
        return rows
    except Exception as exc:
        log.warning("BTC 10min OHLCV failed: %s", exc)
        return []


def fetch_btc_technicals(interval: str = "1h") -> BTCTechnicals:
    """Fetch TradingView technicals for BTCUSDT on Binance.

    Bitcoin is 24/7 so this always returns data.
    """
    cache_key = f"btc_tech:{interval}"

    # Use longer TTL for cached 429 errors
    cached_raw = _get_cached(cache_key, _TECHNICALS_TTL)
    if cached_raw is not None:
        return cached_raw  # type: ignore
    # Also check with longer 429 TTL
    cached_429 = _get_cached(cache_key, _TECHNICALS_429_TTL)
    if cached_429 is not None and getattr(cached_429, 'error', '') and '429' in str(cached_429.error):
        return cached_429  # type: ignore

    if not _TV:
        return BTCTechnicals(interval=interval, error="tradingview_ta not installed")

    # Check 429 cooldown — return stale cache or error without hitting API
    if _tv_is_cooling_down():
        stale = _get_cached(cache_key, 86400)  # return any cached value
        if stale is not None:
            return stale  # type: ignore
        remaining = _tv_cooldown_until - time.time()
        log.debug("TradingView BTC cooldown active (%.0fs remaining), skipping %s", remaining, interval)
        return BTCTechnicals(interval=interval, error="Rate limited — cooldown active")

    interval_map = {
        "1m": Interval.INTERVAL_1_MINUTE,
        "5m": Interval.INTERVAL_5_MINUTES,
        "15m": Interval.INTERVAL_15_MINUTES,
        "30m": Interval.INTERVAL_30_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "2h": Interval.INTERVAL_2_HOURS,
        "4h": Interval.INTERVAL_4_HOURS,
        "1d": Interval.INTERVAL_1_DAY,
        "1w": Interval.INTERVAL_1_WEEK,
        "1M": Interval.INTERVAL_1_MONTH,
    }
    tv_interval = interval_map.get(interval, Interval.INTERVAL_1_HOUR)

    _MAX_RETRIES = 3
    _BASE_BACKOFF = 5.0  # seconds

    for attempt in range(_MAX_RETRIES + 1):
        try:
            _tv_throttle()  # enforce spacing between calls
            handler = TA_Handler(
                symbol="BTCUSDT",
                screener="crypto",
                exchange="BINANCE",
                interval=tv_interval,
            )
            analysis = handler.get_analysis()
            if not analysis or not analysis.summary:
                return BTCTechnicals(interval=interval, error="No analysis data")

            s = analysis.summary
            indicators = analysis.indicators or {}

            result = BTCTechnicals(
                summary=s.get("RECOMMENDATION", ""),
                buy=s.get("BUY", 0),
                sell=s.get("SELL", 0),
                neutral=s.get("NEUTRAL", 0),
                osc_signal=analysis.oscillators.get("RECOMMENDATION", "") if analysis.oscillators else "",
                osc_buy=analysis.oscillators.get("BUY", 0) if analysis.oscillators else 0,
                osc_sell=analysis.oscillators.get("SELL", 0) if analysis.oscillators else 0,
                osc_neutral=analysis.oscillators.get("NEUTRAL", 0) if analysis.oscillators else 0,
                ma_signal=analysis.moving_averages.get("RECOMMENDATION", "") if analysis.moving_averages else "",
                ma_buy=analysis.moving_averages.get("BUY", 0) if analysis.moving_averages else 0,
                ma_sell=analysis.moving_averages.get("SELL", 0) if analysis.moving_averages else 0,
                ma_neutral=analysis.moving_averages.get("NEUTRAL", 0) if analysis.moving_averages else 0,
                rsi=indicators.get("RSI"),
                macd=indicators.get("MACD.macd"),
                macd_signal=indicators.get("MACD.signal"),
                stoch_k=indicators.get("Stoch.K"),
                adx=indicators.get("ADX"),
                cci=indicators.get("CCI20"),
                interval=interval,
            )
            _set_cached(cache_key, result)
            _tv_register_success()
            return result
        except Exception as exc:
            _msg = str(exc)
            if "429" in _msg:
                _tv_register_429()
                if attempt < _MAX_RETRIES:
                    _sleep = _BASE_BACKOFF * (2 ** attempt)
                    log.info(
                        "TradingView BTC 429 (%s) — retry %d/%d after %.1fs",
                        interval, attempt + 1, _MAX_RETRIES, _sleep,
                    )
                    time.sleep(_sleep)
                    continue
            log.warning("TradingView BTC technicals (%s) failed: %s", interval, exc)
            result = BTCTechnicals(interval=interval, error=str(exc))
            _set_cached(cache_key, result)  # cache errors too
            return result
    return BTCTechnicals(interval=interval, error="Max retries exceeded")


def fetch_fear_greed() -> FearGreed | None:
    """Fetch Crypto Fear & Greed index from alternative.me (free, no key needed).

    Falls back to FMP if alternative.me is unavailable.
    """
    cached = _get_cached("fear_greed", _FG_TTL)
    if cached is not None:
        return cached  # type: ignore

    client = _get_client()
    if client is None:
        return None

    # Primary: Alternative.me crypto Fear & Greed (free, no API key)
    try:
        r = client.get(
            "https://api.alternative.me/fng/",
            params={"limit": "1", "format": "json"},
        )
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, dict):
            log.warning("Fear & Greed API returned non-dict: %r", type(body))
            return None
        data_list = body.get("data", [])
        if data_list:
            d = data_list[0]
            ts_val = d.get("timestamp", "")
            ts_str = ""
            if ts_val:
                try:
                    ts_str = datetime.fromtimestamp(int(ts_val), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                except (ValueError, OverflowError, OSError):
                    ts_str = str(ts_val)
            fg = FearGreed(
                value=float(d.get("value", 0)),
                label=d.get("value_classification", ""),
                timestamp=ts_str,
            )
            _set_cached("fear_greed", fg)
            return fg
    except (httpx.HTTPError, OSError, ValueError) as exc:
        log.debug("alternative.me F&G failed: %s", exc)

    # Fallback: FMP (may not be available on all plans)
    data = _fmp_get("fear-and-greed-index")
    if not data:
        return None

    rows = data if isinstance(data, list) else [data]
    if not rows:
        return None

    d = rows[0] if isinstance(rows[0], dict) else {}
    fg = FearGreed(
        value=float(d.get("value", 0)),
        label=d.get("valueClassification", d.get("label", "")),
        timestamp=str(d.get("timestamp", d.get("date", ""))),
    )
    _set_cached("fear_greed", fg)
    return fg


def fetch_crypto_movers() -> dict[str, list[CryptoMover]]:
    """Fetch cryptocurrency gainers and losers from FMP.

    Returns dict with keys 'gainers' and 'losers'.
    """
    cached = _get_cached("crypto_movers", _MOVERS_TTL)
    if cached is not None:
        return cached  # type: ignore

    result: dict[str, list[CryptoMover]] = {"gainers": [], "losers": []}

    # Use batch-crypto-quotes (fields: symbol, price, change, volume)
    # and compute change_pct ourselves since the endpoint doesn't provide it.
    data = _fmp_get("batch-crypto-quotes")
    if data and isinstance(data, list):
        for d in data:
            if not isinstance(d, dict):
                continue
            price = float(d.get("price", 0) or 0)
            change = float(d.get("change", 0) or 0)
            prev_price = price - change
            chg_pct = (change / prev_price * 100) if prev_price else 0.0
            sym = d.get("symbol", "")
            # Derive display name from symbol (strip trailing USD)
            name = sym[:-3] if sym.endswith("USD") else sym
            mover = CryptoMover(
                symbol=sym,
                name=name,
                price=price,
                change=change,
                change_pct=chg_pct,
            )
            if chg_pct >= 0:
                result["gainers"].append(mover)
            else:
                result["losers"].append(mover)
        # Sort and keep top movers
        result["gainers"].sort(key=lambda m: m.change_pct, reverse=True)
        result["losers"].sort(key=lambda m: m.change_pct)

    _set_cached("crypto_movers", result)
    return result


def fetch_crypto_listings(limit: int = 50) -> list[CryptoListing]:
    """Fetch cryptocurrency exchange listings from FMP."""
    cached = _get_cached("crypto_listings", _LISTINGS_TTL)
    if cached is not None:
        return cached[:limit]  # type: ignore

    data = _fmp_get("cryptocurrency-list")
    if not data or not isinstance(data, list):
        return []

    listings: list[CryptoListing] = []
    for d in data:
        if not isinstance(d, dict):
            continue
        listings.append(CryptoListing(
            symbol=d.get("symbol", ""),
            name=d.get("name", ""),
            currency=d.get("currency", ""),
            exchange=d.get("exchangeShortName", d.get("exchange", "")),
        ))
    _set_cached("crypto_listings", listings)
    return listings[:limit]


def fetch_btc_supply() -> BTCSupply:
    """Fetch Bitcoin market cap and supply data from yfinance."""
    cached = _get_cached("btc_supply", _SUPPLY_TTL)
    if cached is not None:
        return cached  # type: ignore

    supply = BTCSupply()
    if _YF:
        try:
            t = yf.Ticker("BTC-USD")
            info = t.info or {}
            supply = BTCSupply(
                market_cap=float(info.get("marketCap", 0) or 0),
                circulating_supply=float(info.get("circulatingSupply", 0) or 0),
                volume_24h=float(info.get("volume24Hr", 0) or info.get("volume", 0) or 0),
                avg_volume_10d=float(info.get("averageDailyVolume10Day", 0) or info.get("averageVolume10days", 0) or 0),
                fifty_day_avg=float(info.get("fiftyDayAverage", 0) or 0),
                two_hundred_day_avg=float(info.get("twoHundredDayAverage", 0) or 0),
            )
        except Exception as exc:
            log.warning("yfinance BTC supply failed: %s", exc)

    _set_cached("btc_supply", supply)
    return supply


def fetch_btc_news(limit: int = 10) -> list[dict[str, Any]]:
    """Fetch Bitcoin-related news from FMP."""
    cached = _get_cached("btc_news", _NEWS_TTL)
    if cached is not None:
        return cached[:limit]  # type: ignore

    # FMP crypto news
    data = _fmp_get("news/stock-latest", {"symbol": "BTCUSD", "limit": str(limit)})

    articles: list[dict[str, Any]] = []
    if isinstance(data, list):
        for d in data:
            if isinstance(d, dict):
                articles.append({
                    "title": d.get("title", ""),
                    "url": d.get("url", ""),
                    "source": d.get("site", d.get("source", "")),
                    "date": d.get("publishedDate", d.get("date", "")),
                    "sentiment": d.get("sentiment", ""),
                    "image": d.get("image", ""),
                    "text": d.get("text", "")[:300] if d.get("text") else "",
                })

    # If FMP returned nothing, try general crypto search
    if not articles:
        data2 = _fmp_get("news/stock-latest", {"limit": "50"})
        if isinstance(data2, list):
            for d in data2:
                if isinstance(d, dict):
                    title = (d.get("title", "") or "").lower()
                    text = (d.get("text", "") or "").lower()
                    if any(kw in title or kw in text for kw in ("bitcoin", "btc", "crypto", "cryptocurrency")):
                        articles.append({
                            "title": d.get("title", ""),
                            "url": d.get("url", ""),
                            "source": d.get("site", d.get("source", "")),
                            "date": d.get("publishedDate", d.get("date", "")),
                            "sentiment": d.get("sentiment", ""),
                            "image": d.get("image", ""),
                            "text": d.get("text", "")[:300] if d.get("text") else "",
                        })
                        if len(articles) >= limit:
                            break

    _set_cached("btc_news", articles)
    return articles[:limit]


def fetch_btc_outlook() -> BTCOutlook:
    """Build a composite tomorrow outlook for Bitcoin.

    Combines Fear & Greed, multi-timeframe technicals, and current price
    to generate a directional bias with support/resistance levels.
    """
    cached = _get_cached("btc_outlook", _OUTLOOK_TTL)
    if cached is not None:
        return cached  # type: ignore

    fg = fetch_fear_greed()
    tech_1h = fetch_btc_technicals("1h")
    time.sleep(1.0)  # delay to avoid TradingView 429
    tech_4h = fetch_btc_technicals("4h")
    time.sleep(1.0)
    tech_1d = fetch_btc_technicals("1d")
    quote = fetch_btc_quote()

    # Score: +1 for each bullish signal, -1 for each bearish
    score = 0
    reasons: list[str] = []

    # Fear & Greed
    if fg:
        if fg.value >= 65:
            score += 1
            reasons.append(f"F&G = {fg.value:.0f} ({fg.label}) → bullish sentiment")
        elif fg.value <= 35:
            score -= 1
            reasons.append(f"F&G = {fg.value:.0f} ({fg.label}) → bearish sentiment")
        else:
            reasons.append(f"F&G = {fg.value:.0f} ({fg.label}) → neutral")

    # Technicals
    for label, tech in [("1H", tech_1h), ("4H", tech_4h), ("1D", tech_1d)]:
        if tech and not tech.error:
            if "BUY" in tech.summary:
                score += 1
                reasons.append(f"{label} technicals: {tech.summary}")
            elif "SELL" in tech.summary:
                score -= 1
                reasons.append(f"{label} technicals: {tech.summary}")
            else:
                reasons.append(f"{label} technicals: {tech.summary}")

    # RSI from 1D
    rsi_val = tech_1d.rsi if tech_1d else None
    if rsi_val is not None:
        if rsi_val > 70:
            score -= 1
            reasons.append(f"RSI(1D) = {rsi_val:.1f} → overbought")
        elif rsi_val < 30:
            score += 1
            reasons.append(f"RSI(1D) = {rsi_val:.1f} → oversold")

    # Determine trend
    if score >= 2:
        trend = "Bullish"
        icon = "🟢"
    elif score <= -2:
        trend = "Bearish"
        icon = "🔴"
    else:
        trend = "Neutral"
        icon = "⚪"

    # Support/resistance from price data
    price = quote.price if quote else 0
    support = price * 0.95  # simple 5% below
    resistance = price * 1.05

    # Try to get better S/R from technicals
    if tech_1d and tech_1d.rsi is not None and price > 0:
        # Estimate S/R from recent range
        if quote:
            if quote.day_low > 0:
                support = quote.day_low * 0.99
            if quote.day_high > 0:
                resistance = quote.day_high * 1.01

    summary = f"**{trend}** outlook based on {len(reasons)} signals. " + " | ".join(reasons)

    # If no data sources provided any signals, mark as error
    _has_data = bool(fg or (tech_1h and not tech_1h.error) or (tech_4h and not tech_4h.error) or (tech_1d and not tech_1d.error) or (quote and quote.price > 0))
    _error = "" if _has_data else "All data sources unavailable"

    outlook = BTCOutlook(
        trend_label=trend,
        trend_icon=icon,
        fear_greed=fg,
        technicals_1h=tech_1h,
        technicals_4h=tech_4h,
        technicals_1d=tech_1d,
        price=price,
        support=round(support, 2),
        resistance=round(resistance, 2),
        rsi=rsi_val,
        summary_text=summary,
        error=_error,
    )
    _set_cached("btc_outlook", outlook)
    return outlook


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def is_available() -> bool:
    """Check if at least one data source is available."""
    return bool(_fmp_key()) or _YF or _TV


def format_large_number(n: float) -> str:
    """Format a large number with K/M/B suffix."""
    if n >= 1_000_000_000_000:
        return f"${n / 1_000_000_000_000:.2f}T"
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n / 1_000:.1f}K"
    return f"${n:.2f}"


def format_btc_price(p: float) -> str:
    """Format BTC price with comma separator."""
    return f"${p:,.2f}"


def format_supply(n: float) -> str:
    """Format supply number."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:.0f}"


def technicals_signal_label(signal: str) -> str:
    """Return a human-readable label for a TradingView signal."""
    return {
        "STRONG_BUY": "Strong Buy",
        "BUY": "Buy",
        "NEUTRAL": "Neutral",
        "SELL": "Sell",
        "STRONG_SELL": "Strong Sell",
    }.get(signal, signal)


def technicals_signal_icon(signal: str) -> str:
    """Return an emoji for a TradingView signal."""
    return {
        "STRONG_BUY": "🟢",
        "BUY": "🟢",
        "NEUTRAL": "⚪",
        "SELL": "🔴",
        "STRONG_SELL": "🔴",
    }.get(signal, "⚪")
