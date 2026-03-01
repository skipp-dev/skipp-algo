"""Real-Time News Intelligence Dashboard AI supported.

Features:
- Multi-source news ingestion
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
import ipaddress
import logging
import os
import re
import socket
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import streamlit as st

# ── Path setup ──────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Suppress Tornado WebSocket noise ────────────────────────────
# Streamlit's Tornado server logs harmless WebSocketClosedError /
# StreamClosedError when browser tabs refresh or connections drop.
logging.getLogger("tornado.application").setLevel(logging.ERROR)
logging.getLogger("tornado.general").setLevel(logging.ERROR)


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


def _load_streamlit_secrets() -> None:
    """Bridge Streamlit Cloud secrets into os.environ.

    On Streamlit Cloud the .env file is gitignored (correctly), so API
    keys must be configured via the Secrets dashboard.  Streamlit exposes
    them through ``st.secrets``.  This helper copies any known key into
    ``os.environ`` (without overriding values already present, e.g. from
    a local .env).
    """
    _SECRET_KEYS = (
        "BENZINGA_API_KEY",
        "FMP_API_KEY",
        "OPENAI_API_KEY",
        "NEWSAPI_AI_KEY",
        "TERMINAL_WEBHOOK_URL",
        "TERMINAL_WEBHOOK_SECRET",
    )
    try:
        secrets = st.secrets  # raises FileNotFoundError / KeyError when empty
        for key in _SECRET_KEYS:
            if key in secrets and not os.environ.get(key):
                os.environ[key] = str(secrets[key])
    except Exception:
        # st.secrets unavailable (no secrets.toml / not on Cloud) — fine.
        pass


_load_env_file(PROJECT_ROOT / ".env")
_load_streamlit_secrets()

from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter
from newsstack_fmp.store_sqlite import SqliteStore
from newsstack_fmp._bz_http import _WARNED_ENDPOINTS
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
from open_prep.log_redaction import apply_global_log_redaction
apply_global_log_redaction()
from terminal_notifications import NotifyConfig, notify_high_score_items
from terminal_poller import (
    ClassifiedItem,
    DEFENSE_TICKERS,
    TerminalConfig,
    compute_tomorrow_outlook,
    fetch_benzinga_delayed_quotes,
    fetch_benzinga_market_movers,
    fetch_defense_watchlist,
    fetch_economic_calendar,
    fetch_industry_performance,
    fetch_sector_performance,
    fetch_ticker_sectors,
    poll_and_classify_multi,
)


from terminal_spike_scanner import (
    SESSION_ICONS,
    _YF_AVAILABLE,
    _yf_screen_movers,
    build_spike_rows,
    enrich_with_batch_quote,
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
    compute_feed_stats,
    dedup_feed_items,
    dedup_articles,
    dedup_merge,
    filter_feed,
    format_age_string,
    format_score_badge,
    match_alert_rule,
    provider_icon,
    prune_stale_items,
    safe_markdown_text,
    safe_url,
    split_segments_by_sentiment,
)
from terminal_technicals import (
    fetch_technicals,
    signal_icon,
    signal_label,
    INTERVAL_MAP,
)
from terminal_forecast import (
    fetch_forecast,
)
from terminal_newsapi import (
    NLPSentiment,
    availability_status as newsapi_availability_status,
    fetch_breaking_events,
    fetch_concept_articles,
    fetch_event_articles,
    fetch_event_clusters,
    fetch_nlp_sentiment,
    fetch_social_ranked_articles,
    fetch_trending_concepts,
    get_token_usage,
    has_tokens,
    sentiment_badge as newsapi_sentiment_badge,
    is_available as newsapi_available,
)
from terminal_finnhub import (
    fetch_social_sentiment_batch,
    is_available as finnhub_available,
)
from terminal_bitcoin import (
    fetch_btc_quote,
    fetch_btc_ohlcv_10min,
    fetch_btc_technicals,
    fetch_fear_greed,
    fetch_crypto_movers,
    fetch_crypto_listings,
    fetch_btc_supply,
    fetch_btc_news,
    fetch_btc_outlook,
    format_large_number,
    format_btc_price,
    format_supply,
    technicals_signal_label,
    technicals_signal_icon,
    is_available as btc_available,
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
    page_title="Real-Time News Intelligence Stock + Bitcoin Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _bz_tier_warning(label: str, fallback: str) -> None:
    """Show tier-limited warning if endpoint is known-blocked, else info."""
    if label in _WARNED_ENDPOINTS:
        st.warning(f"⚠️ {label} – endpoint not available on your API plan.")
    else:
        st.info(fallback)


# ── Technical Analysis UI helper ────────────────────────────────


def _render_technicals_expander(symbols: list[str], *, key_prefix: str = "tech") -> None:
    """Render a TradingView Technical Analysis expander for a list of symbols.

    Shows interval selector, summary gauges, oscillator + MA detail tables.
    Only renders if the ``tradingview_ta`` library is available and at least
    one symbol is provided.
    """
    if not INTERVAL_MAP or not symbols:
        return

    with st.expander("📊 Technical Data", expanded=False):
        _tc1, _tc2 = st.columns([1, 3])
        with _tc1:
            _sel_sym = st.selectbox(
                "Symbol",
                symbols[:50],
                key=f"{key_prefix}_sym",
            )
        with _tc2:
            _sel_iv = st.selectbox(
                "Interval",
                list(INTERVAL_MAP.keys()),
                index=list(INTERVAL_MAP.keys()).index("1D"),
                key=f"{key_prefix}_iv",
            )

        if _sel_sym and _sel_iv:
            _tech = fetch_technicals(_sel_sym, _sel_iv)

            if _tech.error:
                st.warning(f"No technical data: {_tech.error}")
                return

            # ── Summary gauge ────────────────────────────────
            st.markdown(f"### {_sel_sym} · Technical Data · {_sel_iv}")

            _g1, _g2, _g3 = st.columns(3)
            with _g1:
                _s_icon = signal_icon(_tech.summary_signal)
                _s_label = signal_label(_tech.summary_signal)
                st.metric("Summary", f"{_s_icon} {_s_label}")
                st.caption(f"Buy {_tech.summary_buy} · Neutral {_tech.summary_neutral} · Sell {_tech.summary_sell}")
            with _g2:
                _o_icon = signal_icon(_tech.osc_signal)
                _o_label = signal_label(_tech.osc_signal)
                st.metric("Oscillators", f"{_o_icon} {_o_label}")
                st.caption(f"Buy {_tech.osc_buy} · Neutral {_tech.osc_neutral} · Sell {_tech.osc_sell}")
            with _g3:
                _m_icon = signal_icon(_tech.ma_signal)
                _m_label = signal_label(_tech.ma_signal)
                st.metric("Moving Averages", f"{_m_icon} {_m_label}")
                st.caption(f"Buy {_tech.ma_buy} · Neutral {_tech.ma_neutral} · Sell {_tech.ma_sell}")

            # ── Multi-interval summary strip ─────────────────
            _strip_intervals = ["1m", "15m", "1h", "4h", "1D"]
            _strip_cols = st.columns(len(_strip_intervals))
            for _si, _siv in enumerate(_strip_intervals):
                with _strip_cols[_si]:
                    if _siv == _sel_iv:
                        # Already fetched
                        _sr = _tech
                    else:
                        _sr = fetch_technicals(_sel_sym, _siv)
                    if _sr.error:
                        st.caption(f"**{_siv}**\n—")
                    else:
                        _si_icon = signal_icon(_sr.summary_signal)
                        _si_lbl = signal_label(_sr.summary_signal)
                        st.caption(f"**{_siv}**\n{_si_icon} {_si_lbl}")

            # ── Oscillator detail table ──────────────────────
            _osc_tab, _ma_tab = st.tabs(["Oscillators", "Moving Averages"])

            with _osc_tab:
                if _tech.osc_detail:
                    _osc_rows = []
                    for d in _tech.osc_detail:
                        _a = d["action"]
                        _a_icon = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "🟡"}.get(_a, "")
                        _osc_rows.append({
                            "Name": d["name"],
                            "Value": d["value"] if d["value"] is not None else "—",
                            "Action": f"{_a_icon} {_a}",
                        })
                    st.dataframe(
                        pd.DataFrame(_osc_rows),
                        width='stretch',
                        hide_index=True,
                        height=min(500, 40 + 35 * len(_osc_rows)),
                    )
                else:
                    st.info("No oscillator data available.")

            with _ma_tab:
                if _tech.ma_detail:
                    _ma_rows = []
                    for d in _tech.ma_detail:
                        _a = d["action"]
                        _a_icon = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "🟡"}.get(_a, "")
                        _ma_rows.append({
                            "Name": d["name"],
                            "Value": d["value"] if d["value"] is not None else "—",
                            "Action": f"{_a_icon} {_a}",
                        })
                    st.dataframe(
                        pd.DataFrame(_ma_rows),
                        width='stretch',
                        hide_index=True,
                        height=min(500, 40 + 35 * len(_ma_rows)),
                    )
                else:
                    st.info("No moving average data available.")


def _render_event_clusters_expander(symbols: list[str], *, key_prefix: str = "ec") -> None:
    """Render an event-clustered news expander for a list of symbols.

    Groups articles by event (story) using NewsAPI.ai, reducing noise
    compared to showing individual articles per ticker.
    """
    if not symbols or not newsapi_available():
        return

    with st.expander("📰 Event-Clustered News (NewsAPI.ai)", expanded=False):
        _ec_sym = st.selectbox(
            "Symbol",
            symbols[:50],
            key=f"{key_prefix}_sym",
        )
        if not _ec_sym:
            return

        clusters = fetch_event_clusters(_ec_sym, count=8, hours=48)
        if not clusters:
            st.info(f"No event clusters found for {_ec_sym} in the last 48h.")
            return

        st.caption(f"**{_ec_sym}** — {len(clusters)} stories grouped by event · Source: NewsAPI.ai")

        for _ci, cluster in enumerate(clusters):
            _c_title = cluster.title or "(Untitled event)"
            _c_sources = ", ".join(cluster.sources[:3]) if cluster.sources else ""

            with st.expander(
                f"{cluster.sentiment_icon} **{_c_title[:100]}** — "
                f"📰 {cluster.article_count} articles · {cluster.event_date}",
                expanded=(_ci == 0),
            ):
                _ec1, _ec2, _ec3 = st.columns(3)
                with _ec1:
                    st.metric("Articles", cluster.article_count)
                with _ec2:
                    if cluster.sentiment is not None:
                        st.metric("NLP Sentiment", f"{cluster.sentiment:+.2f}")
                    else:
                        st.metric("NLP Sentiment", "n/a")
                with _ec3:
                    st.metric("Sources", len(cluster.sources))

                if cluster.summary:
                    st.markdown(f"**Summary:** {cluster.summary}")

                if _c_sources:
                    st.caption(f"Sources: {_c_sources}")

                if cluster.top_articles:
                    st.markdown("**Top articles:**")
                    for _ta in cluster.top_articles:
                        if _ta.get("url"):
                            st.markdown(f"- [{_ta['title'][:80]}]({_ta['url']}) — *{_ta.get('source', '')}*")
                        else:
                            st.markdown(f"- {_ta['title'][:80]} — *{_ta.get('source', '')}*")


def _render_forecast_expander(symbols: list[str], *, key_prefix: str = "fc") -> None:
    """Render an analyst forecast expander for a list of symbols.

    Shows price targets, analyst ratings, EPS estimates, and recent
    upgrades/downgrades.  Uses FMP (primary) with yfinance fallback.
    """
    if not symbols:
        return

    with st.expander("🔮 Forecast", expanded=False):

        _fc_sym = st.selectbox(
            "Symbol",
            symbols[:50],
            key=f"{key_prefix}_sym",
        )
        if not _fc_sym:
            return

        fc = fetch_forecast(_fc_sym)
        if fc.error:
            st.warning(f"No forecast data: {fc.error}")
            return
        if not fc.has_data:
            st.info("No forecast data available for this symbol.")
            return

        _src_tag = f"  ·  *via {fc.source}*" if fc.source else ""
        st.caption(f"**{_fc_sym}** — Analyst Forecast{_src_tag}")

        # ── Price Target ─────────────────────────────────
        if fc.price_target and fc.price_target.target_mean > 0:
            pt = fc.price_target
            st.markdown("### 🎯 Price Target")
            _pt1, _pt2, _pt3, _pt4 = st.columns(4)
            _pt1.metric("Current", f"${pt.current_price:.2f}")
            _pt2.metric("Target (Avg)", f"${pt.target_mean:.2f}", f"{pt.upside_pct:+.1f}%")
            _pt3.metric("Target High", f"${pt.target_high:.2f}", f"{pt.upside_high_pct:+.1f}%")
            _pt4.metric("Target Low", f"${pt.target_low:.2f}", f"{pt.upside_low_pct:+.1f}%")

            # FMP price-target-summary timeline
            if pt.last_month_count or pt.last_quarter_count or pt.last_year_count:
                _pts_rows = []
                if pt.last_month_count:
                    _pts_rows.append({"Period": "Last Month", "Avg Target": f"${pt.last_month_avg:.2f}", "Analysts": pt.last_month_count})
                if pt.last_quarter_count:
                    _pts_rows.append({"Period": "Last Quarter", "Avg Target": f"${pt.last_quarter_avg:.2f}", "Analysts": pt.last_quarter_count})
                if pt.last_year_count:
                    _pts_rows.append({"Period": "Last Year", "Avg Target": f"${pt.last_year_avg:.2f}", "Analysts": pt.last_year_count})
                st.dataframe(pd.DataFrame(_pts_rows), width='stretch', hide_index=True, height=min(180, 40 + 35 * len(_pts_rows)))

        # ── Analyst Rating ───────────────────────────────
        if fc.rating and fc.rating.total > 0:
            rt = fc.rating
            st.markdown(f"### 📊 Analyst Rating — {rt.consensus_icon} {rt.consensus}")
            st.caption(f"Based on {rt.total} analysts")
            _rt1, _rt2, _rt3, _rt4, _rt5 = st.columns(5)
            _rt1.metric("Strong Buy", rt.strong_buy)
            _rt2.metric("Buy", rt.buy)
            _rt3.metric("Hold", rt.hold)
            _rt4.metric("Sell", rt.sell)
            _rt5.metric("Strong Sell", rt.strong_sell)

        # ── EPS Estimates ────────────────────────────────
        if fc.eps_estimates:
            st.markdown("### 📈 EPS Estimates")
            _eps_rows = []
            for e in fc.eps_estimates:
                row: dict[str, Any] = {
                    "Period": e.period,
                    "EPS Est.": f"{e.avg:.2f}",
                    "Low": f"{e.low:.2f}",
                    "High": f"{e.high:.2f}",
                }
                if e.year_ago_eps:
                    row["Year Ago"] = f"{e.year_ago_eps:.2f}"
                if e.growth:
                    row["Growth"] = f"{e.growth * 100:+.1f}%"
                row["Analysts"] = e.num_analysts
                if e.revenue_avg:
                    row["Rev Est."] = f"${e.revenue_avg / 1e9:.1f}B" if e.revenue_avg > 1e9 else f"${e.revenue_avg / 1e6:.0f}M"
                _eps_rows.append(row)
            st.dataframe(
                pd.DataFrame(_eps_rows),
                width='stretch',
                hide_index=True,
                height=min(350, 40 + 35 * len(_eps_rows)),
            )

        # ── Upgrades / Downgrades ────────────────────────
        if fc.upgrades_downgrades:
            st.markdown("### 📋 Recent Upgrades / Downgrades")
            _action_icons = {
                "upgrade": "⬆️", "up": "⬆️",
                "downgrade": "⬇️", "down": "⬇️",
                "maintain": "➡️", "main": "➡️",
                "init": "🆕", "initiated": "🆕",
                "reiterate": "🔄", "reit": "🔄",
            }
            _ud_rows = []
            for u in fc.upgrades_downgrades:
                _action_icon = _action_icons.get(u.action.lower(), "")
                _ud_rows.append({
                    "Date": u.date,
                    "Firm": u.firm,
                    "Action": f"{_action_icon} {u.action}",
                    "From": u.from_grade,
                    "To": u.to_grade,
                })
            st.dataframe(
                pd.DataFrame(_ud_rows),
                width='stretch',
                hide_index=True,
                height=min(500, 40 + 35 * len(_ud_rows)),
            )


# ── Persistent state (survives reruns) ──────────────────────────


def _prune_stale_items(feed: list[dict[str, Any]], max_age_s: float | None = None) -> list[dict[str, Any]]:
    """Drop items whose published_ts is older than *max_age_s* seconds.

    Thin wrapper around ``terminal_ui_helpers.prune_stale_items`` that
    reads the default max-age from Streamlit session state.
    Outside market hours the retention is extended to at least 72 h so
    weekend / overnight feeds are not pruned empty.
    """
    if max_age_s is None:
        cfg_obj = st.session_state.get("cfg")
        max_age_s = cfg_obj.feed_max_age_s if cfg_obj else 14400.0
    if not is_market_hours():
        max_age_s = max(max_age_s, 259200.0)  # 72 h
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
    cfg = st.session_state.get("cfg")
    if cfg is None or not cfg.jsonl_path:
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
    merged = dedup_feed_items(merged)
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
    _restored = dedup_feed_items(_restored)
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
# --- Consolidated simple defaults (Item 5) ---
_SIMPLE_DEFAULTS: dict[str, object] = {
    "poll_attempts": 0,
    "last_poll_ts": 0.0,
    "last_resync_ts": 0.0,
    "consecutive_empty_polls": 0,
    "adapter": None,
    "fmp_adapter": None,
    "store": None,
    "auto_refresh": True,
    "last_poll_status": "—",
    "last_poll_error": "",
    "last_poll_duration_s": 0.0,
    "alert_log": [],
    "bg_poller": None,
    "notify_log": [],
}
for _k, _v in _SIMPLE_DEFAULTS.items():
    st.session_state.setdefault(_k, _v)
if "total_items_ingested" not in st.session_state:
    st.session_state.total_items_ingested = len(st.session_state.feed)
if "alert_rules" not in st.session_state:
    # Load persisted alert rules
    _alert_path = Path("artifacts/alert_rules.json")
    if _alert_path.exists():
        try:
            _loaded = json.loads(_alert_path.read_text())
            st.session_state.alert_rules = _loaded if isinstance(_loaded, list) else []
        except Exception:
            logger.warning("Failed to load alert_rules.json, resetting", exc_info=True)
            st.session_state.alert_rules = []
    else:
        st.session_state.alert_rules = []
if "notify_config" not in st.session_state:
    st.session_state.notify_config = NotifyConfig()
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

    # API key status — re-read env vars directly so keys added after
    # session start are detected without requiring a full server restart.
    _bz_key = os.environ.get("BENZINGA_API_KEY", "") or cfg.benzinga_api_key
    if _bz_key:
        st.success("News API: ✅ configured")
        if not cfg.benzinga_api_key:
            cfg.benzinga_api_key = _bz_key
    else:
        st.error("No BENZINGA_API_KEY found in .env")
        st.info("Set `BENZINGA_API_KEY=your_key` in `.env` and restart.")

    _fmp_key = os.environ.get("FMP_API_KEY", "") or cfg.fmp_api_key
    if _fmp_key:
        st.success("FMP: ✅ configured")
        if not cfg.fmp_api_key:
            cfg.fmp_api_key = _fmp_key
    else:
        st.caption("FMP: not configured (optional)")

    # Re-read env var directly — the cached TerminalConfig may have been
    # created before the user added the key to .env.
    _oai_key = os.environ.get("OPENAI_API_KEY", "") or cfg.openai_api_key
    if _oai_key:
        st.success("OpenAI: ✅ configured")
        # Patch live config so downstream code sees the key too
        if not cfg.openai_api_key:
            cfg.openai_api_key = _oai_key
    else:
        st.caption("OpenAI: not configured (AI Insights disabled)")

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
                logger.warning("Cursor reset prune(%s) failed: %s", _tbl, exc, exc_info=True)
        st.session_state.cursor = None
        st.session_state.consecutive_empty_polls = 0
        st.toast("Cursor reset — next poll will fetch latest articles", icon="🔃")
        st.rerun()

    st.divider()

    # Stats
    st.metric("Polls", st.session_state.poll_count)
    _poll_attempts = st.session_state.get("poll_attempts", 0)
    if _poll_attempts > st.session_state.poll_count:
        # Distinguish in-progress (no poll completed yet) from actual failures
        if st.session_state.last_poll_status == "—":
            st.caption(f"Attempts: {_poll_attempts} (in progress…)")
        else:
            st.caption(f"Attempts: {_poll_attempts} (failures: {_poll_attempts - st.session_state.poll_count})")
    st.metric("Items in feed", len(st.session_state.feed))
    st.metric("Total ingested", st.session_state.total_items_ingested)
    if st.session_state.last_poll_ts:
        ago = time.time() - st.session_state.last_poll_ts
        _dur = st.session_state.get("last_poll_duration_s", 0.0)
        _dur_txt = f" ({_dur:.1f}s)" if _dur > 0 else ""
        st.caption(f"Last poll: {ago:.0f}s ago{_dur_txt}")

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
        sources.append("News")
    if cfg.fmp_api_key and cfg.fmp_enabled and _FmpAdapter:
        sources.append("FMP")
    st.caption(f"Sources: {', '.join(sources) if sources else 'none'}")

    # Reset dedup DB (clears mark_seen so next poll re-ingests)
    if st.button("🗑️ Reset dedup DB", width='stretch'):
        # Stop background poller FIRST so it doesn't use closed adapters
        _bp_reset = st.session_state.get("bg_poller")
        if _bp_reset is not None:
            try:
                _bp_reset.stop()
            except Exception:
                logger.debug("bg_poller.stop() failed during reset", exc_info=True)
        # Close existing SQLite connection before deleting files
        if st.session_state.store is not None:
            try:
                st.session_state.store.close()
            except Exception:
                logger.debug("store.close() failed during reset", exc_info=True)
        # Close HTTP adapters to release connection pools
        for _adapter_key in ("adapter", "fmp_adapter"):
            _adp = st.session_state.get(_adapter_key)
            if _adp is not None:
                try:
                    _adp.close()
                except Exception:
                    logger.debug("%s.close() failed during reset", _adapter_key, exc_info=True)
        db_path = Path(cfg.sqlite_path)
        # Remove main DB + SQLite WAL/SHM journal files
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                p.unlink()
        st.session_state.store = None
        st.session_state.adapter = None
        st.session_state.fmp_adapter = None
        st.session_state.cursor = None
        st.session_state.feed = []
        st.session_state.poll_count = 0
        st.session_state.total_items_ingested = 0
        st.session_state.consecutive_empty_polls = 0
        st.session_state.last_poll_status = "DB reset — will re-poll"
        st.session_state.last_poll_error = ""
        st.session_state.bg_poller = None
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
            _wh_url = alert_webhook.strip()
            _wh_valid = True
            if _wh_url:
                try:
                    from urllib.parse import urlparse
                    _parsed = urlparse(_wh_url)
                    if _parsed.scheme not in ("http", "https"):
                        st.error("Webhook URL must use http:// or https://")
                        _wh_valid = False
                    elif _parsed.hostname:
                        _host = _parsed.hostname.lower()
                        if _host in ("localhost", "0.0.0.0", ""):
                            st.error("Webhook URL must not target localhost")
                            _wh_valid = False
                        else:
                            try:
                                _ip = ipaddress.ip_address(socket.gethostbyname(_host))
                                if _ip.is_private or _ip.is_loopback or _ip.is_link_local:
                                    st.error("Webhook URL must not target private/internal networks")
                                    _wh_valid = False
                            except (socket.gaierror, ValueError):
                                pass  # DNS resolution failed — allow; will fail at POST time
                except Exception as exc:
                    logger.warning("Webhook URL validation error: %s", exc, exc_info=True)
                    _wh_valid = False  # deny by default on validation failure

            if _wh_valid:
                new_rule = {
                    "ticker": alert_ticker.upper().strip(),
                    "condition": alert_cond,
                    "threshold": alert_threshold,
                    "category": alert_cat.lower().strip(),
                    "webhook_url": _wh_url,
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

    # RT engine status — skip on Streamlit Cloud where the local engine can't run
    _is_cloud = str(PROJECT_ROOT).startswith("/mount/src") or os.environ.get("STREAMLIT_SHARING_MODE")
    if _is_cloud:
        st.caption("RT Engine: ☁️ Cloud mode (local-only feature)")
    else:
        _rt_path = str(PROJECT_ROOT / "artifacts" / "open_prep" / "latest" / "latest_vd_signals.jsonl")
        _rt_quotes = load_rt_quotes(_rt_path)
        if _rt_quotes:
            st.success(f"RT Engine: {len(_rt_quotes)} symbols live")
        else:
            if os.path.isfile(_rt_path):
                _rt_age = time.time() - os.path.getmtime(_rt_path)
                st.warning(f"RT Engine: file exists but stale ({_rt_age:.0f}s old > 120s limit)")
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
# NOTE: Each wrapper catches exceptions so Streamlit never caches a raised
# exception for the full TTL — callers always get a safe fallback.

@st.cache_data(ttl=300, show_spinner=False)
def _cached_sector_perf(api_key: str) -> list[dict[str, Any]]:
    """Cache sector performance for 5 minutes."""
    try:
        return fetch_sector_performance(api_key)
    except Exception:
        logger.debug("_cached_sector_perf failed", exc_info=True)
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _cached_ticker_sectors(api_key: str, tickers_csv: str) -> dict[str, str]:
    """Cache ticker→GICS sector mapping for 5 minutes."""
    try:
        tickers = [t.strip() for t in tickers_csv.split(",") if t.strip()]
        return fetch_ticker_sectors(api_key, tickers)
    except Exception:
        logger.debug("_cached_ticker_sectors failed", exc_info=True)
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def _cached_defense_watchlist(api_key: str) -> list[dict[str, Any]]:
    """Cache Aerospace & Defense watchlist quotes for 5 minutes."""
    try:
        return fetch_defense_watchlist(api_key)
    except Exception:
        logger.debug("_cached_defense_watchlist failed", exc_info=True)
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _cached_defense_watchlist_custom(api_key: str, tickers: str) -> list[dict[str, Any]]:
    """Cache custom Aerospace & Defense watchlist quotes for 5 minutes."""
    try:
        return fetch_defense_watchlist(api_key, tickers=tickers)
    except Exception:
        logger.debug("_cached_defense_watchlist_custom failed", exc_info=True)
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _cached_industry_performance(api_key: str, industry: str = "Aerospace & Defense") -> list[dict[str, Any]]:
    """Cache industry screen results for 5 minutes."""
    try:
        return fetch_industry_performance(api_key, industry=industry)
    except Exception:
        logger.debug("_cached_industry_performance failed", exc_info=True)
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _cached_econ_calendar(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache economic calendar for 5 minutes."""
    try:
        return fetch_economic_calendar(api_key, from_date, to_date)
    except Exception:
        logger.debug("_cached_econ_calendar failed", exc_info=True)
        return []


@st.cache_data(ttl=90, show_spinner=False)
def _cached_spike_data(api_key: str) -> dict[str, list[dict[str, Any]]]:
    """Cache gainers/losers/actives for 90 seconds.

    Uses yfinance (free, real-time) as primary source.  Falls back to
    FMP ``/stable/biggest-gainers`` etc. (15-min delayed) when yfinance
    is unavailable.
    """
    try:
        # Primary: yfinance (real-time, no API key needed)
        if _YF_AVAILABLE:
            yf_data = _yf_screen_movers()
            if yf_data["gainers"] or yf_data["losers"] or yf_data["actives"]:
                return yf_data
        # Fallback: FMP (15-min delayed, needs API key)
        if api_key:
            gainers = enrich_with_batch_quote(api_key, fetch_gainers(api_key))
            losers = enrich_with_batch_quote(api_key, fetch_losers(api_key))
            actives = enrich_with_batch_quote(api_key, fetch_most_active(api_key))
            return {"gainers": gainers, "losers": losers, "actives": actives}
        return {"gainers": [], "losers": [], "actives": []}
    except Exception:
        logger.debug("_cached_spike_data failed", exc_info=True)
        return {"gainers": [], "losers": [], "actives": []}


@st.cache_data(ttl=300, show_spinner=False)
def _cached_tomorrow_outlook(
    bz_key: str, fmp_key: str, _cache_buster: str = "",
) -> dict[str, Any]:
    """Cache tomorrow outlook for 5 minutes.

    *_cache_buster* is unused but forces a new cache entry when the date
    changes (caller passes today's ISO date).
    """
    try:
        return compute_tomorrow_outlook(bz_key, fmp_key)
    except Exception:
        logger.debug("_cached_tomorrow_outlook failed", exc_info=True)
        return {}


def _safe_float_mov(val: Any, default: float = 0.0) -> float:
    """Safe float conversion for mover data."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ── Cached Movers & Quotes ──────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def _cached_bz_movers(api_key: str) -> dict[str, list[dict[str, Any]]]:
    """Cache market movers for 60 seconds."""
    try:
        return fetch_benzinga_market_movers(api_key)
    except Exception:
        logger.debug("_cached_bz_movers failed", exc_info=True)
        return {}


@st.cache_data(ttl=60, show_spinner=False)
def _cached_bz_quotes(api_key: str, symbols_csv: str) -> list[dict[str, Any]]:
    """Cache delayed quotes for 60 seconds."""
    try:
        syms = [s.strip() for s in symbols_csv.split(",") if s.strip()]
        return fetch_benzinga_delayed_quotes(api_key, syms)
    except Exception:
        logger.debug("_cached_bz_quotes failed", exc_info=True)
        return []



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
        try:
            with httpx.Client(timeout=5.0) as client:
                for wh_url, wh_payload in pending_webhooks:
                    try:
                        body = json.dumps(wh_payload, default=str).encode()
                        client.post(wh_url, content=body, headers={"Content-Type": "application/json"})
                    except Exception as exc:
                        logger.warning("Alert webhook POST failed (%s): %s", wh_url[:40], exc, exc_info=True)
        except Exception as exc:
            logger.warning("Alert webhook client init failed: %s", exc, exc_info=True)


# ── Poll logic ──────────────────────────────────────────────────

def _process_new_items(
    items: list,
    cfg: TerminalConfig,
    *,
    src_label: str = "BZ",
) -> None:
    """Shared post-poll processing for foreground and background pollers.

    Handles: JSONL export (batched — item 13), global webhook,
    push notifications, news→chart webhook, feed trim/prune,
    VD snapshot.  Uses a single httpx.Client for all webhooks (item 14).
    """
    if not items:
        return

    # Convert to dicts and deduplicate BEFORE persisting to JSONL
    new_dicts = [ci.to_dict() for ci in items]
    # Dedup by item_id:ticker against existing feed
    _existing_keys = {f"{d.get('item_id', '')}:{d.get('ticker', '')}" for d in st.session_state.feed}
    # Also dedup by headline (catches near-identical articles with different item_ids)
    _existing_headlines = {d.get("headline", "").strip().lower() for d in st.session_state.feed if d.get("headline")}
    unique_dicts: list[dict] = []
    _batch_keys: set[str] = set()  # dedup within the incoming batch itself
    for d in new_dicts:
        key = f"{d.get('item_id', '')}:{d.get('ticker', '')}"
        hl = d.get("headline", "").strip().lower()
        if key in _existing_keys or key in _batch_keys:
            continue
        if hl and hl in _existing_headlines:
            continue
        _batch_keys.add(key)
        unique_dicts.append(d)
    new_dicts = unique_dicts

    # JSONL batch export (item 13 — only unique items reach disk)
    if cfg.jsonl_path:
        _jsonl_errors = 0
        for d in new_dicts:
            try:
                # Write dict directly to avoid re-converting from ClassifiedItem
                os.makedirs(os.path.dirname(cfg.jsonl_path) or ".", exist_ok=True)
                line = json.dumps(d, ensure_ascii=False, default=str)
                with open(cfg.jsonl_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
            except Exception as exc:
                _jsonl_errors += 1
                if _jsonl_errors <= 3:
                    logger.warning("JSONL append failed for %s: %s",
                                   d.get('item_id', '?')[:40] if isinstance(d, dict) else '?', exc, exc_info=True)
        if _jsonl_errors > 3:
            logger.warning("JSONL append had %d total failures (suppressed after 3)", _jsonl_errors)

    st.session_state.feed = dedup_feed_items(new_dicts + st.session_state.feed)

    # Webhooks + notifications (single shared httpx client — item 14)
    _nc_webhook_url = os.getenv("TERMINAL_NEWS_CHART_WEBHOOK_URL", cfg.webhook_url)
    _skip_dup = _nc_webhook_url == cfg.webhook_url
    _do_global_wh = bool(cfg.webhook_url)
    _do_nc_wh = bool(
        st.session_state.news_chart_auto_webhook and _nc_webhook_url
        and not _skip_dup
    )

    if _do_global_wh or _do_nc_wh:
        try:
            with httpx.Client(timeout=5.0) as wh_client:
                # Global webhook
                if _do_global_wh:
                    _wh_budget = 20
                    for ci in items:
                        if _wh_budget <= 0:
                            logger.warning("%s global webhook budget exhausted", src_label)
                            break
                        if fire_webhook(ci, cfg.webhook_url, cfg.webhook_secret,
                                        _client=wh_client) is not None:
                            _wh_budget -= 1

                # News→Chart auto-webhook
                if _do_nc_wh:
                    _nc_budget = 5
                    for ci in items:
                        if _nc_budget <= 0:
                            break
                        if ci.news_score >= 0.85 and ci.is_actionable:
                            fire_webhook(ci, _nc_webhook_url, cfg.webhook_secret,
                                         min_score=0.85, _client=wh_client)
                            _nc_budget -= 1
        except Exception as exc:
            logger.warning("Webhook client failed: %s", exc, exc_info=True)

    # Push notifications for high-score items
    if new_dicts:
        try:
            _nr = notify_high_score_items(
                new_dicts, config=st.session_state.notify_config,
            )
            if _nr:
                st.session_state.notify_log = (
                    _nr + st.session_state.notify_log
                )[:100]
        except Exception as exc:
            logger.warning("Push notification dispatch failed: %s", exc, exc_info=True)

    # Trim feed
    max_items = cfg.max_items
    if len(st.session_state.feed) > max_items:
        st.session_state.feed = st.session_state.feed[:max_items]

    # Prune stale items (age-based)
    st.session_state.feed = _prune_stale_items(st.session_state.feed)

    # VD snapshot with extended-hours quote fallback
    _vd_bz_quotes: list[dict[str, Any]] | None = None
    _vd_session = market_session()
    if _vd_session in ("pre-market", "after-hours") and cfg.benzinga_api_key and st.session_state.feed:
        _vd_syms = sorted({
            d.get("ticker", "") for d in st.session_state.feed
            if d.get("ticker") and d.get("ticker") != "MARKET"
        })[:50]
        if _vd_syms:
            try:
                _vd_bz_quotes = fetch_benzinga_delayed_quotes(
                    cfg.benzinga_api_key, _vd_syms)
            except Exception:
                logger.debug("Extended-hours quote fetch skipped", exc_info=True)
    save_vd_snapshot(st.session_state.feed, bz_quotes=_vd_bz_quotes)

    st.toast(f"📡 {len(items)} new item(s) [{src_label}]", icon="✅")


def _should_poll(poll_interval: float) -> bool:
    """Determine if we should poll this cycle."""
    cfg: TerminalConfig = st.session_state.cfg
    if not cfg.benzinga_api_key and not cfg.fmp_api_key:
        return False
    elapsed: float = time.time() - st.session_state.last_poll_ts
    return elapsed >= poll_interval  # type: ignore[no-any-return]


def _do_poll() -> None:
    """Execute one poll cycle (multi-source)."""
    adapter = _get_adapter()
    fmp = _get_fmp_adapter()
    if adapter is None and fmp is None:
        return

    store = _get_store()
    cfg: TerminalConfig = st.session_state.cfg

    st.session_state["poll_attempts"] = st.session_state.get("poll_attempts", 0) + 1

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
        _safe_msg = re.sub(r"(apikey|api_key|token|key)=[^&\s]+", r"\1=***", str(exc), flags=re.IGNORECASE)
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
                    logger.warning("SQLite prune(%s) after empty polls failed: %s", _tbl, exc, exc_info=True)
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

    # Shared post-poll processing (JSONL, webhooks, notifications, trim, VD)
    _process_new_items(items, cfg, src_label=src_label)

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
            logger.warning("SQLite prune failed: %s", exc, exc_info=True)


# ── Execute poll if needed ──────────────────────────────────────

# Feed lifecycle management (weekend clear, pre-seed, off-hours throttle)
_lifecycle: FeedLifecycleManager = st.session_state.lifecycle_mgr
try:
    _lc_result = _lifecycle.manage(st.session_state.feed, _get_store())
except Exception as _lc_exc:
    logger.warning("Feed lifecycle manage() failed: %s", _lc_exc, exc_info=True)
    _lc_result = {"action": "error"}
if _lc_result.get("feed_action") == "cleared":
    st.session_state.feed = []
    st.session_state.cursor = None
    st.session_state.poll_count = 0
    _bp_sync = st.session_state.get("bg_poller")
    if _bp_sync is not None:
        _bp_sync.cursor = None
    logger.info("Feed lifecycle: weekend data cleared")
elif _lc_result.get("feed_action") == "stale_recovery":
    st.session_state.cursor = None
    st.session_state.consecutive_empty_polls = 0
    _bp_sync = st.session_state.get("bg_poller")
    if _bp_sync is not None:
        _bp_sync.cursor = None
    logger.info("Feed lifecycle: stale-recovery cursor reset")

# Adjust poll interval for off-hours
_effective_interval = _lifecycle.get_off_hours_poll_interval(float(interval))
if _effective_interval != float(interval):
    st.sidebar.caption(
        f"⏳ Effective interval: {_effective_interval:.0f}s "
        f"({'weekend' if _lifecycle.get_status_display().get('phase', '').startswith('🌙 Weekend') else 'off-hours'} throttle)"
    )

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
    # Foreground initial poll BEFORE creating the bg poller so both
    # don't race on the same SQLite store with cursor=None.
    if _feed_empty_needs_poll:
        with st.spinner("Loading latest news…"):
            _do_poll()

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

        # Shared post-poll processing (JSONL, webhooks, notifications, trim, VD)
        _process_new_items(_bg_items, st.session_state.cfg, src_label="BG")

    # Sync status from background poller for sidebar display
    _bp = st.session_state.bg_poller
    st.session_state.poll_count = max(st.session_state.poll_count, _bp.poll_count)
    st.session_state["poll_attempts"] = max(
        st.session_state.get("poll_attempts", 0), getattr(_bp, "poll_attempts", _bp.poll_count))
    st.session_state.last_poll_ts = _bp.last_poll_ts
    st.session_state.last_poll_status = _bp.last_poll_status
    if _bp.last_poll_ts > 0:
        st.session_state.last_poll_error = _bp.last_poll_error
    st.session_state.last_poll_duration_s = getattr(_bp, "last_poll_duration_s", 0.0)
    st.session_state.total_items_ingested = max(
        st.session_state.total_items_ingested, _bp.total_items_ingested)
    st.session_state.cursor = _bp.cursor

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

st.title("📡 Real-Time News Intelligence Stock + Bitcoin Dashboard — AI supported")

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

    # ── Expandable detail lists behind the top-line metrics ──
    _detail_cols = st.columns(3)

    # Group feed items by ticker for unique-tickers detail
    _tickers_seen: dict[str, list[dict[str, Any]]] = {}
    for _fi in feed:
        _tk = _fi.get("ticker", "")
        if _tk and _tk != "MARKET":
            _tickers_seen.setdefault(_tk, []).append(_fi)

    with _detail_cols[0]:
        with st.expander(f"Unique tickers ({_stats['unique_tickers']})"):
            for _tk_sym in sorted(_tickers_seen):
                _tk_items = _tickers_seen[_tk_sym]
                _best = max(_tk_items, key=lambda x: x.get("news_score", 0))
                _hl = safe_markdown_text((_best.get("headline") or "")[:100])
                _u = safe_url(_best.get("url") or "")
                _link = f"[{_hl}]({_u})" if _u else _hl
                st.markdown(f"**{_tk_sym}** — {_link}")

    with _detail_cols[1]:
        with st.expander(f"Actionable ({_stats['actionable']})"):
            _act_items = dedup_feed_items([d for d in feed if d.get("is_actionable")])
            if _act_items:
                for _ai in _act_items:
                    _tk = _ai.get("ticker", "?")
                    _hl = safe_markdown_text((_ai.get("headline") or "")[:100])
                    _u = safe_url(_ai.get("url") or "")
                    _sc = _ai.get("news_score", 0)
                    _link = f"[{_hl}]({_u})" if _u else _hl
                    st.markdown(f"**{_tk}** ({_sc:.2f}) — {_link}")
            else:
                st.caption("No actionable items.")

    with _detail_cols[2]:
        with st.expander(f"HIGH materiality ({_stats['high_materiality']})"):
            _high_items = dedup_feed_items([d for d in feed if d.get("materiality") == "HIGH"])
            if _high_items:
                for _hi in _high_items:
                    _tk = _hi.get("ticker", "?")
                    _hl = safe_markdown_text((_hi.get("headline") or "")[:100])
                    _u = safe_url(_hi.get("url") or "")
                    _sc = _hi.get("news_score", 0)
                    _link = f"[{_hl}]({_u})" if _u else _hl
                    st.markdown(f"**{_tk}** ({_sc:.2f}) — {_link}")
            else:
                st.caption("No HIGH materiality items.")

    st.divider()

    # ── Tabs ────────────────────────────────────────────────
    _session_icons = SESSION_ICONS
    # Compute once per render — avoids 4+ redundant calls and cross-tab drift
    _current_session = market_session()

    def _safe_tab(label: str, body_fn, *args, **kwargs) -> None:  # noqa: ANN001
        """Wrap a tab body in try/except so one failing tab doesn't crash others (item 7)."""
        try:
            body_fn(*args, **kwargs)
        except Exception:
            st.error(f"⚠️ {label} tab failed to render.")
            logger.exception("Tab %s render error", label)

    tab_feed, tab_ai, tab_rank, tab_segments, tab_bitcoin, tab_rt_spikes, tab_spikes, tab_heatmap, tab_calendar, tab_outlook, tab_movers, tab_bz_movers, tab_defense, tab_breaking, tab_trending, tab_social, tab_alerts, tab_table = st.tabs(
        ["📰 Live Feed", "🤖 AI Insights", "🏆 Rankings", "🏗️ Segments",
         "₿ Bitcoin", "⚡ RT Spikes", "🚨 Spikes", "🗺️ Heatmap", "📅 Calendar",
         "🔮 Outlook", "🔥 Top Movers", "💹 Movers", "🛡️ Defense & Aerospace",
         "🔴 Breaking", "📈 Trending", "🔥 Social",
         "⚡ Alerts", "📊 Data Table"],
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

        # ── NLP Sentiment enrichment (NewsAPI.ai validation layer) ──
        _feed_nlp: dict[str, NLPSentiment] = {}
        if newsapi_available():
            _feed_tickers = list({
                d.get("ticker", "").upper()
                for d in filtered[:50]
                if d.get("ticker") and d.get("ticker") != "MARKET"
            })
            if _feed_tickers:
                _feed_nlp = fetch_nlp_sentiment(_feed_tickers[:30], hours=24)

        # Show filtered items
        # Column headers with info popovers
        _hdr_cols = st.columns([1, 4, 1, 1, 1, 1, 1])
        with _hdr_cols[0]:
            with st.popover("**Ticker** ℹ️"):
                st.markdown("**Stock symbol** — The ticker symbol of the company mentioned in the article (e.g. AAPL, TSLA, NVDA).")
        with _hdr_cols[1]:
            with st.popover("**Headline** ℹ️"):
                st.markdown("**News headline** with sentiment icon (🟢 positive / 🔴 negative / ⚪ neutral). Click the link to open the full article.")
        with _hdr_cols[2]:
            with st.popover("**Category** ℹ️"):
                st.markdown(
                    "**News category** — Classifies the type of news.\n\n"
                    "Common values:\n"
                    "- `mna` — Mergers & Acquisitions\n"
                    "- `earnings` — Earnings reports\n"
                    "- `macro` — Macroeconomic news\n"
                    "- `analyst` — Analyst actions\n"
                    "- `crypto` — Cryptocurrency\n"
                    "- `guidance` — Company guidance\n"
                    "- `insider` — Insider trading\n"
                    "- `govt` — Government/regulation"
                )
        with _hdr_cols[3]:
            with st.popover("**Score** ℹ️"):
                st.markdown(
                    "**News importance score** (0–1) computed by the scoring engine based on "
                    "source tier, relevance, materiality, and sentiment strength.\n\n"
                    "Higher = more market-moving.\n\n"
                    "**Colour coding** (colour = impact × direction)\n\n"
                    "| Colour | Threshold | Meaning |\n"
                    "|--------|-----------|---------|\n"
                    "| 🟢 **green bold** | + score ≥ 0.80 | **High-impact bullish** — actionable. "
                    "Triggers an A1→A0 upgrade and fires the alert webhook. |\n"
                    "| 🔴 **red bold** | − score ≥ 0.80 | **High-impact bearish** — actionable. "
                    "Scored strongly across source tier, relevance, materiality & sentiment. |\n"
                    "| 🟡 yellow | + score ≥ 0.50 | **Moderate-impact bullish** — notable but below "
                    "high-conviction threshold. |\n"
                    "| 🟠 orange | − score ≥ 0.50 | **Moderate-impact bearish** — notable but below "
                    "high-conviction threshold. |\n"
                    "| plain | score < 0.50 | **Low-impact** — informational only, "
                    "no alert action taken. |\n\n"
                    "**Direction prefix**\n\n"
                    "| Prefix | Meaning |\n"
                    "|--------|---------|\n"
                    "| **+** | Bullish impact |\n"
                    "| **n** | Neutral impact |\n"
                    "| **−** | Bearish impact |\n\n"
                    "The 🔍 badge means **WIIM** (Why It Matters) — a short explanation of the article's market relevance."
                )
        with _hdr_cols[4]:
            with st.popover("**Age** ℹ️"):
                st.markdown(
                    "**Time since publication** — How long ago the article was published.\n\n"
                    "Recency icons:\n"
                    "- 🟢 Fresh (< 1 hour)\n"
                    "- 🟡 Recent (1–4 hours)\n"
                    "- ⚪ Older (> 4 hours)"
                )
        with _hdr_cols[5]:
            with st.popover("**Event** ℹ️"):
                st.markdown(
                    "**Event classification label** — Describes the type of market event.\n\n"
                    "Examples:\n"
                    "- `ma deal` — M&A transaction\n"
                    "- `earnings beat` — Earnings surprise\n"
                    "- `analyst upgrade` — Rating change\n"
                    "- `guidance raised` — Outlook revision\n"
                    "- `stock split` — Corporate action\n\n"
                    "The provider icon shows the data source."
                )
        with _hdr_cols[6]:
            with st.popover("**NLP** ℹ️"):
                st.markdown(
                    "**NLP sentiment cross-validation** from NewsAPI.ai — An independent sentiment score "
                    "computed via natural language processing on recent articles.\n\n"
                    "Compares against the keyword-based sentiment to spot divergences. "
                    "A large gap between NLP and keyword sentiment may indicate the article's "
                    "true tone differs from its headline."
                )
        st.divider()

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
            score_badge = format_score_badge(score, d.get("sentiment_label", ""))
            prov_icon = provider_icon(_provider)
            _safe_url = safe_url(url)
            _wiim_badge = " 🔍" if d.get("is_wiim") else ""

            with st.container():
                cols = st.columns([1, 4, 1, 1, 1, 1, 1])
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
                with cols[6]:
                    # NLP sentiment validation (NewsAPI.ai)
                    _nlp_data = _feed_nlp.get(ticker.upper())
                    if _nlp_data and _nlp_data.article_count > 0:
                        st.markdown(f"{_nlp_data.icon} `NLP {_nlp_data.nlp_score:+.2f}`")
                    elif _feed_nlp:
                        st.markdown("⚪ `NLP —`")
                    # else: no NLP data fetched (NewsAPI.ai unavailable)

    # ── TAB: Top Movers ─────────────────────────────────────
    with tab_movers:
        # ── Real-time Top Movers: merge data sources ──────────
        fmp_key_mov = st.session_state.cfg.fmp_api_key
        bz_key_mov = st.session_state.cfg.benzinga_api_key
        _session_label_mov = _session_icons.get(_current_session, _current_session)

        if not fmp_key_mov and not bz_key_mov:
            st.info("Set `FMP_API_KEY` and/or `BENZINGA_API_KEY` in `.env` for real-time movers.")
        else:
            st.subheader("🔥 Real-Time Top Movers")
            st.caption(f"**{_session_label_mov}** — Live gainers & losers ranked by absolute price change. Auto-refreshes each cycle.")

            # Gather data from all sources
            _mov_now = time.time()
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
                                "_ts": _mov_now,
                            }

            # 2) Market movers (60s TTL)
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
                        # Delayed quotes are fresher than FMP during extended hours
                        if not existing or (_current_session in ("pre-market", "after-hours")):
                            _mov_all[sym] = {
                                "symbol": sym,
                                "name": name[:50],
                                "price": price,
                                "change": chg,
                                "chg_pct": chg_pct,
                                "volume": vol,
                                "source": _bz_label,
                                "_ts": _mov_now,
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
                        "_ts": ev.ts,
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
                _now_mov = time.time()
                for m in _sorted_movers[:100]:
                    _dir_icon = "🟢" if m.get("chg_pct", 0) > 0 else "🔴"
                    _mov_rows.append({
                        "Dir": _dir_icon,
                        "Symbol": m["symbol"],
                        "Name": m.get("name", ""),
                        "Price": f"${m['price']:.2f}" if m["price"] >= 1 else f"${m['price']:.4f}",
                        "Change": f"{m['change']:+.2f}",
                        "Change %": f"{m['chg_pct']:+.2f}%",
                        "Age": format_age_string(m.get("_ts"), now=_now_mov),
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
                        "Dir": st.column_config.TextColumn("Dir", width="small"),
                        "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                        "Name": st.column_config.TextColumn("Name", width="medium"),
                        "Change %": st.column_config.TextColumn("Change %", width="small"),
                        "Age": st.column_config.TextColumn("Age", width="small"),
                    },
                )

                # Technical Analysis expander
                _mov_symbols = [m["symbol"] for m in _sorted_movers[:50]]
                _render_technicals_expander(_mov_symbols, key_prefix="tech_movers")
                _render_forecast_expander(_mov_symbols, key_prefix="fc_movers")
                _render_event_clusters_expander(_mov_symbols, key_prefix="ec_movers")

    # ── TAB: Rankings (real-time price-based) ─────────────────
    with tab_rank:
        fmp_key_rank = st.session_state.cfg.fmp_api_key
        bz_key_rank = st.session_state.cfg.benzinga_api_key
        _session_label_rank = _session_icons.get(_current_session, _current_session)

        if not fmp_key_rank and not bz_key_rank:
            st.info("Set `FMP_API_KEY` and/or `BENZINGA_API_KEY` in `.env` for real-time rankings.")
        else:
            st.subheader("🏆 Real-Time Rankings")
            st.caption(f"**{_session_label_rank}** — All movers ranked by absolute price change %. Combines multiple data sources + RT Spike data.")

            # Build unified symbol map (same data as Movers, re-sorted by abs change)
            _rank_now = time.time()
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
                                "_ts": _rank_now,
                            }

            # 2) Market movers
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
                                "_ts": _rank_now,
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
                        "_ts": ev.ts,
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

                # NLP sentiment enrichment for top ranked symbols
                _rank_nlp: dict[str, NLPSentiment] = {}
                if newsapi_available():
                    _rank_syms = [m["symbol"] for m in _ranked[:30]]
                    _rank_nlp = fetch_nlp_sentiment(_rank_syms, hours=24)

                top_n = min(50, len(_ranked))
                _rank_rows = []
                for i, m in enumerate(_ranked[:top_n], 1):
                    _dir = "🟢" if m.get("chg_pct", 0) > 0 else "🔴" if m.get("chg_pct", 0) < 0 else "⚪"
                    _sent_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(
                        (m.get("sentiment") or "").lower(), ""
                    )
                    _hl_url = m.get("url", "")
                    _hl_text = m.get("headline", "")
                    _nlp_r = _rank_nlp.get(m["symbol"])
                    _nlp_col = ""
                    if _nlp_r and _nlp_r.article_count > 0:
                        _nlp_col = f"{_nlp_r.icon} {_nlp_r.nlp_score:+.2f}"
                    elif _rank_nlp:
                        _nlp_col = "⚪ —"
                    _rank_rows.append({
                        "#": i,
                        "Dir": _dir,
                        "Symbol": m["symbol"],
                        "Name": m.get("name", ""),
                        "Price": f"${m['price']:.2f}" if m["price"] >= 1 else f"${m['price']:.4f}",
                        "Change": f"{m['change']:+.2f}",
                        "Change %": f"{m['chg_pct']:+.2f}%",
                        "Score": round(_composite_score(m), 2),
                        "Age": format_age_string(m.get("_ts")),
                        "Sentiment": f"{_sent_icon} {m.get('sentiment', '')}" if m.get("sentiment") else "",
                        "NLP": _nlp_col,
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

                with st.popover("ℹ️ Column guide"):
                    st.markdown(
                        "- **Sentiment** — From news feed; shows when a news article matches this ticker\n"
                        "- **NLP Sent.** — NLP sentiment from NewsAPI.ai (requires `NEWSAPI_AI_KEY` env var)\n"
                        "- **Headline** — Latest matching news headline (clickable when a URL is available)\n"
                        "- **Volume** — Trading volume from market data source\n\n"
                        "Empty columns mean no matching data is available yet for that ticker."
                    )

                # Build column config
                _rank_col_cfg: dict[str, Any] = {
                    "Dir": st.column_config.TextColumn("Dir", width="small"),
                    "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                    "Change %": st.column_config.TextColumn("Change %", width="small"),
                    "Score": st.column_config.NumberColumn("Score", width="small"),
                    "Age": st.column_config.TextColumn("Age", width="small"),
                    "NLP": st.column_config.TextColumn("NLP Sent.", width="small"),
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

                # Technical Analysis expander
                _rank_symbols = [m["symbol"] for m in _ranked[:50]]
                _render_technicals_expander(_rank_symbols, key_prefix="tech_rank")
                _render_forecast_expander(_rank_symbols, key_prefix="fc_rank")
                _render_event_clusters_expander(_rank_symbols, key_prefix="ec_rank")

    # ── TAB: Segments ───────────────────────────────────────
    with tab_segments:
        seg_rows = aggregate_segments(feed)

        if not seg_rows:
            st.info("No segment data yet. Channels are populated by news articles.")
        else:
            # ── Overview table (expandable rows) ────────────────────
            st.caption(f"{len(seg_rows)} segments across {len(feed)} articles")

            for _sr in seg_rows:
                _sr_name = safe_markdown_text(_sr["segment"])
                _sr_sent = _sr["sentiment"]
                _sr_n = _sr["articles"]
                _sr_tk = _sr["tickers"]
                _sr_avg = _sr["avg_score"]
                _exp_hdr = (
                    f"{_sr_sent} **{_sr_name}** — "
                    f"{_sr_n} articles · {_sr_tk} tickers · avg {_sr_avg:.3f}"
                )
                with st.expander(_exp_hdr):
                    _sr_items = sorted(
                        _sr.get("_items", []),
                        key=lambda d: d.get("news_score", 0),
                        reverse=True,
                    )
                    _sr_items = dedup_articles(_sr_items)[:20]
                    if not _sr_items:
                        st.caption("No articles.")
                    for _si in _sr_items:
                        _si_hl = (_si.get("headline") or "(no headline)")[:120]
                        _si_url = _si.get("url", "")
                        _si_tk = _si.get("ticker", "")
                        _si_sc = _si.get("news_score", 0)
                        if _si_url:
                            st.markdown(
                                f"- [{safe_markdown_text(_si_hl)}]({safe_url(_si_url)})"
                                f" · `{_si_tk}` · {_si_sc:.3f}"
                            )
                        else:
                            st.markdown(
                                f"- {safe_markdown_text(_si_hl)}"
                                f" · `{_si_tk}` · {_si_sc:.3f}"
                            )

            st.divider()

            # ── Per-segment drill-down ──────────────────────────────
            leading, neutral_segs, lagging = split_segments_by_sentiment(seg_rows)

            scols = st.columns(3)

            def _render_seg_block(label: str, segments: list, bold: bool = True) -> None:
                """Item 3 — shared segment article renderer."""
                st.markdown(f"**{label}**")
                if not segments:
                    st.caption("None")
                for r in segments[:8]:
                    _seg_title = safe_markdown_text(r['segment'])
                    _exp_label = f"**{_seg_title}**" if bold else _seg_title
                    with st.expander(f"{_exp_label} — {r['articles']} articles, avg {r['avg_score']:.3f}"):
                        _seg_articles = sorted(
                            r.get("_items", []),
                            key=lambda d: d.get("news_score", 0),
                            reverse=True,
                        )
                        _seg_articles = dedup_articles(_seg_articles)[:20]
                        for _sa in _seg_articles:
                            _sa_hl = (_sa.get("headline") or "(no headline)")[:100]
                            _sa_url = _sa.get("url", "")
                            _sa_tk = _sa.get("ticker", "")
                            _sa_sc = _sa.get("news_score", 0)
                            if _sa_url:
                                st.markdown(f"- [{safe_markdown_text(_sa_hl)}]({_sa_url}) · `{_sa_tk}` · {_sa_sc:.3f}")
                            else:
                                st.markdown(f"- {safe_markdown_text(_sa_hl)} · `{_sa_tk}` · {_sa_sc:.3f}")

            with scols[0]:
                _render_seg_block("🟢 Bullish Segments", leading)
            with scols[1]:
                _render_seg_block("🟡 Neutral Segments", neutral_segs, bold=False)
            with scols[2]:
                _render_seg_block("🔴 Bearish Segments", lagging)

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
                # Build display table
                _rt_rows = []
                for ev in _rt_events:
                    _rt_rows.append({
                        "Signal": f"{ev.icon} Price Spike {ev.direction}",
                        "Symbol": ev.symbol,
                        "Time": format_time_et(ev.ts),
                        "Age": format_age_string(ev.ts),
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

                # Technical Analysis expander
                _rt_symbols = list(dict.fromkeys(ev.symbol for ev in _rt_events[:50]))
                _render_technicals_expander(_rt_symbols, key_prefix="tech_rt")
                _render_forecast_expander(_rt_symbols, key_prefix="fc_rt")
                _render_event_clusters_expander(_rt_symbols, key_prefix="ec_rt")

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
                    "Extended-hours prices overlaid from delayed quotes."
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
            _spike_ts = time.time()
            spike_rows = build_spike_rows(
                spike_data["gainers"],
                spike_data["losers"],
                spike_data["actives"],
            )
            for _sr in spike_rows:
                _sr["_ts"] = _spike_ts

            # Overlay extended-hours quotes when outside regular session
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
                _now_sp = time.time()
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
                        "Age": format_age_string(r.get("_ts"), now=_now_sp),
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

                # Technical Analysis expander
                _spike_symbols = list(dict.fromkeys(r["symbol"] for r in filtered_spikes[:50]))
                _render_technicals_expander(_spike_symbols, key_prefix="tech_spikes")
                _render_forecast_expander(_spike_symbols, key_prefix="fc_spikes")
                _render_event_clusters_expander(_spike_symbols, key_prefix="ec_spikes")

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

            # Build GICS sector mapping from FMP profile data
            _hm_fmp_key = st.session_state.cfg.fmp_api_key
            _hm_sector_map: dict[str, str] | None = None
            if _hm_fmp_key and feed:
                _hm_tickers = sorted({
                    d.get("ticker", "")
                    for d in feed
                    if d.get("ticker") and d.get("ticker") not in ("", "MARKET", "?")
                })
                if _hm_tickers:
                    _hm_sector_map = _cached_ticker_sectors(
                        _hm_fmp_key, ",".join(_hm_tickers)
                    )

            hm_data = build_heatmap_data(feed, sector_map=_hm_sector_map)

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
                    title="GICS Sector × Ticker Heatmap (article count, colored by sentiment)",
                )
                fig.update_layout(
                    height=600,
                    margin=dict(t=40, l=0, r=0, b=0),
                    paper_bgcolor="#0E1117",
                    font_color="white",
                )
                st.plotly_chart(fig, width='stretch')
                if _hm_sector_map:
                    st.caption(
                        "💡 Tickers are grouped by GICS sector (via FMP profile data). "
                        'Tickers without a known sector appear under "Other".'
                    )
                else:
                    st.caption(
                        "💡 Set `FMP_API_KEY` to group tickers by GICS sector. "
                        "Currently grouped by news article channels."
                    )
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
                    _bz_tier_warning("FMP industry performance", "No sector data returned from FMP.")
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
                    hide_index=True,
                    column_config={
                        "date": st.column_config.TextColumn("Date", width="medium"),
                        "impact": st.column_config.TextColumn("Impact", width="small"),
                    },
                )
                st.caption("💡 Sorted by date ascending. Use the Impact filter above to narrow to High/Medium/Low.")

                # ── Upcoming highlights ─────────────────────────────
                now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
                upcoming = df_cal[df_cal["date"] >= now_str] if "date" in df_cal.columns else pd.DataFrame()
                if not upcoming.empty:
                    st.subheader("⏰ Upcoming")
                    for _, row in upcoming.head(10).iterrows():
                        impact = row.get("impact", "")
                        impact_icon = "🔴" if impact == "High" else ("🟠" if impact == "Medium" else "🟡")
                        _cal_ev = safe_markdown_text(str(row.get('event', '?')))
                        st.markdown(
                            f"{impact_icon} **{_cal_ev}** — "
                            f"{row.get('country', '?')} | {row.get('date', '?')} | "
                            f"Prev: {row.get('previous', '?')} | Cons: {row.get('consensus', '?')}"
                        )
            else:
                st.info("No calendar events found for the selected range.")

    # ── TAB: Outlook ────────────────────────────────────────
    with tab_outlook:
        st.subheader("🔮 Outlook — Next-Trading-Day Assessment")

        bz_key = cfg.benzinga_api_key
        fmp_key = cfg.fmp_api_key

        if not bz_key and not fmp_key:
            st.warning("Configure at least one API key to compute the outlook.")
        else:
            _today_iso = datetime.now(UTC).strftime("%Y-%m-%d")

            # API-heavy factors (earnings, economics, sectors) are cached.
            # Feed sentiment is computed live below since the feed is mutable
            # session state that cannot be hashed for caching.
            outlook = _cached_tomorrow_outlook(bz_key, fmp_key, _cache_buster=_today_iso)

            # Overlay live feed sentiment on top of cached outlook
            _feed_for_outlook = feed[-200:] if feed else []
            if _feed_for_outlook:
                _bear_c = sum(
                    1 for it in _feed_for_outlook
                    if str(it.get("sentiment_label") or "").lower() == "bearish"
                )
                _bull_c = sum(
                    1 for it in _feed_for_outlook
                    if str(it.get("sentiment_label") or "").lower() == "bullish"
                )
                _total_f = len(_feed_for_outlook)
                if _total_f > 10:
                    _bear_ratio = _bear_c / _total_f
                    _bull_ratio = _bull_c / _total_f
                    if _bear_ratio > 0.55:
                        _feed_sentiment_label = "🔴 Bearish-heavy"
                    elif _bull_ratio > 0.55:
                        _feed_sentiment_label = "🟢 Bullish-heavy"
                    else:
                        _feed_sentiment_label = "🟡 Mixed"
                else:
                    _feed_sentiment_label = "⚪ Insufficient data"
            else:
                _feed_sentiment_label = "⚪ No feed data"

            # ── Traffic light banner ──
            o_label = outlook.get("outlook_label", "🟡 NEUTRAL")
            o_color = outlook.get("outlook_color", "orange")
            next_td_str = outlook.get("next_trading_day", "—")

            st.markdown(
                f"<div style='padding:0.8rem 1.2rem;border-radius:0.6rem;"
                f"background:{o_color};color:white;font-weight:700;"
                f"font-size:1.3rem;text-align:center;margin-bottom:1rem'>"
                f"{o_label} — {next_td_str}</div>",
                unsafe_allow_html=True,
            )

            # ── Key metrics ──
            ocols = st.columns(5)
            ocols[0].metric("Outlook Score", f"{outlook.get('outlook_score', 0):.2f}")
            ocols[1].metric("Earnings Tomorrow", outlook.get("earnings_tomorrow_count", 0))
            ocols[2].metric("Earnings BMO", outlook.get("earnings_bmo_tomorrow_count", 0))
            ocols[3].metric("High-Impact Events", outlook.get("high_impact_events_tomorrow", 0))
            ocols[4].metric("Feed Sentiment", _feed_sentiment_label)

            st.divider()

            # ── High-impact events detail ──
            hi_details: list[dict[str, Any]] = outlook.get("high_impact_events_tomorrow_details") or []
            if hi_details:
                st.subheader("📋 Scheduled High-Impact Events")
                _show_unmatched_hi = st.toggle(
                    "Show scheduled events without related feed articles",
                    value=False,
                    key="outlook_show_unmatched_events",
                    help="When off, only events with at least one related article in the current feed are shown.",
                )
                _rendered_hi = 0
                for _hi_ev in hi_details:
                    _hi_name_raw = str(_hi_ev.get("event", "—"))
                    _hi_name = safe_markdown_text(_hi_name_raw)
                    _hi_country = safe_markdown_text(str(_hi_ev.get("country", "US")))
                    _hi_source = safe_markdown_text(str(_hi_ev.get("source", "")))
                    # Find related articles in current feed
                    _hi_keywords = [w.lower() for w in _hi_name_raw.split() if len(w) > 3]
                    _hi_articles: list[dict[str, Any]] = []
                    if _hi_keywords and feed:
                        for _fd in feed:
                            _fd_hl = str(_fd.get("headline") or "").lower()
                            if _fd_hl and any(kw in _fd_hl for kw in _hi_keywords):
                                _hi_articles.append(_fd)
                        _hi_articles = dedup_articles(
                            sorted(_hi_articles, key=lambda d: d.get("news_score", 0), reverse=True)
                        )[:20]

                    if not _hi_articles and not _show_unmatched_hi:
                        continue

                    _rendered_hi += 1
                    _hi_match_label = f" · {len(_hi_articles)} related" if _hi_articles else ""
                    with st.expander(f"**{_hi_name}** ({_hi_country}) — Source: {_hi_source}{_hi_match_label}"):
                        if _hi_articles:
                            for _ha in _hi_articles:
                                _ha_hl = (str(_ha.get("headline") or "(no headline)"))[:100]
                                _ha_url = _ha.get("url", "")
                                _ha_tk = _ha.get("ticker", "")
                                _ha_sc = _ha.get("news_score", 0)
                                if _ha_url:
                                    st.markdown(f"- [{safe_markdown_text(_ha_hl)}]({_ha_url}) · `{_ha_tk}` · {_ha_sc:.3f}")
                                else:
                                    st.markdown(f"- {safe_markdown_text(_ha_hl)} · `{_ha_tk}` · {_ha_sc:.3f}")
                        else:
                            st.caption(
                                "No related articles in current feed yet. "
                                "This event is from the macro calendar and may not be covered in headlines yet."
                            )
                if _rendered_hi == 0:
                    st.info(
                        "No related feed articles found for scheduled high-impact events right now. "
                        "Enable 'Show scheduled events without related feed articles' to view all calendar entries."
                    )
            else:
                st.info("No high-impact macro events scheduled for the next trading day.")

            # ── Notable earnings ──
            notable = outlook.get("notable_earnings") or []
            if notable:
                st.subheader(f"📊 Earnings Reporting on {next_td_str}")
                _ne_df = pd.DataFrame(notable)
                display_cols = [c for c in ["ticker", "name", "timing"] if c in _ne_df.columns]
                st.dataframe(
                    _ne_df[display_cols] if display_cols else _ne_df,
                    width='stretch',
                    height=min(400, 40 + 35 * len(_ne_df)),
                )

            # ── Reasoning factors ──
            reasons = outlook.get("reasons") or []
            if reasons:
                st.divider()
                st.caption("**Factors:** " + " · ".join(reasons))

            # ── Sector mood ──
            sector_mood = outlook.get("sector_mood", "neutral")
            mood_emoji = {"risk-on": "🟢", "risk-off": "🔴", "neutral": "🟡"}.get(sector_mood, "⚪")
            st.caption(f"**Sector Mood:** {mood_emoji} {sector_mood.title()}")

            # ── Trending Themes (NewsAPI.ai market awareness) ──
            if newsapi_available():
                _outlook_trending = fetch_trending_concepts(count=10, source="news")
                if _outlook_trending:
                    st.divider()
                    st.subheader("🔥 Trending Themes in Global News")
                    st.caption("Real-time trending entities — emerging themes that may affect tomorrow's session.")
                    _show_unmatched_themes = st.toggle(
                        "Show themes without feed matches",
                        value=False,
                        key="outlook_show_unmatched_themes",
                        help="When off, only themes with at least one related article in the current feed are shown.",
                    )
                    _rendered_themes = 0

                    for _tc in _outlook_trending[:8]:
                        # Find related articles in current feed
                        _tc_label_lower = _tc.label.lower()
                        _tc_keywords = [w.lower() for w in _tc.label.split() if len(w) > 3]
                        _tc_articles: list[dict[str, Any]] = []
                        if feed and (_tc_keywords or len(_tc_label_lower) > 3):
                            for _fd in feed:
                                _fd_hl = str(_fd.get("headline") or "").lower()
                                if not _fd_hl:
                                    continue
                                if _tc_label_lower in _fd_hl or (
                                    _tc_keywords and any(kw in _fd_hl for kw in _tc_keywords)
                                ):
                                    _tc_articles.append(_fd)
                            _tc_articles = dedup_articles(
                                sorted(_tc_articles, key=lambda d: d.get("news_score", 0), reverse=True)
                            )[:20]

                        if not _tc_articles and not _show_unmatched_themes:
                            continue

                        _rendered_themes += 1
                        _tc_match_label = f" · {len(_tc_articles)} in feed" if _tc_articles else ""
                        with st.expander(
                            f"{_tc.type_icon} **{safe_markdown_text(_tc.label)}** "
                            f"({_tc.article_count} global){_tc_match_label}"
                        ):
                            if _tc_articles:
                                for _ta in _tc_articles:
                                    _ta_hl = (str(_ta.get("headline") or "(no headline)"))[:100]
                                    _ta_url = _ta.get("url", "")
                                    _ta_tk = _ta.get("ticker", "")
                                    _ta_sc = _ta.get("news_score", 0)
                                    if _ta_url:
                                        st.markdown(f"- [{safe_markdown_text(_ta_hl)}]({_ta_url}) · `{_ta_tk}` · {_ta_sc:.3f}")
                                    else:
                                        st.markdown(f"- {safe_markdown_text(_ta_hl)} · `{_ta_tk}` · {_ta_sc:.3f}")
                            else:
                                st.caption(
                                    "No related articles in current feed yet. "
                                    "Theme is trending globally but not represented in your current feed window."
                                )

                    if _rendered_themes == 0:
                        st.info(
                            "No related feed articles found for current trending themes. "
                            "Enable 'Show themes without feed matches' to inspect all global themes."
                        )

                    # Sentiment of trending entities
                    _trend_labels = [c.label for c in _outlook_trending[:5] if c.concept_type in ("org", "person")]
                    if _trend_labels:
                        _trend_nlp = fetch_nlp_sentiment(_trend_labels, hours=12)
                        if any(v.article_count > 0 for v in _trend_nlp.values()):
                            st.markdown("**Sentiment of top trending entities:**")
                            for _tl in _trend_labels:
                                _tn = _trend_nlp.get(_tl)
                                if _tn and _tn.article_count > 0:
                                    st.markdown(
                                        f"- {_tn.icon} **{_tl}**: NLP {_tn.nlp_score:+.2f} "
                                        f"({_tn.article_count} articles, {_tn.agreement:.0%} agreement)"
                                    )

    # ── TAB: AI Insights ────────────────────────────────────────
    with tab_ai:
        st.markdown('<div id="ai-insights"></div>', unsafe_allow_html=True)
        from terminal_tabs.tab_ai import render as render_ai
        _safe_tab("AI Insights", render_ai, feed, current_session=_current_session)

    # ── TAB: Market Movers + Quotes ────────────────
    with tab_bz_movers:
        bz_key = st.session_state.cfg.benzinga_api_key
        if not bz_key:
            st.info("Set `BENZINGA_API_KEY` in `.env` for market movers & quotes.")
        else:
            st.subheader("💹 Market Movers")

            # Session indicator — movers are regular-session only
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
                st.caption("Real-time market movers. Gainers & Losers with delayed quotes.")

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
                            "Age": format_age_string(time.time()),
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
                            "Age": format_age_string(time.time()),
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

            st.caption(
                "💡 Sector column may be empty — movers endpoints do not always "
                "include GICS sector classification. Check the *Segments* tab for sector-level data."
            )

            # ── Delayed Quotes Lookup ───────────────────────
            st.divider()
            st.subheader("🔎 Delayed Quotes Lookup")
            st.caption("Enter up to 50 comma-separated tickers for delayed quotes.")

            # Auto-populate from feed tickers
            _feed_tickers = sorted(set(d.get("ticker", "") for d in feed if d.get("ticker") and d.get("ticker") != "MARKET"))[:20]
            _default_symbols = ",".join(_feed_tickers) if _feed_tickers else "AAPL,NVDA,TSLA,MSFT,AMZN,SPY,QQQ"

            quote_symbols = st.text_input(
                "Symbols", value=_default_symbols,
                key="bz_quote_symbols",
                placeholder="AAPL, NVDA, TSLA, ...",
            )

            if quote_symbols.strip():
                # Sanitize: allow only alphanumeric, commas, dots, spaces, hyphens
                _sanitized_syms = re.sub(r"[^A-Za-z0-9,.\- ]", "", quote_symbols)
                quotes_data = _cached_bz_quotes(bz_key, _sanitized_syms)
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

    # ── TAB: Bitcoin ────────────────────────────────────────
    with tab_bitcoin:
        st.subheader("₿ Bitcoin Dashboard")
        st.caption("🟢 Market: 24/7 — always open")

        if not btc_available():
            st.warning("No data sources available. Set FMP_API_KEY or install yfinance / tradingview_ta.")
        else:
            # ── Tomorrow Outlook (on top as requested) ──────
            with st.container():
                st.markdown("### 🔮 Bitcoin Outlook")
                _btc_outlook = fetch_btc_outlook()
                if _btc_outlook and not _btc_outlook.error:
                    _oc1, _oc2, _oc3, _oc4 = st.columns(4)
                    with _oc1:
                        st.metric(
                            "Trend",
                            _btc_outlook.trend_label,
                            delta=f"RSI {_btc_outlook.rsi:.1f}" if _btc_outlook.rsi else None,
                        )
                    with _oc2:
                        if _btc_outlook.fear_greed:
                            _ol_fg = _btc_outlook.fear_greed
                            _fg_val = _ol_fg.value
                            _fg_label = _ol_fg.label
                            st.metric("Fear & Greed", f"{_fg_val:.0f}", delta=_fg_label)
                            with st.expander(f"ℹ️ {_fg_label} — what does {_fg_val:.0f} mean?"):
                                st.markdown(
                                    f"**Fear & Greed Index: {_fg_val:.0f}** means **{_fg_label}**. "
                                    "The scale runs 0–100:\n\n"
                                    "| Range | Meaning |\n"
                                    "|---|---|\n"
                                    "| **0–24** | Extreme Fear — investors are very worried (often a contrarian buy signal) |\n"
                                    "| **25–49** | Fear |\n"
                                    "| **50** | Neutral |\n"
                                    "| **51–74** | Greed |\n"
                                    "| **75–100** | Extreme Greed — market euphoria (often a contrarian sell signal) |\n\n"
                                    f"A reading of **{_fg_val:.0f}** indicates the market is in "
                                    f"{'deep panic territory.' if _fg_val < 25 else 'a fearful state.' if _fg_val < 50 else 'neutral territory.' if _fg_val < 55 else 'a greedy state.' if _fg_val < 75 else 'euphoric territory.'}"
                                )
                    with _oc3:
                        st.metric("Support", format_btc_price(_btc_outlook.support))
                    with _oc4:
                        st.metric("Resistance", format_btc_price(_btc_outlook.resistance))

                    # Technicals summary row
                    _tc1, _tc2, _tc3 = st.columns(3)
                    for _col, _label, _tech in [
                        (_tc1, "1H", _btc_outlook.technicals_1h),
                        (_tc2, "4H", _btc_outlook.technicals_4h),
                        (_tc3, "1D", _btc_outlook.technicals_1d),
                    ]:
                        with _col:
                            if _tech and not _tech.error:
                                st.markdown(
                                    f"**{_label}:** {technicals_signal_icon(_tech.summary)} "
                                    f"{technicals_signal_label(_tech.summary)} "
                                    f"(Buy {_tech.buy} / Sell {_tech.sell} / Neutral {_tech.neutral})"
                                )
                            elif _tech and _tech.error:
                                st.caption(f"{_label}: ⚠️ {_tech.error}")

                    with st.expander("📋 Full Outlook Analysis", expanded=True):
                        st.markdown(_btc_outlook.summary_text)
                elif _btc_outlook and _btc_outlook.error:
                    st.warning(f"⚠️ Bitcoin outlook unavailable: {_btc_outlook.error}")

                st.markdown("---")

            # ── Real-time Quote ─────────────────────────────
            _btc_quote = fetch_btc_quote()
            if _btc_quote and _btc_quote.price > 0:
                st.markdown("### 💰 Real-time Quote")
                _qc1, _qc2, _qc3, _qc4 = st.columns(4)
                with _qc1:
                    st.metric(
                        "BTC Price",
                        format_btc_price(_btc_quote.price),
                        delta=f"{_btc_quote.change_pct:+.2f}%",
                    )
                with _qc2:
                    st.metric("24h Volume", format_large_number(_btc_quote.volume))
                with _qc3:
                    st.metric("Day Range", f"{format_btc_price(_btc_quote.day_low)} – {format_btc_price(_btc_quote.day_high)}")
                with _qc4:
                    st.metric("Market Cap", format_large_number(_btc_quote.market_cap))

                _qc5, _qc6, _qc7, _qc8 = st.columns(4)
                with _qc5:
                    st.metric("Open", format_btc_price(_btc_quote.open_price))
                with _qc6:
                    st.metric("Prev Close", format_btc_price(_btc_quote.prev_close))
                with _qc7:
                    st.metric("52w High", format_btc_price(_btc_quote.year_high))
                with _qc8:
                    st.metric("52w Low", format_btc_price(_btc_quote.year_low))

                st.markdown("---")

            # ── Combined Price + Volume Chart ───────────────
            with st.expander("📊 Price & Volume Chart (48h)"):
                try:
                    import plotly.graph_objects as go
                    from plotly.subplots import make_subplots

                    _ohlcv_10m = fetch_btc_ohlcv_10min(hours=48)
                    if _ohlcv_10m:
                        _chart_dates = [r["date"] for r in _ohlcv_10m]
                        _chart_opens = [r["open"] for r in _ohlcv_10m]
                        _chart_highs = [r["high"] for r in _ohlcv_10m]
                        _chart_lows = [r["low"] for r in _ohlcv_10m]
                        _chart_closes = [r["close"] for r in _ohlcv_10m]
                        _chart_volumes = [r["volume"] for r in _ohlcv_10m]

                        # Color volume bars by direction
                        _vol_colors = [
                            "rgba(38, 166, 91, 0.6)" if c >= o else "rgba(239, 83, 80, 0.6)"
                            for o, c in zip(_chart_opens, _chart_closes)
                        ]

                        fig = make_subplots(
                            rows=2, cols=1,
                            shared_xaxes=True,
                            vertical_spacing=0.03,
                            row_heights=[0.7, 0.3],
                            subplot_titles=("BTC/USD · 10min Candles", "Volume (10min)"),
                        )

                        # Candlestick chart
                        fig.add_trace(
                            go.Candlestick(
                                x=_chart_dates,
                                open=_chart_opens,
                                high=_chart_highs,
                                low=_chart_lows,
                                close=_chart_closes,
                                name="BTC/USD",
                                increasing_line_color="#26a65b",
                                decreasing_line_color="#ef5350",
                                increasing_fillcolor="#26a65b",
                                decreasing_fillcolor="#ef5350",
                            ),
                            row=1, col=1,
                        )

                        # Volume bars
                        fig.add_trace(
                            go.Bar(
                                x=_chart_dates,
                                y=_chart_volumes,
                                name="Volume",
                                marker_color=_vol_colors,
                                opacity=0.7,
                            ),
                            row=2, col=1,
                        )

                        fig.update_layout(
                            height=650,
                            template="plotly_dark",
                            showlegend=False,
                            xaxis_rangeslider_visible=False,
                            margin=dict(l=50, r=20, t=40, b=20),
                            font=dict(size=11),
                        )
                        fig.update_yaxes(title_text="Price (USD)", row=1, col=1)
                        fig.update_yaxes(title_text="Volume", row=2, col=1)
                        fig.update_xaxes(title_text="Time (UTC)", row=2, col=1)

                        st.plotly_chart(fig, width='stretch')
                    else:
                        st.info("No 10-minute OHLCV data available. Install yfinance and pandas for chart data.")
                except ImportError:
                    st.warning("Install plotly for charts: `pip install plotly`")

            st.markdown("---")

            # ── Technical Analysis ──────────────────────────
            st.markdown("### 📐 Technical Analysis")
            _btc_tech_interval = st.selectbox(
                "Interval", ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"],
                index=4,  # default 1h
                key="btc_tech_interval",
            )
            _btc_tech = fetch_btc_technicals(_btc_tech_interval)
            if _btc_tech and not _btc_tech.error:
                _tech_c1, _tech_c2, _tech_c3 = st.columns(3)
                with _tech_c1:
                    st.markdown(
                        f"**Overall:** {technicals_signal_icon(_btc_tech.summary)} "
                        f"{technicals_signal_label(_btc_tech.summary)}"
                    )
                    st.caption(f"Buy {_btc_tech.buy} · Sell {_btc_tech.sell} · Neutral {_btc_tech.neutral}")
                with _tech_c2:
                    st.markdown(
                        f"**Oscillators:** {technicals_signal_icon(_btc_tech.osc_signal)} "
                        f"{technicals_signal_label(_btc_tech.osc_signal)}"
                    )
                    st.caption(f"Buy {_btc_tech.osc_buy} · Sell {_btc_tech.osc_sell} · Neutral {_btc_tech.osc_neutral}")
                with _tech_c3:
                    st.markdown(
                        f"**Moving Avgs:** {technicals_signal_icon(_btc_tech.ma_signal)} "
                        f"{technicals_signal_label(_btc_tech.ma_signal)}"
                    )
                    st.caption(f"Buy {_btc_tech.ma_buy} · Sell {_btc_tech.ma_sell} · Neutral {_btc_tech.ma_neutral}")

                # Key indicators
                with st.expander("📊 Key Indicators"):
                    _ind_c1, _ind_c2, _ind_c3 = st.columns(3)
                    with _ind_c1:
                        if _btc_tech.rsi is not None:
                            _rsi_status = "🔴 Overbought" if _btc_tech.rsi > 70 else ("🟢 Oversold" if _btc_tech.rsi < 30 else "⚪ Normal")
                            st.metric("RSI (14)", f"{_btc_tech.rsi:.1f}", delta=_rsi_status)
                        if _btc_tech.adx is not None:
                            st.metric("ADX", f"{_btc_tech.adx:.1f}")
                    with _ind_c2:
                        if _btc_tech.macd is not None:
                            _macd_delta = "Bullish" if _btc_tech.macd > 0 else "Bearish"
                            st.metric("MACD", f"{_btc_tech.macd:.2f}", delta=_macd_delta)
                        if _btc_tech.cci is not None:
                            st.metric("CCI (20)", f"{_btc_tech.cci:.1f}")
                    with _ind_c3:
                        if _btc_tech.stoch_k is not None:
                            st.metric("Stoch %K", f"{_btc_tech.stoch_k:.1f}")
                        if _btc_tech.macd_signal is not None:
                            st.metric("MACD Signal", f"{_btc_tech.macd_signal:.2f}")
            elif _btc_tech and _btc_tech.error:
                st.warning(f"Technical analysis unavailable: {_btc_tech.error}")

            st.markdown("---")

            # ── Fear & Greed Index ──────────────────────────
            st.markdown("### 😱 Fear & Greed Index")
            _fg = fetch_fear_greed()
            if _fg:
                _fg_c1, _fg_c2 = st.columns([1, 3])
                with _fg_c1:
                    st.metric(f"{_fg.icon} Index", f"{_fg.value:.0f}", delta=_fg.label)
                with _fg_c2:
                    # Simple gauge using progress bar
                    st.progress(min(_fg.value / 100, 1.0), text=f"{_fg.label} ({_fg.value:.0f}/100)")
                    st.caption(f"Updated: {_fg.timestamp}")
            else:
                st.info("Fear & Greed data not available. Set FMP_API_KEY.")

            st.markdown("---")

            # ── Market Cap & Supply ─────────────────────────
            st.markdown("### 🏦 Market Cap & Supply")
            _supply = fetch_btc_supply()
            if _supply and _supply.market_cap > 0:
                _sc1, _sc2, _sc3 = st.columns(3)
                with _sc1:
                    st.metric("Market Cap", format_large_number(_supply.market_cap))
                    st.metric("Circulating Supply", format_supply(_supply.circulating_supply))
                with _sc2:
                    st.metric("Max Supply", "21.00M BTC")
                    _pct_mined = (_supply.circulating_supply / 21_000_000 * 100) if _supply.circulating_supply > 0 else 0
                    st.progress(min(_pct_mined / 100, 1.0), text=f"{_pct_mined:.1f}% mined")
                with _sc3:
                    st.metric("50-day Avg", format_btc_price(_supply.fifty_day_avg))
                    st.metric("200-day Avg", format_btc_price(_supply.two_hundred_day_avg))
            else:
                st.info("Supply data not available. Install yfinance.")

            st.markdown("---")

            # ── Bitcoin News ────────────────────────────────
            st.markdown("### 📰 Bitcoin News")
            _btc_news_articles = fetch_btc_news(limit=10)
            if _btc_news_articles:
                for _btc_art in _btc_news_articles:
                    _art_title = _btc_art.get("title", "")
                    _art_url = _btc_art.get("url", "")
                    _art_source = _btc_art.get("source", "")
                    _art_date = _btc_art.get("date", "")
                    _art_sent = _btc_art.get("sentiment", "")
                    _sent_icon = "🟢" if _art_sent == "Bullish" else ("🔴" if _art_sent == "Bearish" else "⚪")
                    _source_str = f" — *{_art_source}*" if _art_source else ""
                    _date_str = f" · {_art_date[:10]}" if _art_date else ""
                    if _art_url:
                        st.markdown(f"- {_sent_icon} [{_art_title[:120]}]({_art_url}){_source_str}{_date_str}")
                    else:
                        st.markdown(f"- {_sent_icon} {_art_title[:120]}{_source_str}{_date_str}")
                    if _btc_art.get("text"):
                        st.caption(f"  {_btc_art['text'][:200]}...")
            else:
                st.info("No Bitcoin news available.")

            # NewsAPI.ai Bitcoin breaking events (if available)
            if newsapi_available() and has_tokens():
                with st.expander("🔴 NewsAPI.ai Bitcoin Headlines"):
                    _btc_breaking = fetch_breaking_events(count=20)
                    # Filter to Bitcoin-related events
                    _btc_breaking = [
                        ev for ev in _btc_breaking
                        if any(kw in (ev.title or "").lower() or kw in (ev.summary or "").lower()
                               for kw in ("bitcoin", "btc", "crypto", "cryptocurrency"))
                    ][:5]
                    if _btc_breaking:
                        for _ev in _btc_breaking:
                            st.markdown(f"- **{_ev.title}** (📰 {_ev.article_count} articles)")
                            if _ev.summary:
                                st.caption(f"  {_ev.summary[:200]}")
                    else:
                        st.caption("No Bitcoin breaking events found.")

            st.markdown("---")

            # ── Crypto Movers ───────────────────────────────
            st.markdown("### 🚀 Crypto Movers (24h)")
            _crypto_movers = fetch_crypto_movers()
            _movers_c1, _movers_c2 = st.columns(2)
            with _movers_c1:
                st.markdown("#### 🟢 Top Gainers")
                _gainers = _crypto_movers.get("gainers", [])[:10]
                if _gainers:
                    _gainer_data = [{
                        "Symbol": g.symbol,
                        "Name": g.name[:30],
                        "Price": f"${g.price:,.4f}" if g.price < 1 else f"${g.price:,.2f}",
                        "Change %": f"{g.change_pct:+.2f}%",
                    } for g in _gainers]
                    st.dataframe(_gainer_data, width='stretch', hide_index=True)
                else:
                    st.caption("No gainers data.")
            with _movers_c2:
                st.markdown("#### 🔴 Top Losers")
                _losers = _crypto_movers.get("losers", [])[:10]
                if _losers:
                    _loser_data = [{
                        "Symbol": lo.symbol,
                        "Name": lo.name[:30],
                        "Price": f"${lo.price:,.4f}" if lo.price < 1 else f"${lo.price:,.2f}",
                        "Change %": f"{lo.change_pct:+.2f}%",
                    } for lo in _losers]
                    st.dataframe(_loser_data, width='stretch', hide_index=True)
                else:
                    st.caption("No losers data.")

            st.markdown("---")

            # ── Exchange Listings ───────────────────────────
            with st.expander("🏦 Cryptocurrency Exchange Listings"):
                _listings = fetch_crypto_listings(limit=50)
                if _listings:
                    _listing_data = [{
                        "Symbol": li.symbol,
                        "Name": li.name,
                        "Currency": li.currency,
                        "Exchange": li.exchange,
                    } for li in _listings]
                    st.dataframe(_listing_data, width='stretch', hide_index=True, height=400)
                else:
                    st.info("No listing data available. Set FMP_API_KEY.")

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
                custom_tickers = re.sub(
                    r"[^A-Za-z0-9,.\- ]", "",
                    st.text_input(
                        "Tickers (comma-separated)",
                        value=DEFENSE_TICKERS,
                        key="defense_tickers_input",
                    ),
                ).strip().upper()

                def_data = _cached_defense_watchlist(fmp_key) if (not custom_tickers or custom_tickers == DEFENSE_TICKERS) else _cached_defense_watchlist_custom(fmp_key, custom_tickers)

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

                    st.caption(f"{len(df_ind)} {safe_markdown_text(industry_name)} stock(s)")
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
                        st.markdown(f"**Top 10 {safe_markdown_text(industry_name)} by Market Cap**")
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
                    st.info(f"No stocks found for industry: {safe_markdown_text(industry_name)}")

    # ── TAB: Breaking Events (NewsAPI.ai) ───────────────────
    with tab_breaking:
        st.subheader("🔴 Breaking Events")
        if not newsapi_available():
            _ok_newsapi, _newsapi_reason = newsapi_availability_status()
            st.info(_newsapi_reason or "NewsAPI.ai integration is currently unavailable.")
        else:
            # Token usage indicator
            _usage = get_token_usage()
            _avail = _usage.get("availableTokens", 0)
            _used = _usage.get("usedTokens", 0)
            if _avail > 0 and _used >= _avail:
                st.warning(
                    f"⚠️ NewsAPI.ai token limit reached ({_used:,}/{_avail:,} used). "
                    "Upgrade to a paid plan or wait for monthly reset."
                )
                st.stop()
            elif _avail > 0:
                _remaining = _avail - _used
                st.caption(f"📊 API tokens: {_remaining:,} remaining ({_used:,}/{_avail:,} used)")

            _brk_col1, _brk_col2, _brk_col3 = st.columns([1, 1, 1])
            with _brk_col1:
                _brk_count = st.slider(
                    "Max events", 5, 50, 20, key="brk_count",
                )
            with _brk_col2:
                _brk_min_articles = st.slider(
                    "Min articles", 2, 50, 5, key="brk_min_art",
                )
            with _brk_col3:
                _brk_category = st.selectbox(
                    "Category",
                    ["All", "Business", "Politics", "Technology", "Health", "Science", "Sports", "Entertainment"],
                    key="brk_cat",
                )

            _cat_uri = None
            if _brk_category != "All":
                _cat_uri = f"news/{_brk_category}"

            _breaking = fetch_breaking_events(
                count=_brk_count,
                min_articles=_brk_min_articles,
                category=_cat_uri,
            )

            if _breaking:
                st.caption(f"Showing {len(_breaking)} breaking events · Source: NewsAPI.ai (Event Registry)")
                for _ev in _breaking:
                    _ev_title = _ev.title or "(Untitled event)"
                    _art_badge = f"📰 {_ev.article_count}"
                    _loc_str = f" · 📍 {_ev.location}" if _ev.location else ""
                    _date_str = f" · 📅 {_ev.event_date}" if _ev.event_date else ""

                    with st.expander(
                        f"{_ev.sentiment_icon} **{_ev_title[:120]}** — {_art_badge} articles{_loc_str}{_date_str}",
                        expanded=False,
                    ):
                        # Top metrics row
                        _m1, _m2, _m3, _m4 = st.columns(4)
                        with _m1:
                            st.metric("Articles", _ev.article_count)
                        with _m2:
                            if _ev.sentiment is not None:
                                st.metric("Sentiment", f"{_ev.sentiment:+.2f}")
                            else:
                                st.metric("Sentiment", "n/a")
                        with _m3:
                            st.metric("Social Score", f"{_ev.social_score:,}" if _ev.social_score else "0")
                        with _m4:
                            st.metric("Date", _ev.event_date or "—")

                        # Summary
                        if _ev.summary:
                            st.markdown(f"**Summary:** {_ev.summary[:500]}")

                        # Concepts chips
                        if _ev.concepts:
                            _concept_chips = " · ".join(
                                f"`{c['label']}`" for c in _ev.concepts[:10] if c.get("label")
                            )
                            st.markdown(f"**Key entities:** {_concept_chips}")

                        # Categories
                        if _ev.categories:
                            _cat_chips = " · ".join(f"`{c}`" for c in _ev.categories[:5])
                            st.markdown(f"**Categories:** {_cat_chips}")

                        # Articles for this event — click to load (saves API tokens)
                        _art_key = f"brk_art_{_ev.uri}"
                        if st.button("📰 Load articles", key=_art_key):
                            st.session_state[_art_key] = True

                        if st.session_state.get(_art_key):
                            _ev_articles = fetch_event_articles(_ev.uri, count=5)
                            if _ev_articles:
                                st.markdown("---")
                                st.markdown("**Top articles (by social shares):**")
                                for _art in _ev_articles:
                                    _art_sent = newsapi_sentiment_badge(_art.sentiment) if _art.sentiment is not None else ""
                                    _art_source = f" — *{_art.source}*" if _art.source else ""
                                    _art_social = f" 📊{_art.social_score:,}" if _art.social_score else ""
                                    if _art.url:
                                        st.markdown(
                                            f"- [{_art.title[:100]}]({_art.url}){_art_source}{_art_social} {_art_sent}"
                                        )
                                    else:
                                        st.markdown(f"- {_art.title[:100]}{_art_source}{_art_social} {_art_sent}")

                                    # Show enriched data inline
                                    _enriched_parts: list[str] = []
                                    if _art.authors:
                                        _enriched_parts.append(f"✍️ {', '.join(_art.authors[:3])}")
                                    if _art.concepts:
                                        _enriched_parts.append(f"🏷️ {', '.join(_art.concepts[:4])}")
                                    if _enriched_parts:
                                        st.caption(f"  {'  ·  '.join(_enriched_parts)}")
                            else:
                                st.caption("No articles found for this event.")
            else:
                st.info("No breaking events found. Try lowering the minimum articles threshold.")

    # ── TAB: Trending Concepts (NewsAPI.ai) ─────────────────
    with tab_trending:
        st.subheader("📈 Trending Concepts")
        if not newsapi_available():
            _ok_newsapi, _newsapi_reason = newsapi_availability_status()
            st.info(_newsapi_reason or "NewsAPI.ai integration is currently unavailable.")
        else:
            _tr_col1, _tr_col2, _tr_col3 = st.columns([1, 1, 1])
            with _tr_col1:
                _tr_count = st.slider(
                    "Max concepts", 5, 50, 20, key="tr_count",
                )
            with _tr_col2:
                _tr_source = st.selectbox(
                    "Source", ["news", "social"],
                    key="tr_source",
                )
            with _tr_col3:
                _tr_type = st.selectbox(
                    "Type",
                    ["All", "person", "org", "loc", "wiki"],
                    key="tr_type",
                )

            _type_filter = _tr_type if _tr_type != "All" else None

            _trending = fetch_trending_concepts(
                count=_tr_count,
                source=_tr_source,
                concept_type=_type_filter,
            )

            if _trending:
                st.caption(
                    f"Showing {len(_trending)} trending concepts · Source: NewsAPI.ai ({_tr_source})"
                )

                # Summary bar with top 5 as chips
                _top5 = _trending[:5]
                _chips = " → ".join(
                    f"{c.type_icon} **{c.label}**" for c in _top5
                )
                st.markdown(f"🔥 Top trending: {_chips}")
                st.markdown("---")

                # Full table
                _tr_rows: list[dict[str, Any]] = []
                for _idx, _c in enumerate(_trending, 1):
                    _tr_rows.append({
                        "#": _idx,
                        "Type": _c.type_icon,
                        "Concept": _c.label,
                        "Category": _c.concept_type,
                        "Score": round(_c.trending_score, 1),
                        "Articles": _c.article_count,
                    })

                if _tr_rows:
                    _tr_df = pd.DataFrame(_tr_rows)
                    with st.expander("ℹ️ Column guide", expanded=False):
                        st.markdown(
                            "- **#** — Rank position by trending momentum\n"
                            "- **Type** — Entity type icon (👤 person, 🏢 org, 📍 location, 📄 wiki/concept)\n"
                            "- **Concept** — Entity detected by NLP in recent news articles\n"
                            "- **Category** — Classification of the entity type\n"
                            "- **Score** — Trending momentum score from NewsAPI.ai: "
                            "higher values indicate a sharper increase in media attention\n"
                            "- **Articles** — Number of news articles mentioning this concept in the lookback period. "
                            "Click the article count to expand and view the latest 20 articles."
                        )
                    st.dataframe(
                        _tr_df,
                        width="stretch",
                        height=min(40 * len(_tr_rows) + 50, 600),
                        hide_index=True,
                        column_config={
                            "#": st.column_config.NumberColumn("#", width="small"),
                            "Type": st.column_config.TextColumn("Type", width="small"),
                            "Score": st.column_config.NumberColumn("Score", width="small"),
                            "Articles": st.column_config.NumberColumn("Articles", width="small"),
                        },
                    )

                    # ── Per-concept article expanders ────────────────────
                    st.markdown("#### 📰 Articles per Concept")
                    for _idx, _c in enumerate(_trending, 1):
                        if _c.article_count == 0 and not _c.uri:
                            continue
                        with st.expander(
                            f"{_c.type_icon} **{_c.label}** — {_c.article_count} articles",
                            expanded=False,
                        ):
                            _concept_arts = fetch_concept_articles(_c.uri, count=20)
                            if _concept_arts:
                                for _art in _concept_arts:
                                    _art_date = _art.date[:16] if _art.date else ""
                                    _art_src = f" · {_art.source}" if _art.source else ""
                                    st.markdown(
                                        f"- [{_art.title}]({_art.url})"
                                        f"  <small style='color:gray'>{_art_date}{_art_src}</small>",
                                        unsafe_allow_html=True,
                                    )
                            else:
                                st.caption("No articles found for this concept.")
            else:
                st.info("No trending concepts found.")

    # ── TAB: Social Score Ranking (NewsAPI.ai + Finnhub) ──────────────
    with tab_social:
        st.subheader("🔥 Social Score — Most Shared News")

        # ── Finnhub Reddit + Twitter Sentiment ──────────────────
        if finnhub_available():
            # Extract tickers from the live feed for social lookups
            _fh_tickers: list[str] = []
            _fh_seen: set[str] = set()
            for _fi in st.session_state.get("feed", []):
                for _ft in _fi.get("tickers", []):
                    _fts = _ft.upper().strip()
                    if _fts and _fts not in _fh_seen and len(_fts) <= 5:
                        _fh_seen.add(_fts)
                        _fh_tickers.append(_fts)
            _fh_tickers = _fh_tickers[:20]

            if _fh_tickers:
                st.markdown("### 📡 Reddit & Twitter Sentiment")
                st.caption(
                    f"Live social-media mentions for {len(_fh_tickers)} trending tickers · "
                    "Source: Finnhub (free tier, real-time)"
                )
                _fh_social = fetch_social_sentiment_batch(_fh_tickers)
                if _fh_social:
                    _fh_sorted = sorted(_fh_social.values(), key=lambda s: s.total_mentions, reverse=True)
                    _fh_top = _fh_sorted[:5]
                    _fh_cols = st.columns(min(5, len(_fh_top)))
                    for _fi, _fs in enumerate(_fh_top):
                        with _fh_cols[_fi]:
                            st.markdown(f"**{_fs.symbol}** {_fs.emoji}")
                            st.metric("Mentions", f"{_fs.total_mentions:,}")
                            st.caption(
                                f"Reddit {_fs.reddit_mentions:,} · Twitter {_fs.twitter_mentions:,}\n\n"
                                f"Score: {_fs.score:+.2f}"
                            )
                    _fh_rows = []
                    for _fs in _fh_sorted:
                        _fh_rows.append({
                            "Symbol": _fs.symbol,
                            "Sentiment": _fs.emoji,
                            "Total Mentions": _fs.total_mentions,
                            "Reddit": _fs.reddit_mentions,
                            "Twitter/X": _fs.twitter_mentions,
                            "Score": f"{_fs.score:+.4f}",
                            "Label": _fs.sentiment_label.title(),
                        })
                    if _fh_rows:
                        _fh_df = pd.DataFrame(_fh_rows)
                        st.dataframe(
                            _fh_df, hide_index=True,
                            height=min(40 * len(_fh_rows) + 50, 400),
                        )
                else:
                    st.caption("No social sentiment data available for current tickers.")
                st.markdown("---")

        if not newsapi_available():
            _ok_newsapi, _newsapi_reason = newsapi_availability_status()
            st.info(_newsapi_reason or "NewsAPI.ai Social Score integration is currently unavailable.")
        else:
            _soc_col1, _soc_col2, _soc_col3 = st.columns([1, 1, 1])
            with _soc_col1:
                _soc_count = st.slider(
                    "Max articles", 10, 100, 30, key="soc_count",
                )
            with _soc_col2:
                _soc_hours = st.slider(
                    "Hours lookback", 1, 72, 24, key="soc_hours",
                )
            with _soc_col3:
                _soc_category = st.selectbox(
                    "Category",
                    ["Business", "Technology", "Politics", "Health", "Science", "Sports", "Entertainment"],
                    key="soc_cat",
                )

            _soc_cat_uri = f"news/{_soc_category}"

            _social_articles = fetch_social_ranked_articles(
                count=_soc_count,
                category=_soc_cat_uri,
                hours=_soc_hours,
            )

            if _social_articles:
                st.caption(
                    f"Showing {len(_social_articles)} most-shared articles · "
                    f"Last {_soc_hours}h · {_soc_category} · Source: NewsAPI.ai"
                )

                # Warn if all social scores are zero (plan limitation)
                _all_soc_zero = all(a.social_score == 0 for a in _social_articles)
                if _all_soc_zero:
                    st.info(
                        "ℹ️ Social sharing scores are unavailable on this API plan. "
                        "This is a NewsAPI.ai plan limitation — enterprise plans include "
                        "Facebook shares, tweet counts, etc. Articles below are still sorted "
                        "by the API's internal social relevance ranking."
                    )

                # ── Top 5 viral cards ──
                _top5_social = _social_articles[:5]
                _soc_cards = st.columns(min(5, len(_top5_social)))
                for _si, _sa in enumerate(_top5_social):
                    with _soc_cards[_si]:
                        _soc_sent = newsapi_sentiment_badge(_sa.sentiment) if _sa.sentiment is not None else ""
                        st.markdown(f"**#{_si + 1}** {_sa.sentiment_icon}")
                        st.markdown(f"📊 **{_sa.social_score:,}** shares")
                        _safe_title = _sa.title[:60]
                        if _sa.url:
                            st.markdown(f"[{_safe_title}]({_sa.url})")
                        else:
                            st.markdown(_safe_title)
                        st.caption(f"*{_sa.source}* · {_soc_sent}")

                st.markdown("---")

                # ── Full table ──
                _soc_rows: list[dict[str, Any]] = []
                for _si, _sa in enumerate(_social_articles, 1):
                    _soc_rows.append({
                        "#": _si,
                        "Sentiment": _sa.sentiment_icon,
                        "Title": _sa.title[:80],
                        "Source": _sa.source,
                        "Social Score": "N/A" if _all_soc_zero else f"{_sa.social_score:,}",
                        "NLP Sentiment": f"{_sa.sentiment:+.2f}" if _sa.sentiment is not None else "—",
                        "Published": _sa.date[:16] if _sa.date else "—",
                        "Entities": ", ".join(_sa.concepts[:4]) if _sa.concepts else "",
                        "URL": _sa.url,
                    })

                if _soc_rows:
                    _soc_df = pd.DataFrame(_soc_rows)

                    _soc_col_cfg: dict[str, Any] = {
                        "#": st.column_config.NumberColumn("#", width="small"),
                        "Social Score": st.column_config.TextColumn("Social Score", width="small"),
                        "NLP Sentiment": st.column_config.TextColumn("NLP Sent.", width="small"),
                    }
                    # Use LinkColumn for URLs
                    if any(r.get("URL", "").startswith("http") for r in _soc_rows):
                        _soc_col_cfg["URL"] = st.column_config.LinkColumn(
                            "Link",
                            display_text="🔗",
                            width="small",
                        )
                        # Also make Title clickable by linking to source
                        _soc_col_cfg["Title"] = st.column_config.TextColumn(
                            "Title", width="large",
                        )

                    st.dataframe(
                        _soc_df,
                        width="stretch",
                        height=min(40 * len(_soc_rows) + 50, 800),
                        hide_index=True,
                        column_config=_soc_col_cfg,
                    )

                # ── Sentiment distribution ──
                _soc_sents = [a.sentiment for a in _social_articles if a.sentiment is not None]
                if _soc_sents:
                    st.markdown("---")
                    _sc1, _sc2, _sc3, _sc4 = st.columns(4)
                    _pos = sum(1 for s in _soc_sents if s >= 0.2)
                    _neg = sum(1 for s in _soc_sents if s <= -0.2)
                    _neu = len(_soc_sents) - _pos - _neg
                    _avg = sum(_soc_sents) / len(_soc_sents)
                    _sc1.metric("Avg Sentiment", f"{_avg:+.2f}")
                    _sc2.metric("🟢 Positive", _pos)
                    _sc3.metric("🔴 Negative", _neg)
                    _sc4.metric("⚪ Neutral", _neu)

                # ── Article detail expanders ──
                st.markdown("---")
                st.subheader("📄 Article Details")
                for _di, _da in enumerate(_social_articles[:10]):
                    _da_sent = newsapi_sentiment_badge(_da.sentiment) if _da.sentiment is not None else ""
                    with st.expander(
                        f"{_da.sentiment_icon} #{_di + 1} — {_da.title[:80]} "
                        f"(📊 {_da.social_score:,})",
                        expanded=False,
                    ):
                        _d1, _d2, _d3 = st.columns(3)
                        with _d1:
                            st.metric("Social Score", f"{_da.social_score:,}")
                        with _d2:
                            st.metric("NLP Sentiment", f"{_da.sentiment:+.2f}" if _da.sentiment is not None else "n/a")
                        with _d3:
                            st.metric("Source", _da.source)

                        if _da.url:
                            st.markdown(f"🔗 [Open article]({_da.url})")

                        if _da.authors:
                            st.caption(f"✍️ Authors: {', '.join(_da.authors[:5])}")

                        if _da.body:
                            st.markdown(f"**Body preview:** {_da.body[:500]}{'…' if len(_da.body) > 500 else ''}")

                        if _da.concepts:
                            st.markdown(f"🏷️ **Entities:** {' · '.join(_da.concepts)}")

                        if _da.categories:
                            st.markdown(f"📂 **Categories:** {' · '.join(_da.categories)}")

                        if _da.links:
                            with st.expander("🔗 Links from article body", expanded=False):
                                for _lnk in _da.links[:10]:
                                    _lnk_str = _lnk if isinstance(_lnk, str) else str(_lnk.get("uri", _lnk))
                                    st.markdown(f"- [{_lnk_str[:60]}]({_lnk_str})")

                        if _da.videos:
                            with st.expander("🎥 Videos", expanded=False):
                                for _vid in _da.videos[:5]:
                                    _vid_str = _vid if isinstance(_vid, str) else str(_vid.get("uri", _vid))
                                    st.markdown(f"- [{_vid_str[:60]}]({_vid_str})")

                        if _da.event_uri:
                            st.caption(f"Event cluster: `{_da.event_uri}`")
                        if _da.is_duplicate:
                            st.caption("⚠️ Marked as duplicate")

            else:
                st.info("No social-ranked articles found. Try expanding the time window.")

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
                "ticker", "headline", "age", "news_score", "relevance",
                "sentiment_label", "category", "event_label", "materiality",
                "recency_bucket", "source_tier", "provider",
                "entity_count", "novelty_count", "impact", "polarity", "is_wiim",
            ]
            df = pd.DataFrame(feed)

            # Add human-readable Age column (d:hh:mm:ss)
            _dt_now = time.time()
            df["age"] = df.apply(
                lambda r: format_age_string(r.get("published_ts") or r.get("ts"), now=_dt_now),
                axis=1,
            )

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
                hide_index=True,
                column_config=_dt_col_cfg if _dt_col_cfg else None,
            )
        else:
            st.info("No data yet.")


# ── Auto-refresh trigger ───────────────────────────────────────

if st.session_state.auto_refresh and (
    st.session_state.cfg.benzinga_api_key or st.session_state.cfg.fmp_api_key
):
    # Use st.fragment with run_every for non-blocking auto-refresh (item 4).
    # This avoids the blocking time.sleep(1) call that froze the UI.
    @st.fragment(run_every=timedelta(seconds=2))
    def _auto_refresh_fragment() -> None:
        """Non-blocking auto-refresh fragment.

        Streamlit fragments with ``run_every`` only re-execute the
        fragment body — they do NOT trigger a full page rerun.  We
        must explicitly call ``st.rerun()`` when the background
        poller has new items or a status change, otherwise the sync
        code in the main script never re-executes and the sidebar
        shows stale "Polls: 0 / Last poll: —" indefinitely.
        """
        _bp_frag = st.session_state.get("bg_poller")
        if _bp_frag is not None:
            # BG mode: rerun when poller completed a poll (success or failure)
            if _bp_frag.poll_count != st.session_state.get("poll_count", 0):
                st.rerun()
            if _bp_frag.last_poll_status != st.session_state.get("last_poll_status", "—"):
                st.rerun()
        elif st.session_state.get("auto_refresh") and _should_poll(_effective_interval):
            st.rerun()

    _auto_refresh_fragment()
