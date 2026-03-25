"""TradingView Headlines integration for the Streamlit terminal.

Fetches real-time news headlines from TradingView's headlines API.
This is an *unofficial* endpoint — no API key required — but it may
be rate-limited or blocked (Cloudflare) intermittently.  The module
includes health monitoring so the dashboard surfaces availability
issues rather than silently failing.

Usage::

    from terminal_tradingview_news import (
        fetch_tv_headlines,
        fetch_tv_multi,
        health_status,
        is_available,
    )

    items = fetch_tv_headlines("AAPL")  # -> list[TVHeadline]
    items = fetch_tv_multi(["AAPL", "TSLA", "NVDA"])  # batch

All results are cached in-memory with a configurable TTL so the
endpoint isn't hammered.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen
import urllib.error
import json
import ssl

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_BASE_URL = "https://news-headlines.tradingview.com/v2/view/headlines/symbol"
_DEFAULT_PARAMS = "client=web&lang=en"

# Cache settings
_CACHE_TTL = 180          # 3 min per symbol
_CACHE_MAX_SIZE = 300     # max cached symbol results

# Health monitoring
_HEALTH_WINDOW = 600      # 10 min window
_HEALTH_FAIL_THRESHOLD = 3  # consecutive failures before "degraded"
_REQUEST_TIMEOUT = 8      # seconds

# Rate control — avoid hammering the endpoint
_MIN_REQUEST_INTERVAL = 1.0  # seconds between HTTP requests

# ── Exchange prefix mapping for symbol normalization ─────────────

# TradingView uses EXCHANGE:TICKER format. We map common US tickers
# to their exchange prefix.  For unknown exchanges we try NASDAQ first.
_EXCHANGE_PREFIXES = {
    "AAPL": "NASDAQ", "MSFT": "NASDAQ", "GOOG": "NASDAQ", "GOOGL": "NASDAQ",
    "AMZN": "NASDAQ", "META": "NASDAQ", "NVDA": "NASDAQ", "TSLA": "NASDAQ",
    "AMD": "NASDAQ", "INTC": "NASDAQ", "NFLX": "NASDAQ", "PYPL": "NASDAQ",
    "ADBE": "NASDAQ", "CRM": "NYSE", "ORCL": "NYSE", "CSCO": "NASDAQ",
    "AVGO": "NASDAQ", "QCOM": "NASDAQ", "MU": "NASDAQ", "MRVL": "NASDAQ",
    "AMAT": "NASDAQ", "LRCX": "NASDAQ", "KLAC": "NASDAQ", "SNPS": "NASDAQ",
    "CDNS": "NASDAQ", "PANW": "NASDAQ", "CRWD": "NASDAQ", "ZS": "NASDAQ",
    "DDOG": "NASDAQ", "NET": "NYSE", "SNOW": "NYSE", "PLTR": "NASDAQ",
    "COIN": "NASDAQ", "MSTR": "NASDAQ", "SQ": "NYSE", "SHOP": "NYSE",
    "UBER": "NYSE", "LYFT": "NASDAQ", "DASH": "NASDAQ", "ABNB": "NASDAQ",
    "RBLX": "NYSE", "U": "NYSE", "SOFI": "NASDAQ", "HOOD": "NASDAQ",
    "JPM": "NYSE", "GS": "NYSE", "MS": "NYSE", "BAC": "NYSE",
    "WFC": "NYSE", "C": "NYSE", "V": "NYSE", "MA": "NYSE",
    "DIS": "NYSE", "CMCSA": "NASDAQ", "T": "NYSE", "VZ": "NYSE",
    "PFE": "NYSE", "JNJ": "NYSE", "UNH": "NYSE", "LLY": "NYSE",
    "MRK": "NYSE", "ABBV": "NYSE", "BMY": "NYSE", "AMGN": "NASDAQ",
    "GILD": "NASDAQ", "MRNA": "NASDAQ", "BNTX": "NASDAQ",
    "XOM": "NYSE", "CVX": "NYSE", "COP": "NYSE", "OXY": "NYSE",
    "WMT": "NASDAQ", "COST": "NASDAQ", "HD": "NYSE", "LOW": "NYSE",
    "TGT": "NYSE", "KO": "NYSE", "PEP": "NASDAQ", "MCD": "NYSE",
    "SBUX": "NASDAQ", "NKE": "NYSE", "F": "NYSE", "GM": "NYSE",
    "BA": "NYSE", "CAT": "NYSE", "DE": "NYSE", "GE": "NYSE",
    "HON": "NASDAQ", "MMM": "NYSE", "RTX": "NYSE", "LMT": "NYSE",
    "BRK.A": "NYSE", "BRK.B": "NYSE", "BLK": "NYSE", "SCHW": "NYSE",
    "RIVN": "NASDAQ", "LCID": "NASDAQ", "NIO": "NYSE",
    "SPY": "AMEX", "QQQ": "NASDAQ", "IWM": "AMEX", "DIA": "AMEX",
    # Crypto
    "BTCUSD": "BITSTAMP", "ETHUSD": "BITSTAMP",
}


# ── Data classes ─────────────────────────────────────────────────

@dataclass
class TVHeadline:
    """A single TradingView news headline."""
    id: str
    title: str
    provider: str                # e.g. "reuters", "dow-jones", "tradingview"
    source: str                  # human-readable, e.g. "Reuters", "Dow Jones Newswires"
    published: float             # Unix timestamp
    urgency: int                 # typically 2
    tickers: list[str]           # extracted tickers (e.g. ["AAPL", "MSFT"])
    story_url: str               # TradingView story path or external link
    is_exclusive: bool = False
    is_flash: bool = False
    permission: str = ""         # "headline", "provider", or ""

    def to_feed_dict(self) -> dict[str, Any]:
        """Convert to a dict compatible with the terminal feed format."""
        # Compute recency-based actionability from published timestamp
        if self.published > 0:
            _age_min = max((time.time() - self.published) / 60.0, 0.0)
            if _age_min <= 5:
                _recency = "ULTRA_FRESH"
            elif _age_min <= 15:
                _recency = "FRESH"
            elif _age_min <= 60:
                _recency = "WARM"
            elif _age_min <= 1440:
                _recency = "AGING"
            else:
                _recency = "STALE"
            _age_minutes: float | None = round(_age_min, 1)
        else:
            _recency = "UNKNOWN"
            _age_minutes = None
        _is_act = _recency in {"ULTRA_FRESH", "FRESH", "WARM"}

        return {
            "item_id": self.id,
            "ticker": self.tickers[0] if self.tickers else "MARKET",
            "tickers_all": self.tickers,
            "headline": self.title,
            "snippet": "",
            "url": self.story_url,
            "source": self.source,
            "published_ts": self.published,
            "updated_ts": self.published,
            "provider": f"tv_{self.provider}",
            # Scoring defaults — these headlines don't go through the
            # full classify pipeline but still need valid fields for
            # the Live Feed renderer.
            "category": "news",
            "impact": 0.5,
            "clarity": 0.5,
            "polarity": 0.0,
            "news_score": 0.4,       # moderate default
            "cluster_hash": "",
            "novelty_count": 1,
            "relevance": 0.5,
            "entity_count": len(self.tickers),
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "event_class": "UNKNOWN",
            "event_label": "",
            "materiality": "MEDIUM",
            "recency_bucket": _recency,
            "age_minutes": _age_minutes,
            "is_actionable": _is_act,
            "source_tier": _source_tier(self.provider),
            "source_rank": _source_rank(self.provider),
            "channels": [],
            "tags": ["tradingview"],
            "is_wiim": False,
        }


# ── Source quality heuristics ────────────────────────────────────

_TIER_1_PROVIDERS = {"reuters", "dow-jones", "market-watch"}
_TIER_2_PROVIDERS = {"tradingview", "dpa_afx", "cnbctv"}
_TIER_3_PROVIDERS = {"gurufocus", "stocktwits", "zacks", "invezz", "cointelegraph"}


def _source_tier(provider: str) -> str:
    p = provider.lower()
    if p in _TIER_1_PROVIDERS:
        return "TIER_1"
    if p in _TIER_2_PROVIDERS:
        return "TIER_2"
    if p in _TIER_3_PROVIDERS:
        return "TIER_3"
    return "TIER_4"


def _source_rank(provider: str) -> int:
    tier = _source_tier(provider)
    return {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}.get(tier, 4)


# ── In-memory cache ──────────────────────────────────────────────

_cache: dict[str, tuple[float, list[TVHeadline]]] = {}
_cache_lock = threading.Lock()


def _get_cached(key: str) -> list[TVHeadline] | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if time.time() - ts > _CACHE_TTL:
            del _cache[key]
            return None
        return val


def _set_cached(key: str, val: list[TVHeadline]) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), val)
        if len(_cache) > _CACHE_MAX_SIZE:
            now = time.time()
            expired = [k for k, (ts, _) in _cache.items() if now - ts > _CACHE_TTL]
            for k in expired:
                del _cache[k]
            if len(_cache) > _CACHE_MAX_SIZE:
                oldest = sorted(_cache, key=lambda k: _cache[k][0])
                for k in oldest[:len(_cache) - _CACHE_MAX_SIZE]:
                    del _cache[k]


# ── Health monitoring ────────────────────────────────────────────

@dataclass
class _HealthState:
    """Tracks TradingView API availability."""
    consecutive_failures: int = 0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0
    last_error: str = ""
    total_requests: int = 0
    total_failures: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_failures = 0
            self.last_success_ts = time.time()
            self.total_requests += 1

    def record_failure(self, error: str) -> None:
        with self._lock:
            self.consecutive_failures += 1
            self.last_failure_ts = time.time()
            self.last_error = error
            self.total_requests += 1
            self.total_failures += 1

    @property
    def is_healthy(self) -> bool:
        with self._lock:
            return self.consecutive_failures < _HEALTH_FAIL_THRESHOLD

    @property
    def status(self) -> str:
        with self._lock:
            if self.total_requests == 0:
                return "unknown"
            if self.consecutive_failures == 0:
                return "healthy"
            if self.consecutive_failures < _HEALTH_FAIL_THRESHOLD:
                return "degraded"
            return "down"


_health = _HealthState()

# Rate limiter
_last_request_ts: float = 0.0
_rate_lock = threading.Lock()


def is_available() -> bool:
    """Return True when the TradingView API appears reachable.

    Always returns True initially (before first request) —
    we optimistically try and let health tracking take over.
    """
    with _health._lock:
        if _health.total_requests == 0:
            return True
        return _health.consecutive_failures < _HEALTH_FAIL_THRESHOLD


def health_status() -> dict[str, Any]:
    """Return a health-status dict for sidebar display."""
    with _health._lock:
        # Compute status inline (avoid calling self.status which
        # would try to re-acquire the non-reentrant lock).
        if _health.total_requests == 0:
            _st = "unknown"
        elif _health.consecutive_failures == 0:
            _st = "healthy"
        elif _health.consecutive_failures < _HEALTH_FAIL_THRESHOLD:
            _st = "degraded"
        else:
            _st = "down"
        return {
            "status": _st,
            "consecutive_failures": _health.consecutive_failures,
            "last_success": _health.last_success_ts,
            "last_failure": _health.last_failure_ts,
            "last_error": _health.last_error,
            "total_requests": _health.total_requests,
            "total_failures": _health.total_failures,
            "uptime_pct": (
                round(100 * (1 - _health.total_failures / max(1, _health.total_requests)), 1)
            ),
        }


# ── Symbol normalization ─────────────────────────────────────────

def _to_tv_symbol(ticker: str) -> str:
    """Convert a bare ticker to EXCHANGE:TICKER format for the TV API."""
    ticker = ticker.upper().strip()
    if ":" in ticker:
        return ticker  # already qualified
    exchange = _EXCHANGE_PREFIXES.get(ticker, "NASDAQ")
    return f"{exchange}:{ticker}"


def _from_tv_symbol(tv_sym: str) -> str:
    """Extract bare ticker from EXCHANGE:TICKER format."""
    if ":" in tv_sym:
        return tv_sym.split(":", 1)[1]
    return tv_sym


# ── HTTP fetcher ─────────────────────────────────────────────────

def _fetch_raw(symbol: str) -> dict[str, Any]:
    """Fetch raw JSON from the TradingView headlines API.

    Applies rate limiting and updates health state.
    """
    global _last_request_ts

    # Rate limiting
    with _rate_lock:
        elapsed = time.time() - _last_request_ts
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        _last_request_ts = time.time()

    tv_sym = _to_tv_symbol(symbol)
    url = f"{_BASE_URL}?{_DEFAULT_PARAMS}&symbol={tv_sym}"

    request = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
    })

    try:
        with urlopen(request, timeout=_REQUEST_TIMEOUT, context=_SSL_CTX) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
            _health.record_success()
            return data
    except urllib.error.HTTPError as exc:
        _msg = f"HTTP {exc.code}"
        _health.record_failure(_msg)
        log.warning("TradingView headlines HTTP error for %s: %s", symbol, _msg)
        raise
    except urllib.error.URLError as exc:
        _msg = str(exc.reason)[:80]
        _health.record_failure(_msg)
        log.warning("TradingView headlines URL error for %s: %s", symbol, _msg)
        raise
    except Exception as exc:
        _msg = f"{type(exc).__name__}: {str(exc)[:80]}"
        _health.record_failure(_msg)
        log.warning("TradingView headlines error for %s: %s", symbol, _msg)
        raise


# ── Parser ───────────────────────────────────────────────────────

def _parse_items(data: dict[str, Any]) -> list[TVHeadline]:
    """Parse the TradingView JSON response into TVHeadline objects."""
    items: list[TVHeadline] = []
    for raw in data.get("items", []):
        try:
            # Extract tickers from relatedSymbols
            tickers: list[str] = []
            for rs in raw.get("relatedSymbols", []):
                sym = rs.get("symbol", "")
                if sym:
                    tk = _from_tv_symbol(sym)
                    if tk and len(tk) <= 10:
                        tickers.append(tk)
            # Deduplicate preserving order
            seen: set[str] = set()
            unique_tickers: list[str] = []
            for t in tickers:
                tu = t.upper()
                if tu not in seen:
                    seen.add(tu)
                    unique_tickers.append(tu)

            # Build story URL
            story_path = raw.get("storyPath", "")
            link = raw.get("link", "")
            story_url = link if link else (
                f"https://www.tradingview.com{story_path}" if story_path else ""
            )

            items.append(TVHeadline(
                id=raw.get("id", ""),
                title=raw.get("title", ""),
                provider=raw.get("provider", "unknown"),
                source=raw.get("source", ""),
                published=float(raw.get("published", 0)),
                urgency=int(raw.get("urgency", 2)),
                tickers=unique_tickers,
                story_url=story_url,
                is_exclusive=bool(raw.get("isExclusive", False)),
                is_flash=bool(raw.get("is_flash", False)),
                permission=raw.get("permission", ""),
            ))
        except Exception:
            log.debug("Skipping malformed TV headline item", exc_info=True)

    return items


# ── Public API ───────────────────────────────────────────────────

def fetch_tv_headlines(
    ticker: str,
    *,
    max_items: int = 30,
) -> list[TVHeadline]:
    """Fetch TradingView headlines for a single ticker.

    Returns cached data if available.  On error, returns empty list
    (health state is updated for monitoring).
    """
    cache_key = f"tv:{ticker.upper()}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached[:max_items]

    try:
        data = _fetch_raw(ticker)
        headlines = _parse_items(data)
        _set_cached(cache_key, headlines)
        return headlines[:max_items]
    except Exception:
        return []


def fetch_tv_multi(
    tickers: list[str],
    *,
    max_per_ticker: int = 15,
    max_total: int = 50,
) -> list[TVHeadline]:
    """Fetch TradingView headlines for multiple tickers.

    Fetches sequentially with rate limiting to avoid overloading
    the endpoint.  De-duplicates across tickers by headline ID.
    """
    all_items: list[TVHeadline] = []
    seen_ids: set[str] = set()

    for tk in tickers:
        if len(all_items) >= max_total:
            break
        try:
            items = fetch_tv_headlines(tk, max_items=max_per_ticker)
            for item in items:
                if item.id not in seen_ids and len(all_items) < max_total:
                    seen_ids.add(item.id)
                    all_items.append(item)
        except Exception:
            log.debug("TV multi-fetch failed for %s", tk, exc_info=True)

    # Sort by published descending (newest first)
    all_items.sort(key=lambda x: x.published, reverse=True)
    return all_items


def fetch_tv_feed_dicts(
    tickers: list[str],
    *,
    max_per_ticker: int = 10,
    max_total: int = 40,
) -> list[dict[str, Any]]:
    """Fetch TV headlines and return as feed-compatible dicts.

    This is the main entry point for integrating TV headlines
    into the terminal feed.  Each headline is converted to a dict
    matching the ``ClassifiedItem.to_dict()`` schema.
    """
    headlines = fetch_tv_multi(
        tickers,
        max_per_ticker=max_per_ticker,
        max_total=max_total,
    )
    return [h.to_feed_dict() for h in headlines]
