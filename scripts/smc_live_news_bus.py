from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from newsstack_fmp.common_types import NewsItem
from newsstack_fmp.ingest_benzinga import BenzingaRssAdapter
from newsstack_fmp.ingest_benzinga import fetch_benzinga_quantified_news as _fetch_benzinga_quantified
from newsstack_fmp.ingest_fmp import FmpAdapter
from newsstack_fmp.normalize import normalize_newsapi_ai
from newsstack_fmp.scoring import classify_and_score, cluster_hash
from newsstack_fmp.shared_fetch import (
    DEFAULT_SHARED_NEWS_CACHE_DIR,
    DEFAULT_SHARED_NEWS_CACHE_TTL_SECONDS,
    fetch_cached_batch,
    tv_headline_to_news_item,
)
from scripts.smc_atomic_write import atomic_write_text
from smc_integration.release_policy import RELEASE_REFERENCE_SYMBOLS
from terminal_tradingview_news import fetch_tv_multi

logger = logging.getLogger(__name__)

_SENSITIVE_QUERY_RE = re.compile(r"(apikey|api_key|token|key)=[^&\s]+", re.IGNORECASE)

PROVIDER_ORDER = ("benzinga", "benzinga_quantified", "fmp_stock", "fmp_press", "fmp_articles", "newsapi_ai", "tv")
DEFAULT_STORY_WINDOW_SECONDS = 24 * 60 * 60
DEFAULT_STATE_RETENTION_SECONDS = 7 * 24 * 60 * 60
DEFAULT_MAX_STATE_STORIES = 5000
DEFAULT_SYMBOL_LIMIT = 100
DEFAULT_TV_SYMBOL_LIMIT = 20
_SHARED_CACHE_DIR = os.getenv("SHARED_NEWS_CACHE_DIR", DEFAULT_SHARED_NEWS_CACHE_DIR)
_SHARED_CACHE_TTL_SECONDS = float(os.getenv("SHARED_NEWS_CACHE_TTL_SECONDS", str(DEFAULT_SHARED_NEWS_CACHE_TTL_SECONDS)))

_TIER_RANK = {
    "TIER_1": 1,
    "TIER_2": 2,
    "TIER_3": 3,
    "TIER_4": 4,
}
_RECENCY_MULTIPLIER = {
    "ULTRA_FRESH": 1.15,
    "FRESH": 1.0,
    "WARM": 0.8,
    "AGING": 0.55,
    "STALE": 0.3,
    "UNKNOWN": 0.5,
}
_ACTIONABLE_RECENCY_BUCKETS = {"ULTRA_FRESH", "FRESH", "WARM"}
_ACTIONABLE_MATERIALITY = {"HIGH", "MEDIUM"}
_WARM_MAX_AGE_MINUTES = 60.0
_EARLY_AGING_ACTIONABLE_MAX_MINUTES = 180.0
_SOFT_AGING_RECENCY_MAX_MINUTES = 300.0
_CATEGORY_TO_EVENT_CLASS = {
    "halt": "HALT",
    "offering": "OFFERING",
    "mna": "MNA",
    "fda": "FDA",
    "guidance": "GUIDANCE",
    "insider": "INSIDER",
    "buyback": "BUYBACK",
    "dividend": "DIVIDEND",
    "earnings": "EARNINGS",
    "macro": "MACRO",
    "crypto": "CRYPTO",
    "ipo": "IPO",
    "analyst": "ANALYST",
    "contract": "CONTRACT",
    "lawsuit": "LEGAL",
    "management": "MANAGEMENT",
    "other": "UNKNOWN",
}


@dataclass(frozen=True)
class LiveNewsCandidate:
    provider_bucket: str
    provider_name: str
    item_id: str
    headline: str
    tickers: tuple[str, ...]
    published_ts: float
    updated_ts: float
    url: str
    source: str


@dataclass
class ProviderPollResult:
    provider: str
    ok: bool = True
    items: list[LiveNewsCandidate] = field(default_factory=list)
    raw_count: int = 0
    cursor: float = 0.0
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def _normalize_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_symbol in symbols:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _coerce_timestamp(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return max(float(value), 0.0)
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        return max(float(text), 0.0)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _isoformat_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(max(timestamp, 0.0), tz=UTC).isoformat().replace("+00:00", "Z")


def _recency_bucket(age_minutes: float | None) -> str:
    if age_minutes is None:
        return "UNKNOWN"
    if age_minutes <= 5.0:
        return "ULTRA_FRESH"
    if age_minutes <= 15.0:
        return "FRESH"
    if age_minutes <= 60.0:
        return "WARM"
    if age_minutes <= 1440.0:
        return "AGING"
    return "STALE"


def _source_tier(source: str, provider_bucket: str) -> str:
    lowered = (source or "").strip().lower()
    if any(token in lowered for token in ("reuters", "dow jones", "dow-jones", "marketwatch", "associated press", " ap ")):
        return "TIER_1"
    if any(token in lowered for token in ("benzinga", "tradingview", "cnbc", "dpa", "afx")):
        return "TIER_2"
    if any(token in lowered for token in ("pr newswire", "globe newswire", "business wire", "accesswire", "financial modeling prep", "financialmodelingprep", "fmp")):
        return "TIER_3"
    if provider_bucket == "benzinga":
        return "TIER_2"
    if provider_bucket in {"fmp_stock", "fmp_press", "fmp_articles"}:
        return "TIER_3"
    if provider_bucket == "newsapi_ai":
        return "TIER_3"
    if provider_bucket == "tv":
        return "TIER_2"
    return "TIER_4"


def _source_rank(source_tier: str) -> int:
    return _TIER_RANK.get(source_tier, 4)


def _sentiment_label(polarity: float) -> str:
    if polarity > 0.1:
        return "bullish"
    if polarity < -0.1:
        return "bearish"
    return "neutral"


def _materiality(score: float) -> str:
    if score >= 0.75:
        return "HIGH"
    if score >= 0.5:
        return "MEDIUM"
    return "LOW"


def _recency_multiplier(age_minutes: float | None) -> float:
    recency = _recency_bucket(age_minutes)
    default_multiplier = _RECENCY_MULTIPLIER.get(recency, 0.5)
    if recency != "AGING" or age_minutes is None:
        return default_multiplier
    if age_minutes <= _EARLY_AGING_ACTIONABLE_MAX_MINUTES:
        progress = max(min((age_minutes - _WARM_MAX_AGE_MINUTES) / (_EARLY_AGING_ACTIONABLE_MAX_MINUTES - _WARM_MAX_AGE_MINUTES), 1.0), 0.0)
        return 0.8 - 0.1 * progress
    if age_minutes <= _SOFT_AGING_RECENCY_MAX_MINUTES:
        progress = (age_minutes - _EARLY_AGING_ACTIONABLE_MAX_MINUTES) / (_SOFT_AGING_RECENCY_MAX_MINUTES - _EARLY_AGING_ACTIONABLE_MAX_MINUTES)
        return 0.7 - 0.15 * progress
    return default_multiplier


def _is_actionable_story(*, recency_bucket: str, materiality: str, age_minutes: float | None) -> bool:
    if materiality not in _ACTIONABLE_MATERIALITY:
        return False
    if recency_bucket in _ACTIONABLE_RECENCY_BUCKETS:
        return True
    return recency_bucket == "AGING" and age_minutes is not None and age_minutes <= _EARLY_AGING_ACTIONABLE_MAX_MINUTES


def _event_class(category: str) -> str:
    return _CATEGORY_TO_EVENT_CLASS.get(category, "UNKNOWN")


def _event_label(headline: str) -> str:
    cleaned = " ".join(str(headline or "").split())
    return cleaned[:120]


def _story_key(headline: str, tickers: tuple[str, ...], published_ts: float) -> tuple[str, str]:
    cluster = cluster_hash(headline, list(tickers))
    bucket = int(max(published_ts, 0.0) // 300)
    return cluster, f"{cluster}:{bucket}"


def _select_representative(candidates: list[LiveNewsCandidate]) -> LiveNewsCandidate:
    def _sort_key(candidate: LiveNewsCandidate) -> tuple[int, float, str]:
        return (
            _source_rank(_source_tier(candidate.source, candidate.provider_bucket)),
            candidate.published_ts,
            candidate.provider_bucket,
        )

    return sorted(candidates, key=_sort_key)[0]


def _candidate_from_news_item(
    item: NewsItem,
    *,
    provider_bucket: str,
    provider_name: str,
    universe: set[str],
) -> LiveNewsCandidate | None:
    headline = str(item.headline or "").strip()
    if not headline:
        return None
    tickers = tuple(sorted({str(ticker or "").strip().upper() for ticker in item.tickers if str(ticker or "").strip().upper() in universe}))
    if not tickers:
        return None
    published_ts = _coerce_timestamp(item.published_ts)
    updated_ts = max(_coerce_timestamp(item.updated_ts), published_ts)
    item_id = str(item.item_id or "").strip()
    if not item_id:
        item_id = f"{provider_bucket}:{cluster_hash(headline, list(tickers))}:{int(published_ts)}"
    return LiveNewsCandidate(
        provider_bucket=provider_bucket,
        provider_name=provider_name,
        item_id=item_id,
        headline=headline,
        tickers=tickers,
        published_ts=published_ts,
        updated_ts=updated_ts,
        url=str(item.url or ""),
        source=str(item.source or provider_name or provider_bucket),
    )


def _disabled_provider(provider: str, *, cursor: float, error: str) -> ProviderPollResult:
    return ProviderPollResult(provider=provider, ok=False, items=[], raw_count=0, cursor=cursor, error=error)


def _sanitize_error_text(value: Any) -> str:
    return _SENSITIVE_QUERY_RE.sub(r"\1=***", str(value or ""))


def _newsapi_records_from_items(items: list[NewsItem]) -> list[dict[str, Any]]:
    return [item.raw for item in items if item.provider == "newsapi_ai" and isinstance(item.raw, dict)]


def _next_newsapi_feed_uri(current_uri: str, items: list[NewsItem], *, cursor_advanced: bool) -> str:
    from scripts.smc_newsapi_ai import extract_newsapi_feed_article_cursor_uri

    next_uri = extract_newsapi_feed_article_cursor_uri(_newsapi_records_from_items(items))
    if next_uri:
        return next_uri
    if cursor_advanced:
        return ""
    return str(current_uri or "").strip()


def _newsapi_operator_status(
    *,
    cursor: float,
    raw_items: list[NewsItem],
    candidates: list[LiveNewsCandidate],
) -> tuple[str, str]:
    if candidates:
        return "ok", ""
    if cursor <= 0.0:
        return "ok", ""
    if raw_items:
        return (
            "ok_no_recent_matches",
            "Event Registry reachable, but no new symbol-matching NewsAPI.ai items were newer than the current cursor.",
        )
    return (
        "ok_no_recent_matches",
        "Event Registry reachable, but no recent symbol-matching NewsAPI.ai items were returned for the current feed window.",
    )


def _fetch_cached_live_provider_batch(
    *,
    provider: str,
    scope: dict[str, Any],
    cursor: float,
    fetcher: Any,
):
    return fetch_cached_batch(
        provider=provider,
        scope=scope,
        ttl_seconds=_SHARED_CACHE_TTL_SECONDS,
        min_cursor=cursor,
        fetcher=fetcher,
        cache_dir=_SHARED_CACHE_DIR,
    )


def fetch_live_news_benzinga(
    *,
    api_key: str,
    symbols: list[str],
    cursor: float,
    page_size: int,
) -> ProviderPollResult:
    # Switched from BenzingaRestAdapter (paid API, returned 401 since the
    # subscription lapsed — run 628, 2026-06-30) to BenzingaRssAdapter (free
    # public RSS feed, no API key required). The api_key parameter is kept for
    # signature compatibility with the bus dispatch but is ignored.
    universe = set(symbols)
    adapter = BenzingaRssAdapter()
    batch = _fetch_cached_live_provider_batch(
        provider="benzinga_rss",
        scope={"page_size": page_size},
        cursor=cursor,
        fetcher=lambda: adapter.fetch_news(min_epoch=cursor),
    )
    candidates = [
        candidate
        for item in batch.items
        if (candidate := _candidate_from_news_item(item, provider_bucket="benzinga", provider_name="benzinga_rss", universe=universe)) is not None
    ]
    return ProviderPollResult(provider="benzinga", ok=True, items=candidates, raw_count=batch.raw_count, cursor=batch.cursor)


def fetch_live_news_benzinga_quantified(
    *,
    api_key: str,
    symbols: list[str],
    cursor: float,
    page_size: int,
) -> ProviderPollResult:
    """Fetch Benzinga quantified news (items with price-impact context) (WP-NW6)."""
    if not api_key:
        return _disabled_provider("benzinga_quantified", cursor=cursor, error="missing_api_key")
    universe = set(symbols)
    from newsstack_fmp.normalize import normalize_benzinga_quantified

    try:
        raw_items = _fetch_benzinga_quantified(api_key, page_size=page_size)
    except Exception:
        logger.warning("Benzinga quantified fetch failed", exc_info=True)
        return _disabled_provider("benzinga_quantified", cursor=cursor, error="fetch_failed")

    items = [normalize_benzinga_quantified(it) for it in raw_items if isinstance(it, dict)]
    candidates = [
        candidate
        for item in items
        if (candidate := _candidate_from_news_item(item, provider_bucket="benzinga_quantified", provider_name="benzinga_quantified", universe=universe)) is not None
    ]
    new_cursor = cursor
    for candidate in candidates:
        if candidate.published_ts > new_cursor:
            new_cursor = candidate.published_ts
    return ProviderPollResult(provider="benzinga_quantified", ok=True, items=candidates, raw_count=len(raw_items), cursor=new_cursor)


def fetch_live_news_fmp_stock(
    *,
    api_key: str,
    symbols: list[str],
    cursor: float,
    page_size: int,
) -> ProviderPollResult:
    if not api_key:
        return _disabled_provider("fmp_stock", cursor=cursor, error="missing_api_key")
    universe = set(symbols)
    adapter = FmpAdapter(api_key)
    try:
        batch = _fetch_cached_live_provider_batch(
            provider="fmp_stock_latest",
            scope={"page": 0, "limit": page_size},
            cursor=cursor,
            fetcher=lambda: adapter.fetch_stock_latest(page=0, limit=page_size),
        )
    finally:
        adapter.close()
    candidates = [
        candidate
        for item in batch.items
        if (candidate := _candidate_from_news_item(item, provider_bucket="fmp_stock", provider_name=item.provider, universe=universe)) is not None
    ]
    return ProviderPollResult(provider="fmp_stock", ok=True, items=candidates, raw_count=batch.raw_count, cursor=batch.cursor)


def fetch_live_news_fmp_press(
    *,
    api_key: str,
    symbols: list[str],
    cursor: float,
    page_size: int,
) -> ProviderPollResult:
    if not api_key:
        return _disabled_provider("fmp_press", cursor=cursor, error="missing_api_key")
    universe = set(symbols)
    adapter = FmpAdapter(api_key)
    try:
        batch = _fetch_cached_live_provider_batch(
            provider="fmp_press_latest",
            scope={"page": 0, "limit": page_size},
            cursor=cursor,
            fetcher=lambda: adapter.fetch_press_latest(page=0, limit=page_size),
        )
    finally:
        adapter.close()
    candidates = [
        candidate
        for item in batch.items
        if (candidate := _candidate_from_news_item(item, provider_bucket="fmp_press", provider_name=item.provider, universe=universe)) is not None
    ]
    return ProviderPollResult(provider="fmp_press", ok=True, items=candidates, raw_count=batch.raw_count, cursor=batch.cursor)


def fetch_live_news_fmp_articles(
    *,
    api_key: str,
    symbols: list[str],
    cursor: float,
    limit: int,
) -> ProviderPollResult:
    if not api_key:
        return _disabled_provider("fmp_articles", cursor=cursor, error="missing_api_key")
    universe = set(symbols)
    adapter = FmpAdapter(api_key)
    try:
        batch = _fetch_cached_live_provider_batch(
            provider="fmp_articles",
            scope={"limit": limit},
            cursor=cursor,
            fetcher=lambda: adapter.fetch_articles(limit=limit),
        )
    finally:
        adapter.close()
    candidates = [
        candidate
        for item in batch.items
        if (candidate := _candidate_from_news_item(item, provider_bucket="fmp_articles", provider_name=item.provider, universe=universe)) is not None
    ]
    return ProviderPollResult(provider="fmp_articles", ok=True, items=candidates, raw_count=batch.raw_count, cursor=batch.cursor)


def fetch_live_news_newsapi_ai(
    *,
    api_key: str,
    symbols: list[str],
    cursor: float,
    article_feed_after_uri: str = "",
    lookback_days: int = 2,
    articles_per_request: int = 100,
) -> ProviderPollResult:
    if not api_key:
        return _disabled_provider("newsapi_ai", cursor=cursor, error="missing_api_key")
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        return _disabled_provider("newsapi_ai", cursor=cursor, error="no_symbols")

    from scripts.smc_newsapi_ai import NewsApiAiProviderError, fetch_newsapi_records

    universe = set(normalized_symbols)
    try:
        batch = _fetch_cached_live_provider_batch(
            provider="newsapi_ai",
            scope={
                "symbols": normalized_symbols,
                "lookback_days": lookback_days,
                "articles_per_request": articles_per_request,
                "include_events": True,
                "article_feed_after_uri": article_feed_after_uri.strip(),
            },
            cursor=cursor,
            fetcher=lambda: [
                normalize_newsapi_ai(article)
                for article in fetch_newsapi_records(
                    api_key,
                    normalized_symbols,
                    lookback_days=lookback_days,
                    articles_per_request=articles_per_request,
                    prefer_article_feed=cursor > 0.0,
                    article_feed_after_epoch=cursor,
                    article_feed_after_uri=article_feed_after_uri,
                )
            ],
        )
    except NewsApiAiProviderError as exc:
        return ProviderPollResult(
            provider="newsapi_ai",
            ok=False,
            items=[],
            raw_count=0,
            cursor=cursor,
            error=_sanitize_error_text(str(exc)),
            meta={
                "provider_status": exc.provider_status,
                "error_code": exc.error_code,
            },
        )
    next_feed_uri = _next_newsapi_feed_uri(
        article_feed_after_uri,
        batch.items,
        cursor_advanced=batch.cursor > cursor,
    )
    candidates = [
        candidate
        for item in batch.items
        if (candidate := _candidate_from_news_item(item, provider_bucket="newsapi_ai", provider_name=item.provider, universe=universe)) is not None
    ]
    provider_status, status_detail = _newsapi_operator_status(
        cursor=cursor,
        raw_items=list(batch.raw_items),
        candidates=candidates,
    )
    return ProviderPollResult(
        provider="newsapi_ai",
        ok=True,
        items=candidates,
        raw_count=batch.raw_count,
        cursor=batch.cursor,
        meta={
            "last_seen_news_uri": next_feed_uri,
            "provider_status": provider_status,
            "status_detail": status_detail,
        },
    )


def fetch_live_news_tv(
    *,
    symbols: list[str],
    cursor: float,
    max_per_ticker: int,
    max_total: int,
    symbol_limit: int,
) -> ProviderPollResult:
    scoped_symbols = symbols[: max(symbol_limit, 0)] if symbol_limit > 0 else list(symbols)
    if not scoped_symbols:
        return _disabled_provider("tv", cursor=cursor, error="no_symbols")
    universe = set(scoped_symbols)
    batch = _fetch_cached_live_provider_batch(
        provider="tradingview",
        scope={
            "symbols": scoped_symbols,
            "max_per_ticker": max_per_ticker,
            "max_total": max_total,
        },
        cursor=cursor,
        fetcher=lambda: [
            tv_headline_to_news_item(headline)
            for headline in fetch_tv_multi(scoped_symbols, max_per_ticker=max_per_ticker, max_total=max_total)
        ],
    )
    candidates = [
        candidate
        for item in batch.items
        if (candidate := _candidate_from_news_item(item, provider_bucket="tv", provider_name=item.provider, universe=universe)) is not None
    ]
    return ProviderPollResult(provider="tv", ok=True, items=candidates, raw_count=batch.raw_count, cursor=batch.cursor)


def _normalize_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw_payload = payload or {}
    raw_cursors = raw_payload.get("provider_cursors") if isinstance(raw_payload, dict) else None
    cursors = {provider: _coerce_timestamp((raw_cursors or {}).get(provider) if isinstance(raw_cursors, dict) else None) for provider in PROVIDER_ORDER}
    cursors["legacy_cursor"] = max(cursors.values(), default=0.0)

    raw_provider_state = raw_payload.get("provider_state") if isinstance(raw_payload, dict) else None
    provider_state: dict[str, dict[str, Any]] = {}
    if isinstance(raw_provider_state, dict):
        raw_newsapi_state = raw_provider_state.get("newsapi_ai")
        if isinstance(raw_newsapi_state, dict):
            last_seen_news_uri = str(raw_newsapi_state.get("last_seen_news_uri") or "").strip()
            if last_seen_news_uri:
                provider_state["newsapi_ai"] = {"last_seen_news_uri": last_seen_news_uri}

    raw_story_state = raw_payload.get("story_state") if isinstance(raw_payload, dict) else None
    story_state: dict[str, dict[str, Any]] = {}
    if isinstance(raw_story_state, dict):
        for raw_key, raw_value in raw_story_state.items():
            if not isinstance(raw_value, dict):
                continue
            story_key = str(raw_key or "").strip()
            if not story_key:
                continue
            tickers = _normalize_symbols(list(raw_value.get("tickers") or []))
            if not tickers:
                continue
            providers = [provider for provider in PROVIDER_ORDER if provider in set(str(item).strip() for item in raw_value.get("providers") or [])]
            story_state[story_key] = {
                "story_key": story_key,
                "cluster_hash": str(raw_value.get("cluster_hash") or story_key.split(":", 1)[0]),
                "headline": str(raw_value.get("headline") or "").strip(),
                "tickers": tickers,
                "published_ts": _coerce_timestamp(raw_value.get("published_ts")),
                "first_seen_ts": _coerce_timestamp(raw_value.get("first_seen_ts")),
                "first_provider": str(raw_value.get("first_provider") or "unknown"),
                "providers": providers,
                "provider_names": sorted({str(item).strip() for item in raw_value.get("provider_names") or [] if str(item).strip()}),
                "sources": sorted({str(item).strip() for item in raw_value.get("sources") or [] if str(item).strip()}),
                "url": str(raw_value.get("url") or "").strip(),
                "category": str(raw_value.get("category") or "other"),
                "impact": float(raw_value.get("impact") or 0.0),
                "clarity": float(raw_value.get("clarity") or 0.0),
                "relevance": float(raw_value.get("relevance") or 0.0),
                "polarity": float(raw_value.get("polarity") or 0.0),
                "source_tier": str(raw_value.get("source_tier") or "TIER_4"),
                "source_rank": int(raw_value.get("source_rank") or 4),
                "last_seen_ts": _coerce_timestamp(raw_value.get("last_seen_ts")),
            }
    return {"provider_cursors": cursors, "provider_state": provider_state, "story_state": story_state}


def load_live_news_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _normalize_state(None)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read live news state: %s", path, exc_info=True)
        return _normalize_state(None)
    return _normalize_state(payload if isinstance(payload, dict) else None)


def save_live_news_state(path: Path, state: dict[str, Any]) -> None:
    normalized = _normalize_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(normalized, indent=2) + "\n", path)


def write_live_news_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(snapshot, indent=2) + "\n", path)


def _story_score(entry: dict[str, Any], *, age_minutes: float | None) -> float:
    recency_multiplier = _recency_multiplier(age_minutes)
    source_bonus = {
        "TIER_1": 0.15,
        "TIER_2": 0.10,
        "TIER_3": 0.05,
        "TIER_4": 0.0,
    }.get(str(entry.get("source_tier") or "TIER_4"), 0.0)
    provider_bonus = min(0.08, 0.04 * max(len(entry.get("providers") or []) - 1, 0))
    base_score = (
        float(entry.get("impact") or 0.0) * 0.45
        + float(entry.get("clarity") or 0.0) * 0.15
        + float(entry.get("relevance") or 0.0) * 0.25
        + source_bonus
        + provider_bonus
    )
    return round(max(0.0, min(base_score * recency_multiplier, 1.0)), 4)


def _build_story_record(entry: dict[str, Any], *, now_ts: float, is_new: bool) -> dict[str, Any]:
    published_ts = _coerce_timestamp(entry.get("published_ts"))
    age_minutes = max((now_ts - published_ts) / 60.0, 0.0) if published_ts > 0 else None
    news_catalyst_score = _story_score(entry, age_minutes=age_minutes)
    recency_bucket = _recency_bucket(age_minutes)
    materiality = _materiality(news_catalyst_score)
    return {
        "story_key": entry["story_key"],
        "headline": entry.get("headline", ""),
        "tickers": list(entry.get("tickers") or []),
        "published_at": _isoformat_utc(published_ts),
        "published_ts": published_ts,
        "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
        "first_provider": entry.get("first_provider", "unknown"),
        "providers": list(entry.get("providers") or []),
        "provider_names": list(entry.get("provider_names") or []),
        "sources": list(entry.get("sources") or []),
        "source_tier": entry.get("source_tier", "TIER_4"),
        "source_rank": int(entry.get("source_rank") or 4),
        "category": entry.get("category", "other"),
        "event_class": _event_class(str(entry.get("category") or "other")),
        "event_label": _event_label(str(entry.get("headline") or "")),
        "sentiment_label": _sentiment_label(float(entry.get("polarity") or 0.0)),
        "polarity": round(float(entry.get("polarity") or 0.0), 4),
        "impact": round(float(entry.get("impact") or 0.0), 4),
        "clarity": round(float(entry.get("clarity") or 0.0), 4),
        "relevance": round(float(entry.get("relevance") or 0.0), 4),
        "news_catalyst_score": news_catalyst_score,
        "materiality": materiality,
        "recency_bucket": recency_bucket,
        "is_actionable": _is_actionable_story(
            recency_bucket=recency_bucket,
            materiality=materiality,
            age_minutes=age_minutes,
        ),
        "url": entry.get("url", ""),
        "first_seen_at": _isoformat_utc(_coerce_timestamp(entry.get("first_seen_ts"))),
        "is_new": bool(is_new),
        "provider_count": len(entry.get("providers") or []),
    }


def _build_news_catalyst_by_symbol(stories: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for story in stories:
        for symbol in story.get("tickers") or []:
            grouped.setdefault(symbol, []).append(story)

    result: dict[str, dict[str, Any]] = {}
    for symbol, symbol_stories in grouped.items():
        top_story = sorted(symbol_stories, key=lambda item: (-float(item["news_catalyst_score"]), -float(item["published_ts"])))[0]
        avg_polarity = sum(float(item.get("polarity") or 0.0) for item in symbol_stories) / max(len(symbol_stories), 1)
        mentions_24h = len(symbol_stories)
        score = min(1.0, float(top_story["news_catalyst_score"]) + min(0.12, 0.03 * max(mentions_24h - 1, 0)))
        result[symbol] = {
            "news_catalyst_score": round(score, 4),
            "sentiment_label": _sentiment_label(avg_polarity),
            "event_class": top_story["event_class"],
            "event_label": top_story["event_label"],
            "materiality": top_story["materiality"],
            "recency_bucket": top_story["recency_bucket"],
            "source_tier": top_story["source_tier"],
            "mentions_24h": mentions_24h,
            "is_actionable": any(bool(item.get("is_actionable")) for item in symbol_stories),
            "first_provider": top_story["first_provider"],
            "story_key": top_story["story_key"],
        }
    return dict(sorted(result.items()))


def _prune_story_state(
    story_state: dict[str, dict[str, Any]],
    *,
    now_ts: float,
    retention_seconds: int,
    max_entries: int,
) -> dict[str, dict[str, Any]]:
    retained_items = [
        (story_key, payload)
        for story_key, payload in story_state.items()
        if max(_coerce_timestamp(payload.get("published_ts")), _coerce_timestamp(payload.get("last_seen_ts"))) >= now_ts - retention_seconds
    ]
    retained_items.sort(key=lambda item: max(_coerce_timestamp(item[1].get("published_ts")), _coerce_timestamp(item[1].get("last_seen_ts"))), reverse=True)
    return {story_key: payload for story_key, payload in retained_items[:max_entries]}


def poll_live_news_bus(
    *,
    symbols: list[str],
    state: dict[str, Any] | None = None,
    fmp_api_key: str = "",
    benzinga_api_key: str = "",
    newsapi_ai_key: str = "",
    include_benzinga: bool = True,
    include_fmp: bool = True,
    include_newsapi_ai: bool = True,
    include_tradingview: bool = True,
    include_fmp_articles: bool = True,
    page_size: int = 100,
    tv_max_per_ticker: int = 3,
    tv_max_total: int = 25,
    tv_symbol_limit: int = DEFAULT_TV_SYMBOL_LIMIT,
    newsapi_lookback_days: int = 2,
    newsapi_articles_per_request: int = 100,
    story_window_seconds: int = DEFAULT_STORY_WINDOW_SECONDS,
    state_retention_seconds: int = DEFAULT_STATE_RETENTION_SECONDS,
    max_state_stories: int = DEFAULT_MAX_STATE_STORIES,
    now_ts: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now_ts = float(now_ts if now_ts is not None else time.time())
    normalized_symbols = _normalize_symbols(symbols)
    normalized_state = _normalize_state(state)
    provider_cursors = dict(normalized_state["provider_cursors"])
    provider_state = {
        provider: dict(payload)
        for provider, payload in normalized_state["provider_state"].items()
        if isinstance(payload, dict)
    }
    story_state = dict(normalized_state["story_state"])

    fetch_specs: list[tuple[str, Any, dict[str, Any]]] = []
    if include_benzinga:
        fetch_specs.append(
            (
                "benzinga",
                fetch_live_news_benzinga,
                {
                    "api_key": benzinga_api_key,
                    "symbols": normalized_symbols,
                    "cursor": provider_cursors["benzinga"],
                    "page_size": page_size,
                },
            )
        )
        fetch_specs.append(
            (
                "benzinga_quantified",
                fetch_live_news_benzinga_quantified,
                {
                    "api_key": benzinga_api_key,
                    "symbols": normalized_symbols,
                    "cursor": provider_cursors["benzinga_quantified"],
                    "page_size": page_size,
                },
            )
        )
    if include_fmp:
        fetch_specs.extend(
            [
                (
                    "fmp_stock",
                    fetch_live_news_fmp_stock,
                    {
                        "api_key": fmp_api_key,
                        "symbols": normalized_symbols,
                        "cursor": provider_cursors["fmp_stock"],
                        "page_size": page_size,
                    },
                ),
                (
                    "fmp_press",
                    fetch_live_news_fmp_press,
                    {
                        "api_key": fmp_api_key,
                        "symbols": normalized_symbols,
                        "cursor": provider_cursors["fmp_press"],
                        "page_size": page_size,
                    },
                ),
            ]
        )
    if include_fmp and include_fmp_articles:
        fetch_specs.append(
            (
                "fmp_articles",
                fetch_live_news_fmp_articles,
                {
                    "api_key": fmp_api_key,
                    "symbols": normalized_symbols,
                    "cursor": provider_cursors["fmp_articles"],
                    "limit": max(page_size, 1),
                },
            )
        )
    if include_newsapi_ai:
        fetch_specs.append(
            (
                "newsapi_ai",
                fetch_live_news_newsapi_ai,
                {
                    "api_key": newsapi_ai_key,
                    "symbols": normalized_symbols,
                    "cursor": provider_cursors["newsapi_ai"],
                    "article_feed_after_uri": str((provider_state.get("newsapi_ai") or {}).get("last_seen_news_uri") or ""),
                    "lookback_days": max(int(newsapi_lookback_days), 1),
                    "articles_per_request": max(int(newsapi_articles_per_request), 1),
                },
            )
        )
    if include_tradingview:
        fetch_specs.append(
            (
                "tv",
                fetch_live_news_tv,
                {
                    "symbols": normalized_symbols,
                    "cursor": provider_cursors["tv"],
                    "max_per_ticker": tv_max_per_ticker,
                    "max_total": tv_max_total,
                    "symbol_limit": tv_symbol_limit,
                },
            )
        )

    provider_results: dict[str, ProviderPollResult] = {}
    with ThreadPoolExecutor(max_workers=max(len(fetch_specs), 1)) as executor:
        futures = {
            executor.submit(fetcher, **kwargs): provider
            for provider, fetcher, kwargs in fetch_specs
        }
        for future in as_completed(futures):
            provider = futures[future]
            fallback_cursor = provider_cursors.get(provider, 0.0)
            try:
                provider_results[provider] = future.result()
            except Exception as exc:
                error_text = _sanitize_error_text(f"{type(exc).__name__}: {exc}")
                logger.warning("Live news provider failed: %s: %s", provider, error_text)
                provider_results[provider] = _disabled_provider(provider, cursor=fallback_cursor, error=error_text)

    for provider in PROVIDER_ORDER:
        provider_results.setdefault(provider, _disabled_provider(provider, cursor=provider_cursors.get(provider, 0.0), error="disabled"))

    grouped_candidates: dict[str, list[LiveNewsCandidate]] = {}
    for provider in PROVIDER_ORDER:
        result = provider_results[provider]
        provider_cursors[provider] = max(provider_cursors.get(provider, 0.0), _coerce_timestamp(result.cursor))
        for candidate in result.items:
            _, story_key = _story_key(candidate.headline, candidate.tickers, candidate.published_ts)
            grouped_candidates.setdefault(story_key, []).append(candidate)

    newsapi_meta = provider_results["newsapi_ai"].meta
    if "last_seen_news_uri" in newsapi_meta:
        next_newsapi_uri = str(newsapi_meta.get("last_seen_news_uri") or "").strip()
        if next_newsapi_uri:
            provider_state["newsapi_ai"] = {"last_seen_news_uri": next_newsapi_uri}
        else:
            provider_state.pop("newsapi_ai", None)

    new_story_keys: set[str] = set()
    for story_key, candidates in grouped_candidates.items():
        representative = _select_representative(candidates)
        cluster, _ = _story_key(representative.headline, representative.tickers, representative.published_ts)
        current_entry = story_state.get(story_key)
        if current_entry is None:
            cluster_count = sum(1 for existing_story_key in story_state if existing_story_key.startswith(f"{cluster}:")) + 1
            score = classify_and_score(
                {"headline": representative.headline, "tickers": list(representative.tickers)},
                cluster_count=cluster_count,
                chash=cluster,
            )
            current_entry = {
                "story_key": story_key,
                "cluster_hash": cluster,
                "headline": representative.headline,
                "tickers": list(representative.tickers),
                "published_ts": representative.published_ts,
                "first_seen_ts": now_ts,
                "first_provider": representative.provider_bucket,
                "providers": [],
                "provider_names": [],
                "sources": [],
                "url": representative.url,
                "category": score.category,
                "impact": score.impact,
                "clarity": score.clarity,
                "relevance": score.relevance,
                "polarity": score.polarity,
                "source_tier": "TIER_4",
                "source_rank": 4,
                "last_seen_ts": now_ts,
            }
            new_story_keys.add(story_key)

        providers = set(str(item).strip() for item in current_entry.get("providers") or [])
        provider_names = set(str(item).strip() for item in current_entry.get("provider_names") or [])
        sources = set(str(item).strip() for item in current_entry.get("sources") or [])
        for candidate in candidates:
            providers.add(candidate.provider_bucket)
            provider_names.add(candidate.provider_name)
            if candidate.source:
                sources.add(candidate.source)
            if not current_entry.get("url") and candidate.url:
                current_entry["url"] = candidate.url
        best_source_tier = current_entry.get("source_tier", "TIER_4")
        best_source_rank = _source_rank(str(best_source_tier))
        for candidate in candidates:
            candidate_tier = _source_tier(candidate.source, candidate.provider_bucket)
            candidate_rank = _source_rank(candidate_tier)
            if candidate_rank < best_source_rank:
                best_source_tier = candidate_tier
                best_source_rank = candidate_rank
        current_entry["providers"] = [provider for provider in PROVIDER_ORDER if provider in providers]
        current_entry["provider_names"] = sorted(provider_names)
        current_entry["sources"] = sorted(sources)
        current_entry["source_tier"] = best_source_tier
        current_entry["source_rank"] = best_source_rank
        current_entry["last_seen_ts"] = now_ts
        story_state[story_key] = current_entry

    provider_cursors["legacy_cursor"] = max(provider_cursors[provider] for provider in PROVIDER_ORDER)
    story_state = _prune_story_state(
        story_state,
        now_ts=now_ts,
        retention_seconds=state_retention_seconds,
        max_entries=max_state_stories,
    )

    active_story_payloads = [
        payload
        for payload in story_state.values()
        if _coerce_timestamp(payload.get("published_ts")) >= now_ts - story_window_seconds
    ]
    active_stories = [
        _build_story_record(payload, now_ts=now_ts, is_new=payload["story_key"] in new_story_keys)
        for payload in active_story_payloads
    ]
    active_stories.sort(key=lambda item: (-float(item["news_catalyst_score"]), -float(item["published_ts"])))
    news_catalyst_by_symbol = _build_news_catalyst_by_symbol(active_stories)

    snapshot = {
        "generated_at": _isoformat_utc(now_ts),
        "symbols": normalized_symbols,
        "provider_cursors": provider_cursors,
        "legacy_cursor": provider_cursors["legacy_cursor"],
        "providers": {
            provider: {
                "ok": bool(provider_results[provider].ok),
                "error": provider_results[provider].error,
                "raw_count": int(provider_results[provider].raw_count),
                "new_item_count": len(provider_results[provider].items),
                "cursor": provider_cursors[provider],
                **(
                    {
                        "last_seen_news_uri": str((provider_state.get(provider) or {}).get("last_seen_news_uri") or "")
                        ,"provider_status": str(provider_results[provider].meta.get("provider_status") or ("ok" if provider_results[provider].ok else ""))
                            ,"status_detail": str(provider_results[provider].meta.get("status_detail") or "")
                        ,"error_code": str(provider_results[provider].meta.get("error_code") or "")
                    }
                    if provider == "newsapi_ai"
                    else {}
                ),
            }
            for provider in PROVIDER_ORDER
        },
        "stories": active_stories,
        "news_catalyst_by_symbol": news_catalyst_by_symbol,
        "summary": {
            "active_story_count": len(active_stories),
            "new_story_count": sum(1 for story in active_stories if story["is_new"]),
            "actionable_story_count": sum(1 for story in active_stories if story["is_actionable"]),
            "actionable_symbols": sorted(symbol for symbol, payload in news_catalyst_by_symbol.items() if payload.get("is_actionable")),
            "symbol_count": len(news_catalyst_by_symbol),
        },
    }
    next_state = {
        "provider_cursors": provider_cursors,
        "provider_state": provider_state,
        "story_state": story_state,
    }
    return snapshot, next_state


def _resolve_manifest_path(export_dir: Path) -> Path:
    from scripts.smc_artifact_resolver import latest_by_filename_iso
    manifest = latest_by_filename_iso(
        export_dir.glob("*__smc_microstructure_base_manifest.json")
    )
    if manifest is None:
        raise FileNotFoundError(f"No SMC base manifest found in {export_dir}")
    return manifest


def _resolve_path_from_manifest(raw_path: str, manifest_path: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute() or path.exists():
        return path
    candidate = manifest_path.parent / path
    return candidate if candidate.exists() else path


def load_symbols_from_base_csv(base_csv_path: Path, *, symbol_limit: int = DEFAULT_SYMBOL_LIMIT) -> list[str]:
    rows: list[tuple[str, float]] = []
    seen: set[str] = set()
    with base_csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = str((row or {}).get("symbol") or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            try:
                adv_dollar = float((row or {}).get("adv_dollar_rth_20d") or 0.0)
            except (TypeError, ValueError):
                adv_dollar = 0.0
            rows.append((symbol, adv_dollar))
    rows.sort(key=lambda item: item[1], reverse=True)
    ordered = [symbol for symbol, _ in rows]
    if symbol_limit > 0:
        return ordered[:symbol_limit]
    return ordered


def resolve_live_news_symbols(
    *,
    symbols: list[str] | None = None,
    base_csv_path: Path | None = None,
    base_manifest_path: Path | None = None,
    export_dir: Path | None = None,
    symbol_limit: int = DEFAULT_SYMBOL_LIMIT,
) -> tuple[list[str], dict[str, Any]]:
    explicit_symbols = _normalize_symbols(symbols or [])
    if explicit_symbols:
        return explicit_symbols, {"mode": "explicit", "symbol_limit": len(explicit_symbols)}

    manifest_path = base_manifest_path
    if manifest_path is None and export_dir is not None:
        try:
            manifest_path = _resolve_manifest_path(export_dir)
        except FileNotFoundError:
            manifest_path = None

    resolved_base_csv = base_csv_path
    if resolved_base_csv is None and manifest_path is not None:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw_base_csv_path = str((payload or {}).get("base_csv_path") or "").strip()
        if not raw_base_csv_path:
            raise ValueError(f"Manifest does not contain base_csv_path: {manifest_path}")
        resolved_base_csv = _resolve_path_from_manifest(raw_base_csv_path, manifest_path)

    if resolved_base_csv is None:
        fallback_symbols = list(RELEASE_REFERENCE_SYMBOLS)
        if symbol_limit > 0:
            fallback_symbols = fallback_symbols[:symbol_limit]
        return fallback_symbols, {
            "mode": "release_policy_fallback",
            "symbol_limit": len(fallback_symbols),
            "base_csv_path": None,
            "base_manifest_path": str(manifest_path) if manifest_path is not None else None,
            "export_dir": str(export_dir) if export_dir is not None else None,
        }

    scope_symbols = load_symbols_from_base_csv(resolved_base_csv, symbol_limit=symbol_limit)
    return scope_symbols, {
        "mode": "base_csv",
        "symbol_limit": symbol_limit,
        "base_csv_path": str(resolved_base_csv),
        "base_manifest_path": str(manifest_path) if manifest_path is not None else None,
    }


def export_live_news_snapshot(
    *,
    symbols: list[str],
    output_path: Path,
    state_path: Path,
    fmp_api_key: str = "",
    benzinga_api_key: str = "",
    newsapi_ai_key: str = "",
    include_benzinga: bool = True,
    include_fmp: bool = True,
    include_newsapi_ai: bool = True,
    include_tradingview: bool = True,
    include_fmp_articles: bool = True,
    page_size: int = 100,
    tv_max_per_ticker: int = 3,
    tv_max_total: int = 25,
    tv_symbol_limit: int = DEFAULT_TV_SYMBOL_LIMIT,
    newsapi_lookback_days: int = 2,
    newsapi_articles_per_request: int = 100,
    story_window_seconds: int = DEFAULT_STORY_WINDOW_SECONDS,
    now_ts: float | None = None,
    scope_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = load_live_news_state(state_path)
    snapshot, next_state = poll_live_news_bus(
        symbols=symbols,
        state=state,
        fmp_api_key=fmp_api_key,
        benzinga_api_key=benzinga_api_key,
        newsapi_ai_key=newsapi_ai_key,
        include_benzinga=include_benzinga,
        include_fmp=include_fmp,
        include_newsapi_ai=include_newsapi_ai,
        include_tradingview=include_tradingview,
        include_fmp_articles=include_fmp_articles,
        page_size=page_size,
        tv_max_per_ticker=tv_max_per_ticker,
        tv_max_total=tv_max_total,
        tv_symbol_limit=tv_symbol_limit,
        newsapi_lookback_days=newsapi_lookback_days,
        newsapi_articles_per_request=newsapi_articles_per_request,
        story_window_seconds=story_window_seconds,
        now_ts=now_ts,
    )
    if scope_metadata:
        snapshot["symbol_scope"] = scope_metadata
    save_live_news_state(state_path, next_state)
    write_live_news_snapshot(output_path, snapshot)
    return snapshot
