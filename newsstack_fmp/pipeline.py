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
from typing import Any

from .common_types import NewsItem
from .config import Config
from .enrich import Enricher
from .ingest_fmp import FmpAdapter
from .open_prep_export import export_open_prep
from .scoring import classify_and_score, cluster_hash
from .store_sqlite import SqliteStore

logger = logging.getLogger(__name__)

# ── Module-level singletons (reused across Streamlit refreshes) ──
_store: SqliteStore | None = None
_fmp_adapter: FmpAdapter | None = None
_bz_rest_adapter: Any | None = None  # BenzingaRestAdapter (lazy)
_bz_ws_adapter: Any | None = None  # BenzingaWsAdapter (lazy)
_enricher: Enricher | None = None
_best_by_ticker: dict[str, dict[str, Any]] = {}
_bbt_lock = threading.Lock()


def _get_store(cfg: Config) -> SqliteStore:
    global _store
    if _store is None:
        os.makedirs(os.path.dirname(cfg.sqlite_path) or ".", exist_ok=True)
        _store = SqliteStore(cfg.sqlite_path)
    return _store


def _get_fmp_adapter(cfg: Config) -> FmpAdapter:
    global _fmp_adapter
    if _fmp_adapter is None:
        _fmp_adapter = FmpAdapter(cfg.fmp_api_key)
    return _fmp_adapter


def _get_bz_rest_adapter(cfg: Config) -> Any:
    global _bz_rest_adapter
    if _bz_rest_adapter is None:
        from .ingest_benzinga import BenzingaRestAdapter
        _bz_rest_adapter = BenzingaRestAdapter(cfg.benzinga_api_key)
    return _bz_rest_adapter


def _get_bz_ws_adapter(cfg: Config) -> Any:
    global _bz_ws_adapter
    if _bz_ws_adapter is None:
        from .ingest_benzinga import BenzingaWsAdapter
        _bz_ws_adapter = BenzingaWsAdapter(
            cfg.benzinga_api_key,
            cfg.benzinga_ws_url,
            channels=cfg.benzinga_channels or None,
        )
        _bz_ws_adapter.start()
    return _bz_ws_adapter


def _get_enricher() -> Enricher:
    global _enricher
    if _enricher is None:
        _enricher = Enricher()
    return _enricher


# ── Helpers ─────────────────────────────────────────────────────

def load_universe(path: str) -> set[str]:
    """Load universe from a text file (one ticker per line)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
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
) -> tuple[float, int]:
    """Dedupe → novelty → score → enrich a batch of :class:`NewsItem`.

    Returns ``(max_ts, enrich_used)`` — the maximum ``updated_ts`` seen
    (for cursor advancement) and the number of enrichment HTTP calls made.

    *_shared_enrich_counter*: if provided, a single-element ``[int]`` list
    that is incremented on each enrichment call.  Survives exceptions so
    the budget is correctly shared across batches even on partial failure.
    """
    max_ts = last_seen_epoch
    enrich_count = 0
    if _shared_enrich_counter is None:
        _shared_enrich_counter = [0]

    for it in items:
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
        enrich_result = None
        if score.score >= enrich_threshold and _shared_enrich_counter[0] < enrich_budget:
            enrich_result = enricher.fetch_url_snippet(it.url)
            enrich_count += 1
            _shared_enrich_counter[0] += 1

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
    fmp_last = float(store.get_kv("fmp.last_seen_epoch") or "0")
    bz_rest_cursor = store.get_kv("benzinga.updatedSince")  # str cursor

    all_items: list[NewsItem] = []
    new_fmp_max = fmp_last
    cycle_warnings: list[str] = []

    def _sanitize_exc(exc: Exception) -> str:
        return re.sub(r"(apikey|token)=[^&\s]+", r"\1=***", str(exc), flags=re.IGNORECASE)

    # ── 1) FMP poll ─────────────────────────────────────────────
    if cfg.enable_fmp and cfg.fmp_api_key:
        fmp = _get_fmp_adapter(cfg)
        try:
            all_items.extend(fmp.fetch_stock_latest(cfg.stock_latest_page, cfg.stock_latest_limit))
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("FMP stock-latest fetch failed: %s", _msg)
            cycle_warnings.append(f"fmp_stock_latest: {_msg}")
        try:
            all_items.extend(fmp.fetch_press_latest(cfg.press_latest_page, cfg.press_latest_limit))
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("FMP press-latest fetch failed: %s", _msg)
            cycle_warnings.append(f"fmp_press_latest: {_msg}")

    # ── 2) Benzinga REST delta ──────────────────────────────────
    bz_rest_items: list[NewsItem] = []
    if cfg.enable_benzinga_rest and cfg.benzinga_api_key:
        bz_rest = _get_bz_rest_adapter(cfg)
        try:
            bz_rest_items = bz_rest.fetch_news(
                updated_since=bz_rest_cursor,
                page_size=cfg.benzinga_rest_page_size,
                channels=cfg.benzinga_channels or None,
                topics=cfg.benzinga_topics or None,
            )
            all_items.extend(bz_rest_items)
        except Exception as exc:
            _msg = _sanitize_exc(exc)
            logger.warning("Benzinga REST fetch failed: %s", _msg)
            cycle_warnings.append(f"benzinga_rest: {_msg}")

    # ── 3) Benzinga WS drain ────────────────────────────────────
    if cfg.enable_benzinga_ws and cfg.benzinga_api_key:
        bz_ws = _get_bz_ws_adapter(cfg)
        ws_items = bz_ws.drain()
        all_items.extend(ws_items)
        if ws_items:
            logger.info("Drained %d items from Benzinga WS queue.", len(ws_items))

    # ── 4) Process all items through unified pipeline ───────────
    # Split FMP vs Benzinga for separate cursor tracking
    fmp_items = [it for it in all_items if it.provider.startswith("fmp_")]
    bz_items = [it for it in all_items if not it.provider.startswith("fmp_")]

    _enrich_ctr: list[int] = [0]  # mutable counter survives exceptions
    try:
        new_fmp_max, _fmp_enrich_used = process_news_items(
            store, fmp_items, _best_by_ticker, universe, enricher,
            cfg.score_enrich_threshold, last_seen_epoch=fmp_last,
            _shared_enrich_counter=_enrich_ctr,
        )
    except Exception as exc:
        _msg = _sanitize_exc(exc)
        logger.warning("process_news_items(fmp) failed: %s", _msg)
        cycle_warnings.append(f"process_fmp: {_msg}")
        new_fmp_max = fmp_last

    # Benzinga items: rely on mark_seen() dedup + REST updatedSince cursor.
    # Do NOT use a stored epoch cursor for Benzinga — WS items would advance
    # the epoch past valid REST items that haven't been fetched yet, causing
    # permanent data loss.  last_seen_epoch=0.0 accepts all items; the
    # authoritative dedup is mark_seen() (provider, item_id).
    bz_processing_ok = False
    try:
        process_news_items(
            store, bz_items, _best_by_ticker, universe, enricher,
            cfg.score_enrich_threshold, last_seen_epoch=0.0,
            enrich_budget=max(0, 3 - _enrich_ctr[0]),
            _shared_enrich_counter=_enrich_ctr,
        )
        bz_processing_ok = True
    except Exception as exc:
        _msg = _sanitize_exc(exc)
        logger.warning("process_news_items(benzinga) failed: %s", _msg)
        cycle_warnings.append(f"process_benzinga: {_msg}")

    # ── 5) Update cursors ───────────────────────────────────────
    if new_fmp_max > fmp_last:
        store.set_kv("fmp.last_seen_epoch", str(new_fmp_max))
    if bz_rest_items and bz_processing_ok:
        # Advance Benzinga updatedSince to max observed updated_ts so we
        # don't skip items that Benzinga indexes out-of-order.
        # Only advance when processing succeeded — otherwise those items
        # would be permanently skipped on the next poll cycle.
        bz_max_ts = max(
            (it.updated_ts or it.published_ts or 0.0 for it in bz_rest_items),
            default=0.0,
        )
        if bz_max_ts > 0:
            store.set_kv("benzinga.updatedSince", str(int(bz_max_ts)))
        else:
            # All items lacked real timestamps — do NOT advance cursor.
            # Advancing to time.time() would permanently skip any items
            # published before 'now' that haven't been fetched yet.
            # The next poll will re-fetch the same window; dedup handles
            # the duplicates.
            logger.warning(
                "Benzinga REST: all %d items lack timestamps — cursor NOT advanced.",
                len(bz_rest_items),
            )

    # ── 6) Export ───────────────────────────────────────────────
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
    bz_count = sum(1 for it in bz_items if it.is_valid)
    meta: dict[str, Any] = {
        "generated_ts": time.time(),
        "cursor": {
            "fmp_last_seen_epoch": new_fmp_max,
            "benzinga_updatedSince": store.get_kv("benzinga.updatedSince"),
        },
        "poll_interval_s": cfg.poll_interval_s,
        "universe_size": len(universe) if universe else None,
        "sources": cfg.active_sources,
        "ingest_counts": {"fmp": fmp_count, "benzinga": bz_count},
        "total_candidates": len(candidates),
        "warnings": cycle_warnings,
    }
    try:
        export_open_prep(cfg.export_path, export_candidates, meta)
    except Exception as exc:
        logger.warning("export_open_prep failed: %s", exc)

    # ── 7) Prune old records + stale best_by_ticker entries ────
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
    global _store, _fmp_adapter, _bz_rest_adapter, _bz_ws_adapter, _enricher
    for obj in (_fmp_adapter, _bz_rest_adapter, _enricher):
        if obj is not None and hasattr(obj, "close"):
            try:
                obj.close()
            except Exception:
                pass
    if _bz_ws_adapter is not None and hasattr(_bz_ws_adapter, "stop"):
        try:
            _bz_ws_adapter.stop()
        except Exception:
            pass
    if _store is not None:
        try:
            _store.close()
        except Exception:
            pass
    with _bbt_lock:
        _best_by_ticker.clear()
    _store = _fmp_adapter = _bz_rest_adapter = _bz_ws_adapter = _enricher = None


import atexit as _atexit  # noqa: E402

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
