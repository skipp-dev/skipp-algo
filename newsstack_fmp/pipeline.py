"""Multi-source pipeline: FMP + Benzinga → Cursor/State → Dedupe/Novelty → Score → Enrich → Export.

Designed for **synchronous poll-on-refresh** from Streamlit.
Call ``poll_once(cfg)`` on each Streamlit cycle — no background process needed.

Benzinga WebSocket (if enabled) runs in a daemon thread and feeds items
into a thread-safe queue that ``poll_once()`` drains each cycle.

Also provides ``run_pipeline(cfg)`` for standalone infinite-loop usage.
"""

from __future__ import annotations

import copy
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

from .common_types import NewsItem
from .config import Config
from .enrich import Enricher
from .ingest_fmp import FmpAdapter
from .ingest_fmp_filings import fetch_fmp_8k_latest, fetch_fmp_13f_latest
from .ingest_fmp_political import fetch_fmp_house_trades, fetch_fmp_senate_trades
from .ingest_unusual_whales import fetch_uw_news_headlines, is_uw_configured
from .normalize import (
    normalize_fmp_filing_8k,
    normalize_fmp_filing_13f,
    normalize_fmp_political_trade,
    normalize_newsapi_ai,
    normalize_uw_news_headline,
)
from .open_prep_export import export_open_prep
from .scoring import classify_and_score, cluster_hash
from .shared_fetch import CachedNewsBatch, fetch_cached_batch, tv_headline_to_news_item
from .store_sqlite import SqliteStore

logger = logging.getLogger(__name__)

# ── Module-level singletons (reused across Streamlit refreshes) ──
_store: SqliteStore | None = None
_fmp_adapter: FmpAdapter | None = None
_fmp_adapter_key: str | None = None  # api_key the singleton was built with
_bz_rest_adapter: Any | None = None  # BenzingaRestAdapter (lazy)
_bz_rest_adapter_key: str | None = None
_bz_ws_adapter: Any | None = None  # BenzingaWsAdapter (lazy)
_bz_ws_adapter_key: tuple[str, str, tuple[str, ...] | None] | None = None
_bz_rss_adapter: Any | None = None  # BenzingaRssAdapter (lazy)
_enricher: Enricher | None = None
_best_by_ticker: dict[str, dict[str, Any]] = {}
_bbt_lock = threading.Lock()
_last_meta: dict[str, Any] | None = None
_meta_lock = threading.Lock()  # protects _last_meta read/write
_init_lock = threading.Lock()  # protects all singleton getters below


def _credential_changed(stored: Any, current: Any) -> bool:
    """Return True when a singleton must be rebuilt because the
    config-supplied credential / endpoint differs from the one it was
    originally constructed with. Found via SMC bug-hunt v2 phase 4 —
    silent credential-rotation skip on Streamlit refresh."""
    return stored is not None and stored != current


def _get_store(cfg: Config) -> SqliteStore:
    global _store
    with _init_lock:
        if _store is None:
            os.makedirs(os.path.dirname(cfg.sqlite_path) or ".", exist_ok=True)
            _store = SqliteStore(cfg.sqlite_path)
    return _store


def _get_fmp_adapter(cfg: Config) -> FmpAdapter:
    global _fmp_adapter, _fmp_adapter_key
    with _init_lock:
        if _fmp_adapter is None or _credential_changed(_fmp_adapter_key, cfg.fmp_api_key):
            if _fmp_adapter is not None and hasattr(_fmp_adapter, "close"):
                try:
                    _fmp_adapter.close()
                except Exception:
                    logger.debug("fmp adapter close on rotation failed", exc_info=True)
            _fmp_adapter = FmpAdapter(cfg.fmp_api_key)
            _fmp_adapter_key = cfg.fmp_api_key
    return _fmp_adapter


def _get_bz_rest_adapter(cfg: Config) -> Any:
    global _bz_rest_adapter, _bz_rest_adapter_key
    with _init_lock:
        if _bz_rest_adapter is None or _credential_changed(_bz_rest_adapter_key, cfg.benzinga_api_key):
            from .ingest_benzinga import BenzingaRestAdapter
            if _bz_rest_adapter is not None and hasattr(_bz_rest_adapter, "close"):
                try:
                    _bz_rest_adapter.close()
                except Exception:
                    logger.debug("bz rest adapter close on rotation failed", exc_info=True)
            _bz_rest_adapter = BenzingaRestAdapter(cfg.benzinga_api_key)
            _bz_rest_adapter_key = cfg.benzinga_api_key
    return _bz_rest_adapter


def _get_bz_ws_adapter(cfg: Config) -> Any:
    global _bz_ws_adapter, _bz_ws_adapter_key
    current_key = (
        cfg.benzinga_api_key,
        cfg.benzinga_ws_url,
        tuple(cfg.benzinga_channels) if cfg.benzinga_channels else None,
    )
    with _init_lock:
        if _bz_ws_adapter is None or _credential_changed(_bz_ws_adapter_key, current_key):
            from .ingest_benzinga import BenzingaWsAdapter
            if _bz_ws_adapter is not None and hasattr(_bz_ws_adapter, "stop"):
                try:
                    _bz_ws_adapter.stop()
                except Exception:
                    logger.debug("bz ws adapter stop on rotation failed", exc_info=True)
            _bz_ws_adapter = BenzingaWsAdapter(
                cfg.benzinga_api_key,
                cfg.benzinga_ws_url,
                channels=cfg.benzinga_channels or None,
            )
            _bz_ws_adapter.start()
            _bz_ws_adapter_key = current_key
    return _bz_ws_adapter


def _get_bz_rss_adapter() -> Any:
    """Lazy-init the free Benzinga RSS adapter (no API key needed)."""
    global _bz_rss_adapter
    with _init_lock:
        if _bz_rss_adapter is None:
            from .ingest_benzinga import BenzingaRssAdapter
            _bz_rss_adapter = BenzingaRssAdapter()
    return _bz_rss_adapter


def _get_enricher() -> Enricher:
    global _enricher
    with _init_lock:
        if _enricher is None:
            _enricher = Enricher()
    return _enricher


# ── Helpers ─────────────────────────────────────────────────────

def load_universe(path: str) -> set[str]:
    """Load universe from a text file (one ticker per line)."""
    try:
        with open(path, encoding="utf-8") as f:
            universe = {
                line.strip().upper()
                for line in f
                if line.strip() and not line.startswith("#")
            }
        if not universe:
            logger.warning("Universe file %s is empty — universe filter disabled.", path)
        return universe
    except FileNotFoundError:
        logger.info("Universe file %s not found — optional universe filter disabled.", path)
        return set()


def vwap_gate_stub(ticker: str) -> dict[str, Any]:
    """Hook: later plug your VWAP reclaim detector here."""
    return {"vwap_signal": "NA", "vwap_reclaim_go": False, "vwap_bias_up": None}


def _fetch_cached_provider_items(
    *,
    cfg: Config,
    provider: str,
    min_cursor: float,
    scope: dict[str, Any],
    fetcher: Any,
    cache_owner: Any | None = None,
) -> CachedNewsBatch:
    ttl_seconds = cfg.shared_news_cache_ttl_seconds
    if cache_owner is not None and type(cache_owner).__module__.startswith("unittest.mock"):
        ttl_seconds = -1.0
    return fetch_cached_batch(
        provider=provider,
        scope=scope,
        ttl_seconds=ttl_seconds,
        min_cursor=min_cursor,
        fetcher=fetcher,
        cache_dir=cfg.shared_news_cache_dir,
    )


def _fetch_tradingview_provider_items(
    *,
    cfg: Config,
    symbols: list[str],
    min_cursor: float,
) -> CachedNewsBatch:
    from terminal_tradingview_news import fetch_tv_multi

    limited_symbols = list(symbols[: max(cfg.tv_symbol_limit, 0)]) if cfg.tv_symbol_limit > 0 else list(symbols)
    return _fetch_cached_provider_items(
        cfg=cfg,
        provider="tradingview",
        min_cursor=min_cursor,
        scope={
            "symbols": limited_symbols,
            "max_per_ticker": cfg.tv_max_per_ticker,
            "max_total": cfg.tv_max_total,
        },
        fetcher=lambda: [
            tv_headline_to_news_item(headline)
            for headline in fetch_tv_multi(
                limited_symbols,
                max_per_ticker=cfg.tv_max_per_ticker,
                max_total=cfg.tv_max_total,
            )
        ],
    )


def _fetch_newsapi_provider_items(
    *,
    cfg: Config,
    symbols: list[str],
    min_cursor: float,
    article_feed_after_uri: str = "",
) -> CachedNewsBatch:
    from scripts.smc_newsapi_ai import fetch_newsapi_records

    return _fetch_cached_provider_items(
        cfg=cfg,
        provider="newsapi_ai",
        min_cursor=min_cursor,
        scope={
            "symbols": list(symbols),
            "lookback_days": cfg.newsapi_ai_lookback_days,
            "articles_per_request": cfg.newsapi_ai_articles_per_request,
            "include_events": True,
            "article_feed_after_uri": article_feed_after_uri.strip(),
        },
        fetcher=lambda: [
            normalize_newsapi_ai(article)
            for article in fetch_newsapi_records(
                cfg.newsapi_ai_key,
                symbols,
                lookback_days=cfg.newsapi_ai_lookback_days,
                articles_per_request=cfg.newsapi_ai_articles_per_request,
                prefer_article_feed=min_cursor > 0.0,
                article_feed_after_epoch=min_cursor,
                article_feed_after_uri=article_feed_after_uri,
            )
        ],
    )


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


def _newsapi_item_matches_universe(item: NewsItem, universe: set[str]) -> bool:
    if not item.is_valid or not universe:
        return False
    return any(
        str(ticker or "").strip().upper() in universe
        for ticker in item.tickers or []
    )


def _newsapi_operator_status(
    *,
    cursor: float,
    raw_items: list[NewsItem],
    filtered_items: list[NewsItem],
    universe: set[str],
) -> tuple[str, str]:
    if any(_newsapi_item_matches_universe(item, universe) for item in filtered_items):
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


def _filter_new_by_watermark(
    items: Iterable[Any],
    last_seen_epoch: float | None,
    get_epoch: Callable[[Any], float | None],
) -> list:
    """Inclusive (``>=``) watermark filter — single source of truth.

    Audit-fix-followup-2 (2026-05-10): consolidates the 5 watermark sites
    (UW news + FMP senate/house/8K/13F) onto one helper so the inclusivity
    invariant is unit-testable in one place and cannot regress per-site.

    Mirrors prior fixes:

    - F5 (2026-05-10, PR #2119): UW news ``>`` → ``>=``.
    - 2026-05-09: FMP senate/house/8K/13F ``>`` → ``>=``.

    ``mark_seen()`` remains the authoritative per-item dedup, so the
    watermark only needs to bracket the candidate window inclusively.

    Args:
        items: iterable of records (typically NewsItem instances).
        last_seen_epoch: int/float epoch, or ``None`` to disable filtering
            (returns all items — used on the very first poll).
        get_epoch: callable mapping a record to its epoch (or ``None`` to
            drop the record from the result).

    Returns:
        List of records with ``epoch >= last_seen_epoch``.
    """
    if last_seen_epoch is None:
        return [it for it in items if get_epoch(it) is not None]
    out: list = []
    for it in items:
        ep = get_epoch(it)
        if ep is None:
            continue
        if ep >= last_seen_epoch:  # inclusive — see audit-fix-followup-2
            out.append(it)
    return out


def _filter_uw_news_new(items: list, last_seen: float) -> list:
    """Filter UW news items newer-or-equal-to the watermark.

    Thin wrapper around :func:`_filter_new_by_watermark` preserved for
    backwards-compat with the existing UW regression test
    (``test_uw_watermark_is_inclusive_for_same_epoch``).
    """
    return _filter_new_by_watermark(items, last_seen, lambda it: it.updated_ts)


# ── Core: process a batch of NewsItem objects ───────────────────

def process_news_items(
    store: SqliteStore,
    items: list[NewsItem],
    best_by_ticker: dict[str, dict[str, Any]],
    universe: set[str] | None,
    enricher: Enricher,
    enrich_threshold: float,
    last_seen_epoch: float = 0.0,
    enrich_budget: int = 3,
    _shared_enrich_counter: list[int] | None = None,
    _enriched_clusters: dict[str, dict[str, Any]] | None = None,
) -> tuple[float, int]:
    """Dedupe → novelty → score → enrich a batch of :class:`NewsItem`.

    Returns ``(max_ts, enrich_used)`` — the maximum ``updated_ts`` seen
    (for cursor advancement) and the number of enrichment HTTP calls made.

    *_shared_enrich_counter*: if provided, a single-element ``[int]`` list
    that is incremented on each enrichment call.  Survives exceptions so
    the budget is correctly shared across batches even on partial failure.

    *_enriched_clusters* (cross-provider hard-dedup, 2026-05-09): if
    provided, a dict keyed by ``chash`` storing the first enrichment
    result + score metadata seen for that cluster within the current
    poll cycle. Subsequent items sharing a chash skip the enrichment
    HTTP call and reuse the stored snippet.  Saves quota when the same
    story arrives via FMP + Benzinga + UW + NewsAPI.ai in one cycle.
    Provider-agnostic: ``cluster_hash`` already excludes provider.
    Pass the same dict to both calls in ``poll_once`` to dedup across
    fmp_items vs other_items batches.
    """
    max_ts = last_seen_epoch
    enrich_count = 0
    if _shared_enrich_counter is None:
        _shared_enrich_counter = [0]
    if _enriched_clusters is None:
        _enriched_clusters = {}

    for it in items:
        # Lens 1 (silent-degradation v2): isolate per-item failures so a
        # single bad item (DB locked, scoring crash, malformed payload)
        # does not silently drop the remainder of the batch. exc_info=True
        # preserves the traceback for diagnosis while continuing the loop.
        marked_seen = False
        try:
            if not it.is_valid:
                continue

            # Determine effective timestamp.  _to_epoch returns 0.0 for
            # missing/unparseable dates — fall back to time.time() for
            # processing but do NOT let synthetic timestamps advance the cursor.
            raw_ts = it.updated_ts or it.published_ts
            has_real_ts = raw_ts is not None and raw_ts > 0
            ts = raw_ts if has_real_ts else time.time()

            # Cursor check: skip items older than last seen for this provider.
            # Use strict < so items sharing the cursor timestamp are not dropped;
            # mark_seen() is the authoritative dedup.
            if ts < last_seen_epoch:
                continue

            # Only advance cursor with real (non-synthetic) timestamps
            if has_real_ts:
                max_ts = max(max_ts, ts)

            # Dedup (provider, item_id)
            if not store.mark_seen(it.provider, it.item_id, ts):
                continue
            # Track for rollback: if classification/enrich/best_by_ticker
            # raises below, we must unmark to keep the item retriable.
            marked_seen = True

            # Tickers + universe filter (deduplicate to avoid redundant per-ticker work)
            tickers = [t for t in (it.tickers or []) if isinstance(t, str) and t.strip()]
            tickers = list(dict.fromkeys(t.strip().upper() for t in tickers))
            if universe:
                tickers = [t for t in tickers if t in universe]
                if not tickers:
                    continue

            if not it.headline.strip():
                continue

            # Novelty cluster -- compute hash once, reuse in scorer
            chash = cluster_hash(it.headline or "", it.tickers or [])
            cluster_count, _ = store.cluster_touch(chash, ts)
            score = classify_and_score(it, cluster_count=cluster_count, chash=chash)

            warn_flags: list[str] = []
            if score.category == "offering":
                warn_flags.append("offering_risk")
            if score.category == "lawsuit":
                warn_flags.append("likely_noise")

            # Enrich high-score items once per item (budget shared across calls).
            # Hoisted above the per-ticker loop to avoid redundant HTTP calls
            # when one item maps to multiple tickers.
            #
            # Cross-provider hard-dedup (2026-05-09): if the same cluster
            # (chash) was already enriched in this poll cycle by another
            # provider, reuse the snippet and skip the HTTP call. cluster_hash
            # is provider-independent so FMP+Benzinga+UW+NewsAPI.ai variants
            # of the same story share a chash.
            enrich_result = None
            cluster_dedup_hit = False
            if chash in _enriched_clusters:
                enrich_result = _enriched_clusters[chash].get("enrich_result")
                cluster_dedup_hit = True
            elif score.score >= enrich_threshold and _shared_enrich_counter[0] < enrich_budget:
                enrich_result = enricher.fetch_url_snippet(it.url)
                enrich_count += 1
                _shared_enrich_counter[0] += 1
                _enriched_clusters[chash] = {"enrich_result": enrich_result, "ts": ts}

            # Build candidate per ticker
            for tk in tickers:
                vwap = vwap_gate_stub(tk)

                cand: dict[str, Any] = {
                    "ticker": tk,
                    "headline": it.headline[:260],
                    "snippet": (it.snippet or "")[:260],
                    "news_provider": it.provider,
                    "news_source": it.source,
                    "news_url": it.url,
                    "category": score.category,
                    "impact": round(score.impact, 3),
                    "clarity": round(score.clarity, 3),
                    "novelty_cluster_count": int(cluster_count),
                    "polarity": score.polarity,
                    "news_score": round(score.score, 4),
                    "warn_flags": list(warn_flags),
                    "signals": {"vwap": vwap},
                    "published_ts": it.published_ts,
                    "updated_ts": it.updated_ts,
                    "_seen_ts": ts,
                    "cluster_dedup": bool(cluster_dedup_hit),
                }

                if enrich_result is not None:
                    cand["enrich"] = dict(enrich_result)

                # Keep best per ticker
                with _bbt_lock:
                    prev = best_by_ticker.get(tk)
                    if (prev is None) or (cand["news_score"] > prev["news_score"]) or (
                        cand["news_score"] == prev["news_score"]
                        and cand.get("updated_ts", 0) > prev.get("updated_ts", 0)
                    ):
                        best_by_ticker[tk] = cand
        except Exception as exc:
            if marked_seen:
                # Roll back the dedup commit so a transient failure does
                # not turn into permanent data loss on the next poll cycle.
                try:
                    store.unmark_seen(it.provider, it.item_id)
                except Exception:
                    logger.exception(
                        "process_news_items: unmark_seen rollback failed for %s/%s",
                        getattr(it, "provider", "?"),
                        getattr(it, "item_id", "?"),
                    )
            logger.warning(
                "process_news_items: skipping item provider=%s id=%s due to %s",
                getattr(it, "provider", "?"),
                getattr(it, "item_id", "?"),
                type(exc).__name__,
                exc_info=True,
            )
            continue

    return max_ts, enrich_count


# ── Core single-cycle poll ──────────────────────────────────────

def poll_once(
    cfg: Config | None = None,
    universe: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Run one poll cycle (synchronous).  Returns scored candidates.

    Called from Streamlit on each refresh.  State is persisted in SQLite
    so cursors / dedup / novelty survive across refreshes.

    Polls all enabled sources (FMP, Benzinga REST, Benzinga WS queue)
    and feeds them through ``process_news_items()``.

    Parameters
    ----------
    cfg : Config, optional
        Configuration.  Defaults to ``Config()`` (reads env vars).
    universe : set[str], optional
        Pre-loaded universe set.  If ``None`` and ``cfg.filter_to_universe``
        is True, the universe is loaded from ``cfg.universe_path``.

    Returns
    -------
    list[dict]
        Scored news candidates, sorted by ``news_score`` descending.
    """
    if cfg is None:
        cfg = Config()

    store = _get_store(cfg)
    enricher = _get_enricher()

    if universe is None and cfg.filter_to_universe:
        universe = load_universe(cfg.universe_path)

    # ── Provider cursors (persisted in SQLite KV) ───────────────
    fmp_legacy_last = float(store.get_kv("fmp.last_seen_epoch") or "0")
    fmp_stock_last = float(store.get_kv("fmp.stock.last_seen_epoch") or fmp_legacy_last or 0.0)
    fmp_press_last = float(store.get_kv("fmp.press.last_seen_epoch") or fmp_legacy_last or 0.0)
    fmp_articles_last = float(store.get_kv("fmp.articles.last_seen_epoch") or 0.0)
    bz_rest_cursor = float(store.get_kv("benzinga.updatedSince") or "0")
    bz_rss_last_seen = float(store.get_kv("benzinga_rss.last_seen_epoch") or "0")
    tv_last_seen = float(store.get_kv("tradingview.last_seen_epoch") or "0")
    newsapi_last_seen = float(store.get_kv("newsapi_ai.last_seen_epoch") or "0")
    newsapi_last_seen_uri = str(store.get_kv("newsapi_ai.last_seen_news_uri") or "").strip()
    uw_news_last_seen = float(store.get_kv("uw_news.last_seen_epoch") or "0")
    # PR3: FMP extras cursors
    fmp_general_last = float(store.get_kv("fmp.general.last_seen_epoch") or "0")
    fmp_senate_last = float(store.get_kv("fmp.senate.last_seen_epoch") or "0")
    fmp_house_last = float(store.get_kv("fmp.house.last_seen_epoch") or "0")
    fmp_8k_last = float(store.get_kv("fmp.8k.last_seen_epoch") or "0")
    fmp_13f_last = float(store.get_kv("fmp.13f.last_seen_epoch") or "0")

    cycle_warnings: list[str] = []
    universe_symbols = sorted(universe) if universe else []
    fmp_items: list[NewsItem] = []
    other_items: list[NewsItem] = []
    new_fmp_stock_max = fmp_stock_last
    new_fmp_press_max = fmp_press_last
    new_fmp_articles_max = fmp_articles_last
    new_bz_rest_max = bz_rest_cursor
    new_bz_rss_max = bz_rss_last_seen
    new_tv_max = tv_last_seen
    new_newsapi_max = newsapi_last_seen
    new_newsapi_uri = newsapi_last_seen_uri
    new_uw_news_max = uw_news_last_seen
    # PR3: FMP extras cursor maxes
    new_fmp_general_max = fmp_general_last
    new_fmp_senate_max = fmp_senate_last
    new_fmp_house_max = fmp_house_last
    new_fmp_8k_max = fmp_8k_last
    new_fmp_13f_max = fmp_13f_last
    newsapi_provider_meta: dict[str, str] | None = None
    ingest_counts_by_source: dict[str, int] = {}

    def _sanitize_exc(exc: Exception) -> str:
        return re.sub(r"(apikey|api_key|token|key)=[^&\s]+", r"\1=***", str(exc), flags=re.IGNORECASE)

    # ── 1) FMP poll ─────────────────────────────────────────────
    if cfg.enable_fmp and cfg.fmp_api_key:
        fmp = _get_fmp_adapter(cfg)
        try:
            stock_batch = _fetch_cached_provider_items(
                cfg=cfg,
                provider="fmp_stock_latest",
                min_cursor=fmp_stock_last,
                scope={"page": cfg.stock_latest_page, "limit": cfg.stock_latest_limit},
                fetcher=lambda: fmp.fetch_stock_latest(cfg.stock_latest_page, cfg.stock_latest_limit),
                cache_owner=fmp,
            )
            fmp_items.extend(stock_batch.items)
            new_fmp_stock_max = stock_batch.cursor
            ingest_counts_by_source["fmp_stock_latest"] = stock_batch.raw_count
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("FMP stock-latest fetch failed: %s", _msg)
            cycle_warnings.append(f"fmp_stock_latest: {_msg}")
        try:
            press_batch = _fetch_cached_provider_items(
                cfg=cfg,
                provider="fmp_press_latest",
                min_cursor=fmp_press_last,
                scope={"page": cfg.press_latest_page, "limit": cfg.press_latest_limit},
                fetcher=lambda: fmp.fetch_press_latest(cfg.press_latest_page, cfg.press_latest_limit),
                cache_owner=fmp,
            )
            fmp_items.extend(press_batch.items)
            new_fmp_press_max = press_batch.cursor
            ingest_counts_by_source["fmp_press_latest"] = press_batch.raw_count
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("FMP press-latest fetch failed: %s", _msg)
            cycle_warnings.append(f"fmp_press_latest: {_msg}")
        if cfg.enable_fmp_articles:
            try:
                articles_batch = _fetch_cached_provider_items(
                    cfg=cfg,
                    provider="fmp_articles",
                    min_cursor=fmp_articles_last,
                    scope={"limit": cfg.fmp_articles_limit},
                    fetcher=lambda: fmp.fetch_articles(cfg.fmp_articles_limit),
                    cache_owner=fmp,
                )
                fmp_items.extend(articles_batch.items)
                new_fmp_articles_max = articles_batch.cursor
                ingest_counts_by_source["fmp_articles"] = articles_batch.raw_count
            except Exception as exc:
                _msg = _sanitize_exc(exc)
                logger.warning("FMP articles fetch failed: %s", _msg)
                cycle_warnings.append(f"fmp_articles: {_msg}")
        # B4 (PR3 2026-05-09): FMP /news/general-latest — macro / market-wide news
        if cfg.enable_fmp_general:
            try:
                general_batch = _fetch_cached_provider_items(
                    cfg=cfg,
                    provider="fmp_general_latest",
                    min_cursor=fmp_general_last,
                    scope={"page": cfg.fmp_general_page, "limit": cfg.fmp_general_limit},
                    fetcher=lambda: fmp.fetch_general_latest(
                        cfg.fmp_general_page, cfg.fmp_general_limit
                    ),
                    cache_owner=fmp,
                )
                fmp_items.extend(general_batch.items)
                new_fmp_general_max = general_batch.cursor
                ingest_counts_by_source["fmp_general_latest"] = general_batch.raw_count
            except Exception as exc:
                _msg = _sanitize_exc(exc)
                logger.warning("FMP general-latest fetch failed: %s", _msg)
                cycle_warnings.append(f"fmp_general_latest: {_msg}")

    # ── 2) Benzinga REST delta ──────────────────────────────────
    bz_rest_items: list[NewsItem] = []
    if cfg.enable_benzinga_rest and cfg.benzinga_api_key:
        bz_rest = _get_bz_rest_adapter(cfg)
        try:
            benzinga_batch = _fetch_cached_provider_items(
                cfg=cfg,
                provider="benzinga_rest",
                min_cursor=bz_rest_cursor,
                scope={
                    "page_size": cfg.benzinga_rest_page_size,
                    "channels": cfg.benzinga_channels,
                    "topics": cfg.benzinga_topics,
                },
                fetcher=lambda: bz_rest.fetch_news(
                    updated_since=None,
                    page_size=cfg.benzinga_rest_page_size,
                    channels=cfg.benzinga_channels or None,
                    topics=cfg.benzinga_topics or None,
                ),
                cache_owner=bz_rest,
            )
            bz_rest_items = benzinga_batch.items
            new_bz_rest_max = benzinga_batch.cursor
            ingest_counts_by_source["benzinga_rest"] = benzinga_batch.raw_count
            other_items.extend(bz_rest_items)
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("Benzinga REST fetch failed: %s", _msg)
            cycle_warnings.append(f"benzinga_rest: {_msg}")

    # ── 2.4b) Benzinga RSS (free, no key) ───────────────────────
    if cfg.enable_benzinga_rss:
        try:
            bz_rss = _get_bz_rss_adapter()
            bz_rss_items = bz_rss.fetch_news(min_epoch=bz_rss_last_seen)
            bz_rss_new = [it for it in bz_rss_items if it.is_valid]
            # Use published_ts for the watermark because the RSS adapter
            # filters items by published_ts >= min_epoch.  updated_ts may
            # reflect a later edit and would cause us to skip new items.
            new_bz_rss_max = max(
                (it.published_ts for it in bz_rss_new),
                default=bz_rss_last_seen,
            )
            ingest_counts_by_source["benzinga_rss"] = len(bz_rss_items)
            other_items.extend(bz_rss_new)
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("Benzinga RSS fetch failed: %s", _msg)
            cycle_warnings.append(f"benzinga_rss: {_msg}")

    # ── 2.5) Unusual Whales /news/headlines (B1+B2+B3, PR2 2026-05-09) ─
    # Default-OFF via ENABLE_UW_NEWS=1.  DISABLED-pattern in the adapter
    # auto-suppresses subsequent calls if the endpoint returns 401/403/404.
    # Items flow via other_items so they share PR1's cross-provider hard-
    # dedup cache (cluster_hash is provider-agnostic).
    if cfg.enable_uw_news and is_uw_configured():
        try:
            uw_raw = fetch_uw_news_headlines(
                os.getenv("UNUSUAL_WHALES_API_KEY", ""),
                limit=cfg.uw_news_limit,
            )
            uw_news_items = [normalize_uw_news_headline(rec) for rec in uw_raw]
            uw_news_items = [it for it in uw_news_items if it.is_valid]
            uw_news_new = _filter_uw_news_new(uw_news_items, uw_news_last_seen)
            new_uw_news_max = max(
                (it.updated_ts for it in uw_news_new),
                default=uw_news_last_seen,
            )
            ingest_counts_by_source["uw_news"] = len(uw_raw)
            other_items.extend(uw_news_new)
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("UW news/headlines fetch failed: %s", _msg)
            cycle_warnings.append(f"uw_news: {_msg}")

    # ── 2.6) FMP Senate trades (B5, PR3 2026-05-09) ──────────
    # Default-OFF; DISABLED-pattern in adapter auto-suppresses 401/403/404.
    if cfg.enable_fmp_senate_trades and cfg.fmp_api_key:
        try:
            senate_raw: list[dict] = []
            for page in range(max(1, cfg.fmp_political_pages)):
                page_raw = fetch_fmp_senate_trades(cfg.fmp_api_key, page=page)
                if not page_raw:
                    break
                senate_raw.extend(page_raw)
            senate_items = [
                normalize_fmp_political_trade(rec, chamber="senate")
                for rec in senate_raw
            ]
            senate_items = [it for it in senate_items if it.is_valid]
            # Audit-fix-followup-2 (2026-05-10): consolidated >= filter; see
            # _filter_new_by_watermark. FMP returns date-only granularity for
            # senate/house, so inclusive avoids same-day drops.
            senate_new = _filter_new_by_watermark(
                senate_items, fmp_senate_last, lambda it: it.updated_ts
            )
            new_fmp_senate_max = max(
                (it.updated_ts for it in senate_new),
                default=fmp_senate_last,
            )
            ingest_counts_by_source["fmp_senate_trade"] = len(senate_raw)
            other_items.extend(senate_new)
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("FMP senate-trades fetch failed: %s", _msg)
            cycle_warnings.append(f"fmp_senate_trade: {_msg}")

    # ── 2.7) FMP House trades (B5, PR3 2026-05-09) ───────────
    if cfg.enable_fmp_house_trades and cfg.fmp_api_key:
        try:
            house_raw: list[dict] = []
            for page in range(max(1, cfg.fmp_political_pages)):
                page_raw = fetch_fmp_house_trades(cfg.fmp_api_key, page=page)
                if not page_raw:
                    break
                house_raw.extend(page_raw)
            house_items = [
                normalize_fmp_political_trade(rec, chamber="house")
                for rec in house_raw
            ]
            house_items = [it for it in house_items if it.is_valid]
            # Audit-fix-followup-2 (2026-05-10): consolidated >= filter.
            house_new = _filter_new_by_watermark(
                house_items, fmp_house_last, lambda it: it.updated_ts
            )
            new_fmp_house_max = max(
                (it.updated_ts for it in house_new),
                default=fmp_house_last,
            )
            ingest_counts_by_source["fmp_house_trade"] = len(house_raw)
            other_items.extend(house_new)
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("FMP house-trades fetch failed: %s", _msg)
            cycle_warnings.append(f"fmp_house_trade: {_msg}")

    # ── 2.8) FMP SEC 8-K filings (B7, PR3 2026-05-09) ──────────
    if cfg.enable_fmp_8k and cfg.fmp_api_key:
        try:
            eight_k_raw = fetch_fmp_8k_latest(
                cfg.fmp_api_key, page=0, limit=cfg.fmp_8k_limit
            )
            eight_k_items = [
                normalize_fmp_filing_8k(rec) for rec in eight_k_raw
            ]
            eight_k_items = [it for it in eight_k_items if it.is_valid]
            # Audit-fix-followup-2 (2026-05-10): consolidated >= filter.
            eight_k_new = _filter_new_by_watermark(
                eight_k_items, fmp_8k_last, lambda it: it.updated_ts
            )
            new_fmp_8k_max = max(
                (it.updated_ts for it in eight_k_new),
                default=fmp_8k_last,
            )
            ingest_counts_by_source["fmp_8k_latest"] = len(eight_k_raw)
            other_items.extend(eight_k_new)
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("FMP 8-K-latest fetch failed: %s", _msg)
            cycle_warnings.append(f"fmp_8k_latest: {_msg}")

    # ── 2.9) FMP SEC 13F-HR filings (B6, PR5 2026-05-09) ───────
    if cfg.enable_fmp_13f and cfg.fmp_api_key:
        try:
            thirteen_f_raw = fetch_fmp_13f_latest(
                cfg.fmp_api_key, page=0, limit=cfg.fmp_13f_limit
            )
            thirteen_f_items = [
                normalize_fmp_filing_13f(rec) for rec in thirteen_f_raw
            ]
            thirteen_f_items = [it for it in thirteen_f_items if it.is_valid]
            # Audit-fix-followup-2 (2026-05-10): consolidated >= filter.
            thirteen_f_new = _filter_new_by_watermark(
                thirteen_f_items, fmp_13f_last, lambda it: it.updated_ts
            )
            new_fmp_13f_max = max(
                (it.updated_ts for it in thirteen_f_new),
                default=fmp_13f_last,
            )
            ingest_counts_by_source["fmp_13f_latest"] = len(thirteen_f_raw)
            other_items.extend(thirteen_f_new)
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("FMP 13F-HR-latest fetch failed: %s", _msg)
            cycle_warnings.append(f"fmp_13f_latest: {_msg}")

    # ── 3) Symbol-scoped providers (TradingView + NewsAPI.ai) ──
    if universe_symbols:
        if cfg.enable_tradingview_news:
            try:
                tv_batch = _fetch_tradingview_provider_items(
                    cfg=cfg,
                    symbols=universe_symbols,
                    min_cursor=tv_last_seen,
                )
                other_items.extend(tv_batch.items)
                new_tv_max = tv_batch.cursor
                ingest_counts_by_source["tradingview"] = tv_batch.raw_count
            except Exception as exc:
                _msg = _sanitize_exc(exc)
                logger.warning("TradingView news fetch failed: %s", _msg)
                cycle_warnings.append(f"tradingview: {_msg}")

        if cfg.enable_newsapi_ai and cfg.newsapi_ai_key:
            try:
                newsapi_batch = _fetch_newsapi_provider_items(
                    cfg=cfg,
                    symbols=universe_symbols,
                    min_cursor=newsapi_last_seen,
                    article_feed_after_uri=newsapi_last_seen_uri,
                )
                other_items.extend(newsapi_batch.items)
                new_newsapi_max = newsapi_batch.cursor
                new_newsapi_uri = _next_newsapi_feed_uri(
                    newsapi_last_seen_uri,
                    newsapi_batch.items,
                    cursor_advanced=newsapi_batch.cursor > newsapi_last_seen,
                )
                newsapi_provider_status, newsapi_status_detail = _newsapi_operator_status(
                    cursor=newsapi_batch.cursor,
                    raw_items=newsapi_batch.raw_items,
                    filtered_items=newsapi_batch.items,
                    universe=set(universe_symbols),
                )
                newsapi_provider_meta = {
                    "provider_status": newsapi_provider_status,
                    "status_detail": newsapi_status_detail,
                }
                ingest_counts_by_source["newsapi_ai"] = newsapi_batch.raw_count
            except Exception as exc:
                _msg = _sanitize_exc(exc)
                logger.warning("NewsAPI.ai fetch failed: %s", _msg)
                newsapi_provider_meta = {
                    "provider_status": str(getattr(exc, "provider_status", "http_error") or "http_error"),
                    "status_detail": str(getattr(exc, "detail", "") or _msg),
                }
                cycle_warnings.append(f"newsapi_ai: {_msg}")

    # ── 4) Benzinga WS drain ────────────────────────────────────
    if cfg.enable_benzinga_ws and cfg.benzinga_api_key:
        bz_ws = _get_bz_ws_adapter(cfg)
        try:
            ws_items = bz_ws.drain()
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("Benzinga WebSocket drain failed: %s — continuing without WS items", _msg)
            ws_items = []
            cycle_warnings.append(f"benzinga_ws: {_msg}")
        other_items.extend(ws_items)
        ingest_counts_by_source["benzinga_ws"] = len([item for item in ws_items if item.is_valid])
        if ws_items:
            logger.info("Drained %d items from Benzinga WS queue.", len(ws_items))

    # ── 5) Process all items through unified pipeline ───────────
    _enrich_ctr: list[int] = [0]  # mutable counter survives exceptions
    # Cross-provider hard-dedup: shared across both batches so the same
    # cluster (chash) seen via FMP and via Benzinga/UW/NewsAPI.ai in the
    # same poll cycle only triggers ONE enrichment HTTP call.
    _enriched_clusters: dict[str, dict[str, Any]] = {}
    fmp_processing_ok = False
    try:
        processed_fmp_max, _fmp_enrich_used = process_news_items(
            store, fmp_items, _best_by_ticker, universe, enricher,
            cfg.score_enrich_threshold, last_seen_epoch=0.0,
            _shared_enrich_counter=_enrich_ctr,
            _enriched_clusters=_enriched_clusters,
        )
        fmp_processing_ok = True
    except Exception as exc:
        _msg = _sanitize_exc(exc)
        logger.warning("process_news_items(fmp) failed: %s", _msg)
        cycle_warnings.append(f"process_fmp: {_msg}")
        processed_fmp_max = 0.0

    other_processing_ok = False
    try:
        process_news_items(
            store, other_items, _best_by_ticker, universe, enricher,
            cfg.score_enrich_threshold, last_seen_epoch=0.0,
            # Audit-fix (2026-05-09): absolute cap of 3 (was relative
            # `max(0, 3 - _enrich_ctr[0])` which under-budgeted the
            # other-provider batch when fmp had already consumed enrichments).
            enrich_budget=3,
            _shared_enrich_counter=_enrich_ctr,
            _enriched_clusters=_enriched_clusters,
        )
        other_processing_ok = True
    except Exception as exc:
        _msg = _sanitize_exc(exc)
        logger.warning("process_news_items(other) failed: %s", _msg)
        cycle_warnings.append(f"process_other: {_msg}")

    # ── 6) Update cursors ───────────────────────────────────────
    combined_fmp_max = max(new_fmp_stock_max, new_fmp_press_max, new_fmp_articles_max, new_fmp_general_max, processed_fmp_max, fmp_legacy_last)
    if fmp_processing_ok:
        if new_fmp_stock_max > fmp_stock_last:
            store.set_kv("fmp.stock.last_seen_epoch", str(new_fmp_stock_max))
        if new_fmp_press_max > fmp_press_last:
            store.set_kv("fmp.press.last_seen_epoch", str(new_fmp_press_max))
        if new_fmp_articles_max > fmp_articles_last:
            store.set_kv("fmp.articles.last_seen_epoch", str(new_fmp_articles_max))
        if new_fmp_general_max > fmp_general_last:
            store.set_kv("fmp.general.last_seen_epoch", str(new_fmp_general_max))
        if combined_fmp_max > fmp_legacy_last:
            store.set_kv("fmp.last_seen_epoch", str(combined_fmp_max))

    if bz_rest_items and other_processing_ok:
        if new_bz_rest_max > bz_rest_cursor:
            store.set_kv("benzinga.updatedSince", str(int(new_bz_rest_max)))
        else:
            logger.warning(
                "Benzinga REST: all %d items lack timestamps — cursor NOT advanced.",
                len(bz_rest_items),
            )
    if other_processing_ok and new_bz_rss_max > bz_rss_last_seen:
        store.set_kv("benzinga_rss.last_seen_epoch", str(new_bz_rss_max))
    if other_processing_ok and new_tv_max > tv_last_seen:
        store.set_kv("tradingview.last_seen_epoch", str(new_tv_max))
    if other_processing_ok and new_newsapi_max > newsapi_last_seen:
        store.set_kv("newsapi_ai.last_seen_epoch", str(new_newsapi_max))
    if other_processing_ok and new_newsapi_uri != newsapi_last_seen_uri:
        store.set_kv("newsapi_ai.last_seen_news_uri", new_newsapi_uri)
    if other_processing_ok and new_uw_news_max > uw_news_last_seen:
        store.set_kv("uw_news.last_seen_epoch", str(new_uw_news_max))
    # PR3: FMP political/filings cursor writes
    if other_processing_ok and new_fmp_senate_max > fmp_senate_last:
        store.set_kv("fmp.senate.last_seen_epoch", str(new_fmp_senate_max))
    if other_processing_ok and new_fmp_house_max > fmp_house_last:
        store.set_kv("fmp.house.last_seen_epoch", str(new_fmp_house_max))
    if other_processing_ok and new_fmp_8k_max > fmp_8k_last:
        store.set_kv("fmp.8k.last_seen_epoch", str(new_fmp_8k_max))
    if other_processing_ok and new_fmp_13f_max > fmp_13f_last:
        store.set_kv("fmp.13f.last_seen_epoch", str(new_fmp_13f_max))

    # ── 7) Export ───────────────────────────────────────────────
    with _bbt_lock:
        candidates: list[dict[str, Any]] = list(_best_by_ticker.values())
    candidates.sort(
        key=lambda x: (x.get("news_score", 0), x.get("updated_ts", 0), x.get("ticker", "")),
        reverse=True,
    )
    candidates = candidates[: cfg.top_n_export]

    # Strip internal fields (prefixed with _) before exporting to JSON.
    # _seen_ts is used internally for pruning but must not leak into the
    # public data contract.  Deep-copy so nested mutable values (signals,
    # warn_flags, enrich) are fully detached from _best_by_ticker.
    export_candidates = [
        copy.deepcopy({k: v for k, v in c.items() if not k.startswith("_")})
        for c in candidates
    ]

    fmp_count = sum(1 for it in fmp_items if it.is_valid)
    bz_count = sum(1 for it in other_items if it.provider.startswith("benzinga") and it.is_valid)
    bz_rest_count = sum(1 for it in other_items if it.provider == "benzinga_rest" and it.is_valid)
    bz_rss_count = sum(1 for it in other_items if it.provider == "benzinga_rss" and it.is_valid)
    tv_count = sum(1 for it in other_items if (it.provider in ("tradingview", "tv_news") or it.provider.startswith("tv_")) and it.is_valid)
    newsapi_count = sum(1 for it in other_items if it.provider == "newsapi_ai" and it.is_valid)
    meta_sources: list[str] = []
    if cfg.enable_fmp:
        meta_sources.extend(["fmp_stock_latest", "fmp_press_latest"])
        if cfg.enable_fmp_articles:
            meta_sources.append("fmp_articles")
        # Audit-fix (2026-05-09): expose new FMP sources for telemetry.
        if cfg.enable_fmp_general:
            meta_sources.append("fmp_general_latest")
        # Copilot follow-up (2026-05-09): use singular provider labels to match
        # normalize_fmp_political_trade / Config.active_sources / ingest_counts_by_source.
        if cfg.enable_fmp_senate_trades and cfg.fmp_api_key:
            meta_sources.append("fmp_senate_trade")
        if cfg.enable_fmp_house_trades and cfg.fmp_api_key:
            meta_sources.append("fmp_house_trade")
        if cfg.enable_fmp_8k and cfg.fmp_api_key:
            meta_sources.append("fmp_8k_latest")
        if cfg.enable_fmp_13f and cfg.fmp_api_key:
            meta_sources.append("fmp_13f_latest")
    if cfg.enable_benzinga_rest:
        meta_sources.append("benzinga_rest")
    if cfg.enable_benzinga_rss:
        meta_sources.append("benzinga_rss")
    if cfg.enable_benzinga_ws:
        meta_sources.append("benzinga_ws")
    if cfg.enable_tradingview_news and universe_symbols:
        meta_sources.append("tradingview")
    if cfg.enable_newsapi_ai and cfg.newsapi_ai_key and universe_symbols:
        meta_sources.append("newsapi_ai")
    # Audit-fix (2026-05-09): UW news source telemetry.
    if cfg.enable_uw_news and is_uw_configured():
        meta_sources.append("uw_news")
    meta: dict[str, Any] = {
        "generated_ts": time.time(),
        "cursor": {
            "fmp_last_seen_epoch": combined_fmp_max,
            "fmp_stock_last_seen_epoch": new_fmp_stock_max,
            "fmp_press_last_seen_epoch": new_fmp_press_max,
            "fmp_articles_last_seen_epoch": new_fmp_articles_max,
            "benzinga_updatedSince": store.get_kv("benzinga.updatedSince"),
            "benzinga_rss_last_seen_epoch": store.get_kv("benzinga_rss.last_seen_epoch"),
            "tradingview_last_seen_epoch": store.get_kv("tradingview.last_seen_epoch"),
            "newsapi_ai_last_seen_epoch": store.get_kv("newsapi_ai.last_seen_epoch"),
            "newsapi_ai_last_seen_news_uri": store.get_kv("newsapi_ai.last_seen_news_uri"),
        },
        "poll_interval_s": cfg.poll_interval_s,
        "universe_size": len(universe) if universe else None,
        "sources": meta_sources,
        "ingest_counts": {
            "fmp": fmp_count,
            "benzinga": bz_count,
            "benzinga_rest": bz_rest_count,
            "benzinga_rss": bz_rss_count,
            "tradingview": tv_count,
            "newsapi_ai": newsapi_count,
        },
        "ingest_counts_by_source": ingest_counts_by_source,
        "total_candidates": len(candidates),
        "warnings": cycle_warnings,
    }
    if newsapi_provider_meta is not None:
        meta["providers"] = {"newsapi_ai": newsapi_provider_meta}
    # ── Benzinga RSS provider state ──────────────────────────────────
    if cfg.enable_benzinga_rss:
        _bz = _bz_rss_adapter
        if _bz is not None:
            meta.setdefault("providers", {})["benzinga_rss"] = {
                "ok": _bz.fetch_total > 0 and _bz.fetch_errors == 0,
                "fetch_total": _bz.fetch_total,
                "fetch_errors": _bz.fetch_errors,
                "last_fetch_errors": _bz.last_fetch_errors,
                "items_parsed": _bz.items_parsed,
                "items_deduped": _bz.items_deduped,
                "bozo_total": _bz.bozo_total,
                "last_fetch_duration_s": round(_bz.last_fetch_duration, 3),
            }
    global _last_meta
    with _meta_lock:
        _last_meta = copy.deepcopy(meta)
    try:
        export_open_prep(cfg.export_path, export_candidates, meta)
    except Exception as exc:
        logger.warning("export_open_prep failed: %s", type(exc).__name__, exc_info=True)

    # ── 8) Prune old records + stale best_by_ticker entries ────
    store.prune_seen(cfg.keep_seen_seconds)
    store.prune_clusters(cfg.keep_clusters_seconds)
    _prune_best_by_ticker(cfg.keep_seen_seconds)

    logger.info(
        "newsstack poll: fmp=%d bz=%d → %d candidates",
        fmp_count, bz_count, len(candidates),
    )

    # Return copies (export_candidates) so callers cannot mutate
    # the internal _best_by_ticker state across poll cycles.
    return export_candidates


def get_last_meta() -> dict[str, Any]:
    """Return the last export metadata produced by ``poll_once``.

    A deep copy is returned so downstream consumers cannot mutate the
    poller's module-level state across Streamlit refreshes.
    """
    with _meta_lock:
        if _last_meta is None:
            return {}
        return copy.deepcopy(_last_meta)


def get_news_score(symbol: str) -> float:
    """Return the latest best-by-ticker news score for *symbol*.

    The Streamlit poller owns ``_best_by_ticker``; this read-only facade keeps
    bridge consumers off private module globals while preserving the existing
    best-effort ``0.0`` fallback when no recent candidate is available.
    """
    ticker = str(symbol or "").strip().upper()
    if not ticker:
        return 0.0
    with _bbt_lock:
        candidate = copy.deepcopy(_best_by_ticker.get(ticker))
    if not candidate:
        return 0.0
    try:
        return float(candidate.get("news_score") or 0.0)
    except (TypeError, ValueError):
        logger.debug("Invalid news_score for %s: %r", ticker, candidate.get("news_score"))
        return 0.0


def _effective_ts(cand: dict[str, Any]) -> float:
    """Return the best available timestamp for a candidate.

    Handles 0.0 timestamps correctly (Python ``or`` treats 0.0 as falsy).
    """
    ts = cand.get("updated_ts")
    if ts is not None and ts > 0:
        return float(ts)
    ts = cand.get("published_ts")
    if ts is not None and ts > 0:
        return float(ts)
    # Fallback: _seen_ts records when the pipeline first observed this
    # item.  Prevents zero-timestamp candidates from being pruned
    # immediately (0.0 is always < cutoff).
    return float(cand.get("_seen_ts", 0.0))


def _prune_best_by_ticker(keep_seconds: float) -> None:
    """Remove entries from ``_best_by_ticker`` older than *keep_seconds*."""
    cutoff = time.time() - keep_seconds
    with _bbt_lock:
        stale = [
            tk for tk, cand in _best_by_ticker.items()
            if _effective_ts(cand) < cutoff
        ]
        for tk in stale:
            del _best_by_ticker[tk]
    if stale:
        logger.debug("Pruned %d stale entries from best_by_ticker.", len(stale))


def _cleanup_singletons() -> None:
    """Close all module-level singleton resources."""
    global _store, _fmp_adapter, _bz_rest_adapter, _bz_rss_adapter, _bz_ws_adapter, _enricher, _last_meta
    global _fmp_adapter_key, _bz_rest_adapter_key, _bz_ws_adapter_key
    for obj in (_fmp_adapter, _bz_rest_adapter, _enricher):
        if obj is not None and hasattr(obj, "close"):
            try:
                obj.close()
            except Exception:
                logger.debug("singleton cleanup error", exc_info=True)
    if _bz_ws_adapter is not None and hasattr(_bz_ws_adapter, "stop"):
        try:
            _bz_ws_adapter.stop()
        except Exception:
            logger.debug("singleton cleanup error", exc_info=True)
    if _store is not None:
        try:
            _store.close()
        except Exception:
            logger.debug("singleton cleanup error", exc_info=True)
    with _bbt_lock:
        _best_by_ticker.clear()
    with _meta_lock:
        _last_meta = None
    _store = _fmp_adapter = _bz_rest_adapter = _bz_rss_adapter = _bz_ws_adapter = _enricher = None
    _fmp_adapter_key = _bz_rest_adapter_key = _bz_ws_adapter_key = None


import atexit as _atexit  # noqa: E402 -- late import for atexit cleanup hook registration after singleton helpers are defined

_atexit.register(_cleanup_singletons)


# ── Standalone infinite loop (optional) ─────────────────────────

def run_pipeline(cfg: Config | None = None) -> None:
    """Infinite polling loop — only for standalone background usage."""
    if cfg is None:
        cfg = Config()

    logger.info(
        "newsstack pipeline started (interval=%.1fs, sources=%s).",
        cfg.poll_interval_s,
        cfg.active_sources,
    )
    try:
        while True:
            t0 = time.time()
            try:
                poll_once(cfg)
            except Exception:
                logger.exception("Pipeline cycle error — will retry next tick.")
            dt = time.time() - t0
            time.sleep(max(0.2, cfg.poll_interval_s - dt))
    except KeyboardInterrupt:
        logger.info("newsstack pipeline stopped.")
