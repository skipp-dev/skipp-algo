"""Bloomberg Terminal — Real-Time News Intelligence Dashboard.

Features:
- Multi-source ingestion (Benzinga + FMP)
- Enhanced NLP: 16-category event classifier, relevance scoring, entity analysis
- Full-text search + date filters on Live Feed
- Economic Calendar (FMP API)
- Sector Heatmap (Plotly treemap)
- Compound Alert Builder with webhook dispatch
- Live RT quote integration

Run with::

    streamlit run streamlit_terminal.py

Requires ``BENZINGA_API_KEY`` in ``.env`` or environment.
Optional: ``FMP_API_KEY`` for economic calendar + multi-source news.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ── Path setup ──────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_env_file(env_path: Path) -> None:
    """Load KEY=VALUE pairs from .env into process env."""
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
    except Exception:
        logging.getLogger(__name__).warning("Failed to parse .env file: %s", env_path)


_load_env_file(PROJECT_ROOT / ".env")

from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter
from newsstack_fmp.store_sqlite import SqliteStore
from open_prep.playbook import classify_recency as _classify_recency
from terminal_background_poller import BackgroundPoller
from terminal_export import (
    append_jsonl,
    fire_webhook,
    load_jsonl_feed,
    load_rt_quotes,
    rotate_jsonl,
    save_vd_snapshot,
)
from terminal_feed_lifecycle import FeedLifecycleManager, feed_staleness_minutes, is_market_hours
from terminal_notifications import NotifyConfig, notify_high_score_items
from terminal_poller import (
    ClassifiedItem,
    DEFENSE_TICKERS,
    TerminalConfig,
    compute_power_gaps,
    fetch_benzinga_channel_list,
    fetch_benzinga_conference_calls,
    fetch_benzinga_delayed_quotes,
    fetch_benzinga_dividends,
    fetch_benzinga_earnings,
    fetch_benzinga_economics,
    fetch_benzinga_guidance,
    fetch_benzinga_insider_transactions,
    fetch_benzinga_ipos,
    fetch_benzinga_market_movers,
    fetch_benzinga_news_by_channel,
    fetch_benzinga_quantified,
    fetch_benzinga_ratings,
    fetch_benzinga_retail,
    fetch_benzinga_splits,
    fetch_benzinga_top_news_items,
    fetch_defense_watchlist,
    fetch_economic_calendar,
    fetch_industry_performance,
    fetch_sector_performance,
    poll_and_classify_multi,
)

try:
    from terminal_poller import (
        fetch_benzinga_auto_complete as _tp_auto_complete,
        fetch_benzinga_company_profile as _tp_company_profile,
        fetch_benzinga_financials as _tp_financials,
        fetch_benzinga_fundamentals as _tp_fundamentals,
        fetch_benzinga_logos as _tp_logos,
        fetch_benzinga_options_activity as _tp_options_activity,
        fetch_benzinga_price_history as _tp_price_history,
        fetch_benzinga_ticker_detail as _tp_ticker_detail,
    )
except ImportError:
    _tp_auto_complete = None  # type: ignore[assignment]
    _tp_company_profile = None  # type: ignore[assignment]
    _tp_financials = None  # type: ignore[assignment]
    _tp_fundamentals = None  # type: ignore[assignment]
    _tp_logos = None  # type: ignore[assignment]
    _tp_options_activity = None  # type: ignore[assignment]
    _tp_price_history = None  # type: ignore[assignment]
    _tp_ticker_detail = None  # type: ignore[assignment]

from terminal_spike_scanner import (
    SESSION_ICONS,
    build_spike_rows,
    fetch_gainers,
    fetch_losers,
    fetch_most_active,
    filter_spike_rows,
    market_session,
    overlay_extended_hours_quotes,
)
from terminal_spike_detector import (
    SpikeDetector,
    format_spike_description,
    format_time_et,
)
from terminal_ui_helpers import (
    MATERIALITY_COLORS,
    RECENCY_COLORS,
    SENTIMENT_COLORS,
    aggregate_segments,
    build_heatmap_data,
    build_segment_summary_rows,
    compute_feed_stats,
    compute_top_movers,
    dedup_merge,
    enrich_rank_rows,
    filter_feed,
    format_age_string,
    format_score_badge,
    highlight_fresh_row,
    match_alert_rule,
    provider_icon,
    prune_stale_items,
    safe_markdown_text,
    safe_url,
    split_segments_by_sentiment,
)

logger = logging.getLogger(__name__)

# ── Try to import FMP adapter (optional) ────────────────────────

_FmpAdapter = None
try:
    from newsstack_fmp.ingest_fmp import FmpAdapter as _FmpAdapter  # type: ignore[assignment]
except ImportError:
    pass

# ── Page config ─────────────────────────────────────────────────

st.set_page_config(
    page_title="News Terminal",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Persistent state (survives reruns) ──────────────────────────


def _prune_stale_items(feed: list[dict[str, Any]], max_age_s: float | None = None) -> list[dict[str, Any]]:
    """Drop items whose published_ts is older than *max_age_s* seconds.

    Thin wrapper around ``terminal_ui_helpers.prune_stale_items`` that
    reads the default max-age from Streamlit session state.
    """
    if max_age_s is None:
        cfg_obj = st.session_state.get("cfg")
        max_age_s = cfg_obj.feed_max_age_s if cfg_obj else 14400.0
    return prune_stale_items(feed, max_age_s)


# Resync interval: re-read JSONL every 120 s so long-running sessions
# pick up items written by prior poll cycles or other sessions.
_RESYNC_INTERVAL_S: float = 120.0


def _resync_feed_from_jsonl() -> None:
    """Merge JSONL contents into the session feed.

    Long-running Streamlit sessions only receive NEW API items via
    ``_do_poll()``.  Items that were already marked as "seen" in the
    SQLite dedup store (e.g. ingested by a prior session) are skipped
    by the poller but still exist in the JSONL on disk.  This function
    periodically re-reads the JSONL file and merges any missing items
    into the session feed, keeping long-lived tabs in sync with the
    persisted data.
    """
    cfg: TerminalConfig = st.session_state.cfg
    if not cfg.jsonl_path:
        # Still update the timestamp so we don't re-check every rerun.
        st.session_state.last_resync_ts = time.time()
        return

    restored = load_jsonl_feed(cfg.jsonl_path)
    if not restored:
        # JSONL empty/missing — update timestamp so we don't retry
        # on every 1-second rerun (unnecessary I/O).
        st.session_state.last_resync_ts = time.time()
        return

    merged = dedup_merge(st.session_state.feed, restored)
    new_count = len(merged) - len(st.session_state.feed)
    if new_count > 0:
        st.session_state.feed = merged
        logger.info("JSONL resync: merged %d items into session feed", new_count)

    # Prune stale items after merge
    st.session_state.feed = _prune_stale_items(st.session_state.feed)

    # Only advance the session cursor when the background poller is
    # NOT running.  The BG poller maintains its own cursor; overwriting
    # session_state.cursor here would rewind it on the next rerun
    # (the main loop syncs session cursor back into the poller),
    # causing duplicate ingestion.
    if not st.session_state.get("use_bg_poller") or st.session_state.get("bg_poller") is None:
        _ts_vals = [
            d.get("updated_ts") or d.get("published_ts") or 0
            for d in st.session_state.feed
        ]
        _ts_vals = [t for t in _ts_vals if isinstance(t, (int, float)) and t > 0]
        if _ts_vals:
            st.session_state["cursor"] = str(int(max(_ts_vals)))

    st.session_state.last_resync_ts = time.time()


if "cfg" not in st.session_state:
    st.session_state.cfg = TerminalConfig()
if "cursor" not in st.session_state:
    st.session_state.cursor = None
if "feed" not in st.session_state:
    _restored = load_jsonl_feed(TerminalConfig().jsonl_path)
    # Drop items older than feed_max_age_s so a stale JSONL doesn't
    # populate the session with outdated symbols.
    _before_len = len(_restored)
    _restored = _prune_stale_items(_restored)
    if len(_restored) < _before_len:
        # Rewrite the JSONL file on disk so stale entries don't
        # reappear when the next Streamlit session starts.
        from terminal_export import rewrite_jsonl
        rewrite_jsonl(TerminalConfig().jsonl_path, _restored)
        logger.info("Pruned %d stale items from JSONL on startup", _before_len - len(_restored))
    # Also prune SQLite dedup table so items can be re-ingested on the
    # next poll instead of being blocked by stale "seen" entries from a
    # prior session.  When the feed is completely empty (all items were
    # stale), clear the dedup store entirely — a partial prune (keep=4h)
    # still blocks recent items that were already seen, leaving the user
    # with an empty or stale dashboard.
    if _before_len > 0 and len(_restored) < _before_len:
        from newsstack_fmp.store_sqlite import SqliteStore as _InitStore
        _init_cfg = TerminalConfig()
        _init_store = _InitStore(_init_cfg.sqlite_path)
        _keep = 0.0 if not _restored else _init_cfg.feed_max_age_s
        _init_store.prune_seen(keep_seconds=_keep)
        _init_store.prune_clusters(keep_seconds=_keep)
        _init_store.close()
        logger.info("Pruned SQLite dedup tables (keep_seconds=%.0f) on startup", _keep)
    st.session_state.feed = _restored
    if _restored:
        # Derive cursor from restored feed so polling resumes from latest.
        # Items use "published_ts" (float epoch) or "updated_ts".
        _ts_vals = [
            r.get("updated_ts") or r.get("published_ts") or 0
            for r in _restored
        ]
        _ts_vals = [t for t in _ts_vals if isinstance(t, (int, float)) and t > 0]
        if _ts_vals:
            st.session_state["cursor"] = str(int(max(_ts_vals)))
if "poll_count" not in st.session_state:
    st.session_state.poll_count = 0
if "last_poll_ts" not in st.session_state:
    st.session_state.last_poll_ts = 0.0
if "last_resync_ts" not in st.session_state:
    st.session_state.last_resync_ts = 0.0
if "consecutive_empty_polls" not in st.session_state:
    st.session_state.consecutive_empty_polls = 0
if "adapter" not in st.session_state:
    st.session_state.adapter = None
if "fmp_adapter" not in st.session_state:
    st.session_state.fmp_adapter = None
if "store" not in st.session_state:
    st.session_state.store = None
if "total_items_ingested" not in st.session_state:
    st.session_state.total_items_ingested = len(st.session_state.feed)
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True
if "last_poll_status" not in st.session_state:
    st.session_state.last_poll_status = "—"
if "last_poll_error" not in st.session_state:
    st.session_state.last_poll_error = ""
if "alert_rules" not in st.session_state:
    # Load persisted alert rules
    _alert_path = Path("artifacts/alert_rules.json")
    if _alert_path.exists():
        try:
            _loaded = json.loads(_alert_path.read_text())
            st.session_state.alert_rules = _loaded if isinstance(_loaded, list) else []
        except Exception:
            st.session_state.alert_rules = []
    else:
        st.session_state.alert_rules = []
if "alert_log" not in st.session_state:
    st.session_state.alert_log = []
if "bg_poller" not in st.session_state:
    st.session_state.bg_poller = None
if "notify_config" not in st.session_state:
    st.session_state.notify_config = NotifyConfig()
if "notify_log" not in st.session_state:
    st.session_state.notify_log = []
if "lifecycle_mgr" not in st.session_state:
    _cfg_lc = TerminalConfig()
    st.session_state.lifecycle_mgr = FeedLifecycleManager(
        jsonl_path=_cfg_lc.jsonl_path,
        sqlite_path=_cfg_lc.sqlite_path,
        feed_max_age_s=_cfg_lc.feed_max_age_s,
    )
if "use_bg_poller" not in st.session_state:
    st.session_state.use_bg_poller = os.getenv("TERMINAL_BG_POLL", "1") == "1"
if "news_chart_auto_webhook" not in st.session_state:
    st.session_state.news_chart_auto_webhook = os.getenv("TERMINAL_NEWS_CHART_WEBHOOK", "0") == "1"
if "spike_detector" not in st.session_state:
    st.session_state.spike_detector = SpikeDetector(
        spike_threshold_pct=1.0,
        lookback_s=60.0,
        max_history=200,
        max_event_age_s=3600.0,
        cooldown_s=120.0,
    )


def _get_adapter() -> BenzingaRestAdapter | None:
    """Lazy-init the REST adapter."""
    cfg: TerminalConfig = st.session_state.cfg
    if not cfg.benzinga_api_key:
        return None
    if st.session_state.adapter is None:
        st.session_state.adapter = BenzingaRestAdapter(cfg.benzinga_api_key)
    return st.session_state.adapter  # type: ignore[no-any-return]


def _get_fmp_adapter():
    """Lazy-init the FMP adapter (returns None if missing key or module)."""
    if _FmpAdapter is None:
        return None
    cfg: TerminalConfig = st.session_state.cfg
    if not cfg.fmp_api_key or not cfg.fmp_enabled:
        return None
    if st.session_state.fmp_adapter is None:
        st.session_state.fmp_adapter = _FmpAdapter(cfg.fmp_api_key)
    return st.session_state.fmp_adapter


def _get_store() -> SqliteStore:
    """Lazy-init the SQLite store."""
    if st.session_state.store is None:
        cfg: TerminalConfig = st.session_state.cfg
        os.makedirs(os.path.dirname(cfg.sqlite_path) or ".", exist_ok=True)
        st.session_state.store = SqliteStore(cfg.sqlite_path)
    return st.session_state.store  # type: ignore[no-any-return]


# ── Sidebar ─────────────────────────────────────────────────────

with st.sidebar:
    st.title("📡 Terminal Config")

    cfg: TerminalConfig = st.session_state.cfg

    # API key status
    if cfg.benzinga_api_key:
        st.success(f"Benzinga: …{cfg.benzinga_api_key[-4:]}")
    else:
        st.error("No BENZINGA_API_KEY found in .env")
        st.info("Set `BENZINGA_API_KEY=your_key` in `.env` and restart.")

    if cfg.fmp_api_key:
        st.success(f"FMP: …{cfg.fmp_api_key[-4:]}")
    else:
        st.caption("FMP: not configured (optional)")

    # Poll interval
    interval = st.slider(
        "Poll interval (seconds)",
        min_value=3,
        max_value=60,
        value=int(cfg.poll_interval_s),
        step=1,
    )

    # Auto-refresh toggle
    st.session_state.auto_refresh = st.toggle("Auto-refresh", value=st.session_state.auto_refresh)

    # Manual poll button
    force_poll = st.button("🔄 Poll Now", width='stretch')

    # Reset cursor (forces next poll to fetch latest without updatedSince)
    if st.button("🔃 Reset Cursor", width='stretch',
                 help="Reset the API cursor so the next poll fetches the most recent articles "
                      "without an updatedSince filter. Use when data appears stale."):
        _store = _get_store()
        for _prune_fn, _tbl in (
            (_store.prune_seen, "seen"),
            (_store.prune_clusters, "clusters"),
        ):
            try:
                _prune_fn(keep_seconds=0.0)
            except Exception as exc:
                logger.warning("Cursor reset prune(%s) failed: %s", _tbl, exc)
        st.session_state.cursor = None
        st.session_state.consecutive_empty_polls = 0
        st.toast("Cursor reset — next poll will fetch latest articles", icon="🔃")
        st.rerun()

    st.divider()

    # Stats
    st.metric("Polls", st.session_state.poll_count)
    st.metric("Items in feed", len(st.session_state.feed))
    st.metric("Total ingested", st.session_state.total_items_ingested)
    if st.session_state.last_poll_ts:
        ago = time.time() - st.session_state.last_poll_ts
        st.caption(f"Last poll: {ago:.0f}s ago")

    # Feed staleness + cursor diagnostics
    _diag_feed = st.session_state.feed
    _diag_staleness = feed_staleness_minutes(_diag_feed)
    if _diag_staleness is not None:
        _stale_label = f"Feed age: {_diag_staleness:.0f}m"
        if _diag_staleness > 2 and is_market_hours():
            st.warning(_stale_label)
        else:
            st.caption(_stale_label)
    _diag_cursor = st.session_state.cursor
    if _diag_cursor:
        try:
            _cursor_ago = (time.time() - float(_diag_cursor)) / 60
            st.caption(f"Cursor: {_cursor_ago:.0f}m ago")
        except (ValueError, TypeError):
            st.caption(f"Cursor: {str(_diag_cursor)[:20]}")
    else:
        st.caption("Cursor: (initial)")
    _diag_empty = st.session_state.get("consecutive_empty_polls", 0)
    if _diag_empty > 0:
        st.caption(f"Empty polls: {_diag_empty}")

    st.divider()

    # Last poll status (persistent — survives rerun unlike toasts)
    poll_status = st.session_state.last_poll_status
    poll_error = st.session_state.last_poll_error
    if poll_error:
        st.error(f"Last poll: {poll_error}")
    elif poll_status:
        st.caption(f"Last poll: {poll_status}")

    # Data sources active
    sources = []
    if cfg.benzinga_api_key:
        sources.append("Benzinga")
    if cfg.fmp_api_key and cfg.fmp_enabled and _FmpAdapter:
        sources.append("FMP")
    st.caption(f"Sources: {', '.join(sources) if sources else 'none'}")

    # Reset dedup DB (clears mark_seen so next poll re-ingests)
    if st.button("🗑️ Reset dedup DB", width='stretch'):
        import pathlib
        # Close existing SQLite connection before deleting files
        if st.session_state.store is not None:
            try:
                st.session_state.store.close()
            except Exception:
                pass
        # Close HTTP adapters to release connection pools
        for _adapter_key in ("adapter", "fmp_adapter"):
            _adp = st.session_state.get(_adapter_key)
            if _adp is not None:
                try:
                    _adp.close()
                except Exception:
                    pass
        db_path = pathlib.Path(cfg.sqlite_path)
        # Remove main DB + SQLite WAL/SHM journal files
        for suffix in ("", "-wal", "-shm"):
            p = pathlib.Path(str(db_path) + suffix)
            if p.exists():
                p.unlink()
        st.session_state.store = None
        st.session_state.adapter = None
        st.session_state.fmp_adapter = None
        st.session_state.cursor = None
        st.session_state.feed = []
        st.session_state.poll_count = 0
        st.session_state.total_items_ingested = 0
        st.session_state.last_poll_status = "DB reset — will re-poll"
        st.session_state.last_poll_error = ""
        st.toast("Dedup DB cleared. Next poll will re-ingest.", icon="🗑️")
        st.rerun()

    st.divider()

    # ── Compound Alert Builder (sidebar) ────────────────────
    st.subheader("⚡ Alert Rules")

    with st.expander("➕ New Alert Rule"):
        alert_ticker = st.text_input("Ticker (or * for all)", value="*", key="alert_tk")
        alert_cond = st.selectbox("Condition", [
            "score >= threshold",
            "sentiment == bearish",
            "sentiment == bullish",
            "materiality == HIGH",
            "category matches",
        ], key="alert_cond")
        alert_threshold = st.slider("Score threshold", 0.0, 1.0, 0.80, 0.05, key="alert_thresh")
        alert_cat = st.text_input("Category (for 'category matches')", value="halt", key="alert_cat")
        alert_webhook = st.text_input("Webhook URL (optional)", value="", key="alert_wh")

        if st.button("Add Rule", key="add_rule"):
            new_rule = {
                "ticker": alert_ticker.upper().strip(),
                "condition": alert_cond,
                "threshold": alert_threshold,
                "category": alert_cat.lower().strip(),
                "webhook_url": alert_webhook.strip(),
                "created": time.time(),
            }
            st.session_state.alert_rules.append(new_rule)
            # Persist
            os.makedirs("artifacts", exist_ok=True)
            Path("artifacts/alert_rules.json").write_text(
                json.dumps(st.session_state.alert_rules, indent=2),
            )
            st.toast(f"Alert rule added for {new_rule['ticker']}", icon="⚡")
            st.rerun()

    # Show existing rules
    for i, rule in enumerate(st.session_state.alert_rules):
        cols = st.columns([5, 1])
        with cols[0]:
            st.caption(f"{rule['ticker']}: {rule['condition']} ({rule.get('threshold', '')})")
        with cols[1]:
            if st.button("✕", key=f"del_rule_{rule.get('created', i)}"):
                st.session_state.alert_rules.pop(i)
                Path("artifacts/alert_rules.json").write_text(
                    json.dumps(st.session_state.alert_rules, indent=2),
                )
                st.rerun()

    st.divider()

    # Export paths
    st.caption(f"JSONL: `{cfg.jsonl_path}`")
    st.caption("VD snapshot: `artifacts/terminal_vd.jsonl`")
    st.caption(f"SQLite: `{cfg.sqlite_path}`")
    if cfg.webhook_url:
        st.caption(f"Webhook: `{cfg.webhook_url[:40]}…`")
    else:
        st.caption("Webhook: disabled")

    st.divider()

    # ── Background Poller + Lifecycle ───────────────────────
    st.subheader("🔧 Engine")

    st.session_state.use_bg_poller = st.toggle(
        "Background Polling",
        value=st.session_state.use_bg_poller,
        help="Run API polling in a background thread to prevent UI stalls.",
    )

    st.session_state.news_chart_auto_webhook = st.toggle(
        "News→Chart Auto-Webhook",
        value=st.session_state.news_chart_auto_webhook,
        help="Auto-fire webhook for score ≥ 0.85 actionable items (routes to TradersPost).",
    )

    # Lifecycle status
    _lc_status = st.session_state.lifecycle_mgr.get_status_display()
    st.caption(f"Market: {_lc_status['phase']} ({_lc_status['time_et']})")
    if _lc_status["weekend_cleared"] == "✅":
        st.caption("Weekend clear: ✅")
    if _lc_status["preseed_done"] == "✅":
        st.caption("Pre-seed: ✅")

    # Notification status
    _nc = st.session_state.notify_config
    if _nc.enabled and _nc.has_any_channel:
        _channels = []
        if _nc.telegram_bot_token and _nc.telegram_chat_id:
            _channels.append("Telegram")
        if _nc.discord_webhook_url:
            _channels.append("Discord")
        if _nc.pushover_app_token and _nc.pushover_user_key:
            _channels.append("Pushover")
        st.success(f"Push: {', '.join(_channels)} (≥{_nc.min_score})")
    elif _nc.enabled:
        st.warning("Push: enabled but no channels configured")
    else:
        st.caption("Push notifications: disabled")

    # Background poller status
    if st.session_state.use_bg_poller and st.session_state.bg_poller is not None:
        _bp_alive = st.session_state.bg_poller.is_alive
        if _bp_alive:
            st.success("BG Poller: running")
        else:
            st.error("BG Poller: stopped (will restart)")

    st.divider()

    # RT engine status
    _rt_path = "artifacts/open_prep/latest/latest_vd_signals.jsonl"
    _rt_quotes = load_rt_quotes(_rt_path)
    if _rt_quotes:
        st.success(f"RT Engine: {len(_rt_quotes)} symbols live")
    else:
        if os.path.isfile(_rt_path):
            st.warning("RT Engine: file exists but stale (>120s)")
        else:
            st.info("RT Engine: not running (terminal poller is independent)")


# ── Sentiment helpers (imported from terminal_ui_helpers) ──────
# SENTIMENT_COLORS, MATERIALITY_COLORS, RECENCY_COLORS are
# imported at the top of the file from terminal_ui_helpers.
# Legacy aliases kept for backward compat inside this module.
_SENTIMENT_COLORS = SENTIMENT_COLORS
_MATERIALITY_COLORS = MATERIALITY_COLORS
_RECENCY_COLORS = RECENCY_COLORS


# ── Cached FMP wrappers (avoid re-fetching every Streamlit rerun) ──

@st.cache_data(ttl=60, show_spinner=False)
def _cached_sector_perf(api_key: str) -> list[dict[str, Any]]:
    """Cache sector performance for 60 seconds."""
    return fetch_sector_performance(api_key)


@st.cache_data(ttl=120, show_spinner=False)
def _cached_defense_watchlist(api_key: str) -> list[dict[str, Any]]:
    """Cache Aerospace & Defense watchlist quotes for 2 minutes."""
    return fetch_defense_watchlist(api_key)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_industry_performance(api_key: str, industry: str = "Aerospace & Defense") -> list[dict[str, Any]]:
    """Cache industry screen results for 5 minutes."""
    return fetch_industry_performance(api_key, industry=industry)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_econ_calendar(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache economic calendar for 5 minutes."""
    return fetch_economic_calendar(api_key, from_date, to_date)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_spike_data(api_key: str) -> dict[str, list[dict[str, Any]]]:
    """Cache gainers/losers/actives for 30 seconds."""
    return {
        "gainers": fetch_gainers(api_key),
        "losers": fetch_losers(api_key),
        "actives": fetch_most_active(api_key),
    }


def _safe_float_mov(val: Any, default: float = 0.0) -> float:
    """Safe float conversion for mover data."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ── Cached Benzinga Calendar Wrappers ───────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_ratings(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache Benzinga analyst ratings for 5 minutes."""
    return fetch_benzinga_ratings(api_key, date_from=from_date, date_to=to_date, page_size=100)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_earnings(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache Benzinga earnings calendar for 5 minutes."""
    return fetch_benzinga_earnings(api_key, date_from=from_date, date_to=to_date, page_size=100)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_economics(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache Benzinga economics calendar for 5 minutes."""
    return fetch_benzinga_economics(api_key, date_from=from_date, date_to=to_date, page_size=100)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_bz_movers(api_key: str) -> dict[str, list[dict[str, Any]]]:
    """Cache Benzinga market movers for 60 seconds."""
    return fetch_benzinga_market_movers(api_key)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_bz_quotes(api_key: str, symbols_csv: str) -> list[dict[str, Any]]:
    """Cache Benzinga delayed quotes for 60 seconds."""
    syms = [s.strip() for s in symbols_csv.split(",") if s.strip()]
    return fetch_benzinga_delayed_quotes(api_key, syms)


# ── Cached Benzinga NEW Calendar Wrappers ───────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_dividends(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache Benzinga dividends calendar for 5 minutes."""
    return fetch_benzinga_dividends(api_key, date_from=from_date, date_to=to_date, page_size=100)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_splits(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache Benzinga splits calendar for 5 minutes."""
    return fetch_benzinga_splits(api_key, date_from=from_date, date_to=to_date, page_size=100)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_ipos(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache Benzinga IPO calendar for 5 minutes."""
    return fetch_benzinga_ipos(api_key, date_from=from_date, date_to=to_date, page_size=100)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_guidance(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache Benzinga guidance calendar for 5 minutes."""
    return fetch_benzinga_guidance(api_key, date_from=from_date, date_to=to_date, page_size=100)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_retail(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache Benzinga retail sales calendar for 5 minutes."""
    return fetch_benzinga_retail(api_key, date_from=from_date, date_to=to_date, page_size=100)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_conference_calls(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache Benzinga conference calls calendar for 5 minutes."""
    return fetch_benzinga_conference_calls(api_key, date_from=from_date, date_to=to_date, page_size=100)


@st.cache_data(ttl=180, show_spinner=False)
def _cached_bz_insider_transactions(
    api_key: str,
    date_from: str | None = None,
    date_to: str | None = None,
    action: str | None = None,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Cache Benzinga insider transactions for 3 minutes."""
    return fetch_benzinga_insider_transactions(
        api_key, date_from=date_from, date_to=date_to,
        action=action, page_size=page_size,
    )


@st.cache_data(ttl=120, show_spinner=False)
def _cached_bz_power_gaps(api_key: str) -> list[dict[str, Any]]:
    """Cache power gap classifications for 2 minutes."""
    return compute_power_gaps(api_key)


# ── Cached Benzinga News Wrappers ───────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def _cached_bz_top_news(api_key: str, channel: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Cache Benzinga top news for 2 minutes."""
    return fetch_benzinga_top_news_items(api_key, channel=channel, limit=limit)


@st.cache_data(ttl=120, show_spinner=False)
def _cached_bz_quantified(api_key: str, from_date: str | None = None, to_date: str | None = None) -> list[dict[str, Any]]:
    """Cache Benzinga quantified news for 2 minutes."""
    return fetch_benzinga_quantified(api_key, date_from=from_date, date_to=to_date)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_bz_channel_list(api_key: str) -> list[dict[str, Any]]:
    """Cache Benzinga channel list for 1 hour (rarely changes)."""
    return fetch_benzinga_channel_list(api_key)


@st.cache_data(ttl=120, show_spinner=False)
def _cached_bz_news_by_channel(api_key: str, channels: str, page_size: int = 50) -> list[dict[str, Any]]:
    """Cache channel-filtered Benzinga news for 2 minutes."""
    return fetch_benzinga_news_by_channel(api_key, channels, page_size=page_size)


# ── Cached Benzinga Financial Data Wrappers ─────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_options_activity(api_key: str, tickers: str, from_date: str | None = None, to_date: str | None = None) -> list[dict[str, Any]]:
    """Cache Benzinga options activity for 5 minutes."""
    if _tp_options_activity is None:
        return []
    return _tp_options_activity(api_key, tickers, date_from=from_date, date_to=to_date)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_bz_fundamentals(api_key: str, tickers: str) -> list[dict[str, Any]]:
    """Cache Benzinga fundamentals for 10 minutes."""
    if _tp_fundamentals is None:
        return []
    return _tp_fundamentals(api_key, tickers)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_bz_financials(api_key: str, tickers: str) -> list[dict[str, Any]]:
    """Cache Benzinga financials for 10 minutes."""
    if _tp_financials is None:
        return []
    return _tp_financials(api_key, tickers)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_bz_company_profile(api_key: str, tickers: str) -> list[dict[str, Any]]:
    """Cache Benzinga company profile for 10 minutes."""
    if _tp_company_profile is None:
        return []
    return _tp_company_profile(api_key, tickers)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_bz_ticker_detail(api_key: str, tickers: str) -> list[dict[str, Any]]:
    """Cache Benzinga ticker detail for 5 minutes."""
    if _tp_ticker_detail is None:
        return []
    return _tp_ticker_detail(api_key, tickers)


# ── Alert evaluation ────────────────────────────────────────────

_ALERT_WEBHOOK_BUDGET: int = 10  # max webhook POSTs per poll cycle


def _evaluate_alerts(items: list[ClassifiedItem]) -> None:
    """Check each new item against alert rules, fire webhooks + log.

    Guards:
    - Dedup by item_id: multi-ticker articles only fire once per rule.
    - Webhook budget: max *_ALERT_WEBHOOK_BUDGET* POSTs per call to
      avoid hammering external endpoints on noisy rules.
    """
    rules = st.session_state.alert_rules
    if not rules:
        return

    seen_pairs: set[tuple[str, int]] = set()
    webhook_budget = _ALERT_WEBHOOK_BUDGET
    # Collect webhook POSTs so we can fire them in a single client session
    pending_webhooks: list[tuple[str, dict]] = []

    for ci in items:
        for rule_idx, rule in enumerate(rules):
            tk_match = rule["ticker"] in ("*", ci.ticker)
            if not tk_match:
                continue

            # Dedup: skip if this item already fired for this rule
            pair_key = (ci.item_id, rule_idx)
            if pair_key in seen_pairs:
                continue

            cond = rule["condition"]
            fired = False

            if match_alert_rule(
                rule,
                ticker=ci.ticker,
                news_score=ci.news_score,
                sentiment_label=ci.sentiment_label,
                materiality=ci.materiality,
                category=ci.category,
            ):
                fired = True

            if fired:
                seen_pairs.add(pair_key)

                log_entry = {
                    "ts": time.time(),
                    "ticker": ci.ticker,
                    "headline": ci.headline[:120],
                    "rule": cond,
                    "score": ci.news_score,
                    "item_id": ci.item_id,
                }
                st.session_state.alert_log.insert(0, log_entry)
                # Cap alert log
                if len(st.session_state.alert_log) > 100:
                    st.session_state.alert_log = st.session_state.alert_log[:100]

                # Queue webhook if configured (with budget guard)
                wh = rule.get("webhook_url", "")
                if wh and webhook_budget > 0:
                    webhook_budget -= 1
                    pending_webhooks.append((wh, log_entry))

    # Fire all queued webhooks through a single shared httpx client
    if pending_webhooks:
        import httpx as _httpx
        try:
            with _httpx.Client(timeout=5.0) as client:
                for wh_url, wh_payload in pending_webhooks:
                    try:
                        body = json.dumps(wh_payload, default=str).encode()
                        client.post(wh_url, content=body, headers={"Content-Type": "application/json"})
                    except Exception as exc:
                        logger.warning("Alert webhook POST failed (%s): %s", wh_url[:40], exc)
        except Exception as exc:
            logger.warning("Alert webhook client init failed: %s", exc)


# ── Poll logic ──────────────────────────────────────────────────

def _should_poll(poll_interval: float) -> bool:
    """Determine if we should poll this cycle."""
    cfg: TerminalConfig = st.session_state.cfg
    if not cfg.benzinga_api_key and not cfg.fmp_api_key:
        return False
    elapsed: float = time.time() - st.session_state.last_poll_ts
    return elapsed >= poll_interval  # type: ignore[no-any-return]


def _do_poll() -> None:
    """Execute one poll cycle (multi-source: Benzinga + FMP)."""
    adapter = _get_adapter()
    fmp = _get_fmp_adapter()
    if adapter is None and fmp is None:
        return

    store = _get_store()
    cfg: TerminalConfig = st.session_state.cfg

    try:
        items, new_cursor = poll_and_classify_multi(
            benzinga_adapter=adapter,
            fmp_adapter=fmp,
            store=store,
            cursor=st.session_state.cursor,
            page_size=cfg.page_size,
            channels=cfg.channels or None,
            topics=cfg.topics or None,
        )
    except Exception as exc:
        import re as _re
        _safe_msg = _re.sub(r"(apikey|token)=[^&\s]+", r"\1=***", str(exc), flags=_re.IGNORECASE)
        logger.exception("Poll failed: %s", _safe_msg)
        st.session_state.last_poll_error = _safe_msg
        st.session_state.last_poll_status = "ERROR"
        # Advance last_poll_ts even on failure to prevent a tight retry
        # loop that hammers a broken API on every Streamlit rerun.
        st.session_state.last_poll_ts = time.time()
        return

    st.session_state.cursor = new_cursor
    st.session_state.poll_count += 1
    st.session_state.last_poll_ts = time.time()
    st.session_state.total_items_ingested += len(items)
    st.session_state.last_poll_error = ""

    src_label = "BZ"
    if fmp is not None:
        src_label = "BZ+FMP"
    st.session_state.last_poll_status = f"{len(items)} items [{src_label}] (cursor={new_cursor})"

    # Track consecutive empty polls — if the API returns items but
    # _classify_item deduplicates them all away, the cursor advances
    # but the feed doesn't grow.  After several empty polls, prune
    # the SQLite dedup tables and reset the cursor to force a fresh
    # ingestion cycle.
    if not items:
        st.session_state.consecutive_empty_polls = st.session_state.get(
            "consecutive_empty_polls", 0
        ) + 1
        if st.session_state.consecutive_empty_polls >= 3:
            # Full clear (keep=0) when the feed is empty — a partial
            # prune with keep=4h still blocks recently-seen items and
            # the poll keeps returning 0 classified results.
            _prune_keep = 0.0 if not st.session_state.feed else cfg.feed_max_age_s
            for _prune_fn, _tbl in (
                (store.prune_seen, "seen"),
                (store.prune_clusters, "clusters"),
            ):
                try:
                    _prune_fn(keep_seconds=_prune_keep)
                except Exception as exc:
                    logger.warning("SQLite prune(%s) after empty polls failed: %s", _tbl, exc)
            # Cursor reset MUST happen even if prune failed — the cursor
            # is the primary recovery action (API returns latest articles).
            st.session_state.cursor = None
            logger.info(
                "Reset cursor + pruned SQLite (keep=%.0f) after %d consecutive empty polls",
                _prune_keep,
                st.session_state.consecutive_empty_polls,
            )
            st.session_state.consecutive_empty_polls = 0
    else:
        st.session_state.consecutive_empty_polls = 0

    # Evaluate alert rules on new items
    _evaluate_alerts(items)

    # JSONL export (before dict conversion — append_jsonl expects ClassifiedItem)
    if cfg.jsonl_path:
        for ci in items:
            try:
                append_jsonl(ci, cfg.jsonl_path)
            except Exception as exc:
                logger.warning("JSONL append failed for %s: %s", ci.item_id[:40], exc)

    # Prepend batch in one operation (avoids O(n²) repeated insert(0, …))
    new_dicts = [ci.to_dict() for ci in items]
    st.session_state.feed = new_dicts + st.session_state.feed

    # Fire global webhook for qualifying items (single shared client, capped)
    if cfg.webhook_url and items:
        import httpx as _httpx_wh
        _wh_budget = 20  # max webhook POSTs per poll cycle
        with _httpx_wh.Client(timeout=5.0) as wh_client:
            for ci in items:
                if _wh_budget <= 0:
                    logger.warning("Global webhook budget exhausted, skipping remaining items")
                    break
                if fire_webhook(ci, cfg.webhook_url, cfg.webhook_secret, _client=wh_client) is not None:
                    _wh_budget -= 1

    # ── Push notifications for high-score items ─────────────
    if new_dicts:
        try:
            _notify_results = notify_high_score_items(
                new_dicts, config=st.session_state.notify_config,
            )
            if _notify_results:
                st.session_state.notify_log = (
                    _notify_results + st.session_state.notify_log
                )[:100]
        except Exception as exc:
            logger.warning("Push notification dispatch failed: %s", exc)

    # ── News→Chart auto-webhook: route high-score items to TradersPost.
    # Only fire when the auto-webhook URL differs from the global webhook,
    # OR when the global webhook didn't fire (score between 0.70–0.85).
    # When both URLs are the same, the global webhook already sent items
    # with score ≥ 0.70, so re-sending at ≥ 0.85 is a duplicate POST.
    _nc_webhook_url = os.getenv("TERMINAL_NEWS_CHART_WEBHOOK_URL", cfg.webhook_url)
    if st.session_state.news_chart_auto_webhook and _nc_webhook_url and items:
        import httpx as _httpx_nc
        _nc_budget = 5
        _skip_dup = _nc_webhook_url == cfg.webhook_url
        with _httpx_nc.Client(timeout=5.0) as nc_client:
            for ci in items:
                if _nc_budget <= 0:
                    break
                if ci.news_score >= 0.85 and ci.is_actionable:
                    if _skip_dup:
                        continue  # already sent by global webhook above
                    fire_webhook(ci, _nc_webhook_url, cfg.webhook_secret,
                                 min_score=0.85, _client=nc_client)
                    _nc_budget -= 1

    # Trim feed
    max_items = cfg.max_items
    if len(st.session_state.feed) > max_items:
        st.session_state.feed = st.session_state.feed[:max_items]

    # Prune stale items (age-based) so rankings stay fresh
    st.session_state.feed = _prune_stale_items(st.session_state.feed)

    # Periodically resync from JSONL so long-running sessions pick up
    # items that were deduped by the SQLite store (ingested by a prior
    # session) but still persisted on disk.
    if time.time() - st.session_state.last_resync_ts >= _RESYNC_INTERVAL_S:
        _resync_feed_from_jsonl()

    # Rotate JSONL periodically (also drops stale entries)
    if cfg.jsonl_path and st.session_state.poll_count % 100 == 0:
        rotate_jsonl(cfg.jsonl_path, max_age_s=cfg.feed_max_age_s)

    # Prune SQLite dedup tables periodically (alongside JSONL rotation)
    if st.session_state.poll_count % 100 == 0:
        try:
            store.prune_seen(keep_seconds=86400)
            store.prune_clusters(keep_seconds=86400)
        except Exception as exc:
            logger.warning("SQLite prune failed: %s", exc)

    # Write per-symbol VisiData snapshot (atomic overwrite)
    # Fetch Benzinga delayed quotes as fallback for extended hours
    _vd_bz_quotes: list[dict[str, Any]] | None = None
    _vd_session = market_session()
    if _vd_session in ("pre-market", "after-hours") and cfg.benzinga_api_key and st.session_state.feed:
        _vd_syms = sorted({d.get("ticker", "") for d in st.session_state.feed
                         if d.get("ticker") and d.get("ticker") != "MARKET"})[:50]
        if _vd_syms:
            try:
                _vd_bz_quotes = fetch_benzinga_delayed_quotes(
                    cfg.benzinga_api_key, _vd_syms)
            except Exception:
                pass  # non-critical fallback
    save_vd_snapshot(st.session_state.feed, bz_quotes=_vd_bz_quotes)

    if items:
        st.toast(f"📡 {len(items)} new item(s) [{src_label}]", icon="✅")


# ── Execute poll if needed ──────────────────────────────────────

# Feed lifecycle management (weekend clear, pre-seed, off-hours throttle)
_lifecycle: FeedLifecycleManager = st.session_state.lifecycle_mgr
try:
    _lc_result = _lifecycle.manage(st.session_state.feed, _get_store())
except Exception as _lc_exc:
    logger.warning("Feed lifecycle manage() failed: %s", _lc_exc)
    _lc_result = {"action": "error"}
if _lc_result.get("feed_action") == "cleared":
    st.session_state.feed = []
    st.session_state.cursor = None
    st.session_state.poll_count = 0
    logger.info("Feed lifecycle: weekend data cleared")
elif _lc_result.get("feed_action") == "stale_recovery":
    st.session_state.cursor = None
    st.session_state.consecutive_empty_polls = 0
    logger.info("Feed lifecycle: stale-recovery cursor reset")

# Adjust poll interval for off-hours
_effective_interval = _lifecycle.get_off_hours_poll_interval(float(interval))

# When the feed is completely empty (e.g. all JSONL items were stale
# and pruned on startup), force an immediate poll so the user sees
# data on the very first render instead of "No items yet".
_feed_empty_needs_poll = (
    not st.session_state.feed
    and st.session_state.poll_count == 0
    and (st.session_state.cfg.benzinga_api_key or st.session_state.cfg.fmp_api_key)
)

# ── Background poller mode ──────────────────────────────────────
if st.session_state.use_bg_poller:
    # Start background poller if not running
    if st.session_state.bg_poller is None or not st.session_state.bg_poller.is_alive:
        _bp = BackgroundPoller(
            cfg=st.session_state.cfg,
            benzinga_adapter=_get_adapter(),
            fmp_adapter=_get_fmp_adapter(),
            store=_get_store(),
        )
        _bp.start(cursor=st.session_state.cursor)
        st.session_state.bg_poller = _bp
        logger.info("Background poller initialized")

    # Update interval (may have changed via slider or off-hours adjustment)
    st.session_state.bg_poller.update_interval(_effective_interval)

    # Drain new items from background thread
    _bg_items = st.session_state.bg_poller.drain()
    if _bg_items:
        # Alert evaluation (needs ClassifiedItem objects)
        _evaluate_alerts(_bg_items)

        # JSONL export
        _bg_cfg = st.session_state.cfg
        if _bg_cfg.jsonl_path:
            for ci in _bg_items:
                try:
                    append_jsonl(ci, _bg_cfg.jsonl_path)
                except Exception as exc:
                    logger.warning("JSONL append failed: %s", exc)

        new_dicts = [ci.to_dict() for ci in _bg_items]
        st.session_state.feed = new_dicts + st.session_state.feed

        # Push notifications for high-score items
        try:
            _nr = notify_high_score_items(new_dicts, config=st.session_state.notify_config)
            if _nr:
                st.session_state.notify_log = (_nr + st.session_state.notify_log)[:100]
        except Exception as exc:
            logger.warning("Push notification dispatch failed: %s", exc)

        # ── Global webhook for qualifying items ─────────────
        if _bg_cfg.webhook_url:
            import httpx as _httpx_bgwh
            _wh_budget_bg = 20
            with _httpx_bgwh.Client(timeout=5.0) as _wh_c:
                for ci in _bg_items:
                    if _wh_budget_bg <= 0:
                        logger.warning("BG global webhook budget exhausted, skipping remaining")
                        break
                    if fire_webhook(ci, _bg_cfg.webhook_url, _bg_cfg.webhook_secret,
                                    _client=_wh_c) is not None:
                        _wh_budget_bg -= 1

        # ── News→Chart auto-webhook ─────────────────────────
        _nc_webhook_url_bg = os.getenv("TERMINAL_NEWS_CHART_WEBHOOK_URL", _bg_cfg.webhook_url)
        _skip_dup_bg = _nc_webhook_url_bg == _bg_cfg.webhook_url
        if st.session_state.news_chart_auto_webhook and _nc_webhook_url_bg:
            import httpx as _httpx_bg
            _nc_b = 5
            with _httpx_bg.Client(timeout=5.0) as _nc_c:
                for ci in _bg_items:
                    if _nc_b <= 0:
                        break
                    if ci.news_score >= 0.85 and ci.is_actionable:
                        if _skip_dup_bg:
                            continue  # already sent by global webhook above
                        fire_webhook(ci, _nc_webhook_url_bg, _bg_cfg.webhook_secret,
                                     min_score=0.85, _client=_nc_c)
                        _nc_b -= 1

        # Trim + prune
        max_items = _bg_cfg.max_items
        if len(st.session_state.feed) > max_items:
            st.session_state.feed = st.session_state.feed[:max_items]
        st.session_state.feed = _prune_stale_items(st.session_state.feed)
        # Fetch Benzinga delayed quotes as fallback for extended hours
        _vd_bz_quotes_bg: list[dict[str, Any]] | None = None
        _vd_session_bg = market_session()
        if _vd_session_bg in ("pre-market", "after-hours") and _bg_cfg.benzinga_api_key and st.session_state.feed:
            _vd_syms_bg = sorted({d.get("ticker", "") for d in st.session_state.feed
                                if d.get("ticker") and d.get("ticker") != "MARKET"})[:50]
            if _vd_syms_bg:
                try:
                    _vd_bz_quotes_bg = fetch_benzinga_delayed_quotes(
                        _bg_cfg.benzinga_api_key, _vd_syms_bg)
                except Exception:
                    pass  # non-critical fallback
        save_vd_snapshot(st.session_state.feed, bz_quotes=_vd_bz_quotes_bg)
        st.toast(f"📡 {len(_bg_items)} new item(s) [BG]", icon="✅")

    # Sync status from background poller for sidebar display
    _bp = st.session_state.bg_poller
    st.session_state.poll_count = _bp.poll_count
    st.session_state.last_poll_ts = _bp.last_poll_ts
    st.session_state.last_poll_status = _bp.last_poll_status
    st.session_state.last_poll_error = _bp.last_poll_error
    st.session_state.total_items_ingested = _bp.total_items_ingested
    st.session_state.cursor = _bp.cursor

    # Force poll still works in BG mode (for initial load)
    if _feed_empty_needs_poll:
        with st.spinner("Loading latest news…"):
            _do_poll()
        # Sync the newly-advanced cursor into the BG poller so its
        # first real poll doesn't re-fetch what the foreground just got.
        if st.session_state.bg_poller is not None:
            st.session_state.bg_poller.cursor = st.session_state.cursor
else:
    # ── Foreground (legacy) polling ─────────────────────────
    if _feed_empty_needs_poll:
        with st.spinner("Loading latest news…"):
            _do_poll()
    elif force_poll or (st.session_state.auto_refresh and _should_poll(_effective_interval)):
        _do_poll()

# Resync from JSONL even outside poll cycles so that sessions which
# never poll (e.g. missing API keys on Streamlit Cloud) still reflect
# data written to disk by other sessions or external scripts.
if time.time() - st.session_state.last_resync_ts >= _RESYNC_INTERVAL_S:
    _resync_feed_from_jsonl()


# ── Main display ────────────────────────────────────────────────

st.title("📡 News Terminal")

if not st.session_state.cfg.benzinga_api_key and not st.session_state.cfg.fmp_api_key:
    st.warning("Set `BENZINGA_API_KEY` and/or `FMP_API_KEY` in `.env` to start polling.")
    st.stop()

feed = st.session_state.feed

if not feed:
    # Show poll status / errors so the user knows what's happening
    _poll_err = st.session_state.get("last_poll_error", "")
    if _poll_err:
        st.error(f"Poll error: {_poll_err}")
    elif st.session_state.poll_count > 0:
        st.warning("Poll returned no new items. Will retry automatically.")
    else:
        st.info("No items yet. Waiting for first poll…")
else:
    # ── Stats bar ───────────────────────────────────────────
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    _stats = compute_feed_stats(feed)

    col1.metric("Feed items", _stats["count"])
    col2.metric("Unique tickers", _stats["unique_tickers"])
    col3.metric("Actionable", _stats["actionable"])
    col4.metric("HIGH materiality", _stats["high_materiality"])
    col5.metric("Avg relevance", f"{_stats['avg_relevance']:.3f}")
    col6.metric("Newest item", f"{_stats['newest_age_min']:.0f}m ago")

    st.divider()

    # ── Tabs ────────────────────────────────────────────────
    _session_icons = SESSION_ICONS
    # Compute once per render — avoids 4+ redundant calls and cross-tab drift
    _current_session = market_session()

    tab_feed, tab_movers, tab_rank, tab_segments, tab_rt_spikes, tab_spikes, tab_heatmap, tab_calendar, tab_bz_cal, tab_bz_movers, tab_defense, tab_alerts, tab_table = st.tabs(
        ["📰 Live Feed", "🔥 Top Movers", "🏆 Rankings", "🏗️ Segments",
         "⚡ RT Spikes", "🚨 Spikes", "🗺️ Heatmap", "📅 Calendar", "📊 Benzinga Intel",
         "💹 Bz Movers", "🛡️ Defense & Aerospace", "⚡ Alerts", "📊 Data Table"],
    )

    # ── TAB: Live Feed (with search + date filter) ──────────
    with tab_feed:
        # Search + filter controls
        fcol1, fcol2, fcol3 = st.columns([3, 2, 2])
        with fcol1:
            search_q = st.text_input(
                "🔍 Search headlines", value="", placeholder="e.g. AAPL earnings",
                key="feed_search",
            )
        with fcol2:
            filter_sentiment = st.selectbox(
                "Sentiment", ["all", "bullish", "bearish", "neutral"],
                key="feed_sent",
            )
        with fcol3:
            filter_category = st.selectbox(
                "Category", ["all", *sorted(set(d.get("category", "other") for d in feed))],
                key="feed_cat",
            )

        # Date range filter
        dcol1, dcol2 = st.columns(2)
        with dcol1:
            date_from = st.date_input(
                "From",
                value=datetime.now(UTC).date() - timedelta(days=7),
                key="feed_date_from",
            )
        with dcol2:
            date_to = st.date_input("To", value=datetime.now(UTC).date(), key="feed_date_to")

        # Apply filters (pure function from terminal_ui_helpers)
        from_epoch = datetime.combine(date_from, datetime.min.time(), tzinfo=UTC).timestamp()
        to_epoch = datetime.combine(date_to, datetime.max.time(), tzinfo=UTC).timestamp()
        filtered = filter_feed(
            feed,
            search_q=search_q,
            sentiment=filter_sentiment,
            category=filter_category,
            from_epoch=from_epoch,
            to_epoch=to_epoch,
        )

        st.caption(f"Showing {len(filtered)} of {len(feed)} items")

        # Show filtered items
        for d in filtered[:50]:
            sent_icon = _SENTIMENT_COLORS.get(d.get("sentiment_label", ""), "")
            mat_icon = _MATERIALITY_COLORS.get(d.get("materiality", ""), "")

            # Recompute recency live from published_ts
            _pub = d.get("published_ts")
            if _pub and _pub > 0:
                _live_rec = _classify_recency(
                    datetime.fromtimestamp(_pub, tz=UTC),
                )
                rec_icon = _RECENCY_COLORS.get(_live_rec["recency_bucket"], "")
            else:
                rec_icon = _RECENCY_COLORS.get(d.get("recency_bucket", ""), "")

            ticker = d.get("ticker", "?")
            score = d.get("news_score", 0)
            relevance = d.get("relevance", 0)
            category = d.get("category", "other")
            headline = d.get("headline", "")
            event_label = d.get("event_label", "")
            source_tier = d.get("source_tier", "")
            _provider = d.get("provider", "")
            url = d.get("url", "")

            age_str = format_age_string(d.get("published_ts"))
            score_badge = format_score_badge(score)
            prov_icon = provider_icon(_provider)
            _safe_url = safe_url(url)
            _wiim_badge = " 🔍" if d.get("is_wiim") else ""

            with st.container():
                cols = st.columns([1, 5, 1, 1, 1, 1])
                with cols[0]:
                    st.markdown(f"**{ticker}**")
                with cols[1]:
                    safe_hl = safe_markdown_text(headline[:100])
                    link = f"[{safe_hl}]({_safe_url})" if _safe_url else headline[:100]
                    st.markdown(f"{sent_icon} {link}")
                with cols[2]:
                    st.markdown(f"`{category}`")
                with cols[3]:
                    st.markdown(score_badge + _wiim_badge)
                with cols[4]:
                    st.markdown(f"{rec_icon} {age_str}")
                with cols[5]:
                    st.markdown(f"{prov_icon} {event_label}")

    # ── TAB: Top Movers ─────────────────────────────────────
    with tab_movers:
        # ── Real-time Top Movers: merge FMP + Benzinga ──────────
        fmp_key_mov = st.session_state.cfg.fmp_api_key
        bz_key_mov = st.session_state.cfg.benzinga_api_key
        _session_label_mov = _session_icons.get(_current_session, _current_session)

        if not fmp_key_mov and not bz_key_mov:
            st.info("Set `FMP_API_KEY` and/or `BENZINGA_API_KEY` in `.env` for real-time movers.")
        else:
            st.subheader("🔥 Real-Time Top Movers")
            st.caption(f"**{_session_label_mov}** — Live gainers & losers ranked by absolute price change. Auto-refreshes each cycle.")

            # Gather data from all sources
            _mov_all: dict[str, dict[str, Any]] = {}  # symbol → best row

            # 1) FMP gainers/losers/actives (30s TTL)
            if fmp_key_mov:
                _fmp_data = _cached_spike_data(fmp_key_mov)
                for _src_list, _src_label in [
                    (_fmp_data["gainers"], "FMP-Gainer"),
                    (_fmp_data["losers"], "FMP-Loser"),
                    (_fmp_data["actives"], "FMP-Active"),
                ]:
                    for item in _src_list:
                        sym = (item.get("symbol") or "").upper().strip()
                        if not sym:
                            continue
                        price = _safe_float_mov(item.get("price"))
                        chg_pct = _safe_float_mov(item.get("changesPercentage"))
                        chg = _safe_float_mov(item.get("change"))
                        vol = int(_safe_float_mov(item.get("volume")))
                        name = item.get("name") or item.get("companyName") or ""
                        existing = _mov_all.get(sym)
                        if not existing or abs(chg_pct) > abs(existing.get("chg_pct", 0)):
                            _mov_all[sym] = {
                                "symbol": sym,
                                "name": name[:50],
                                "price": price,
                                "change": chg,
                                "chg_pct": chg_pct,
                                "volume": vol,
                                "source": _src_label,
                            }

            # 2) Benzinga movers (60s TTL)
            if bz_key_mov:
                _bz_movers = _cached_bz_movers(bz_key_mov)
                for _bz_list, _bz_label in [
                    (_bz_movers.get("gainers", []), "BZ-Gainer"),
                    (_bz_movers.get("losers", []), "BZ-Loser"),
                ]:
                    for item in _bz_list:
                        sym = (item.get("symbol") or item.get("ticker") or "").upper().strip()
                        if not sym:
                            continue
                        price = _safe_float_mov(item.get("price") or item.get("last"))
                        chg_pct = _safe_float_mov(item.get("changePercent") or item.get("change_percent"))
                        chg = _safe_float_mov(item.get("change"))
                        vol = int(_safe_float_mov(item.get("volume")))
                        name = item.get("companyName") or item.get("company_name") or ""
                        existing = _mov_all.get(sym)
                        # Benzinga is fresher than FMP during extended hours
                        if not existing or (_current_session in ("pre-market", "after-hours")):
                            _mov_all[sym] = {
                                "symbol": sym,
                                "name": name[:50],
                                "price": price,
                                "change": chg,
                                "chg_pct": chg_pct,
                                "volume": vol,
                                "source": _bz_label,
                            }

            # 3) RT spike events from our detector (real-time, sub-minute)
            _detector_mov: SpikeDetector = st.session_state.spike_detector
            for ev in _detector_mov.events[:50]:
                sym = ev.symbol
                existing = _mov_all.get(sym)
                # If spike is larger than what we already have, use it
                if not existing or abs(ev.spike_pct) > abs(existing.get("chg_pct", 0)):
                    _mov_all[sym] = {
                        "symbol": sym,
                        "name": ev.name[:50],
                        "price": ev.price,
                        "change": ev.change,
                        "chg_pct": ev.spike_pct,
                        "volume": ev.volume,
                        "source": f"RT-Spike {ev.direction}",
                    }

            if not _mov_all:
                st.info("No mover data available yet. Data sources are loading.")
            else:
                # Sort by absolute change% (biggest movers first)
                _sorted_movers = sorted(
                    _mov_all.values(),
                    key=lambda x: abs(x.get("chg_pct", 0)),
                    reverse=True,
                )

                # Summary metrics
                _n_up = sum(1 for m in _sorted_movers if m.get("chg_pct", 0) > 0)
                _n_dn = sum(1 for m in _sorted_movers if m.get("chg_pct", 0) < 0)
                _m1, _m2, _m3, _m4 = st.columns(4)
                _m1.metric("Total Movers", len(_sorted_movers))
                _m2.metric("🟢 Gainers", _n_up)
                _m3.metric("🔴 Losers", _n_dn)
                if _sorted_movers:
                    _top = _sorted_movers[0]
                    _m4.metric("🏆 Top Mover", f"{_top['symbol']} {_top['chg_pct']:+.2f}%")

                # Build table
                _mov_rows = []
                for m in _sorted_movers[:100]:
                    _dir_icon = "🟢" if m.get("chg_pct", 0) > 0 else "🔴"
                    _mov_rows.append({
                        "": _dir_icon,
                        "Symbol": m["symbol"],
                        "Name": m.get("name", ""),
                        "Price": f"${m['price']:.2f}" if m["price"] >= 1 else f"${m['price']:.4f}",
                        "Change": f"{m['change']:+.2f}",
                        "Change %": f"{m['chg_pct']:+.2f}%",
                        "Volume": f"{m['volume']:,}" if m.get("volume") else "",
                        "Source": m.get("source", ""),
                    })

                df_mov = pd.DataFrame(_mov_rows)
                df_mov.index = df_mov.index + 1

                st.dataframe(
                    df_mov,
                    width='stretch',
                    height=min(800, 40 + 35 * len(df_mov)),
                    column_config={
                        "": st.column_config.TextColumn("", width="small"),
                        "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                        "Name": st.column_config.TextColumn("Name", width="medium"),
                        "Change %": st.column_config.TextColumn("Change %", width="small"),
                    },
                )

    # ── TAB: Rankings (real-time price-based) ─────────────────
    with tab_rank:
        fmp_key_rank = st.session_state.cfg.fmp_api_key
        bz_key_rank = st.session_state.cfg.benzinga_api_key
        _session_label_rank = _session_icons.get(_current_session, _current_session)

        if not fmp_key_rank and not bz_key_rank:
            st.info("Set `FMP_API_KEY` and/or `BENZINGA_API_KEY` in `.env` for real-time rankings.")
        else:
            st.subheader("🏆 Real-Time Rankings")
            st.caption(f"**{_session_label_rank}** — All movers ranked by absolute price change %. Combines FMP + Benzinga + RT Spike data.")

            # Build unified symbol map (same data as Movers, re-sorted by abs change)
            _rank_all: dict[str, dict[str, Any]] = {}

            # 1) FMP gainers/losers/actives
            if fmp_key_rank:
                _fmp_rank = _cached_spike_data(fmp_key_rank)
                for _src_list in [_fmp_rank["gainers"], _fmp_rank["losers"], _fmp_rank["actives"]]:
                    for item in _src_list:
                        sym = (item.get("symbol") or "").upper().strip()
                        if not sym:
                            continue
                        price = _safe_float_mov(item.get("price"))
                        chg_pct = _safe_float_mov(item.get("changesPercentage"))
                        chg = _safe_float_mov(item.get("change"))
                        vol = int(_safe_float_mov(item.get("volume")))
                        name = item.get("name") or item.get("companyName") or ""
                        mkt_cap = item.get("marketCap") or ""
                        existing = _rank_all.get(sym)
                        if not existing or abs(chg_pct) > abs(existing.get("chg_pct", 0)):
                            _rank_all[sym] = {
                                "symbol": sym, "name": name[:50],
                                "price": price, "change": chg, "chg_pct": chg_pct,
                                "volume": vol, "mkt_cap": mkt_cap,
                            }

            # 2) Benzinga movers
            if bz_key_rank:
                _bz_rank = _cached_bz_movers(bz_key_rank)
                for _bz_list in [_bz_rank.get("gainers", []), _bz_rank.get("losers", [])]:
                    for item in _bz_list:
                        sym = (item.get("symbol") or item.get("ticker") or "").upper().strip()
                        if not sym:
                            continue
                        price = _safe_float_mov(item.get("price") or item.get("last"))
                        chg_pct = _safe_float_mov(item.get("changePercent") or item.get("change_percent"))
                        chg = _safe_float_mov(item.get("change"))
                        vol = int(_safe_float_mov(item.get("volume")))
                        name = item.get("companyName") or item.get("company_name") or ""
                        mkt_cap = item.get("marketCap") or item.get("market_cap") or ""
                        sector = item.get("gicsSectorName") or item.get("sector") or ""
                        existing = _rank_all.get(sym)
                        if not existing or (_current_session in ("pre-market", "after-hours")):
                            _rank_all[sym] = {
                                "symbol": sym, "name": name[:50],
                                "price": price, "change": chg, "chg_pct": chg_pct,
                                "volume": vol, "mkt_cap": mkt_cap, "sector": sector,
                            }

            # 3) RT spike events
            _detector_rank: SpikeDetector = st.session_state.spike_detector
            for ev in _detector_rank.events[:50]:
                sym = ev.symbol
                existing = _rank_all.get(sym)
                if not existing or abs(ev.spike_pct) > abs(existing.get("chg_pct", 0)):
                    _rank_all[sym] = {
                        "symbol": sym, "name": ev.name[:50],
                        "price": ev.price, "change": ev.change, "chg_pct": ev.spike_pct,
                        "volume": ev.volume, "mkt_cap": "",
                    }

            if not _rank_all:
                st.info("No ranking data available yet.")
            else:
                # ── Merge news scores from feed ─────────────────────
                _news_by_ticker: dict[str, dict[str, Any]] = {}
                for _ni in feed:
                    _nticker = (_ni.get("ticker") or "").upper().strip()
                    if not _nticker or _nticker == "MARKET":
                        continue
                    _nscore = _safe_float_mov(_ni.get("composite_score"))
                    _existing_news = _news_by_ticker.get(_nticker)
                    if not _existing_news or _nscore > _safe_float_mov(_existing_news.get("news_score")):
                        _news_by_ticker[_nticker] = {
                            "news_score": _nscore,
                            "headline": (_ni.get("headline") or "")[:120],
                            "url": _ni.get("url") or "",
                            "sentiment": _ni.get("sentiment_label") or "",
                        }

                # Enrich _rank_all with news data
                _news_match_count = 0
                for sym, row in _rank_all.items():
                    news = _news_by_ticker.get(sym)
                    if news:
                        row["news_score"] = news["news_score"]
                        row["headline"] = news["headline"]
                        row["url"] = news["url"]
                        row["sentiment"] = news["sentiment"]
                        _news_match_count += 1
                    else:
                        row["news_score"] = 0.0
                        row["headline"] = ""
                        row["url"] = ""
                        row["sentiment"] = ""

                # Composite ranking: 70% price move + 30% news score
                # news_score is typically 0-1, scale to comparable range
                def _composite_score(r: dict[str, Any]) -> float:
                    _chg = float(r.get("chg_pct") or 0)
                    _ns = float(r.get("news_score") or 0)
                    return abs(_chg) * 0.7 + _ns * 100.0 * 0.3

                _ranked = sorted(
                    _rank_all.values(),
                    key=_composite_score,
                    reverse=True,
                )

                top_n = min(50, len(_ranked))
                _rank_rows = []
                for i, m in enumerate(_ranked[:top_n], 1):
                    _dir = "🟢" if m.get("chg_pct", 0) > 0 else "🔴" if m.get("chg_pct", 0) < 0 else "⚪"
                    _sent_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(
                        (m.get("sentiment") or "").lower(), ""
                    )
                    _hl_url = m.get("url", "")
                    _hl_text = m.get("headline", "")
                    _rank_rows.append({
                        "#": i,
                        "": _dir,
                        "Symbol": m["symbol"],
                        "Name": m.get("name", ""),
                        "Price": f"${m['price']:.2f}" if m["price"] >= 1 else f"${m['price']:.4f}",
                        "Change": f"{m['change']:+.2f}",
                        "Change %": f"{m['chg_pct']:+.2f}%",
                        "Score": round(_composite_score(m), 2),
                        "News": f"{m.get('news_score', 0):.3f}" if m.get("news_score") else "",
                        "Sentiment": f"{_sent_icon} {m.get('sentiment', '')}" if m.get("sentiment") else "",
                        "Headline": _hl_url if _hl_url else _hl_text,
                        "Volume": f"{m['volume']:,}" if m.get("volume") else "",
                    })

                df_rank = pd.DataFrame(_rank_rows)
                df_rank = df_rank.set_index("#")

                st.caption(
                    f"Top {top_n} of {len(_ranked)} symbols — "
                    f"composite rank (70% price move + 30% news score) · "
                    f"{_news_match_count} with news"
                )

                # Build column config
                _rank_col_cfg: dict[str, Any] = {
                    "": st.column_config.TextColumn("", width="small"),
                    "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                    "Change %": st.column_config.TextColumn("Change %", width="small"),
                    "Score": st.column_config.NumberColumn("Score", width="small"),
                    "News": st.column_config.TextColumn("News", width="small"),
                }
                # Use LinkColumn for headlines when URLs are present
                if any(r.get("Headline", "").startswith("http") for r in _rank_rows):
                    _rank_col_cfg["Headline"] = st.column_config.LinkColumn(
                        "Headline",
                        display_text=r"https?://[^/]+/(.{0,60}).*",
                        width="large",
                    )

                st.dataframe(
                    df_rank,
                    width='stretch',
                    height=min(800, 40 + 35 * len(df_rank)),
                    column_config=_rank_col_cfg,
                )

    # ── TAB: Segments ───────────────────────────────────────
    with tab_segments:
        seg_rows = aggregate_segments(feed)

        if not seg_rows:
            st.info("No segment data yet. Channels are populated by Benzinga articles.")
        else:
            # ── Overview table ──────────────────────────────────────
            summary_data = build_segment_summary_rows(seg_rows)

            st.caption(f"{len(seg_rows)} segments across {len(feed)} articles")
            df_seg = pd.DataFrame(summary_data)
            df_seg.index = df_seg.index + 1
            st.dataframe(df_seg, width='stretch', height=min(400, 40 + 35 * len(df_seg)))

            st.divider()

            # ── Per-segment drill-down ──────────────────────────────
            leading, neutral_segs, lagging = split_segments_by_sentiment(seg_rows)

            scols = st.columns(3)
            with scols[0]:
                st.markdown("**🟢 Bullish Segments**")
                if not leading:
                    st.caption("None")
                for r in leading[:8]:
                    st.markdown(f"**{safe_markdown_text(r['segment'])}** — {r['articles']} articles, avg {r['avg_score']:.3f}")
            with scols[1]:
                st.markdown("**🟡 Neutral Segments**")
                if not neutral_segs:
                    st.caption("None")
                for r in neutral_segs[:8]:
                    st.markdown(f"{safe_markdown_text(r['segment'])} — {r['articles']} articles, avg {r['avg_score']:.3f}")
            with scols[2]:
                st.markdown("**🔴 Bearish Segments**")
                if not lagging:
                    st.caption("None")
                for r in lagging[:8]:
                    st.markdown(f"**{safe_markdown_text(r['segment'])}** — {r['articles']} articles, avg {r['avg_score']:.3f}")

            st.divider()

            # ── Detailed drill-down per segment (top 40 symbols each)
            st.subheader("Top Symbols per Segment")
            for r in seg_rows:
                ticker_map = r["_ticker_map"]
                sorted_tks = sorted(
                    ticker_map.values(),
                    key=lambda x: x.get("news_score", 0),
                    reverse=True,
                )[:40]

                with st.expander(f"{r['sentiment']} **{r['segment']}** — {r['tickers']} tickers, {r['articles']} articles"):
                    tk_rows = []
                    for d in sorted_tks:
                        sent_label = d.get("sentiment_label", "neutral")
                        raw_headline = (d.get("headline", "") or "")[:120]
                        article_url = d.get("url", "")
                        headline_display = (
                            f"[{raw_headline}]({article_url})"
                            if article_url
                            else raw_headline
                        )
                        tk_rows.append({
                            "Symbol": d.get("ticker", "?"),
                            "Score": round(d.get("news_score", 0), 4),
                            "Sentiment": _SENTIMENT_COLORS.get(sent_label, "🟡") + " " + sent_label,
                            "Event": d.get("event_label", ""),
                            "Materiality": d.get("materiality", ""),
                            "Headline": headline_display,
                        })
                    if tk_rows:
                        df_tk = pd.DataFrame(tk_rows)
                        df_tk.index = df_tk.index + 1
                        st.dataframe(
                            df_tk,
                            width='stretch',
                            height=min(1000, 40 + 35 * len(df_tk)),
                            column_config={
                                "Headline": st.column_config.LinkColumn(
                                    "Headline",
                                    display_text=r"(.*)",
                                ),
                            },
                        )
                    else:
                        st.caption("No ticker data")

    # ── TAB: RT Price Spikes (real-time detector) ───────────
    with tab_rt_spikes:
        fmp_key_rt = st.session_state.cfg.fmp_api_key
        if not fmp_key_rt:
            st.info("Set `FMP_API_KEY` in `.env` for real-time price spike detection.")
        else:
            st.subheader("⚡ Real-Time Price Spikes")
            _session_label_rt = _session_icons.get(_current_session, _current_session)
            st.caption(
                f"**{_session_label_rt}** — Detecting rapid price moves (≥1% within 60 s). "
                "Updates every refresh cycle."
            )

            # Feed current quotes into the detector
            _rt_spike_data = _cached_spike_data(fmp_key_rt)
            _rt_all_quotes: list[dict[str, Any]] = (
                list(_rt_spike_data["gainers"])
                + list(_rt_spike_data["losers"])
                + list(_rt_spike_data["actives"])
            )
            _detector: SpikeDetector = st.session_state.spike_detector
            _new_spikes = _detector.update(_rt_all_quotes)

            # Diagnostics
            _rt_diag_col1, _rt_diag_col2, _rt_diag_col3, _rt_diag_col4 = st.columns(4)
            _rt_events = _detector.events
            _rt_up = sum(1 for e in _rt_events if e.direction == "UP")
            _rt_dn = sum(1 for e in _rt_events if e.direction == "DOWN")
            _rt_diag_col1.metric("Total Spikes", len(_rt_events))
            _rt_diag_col2.metric("🟢 Spike UP", _rt_up)
            _rt_diag_col3.metric("🔴 Spike DOWN", _rt_dn)
            _rt_diag_col4.metric("Symbols Tracked", _detector.symbols_tracked)

            if _new_spikes:
                st.success(
                    f"🆕 {len(_new_spikes)} new spike(s) detected: "
                    + ", ".join(f"{e.icon} {e.symbol} {e.spike_pct:+.1f}%" for e in _new_spikes)
                )

            if not _rt_events:
                st.info(
                    "No spikes detected yet. The detector needs at least 2 poll cycles "
                    "(~60 s apart) to compare prices. Keep the terminal refreshing."
                )
            else:
                # Build display table matching Benzinga Pro layout
                _rt_rows = []
                for ev in _rt_events:
                    _rt_rows.append({
                        "Signal": f"{ev.icon} Price Spike {ev.direction}",
                        "Symbol": ev.symbol,
                        "Time": format_time_et(ev.ts),
                        "Spike %": f"{ev.spike_pct:+.2f}%",
                        "Type": ev.asset_type,
                        "Description": format_spike_description(ev),
                        "Quote": f"${ev.price:.2f}" if ev.price >= 1 else f"${ev.price:.4f}",
                        "Day Chg": f"{ev.change:+.2f}",
                        "Day Chg %": f"{ev.change_pct:+.4f}%",
                    })

                _df_rt = pd.DataFrame(_rt_rows)
                _df_rt.index = _df_rt.index + 1

                st.dataframe(
                    _df_rt,
                    width='stretch',
                    height=min(800, 40 + 35 * len(_df_rt)),
                    column_config={
                        "Signal": st.column_config.TextColumn("Signal", width="medium"),
                        "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                        "Time": st.column_config.TextColumn("Time", width="small"),
                        "Spike %": st.column_config.TextColumn("Spike %", width="small"),
                        "Description": st.column_config.TextColumn("Description", width="large"),
                    },
                )

                # Age distribution
                st.divider()
                _age_col1, _age_col2 = st.columns(2)
                with _age_col1:
                    st.caption(
                        f"📊 Polls: {_detector.poll_count} · "
                        f"Total spikes ever: {_detector.total_spikes_detected}"
                    )
                with _age_col2:
                    if _rt_events:
                        _newest = _rt_events[0].age_s
                        _oldest = _rt_events[-1].age_s
                        st.caption(
                            f"Newest: {_newest:.0f}s ago · Oldest: {_oldest / 60:.1f}m ago"
                        )

    # ── TAB: Spikes (daily change scanner) ──────────────────
    with tab_spikes:
        fmp_key = st.session_state.cfg.fmp_api_key
        if not fmp_key:
            st.info("Set `FMP_API_KEY` in `.env` for price & volume spike screening.")
        else:
            st.subheader("🚨 Price & Volume Spike Scanner")

            # Market session indicator
            _session_label = _session_icons.get(_current_session, _current_session)

            if _current_session in ("pre-market", "after-hours"):
                st.caption(
                    f"**{_session_label}** — FMP gainers/losers show previous session. "
                    "Extended-hours prices overlaid from Benzinga delayed quotes."
                )
            elif _current_session == "closed":
                st.caption(
                    f"**{_session_label}** — Showing last session data."
                )
            else:
                st.caption(
                    f"**{_session_label}** — Live screening for rapid price moves "
                    "and unusual volume. Data from FMP. Refreshes every 30 s."
                )

            # Fetch cached spike data
            spike_data = _cached_spike_data(fmp_key)
            spike_rows = build_spike_rows(
                spike_data["gainers"],
                spike_data["losers"],
                spike_data["actives"],
            )

            # Overlay Benzinga extended-hours quotes when outside regular session
            if _current_session in ("pre-market", "after-hours") and spike_rows:
                bz_key = st.session_state.cfg.benzinga_api_key
                if bz_key:
                    _spike_symbols = sorted(r["symbol"] for r in spike_rows)
                    _bz_quotes = _cached_bz_quotes(bz_key, ",".join(_spike_symbols))
                    if _bz_quotes:
                        overlay_extended_hours_quotes(spike_rows, _bz_quotes)

            # Filter controls
            sp_col1, sp_col2, sp_col3, sp_col4 = st.columns(4)
            with sp_col1:
                sp_direction = st.selectbox(
                    "Direction", ["all", "UP", "DOWN"],
                    key="spike_dir",
                )
            with sp_col2:
                sp_min_chg = st.slider(
                    "Min |Change| %", 0.0, 20.0, 1.0, 0.5,
                    key="spike_min_chg",
                )
            with sp_col3:
                sp_asset = st.selectbox(
                    "Asset Type", ["all", "STOCK", "ETF"],
                    key="spike_asset",
                )
            with sp_col4:
                sp_vol_only = st.checkbox(
                    "Volume Spikes Only", value=False,
                    key="spike_vol_only",
                )

            filtered_spikes = filter_spike_rows(
                spike_rows,
                direction=sp_direction,
                min_change_pct=sp_min_chg,
                asset_type=sp_asset,
                vol_spike_only=sp_vol_only,
            )

            # Summary metrics
            _up_count = sum(1 for r in filtered_spikes if r["spike_dir"] == "UP")
            _dn_count = sum(1 for r in filtered_spikes if r["spike_dir"] == "DOWN")
            _vol_count = sum(1 for r in filtered_spikes if r["vol_spike"])

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Signals", len(filtered_spikes))
            m2.metric("🟢 Price Spike UP", _up_count)
            m3.metric("🔴 Price Spike DOWN", _dn_count)
            m4.metric("📊 Volume Spikes", _vol_count)

            if not filtered_spikes:
                st.info("No spikes matching current filters.")
            else:
                # Build display DataFrame
                display_rows = []
                for r in filtered_spikes:
                    display_rows.append({
                        "Signal": f"{r['spike_icon']} Price Spike {r['spike_dir']}" if r["spike_dir"] else (
                            f"{r['vol_icon']} Volume Spike" if r["vol_spike"] else "Active"
                        ),
                        "Symbol": r["symbol"],
                        "Name": r["name"],
                        "Price": f"${r['price']:.2f}",
                        "Change %": r["change_display"],
                        "Change": f"{r['change']:+.2f}",
                        "Volume": f"{r['volume']:,}",
                        "Vol Ratio": f"{r['volume_ratio']:.1f}x" if r["volume_ratio"] > 0 else "—",
                        "Mkt Cap": r["mktcap_display"],
                        "Type": r["asset_type"],
                    })

                df_spikes = pd.DataFrame(display_rows)
                df_spikes.index = df_spikes.index + 1

                st.dataframe(
                    df_spikes,
                    width='stretch',
                    height=min(800, 40 + 35 * len(df_spikes)),
                )

                # ── Detail cards for top 10 ──────────────────────
                st.divider()
                st.subheader("Top Spike Details")
                for r in filtered_spikes[:10]:
                    _sig = r["spike_dir"] or "VOL"
                    _icon = r["spike_icon"]
                    with st.container():
                        c1, c2 = st.columns([2, 8])
                        with c1:
                            st.markdown(f"### {r['symbol']}")
                            st.markdown(f"{_icon} **{_sig}** {r['change_display']}")
                            if r["vol_spike"]:
                                st.markdown(f"📊 Vol: **{r['volume_ratio']:.1f}x** avg")
                        with c2:
                            st.markdown(f"**{safe_markdown_text(r['name'])}**")
                            st.markdown(
                                f"Price: **${r['price']:.2f}** | "
                                f"Change: {r['change']:+.2f} | "
                                f"Mkt Cap: {r['mktcap_display']} | "
                                f"Type: {r['asset_type']}"
                            )
                            st.markdown(
                                f"Volume: {r['volume']:,} | "
                                f"Avg Volume: {r['avg_volume']:,} | "
                                f"Ratio: {r['volume_ratio']:.1f}x"
                            )
                        st.divider()

    # ── TAB: Sector Heatmap (treemap) ───────────────────────
    with tab_heatmap:
        try:
            import plotly.express as px  # type: ignore

            hm_data = build_heatmap_data(feed)

            if hm_data:
                df_hm = pd.DataFrame(hm_data)

                # Color by sentiment: bullish=green, bearish=red
                color_map = {"bullish": "#00C853", "neutral": "#FFC107", "bearish": "#FF1744"}

                fig = px.treemap(
                    df_hm,
                    path=["sector", "ticker"],
                    values="articles",
                    color="sentiment",
                    color_discrete_map=color_map,
                    hover_data=["score", "articles"],
                    title="Sector × Ticker Heatmap (article count, colored by sentiment)",
                )
                fig.update_layout(
                    height=600,
                    margin=dict(t=40, l=0, r=0, b=0),
                    paper_bgcolor="#0E1117",
                    font_color="white",
                )
                st.plotly_chart(fig, width='stretch')
            else:
                st.info("No segment data available for heatmap.")

            # ── FMP Sector Performance ──────────────────────────────
            fmp_key = st.session_state.cfg.fmp_api_key
            if fmp_key:
                st.subheader("📊 Market Sector Performance (FMP)")
                if _current_session in ("pre-market", "after-hours"):
                    st.caption(
                        f"**{_session_icons.get(_current_session, _current_session)}** — "
                        "FMP sector data shows previous regular session."
                    )
                elif _current_session == "closed":
                    st.caption("**⚫ Market Closed** — Showing last session sector data.")
                sector_data = _cached_sector_perf(fmp_key)
                if sector_data:
                    df_sp = pd.DataFrame(sector_data)
                    if "changesPercentage" in df_sp.columns and "sector" in df_sp.columns:
                        df_sp["changesPercentage"] = pd.to_numeric(
                            df_sp["changesPercentage"].astype(str).str.rstrip("%"),
                            errors="coerce",
                        )
                        df_sp = df_sp.sort_values("changesPercentage", ascending=False)

                        fig_sp = px.bar(
                            df_sp, x="sector", y="changesPercentage",
                            color="changesPercentage",
                            color_continuous_scale=["#FF1744", "#FFC107", "#00C853"],
                            title="Sector Performance (%)",
                        )
                        fig_sp.update_layout(
                            height=350,
                            paper_bgcolor="#0E1117",
                            plot_bgcolor="#0E1117",
                            font_color="white",
                            xaxis_tickangle=-45,
                        )
                        st.plotly_chart(fig_sp, width='stretch')
                    else:
                        st.dataframe(df_sp, width='stretch')
                else:
                    st.caption("No sector data returned from FMP.")
            else:
                st.caption("Set FMP_API_KEY for live sector performance.")

        except ImportError:
            st.warning("Install `plotly` for heatmap: `pip install plotly`")

    # ── TAB: Economic Calendar ──────────────────────────────
    with tab_calendar:
        fmp_key = st.session_state.cfg.fmp_api_key
        if not fmp_key:
            st.info("Set `FMP_API_KEY` in `.env` for economic calendar data.")
        else:
            st.subheader("📅 Economic Calendar")

            cal_col1, cal_col2 = st.columns(2)
            with cal_col1:
                cal_from = st.date_input(
                    "From", value=datetime.now(UTC).date(),
                    key="cal_from",
                )
            with cal_col2:
                cal_to = st.date_input(
                    "To", value=datetime.now(UTC).date() + timedelta(days=7),
                    key="cal_to",
                )

            cal_data = _cached_econ_calendar(
                fmp_key,
                from_date=cal_from.strftime("%Y-%m-%d"),
                to_date=cal_to.strftime("%Y-%m-%d"),
            )

            if cal_data:
                df_cal = pd.DataFrame(cal_data)

                # Normalise column names: stable API uses "estimate", legacy used "consensus"
                if "estimate" in df_cal.columns and "consensus" not in df_cal.columns:
                    df_cal = df_cal.rename(columns={"estimate": "consensus"})

                # Filter to major events
                impact_filter = st.selectbox(
                    "Impact filter", ["all", "High", "Medium", "Low"],
                    key="cal_impact",
                )

                display_cols = [c for c in [
                    "date", "country", "event", "impact",
                    "actual", "previous", "consensus", "change",
                ] if c in df_cal.columns]

                if impact_filter != "all" and "impact" in df_cal.columns:
                    df_cal = df_cal[df_cal["impact"].str.lower() == impact_filter.lower()]

                st.caption(f"{len(df_cal)} economic events from {cal_from} to {cal_to}")
                st.dataframe(
                    df_cal[display_cols] if display_cols else df_cal,
                    width='stretch',
                    height=min(600, 40 + 35 * len(df_cal)),
                )

                # ── Upcoming highlights ─────────────────────────────
                now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
                upcoming = df_cal[df_cal["date"] >= now_str] if "date" in df_cal.columns else pd.DataFrame()
                if not upcoming.empty:
                    st.subheader("⏰ Upcoming")
                    for _, row in upcoming.head(10).iterrows():
                        impact = row.get("impact", "")
                        impact_icon = "🔴" if impact == "High" else ("🟠" if impact == "Medium" else "🟡")
                        _ev = safe_markdown_text(str(row.get('event', '?')))
                        st.markdown(
                            f"{impact_icon} **{_ev}** — "
                            f"{row.get('country', '?')} | {row.get('date', '?')} | "
                            f"Prev: {row.get('previous', '?')} | Cons: {row.get('consensus', '?')}"
                        )
            else:
                st.info("No calendar events found for the selected range.")

    # ── TAB: Benzinga Intel (Ratings + Earnings + Economics) ─
    with tab_bz_cal:
        bz_key = st.session_state.cfg.benzinga_api_key
        if not bz_key:
            st.info("Set `BENZINGA_API_KEY` in `.env` for Benzinga calendar data.")
        else:
            st.subheader("📊 Benzinga Intelligence")
            st.caption("Full Benzinga data suite: Ratings, Earnings, Economics, Conference Calls, Dividends, Splits, IPOs, Guidance, Retail, Top News, Quantified News, Options Flow, Insider Trades, Power Gaps, Channel Browser")

            bz_cal_col1, bz_cal_col2 = st.columns(2)
            with bz_cal_col1:
                bz_cal_from = st.date_input(
                    "From", value=datetime.now(UTC).date(),
                    key="bz_cal_from",
                )
            with bz_cal_col2:
                bz_cal_to = st.date_input(
                    "To", value=datetime.now(UTC).date() + timedelta(days=7),
                    key="bz_cal_to",
                )

            bz_from_str = bz_cal_from.strftime("%Y-%m-%d")
            bz_to_str = bz_cal_to.strftime("%Y-%m-%d")

            # ── Sub-tabs for all Benzinga data types ───────
            (bz_sub_ratings, bz_sub_earnings, bz_sub_econ, bz_sub_conf,
             bz_sub_divs,
             bz_sub_splits, bz_sub_ipos, bz_sub_guidance, bz_sub_retail,
             bz_sub_top_news, bz_sub_quantified, bz_sub_options,
             bz_sub_insider, bz_sub_power_gaps, bz_sub_channels) = st.tabs(
                ["🎯 Ratings", "💰 Earnings", "🌐 Economics",
                 "📞 Conf Calls",
                 "💵 Dividends", "✂️ Splits", "🚀 IPOs",
                 "🔮 Guidance", "🛒 Retail", "📰 Top News",
                 "📈 Quantified", "🎰 Options Flow",
                 "🔍 Insider Trades", "⚡ Power Gaps",
                 "📡 Channel Browser"],
            )

            # ── Analyst Ratings ─────────────────────────────
            with bz_sub_ratings:
                ratings_data = _cached_bz_ratings(bz_key, bz_from_str, bz_to_str)
                if ratings_data:
                    df_rat = pd.DataFrame(ratings_data)

                    # Action filter
                    actions = sorted(set(str(r.get("action_company", "")).strip() for r in ratings_data if r.get("action_company")))
                    rat_action = st.selectbox("Action Filter", ["all"] + actions, key="bz_rat_action")

                    display_cols = [c for c in [
                        "ticker", "date", "action_company", "action_pt",
                        "analyst_name", "rating_current", "rating_prior",
                        "pt_current", "pt_prior", "importance",
                    ] if c in df_rat.columns]

                    if rat_action != "all" and "action_company" in df_rat.columns:
                        df_rat = df_rat[df_rat["action_company"] == rat_action]

                    st.caption(f"{len(df_rat)} analyst rating(s) from {bz_from_str} to {bz_to_str}")

                    # Highlight upgrades/downgrades
                    def _color_action(val: str) -> str:
                        val_lower = str(val).lower()
                        if "upgrade" in val_lower or "initiate" in val_lower:
                            return "color: #00C853"
                        if "downgrade" in val_lower:
                            return "color: #FF1744"
                        return ""

                    df_display = df_rat[display_cols] if display_cols else df_rat
                    if "action_company" in df_display.columns:
                        styled_rat = df_display.style.map(_color_action, subset=["action_company"])
                        st.dataframe(styled_rat, width='stretch', height=min(600, 40 + 35 * len(df_display)))
                    else:
                        st.dataframe(df_display, width='stretch', height=min(600, 40 + 35 * len(df_display)))

                    # ── Key upgrades/downgrades summary ─────
                    upgrades = [r for r in ratings_data if "upgrade" in str(r.get("action_company", "")).lower()]
                    downgrades = [r for r in ratings_data if "downgrade" in str(r.get("action_company", "")).lower()]

                    if upgrades or downgrades:
                        st.divider()
                        st.subheader("⚡ Key Rating Changes")
                        rc1, rc2 = st.columns(2)
                        with rc1:
                            st.markdown("**🟢 Upgrades**")
                            for r in upgrades[:10]:
                                pt_cur = r.get("pt_current", "?")
                                pt_pri = r.get("pt_prior", "?")
                                _tk = safe_markdown_text(str(r.get("ticker", "?")))
                                _analyst = safe_markdown_text(str(r.get("analyst_name", "?")))
                                st.markdown(
                                    f"**{_tk}** — {_analyst} | "
                                    f"{r.get('rating_prior', '?')} → {r.get('rating_current', '?')} | "
                                    f"PT: ${pt_pri} → ${pt_cur}"
                                )
                        with rc2:
                            st.markdown("**🔴 Downgrades**")
                            for r in downgrades[:10]:
                                pt_cur = r.get("pt_current", "?")
                                pt_pri = r.get("pt_prior", "?")
                                _tk = safe_markdown_text(str(r.get("ticker", "?")))
                                _analyst = safe_markdown_text(str(r.get("analyst_name", "?")))
                                st.markdown(
                                    f"**{_tk}** — {_analyst} | "
                                    f"{r.get('rating_prior', '?')} → {r.get('rating_current', '?')} | "
                                    f"PT: ${pt_pri} → ${pt_cur}"
                                )
                else:
                    st.info("No analyst ratings found for the selected range.")

            # ── Earnings Calendar ───────────────────────────
            with bz_sub_earnings:
                earnings_data = _cached_bz_earnings(bz_key, bz_from_str, bz_to_str)
                if earnings_data:
                    df_earn = pd.DataFrame(earnings_data)

                    # Period filter
                    periods = sorted(set(str(r.get("period", "")).strip() for r in earnings_data if r.get("period")))
                    earn_period = st.selectbox("Period Filter", ["all"] + periods, key="bz_earn_period")

                    display_cols = [c for c in [
                        "ticker", "date", "period", "period_year",
                        "eps", "eps_est", "eps_prior", "eps_surprise", "eps_surprise_percent",
                        "revenue", "revenue_est", "revenue_prior", "revenue_surprise",
                        "importance",
                    ] if c in df_earn.columns]

                    if earn_period != "all" and "period" in df_earn.columns:
                        df_earn = df_earn[df_earn["period"] == earn_period]

                    st.caption(f"{len(df_earn)} earnings report(s) from {bz_from_str} to {bz_to_str}")

                    # Highlight beats/misses
                    def _color_surprise(val: Any) -> str:
                        try:
                            v = float(val)
                            if v > 0:
                                return "color: #00C853"
                            if v < 0:
                                return "color: #FF1744"
                        except (ValueError, TypeError):
                            pass
                        return ""

                    df_display = df_earn[display_cols] if display_cols else df_earn
                    surprise_cols = [c for c in ["eps_surprise", "eps_surprise_percent", "revenue_surprise"] if c in df_display.columns]
                    if surprise_cols:
                        styled_earn = df_display.style.map(_color_surprise, subset=surprise_cols)
                        st.dataframe(styled_earn, width='stretch', height=min(600, 40 + 35 * len(df_display)))
                    else:
                        st.dataframe(df_display, width='stretch', height=min(600, 40 + 35 * len(df_display)))

                    # ── Upcoming earnings highlight ─────────
                    now_str = datetime.now(UTC).strftime("%Y-%m-%d")
                    upcoming = df_earn[df_earn["date"] >= now_str] if "date" in df_earn.columns else pd.DataFrame()
                    if not upcoming.empty:
                        st.divider()
                        st.subheader("⏰ Upcoming Earnings")
                        for _, row in upcoming.head(15).iterrows():
                            imp = row.get("importance", 0)
                            imp_icon = "🔴" if imp and int(imp) >= 4 else ("🟠" if imp and int(imp) >= 2 else "🟡")
                            _tk = safe_markdown_text(str(row.get("ticker", "?")))
                            st.markdown(
                                f"{imp_icon} **{_tk}** — {row.get('date', '?')} | "
                                f"{row.get('period', '?')} {row.get('period_year', '')} | "
                                f"EPS est: {row.get('eps_est', '?')} | Rev est: {row.get('revenue_est', '?')}"
                            )
                else:
                    st.info("No earnings data found for the selected range.")

            # ── Benzinga Economics ──────────────────────────
            with bz_sub_econ:
                econ_data = _cached_bz_economics(bz_key, bz_from_str, bz_to_str)
                if econ_data:
                    df_econ = pd.DataFrame(econ_data)

                    # Country filter
                    countries = sorted(set(str(r.get("country", "")).strip() for r in econ_data if r.get("country")))
                    econ_country = st.selectbox("Country Filter", ["all"] + countries, key="bz_econ_country")

                    # Importance filter
                    econ_imp = st.selectbox("Min Importance", ["all", "1", "2", "3", "4", "5"], key="bz_econ_imp")

                    display_cols = [c for c in [
                        "date", "time", "country", "event_name",
                        "actual", "consensus", "prior", "importance",
                    ] if c in df_econ.columns]

                    if econ_country != "all" and "country" in df_econ.columns:
                        df_econ = df_econ[df_econ["country"] == econ_country]
                    if econ_imp != "all" and "importance" in df_econ.columns:
                        df_econ = df_econ[pd.to_numeric(df_econ["importance"], errors="coerce") >= int(econ_imp)]

                    st.caption(f"{len(df_econ)} economic event(s) from {bz_from_str} to {bz_to_str}")

                    # Highlight beats/misses vs consensus
                    def _color_vs_consensus(row: pd.Series) -> list[str]:
                        styles = [""] * len(row)
                        try:
                            actual = float(row.get("actual", ""))
                            cons = float(row.get("consensus", ""))
                            idx = list(row.index).index("actual") if "actual" in row.index else -1
                            if idx >= 0:
                                if actual > cons:
                                    styles[idx] = "color: #00C853"
                                elif actual < cons:
                                    styles[idx] = "color: #FF1744"
                        except (ValueError, TypeError):
                            pass
                        return styles

                    df_display = df_econ[display_cols] if display_cols else df_econ
                    if "actual" in df_display.columns and "consensus" in df_display.columns:
                        styled_econ = df_display.style.apply(_color_vs_consensus, axis=1)
                        st.dataframe(styled_econ, width='stretch', height=min(600, 40 + 35 * len(df_display)))
                    else:
                        st.dataframe(df_display, width='stretch', height=min(600, 40 + 35 * len(df_display)))

                    # Upcoming events
                    now_str = datetime.now(UTC).strftime("%Y-%m-%d")
                    upcoming = df_econ[df_econ["date"] >= now_str] if "date" in df_econ.columns else pd.DataFrame()
                    if not upcoming.empty:
                        st.divider()
                        st.subheader("⏰ Upcoming Economic Events")
                        for _, row in upcoming.head(10).iterrows():
                            imp = row.get("importance", 0)
                            try:
                                imp_val = int(imp)
                            except (ValueError, TypeError):
                                imp_val = 0
                            imp_icon = "🔴" if imp_val >= 4 else ("🟠" if imp_val >= 2 else "🟡")
                            _ev = safe_markdown_text(str(row.get("event_name", "?")))
                            st.markdown(
                                f"{imp_icon} **{_ev}** — "
                                f"{row.get('country', '?')} | {row.get('date', '?')} {row.get('time', '')} | "
                                f"Prior: {row.get('prior', '?')} | Consensus: {row.get('consensus', '?')}"
                            )
                else:
                    st.info("No Benzinga economic events found for the selected range.")

            # ── Dividends Calendar ──────────────────────────
            with bz_sub_divs:
                div_data = _cached_bz_dividends(bz_key, bz_from_str, bz_to_str)
                if div_data:
                    df_div = pd.DataFrame(div_data)
                    display_cols = [c for c in [
                        "ticker", "name", "date", "ex_date", "payable_date",
                        "record_date", "dividend", "dividend_prior",
                        "dividend_yield", "frequency", "importance",
                    ] if c in df_div.columns]
                    st.caption(f"{len(df_div)} dividend(s) from {bz_from_str} to {bz_to_str}")
                    st.dataframe(
                        df_div[display_cols] if display_cols else df_div,
                        width='stretch',
                        height=min(600, 40 + 35 * len(df_div)),
                    )
                else:
                    st.info("No Benzinga dividend data found for the selected range.")

            # ── Splits Calendar ─────────────────────────────
            with bz_sub_splits:
                splits_data = _cached_bz_splits(bz_key, bz_from_str, bz_to_str)
                if splits_data:
                    df_spl = pd.DataFrame(splits_data)
                    display_cols = [c for c in [
                        "ticker", "exchange", "date", "ratio",
                        "optionable", "date_ex", "date_recorded",
                        "date_distribution", "importance",
                    ] if c in df_spl.columns]
                    st.caption(f"{len(df_spl)} split(s) from {bz_from_str} to {bz_to_str}")
                    st.dataframe(
                        df_spl[display_cols] if display_cols else df_spl,
                        width='stretch',
                        height=min(600, 40 + 35 * len(df_spl)),
                    )
                else:
                    st.info("No Benzinga stock splits found for the selected range.")

            # ── IPO Calendar ────────────────────────────────
            with bz_sub_ipos:
                ipo_data = _cached_bz_ipos(bz_key, bz_from_str, bz_to_str)
                if ipo_data:
                    df_ipo = pd.DataFrame(ipo_data)
                    display_cols = [c for c in [
                        "ticker", "name", "exchange", "pricing_date",
                        "price_min", "price_max", "deal_status",
                        "offering_value", "offering_shares",
                        "lead_underwriters", "importance",
                    ] if c in df_ipo.columns]
                    st.caption(f"{len(df_ipo)} IPO(s) from {bz_from_str} to {bz_to_str}")
                    st.dataframe(
                        df_ipo[display_cols] if display_cols else df_ipo,
                        width='stretch',
                        height=min(600, 40 + 35 * len(df_ipo)),
                    )

                    # Highlight upcoming IPOs
                    now_str = datetime.now(UTC).strftime("%Y-%m-%d")
                    date_col = "pricing_date" if "pricing_date" in df_ipo.columns else "date"
                    if date_col in df_ipo.columns:
                        upcoming = df_ipo[df_ipo[date_col] >= now_str]
                        if not upcoming.empty:
                            st.divider()
                            st.subheader("🚀 Upcoming IPOs")
                            for _, row in upcoming.head(10).iterrows():
                                _tk = safe_markdown_text(str(row.get("ticker", "?")))
                                _nm = safe_markdown_text(str(row.get("name", "")))
                                st.markdown(
                                    f"**{_tk}** {_nm} — "
                                    f"{row.get(date_col, '?')} | "
                                    f"${row.get('price_min', '?')} – ${row.get('price_max', '?')} | "
                                    f"Status: {row.get('deal_status', '?')}"
                                )
                else:
                    st.info("No Benzinga IPO data found for the selected range.")

            # ── Guidance Calendar ───────────────────────────
            with bz_sub_guidance:
                guid_data = _cached_bz_guidance(bz_key, bz_from_str, bz_to_str)
                if guid_data:
                    df_guid = pd.DataFrame(guid_data)
                    display_cols = [c for c in [
                        "ticker", "name", "date", "period", "period_year",
                        "prelim", "eps_guidance_est", "eps_guidance_max",
                        "eps_guidance_min", "revenue_guidance_est",
                        "revenue_guidance_max", "revenue_guidance_min",
                        "importance",
                    ] if c in df_guid.columns]
                    st.caption(f"{len(df_guid)} guidance item(s) from {bz_from_str} to {bz_to_str}")
                    st.dataframe(
                        df_guid[display_cols] if display_cols else df_guid,
                        width='stretch',
                        height=min(600, 40 + 35 * len(df_guid)),
                    )
                else:
                    st.info("No Benzinga guidance data found for the selected range.")

            # ── Retail Sales Calendar ───────────────────────
            with bz_sub_retail:
                retail_data = _cached_bz_retail(bz_key, bz_from_str, bz_to_str)
                if retail_data:
                    df_ret = pd.DataFrame(retail_data)
                    display_cols = [c for c in [
                        "ticker", "name", "date", "period", "period_year",
                        "sss", "sss_est", "retail_surprise", "importance",
                    ] if c in df_ret.columns]
                    st.caption(f"{len(df_ret)} retail item(s) from {bz_from_str} to {bz_to_str}")

                    # Highlight beats/misses
                    def _color_retail_surprise(val: Any) -> str:
                        try:
                            v = float(val)
                            return "color: #00C853" if v > 0 else ("color: #FF1744" if v < 0 else "")
                        except (ValueError, TypeError):
                            return ""

                    df_display = df_ret[display_cols] if display_cols else df_ret
                    surprise_cols = [c for c in ["retail_surprise"] if c in df_display.columns]
                    if surprise_cols:
                        styled = df_display.style.map(_color_retail_surprise, subset=surprise_cols)
                        st.dataframe(styled, width='stretch', height=min(600, 40 + 35 * len(df_display)))
                    else:
                        st.dataframe(df_display, width='stretch', height=min(600, 40 + 35 * len(df_display)))
                else:
                    st.info("No Benzinga retail sales data found for the selected range.")

            # ── Top News ────────────────────────────────────
            with bz_sub_top_news:
                tn_limit = st.selectbox("Max stories", [10, 20, 50], index=1, key="bz_tn_limit")
                top_news = _cached_bz_top_news(bz_key, limit=tn_limit)
                if top_news:
                    st.caption(f"{len(top_news)} curated top stories")
                    for i, story in enumerate(top_news):
                        title = safe_markdown_text(str(story.get("title", "Untitled")))
                        author = story.get("author", "")
                        created = story.get("created", "")
                        url = story.get("url", "")
                        teaser = story.get("teaser", "")
                        stocks = story.get("stocks", [])
                        tickers_str = ", ".join(
                            s.get("name", "") if isinstance(s, dict) else str(s)
                            for s in (stocks if isinstance(stocks, list) else [])
                        )

                        header_parts = [f"**{title}**"]
                        if tickers_str:
                            header_parts.append(f"[{tickers_str}]")
                        if author:
                            header_parts.append(f"— {safe_markdown_text(str(author))}")
                        if created:
                            header_parts.append(f"| {created[:16]}")

                        st.markdown(" ".join(header_parts))
                        if teaser:
                            st.caption(safe_markdown_text(str(teaser)[:200]))
                        if url:
                            st.markdown(f"[Read more]({url})", unsafe_allow_html=True)
                        if i < len(top_news) - 1:
                            st.divider()
                else:
                    st.info("No Benzinga top news available.")

            # ── Quantified News (price-impact context) ──────
            with bz_sub_quantified:
                qn_data = _cached_bz_quantified(bz_key, from_date=bz_from_str, to_date=bz_to_str)
                if qn_data:
                    df_qn = pd.DataFrame(qn_data)
                    st.caption(f"{len(df_qn)} quantified news item(s)")
                    st.dataframe(df_qn, width='stretch', height=min(600, 40 + 35 * len(df_qn)))
                else:
                    st.info("No Benzinga quantified news available for the selected range.")

            # ── Options Activity (unusual flow) ─────────────
            with bz_sub_options:
                opt_ticker = st.text_input(
                    "Ticker(s)", value="AAPL,NVDA,SPY",
                    placeholder="e.g. AAPL,NVDA,SPY",
                    key="bz_opt_ticker",
                )
                if opt_ticker.strip():
                    opt_data = _cached_bz_options_activity(
                        bz_key, opt_ticker.strip(),
                        from_date=bz_from_str, to_date=bz_to_str,
                    )
                    if opt_data:
                        df_opt = pd.DataFrame(opt_data)
                        st.caption(f"{len(df_opt)} options activity record(s)")
                        st.dataframe(df_opt, width='stretch', height=min(600, 40 + 35 * len(df_opt)))
                    else:
                        st.info("No Benzinga options activity found. (Requires Options Activity API access.)")
                else:
                    st.info("Enter ticker(s) above to view options activity.")

            # ── Conference Calls ────────────────────────────
            with bz_sub_conf:
                conf_data = _cached_bz_conference_calls(bz_key, bz_from_str, bz_to_str)
                if conf_data:
                    df_conf = pd.DataFrame(conf_data)
                    display_cols = [c for c in [
                        "ticker", "date", "start_time", "phone",
                        "international_phone", "webcast_url",
                        "period", "period_year", "importance",
                    ] if c in df_conf.columns]
                    st.caption(f"{len(df_conf)} conference call(s) from {bz_from_str} to {bz_to_str}")
                    st.dataframe(
                        df_conf[display_cols] if display_cols else df_conf,
                        width='stretch',
                        height=min(600, 40 + 35 * len(df_conf)),
                    )

                    # Highlight upcoming calls
                    now_str = datetime.now(UTC).strftime("%Y-%m-%d")
                    if "date" in df_conf.columns:
                        upcoming = df_conf[df_conf["date"] >= now_str]
                        if not upcoming.empty:
                            st.divider()
                            st.subheader("📞 Upcoming Conference Calls")
                            for _, row in upcoming.head(10).iterrows():
                                _tk = safe_markdown_text(str(row.get("ticker", "?")))
                                _url = row.get("webcast_url", "")
                                _time = row.get("start_time", "")
                                link_part = f" | [Webcast]({_url})" if _url else ""
                                st.markdown(
                                    f"**{_tk}** — {row.get('date', '?')} {_time} | "
                                    f"{row.get('period', '?')} {row.get('period_year', '')}"
                                    f"{link_part}"
                                )
                else:
                    st.info("No Benzinga conference call data found for the selected range.")

            # ── Insider Trades ──────────────────────────────
            with bz_sub_insider:
                st.caption("SEC Form 4 insider transactions — purchases, sales, grants, and exercises.")

                ins_col1, ins_col2, ins_col3 = st.columns(3)
                with ins_col1:
                    ins_action = st.selectbox(
                        "Transaction Type",
                        ["All", "Purchases (P)", "Sales (S)", "Grants/Awards (A)",
                         "Dispositions (D)", "Exercises (M)"],
                        key="bz_ins_action",
                    )
                with ins_col2:
                    ins_ticker = st.text_input(
                        "Ticker(s)", value="", placeholder="e.g. AAPL,MSFT",
                        key="bz_ins_ticker",
                    ).strip().upper()
                with ins_col3:
                    ins_limit = st.selectbox("Max results", [50, 100, 200, 500], index=1, key="bz_ins_limit")

                # Map display label to API action code
                _action_map = {
                    "All": None,
                    "Purchases (P)": "P",
                    "Sales (S)": "S",
                    "Grants/Awards (A)": "A",
                    "Dispositions (D)": "D",
                    "Exercises (M)": "M",
                }
                api_action = _action_map.get(ins_action)

                ins_data = _cached_bz_insider_transactions(
                    bz_key,
                    date_from=bz_from_str,
                    date_to=bz_to_str,
                    action=api_action,
                    page_size=ins_limit,
                )

                # Client-side ticker filter
                if ins_ticker and ins_data:
                    wanted = {t.strip() for t in ins_ticker.split(",") if t.strip()}
                    ins_data = [r for r in ins_data if str(r.get("ticker", "")).upper() in wanted]

                if ins_data:
                    df_ins = pd.DataFrame(ins_data)

                    # Display columns
                    display_cols = [c for c in [
                        "ticker", "company_name", "owner_name", "owner_title",
                        "transaction_type", "date", "shares_traded",
                        "price_per_share", "total_value", "shares_held",
                    ] if c in df_ins.columns]

                    st.caption(f"{len(df_ins)} insider transaction(s) from {bz_from_str} to {bz_to_str}")
                    st.dataframe(
                        df_ins[display_cols] if display_cols else df_ins,
                        width='stretch',
                        height=min(600, 40 + 35 * len(df_ins)),
                    )

                    # Summary metrics
                    if "total_value" in df_ins.columns:
                        df_ins["_val"] = pd.to_numeric(df_ins["total_value"], errors="coerce")
                        if "transaction_type" in df_ins.columns:
                            buys = df_ins[df_ins["transaction_type"].str.upper().str.contains("P|PURCHASE", na=False)]
                            sells = df_ins[df_ins["transaction_type"].str.upper().str.contains("S|SALE", na=False)]
                        else:
                            buys = pd.DataFrame()
                            sells = pd.DataFrame()
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Total Transactions", len(df_ins))
                        m2.metric("Total Purchases", len(buys))
                        m3.metric("Total Sales", len(sells))
                        total_val = df_ins["_val"].sum()
                        m4.metric("Total Value", f"${total_val:,.0f}" if total_val else "N/A")

                    # Notable transactions (>$100K)
                    if "_val" in df_ins.columns:
                        big = df_ins[df_ins["_val"] >= 100_000].sort_values("_val", ascending=False)
                        if not big.empty:
                            st.divider()
                            st.subheader("🔍 Notable Transactions (≥$100K)")
                            for _, row in big.head(15).iterrows():
                                _tk = safe_markdown_text(str(row.get("ticker", "?")))
                                _name = safe_markdown_text(str(row.get("owner_name", "?")))
                                _title = row.get("owner_title", "")
                                _type = row.get("transaction_type", "?")
                                _val = row.get("_val", 0)
                                _shares = row.get("shares_traded", "?")
                                _date = row.get("date", "?")
                                st.markdown(
                                    f"**{_tk}** — {_name}"
                                    + (f" ({_title})" if _title else "")
                                    + f" | {_type} | {_shares} shares | "
                                    f"${_val:,.0f} | {_date}"
                                )
                else:
                    st.info("No insider transactions found for the selected filters and date range.")

            # ── Power Gap Scanner ───────────────────────────
            with bz_sub_power_gaps:
                st.caption(
                    "Power Gap Scanner — classifies today's movers by combining "
                    "gap %, earnings surprise, and relative volume."
                )
                st.markdown(
                    "| Label | Criteria |\n"
                    "| --- | --- |\n"
                    "| **MPEG** (Monster Power Earning Gap) | Gap ≥ 8%, earnings beat, rel-vol ≥ 2× |\n"
                    "| **PEG** (Power Earning Gap) | Gap ≥ 4%, earnings beat, rel-vol ≥ 1.5× |\n"
                    "| **MG** (Monster Gap) | Gap ≥ 8%, rel-vol ≥ 2× (no earnings req.) |\n"
                    "| **Gap Up / Gap Down** | Significant mover — criteria not met |"
                )
                st.divider()

                power_data = _cached_bz_power_gaps(bz_key)

                if power_data:
                    df_pg = pd.DataFrame(power_data)

                    # Filter controls
                    pg_col1, pg_col2 = st.columns(2)
                    with pg_col1:
                        pg_filter = st.multiselect(
                            "Gap Type",
                            options=["MPEG", "PEG", "MG", "Gap Up", "Gap Down"],
                            default=["MPEG", "PEG", "MG"],
                            key="bz_pg_filter",
                        )
                    with pg_col2:
                        pg_min_gap = st.slider(
                            "Min |Gap %|", 0.0, 30.0, 4.0, 0.5, key="bz_pg_min_gap",
                        )

                    # Apply filters
                    if pg_filter:
                        df_pg = df_pg[df_pg["gap_type"].isin(pg_filter)]
                    df_pg = df_pg[df_pg["gap_pct"].abs() >= pg_min_gap]

                    if not df_pg.empty:
                        # Color-code gap_type
                        display_cols = [c for c in [
                            "gap_type", "symbol", "company_name", "gap_pct",
                            "rel_vol", "has_earnings", "eps_surprise",
                            "eps_surprise_pct", "price", "volume",
                            "avg_volume", "sector",
                        ] if c in df_pg.columns]

                        st.caption(f"{len(df_pg)} classified gap(s)")
                        st.dataframe(
                            df_pg[display_cols] if display_cols else df_pg,
                            width='stretch',
                            height=min(600, 40 + 35 * len(df_pg)),
                        )

                        # Summary metrics
                        m1, m2, m3, m4 = st.columns(4)
                        mpeg_count = len(df_pg[df_pg["gap_type"] == "MPEG"])
                        peg_count = len(df_pg[df_pg["gap_type"] == "PEG"])
                        mg_count = len(df_pg[df_pg["gap_type"] == "MG"])
                        m1.metric("⚡ MPEG", mpeg_count)
                        m2.metric("💡 PEG", peg_count)
                        m3.metric("🔥 Monster Gap", mg_count)
                        m4.metric("Total Gaps", len(df_pg))

                        # Highlight top gaps
                        top_gaps = df_pg[df_pg["gap_type"].isin(["MPEG", "PEG", "MG"])].head(10)
                        if not top_gaps.empty:
                            st.divider()
                            st.subheader("⚡ Notable Power Gaps")
                            for _, row in top_gaps.iterrows():
                                _sym = safe_markdown_text(str(row.get("symbol", "?")))
                                _name = safe_markdown_text(str(row.get("company_name", "")))
                                _type = row.get("gap_type", "?")
                                _gap = row.get("gap_pct", 0)
                                _rv = row.get("rel_vol", 0)
                                _eps = row.get("eps_surprise", 0)
                                _price = row.get("price", 0)
                                _sector = row.get("sector", "")

                                type_emoji = {"MPEG": "⚡", "PEG": "💡", "MG": "🔥"}.get(_type, "📊")
                                direction = "🟢" if _gap > 0 else "🔴"
                                eps_part = f" | EPS surprise: {_eps:+.2f}" if row.get("has_earnings") else ""
                                st.markdown(
                                    f"{type_emoji} **[{_type}]** {direction} **{_sym}** "
                                    f"({_name}) — Gap: {_gap:+.1f}% | "
                                    f"Rel Vol: {_rv:.1f}× | "
                                    f"Price: ${_price}"
                                    f"{eps_part}"
                                    + (f" | {_sector}" if _sector else "")
                                )
                    else:
                        st.info("No gaps match the current filters.")
                else:
                    st.info("No market mover data available. Power Gap Scanner requires active market hours.")

            # ── Channel News Browser ────────────────────────
            with bz_sub_channels:
                st.caption("Browse Benzinga news by channel. Select one or more channels to filter.")
                ch_list = _cached_bz_channel_list(bz_key)
                if ch_list:
                    ch_names = sorted(set(
                        str(c.get("name", "")).strip()
                        for c in ch_list if c.get("name")
                    ))
                    selected_channels = st.multiselect(
                        "Channels",
                        options=ch_names,
                        default=[],
                        placeholder="Pick channels…",
                        key="bz_channel_browser_select",
                    )
                    ch_limit = st.selectbox("Max articles", [20, 50, 100], index=0, key="bz_ch_limit")

                    if selected_channels:
                        ch_csv = ",".join(selected_channels)
                        ch_news = _cached_bz_news_by_channel(bz_key, ch_csv, page_size=ch_limit)
                        if ch_news:
                            st.caption(f"{len(ch_news)} article(s) for: {ch_csv}")
                            for i, art in enumerate(ch_news):
                                _title = safe_markdown_text(str(art.get("title", "Untitled")))
                                _src = art.get("source", "")
                                _url = art.get("url", "")
                                _ts = art.get("published_ts", "")
                                _tickers = art.get("tickers", [])
                                _summary = art.get("summary", "")

                                header = [f"**{_title}**"]
                                if _tickers:
                                    tk_str = ", ".join(str(t) for t in _tickers[:5])
                                    header.append(f"[{tk_str}]")
                                if _src:
                                    header.append(f"— {safe_markdown_text(str(_src))}")
                                if _ts:
                                    header.append(f"| {str(_ts)[:16]}")
                                st.markdown(" ".join(header))
                                if _summary:
                                    st.caption(safe_markdown_text(str(_summary)[:250]))
                                if _url:
                                    st.markdown(f"[Read more]({_url})", unsafe_allow_html=True)
                                if i < len(ch_news) - 1:
                                    st.divider()
                        else:
                            st.info(f"No articles found for: {ch_csv}")
                    else:
                        st.info("Select one or more channels above to browse news.")
                else:
                    st.info("Could not load Benzinga channel list.")

    # ── TAB: Benzinga Market Movers + Quotes ────────────────
    with tab_bz_movers:
        bz_key = st.session_state.cfg.benzinga_api_key
        if not bz_key:
            st.info("Set `BENZINGA_API_KEY` in `.env` for Benzinga market movers & quotes.")
        else:
            st.subheader("💹 Benzinga Market Movers")

            # Session indicator — Benzinga movers are regular-session only
            _bz_mov_session = _current_session
            if _bz_mov_session in ("pre-market", "after-hours"):
                st.caption(
                    f"**{_session_icons.get(_bz_mov_session, _bz_mov_session)}** — "
                    "Movers show previous regular session. "
                    "Use Delayed Quotes below for current extended-hours prices."
                )
            elif _bz_mov_session == "closed":
                st.caption(
                    f"**{_session_icons.get(_bz_mov_session, _bz_mov_session)}** — "
                    "Showing last session movers."
                )
            else:
                st.caption("Real-time market movers from Benzinga. Gainers & Losers with delayed quotes.")

            movers_data = _cached_bz_movers(bz_key)
            gainers = movers_data.get("gainers", [])
            losers = movers_data.get("losers", [])

            # During extended hours, fetch delayed quotes to overlay fresh prices
            _bz_mov_quote_map: dict[str, dict[str, Any]] = {}
            if _bz_mov_session in ("pre-market", "after-hours") and (gainers or losers):
                _mov_syms = sorted({
                    g.get("symbol") or g.get("ticker", "")
                    for g in gainers + losers
                    if g.get("symbol") or g.get("ticker")
                })[:50]
                if _mov_syms:
                    _mov_quotes = _cached_bz_quotes(bz_key, ",".join(_mov_syms))
                    if _mov_quotes:
                        for q in _mov_quotes:
                            s = (q.get("symbol") or "").upper().strip()
                            if s:
                                _bz_mov_quote_map[s] = q

            # Summary metrics
            m1, m2, m3 = st.columns(3)
            m1.metric("🟢 Gainers", len(gainers))
            m2.metric("🔴 Losers", len(losers))
            m3.metric("Total Movers", len(gainers) + len(losers))

            # Gainers table
            bz_mov_gain, bz_mov_lose = st.tabs(["🟢 Gainers", "🔴 Losers"])

            with bz_mov_gain:
                if gainers:
                    gainer_rows = []
                    for g in gainers:
                        _gsym = g.get("symbol") or g.get("ticker", "?")
                        _gq = _bz_mov_quote_map.get(_gsym.upper(), {})
                        gainer_rows.append({
                            "Symbol": _gsym,
                            "Company": g.get("companyName", g.get("company_name", "")),
                            "Price": _gq["last"] if "last" in _gq else g.get("price", g.get("last", "")),
                            "Change": _gq["change"] if "change" in _gq else g.get("change", ""),
                            "Change %": _gq["changePercent"] if "changePercent" in _gq else g.get("changePercent", g.get("change_percent", "")),
                            "Volume": _gq["volume"] if "volume" in _gq else g.get("volume", ""),
                            "Avg Volume": g.get("averageVolume", g.get("average_volume", "")),
                            "Mkt Cap": g.get("marketCap", g.get("market_cap", "")),
                            "Sector": g.get("gicsSectorName", g.get("sector", "")),
                        })
                    df_gain = pd.DataFrame(gainer_rows)
                    df_gain.index = df_gain.index + 1
                    st.dataframe(df_gain, width='stretch', height=min(600, 40 + 35 * len(df_gain)))
                else:
                    st.info("No gainers data available.")

            with bz_mov_lose:
                if losers:
                    loser_rows = []
                    for loser in losers:
                        _lsym = loser.get("symbol") or loser.get("ticker", "?")
                        _lq = _bz_mov_quote_map.get(_lsym.upper(), {})
                        loser_rows.append({
                            "Symbol": _lsym,
                            "Company": loser.get("companyName", loser.get("company_name", "")),
                            "Price": _lq["last"] if "last" in _lq else loser.get("price", loser.get("last", "")),
                            "Change": _lq["change"] if "change" in _lq else loser.get("change", ""),
                            "Change %": _lq["changePercent"] if "changePercent" in _lq else loser.get("changePercent", loser.get("change_percent", "")),
                            "Volume": _lq["volume"] if "volume" in _lq else loser.get("volume", ""),
                            "Avg Volume": loser.get("averageVolume", loser.get("average_volume", "")),
                            "Mkt Cap": loser.get("marketCap", loser.get("market_cap", "")),
                            "Sector": loser.get("gicsSectorName", loser.get("sector", "")),
                        })
                    df_lose = pd.DataFrame(loser_rows)
                    df_lose.index = df_lose.index + 1
                    st.dataframe(df_lose, width='stretch', height=min(600, 40 + 35 * len(df_lose)))
                else:
                    st.info("No losers data available.")

            # ── Delayed Quotes Lookup ───────────────────────
            st.divider()
            st.subheader("🔎 Delayed Quotes Lookup")
            st.caption("Enter up to 50 comma-separated tickers for Benzinga delayed quotes.")

            # Auto-populate from feed tickers
            _feed_tickers = sorted(set(d.get("ticker", "") for d in feed if d.get("ticker") and d.get("ticker") != "MARKET"))[:20]
            _default_symbols = ",".join(_feed_tickers) if _feed_tickers else "AAPL,NVDA,TSLA,MSFT,AMZN,SPY,QQQ"

            quote_symbols = st.text_input(
                "Symbols", value=_default_symbols,
                key="bz_quote_symbols",
                placeholder="AAPL, NVDA, TSLA, ...",
            )

            if quote_symbols.strip():
                quotes_data = _cached_bz_quotes(bz_key, quote_symbols)
                if quotes_data:
                    quote_rows = []
                    for q in quotes_data:
                        change = q.get("change")
                        change_pct = q.get("changePercent")
                        change_str = f"{change:+.2f}" if isinstance(change, (int, float)) else str(change or "")
                        change_pct_str = f"{change_pct:+.2f}%" if isinstance(change_pct, (int, float)) else str(change_pct or "")
                        quote_rows.append({
                            "Symbol": q.get("symbol", "?"),
                            "Name": q.get("name", ""),
                            "Last": q.get("last", ""),
                            "Change": change_str,
                            "Change %": change_pct_str,
                            "Open": q.get("open", ""),
                            "High": q.get("high", ""),
                            "Low": q.get("low", ""),
                            "Volume": q.get("volume", ""),
                            "Prev Close": q.get("previousClose", ""),
                            "52W High": q.get("fiftyTwoWeekHigh", ""),
                            "52W Low": q.get("fiftyTwoWeekLow", ""),
                        })
                    df_quotes = pd.DataFrame(quote_rows)
                    df_quotes.index = df_quotes.index + 1

                    # Color change column
                    def _color_change(val: str) -> str:
                        if val.startswith("+"):
                            return "color: #00C853"
                        if val.startswith("-"):
                            return "color: #FF1744"
                        return ""

                    change_cols = [c for c in ["Change", "Change %"] if c in df_quotes.columns]
                    if change_cols:
                        styled_q = df_quotes.style.map(_color_change, subset=change_cols)
                        st.dataframe(styled_q, width='stretch', height=min(600, 40 + 35 * len(df_quotes)))
                    else:
                        st.dataframe(df_quotes, width='stretch', height=min(600, 40 + 35 * len(df_quotes)))
                else:
                    st.info("No quote data returned. Check that symbols are valid.")

    # ── TAB: Defense & Aerospace ────────────────────────────
    with tab_defense:
        st.subheader("🛡️ Defense & Aerospace Industry Dashboard")

        fmp_key = st.session_state.cfg.fmp_api_key
        if not fmp_key:
            st.warning("FMP API key required for Defense & Aerospace data. Set FMP_API_KEY in environment.")
        else:
            def_tab_quotes, def_tab_industry = st.tabs(["📊 A&D Watchlist", "🏭 Industry Screen"])

            # ── Sub-tab: A&D Watchlist ──────────────────────
            with def_tab_quotes:
                st.caption(
                    "Real-time quotes for major Aerospace & Defense names. "
                    "Covers defense primes, mid-caps, and key suppliers."
                )

                # Allow custom ticker override
                custom_tickers = st.text_input(
                    "Tickers (comma-separated)",
                    value=DEFENSE_TICKERS,
                    key="defense_tickers_input",
                ).strip().upper()

                def_data = _cached_defense_watchlist(fmp_key) if not custom_tickers or custom_tickers == DEFENSE_TICKERS else fetch_defense_watchlist(fmp_key, tickers=custom_tickers)

                if def_data:
                    df_def = pd.DataFrame(def_data)

                    # Summary metrics
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Stocks", len(df_def))

                    if "changesPercentage" in df_def.columns:
                        avg_chg = df_def["changesPercentage"].astype(float).mean()
                        _cg_mask = df_def["changesPercentage"].astype(float)
                        m2.metric("Avg Change", f"{avg_chg:+.2f}%")
                        m3.metric("🟢 Gainers", int((_cg_mask > 0).sum()))
                        m4.metric("🔴 Losers", int((_cg_mask < 0).sum()))

                    # Data table
                    display_cols = [c for c in [
                        "symbol", "name", "price", "change",
                        "changesPercentage", "volume", "avgVolume",
                        "marketCap", "pe", "yearHigh", "yearLow",
                    ] if c in df_def.columns]

                    st.dataframe(
                        df_def[display_cols] if display_cols else df_def,
                        width='stretch',
                        height=min(600, 40 + 35 * len(df_def)),
                    )

                    # Top movers within A&D
                    if "changesPercentage" in df_def.columns:
                        df_def["_chg"] = pd.to_numeric(df_def["changesPercentage"], errors="coerce")
                        top_up = df_def.nlargest(5, "_chg")
                        top_dn = df_def.nsmallest(5, "_chg")

                        col_up, col_dn = st.columns(2)
                        with col_up:
                            st.markdown("**🟢 Top A&D Gainers**")
                            for _, r in top_up.iterrows():
                                sym = safe_markdown_text(str(r.get("symbol", "?")))
                                chg = r.get("_chg", 0)
                                price = r.get("price", 0)
                                st.markdown(f"**{sym}** — ${price} ({chg:+.2f}%)")
                        with col_dn:
                            st.markdown("**🔴 Top A&D Losers**")
                            for _, r in top_dn.iterrows():
                                sym = safe_markdown_text(str(r.get("symbol", "?")))
                                chg = r.get("_chg", 0)
                                price = r.get("price", 0)
                                st.markdown(f"**{sym}** — ${price} ({chg:+.2f}%)")
                else:
                    st.info("No Defense & Aerospace data available.")

            # ── Sub-tab: Industry Screen ────────────────────
            with def_tab_industry:
                st.caption(
                    "Full industry screen — all US-listed Aerospace & Defense stocks "
                    "from FMP, sorted by market cap."
                )

                ind_col1, ind_col2 = st.columns(2)
                with ind_col1:
                    industry_name = st.text_input(
                        "Industry",
                        value="Aerospace & Defense",
                        key="defense_industry_input",
                    ).strip()
                with ind_col2:
                    ind_limit = st.selectbox("Max results", [25, 50, 100, 200], index=1, key="defense_ind_limit")

                ind_data = _cached_industry_performance(fmp_key, industry=industry_name)
                if ind_limit and ind_data:
                    ind_data = ind_data[:ind_limit]

                if ind_data:
                    df_ind = pd.DataFrame(ind_data)

                    display_cols = [c for c in [
                        "symbol", "companyName", "marketCap", "price",
                        "volume", "beta", "lastAnnualDividend",
                        "sector", "industry", "exchange", "country",
                    ] if c in df_ind.columns]

                    st.caption(f"{len(df_ind)} {industry_name} stock(s)")
                    st.dataframe(
                        df_ind[display_cols] if display_cols else df_ind,
                        width='stretch',
                        height=min(600, 40 + 35 * len(df_ind)),
                    )

                    # Market cap distribution
                    if "marketCap" in df_ind.columns:
                        df_ind["_mcap"] = pd.to_numeric(df_ind["marketCap"], errors="coerce") / 1e9
                        total_mcap = df_ind["_mcap"].sum()
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Total Market Cap", f"${total_mcap:,.1f}B")
                        m2.metric("Largest", safe_markdown_text(str(df_ind.iloc[0].get("symbol", "?"))))
                        m3.metric("Companies", len(df_ind))

                        # Top 10 by market cap
                        st.divider()
                        st.markdown(f"**Top 10 {industry_name} by Market Cap**")
                        for _, r in df_ind.head(10).iterrows():
                            sym = safe_markdown_text(str(r.get("symbol", "?")))
                            name = safe_markdown_text(str(r.get("companyName", "")))
                            mcap = r.get("_mcap", 0)
                            price = r.get("price", 0)
                            beta = r.get("beta", "")
                            div_str = ""
                            if r.get("lastAnnualDividend"):
                                div_str = f" | Div: ${r['lastAnnualDividend']:.2f}"
                            beta_str = f" | β: {beta:.2f}" if beta else ""
                            st.markdown(
                                f"**{sym}** ({name}) — ${price} | "
                                f"Cap: ${mcap:,.1f}B{beta_str}{div_str}"
                            )
                else:
                    st.info(f"No stocks found for industry: {industry_name}")

    # ── TAB: Alerts ─────────────────────────────────────────
    with tab_alerts:
        st.subheader("⚡ Alert Log")

        alert_log = st.session_state.alert_log
        rules = st.session_state.alert_rules

        if rules:
            st.caption(f"{len(rules)} active rule(s)")
            rule_df = pd.DataFrame([{
                "Ticker": r["ticker"],
                "Condition": r["condition"],
                "Threshold": r.get("threshold", ""),
                "Category": r.get("category", ""),
                "Webhook": "✅" if r.get("webhook_url") else "❌",
            } for r in rules])
            st.dataframe(rule_df, width='stretch')
        else:
            st.info("No alert rules configured. Add rules in the sidebar ➡️")

        st.divider()

        if alert_log:
            st.caption(f"{len(alert_log)} alert(s) fired")
            for entry in alert_log[:20]:
                ts = datetime.fromtimestamp(entry["ts"], tz=UTC).strftime("%H:%M:%S")
                _ahl = safe_markdown_text(entry['headline'][:80])
                st.markdown(
                    f"⚡ `{ts}` **{entry['ticker']}** — "
                    f"{_ahl} | Rule: {entry['rule']} | Score: {entry['score']:.3f}"
                )
        else:
            st.caption("No alerts fired yet.")

        # ── Push Notification Log ───────────────────────────
        st.divider()
        st.subheader("📱 Push Notification Log")
        _nlog = st.session_state.notify_log
        if _nlog:
            st.caption(f"{len(_nlog)} notification(s) sent")
            for _n in _nlog[:20]:
                _ch_names = ", ".join(c["name"] for c in _n.get("channels", []) if c.get("ok"))
                st.markdown(
                    f"📱 **{_n['ticker']}** — score {_n['score']:.3f} → {_ch_names}"
                )
        else:
            _nc = st.session_state.notify_config
            if not _nc.enabled:
                st.info("Push notifications disabled. Set `TERMINAL_NOTIFY_ENABLED=1` in `.env`.")
            elif not _nc.has_any_channel:
                st.info("Push enabled but no channels configured. Set Telegram/Discord/Pushover env vars.")
            else:
                st.caption("No push notifications sent yet.")

    # ── TAB: Data Table ─────────────────────────────────────
    with tab_table:
        if feed:
            display_cols = [
                "ticker", "headline", "news_score", "relevance",
                "sentiment_label", "category", "event_label", "materiality",
                "recency_bucket", "age_minutes", "source_tier", "provider",
                "entity_count", "novelty_count", "impact", "polarity", "is_wiim",
            ]
            df = pd.DataFrame(feed)
            # Only show columns that exist
            show_cols = [c for c in display_cols if c in df.columns]
            df_display = df[show_cols].copy()

            # Make headlines clickable links to the article URL
            _dt_col_cfg: dict[str, Any] = {}
            if "url" in df.columns and "headline" in df_display.columns:
                df_display["headline"] = df.apply(
                    lambda r: r["url"] if r.get("url") else r.get("headline", ""),
                    axis=1,
                )
                if df_display["headline"].str.startswith("http").any():
                    _dt_col_cfg["headline"] = st.column_config.LinkColumn(
                        "Headline",
                        display_text=r"https?://[^/]+/(.{0,80}).*",
                    )

            st.dataframe(
                df_display,
                width='stretch',
                height=600,
                column_config=_dt_col_cfg if _dt_col_cfg else None,
            )
        else:
            st.info("No data yet.")


# ── Auto-refresh trigger ───────────────────────────────────────

if st.session_state.auto_refresh and (
    st.session_state.cfg.benzinga_api_key or st.session_state.cfg.fmp_api_key
):
    # Sleep briefly (not the full poll interval) to keep the UI responsive.
    # _should_poll() already gates the actual API call on elapsed time.
    time.sleep(1)
    st.rerun()
