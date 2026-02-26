"""Polling engine for the Bloomberg Terminal.

Wraps ``BenzingaRestAdapter`` + optional ``FmpAdapter`` + open_prep
classifiers into a single ``poll_and_classify()`` call that fetches new
items, deduplicates them, scores them, and returns fully classified
records ready for display.

Supports multi-source ingestion: Benzinga (primary) + FMP (secondary).

This module is imported by ``streamlit_terminal.py`` — it is **not**
a standalone script.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Set

from newsstack_fmp.common_types import NewsItem
from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter
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
    poll_interval_s: float = field(
        default_factory=lambda: _env_float("TERMINAL_POLL_INTERVAL_S", 5.0),
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
    page_size: int = field(
        default_factory=lambda: _env_int("TERMINAL_PAGE_SIZE", 100),
    )
    display_output: str = field(
        default_factory=lambda: os.getenv("TERMINAL_DISPLAY_OUTPUT", "abstract"),
    )
    fmp_enabled: bool = field(
        default_factory=lambda: os.getenv("TERMINAL_FMP_ENABLED", "1") == "1",
    )


# ── Classified item schema ──────────────────────────────────────

@dataclass
class ClassifiedItem:
    """Fully enriched news item ready for display / export."""

    # Identity
    item_id: str
    ticker: str  # primary ticker (may repeat item for multi-ticker articles)
    tickers_all: List[str]
    headline: str
    snippet: str
    url: Optional[str]
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
    age_minutes: Optional[float]
    is_actionable: bool

    # open_prep: source quality
    source_tier: str  # TIER_1 … TIER_4
    source_rank: int  # 1-4

    # Benzinga metadata
    channels: List[str]
    tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
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
        }


# ── Core polling + classification ───────────────────────────────

def _classify_item(
    item: NewsItem,
    store: SqliteStore,
    now_utc: datetime,
) -> List[ClassifiedItem]:
    """Classify one NewsItem and return one ClassifiedItem per ticker.

    Returns empty list if the item is invalid, already seen, or has no tickers.
    """
    if not item.is_valid:
        return []

    # Determine effective timestamp
    raw_ts = item.updated_ts or item.published_ts
    ts = raw_ts if raw_ts and raw_ts > 0 else time.time()

    # Dedup
    if not store.mark_seen(item.provider, item.item_id, ts):
        return []

    tickers = [t.strip().upper() for t in (item.tickers or []) if isinstance(t, str) and t.strip()]
    tickers = list(dict.fromkeys(tickers))  # dedupe preserving order
    if not tickers:
        # Still classify ticker-less items under "MARKET"
        tickers = ["MARKET"]

    if not item.headline.strip():
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
    article_dt: Optional[datetime] = None
    if item.published_ts and item.published_ts > 0:
        article_dt = datetime.fromtimestamp(item.published_ts, tz=UTC)
    recency_info = classify_recency(article_dt, now_utc)

    source_info = classify_source_quality(item.source or "", item.headline)

    # ── Benzinga-specific metadata ──────────────────────────
    raw = item.raw or {}
    channels = [c.get("name", "") for c in raw.get("channels", []) if isinstance(c, dict)]
    tags = [t.get("name", "") for t in raw.get("tags", []) if isinstance(t, dict)]

    # ── Build one ClassifiedItem per ticker ──────────────────
    results: List[ClassifiedItem] = []
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
            event_class=event_info["event_class"],
            event_label=event_info["event_label"],
            materiality=event_info["materiality"],
            # recency
            recency_bucket=recency_info["recency_bucket"],
            age_minutes=recency_info["age_minutes"],
            is_actionable=recency_info["is_actionable"],
            # source
            source_tier=source_info["source_tier"],
            source_rank=source_info["source_rank"],
            # benzinga metadata
            channels=channels,
            tags=tags,
        )
        results.append(ci)
    return results


def poll_and_classify(
    adapter: BenzingaRestAdapter,
    store: SqliteStore,
    cursor: Optional[str] = None,
    page_size: int = 100,
) -> tuple[List[ClassifiedItem], str]:
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

    Returns
    -------
    (items, new_cursor)
        items: List of fully classified items (may be empty if no new news).
        new_cursor: Updated cursor string for next poll.
    """
    now_utc = datetime.now(UTC)
    raw_items = adapter.fetch_news(updated_since=cursor, page_size=page_size)

    all_classified: List[ClassifiedItem] = []
    try:
        max_ts = float(cursor) if cursor else 0.0
    except (ValueError, TypeError):
        max_ts = 0.0

    for item in raw_items:
        try:
            classified = _classify_item(item, store, now_utc)
            all_classified.extend(classified)
        except Exception as exc:
            logger.warning("Skipping item %s: %s", getattr(item, 'item_id', '?')[:40], exc)

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
    benzinga_adapter: Optional[BenzingaRestAdapter],
    fmp_adapter: "Any | None",
    store: SqliteStore,
    cursor: Optional[str] = None,
    page_size: int = 100,
) -> tuple[List[ClassifiedItem], str]:
    """Poll Benzinga + FMP in one cycle, dedup across sources.

    Parameters
    ----------
    benzinga_adapter : BenzingaRestAdapter or None
    fmp_adapter : FmpAdapter or None
    store : SqliteStore
    cursor : str, optional
    page_size : int

    Returns
    -------
    (items, new_cursor)
    """
    now_utc = datetime.now(UTC)
    raw_items: List[NewsItem] = []
    errors: List[str] = []

    def _sanitize_exc(exc: Exception) -> str:
        """Strip API keys/tokens from exception text for safe logging."""
        return re.sub(r"(apikey|token)=[^&\s]+", r"\1=***", str(exc), flags=re.IGNORECASE)

    # ── Benzinga ────────────────────────────────────────────
    if benzinga_adapter is not None:
        try:
            bz_items = benzinga_adapter.fetch_news(
                updated_since=cursor, page_size=page_size,
            )
            raw_items.extend(bz_items)
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("Benzinga poll failed: %s", _msg)
            errors.append(f"Benzinga: {_msg}")

    # ── FMP (stock news + press releases) ───────────────────
    if fmp_adapter is not None:
        try:
            raw_items.extend(fmp_adapter.fetch_stock_latest(page=0, limit=page_size))
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("FMP stock-news poll failed: %s", _msg)
            errors.append(f"FMP-stock: {_msg}")
        try:
            raw_items.extend(fmp_adapter.fetch_press_latest(page=0, limit=page_size))
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("FMP press-release poll failed: %s", _msg)
            errors.append(f"FMP-press: {_msg}")

    # If ALL configured sources failed, raise so the caller can surface
    # the error in the UI instead of showing misleading "0 items" success.
    n_sources = (1 if benzinga_adapter else 0) + (1 if fmp_adapter else 0)
    if errors and not raw_items and len(errors) >= n_sources:
        raise RuntimeError("All sources failed: " + "; ".join(errors))

    all_classified: List[ClassifiedItem] = []
    try:
        max_ts = float(cursor) if cursor else 0.0
    except (ValueError, TypeError):
        max_ts = 0.0

    for item in raw_items:
        try:
            classified = _classify_item(item, store, now_utc)
            all_classified.extend(classified)
        except Exception as exc:
            logger.warning("Skipping item %s: %s", getattr(item, 'item_id', '?')[:40], exc)

        ts = item.updated_ts or item.published_ts
        if ts and ts > 0:
            max_ts = max(max_ts, ts)

    new_cursor = str(int(max_ts)) if max_ts > 0 else (cursor or "")

    logger.info(
        "Terminal multi-poll: %d raw → %d classified | cursor %s → %s",
        len(raw_items), len(all_classified), cursor or "(initial)", new_cursor,
    )

    return all_classified, new_cursor


# ── FMP Economic Calendar Fetcher ───────────────────────────────

def fetch_economic_calendar(
    api_key: str,
    from_date: str,
    to_date: str,
) -> List[Dict[str, Any]]:
    """Fetch economic calendar events from FMP.

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
        actual, previous, consensus, impact, etc.
    """
    import httpx

    url = "https://financialmodelingprep.com/api/v3/economic_calendar"
    params = {"from": from_date, "to": to_date, "apikey": api_key}

    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return data
            return []
    except Exception as exc:
        _msg = re.sub(r"(apikey|token)=[^&\s]+", r"\1=***", str(exc), flags=re.IGNORECASE)
        logger.warning("FMP economic calendar fetch failed: %s", _msg)
        return []


# ── FMP Sector Performance ──────────────────────────────────────

def fetch_sector_performance(api_key: str) -> List[Dict[str, Any]]:
    """Fetch current sector performance from FMP.

    Returns list of dicts with keys: sector, changesPercentage.
    """
    import httpx

    url = "https://financialmodelingprep.com/api/v3/sectors-performance"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url, params={"apikey": api_key})
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return data
            return []
    except Exception as exc:
        _msg = re.sub(r"(apikey|token)=[^&\s]+", r"\1=***", str(exc), flags=re.IGNORECASE)
        logger.warning("FMP sector performance fetch failed: %s", _msg)
        return []
