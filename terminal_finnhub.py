"""Lightweight Finnhub REST client for the Streamlit terminal.

Provides Reddit + Twitter social-sentiment data without importing
the heavier ``open_prep.macro`` module.  Uses the same ``FINNHUB_API_KEY``
env var.

All results are cached in-memory with a configurable TTL so the free
tier (30 req / s, no daily limit) is never stressed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen
import urllib.error

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

log = logging.getLogger(__name__)

_APIKEY_RE = re.compile(r"(apikey|api_key|token|key)=[^&\s]+", re.IGNORECASE)

# ── In-memory cache ──────────────────────────────────────────────

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_SOCIAL_TTL = 600  # 10 min — Finnhub social data updates slowly
_CACHE_MAX_SIZE = 200  # hard cap on cache entries
# Circuit-breaker / rate-limit scalars below are written from
# ``_finnhub_get`` and read from multiple consumer paths (social
# sentiment, sidebar status, polling threads).  Streamlit reruns +
# background threads can hit them concurrently, so all reads and
# writes go through ``_state_lock`` to avoid torn-state surprises.
_state_lock = threading.Lock()
_social_sentiment_blocked: bool = False  # circuit breaker for 403 (premium-only)
_rate_limit_backoff_until: float = 0.0  # epoch timestamp; skip calls until then
_consecutive_429_count: int = 0  # counter for exponential backoff
_BACKOFF_BASE_SECONDS = 5.0
_BACKOFF_MAX_SECONDS = 300.0  # 5 min ceiling

# ── Equity guard ─────────────────────────────────────────────────
# Finnhub social sentiment is designed for US equities only.
# Crypto, forex, indices, and other non-equity symbols return empty
# data and waste API quota.
_NON_EQUITY_PREFIXES = frozenset({"BINANCE:", "CRYPTO:", "FX:", "FOREX:", "INDEX:", "OANDA:"})
_NON_EQUITY_SUFFIXES = frozenset({".X", "-USD", "-EUR", "-BTC", "-ETH"})
_NON_EQUITY_PATTERNS = frozenset({"BTC", "ETH", "XRP", "SOL", "DOGE", "ADA", "DOT"})


def is_equity_symbol(symbol: str) -> bool:
    """Return True if *symbol* looks like a US equity ticker.

    Rejects crypto tickers, forex pairs, and index symbols that would
    produce empty results from the Finnhub social-sentiment endpoint.
    """
    s = symbol.upper().strip()
    if not s or len(s) > 10:
        return False
    if any(s.startswith(p) for p in _NON_EQUITY_PREFIXES):
        return False
    if any(s.endswith(sfx) for sfx in _NON_EQUITY_SUFFIXES):
        return False
    if s in _NON_EQUITY_PATTERNS:
        return False
    # Must be pure alpha or alpha with dot (e.g. BRK.B)
    cleaned = s.replace(".", "")
    if not cleaned.isalpha():
        return False
    return True


def social_sentiment_status() -> str:
    """Return a human-readable status string for the social sentiment path.

    Used by UI tabs to show clear feedback when the path is blocked.
    """
    with _state_lock:
        blocked = _social_sentiment_blocked
        backoff_until = _rate_limit_backoff_until
    if blocked:
        return "blocked_premium"
    if time.time() < backoff_until:
        return "rate_limited"
    if not _api_key():
        return "no_api_key"
    return "available"


def _get_cached(key: str, ttl: float) -> Any | None:
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
    with _cache_lock:
        _cache[key] = (time.time(), val)
        # Evict oldest entries when cache grows beyond limit
        if len(_cache) > _CACHE_MAX_SIZE:
            now = time.time()
            expired = [k for k, (ts, _) in _cache.items() if now - ts > _SOCIAL_TTL]
            for k in expired:
                del _cache[k]
            # If still over limit after TTL eviction, remove oldest
            if len(_cache) > _CACHE_MAX_SIZE:
                oldest = sorted(_cache, key=lambda k: _cache[k][0])
                for k in oldest[: len(_cache) - _CACHE_MAX_SIZE]:
                    del _cache[k]


# ── API key ──────────────────────────────────────────────────────

def _api_key() -> str:
    return os.environ.get("FINNHUB_API_KEY", "")


def is_available() -> bool:
    """Return True when a Finnhub API key is configured."""
    return bool(_api_key())


# ── HTTP helper ──────────────────────────────────────────────────

_BASE = "https://finnhub.io/api/v1"


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET from Finnhub.  Returns parsed JSON or empty dict on error.

    NOTE (E-3 audit, ``smc_core.resilient``):
        This function is intentionally **not** wrapped with
        ``@smc_core.resilient.resilient``. The decorator's contract is
        *retry-within-call with sleeps* — the wrapper blocks the calling
        thread for up to ``base_delay * 2^retries`` seconds. That is the
        right shape for batch / script adapters (see the FMP client
        migration in PR-stack on ``feat/e3-fmp-client-resilient-migration``)
        but the wrong shape for this module: the Streamlit terminal
        polls Finnhub from a UI thread and must remain *fail-fast +
        skip*. Returning ``{}`` immediately on error lets the next
        polling cycle retry without freezing the tab.

        The 403-permanent-disable on ``/social-sentiment`` and the
        429-skip-window on the rest of the API are a custom *circuit
        breaker* policy that ``@resilient`` cannot express today
        (its ``exceptions=`` filter retries; it does not permanently
        disable a call site or skip a global window). A future
        ``@circuit_breaker`` companion to ``@resilient`` would be the
        right fit. Logged as a follow-up in
        ``docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md``
        under E-3.
    """
    key = _api_key()
    if not key:
        return {}
    query_parts: list[str] = [f"token={key}"]
    for k, v in (params or {}).items():
        query_parts.append(f"{k}={v}")
    url = f"{_BASE}{path}?{'&'.join(query_parts)}"
    request = Request(url, headers={"Accept": "application/json"})
    # Rate-limit backoff guard
    global _rate_limit_backoff_until, _consecutive_429_count
    with _state_lock:
        if time.time() < _rate_limit_backoff_until:
            return {}
    try:
        with urlopen(request, timeout=15, context=_SSL_CTX) as resp:
            with _state_lock:
                _consecutive_429_count = 0  # reset on success
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            with _state_lock:
                _consecutive_429_count += 1
                backoff = min(
                    _BACKOFF_BASE_SECONDS * (2 ** (_consecutive_429_count - 1)),
                    _BACKOFF_MAX_SECONDS,
                )
                _rate_limit_backoff_until = time.time() + backoff
                attempt_for_log = _consecutive_429_count
            log.warning(
                "Finnhub rate-limited (429) for %s — backing off %.0f s (attempt %d)",
                path, backoff, attempt_for_log,
            )
        elif exc.code == 403:
            log.warning(
                "Finnhub HTTP 403 for %s — endpoint requires premium plan "
                "(suppressing further calls this session)", path,
            )
            if "social-sentiment" in path:
                global _social_sentiment_blocked
                with _state_lock:
                    _social_sentiment_blocked = True
        else:
            log.warning("Finnhub HTTP %s for %s", exc.code, path)
        return {}
    except Exception as exc:
        log.warning("Finnhub request failed for %s: %s", path, _APIKEY_RE.sub(r"\1=***", str(exc)))
        return {}


# ── Social Sentiment ─────────────────────────────────────────────

@dataclass
class SocialSentiment:
    """Aggregated social sentiment for a single symbol."""

    symbol: str = ""
    reddit_mentions: int = 0
    reddit_positive: float = 0.0
    reddit_negative: float = 0.0
    twitter_mentions: int = 0
    twitter_positive: float = 0.0
    twitter_negative: float = 0.0
    total_mentions: int = 0
    score: float = 0.0  # -1 … +1
    emoji: str = "📡⚪"

    @property
    def sentiment_label(self) -> str:
        if self.score > 0.3:
            return "bullish"
        if self.score < -0.3:
            return "bearish"
        return "neutral"


def fetch_social_sentiment(symbol: str) -> SocialSentiment | None:
    """Fetch Reddit + Twitter social sentiment for *symbol*.

    Returns ``None`` when no data is available or key is missing.
    Results are cached for ``_SOCIAL_TTL`` seconds (10 min).
    """
    with _state_lock:
        if _social_sentiment_blocked:
            return None
    sym = symbol.upper().strip()
    if not sym:
        return None
    if not is_equity_symbol(sym):
        log.info("Skipping social sentiment for non-equity symbol: %s", sym)
        return None

    cache_key = f"fh_social:{sym}"
    cached = _get_cached(cache_key, _SOCIAL_TTL)
    if cached is not None:
        return cached  # type: ignore[return-value]

    data = _get("/stock/social-sentiment", {"symbol": sym})
    if not isinstance(data, dict):
        return None

    reddit = data.get("reddit", [])
    twitter = data.get("twitter", [])
    if not reddit and not twitter:
        # Cache the miss so we don't keep retrying
        _set_cached(cache_key, None)
        return None

    r_mentions = sum(r.get("mention", 0) for r in reddit) if reddit else 0
    r_pos = sum(r.get("positiveScore", 0) for r in reddit) if reddit else 0
    r_neg = sum(r.get("negativeScore", 0) for r in reddit) if reddit else 0
    t_mentions = sum(t.get("mention", 0) for t in twitter) if twitter else 0
    t_pos = sum(t.get("positiveScore", 0) for t in twitter) if twitter else 0
    t_neg = sum(t.get("negativeScore", 0) for t in twitter) if twitter else 0

    total_pos = r_pos + t_pos
    total_neg = r_neg + t_neg
    total_mentions = r_mentions + t_mentions
    score = 0.0
    if total_pos + total_neg > 0:
        score = round((total_pos - total_neg) / (total_pos + total_neg), 4)

    if score > 0.3:
        emoji = "📡🟢"
    elif score < -0.3:
        emoji = "📡🔴"
    else:
        emoji = "📡⚪"

    result = SocialSentiment(
        symbol=sym,
        reddit_mentions=r_mentions,
        reddit_positive=round(r_pos, 2),
        reddit_negative=round(r_neg, 2),
        twitter_mentions=t_mentions,
        twitter_positive=round(t_pos, 2),
        twitter_negative=round(t_neg, 2),
        total_mentions=total_mentions,
        score=score,
        emoji=emoji,
    )
    _set_cached(cache_key, result)
    return result


def fetch_social_sentiment_batch(
    symbols: list[str],
    max_lookups: int = 20,
) -> dict[str, SocialSentiment]:
    """Fetch social sentiment for multiple symbols.

    Finnhub's free tier allows 30 req/s, so batching up to 20 symbols
    sequentially is fine.  Returns a dict keyed by uppercase symbol.
    """
    results: dict[str, SocialSentiment] = {}
    for sym in symbols[:max_lookups]:
        sent = fetch_social_sentiment(sym)
        if sent is not None:
            results[sent.symbol] = sent
    return results
