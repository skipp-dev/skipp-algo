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
import urllib.error
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

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
# PR4 (2026-05-09) — generalised path-prefix block list. Any path whose
# substring matches an entry here short-circuits in ``_get`` and returns
# ``{}`` immediately, mirroring the per-endpoint DISABLED-pattern from
# newsstack_fmp/ingest_unusual_whales.py and the FMP extras adapters.
_blocked_path_substrings: set[str] = set()
_rate_limit_backoff_until: float = 0.0  # monotonic timestamp; skip calls until then (PR-J4)
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
    return cleaned.isalpha()


def social_sentiment_status() -> str:
    """Return a human-readable status string for the social sentiment path.

    Used by UI tabs to show clear feedback when the path is blocked.
    """
    with _state_lock:
        blocked = _social_sentiment_blocked
        backoff_until = _rate_limit_backoff_until
    if blocked:
        return "blocked_premium"
    # Audit 2026-05-10 (PR-J4): _rate_limit_backoff_until is a
    # monotonic timestamp; compare with time.monotonic().
    if time.monotonic() < backoff_until:
        return "rate_limited"
    if not _api_key():
        return "no_api_key"
    return "available"


def _get_cached(key: str, ttl: float) -> tuple[bool, Any]:
    """Return ``(found, value)`` for *key*.

    Audit 2026-05-10 (PR-B): the previous signature returned ``None`` both
    for "no entry" and for "cached None" (empty-payload miss). That made
    ``_set_cached(key, None)`` ineffective -- callers would re-hit the
    upstream API on every subsequent empty response. The tuple makes the
    distinction explicit: ``found=True`` means a fresh cache entry exists
    (the value may legitimately be ``None``); ``found=False`` means the
    caller must perform the upstream fetch.
    """
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return (False, None)
        ts, val = entry
        # Audit 2026-05-10 (PR-J4): cache timestamps are monotonic.
        if time.monotonic() - ts > ttl:
            del _cache[key]
            return (False, None)
        return (True, val)


def _set_cached(key: str, val: Any) -> None:
    with _cache_lock:
        # Audit 2026-05-10 (PR-J4): use time.monotonic() for cache
        # timestamp arithmetic. time.time() (wall clock) jumps backwards
        # on NTP correction / VM live-migrate / manual `date -s` and
        # would either evict valid entries instantly or never expire
        # stale entries.
        _cache[key] = (time.monotonic(), val)
        # Evict oldest entries when cache grows beyond limit
        if len(_cache) > _CACHE_MAX_SIZE:
            now = time.monotonic()
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


def _get(path: str, params: dict[str, Any] | None = None, *, api_key: str | None = None) -> Any:
    """GET from Finnhub.  Returns parsed JSON or empty dict on error.

    The optional ``api_key`` keyword lets callers pass a key explicitly
    instead of relying on the process-global ``FINNHUB_API_KEY`` env var.
    Added in R6 (2026-05-12) to eliminate the racy
    ``os.environ["FINNHUB_API_KEY"] = ...`` shim that was previously used
    by ``open_prep.macro.FinnhubClient._http_get``. See
    ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md``.

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
    # Quantum-sweep L1: consolidate all ``global`` declarations at the top
    # of the function body so the mutation surface is auditable in one
    # place (was previously one declaration mid-function plus a second
    # nested inside the 403 branch).
    global _rate_limit_backoff_until, _consecutive_429_count, _social_sentiment_blocked
    key = (api_key or "").strip() or _api_key()
    if not key:
        return {}
    # PR4: generalised DISABLED-path short-circuit (any 403/404 path stays muted).
    with _state_lock:
        if any(sub in path for sub in _blocked_path_substrings):
            return {}
    query_parts: list[str] = [f"token={key}"]
    for k, v in (params or {}).items():
        query_parts.append(f"{k}={v}")
    url = f"{_BASE}{path}?{'&'.join(query_parts)}"
    request = Request(url, headers={"Accept": "application/json"})
    # Rate-limit backoff guard
    with _state_lock:
        # Audit 2026-05-10 (PR-J4): _rate_limit_backoff_until is monotonic.
        if time.monotonic() < _rate_limit_backoff_until:
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
                # Audit 2026-05-10 (PR-J4): monotonic deadline for backoff.
                _rate_limit_backoff_until = time.monotonic() + backoff
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
                with _state_lock:
                    _social_sentiment_blocked = True
            # PR4: also mark the full path-substring as blocked so the
            # generalised short-circuit prevents any further quota burn.
            with _state_lock:
                _blocked_path_substrings.add(path)
        elif exc.code == 404:
            log.warning(
                "Finnhub HTTP 404 for %s — endpoint retired or wrong path "
                "(suppressing further calls this session)", path,
            )
            with _state_lock:
                _blocked_path_substrings.add(path)
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
    found, cached = _get_cached(cache_key, _SOCIAL_TTL)
    if found:
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


# ── PR4 (2026-05-09): Finnhub free-tier extensions ───────────
# C3+C4 of Provider Audit 2.0 — surface free-tier endpoints that the
# existing module ignored (only social-sentiment was wired previously).
# All four use the same generic 403/404 DISABLED-path short-circuit
# landed earlier in this file so quota-locked endpoints auto-suppress.

# _NEWS_TTL removed 2026-05-12 (Option B): the Finnhub /company-news
# fetcher had no production consumers and is fully covered by FMP
# /stable/news/stock-latest (wired in newsstack_fmp/pipeline.py).
_SENTIMENT_TTL = 1800   # 30 min — news sentiment is a slower aggregate
_RECO_TTL = 21600       # 6 h    — recommendation trends update infrequently
_INSIDER_TTL = 21600    # 6 h    — insider sentiment is monthly


# CompanyNewsItem removed 2026-05-12 (Option B). The Finnhub /company-news
# endpoint is fully duplicative with FMP /stable/news/stock-latest, which
# is the canonical newsstack source (see newsstack_fmp/pipeline.py and
# scripts/probe_providers.py::probe_fmp_news). The dataclass had no
# production consumer outside of its own fetch_company_news() helper.


@dataclass(frozen=True, slots=True)
class NewsSentimentSummary:
    """Aggregated /news-sentiment buzz/sentiment snapshot for a symbol."""

    symbol: str
    buzz_articles_in_last_week: int
    buzz_weekly_average: float
    buzz_score: float
    company_news_score: float
    sector_avg_news_score: float
    sentiment_bearish_pct: float
    sentiment_bullish_pct: float


@dataclass(frozen=True, slots=True)
class RecommendationTrend:
    """One row of /stock/recommendation — analyst grade tally for a period."""

    symbol: str
    period: str  # ISO date string of the month the row applies to
    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int


@dataclass(frozen=True, slots=True)
class InsiderSentimentMonth:
    """One row of /stock/insider-sentiment — monthly insider activity."""

    symbol: str
    year: int
    month: int
    change: int   # net share change
    mspr: float   # monthly share purchase ratio


def _ymd_window(days_back: int) -> tuple[str, str]:
    """Return (from_yyyymmdd, to_yyyymmdd) covering [today-N, today]."""
    import datetime as _dt

    today = _dt.date.today()
    start = today - _dt.timedelta(days=max(1, days_back))
    return start.isoformat(), today.isoformat()


# fetch_company_news() removed 2026-05-12 (Option B). Replacement:
# the FMP /stable/news/stock-latest endpoint is the canonical newsstack
# source via newsstack_fmp/pipeline.py. The Finnhub variant had no
# production consumers and the /company-news endpoint is a Finnhub
# free-tier feature that frequently rate-limits during market hours.


def fetch_news_sentiment(symbol: str) -> NewsSentimentSummary | None:
    """GET /news-sentiment?symbol= — aggregate buzz + bullish/bearish split.

    Returns ``None`` on HTTP error / quota lock / non-equity symbol.
    Caches per symbol for 30 minutes.
    """
    if not is_equity_symbol(symbol):
        return None
    sym = symbol.upper().strip()
    cache_key = f"news_sentiment:{sym}"
    found, cached = _get_cached(cache_key, _SENTIMENT_TTL)
    if found:
        return cached  # type: ignore[return-value]
    raw = _get("/news-sentiment", {"symbol": sym})
    if not isinstance(raw, dict) or not raw:
        return None
    buzz = raw.get("buzz") or {}
    sent = raw.get("sentiment") or {}
    try:
        summary = NewsSentimentSummary(
            symbol=sym,
            buzz_articles_in_last_week=int(buzz.get("articlesInLastWeek") or 0),
            buzz_weekly_average=float(buzz.get("weeklyAverage") or 0.0),
            buzz_score=float(buzz.get("buzz") or 0.0),
            company_news_score=float(raw.get("companyNewsScore") or 0.0),
            sector_avg_news_score=float(raw.get("sectorAverageNewsScore") or 0.0),
            sentiment_bearish_pct=float(sent.get("bearishPercent") or 0.0),
            sentiment_bullish_pct=float(sent.get("bullishPercent") or 0.0),
        )
    except (TypeError, ValueError):
        return None
    _set_cached(cache_key, summary)
    return summary


def fetch_recommendation_trends(symbol: str) -> list[RecommendationTrend]:
    """GET /stock/recommendation?symbol= — analyst grade tally per month.

    Returns the list ordered as Finnhub returns it (most-recent first).
    Returns ``[]`` on HTTP error / quota lock / non-equity symbol.
    Caches per symbol for 6 hours.
    """
    if not is_equity_symbol(symbol):
        return []
    sym = symbol.upper().strip()
    cache_key = f"reco_trend:{sym}"
    found, cached = _get_cached(cache_key, _RECO_TTL)
    if found:
        return cached  # type: ignore[return-value]
    raw = _get("/stock/recommendation", {"symbol": sym})
    if not isinstance(raw, list):
        return []
    out: list[RecommendationTrend] = []
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        try:
            out.append(
                RecommendationTrend(
                    symbol=sym,
                    period=str(rec.get("period") or "").strip(),
                    strong_buy=int(rec.get("strongBuy") or 0),
                    buy=int(rec.get("buy") or 0),
                    hold=int(rec.get("hold") or 0),
                    sell=int(rec.get("sell") or 0),
                    strong_sell=int(rec.get("strongSell") or 0),
                )
            )
        except (TypeError, ValueError):
            continue
    _set_cached(cache_key, out)
    return out


def fetch_insider_sentiment(
    symbol: str, *, months_back: int = 6
) -> list[InsiderSentimentMonth]:
    """GET /stock/insider-sentiment?symbol=&from=&to= — monthly insider net flow.

    *months_back* selects the lookback window; default 6 months.
    Returns ``[]`` on HTTP error / quota lock / non-equity symbol.
    Caches per (symbol, months_back) for 6 hours.
    """
    if not is_equity_symbol(symbol):
        return []
    sym = symbol.upper().strip()
    cache_key = f"insider_sent:{sym}:{months_back}"
    found, cached = _get_cached(cache_key, _INSIDER_TTL)
    if found:
        return cached  # type: ignore[return-value]
    frm, to = _ymd_window(max(30, months_back * 31))
    raw = _get("/stock/insider-sentiment", {"symbol": sym, "from": frm, "to": to})
    if not isinstance(raw, dict):
        return []
    # Audit-fix (2026-05-09): treat empty dict (rate-limit / key-miss / 4xx
    # short-circuit) as a transient miss — do NOT cache an empty list for the
    # full 6h TTL or the endpoint goes silently dark for hours after a 429.
    if not raw:
        return []
    rows = raw.get("data") or []
    if not isinstance(rows, list):
        return []
    out: list[InsiderSentimentMonth] = []
    for rec in rows:
        if not isinstance(rec, dict):
            continue
        try:
            out.append(
                InsiderSentimentMonth(
                    symbol=sym,
                    year=int(rec.get("year") or 0),
                    month=int(rec.get("month") or 0),
                    change=int(rec.get("change") or 0),
                    mspr=float(rec.get("mspr") or 0.0),
                )
            )
        except (TypeError, ValueError):
            continue
    _set_cached(cache_key, out)
    return out


def clear_blocked_paths() -> None:
    """Reset the generalised DISABLED-path short-circuit (test helper)."""
    global _social_sentiment_blocked
    with _state_lock:
        _blocked_path_substrings.clear()
        _social_sentiment_blocked = False
