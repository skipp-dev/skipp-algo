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

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from newsstack_fmp.common_types import NewsItem
from newsstack_fmp._bz_http import _sanitize_exc, log_fetch_warning
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

# ── Shared FMP httpx client (avoid per-call TCP+TLS overhead) ──

import atexit
import threading

_fmp_client: "httpx.Client | None" = None   # type: ignore[name-defined]
_fmp_client_lock = threading.Lock()


def _get_fmp_client() -> "httpx.Client":   # type: ignore[name-defined]
    """Return a lazily-created, module-scoped httpx.Client for FMP."""
    global _fmp_client
    if _fmp_client is None:
        with _fmp_client_lock:
            if _fmp_client is None:
                import httpx
                _fmp_client = httpx.Client(timeout=12.0)
                atexit.register(_fmp_client.close)
    return _fmp_client  # type: ignore[return-value]


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
    now_utc = datetime.now(UTC)
    raw_items: list[NewsItem] = []
    errors: list[str] = []

    # ── Parallel HTTP fetch (Benzinga + FMP) ────────────────
    # Each source runs in its own thread so a slow/retrying endpoint
    # doesn't block the others.  Typical poll drops from ~6-10s to ~3s.
    futures: dict[Any, str] = {}
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="poll") as pool:
        if benzinga_adapter is not None:
            futures[pool.submit(
                benzinga_adapter.fetch_news,
                updated_since=cursor, page_size=page_size,
                channels=channels, topics=topics,
            )] = "Benzinga"
        if fmp_adapter is not None:
            futures[pool.submit(
                fmp_adapter.fetch_stock_latest, page=0, limit=page_size,
            )] = "FMP-stock"
            futures[pool.submit(
                fmp_adapter.fetch_press_latest, page=0, limit=page_size,
            )] = "FMP-press"

        for fut in as_completed(futures):
            label = futures[fut]
            try:
                raw_items.extend(fut.result())
            except Exception as exc:
                _msg = _sanitize_exc(exc)
                logger.warning("%s poll failed: %s", label, _msg)
                errors.append(f"{label}: {_msg}")

    # If ALL configured sources failed, raise so the caller can surface
    # the error in the UI instead of showing misleading "0 items" success.
    n_sources = (1 if benzinga_adapter else 0) + (1 if fmp_adapter else 0)
    if errors and not raw_items and len(errors) >= n_sources:
        raise RuntimeError("All sources failed: " + "; ".join(errors))

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
    url = "https://financialmodelingprep.com/stable/economic-calendar"
    params = {"from": from_date, "to": to_date, "apikey": api_key}

    try:
        r = _get_fmp_client().get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return []
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

    sym_str = ",".join(t.upper().strip() for t in tickers if t.strip())
    if not sym_str:
        return {}

    try:
        r = _get_fmp_client().get(
            "https://financialmodelingprep.com/stable/profile",
            params={"apikey": api_key, "symbol": sym_str},
        )
        r.raise_for_status()
        profiles = r.json()
        if not isinstance(profiles, list):
            return {}

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
    url = "https://financialmodelingprep.com/stable/sector-performance-snapshot"
    try:
        client = _get_fmp_client()
        data: list = []
        # Walk back up to 5 days to find the most recent trading day
        for offset in range(6):
            query_date = date.today() - timedelta(days=offset)
            r = client.get(url, params={"apikey": api_key, "date": query_date.isoformat()})
            r.raise_for_status()
            candidate = r.json()
            if isinstance(candidate, list) and candidate:
                data = candidate
                break

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
    url = "https://financialmodelingprep.com/stable/batch-quote"
    try:
        r = _get_fmp_client().get(url, params={"apikey": fmp_api_key, "symbols": tickers})
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
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
    url = "https://financialmodelingprep.com/stable/company-screener"
    try:
        r = _get_fmp_client().get(url, params={
            "apikey": fmp_api_key,
            "industry": industry,
            "limit": str(limit),
            "exchange": "NYSE,NASDAQ,AMEX",
        })
        r.raise_for_status()
        data = r.json()
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


# ── Tomorrow Outlook (next-trading-day traffic light) ────────

from newsstack_fmp._market_cal import (
    next_trading_day as _next_trading_day,
)


def compute_tomorrow_outlook(
    bz_api_key: str,
    fmp_api_key: str,
) -> dict[str, Any]:
    """Compute a next-trading-day outlook signal (🟢 / 🟡 / 🔴).

    This is a standalone version for the News Intelligence Dashboard that uses
    live Benzinga + FMP data rather than the open_prep pipeline result.

    Factors
    -------
    - Benzinga earnings calendar for the next trading day (BMO count)
    - FMP economic calendar high-impact events for the next trading day
    - Benzinga economics (FOMC, CPI, NFP, GDP) for the next trading day
    - Current sector performance balance (majority red = caution)

    Feed sentiment is evaluated separately in the UI layer because the
    feed is a mutable session-state object that cannot be cached.

    Returns
    -------
    dict with keys: next_trading_day, outlook_label, outlook_color,
    outlook_score, reasons, earnings_tomorrow_count,
    earnings_bmo_tomorrow_count, high_impact_events_tomorrow,
    high_impact_events_tomorrow_details, sector_mood
    """
    today = date.today()
    next_td = _next_trading_day(today)
    next_td_iso = next_td.isoformat()

    outlook_score = 0.0
    reasons: list[str] = []

    # ── 1. Benzinga earnings for next trading day ──
    earnings_tomorrow: list[dict[str, Any]] = []
    earnings_bmo: list[dict[str, Any]] = []
    if bz_api_key:
        try:
            earnings_all = fetch_benzinga_earnings(
                bz_api_key, date_from=next_td_iso, date_to=next_td_iso,
                page_size=500,
            )
            earnings_tomorrow = [
                e for e in earnings_all
                if str(e.get("date") or "").startswith(next_td_iso)
            ]
            earnings_bmo = [
                e for e in earnings_tomorrow
                if str(e.get("earnings_timing") or e.get("time") or "").lower()
                in {"bmo", "before market open", "before_open"}
            ]
        except (KeyError, TypeError, ValueError, OSError) as exc:
            logger.warning("Tomorrow outlook: earnings fetch failed: %s", type(exc).__name__, exc_info=True)

    if len(earnings_bmo) >= 10:
        outlook_score += 0.5
        reasons.append(f"heavy_earnings_bmo_{len(earnings_bmo)}")
    elif len(earnings_tomorrow) >= 20:
        outlook_score += 0.25
        reasons.append(f"earnings_dense_{len(earnings_tomorrow)}")
    elif len(earnings_tomorrow) == 0:
        reasons.append("no_earnings_tomorrow")
    else:
        reasons.append(f"earnings_{len(earnings_tomorrow)}")

    # ── 2. High-impact macro events for next trading day ──
    hi_events: list[dict[str, Any]] = []

    # 2a) FMP economic calendar
    if fmp_api_key:
        try:
            econ_data = fetch_economic_calendar(fmp_api_key, next_td_iso, next_td_iso)
            for ev in econ_data:
                imp = str(ev.get("impact") or ev.get("importance") or "").lower()
                if imp == "high":
                    hi_events.append({
                        "event": str(ev.get("event") or "—"),
                        "date": str(ev.get("date") or next_td_iso),
                        "country": str(ev.get("country") or "US"),
                        "source": "FMP",
                    })
        except (KeyError, TypeError, ValueError, OSError) as exc:
            logger.warning("Tomorrow outlook: FMP econ calendar failed: %s", type(exc).__name__, exc_info=True)

    # 2b) Benzinga economics calendar
    if bz_api_key:
        try:
            bz_econ = fetch_benzinga_economics(
                bz_api_key, date_from=next_td_iso, date_to=next_td_iso,
                page_size=100, importance=0,
            )
            for ev in bz_econ:
                imp = str(ev.get("importance", "")).lower()
                ev_name = str(ev.get("event_name") or ev.get("name") or "")
                # Benzinga importance: 0=high, 1=medium, 2=low
                if imp in {"0", "high"} or any(
                    kw in ev_name.upper()
                    for kw in ("CPI", "NFP", "FOMC", "GDP", "PCE", "PPI", "EMPLOYMENT")
                ):
                    # Avoid duplicates from FMP
                    already = any(
                        h["event"].lower() == ev_name.lower() for h in hi_events
                    )
                    if not already:
                        hi_events.append({
                            "event": ev_name or "—",
                            "date": str(ev.get("date") or next_td_iso),
                            "country": str(ev.get("country") or "US"),
                            "source": "Benzinga",
                        })
        except (KeyError, TypeError, ValueError, OSError) as exc:
            logger.warning("Tomorrow outlook: Benzinga econ calendar failed: %s", type(exc).__name__, exc_info=True)

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
            logger.warning("Tomorrow outlook: sector performance failed: %s", type(exc).__name__, exc_info=True)

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

    # Build notable earnings list (top names for display)
    notable_earnings: list[dict[str, str]] = []
    for e in earnings_tomorrow[:20]:
        tk = str(e.get("ticker") or "")
        nm = str(e.get("name") or "")
        timing = str(e.get("earnings_timing") or e.get("time") or "—")
        if tk:
            notable_earnings.append({"ticker": tk, "name": nm, "timing": timing})

    return {
        "next_trading_day": next_td_iso,
        "outlook_label": label,
        "outlook_color": color,
        "outlook_score": round(outlook_score, 2),
        "reasons": reasons,
        "earnings_tomorrow_count": len(earnings_tomorrow),
        "earnings_bmo_tomorrow_count": len(earnings_bmo),
        "high_impact_events_tomorrow": len(hi_events),
        "high_impact_events_tomorrow_details": hi_events,
        "notable_earnings": notable_earnings,
        "sector_mood": sector_mood,
    }


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

