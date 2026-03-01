"""Lightweight Finnhub REST client for the Streamlit terminal.

Provides Reddit + Twitter social-sentiment data without importing
the heavier ``open_prep.macro`` module.  Uses the same ``FINNHUB_API_KEY``
env var.

All results are cached in-memory with a configurable TTL so the free
tier (30 req / s, no daily limit) is never stressed.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.request import Request, urlopen
import urllib.error

log = logging.getLogger(__name__)

_APIKEY_RE = re.compile(r"(apikey|api_key|token|key)=[^&\s]+", re.IGNORECASE)

# ── In-memory cache ──────────────────────────────────────────────

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_SOCIAL_TTL = 600  # 10 min — Finnhub social data updates slowly


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


# ── API key ──────────────────────────────────────────────────────

def _api_key() -> str:
    return os.environ.get("FINNHUB_API_KEY", "")


def is_available() -> bool:
    """Return True when a Finnhub API key is configured."""
    return bool(_api_key())


# ── HTTP helper ──────────────────────────────────────────────────

_BASE = "https://finnhub.io/api/v1"


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET from Finnhub.  Returns parsed JSON or empty dict on error."""
    key = _api_key()
    if not key:
        return {}
    query_parts: list[str] = [f"token={key}"]
    for k, v in (params or {}).items():
        query_parts.append(f"{k}={v}")
    url = f"{_BASE}{path}?{'&'.join(query_parts)}"
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            log.warning("Finnhub rate-limited (429) for %s", path)
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
    sym = symbol.upper().strip()
    if not sym:
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
