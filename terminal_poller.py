"""Polling engine for the Real-Time News Intelligence Dashboard.

Wraps news REST adapter + optional FMP adapter + open_prep
classifiers into a single ``poll_and_classify()`` call that fetches new
items, deduplicates them, scores them, and returns fully classified
records ready for display.

Supports multi-source ingestion: REST news API (primary) + FMP (secondary).

This module is imported by ``streamlit_terminal.py`` — it is **not**
a standalone script.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo as _ZoneInfo

_ET = _ZoneInfo("America/New_York")

from newsstack_fmp.common_types import NewsItem
from newsstack_fmp._bz_http import _sanitize_exc, log_fetch_warning
from open_prep.macro import FMPClient
from newsstack_fmp.ingest_benzinga import (
    BenzingaRestAdapter,
    fetch_benzinga_channels,
    fetch_benzinga_quantified_news,
    fetch_benzinga_top_news,
)

try:
    from newsstack_fmp.ingest_benzinga_calendar import (
        BenzingaCalendarAdapter,
        fetch_benzinga_movers,
        fetch_benzinga_quotes,
    )
except ImportError:
    BenzingaCalendarAdapter = None  # type: ignore[assignment,misc]
    fetch_benzinga_movers = None  # type: ignore[assignment]
    fetch_benzinga_quotes = None  # type: ignore[assignment]

try:
    from newsstack_fmp.ingest_benzinga_financial import (
        BenzingaFinancialAdapter,
        fetch_benzinga_auto_complete,
        fetch_benzinga_company_profile,
        fetch_benzinga_financials,
        fetch_benzinga_fundamentals,
        fetch_benzinga_insider_transactions,
        fetch_benzinga_logos,
        fetch_benzinga_options_activity,
        fetch_benzinga_price_history,
        fetch_benzinga_ticker_detail,
    )
except ImportError:
    BenzingaFinancialAdapter = None  # type: ignore[assignment,misc]
    fetch_benzinga_auto_complete = None  # type: ignore[assignment]
    fetch_benzinga_company_profile = None  # type: ignore[assignment]
    fetch_benzinga_financials = None  # type: ignore[assignment]
    fetch_benzinga_fundamentals = None  # type: ignore[assignment]
    fetch_benzinga_insider_transactions = None  # type: ignore[assignment]
    fetch_benzinga_logos = None  # type: ignore[assignment]
    fetch_benzinga_options_activity = None  # type: ignore[assignment]
    fetch_benzinga_price_history = None  # type: ignore[assignment]
    fetch_benzinga_ticker_detail = None  # type: ignore[assignment]

from newsstack_fmp.scoring import classify_and_score, cluster_hash
from newsstack_fmp.store_sqlite import SqliteStore

# open_prep standalone classifiers — no refactoring needed
from open_prep.news import classify_article_sentiment
from open_prep.playbook import (
    classify_news_event,
    classify_recency,
    classify_source_quality,
)

logger = logging.getLogger(__name__)


_CURSOR_KEY_BENZINGA = "benzinga"
_CURSOR_KEY_FMP_STOCK = "fmp_stock"
_CURSOR_KEY_FMP_PRESS = "fmp_press"
_CURSOR_KEY_TV = "tv"
_LIVE_CURSOR_KEYS: tuple[str, ...] = (
    _CURSOR_KEY_BENZINGA,
    _CURSOR_KEY_FMP_STOCK,
    _CURSOR_KEY_FMP_PRESS,
    _CURSOR_KEY_TV,
)
_CANONICAL_STORY_BUCKET_SECONDS = 900
_HEADLINE_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _make_fmp_client(api_key: str) -> FMPClient:
    return FMPClient(api_key=api_key, retry_attempts=1, timeout_seconds=12.0)


def seed_provider_cursors(seed_cursor: str | None) -> dict[str, str]:
    """Seed all live-provider cursors from one legacy cursor value."""
    seeded = str(seed_cursor or "").strip()
    if not seeded:
        return {}
    return {key: seeded for key in _LIVE_CURSOR_KEYS}


def legacy_cursor_from_provider_cursors(provider_cursors: dict[str, str] | None) -> str | None:
    """Collapse provider-specific cursors into one legacy max-timestamp cursor."""
    if not provider_cursors:
        return None
    max_ts = 0.0
    for value in provider_cursors.values():
        try:
            max_ts = max(max_ts, float(value or 0.0))
        except (TypeError, ValueError):
            continue
    if max_ts <= 0:
        return None
    return str(int(max_ts))


def live_news_source_label(provider_counts: dict[str, int] | None) -> str:
    """Return a compact provider label for operator-facing status text."""
    counts = provider_counts or {}
    labels: list[str] = []
    if _CURSOR_KEY_BENZINGA in counts:
        labels.append("BZ")
    if _CURSOR_KEY_FMP_STOCK in counts or _CURSOR_KEY_FMP_PRESS in counts:
        labels.append("FMP")
    if _CURSOR_KEY_TV in counts:
        labels.append("TV")
    return "+".join(labels) if labels else "NONE"


def _item_timestamp(item: NewsItem) -> float:
    ts = item.updated_ts or item.published_ts or 0.0
    try:
        return float(ts)
    except (TypeError, ValueError):
        return 0.0


def _cursor_timestamp(cursor: str | None) -> float:
    try:
        return float(cursor or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _advance_provider_cursor(current_cursor: str | None, items: list[NewsItem]) -> str:
    max_ts = _cursor_timestamp(current_cursor)
    for item in items:
        max_ts = max(max_ts, _item_timestamp(item))
    if max_ts <= 0:
        return str(current_cursor or "")
    return str(int(max_ts))


def _filter_items_by_cursor(items: list[NewsItem], current_cursor: str | None) -> list[NewsItem]:
    current_ts = _cursor_timestamp(current_cursor)
    if current_ts <= 0:
        return list(items)
    return [item for item in items if _item_timestamp(item) >= current_ts]


def _normalize_story_headline(headline: str) -> str:
    collapsed = _HEADLINE_NORMALIZE_RE.sub(" ", str(headline or "").lower())
    return " ".join(collapsed.split())


def _story_tickers(item: NewsItem) -> tuple[str, ...]:
    return tuple(sorted({str(t).strip().upper() for t in (item.tickers or []) if str(t).strip()}))


def _canonical_story_key(item: NewsItem) -> str:
    headline = _normalize_story_headline(item.headline)
    tickers = ",".join(_story_tickers(item))
    ts = _item_timestamp(item)
    bucket = int(ts // _CANONICAL_STORY_BUCKET_SECONDS) if ts > 0 else 0
    base = headline or str(item.url or "").strip().lower() or str(item.item_id or "").strip().lower()
    return hashlib.md5(
        f"{base}|{tickers}|{bucket}".encode("utf-8", errors="replace"),
        usedforsecurity=False,
    ).hexdigest()


def _raw_item_priority(item: NewsItem, fetch_order: int) -> tuple[int, int, int, int, int, int]:
    source_info = classify_source_quality(item.source or "", item.headline)
    source_rank = int(source_info.get("source_rank", 99) or 99)
    return (
        int(fetch_order),
        source_rank,
        0 if item.url else 1,
        0 if item.snippet else 1,
        -len(_story_tickers(item)),
        -len(str(item.headline or "")),
    )


def _dedup_raw_items_cross_provider(items: list[tuple[int, NewsItem]]) -> list[NewsItem]:
    best_by_story: dict[str, tuple[tuple[int, int, int, int, int, int], NewsItem]] = {}
    for fetch_order, item in items:
        story_key = _canonical_story_key(item)
        priority = _raw_item_priority(item, fetch_order)
        existing = best_by_story.get(story_key)
        if existing is None or priority < existing[0]:
            best_by_story[story_key] = (priority, item)
    deduped = [entry[1] for entry in best_by_story.values()]
    deduped.sort(key=_item_timestamp, reverse=True)
    return deduped


def _tv_headline_to_news_item(headline: Any) -> NewsItem:
    item_id = str(getattr(headline, "id", "") or getattr(headline, "story_url", "") or "").strip()
    published = float(getattr(headline, "published", 0.0) or 0.0)
    title = str(getattr(headline, "title", "") or "").strip()
    if not item_id:
        item_id = (
            f"tv_{int(published)}_"
            f"{hashlib.md5(title.encode('utf-8', errors='replace'), usedforsecurity=False).hexdigest()[:10]}"
        )
    provider = str(getattr(headline, "provider", "tradingview") or "tradingview").strip().lower()
    source = str(getattr(headline, "source", "TradingView") or "TradingView").strip()
    tickers = [
        str(t).strip().upper()
        for t in (getattr(headline, "tickers", []) or [])
        if str(t).strip()
    ]
    story_url = str(getattr(headline, "story_url", "") or "").strip() or None
    return NewsItem(
        provider=f"tv_{provider}",
        item_id=item_id,
        published_ts=published,
        updated_ts=published,
        headline=title,
        snippet="",
        tickers=tickers,
        url=story_url,
        source=source,
        raw={
            "tv_provider": provider,
            "permission": str(getattr(headline, "permission", "") or ""),
            "tags": [{"name": "TradingView"}],
            "channels": [],
        },
    )


def _fetch_tv_news_items(tickers: list[str], *, max_total: int) -> list[NewsItem]:
    if not tickers:
        return []
    from terminal_tradingview_news import fetch_tv_multi

    headlines = fetch_tv_multi(
        tickers,
        max_per_ticker=max(5, min(15, max_total)),
        max_total=max_total,
    )
    return [_tv_headline_to_news_item(item) for item in headlines]


# ── Safe env-var parsers ────────────────────────────────────────

def _env_float(key: str, default: float) -> float:
    """Read an env var as float, returning *default* on parse failure."""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_int(key: str, default: int) -> int:
    """Read an env var as int, returning *default* on parse failure."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


# ── Configuration ───────────────────────────────────────────────

@dataclass(frozen=True)
class TerminalConfig:
    """Terminal-specific configuration (reads env vars at instantiation)."""

    benzinga_api_key: str = field(
        default_factory=lambda: os.getenv("BENZINGA_API_KEY", ""),
        repr=False,
    )
    fmp_api_key: str = field(
        default_factory=lambda: os.getenv("FMP_API_KEY", ""),
        repr=False,
    )
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", ""),
        repr=False,
    )
    poll_interval_s: float = field(
        default_factory=lambda: _env_float("TERMINAL_POLL_INTERVAL_S", 10.0),
    )
    sqlite_path: str = field(
        default_factory=lambda: os.getenv("TERMINAL_SQLITE_PATH", "newsstack_fmp/terminal_state.db"),
    )
    jsonl_path: str = field(
        default_factory=lambda: os.getenv("TERMINAL_JSONL_PATH", "artifacts/terminal_feed.jsonl"),
    )
    webhook_url: str = field(
        default_factory=lambda: os.getenv("TERMINAL_WEBHOOK_URL", ""),
    )
    webhook_secret: str = field(
        default_factory=lambda: os.getenv("TERMINAL_WEBHOOK_SECRET", ""),
        repr=False,
    )
    max_items: int = field(
        default_factory=lambda: _env_int("TERMINAL_MAX_ITEMS", 500),
    )
    channels: str = field(
        default_factory=lambda: os.getenv("TERMINAL_CHANNELS", ""),
    )
    topics: str = field(
        default_factory=lambda: os.getenv("TERMINAL_TOPICS", ""),
    )
    page_size: int = field(
        default_factory=lambda: _env_int("TERMINAL_PAGE_SIZE", 100),
    )
    display_output: str = field(
        default_factory=lambda: os.getenv("TERMINAL_DISPLAY_OUTPUT", "abstract"),
    )
    fmp_enabled: bool = field(
        default_factory=lambda: os.getenv("TERMINAL_FMP_ENABLED", "1") == "1",
    )
    tv_news_enabled: bool = field(
        default_factory=lambda: os.getenv("TERMINAL_TV_NEWS_ENABLED", "1") == "1",
    )
    tv_news_symbols: str = field(
        default_factory=lambda: os.getenv("TERMINAL_TV_NEWS_SYMBOLS", ""),
    )
    tv_news_max_symbols: int = field(
        default_factory=lambda: _env_int("TERMINAL_TV_NEWS_MAX_SYMBOLS", 25),
    )
    live_story_ttl_s: float = field(
        default_factory=lambda: _env_float("TERMINAL_LIVE_STORY_TTL_S", 7200.0),
    )
    live_story_cooldown_s: float = field(
        default_factory=lambda: _env_float("TERMINAL_LIVE_STORY_COOLDOWN_S", 900.0),
    )
    feed_max_age_s: float = field(
        default_factory=lambda: _env_float("TERMINAL_FEED_MAX_AGE_S", 14400.0),  # 4 hours
    )


# ── Classified item schema ──────────────────────────────────────

@dataclass
class ClassifiedItem:
    """Fully enriched news item ready for display / export."""

    # Identity
    item_id: str
    ticker: str  # primary ticker (may repeat item for multi-ticker articles)
    tickers_all: list[str]
    headline: str
    snippet: str
    url: str | None
    source: str
    published_ts: float
    updated_ts: float
    provider: str

    # newsstack_fmp scoring
    category: str
    impact: float
    clarity: float
    polarity: float
    news_score: float
    cluster_hash: str
    novelty_count: int
    relevance: float  # 0.0–1.0 composite relevance
    entity_count: int  # number of tickers mentioned

    # open_prep: sentiment
    sentiment_label: str  # bullish / neutral / bearish
    sentiment_score: float  # -1.0 … +1.0

    # open_prep: event classification
    event_class: str  # SCHEDULED / UNSCHEDULED / STRUCTURAL / UNKNOWN
    event_label: str  # earnings / fda / ma_deal / …
    materiality: str  # HIGH / MEDIUM / LOW

    # open_prep: recency
    recency_bucket: str  # ULTRA_FRESH / FRESH / WARM / AGING / STALE
    age_minutes: float | None
    is_actionable: bool

    # open_prep: source quality
    source_tier: str  # TIER_1 … TIER_4
    source_rank: int  # 1-4

    # News provider metadata
    channels: list[str]
    tags: list[str]
    is_wiim: bool  # "Why Is It Moving" — high-signal channel
    story_key: str = ""
    story_update_kind: str = "new"
    story_first_seen_ts: float | None = None
    story_last_seen_ts: float | None = None
    story_providers_seen: list[str] = field(default_factory=list)
    story_best_source: str = ""
    story_best_provider: str = ""
    story_cooldown_until: float | None = None
    story_expires_at: float | None = None
    catalyst_score: float | None = None
    catalyst_direction: str = ""
    catalyst_confidence: float | None = None
    catalyst_freshness: str = ""
    catalyst_story_count: int | None = None
    catalyst_provider_count: int | None = None
    catalyst_best_story_key: str = ""
    catalyst_best_provider: str = ""
    catalyst_best_source: str = ""
    catalyst_headline: str = ""
    catalyst_actionable: bool | None = None
    catalyst_age_minutes: float | None = None
    catalyst_last_update_ts: float | None = None
    catalyst_expires_at: float | None = None
    catalyst_conflict: bool | None = None
    reaction_state: str = ""
    reaction_alignment: str = ""
    reaction_score: float | None = None
    reaction_confidence: float | None = None
    reaction_price: float | None = None
    reaction_change_pct: float | None = None
    reaction_impulse_pct: float | None = None
    reaction_volume_ratio: float | None = None
    reaction_source: str = ""
    reaction_anchor_story_key: str = ""
    reaction_anchor_price: float | None = None
    reaction_anchor_ts: float | None = None
    reaction_peak_impulse_pct: float | None = None
    reaction_last_update_ts: float | None = None
    reaction_confirmed: bool | None = None
    reaction_actionable: bool | None = None
    reaction_reason: str = ""
    resolution_state: str = ""
    resolution_score: float | None = None
    resolution_confidence: float | None = None
    resolution_window_minutes: float | None = None
    resolution_elapsed_minutes: float | None = None
    resolution_price: float | None = None
    resolution_change_pct: float | None = None
    resolution_impulse_pct: float | None = None
    resolution_peak_impulse_pct: float | None = None
    resolution_source: str = ""
    resolution_anchor_story_key: str = ""
    resolution_anchor_price: float | None = None
    resolution_anchor_ts: float | None = None
    resolution_last_update_ts: float | None = None
    resolution_resolved: bool | None = None
    resolution_actionable: bool | None = None
    resolution_reason: str = ""
    posture_state: str = ""
    posture_action: str = ""
    posture_score: float | None = None
    posture_confidence: float | None = None
    posture_actionable: bool | None = None
    posture_reason: str = ""
    posture_last_update_ts: float | None = None
    attention_state: str = ""
    attention_score: float | None = None
    attention_confidence: float | None = None
    attention_active: bool | None = None
    attention_featured: bool | None = None
    attention_dispatchable: bool | None = None
    attention_reason: str = ""
    attention_last_update_ts: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain dict (for JSON export / Streamlit display)."""
        return {
            "item_id": self.item_id,
            "ticker": self.ticker,
            "tickers_all": self.tickers_all,
            "headline": self.headline,
            "snippet": self.snippet,
            "url": self.url,
            "source": self.source,
            "published_ts": self.published_ts,
            "updated_ts": self.updated_ts,
            "provider": self.provider,
            "category": self.category,
            "impact": round(self.impact, 3),
            "clarity": round(self.clarity, 3),
            "polarity": self.polarity,
            "news_score": round(self.news_score, 4),
            "cluster_hash": self.cluster_hash,
            "novelty_count": self.novelty_count,
            "relevance": round(self.relevance, 4),
            "entity_count": self.entity_count,
            "sentiment_label": self.sentiment_label,
            "sentiment_score": self.sentiment_score,
            "event_class": self.event_class,
            "event_label": self.event_label,
            "materiality": self.materiality,
            "recency_bucket": self.recency_bucket,
            "age_minutes": self.age_minutes,
            "is_actionable": self.is_actionable,
            "source_tier": self.source_tier,
            "source_rank": self.source_rank,
            "channels": self.channels,
            "tags": self.tags,
            "is_wiim": self.is_wiim,
            "story_key": self.story_key,
            "story_update_kind": self.story_update_kind,
            "story_first_seen_ts": self.story_first_seen_ts,
            "story_last_seen_ts": self.story_last_seen_ts,
            "story_providers_seen": self.story_providers_seen,
            "story_best_source": self.story_best_source,
            "story_best_provider": self.story_best_provider,
            "story_cooldown_until": self.story_cooldown_until,
            "story_expires_at": self.story_expires_at,
            "catalyst_score": self.catalyst_score,
            "catalyst_direction": self.catalyst_direction,
            "catalyst_confidence": self.catalyst_confidence,
            "catalyst_freshness": self.catalyst_freshness,
            "catalyst_story_count": self.catalyst_story_count,
            "catalyst_provider_count": self.catalyst_provider_count,
            "catalyst_best_story_key": self.catalyst_best_story_key,
            "catalyst_best_provider": self.catalyst_best_provider,
            "catalyst_best_source": self.catalyst_best_source,
            "catalyst_headline": self.catalyst_headline,
            "catalyst_actionable": self.catalyst_actionable,
            "catalyst_age_minutes": self.catalyst_age_minutes,
            "catalyst_last_update_ts": self.catalyst_last_update_ts,
            "catalyst_expires_at": self.catalyst_expires_at,
            "catalyst_conflict": self.catalyst_conflict,
            "reaction_state": self.reaction_state,
            "reaction_alignment": self.reaction_alignment,
            "reaction_score": self.reaction_score,
            "reaction_confidence": self.reaction_confidence,
            "reaction_price": self.reaction_price,
            "reaction_change_pct": self.reaction_change_pct,
            "reaction_impulse_pct": self.reaction_impulse_pct,
            "reaction_volume_ratio": self.reaction_volume_ratio,
            "reaction_source": self.reaction_source,
            "reaction_anchor_story_key": self.reaction_anchor_story_key,
            "reaction_anchor_price": self.reaction_anchor_price,
            "reaction_anchor_ts": self.reaction_anchor_ts,
            "reaction_peak_impulse_pct": self.reaction_peak_impulse_pct,
            "reaction_last_update_ts": self.reaction_last_update_ts,
            "reaction_confirmed": self.reaction_confirmed,
            "reaction_actionable": self.reaction_actionable,
            "reaction_reason": self.reaction_reason,
            "resolution_state": self.resolution_state,
            "resolution_score": self.resolution_score,
            "resolution_confidence": self.resolution_confidence,
            "resolution_window_minutes": self.resolution_window_minutes,
            "resolution_elapsed_minutes": self.resolution_elapsed_minutes,
            "resolution_price": self.resolution_price,
            "resolution_change_pct": self.resolution_change_pct,
            "resolution_impulse_pct": self.resolution_impulse_pct,
            "resolution_peak_impulse_pct": self.resolution_peak_impulse_pct,
            "resolution_source": self.resolution_source,
            "resolution_anchor_story_key": self.resolution_anchor_story_key,
            "resolution_anchor_price": self.resolution_anchor_price,
            "resolution_anchor_ts": self.resolution_anchor_ts,
            "resolution_last_update_ts": self.resolution_last_update_ts,
            "resolution_resolved": self.resolution_resolved,
            "resolution_actionable": self.resolution_actionable,
            "resolution_reason": self.resolution_reason,
            "posture_state": self.posture_state,
            "posture_action": self.posture_action,
            "posture_score": self.posture_score,
            "posture_confidence": self.posture_confidence,
            "posture_actionable": self.posture_actionable,
            "posture_reason": self.posture_reason,
            "posture_last_update_ts": self.posture_last_update_ts,
            "attention_state": self.attention_state,
            "attention_score": self.attention_score,
            "attention_confidence": self.attention_confidence,
            "attention_active": self.attention_active,
            "attention_featured": self.attention_featured,
            "attention_dispatchable": self.attention_dispatchable,
            "attention_reason": self.attention_reason,
            "attention_last_update_ts": self.attention_last_update_ts,
        }


# ── Core polling + classification ───────────────────────────────

def _classify_item(
    item: NewsItem,
    store: SqliteStore,
    now_utc: datetime,
) -> list[ClassifiedItem]:
    """Classify one NewsItem and return one ClassifiedItem per ticker.

    Returns empty list if the item is invalid, already seen, or has no tickers.
    """
    if not item.is_valid:
        return []

    # Determine effective timestamp
    raw_ts = item.updated_ts or item.published_ts
    ts = raw_ts if raw_ts and raw_ts > 0 else time.time()

    # Provider-local dedup remains in place for exact repeats.
    if not store.mark_seen(item.provider, item.item_id, ts):
        return []

    tickers = [t.strip().upper() for t in (item.tickers or []) if isinstance(t, str) and t.strip()]
    tickers = list(dict.fromkeys(tickers))  # dedupe preserving order
    if not tickers:
        # Still classify ticker-less items under "MARKET"
        tickers = ["MARKET"]

    if not (item.headline or "").strip():
        return []

    # ── newsstack_fmp scoring ───────────────────────────────
    chash = cluster_hash(item.headline or "", item.tickers or [])
    c_count, _ = store.cluster_touch(chash, ts)
    score_result = classify_and_score(item, cluster_count=c_count, chash=chash)

    # ── open_prep classifiers ───────────────────────────────
    sentiment_label, sentiment_score = classify_article_sentiment(
        item.headline, item.snippet or "",
    )

    event_info = classify_news_event(item.headline, item.snippet or "")

    # Recency needs a datetime — convert published_ts epoch
    article_dt: datetime | None = None
    if item.published_ts and item.published_ts > 0:
        article_dt = datetime.fromtimestamp(item.published_ts, tz=UTC)
    recency_info = classify_recency(article_dt, now_utc)

    source_info = classify_source_quality(item.source or "", item.headline)

    # ── Benzinga-specific metadata ──────────────────────────
    raw = item.raw or {}
    channels = [c.get("name", "") for c in raw.get("channels", []) if isinstance(c, dict)]
    tags = [t.get("name", "") for t in raw.get("tags", []) if isinstance(t, dict)]

    # ── WIIM boost ──────────────────────────────────────────
    # "Why Is It Moving" is Benzinga's curated high-signal channel.
    # Articles tagged WIIM receive a 15% score boost (capped at 1.0).
    is_wiim = any(ch.upper() == "WIIM" for ch in channels)

    # ── Build one ClassifiedItem per ticker ──────────────────
    results: list[ClassifiedItem] = []
    for tk in tickers:
        ci = ClassifiedItem(
            item_id=item.item_id,
            ticker=tk,
            tickers_all=tickers,
            headline=item.headline[:260],
            snippet=(item.snippet or "")[:260],
            url=item.url,
            source=item.source or "",
            published_ts=item.published_ts,
            updated_ts=item.updated_ts,
            provider=item.provider or "benzinga_rest",
            # scoring
            category=score_result.category,
            impact=score_result.impact,
            clarity=score_result.clarity,
            polarity=score_result.polarity,
            news_score=score_result.score,
            cluster_hash=score_result.cluster_hash,
            novelty_count=c_count,
            relevance=score_result.relevance,
            entity_count=score_result.entity_count,
            # sentiment
            sentiment_label=sentiment_label,
            sentiment_score=sentiment_score,
            # event
            event_class=event_info.get("event_class", "unknown"),
            event_label=event_info.get("event_label", ""),
            materiality=event_info.get("materiality", "LOW"),
            # recency
            recency_bucket=recency_info.get("recency_bucket", "stale"),
            age_minutes=recency_info.get("age_minutes", 0),
            is_actionable=recency_info.get("is_actionable", False),
            # source
            source_tier=source_info.get("source_tier", "unknown"),
            source_rank=source_info.get("source_rank", 99),
            # news provider metadata
            channels=channels,
            tags=tags,
            is_wiim=is_wiim,
        )
        # Apply WIIM boost after construction
        if is_wiim:
            ci.news_score = min(1.0, ci.news_score * 1.15)
            ci.relevance = min(1.0, ci.relevance * 1.10)
        results.append(ci)
    return results


def poll_and_classify(
    adapter: BenzingaRestAdapter,
    store: SqliteStore,
    cursor: str | None = None,
    page_size: int = 100,
    channels: str | None = None,
    topics: str | None = None,
) -> tuple[list[ClassifiedItem], str]:
    """Run one poll cycle: fetch → dedup → classify → return.

    Parameters
    ----------
    adapter : BenzingaRestAdapter
        Pre-configured REST adapter with API key.
    store : SqliteStore
        State store for dedup + novelty.
    cursor : str, optional
        ``updatedSince`` value from previous poll (Unix epoch string).
        Pass ``None`` for initial load.
    page_size : int
        Number of items per API call (max 100).
    channels : str, optional
        Comma-separated Benzinga channel names to filter by.
    topics : str, optional
        Comma-separated Benzinga topic names to filter by.

    Returns
    -------
    (items, new_cursor)
        items: List of fully classified items (may be empty if no new news).
        new_cursor: Updated cursor string for next poll.
    """
    now_utc = datetime.now(UTC)
    raw_items = adapter.fetch_news(updated_since=cursor, page_size=page_size,
                                    channels=channels, topics=topics)

    all_classified: list[ClassifiedItem] = []
    try:
        max_ts = float(cursor) if cursor else 0.0
    except (ValueError, TypeError):
        max_ts = 0.0

    for item in raw_items:
        try:
            classified = _classify_item(item, store, now_utc)
            all_classified.extend(classified)
        except Exception as exc:
            logger.warning("Skipping item %s: %s", getattr(item, 'item_id', '?')[:40], type(exc).__name__, exc_info=True)

        # Track cursor: use the max updated_ts from valid items
        ts = item.updated_ts or item.published_ts
        if ts and ts > 0:
            max_ts = max(max_ts, ts)

    # Advance cursor only if we got items with real timestamps
    new_cursor = str(int(max_ts)) if max_ts > 0 else (cursor or "")

    logger.info(
        "Terminal poll: %d raw items → %d classified | cursor %s → %s",
        len(raw_items), len(all_classified), cursor or "(initial)", new_cursor,
    )

    return all_classified, new_cursor


# ── Multi-source polling (Benzinga + FMP) ───────────────────────

def poll_and_classify_multi(
    benzinga_adapter: BenzingaRestAdapter | None,
    fmp_adapter: Any | None,
    store: SqliteStore,
    cursor: str | None = None,
    page_size: int = 100,
    channels: str | None = None,
    topics: str | None = None,
) -> tuple[list[ClassifiedItem], str]:
    """Poll Benzinga + FMP in one cycle, dedup across sources.

    Parameters
    ----------
    benzinga_adapter : BenzingaRestAdapter or None
    fmp_adapter : FmpAdapter or None
    store : SqliteStore
    cursor : str, optional
    page_size : int
    channels : str, optional
        Comma-separated Benzinga channel names.
    topics : str, optional
        Comma-separated Benzinga topic names.

    Returns
    -------
    (items, new_cursor)
    """
    all_classified, provider_cursors, _provider_counts = poll_and_classify_live_bus(
        benzinga_adapter=benzinga_adapter,
        fmp_adapter=fmp_adapter,
        store=store,
        provider_cursors=seed_provider_cursors(cursor),
        page_size=page_size,
        channels=channels,
        topics=topics,
        tv_symbols=None,
    )
    new_cursor = legacy_cursor_from_provider_cursors(provider_cursors) or (cursor or "")
    return all_classified, new_cursor


def poll_and_classify_live_bus(
    benzinga_adapter: BenzingaRestAdapter | None,
    fmp_adapter: Any | None,
    store: SqliteStore,
    *,
    provider_cursors: dict[str, str] | None = None,
    page_size: int = 100,
    channels: str | None = None,
    topics: str | None = None,
    tv_symbols: list[str] | None = None,
) -> tuple[list[ClassifiedItem], dict[str, str], dict[str, int]]:
    """Poll all configured live-news providers in parallel.

    This is the provider-neutral live lane. Each provider keeps its own
    watermark, all sources fan out in parallel, and raw items are merged with a
    canonical cross-provider dedup pass before classification.
    """
    now_utc = datetime.now(UTC)
    provider_cursors = dict(provider_cursors or {})
    provider_counts: dict[str, int] = {}
    fetched_by_provider: dict[str, list[NewsItem]] = {}
    errors: list[str] = []
    fetch_order_items: list[tuple[int, NewsItem]] = []

    futures: dict[Any, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="live-news") as pool:
        if benzinga_adapter is not None:
            provider_counts[_CURSOR_KEY_BENZINGA] = 0
            futures[pool.submit(
                benzinga_adapter.fetch_news,
                updated_since=provider_cursors.get(_CURSOR_KEY_BENZINGA),
                page_size=page_size,
                channels=channels,
                topics=topics,
            )] = (_CURSOR_KEY_BENZINGA, "Benzinga")
        if fmp_adapter is not None:
            provider_counts[_CURSOR_KEY_FMP_STOCK] = 0
            provider_counts[_CURSOR_KEY_FMP_PRESS] = 0
            futures[pool.submit(
                fmp_adapter.fetch_stock_latest,
                page=0,
                limit=page_size,
            )] = (_CURSOR_KEY_FMP_STOCK, "FMP-stock")
            futures[pool.submit(
                fmp_adapter.fetch_press_latest,
                page=0,
                limit=page_size,
            )] = (_CURSOR_KEY_FMP_PRESS, "FMP-press")
        tv_symbols = [str(symbol).strip().upper() for symbol in (tv_symbols or []) if str(symbol).strip()]
        if tv_symbols:
            provider_counts[_CURSOR_KEY_TV] = 0
            futures[pool.submit(_fetch_tv_news_items, tv_symbols, max_total=page_size)] = (_CURSOR_KEY_TV, "TradingView")

        completion_order = 0
        for fut in as_completed(futures):
            provider_key, label = futures[fut]
            try:
                fetched = fut.result()
            except Exception as exc:
                _msg = _sanitize_exc(exc)
                logger.warning("%s poll failed: %s", label, _msg)
                errors.append(f"{label}: {_msg}")
                continue

            fetched_items = [item for item in fetched if isinstance(item, NewsItem)]
            fetched_by_provider[provider_key] = fetched_items
            filtered_items = _filter_items_by_cursor(fetched_items, provider_cursors.get(provider_key))
            provider_counts[provider_key] = len(filtered_items)
            for item in filtered_items:
                fetch_order_items.append((completion_order, item))
            completion_order += 1

    n_sources = len(provider_counts)
    if errors and not fetch_order_items and len(errors) >= n_sources and n_sources > 0:
        raise RuntimeError("All sources failed: " + "; ".join(errors))

    for provider_key, fetched_items in fetched_by_provider.items():
        provider_cursors[provider_key] = _advance_provider_cursor(
            provider_cursors.get(provider_key),
            fetched_items,
        )

    raw_items = _dedup_raw_items_cross_provider(fetch_order_items)
    all_classified: list[ClassifiedItem] = []
    for item in raw_items:
        try:
            classified = _classify_item(item, store, now_utc)
            all_classified.extend(classified)
        except Exception as exc:
            logger.warning(
                "Skipping item %s: %s",
                getattr(item, "item_id", "?")[:40],
                type(exc).__name__,
                exc_info=True,
            )

    logger.info(
        "Terminal live-bus poll: %d merged raw → %d classified | providers=%s | legacy_cursor=%s",
        len(raw_items),
        len(all_classified),
        live_news_source_label(provider_counts),
        legacy_cursor_from_provider_cursors(provider_cursors) or "(initial)",
    )

    return all_classified, provider_cursors, provider_counts


# ── FMP Economic Calendar Fetcher ───────────────────────────────

def fetch_economic_calendar(
    api_key: str,
    from_date: str,
    to_date: str,
) -> list[dict[str, Any]]:
    """Fetch economic calendar events from FMP (stable endpoint).

    Parameters
    ----------
    api_key : str
        FMP API key.
    from_date : str
        Start date in YYYY-MM-DD format.
    to_date : str
        End date in YYYY-MM-DD format.

    Returns
    -------
    list[dict]
        List of economic events with keys: date, country, event,
        actual, previous, estimate, currency, etc.
    """
    try:
        return _make_fmp_client(api_key).get_macro_calendar(
            date.fromisoformat(from_date),
            date.fromisoformat(to_date),
        )
    except Exception as exc:
        log_fetch_warning("FMP economic calendar", exc)
        return []


# ── FMP Ticker → GICS Sector Mapping ────────────────────────────


def fetch_ticker_sectors(api_key: str, tickers: list[str]) -> dict[str, str]:
    """Map tickers to GICS sectors via FMP ``/stable/profile``.

    Returns dict mapping uppercase ticker → sector string.
    Tickers without a sector in the profile are omitted.
    """
    if not api_key or not tickers:
        return {}

    symbols = [t.upper().strip() for t in tickers if t.strip()]
    if not symbols:
        return {}

    try:
        profiles = _make_fmp_client(api_key).get_profiles(symbols)
        result: dict[str, str] = {}
        for p in profiles:
            sym = (p.get("symbol") or "").upper().strip()
            sector = (p.get("sector") or "").strip()
            if sym and sector:
                result[sym] = sector
        return result
    except Exception as exc:
        log_fetch_warning("FMP ticker sectors", exc)
        return {}


# ── FMP Sector Performance ──────────────────────────────────────

def fetch_sector_performance(api_key: str) -> list[dict[str, Any]]:
    """Fetch current sector performance from FMP (stable endpoint).

    Uses ``/stable/sector-performance-snapshot``.  The endpoint only
    returns data for actual trading days, so on weekends and holidays
    this function walks back up to 5 calendar days to find the most
    recent session with data.

    The endpoint returns one row per (sector, exchange) pair; this
    function aggregates across exchanges to return the mean change
    per sector with a ``changesPercentage`` key for downstream
    compatibility.

    Returns list of dicts with keys: sector, changesPercentage.
    """
    try:
        client = _make_fmp_client(api_key)
        data: list = []
        # Walk back using the formal trading-day calendar to find
        # the most recent session with data (handles long weekends,
        # holidays like Thanksgiving correctly).
        query_date = datetime.now(_ET).date()
        for _ in range(6):
            candidate = client.get_sector_performance_snapshot(query_date)
            if isinstance(candidate, list) and candidate:
                data = candidate
                break
            query_date = _prev_trading_day(query_date)

        if not data:
            return []

        # Aggregate across exchanges: mean averageChange per sector
        sector_totals: dict[str, list[float]] = {}
        for row in data:
            sector = row.get("sector")
            change = row.get("averageChange")
            if sector and change is not None:
                sector_totals.setdefault(sector, []).append(float(change))

        result: list[dict[str, Any]] = []
        for sector, changes in sector_totals.items():
            avg = sum(changes) / len(changes) if changes else 0.0
            result.append({"sector": sector, "changesPercentage": round(avg, 4)})
        return result
    except Exception as exc:
        log_fetch_warning("FMP sector performance", exc)
        return []


# ── Aerospace & Defense Industry Watchlist ──────────────────────

# Default A&D tickers — major US defense primes + notable mid-caps
DEFENSE_TICKERS = (
    "LMT,RTX,NOC,GD,BA,LHX,HII,LDOS,BAH,KTOS,PLTR,AVAV,"
    "TXT,AXON,MRCY,SWBI,RGR,AJRD,BWXT,HEI"
)


def fetch_defense_watchlist(
    fmp_api_key: str,
    *,
    tickers: str = DEFENSE_TICKERS,
) -> list[dict[str, Any]]:
    """Fetch real-time quotes for Aerospace & Defense tickers from FMP.

    Parameters
    ----------
    fmp_api_key : str
        FMP API key.
    tickers : str
        Comma-separated ticker symbols (default: major A&D names).

    Returns
    -------
    list[dict]
        Quote records with keys like ``symbol``, ``name``, ``price``,
        ``change``, ``changesPercentage``, ``volume``, ``avgVolume``,
        ``marketCap``, ``pe``, ``yearHigh``, ``yearLow``.
    """
    try:
        symbols = [sym.strip().upper() for sym in tickers.split(",") if sym.strip()]
        if not symbols:
            return []
        return FMPClient(api_key=fmp_api_key, retry_attempts=1, timeout_seconds=12.0).get_batch_quotes(symbols)
    except Exception as exc:
        log_fetch_warning("FMP defense watchlist", exc)
        return []


def fetch_industry_performance(
    fmp_api_key: str,
    *,
    industry: str = "Aerospace & Defense",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch stocks in a specific industry via FMP stock screener.

    Returns quote-like records for all stocks in the given industry,
    sorted by market cap descending.

    Parameters
    ----------
    fmp_api_key : str
        FMP API key.
    industry : str
        GICS industry name (default: "Aerospace & Defense").
    limit : int
        Max number of results.

    Returns
    -------
    list[dict]
        Screener results with ``symbol``, ``companyName``, ``marketCap``,
        ``price``, ``volume``, ``sector``, ``industry``, ``beta``,
        ``lastAnnualDividend``, etc.
    """
    try:
        data = _make_fmp_client(fmp_api_key).get_company_screener(**{
            "industry": industry,
            "limit": str(limit),
            "exchange": "NYSE,NASDAQ,AMEX",
        })
        if not isinstance(data, list):
            return []
        # Sort by market cap descending
        def _safe_mcap(x: dict[str, Any]) -> float:
            try:
                return float(x.get("marketCap", 0) or 0)
            except (ValueError, TypeError):
                return 0.0
        data.sort(key=_safe_mcap, reverse=True)
        return data
    except Exception as exc:
        log_fetch_warning("FMP industry performance", exc)
        return []


# ── Benzinga Calendar Wrappers ──────────────────────────────────
# Generic factory + thin wrappers.  The BenzingaCalendarAdapter is
# instantiated-per-call so callers don't need to manage its lifecycle.


def _bz_calendar_call(
    api_key: str,
    method_name: str,
    label: str,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Generic lifecycle wrapper for ``BenzingaCalendarAdapter`` methods.

    Creates an adapter, calls *method_name* with *kwargs*, logs on error,
    and closes the adapter.  Returns ``[]`` when the adapter package is
    not installed.
    """
    if BenzingaCalendarAdapter is None:
        return []
    adapter = BenzingaCalendarAdapter(api_key)
    try:
        result: list[dict[str, Any]] = getattr(adapter, method_name)(**kwargs)
        return result
    except Exception as exc:
        log_fetch_warning(f"Benzinga {label}", exc)
        return []
    finally:
        adapter.close()


def fetch_benzinga_ratings(
    api_key: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 100,
    importance: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch analyst ratings from Benzinga (upgrades, downgrades, PT changes)."""
    return _bz_calendar_call(
        api_key, "fetch_ratings", "ratings",
        date_from=date_from, date_to=date_to,
        page_size=page_size, importance=importance,
    )


def fetch_benzinga_earnings(
    api_key: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 100,
    importance: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch earnings calendar from Benzinga (EPS, revenue estimates/actuals)."""
    return _bz_calendar_call(
        api_key, "fetch_earnings", "earnings",
        date_from=date_from, date_to=date_to,
        page_size=page_size, importance=importance,
    )


def fetch_benzinga_economics(
    api_key: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 100,
    importance: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch economic calendar from Benzinga (GDP, NFP, CPI, FOMC, etc.)."""
    return _bz_calendar_call(
        api_key, "fetch_economics", "economics",
        date_from=date_from, date_to=date_to,
        page_size=page_size, importance=importance,
    )


def fetch_benzinga_market_movers(api_key: str) -> dict[str, list[dict[str, Any]]]:
    """Fetch market movers (gainers + losers) from Benzinga."""
    if fetch_benzinga_movers is None:
        return {"gainers": [], "losers": []}
    return fetch_benzinga_movers(api_key)


def fetch_benzinga_delayed_quotes(
    api_key: str,
    symbols: list[str],
) -> list[dict[str, Any]]:
    """Fetch delayed quotes from Benzinga for given symbols."""
    if fetch_benzinga_quotes is None:
        return []
    return fetch_benzinga_quotes(api_key, symbols)


def fetch_benzinga_conference_calls(
    api_key: str,
    *,
    tickers: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Fetch conference call schedule from Benzinga."""
    return _bz_calendar_call(
        api_key, "fetch_conference_calls", "conference calls",
        tickers=tickers, date_from=date_from, date_to=date_to,
        page_size=page_size,
    )


def fetch_benzinga_dividends(
    api_key: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 100,
    importance: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch dividend calendar from Benzinga."""
    return _bz_calendar_call(
        api_key, "fetch_dividends", "dividends",
        date_from=date_from, date_to=date_to,
        page_size=page_size, importance=importance,
    )


def fetch_benzinga_splits(
    api_key: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 100,
    importance: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch stock splits calendar from Benzinga."""
    return _bz_calendar_call(
        api_key, "fetch_splits", "splits",
        date_from=date_from, date_to=date_to,
        page_size=page_size, importance=importance,
    )


def fetch_benzinga_ipos(
    api_key: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 100,
    importance: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch IPO calendar from Benzinga."""
    return _bz_calendar_call(
        api_key, "fetch_ipos", "IPOs",
        date_from=date_from, date_to=date_to,
        page_size=page_size, importance=importance,
    )


def fetch_benzinga_guidance(
    api_key: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 100,
    importance: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch earnings/revenue guidance from Benzinga."""
    return _bz_calendar_call(
        api_key, "fetch_guidance", "guidance",
        date_from=date_from, date_to=date_to,
        page_size=page_size, importance=importance,
    )


def fetch_benzinga_retail(
    api_key: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 100,
    importance: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch retail sales calendar from Benzinga."""
    return _bz_calendar_call(
        api_key, "fetch_retail", "retail",
        date_from=date_from, date_to=date_to,
        page_size=page_size, importance=importance,
    )


# ── News Wrappers (top news, quantified news, channels) ──────


def fetch_benzinga_top_news_items(
    api_key: str,
    *,
    channel: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch curated top news from Benzinga."""
    return fetch_benzinga_top_news(api_key, channel=channel, limit=limit)


def fetch_benzinga_quantified(
    api_key: str,
    *,
    page_size: int = 50,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch quantified news (with price-impact context) from Benzinga."""
    return fetch_benzinga_quantified_news(
        api_key, page_size=page_size,
        date_from=date_from, date_to=date_to,
    )


def fetch_benzinga_channel_list(api_key: str) -> list[dict[str, Any]]:
    """Fetch available channel names/IDs from Benzinga."""
    return fetch_benzinga_channels(api_key)


def fetch_benzinga_news_by_channel(
    api_key: str,
    channels: str,
    *,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    """Fetch news filtered by channel name(s) from Benzinga.

    Uses the ``/api/v2/news`` endpoint with ``channels`` parameter.
    Returns raw article dicts (not normalized ``NewsItem``).
    """
    adapter = BenzingaRestAdapter(api_key)
    try:
        items = adapter.fetch_news(page_size=page_size, channels=channels)
        # Convert NewsItem objects to plain dicts for Streamlit
        return [
            {
                "title": getattr(it, "headline", ""),
                "summary": getattr(it, "snippet", ""),
                "source": getattr(it, "source", ""),
                "url": getattr(it, "url", ""),
                "published_ts": getattr(it, "published_ts", ""),
                "tickers": getattr(it, "tickers", []),
            }
            for it in items
        ]
    except Exception as exc:
        log_fetch_warning("Benzinga channel news", exc)
        return []
    finally:
        adapter.close()


# ── Today / Tomorrow Outlook (trading-day traffic light) ─────

from newsstack_fmp._market_cal import (
    is_us_equity_trading_day as _is_trading_day,
    next_trading_day as _next_trading_day,
    prev_trading_day as _prev_trading_day,
)


def _compute_outlook_for_date(
    target_date: date,
    bz_api_key: str,
    fmp_api_key: str,
) -> dict[str, Any]:
    """Compute a trading-day outlook signal (🟢 / 🟡 / 🔴) for *target_date*.

    Shared core used by both ``compute_today_outlook`` and
    ``compute_tomorrow_outlook``.

    Factors
    -------
    - Benzinga earnings calendar for *target_date* (BMO count)
    - FMP economic calendar high-impact events for *target_date*
    - Benzinga economics (FOMC, CPI, NFP, GDP) for *target_date*
    - Current sector performance balance (majority red = caution)

    Returns
    -------
    dict with keys: target_date, outlook_label, outlook_color,
    outlook_score, reasons, earnings_count, earnings_bmo_count,
    high_impact_events, high_impact_events_details, sector_mood,
    notable_earnings
    """
    td_iso = target_date.isoformat()

    outlook_score = 0.0
    reasons: list[str] = []

    # ── 1. Benzinga earnings ──
    earnings_day: list[dict[str, Any]] = []
    earnings_bmo: list[dict[str, Any]] = []
    if bz_api_key:
        try:
            earnings_all = fetch_benzinga_earnings(
                bz_api_key, date_from=td_iso, date_to=td_iso,
                page_size=500,
            )
            earnings_day = [
                e for e in earnings_all
                if str(e.get("date") or "").startswith(td_iso)
            ]
            earnings_bmo = [
                e for e in earnings_day
                if str(e.get("earnings_timing") or e.get("time") or "").lower()
                in {"bmo", "before market open", "before_open"}
            ]
        except (KeyError, TypeError, ValueError, OSError) as exc:
            logger.warning("Outlook %s: earnings fetch failed: %s", td_iso, type(exc).__name__, exc_info=True)

    if len(earnings_bmo) >= 10:
        outlook_score += 0.5
        reasons.append(f"heavy_earnings_bmo_{len(earnings_bmo)}")
    elif len(earnings_day) >= 20:
        outlook_score += 0.25
        reasons.append(f"earnings_dense_{len(earnings_day)}")
    elif len(earnings_day) == 0:
        reasons.append("no_earnings")
    else:
        reasons.append(f"earnings_{len(earnings_day)}")

    # ── 2. High-impact macro events ──
    hi_events: list[dict[str, Any]] = []

    # 2a) FMP economic calendar
    if fmp_api_key:
        try:
            econ_data = fetch_economic_calendar(fmp_api_key, td_iso, td_iso)
            for ev in econ_data:
                imp = str(ev.get("impact") or ev.get("importance") or "").lower()
                if imp == "high":
                    hi_events.append({
                        "event": str(ev.get("event") or "—"),
                        "date": str(ev.get("date") or td_iso),
                        "country": str(ev.get("country") or "US"),
                        "source": "FMP",
                    })
        except (KeyError, TypeError, ValueError, OSError) as exc:
            logger.warning("Outlook %s: FMP econ calendar failed: %s", td_iso, type(exc).__name__, exc_info=True)

    # 2b) Benzinga economics calendar
    if bz_api_key:
        try:
            bz_econ = fetch_benzinga_economics(
                bz_api_key, date_from=td_iso, date_to=td_iso,
                page_size=100, importance=0,
            )
            for ev in bz_econ:
                imp = str(ev.get("importance", "")).lower()
                ev_name = str(ev.get("event_name") or ev.get("name") or "")
                if imp in {"0", "high"} or any(
                    kw in ev_name.upper()
                    for kw in ("CPI", "NFP", "FOMC", "GDP", "PCE", "PPI", "EMPLOYMENT")
                ):
                    already = any(
                        h["event"].lower() == ev_name.lower() for h in hi_events
                    )
                    if not already:
                        hi_events.append({
                            "event": ev_name or "—",
                            "date": str(ev.get("date") or td_iso),
                            "country": str(ev.get("country") or "US"),
                            "source": "Benzinga",
                        })
        except (KeyError, TypeError, ValueError, OSError) as exc:
            logger.warning("Outlook %s: Benzinga econ calendar failed: %s", td_iso, type(exc).__name__, exc_info=True)

    if len(hi_events) >= 3:
        outlook_score -= 1.5
        reasons.append(f"high_impact_events_{len(hi_events)}")
    elif len(hi_events) >= 2:
        outlook_score -= 1.0
        reasons.append(f"high_impact_events_{len(hi_events)}")
    elif len(hi_events) == 1:
        outlook_score -= 0.5
        reasons.append("high_impact_event_1")
    else:
        reasons.append("no_high_impact_events")

    # ── 3. Sector performance balance ──
    sector_mood = "neutral"
    if fmp_api_key:
        try:
            sectors = fetch_sector_performance(fmp_api_key)
            if sectors:
                red_count = 0
                for s in sectors:
                    try:
                        if float(s.get("changesPercentage", 0) or 0) < 0:
                            red_count += 1
                    except (ValueError, TypeError):
                        pass
                if red_count > len(sectors) * 0.7:
                    outlook_score -= 0.5
                    reasons.append("sectors_mostly_red")
                    sector_mood = "risk-off"
                elif red_count < len(sectors) * 0.3:
                    outlook_score += 0.5
                    reasons.append("sectors_mostly_green")
                    sector_mood = "risk-on"
                else:
                    reasons.append("sectors_mixed")
        except (KeyError, TypeError, ValueError, OSError) as exc:
            logger.warning("Outlook %s: sector performance failed: %s", td_iso, type(exc).__name__, exc_info=True)

    # ── Map score to traffic light ──
    if outlook_score >= 0.5:
        label = "🟢 POSITIVE"
        color = "green"
    elif outlook_score <= -1.0:
        label = "🔴 CAUTION"
        color = "red"
    else:
        label = "🟡 NEUTRAL"
        color = "orange"

    # Build notable earnings list
    notable_earnings: list[dict[str, str]] = []
    for e in earnings_day[:20]:
        tk = str(e.get("ticker") or "")
        nm = str(e.get("name") or "")
        timing = str(e.get("earnings_timing") or e.get("time") or "—")
        if tk:
            notable_earnings.append({"ticker": tk, "name": nm, "timing": timing})

    return {
        "target_date": td_iso,
        "outlook_label": label,
        "outlook_color": color,
        "outlook_score": round(outlook_score, 2),
        "reasons": reasons,
        "earnings_count": len(earnings_day),
        "earnings_bmo_count": len(earnings_bmo),
        "high_impact_events": len(hi_events),
        "high_impact_events_details": hi_events,
        "notable_earnings": notable_earnings,
        "sector_mood": sector_mood,
    }


def compute_today_outlook(
    bz_api_key: str,
    fmp_api_key: str,
) -> dict[str, Any]:
    """Compute a today-trading-day outlook signal.

    If today is not a trading day, returns a dict with
    ``outlook_label = "⚪ MARKET CLOSED"`` and no data.
    """
    today = datetime.now(_ET).date()
    if not _is_trading_day(today):
        return {
            "target_date": today.isoformat(),
            "outlook_label": "⚪ MARKET CLOSED",
            "outlook_color": "gray",
            "outlook_score": 0.0,
            "reasons": ["not_a_trading_day"],
            "earnings_count": 0,
            "earnings_bmo_count": 0,
            "high_impact_events": 0,
            "high_impact_events_details": [],
            "notable_earnings": [],
            "sector_mood": "closed",
        }
    result = _compute_outlook_for_date(today, bz_api_key, fmp_api_key)
    # Backward-compat alias
    result["next_trading_day"] = result["target_date"]
    return result


def compute_tomorrow_outlook(
    bz_api_key: str,
    fmp_api_key: str,
) -> dict[str, Any]:
    """Compute a next-trading-day outlook signal (🟢 / 🟡 / 🔴).

    Delegates to the shared ``_compute_outlook_for_date`` core with the
    next US equity trading day.  Returns the same dict shape with
    backward-compatible key aliases (``next_trading_day``,
    ``earnings_tomorrow_count``, etc.).
    """
    today = datetime.now(_ET).date()
    next_td = _next_trading_day(today)
    result = _compute_outlook_for_date(next_td, bz_api_key, fmp_api_key)

    # Backward-compatible aliases expected by UI layer
    result["next_trading_day"] = result["target_date"]
    result["earnings_tomorrow_count"] = result["earnings_count"]
    result["earnings_bmo_tomorrow_count"] = result["earnings_bmo_count"]
    result["high_impact_events_tomorrow"] = result["high_impact_events"]
    result["high_impact_events_tomorrow_details"] = result["high_impact_events_details"]
    return result


# ── Power Gap Scanner (PEG / Monster PEG / Monster Gap) ──────


def compute_power_gaps(
    api_key: str,
    *,
    peg_min_gap: float = 4.0,
    monster_min_gap: float = 8.0,
    peg_min_rvol: float = 1.5,
    monster_min_rvol: float = 2.0,
) -> list[dict[str, Any]]:
    """Compute Power Earning Gap / Monster Gap classifications.

    Cross-references Benzinga Market Movers with today's earnings calendar:

    * **Power Earning Gap (PEG)**: gap ≥ *peg_min_gap* % AND earnings beat
      (``eps_surprise > 0``) AND relative-volume ≥ *peg_min_rvol*.
    * **Monster Power Earning Gap (MPEG)**: gap ≥ *monster_min_gap* % AND
      earnings beat AND relative-volume ≥ *monster_min_rvol*.
    * **Monster Gap (MG)**: gap ≥ *monster_min_gap* % AND relative-volume ≥
      *monster_min_rvol* (no earnings requirement).
    * **Gap Up / Gap Down**: significant move that doesn't meet PEG/MPEG/MG
      criteria.

    Parameters
    ----------
    api_key : str
        Benzinga API key.
    peg_min_gap : float
        Minimum absolute gap % for Power Earning Gap (default 4%).
    monster_min_gap : float
        Minimum absolute gap % for Monster classifications (default 8%).
    peg_min_rvol : float
        Minimum relative volume for PEG (default 1.5×).
    monster_min_rvol : float
        Minimum relative volume for Monster classifications (default 2.0×).

    Returns
    -------
    list[dict]
        Classified gap records sorted by absolute gap descending.  Each dict
        contains: ``symbol``, ``company_name``, ``gap_pct``, ``change``,
        ``price``, ``volume``, ``avg_volume``, ``rel_vol``, ``sector``,
        ``gap_type`` (``"MPEG"``, ``"PEG"``, ``"MG"``, ``"Gap Up"``, or
        ``"Gap Down"``), ``has_earnings``, ``eps_surprise``,
        ``eps_surprise_pct``.
    """
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1) Fetch movers
    movers_data = fetch_benzinga_market_movers(api_key)
    gainers = movers_data.get("gainers", [])
    losers = movers_data.get("losers", [])
    all_movers: list[dict[str, Any]] = []
    for m in gainers + losers:
        sym = str(m.get("symbol", m.get("ticker", ""))).upper()
        if not sym:
            continue
        try:
            change_pct = float(m.get("changePercent", m.get("change_percent", 0)))
        except (ValueError, TypeError):
            change_pct = 0.0
        try:
            vol = float(m.get("volume", 0))
        except (ValueError, TypeError):
            vol = 0.0
        try:
            avg_vol = float(m.get("averageVolume", m.get("average_volume", 0)))
        except (ValueError, TypeError):
            avg_vol = 0.0
        rel_vol = (vol / avg_vol) if avg_vol > 0 else 0.0

        all_movers.append({
            "symbol": sym,
            "company_name": str(m.get("companyName", m.get("company_name", ""))),
            "gap_pct": change_pct,
            "change": m.get("change", 0),
            "price": m.get("price", m.get("last", 0)),
            "volume": vol,
            "avg_volume": avg_vol,
            "rel_vol": round(rel_vol, 2),
            "sector": str(m.get("gicsSectorName", m.get("sector", ""))),
            "market_cap": m.get("marketCap", m.get("market_cap", "")),
        })

    if not all_movers:
        return []

    # 2) Fetch today's earnings to identify earnings gaps
    earnings = fetch_benzinga_earnings(api_key, date_from=today, date_to=today, page_size=500)
    earnings_map: dict[str, dict[str, Any]] = {}
    for e in earnings:
        tk = str(e.get("ticker", "")).upper()
        if tk:
            earnings_map[tk] = e

    # 3) Classify each mover
    results: list[dict[str, Any]] = []
    for mv in all_movers:
        sym = mv["symbol"]
        abs_gap = abs(mv["gap_pct"])
        rvol = mv["rel_vol"]

        # Check earnings beat/miss
        earn = earnings_map.get(sym)
        has_earnings = earn is not None
        eps_surprise = 0.0
        eps_surprise_pct = 0.0
        if earn:
            try:
                eps_surprise = float(earn.get("eps_surprise", 0) or 0)
            except (ValueError, TypeError):
                eps_surprise = 0.0
            try:
                eps_surprise_pct = float(earn.get("eps_surprise_percent", 0) or 0)
            except (ValueError, TypeError):
                eps_surprise_pct = 0.0

        earnings_beat = has_earnings and eps_surprise > 0

        # Classify
        if abs_gap >= monster_min_gap and earnings_beat and rvol >= monster_min_rvol:
            gap_type = "MPEG"
        elif abs_gap >= peg_min_gap and earnings_beat and rvol >= peg_min_rvol:
            gap_type = "PEG"
        elif abs_gap >= monster_min_gap and rvol >= monster_min_rvol:
            gap_type = "MG"
        else:
            gap_type = "Gap Up" if mv["gap_pct"] > 0 else "Gap Down"

        mv["gap_type"] = gap_type
        mv["has_earnings"] = has_earnings
        mv["eps_surprise"] = eps_surprise
        mv["eps_surprise_pct"] = round(eps_surprise_pct, 2)
        results.append(mv)

    # Sort by absolute gap descending
    results.sort(key=lambda x: abs(x["gap_pct"]), reverse=True)
    return results

