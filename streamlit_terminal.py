"""Real-Time News Intelligence Dashboard AI supported.

Features:
- Multi-source news ingestion
- Enhanced NLP: 16-category event classifier, relevance scoring, entity analysis
- Full-text search + date filters on Live Feed
- Economic Calendar
- Databento US-equity pricing (Standard subscription)
- Sector Heatmap (Plotly treemap)
- Compound Alert Builder with webhook dispatch
- Live RT quote integration

Run with::

    streamlit run streamlit_terminal.py

Requires a live-news provider in ``.env`` or environment, typically
``BENZINGA_API_KEY`` or ``FMP_API_KEY``.
Optional: ``DATABENTO_API_KEY`` for real-time quote enrichment.
"""

from __future__ import annotations

import html
import json
import ipaddress
import logging
import os
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import streamlit as st

# ── Suppress harmless Streamlit fragment-scheduler warnings ────
# When a run_every fragment calls st.rerun(), the full-page rerun
# destroys the old fragment ID.  Streamlit's scheduler still fires
# on the dead ID and logs a warning/info every cycle.  This is
# expected and harmless — filter it out to keep logs clean.
# We add the filter to BOTH the logger AND all its handlers because
# Python logging applies logger-filters and handler-filters at
# different stages; covering both ensures the message never reaches
# stderr regardless of handler replacement by Streamlit internals.
class _FragmentWarningFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "does not exist anymore" not in record.getMessage()

_frag_warn_filter = _FragmentWarningFilter()
# Apply to all Streamlit loggers that may emit fragment-lifecycle warnings
for _frag_logger_name in (
    "streamlit.runtime.app_session",
    "streamlit.runtime.fragment",
    "streamlit.runtime.scriptrunner",
    "streamlit.runtime.scriptrunner.script_runner",
    "streamlit.runtime.scriptrunner_utils",
    "streamlit",
):
    _fl = logging.getLogger(_frag_logger_name)
    _fl.addFilter(_frag_warn_filter)
    for _h in _fl.handlers:
        _h.addFilter(_frag_warn_filter)
# Also apply to root logger to catch propagated messages
logging.getLogger().addFilter(_frag_warn_filter)

# ── Patch Streamlit cache-key builder to tolerate TokenError ────
# inspect.getsource() uses the tokenizer to locate function
# boundaries.  On some files / runtimes the tokenizer raises
# tokenize.TokenError (not caught by Streamlit's OSError|TypeError
# handler) which crashes the app.  Monkey-patch _make_function_key
# so it falls back to bytecode just like the existing OSError path.
try:
    import tokenize as _tokenize_mod
    from streamlit.runtime.caching import cache_utils as _cu

    _orig_make_function_key = _cu._make_function_key

    def _patched_make_function_key(*args: Any, **kwargs: Any) -> str:  # type: ignore[override]
        try:
            return str(_orig_make_function_key(*args, **kwargs))
        except _tokenize_mod.TokenError:
            # Fallback: re-run with bytecode by temporarily monkey-patching
            # inspect.getsource to raise OSError (which Streamlit already handles).
            import inspect as _insp

            _real_gs = _insp.getsource

            def _gs_raise(*a: Any, **kw: Any) -> str:
                raise OSError("tokenize fallback")

            _insp.getsource = _gs_raise  # type: ignore[assignment]
            try:
                return str(_orig_make_function_key(*args, **kwargs))
            finally:
                _insp.getsource = _real_gs  # type: ignore[assignment]

    _cu._make_function_key = _patched_make_function_key  # type: ignore[assignment]
except Exception:
    logging.getLogger(__name__).debug(
        "Streamlit cache-key monkey patch not applied; falling back to native behavior",
        exc_info=True,
    )

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
        "DATABENTO_API_KEY",
        "OPENAI_API_KEY",
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
        logging.getLogger(__name__).debug(
            "Streamlit secrets unavailable or unreadable; continuing with environment variables only",
            exc_info=True,
        )


_load_env_file(PROJECT_ROOT / ".env")
_load_streamlit_secrets()

from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter
from newsstack_fmp.ingest_fmp import FmpAdapter
from newsstack_fmp.store_sqlite import SqliteStore
from newsstack_fmp._bz_http import _WARNED_ENDPOINTS
from open_prep.playbook import classify_recency as _classify_recency
from terminal_background_poller import BackgroundPoller
from terminal_catalyst_state import (
    annotate_feed_with_ticker_catalyst_state,
    effective_catalyst_actionable,
    effective_catalyst_score,
    effective_catalyst_sentiment,
)
from terminal_attention_state import (
    annotate_feed_with_ticker_attention_state,
    effective_attention_active,
    effective_attention_dispatchable,
    effective_attention_priority,
    effective_attention_reason,
    effective_attention_score,
    effective_attention_state,
)
from terminal_export import (
    append_jsonl,
    fire_webhook,
    load_jsonl_feed,
    load_rt_quotes,
    rotate_jsonl,
    save_vd_snapshot,
)
from terminal_feed_lifecycle import FeedLifecycleManager, feed_staleness_minutes, is_market_hours
from terminal_feed_state import (
    build_derived_feed_state,
    merge_live_feed_rows,
    restore_feed_state,
    resync_feed_from_jsonl as resync_feed_from_jsonl_core,
)
from terminal_live_story_state import (
    apply_live_story_state,
    build_live_story_state_from_feed,
    live_story_key,
)
from terminal_reaction_state import (
    annotate_feed_with_ticker_reaction_state,
    effective_reaction_actionable,
    effective_reaction_priority,
    effective_reaction_score,
    effective_reaction_state,
)
from terminal_resolution_state import (
    annotate_feed_with_ticker_resolution_state,
    effective_resolution_actionable,
    effective_resolution_priority,
    effective_resolution_score,
    effective_resolution_state,
)
from terminal_posture_state import (
    annotate_feed_with_ticker_posture_state,
    effective_posture_action,
    effective_posture_actionable,
    effective_posture_priority,
    effective_posture_score,
    effective_posture_state,
)
from terminal_status_helpers import (
    api_key_status,
    cursor_diagnostic,
    degraded_mode_reasons,
    feed_staleness_diagnostic,
    format_poll_ago,
    poll_failure_count,
)
from open_prep.realtime_signals import (
    RealtimeEngine,
    ensure_rt_engine_running,
    get_rt_engine_status,
    get_rt_engine_telemetry_status,
)
from open_prep.log_redaction import apply_global_log_redaction
apply_global_log_redaction()
from terminal_notifications import NotifyConfig, notify_high_score_items
from terminal_poller import (
    ClassifiedItem,
    TerminalConfig,
    compute_today_outlook,
    compute_tomorrow_outlook,
    fetch_benzinga_delayed_quotes,
    fetch_sector_performance,
    fetch_ticker_sectors,
    legacy_cursor_from_provider_cursors,
    live_news_source_label,
    poll_and_classify_live_bus,
    seed_provider_cursors,
)


from terminal_spike_scanner import (
    SESSION_ICONS,
    build_spike_rows,
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
    _is_actionable_broad,
    aggregate_segments,
    build_heatmap_data,
    compute_feed_stats,
    dedup_feed_items,
    dedup_articles,
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
from terminal_finnhub import (
    fetch_social_sentiment_batch,
    is_available as finnhub_available,
)
from terminal_tradingview_news import (
    fetch_tv_feed_dicts,
    health_status as tv_health_status,
    is_available as tv_available,
)
from terminal_databento import (
    fetch_databento_quotes,
    fetch_databento_quote_map,
    is_available as databento_available,
    get_dataset_info as databento_dataset_info,
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

from terminal_newsapi import (
    NLPSentiment,
    newsapi_available,
    fetch_event_clusters,
    fetch_nlp_sentiment,
    fetch_trending_concepts,
    fetch_breaking_events,
)

logger = logging.getLogger(__name__)

# ── Page config ─────────────────────────────────────────────────

st.set_page_config(
    page_title="Real-Time News Intelligence Stock + Bitcoin Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Disable ALL Streamlit dimming / fading during reruns ─────────
# Streamlit dims stale elements, fades containers during re-rendering,
# and applies transition animations that wash out text.  Override
# every known mechanism so the page stays fully readable at all times.
st.markdown(
    """<style>
    /* 1. Stale-element opacity fade (main + sidebar + any nested) */
    [data-stale="true"],
    [data-stale="true"] * {
        opacity: 1 !important;
    }
    .stale-element,
    .stale-element * {
        opacity: 1 !important;
    }

    /* 2. Element container transition/animation dimming */
    .element-container {
        opacity: 1 !important;
        transition: none !important;
        animation: none !important;
    }

    /* 3. Block container (columns, expanders, tabs) fading */
    .block-container,
    [data-testid="stVerticalBlock"],
    [data-testid="stHorizontalBlock"],
    [data-testid="column"] {
        opacity: 1 !important;
        transition: none !important;
    }

    /* 4. Streamlit app view + main area */
    div[data-testid="stAppViewContainer"],
    div[data-testid="stAppViewContainer"] * {
        transition: opacity 0s !important;
    }

    /* 5. Sidebar elements */
    section[data-testid="stSidebar"],
    section[data-testid="stSidebar"] * {
        transition: opacity 0s !important;
    }

    /* 6. Tab content panels */
    div[data-baseweb="tab-panel"] {
        opacity: 1 !important;
        transition: none !important;
    }

    /* 7. Skeleton / loading placeholder shimmer */
    .stMarkdown, .stDataFrame, .stPlotlyChart, .stMetric {
        opacity: 1 !important;
    }

    /* 8. Tab labels – larger, bolder text */
    button[data-baseweb="tab"],
    button[data-baseweb="tab"] p,
    button[data-baseweb="tab"] span,
    div[data-baseweb="tab-list"] button p,
    .stTabs [data-baseweb="tab-list"] button,
    .stTabs [data-baseweb="tab-list"] button p {
        font-size: 1.35rem !important;
        font-weight: 700 !important;
    }
    button[data-baseweb="tab"] {
        padding-top: 0.65rem !important;
        padding-bottom: 0.65rem !important;
    }
    </style>""",
    unsafe_allow_html=True,
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
    """Event clusters removed — NewsAPI.ai no longer available."""
    pass


def _render_forecast_expander(symbols: list[str], *, key_prefix: str = "fc") -> None:
    """Render an analyst forecast expander for a list of symbols.

    Shows price targets, analyst ratings, EPS estimates, and recent
    upgrades/downgrades.  Uses yfinance (+ Databento pricing where available).
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
            # ETF/fund — show info (blue) instead of warning (yellow)
            if "ETF" in fc.error or "Fund" in fc.error:
                st.info(f"📊 {_fc_sym}: {fc.error}")
            else:
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

            # Price-target-summary timeline
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


def _collect_tv_news_symbols(cfg: TerminalConfig, feed: list[dict[str, Any]] | None = None) -> list[str]:
    if not bool(getattr(cfg, "tv_news_enabled", True)):
        return []
    configured = [
        str(symbol).strip().upper()
        for symbol in str(getattr(cfg, "tv_news_symbols", "") or "").split(",")
        if str(symbol).strip()
    ]
    dynamic: list[str] = []
    for row in feed or []:
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker and ticker != "MARKET":
            dynamic.append(ticker)
    merged: list[str] = []
    seen: set[str] = set()
    max_symbols = max(1, int(getattr(cfg, "tv_news_max_symbols", 25) or 25))
    for ticker in [*configured, *dynamic]:
        if ticker in seen:
            continue
        seen.add(ticker)
        merged.append(ticker)
        if len(merged) >= max_symbols:
            break
    return merged


def _has_live_news_provider(cfg: TerminalConfig, feed: list[dict[str, Any]] | None = None) -> bool:
    if str(getattr(cfg, "benzinga_api_key", "") or "").strip():
        return True
    if bool(getattr(cfg, "fmp_enabled", False)) and str(getattr(cfg, "fmp_api_key", "") or "").strip():
        return True
    return bool(_collect_tv_news_symbols(cfg, feed))


def _live_story_state_kwargs(cfg: TerminalConfig | None = None) -> dict[str, float]:
    cfg_obj = cfg or st.session_state.get("cfg") or TerminalConfig()
    return {
        "ttl_s": float(getattr(cfg_obj, "live_story_ttl_s", 7200.0) or 7200.0),
        "cooldown_s": float(getattr(cfg_obj, "live_story_cooldown_s", 900.0) or 900.0),
    }


def _story_key_for_feed_row(row: dict[str, Any]) -> str:
    explicit = str(row.get("story_key") or "").strip()
    return explicit or live_story_key(row)


def _hydrate_feed_story_state(
    feed: list[dict[str, Any]],
    *,
    cfg: TerminalConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    story_state = build_live_story_state_from_feed(
        feed,
        **_live_story_state_kwargs(cfg),
    )
    hydrated: list[dict[str, Any]] = []
    for row in feed:
        hydrated_row = dict(row)
        story_key = live_story_key(hydrated_row)
        state = story_state.get(story_key)
        if state is None:
            hydrated.append(hydrated_row)
            continue

        hydrated_row["story_key"] = state["story_key"]
        hydrated_row["story_update_kind"] = str(
            hydrated_row.get("story_update_kind") or state.get("last_action") or "restored"
        )
        hydrated_row["story_first_seen_ts"] = float(
            hydrated_row.get("story_first_seen_ts") or state.get("first_seen_ts") or 0.0
        )
        hydrated_row["story_last_seen_ts"] = float(
            hydrated_row.get("story_last_seen_ts")
            or hydrated_row.get("updated_ts")
            or hydrated_row.get("published_ts")
            or state.get("last_seen_ts")
            or 0.0
        )
        hydrated_row["story_providers_seen"] = list(
            hydrated_row.get("story_providers_seen") or state.get("providers_seen") or []
        )
        hydrated_row["story_best_source"] = str(
            hydrated_row.get("story_best_source") or state.get("best_source") or ""
        )
        hydrated_row["story_best_provider"] = str(
            hydrated_row.get("story_best_provider") or state.get("best_provider") or ""
        )
        hydrated_row["story_cooldown_until"] = float(
            hydrated_row.get("story_cooldown_until") or state.get("cooldown_until") or 0.0
        )
        hydrated_row["story_expires_at"] = float(
            hydrated_row.get("story_expires_at") or state.get("expires_at") or 0.0
        )
        hydrated.append(hydrated_row)
    return dedup_feed_items(hydrated), story_state


def _apply_live_story_batch(
    items: list[ClassifiedItem],
) -> tuple[list[ClassifiedItem], list[ClassifiedItem], list[str]]:
    result = apply_live_story_state(
        items,
        st.session_state.get("live_story_state"),
        **_live_story_state_kwargs(st.session_state.get("cfg")),
    )
    st.session_state["live_story_state"] = result.story_state
    return result.feed_items, result.alert_items, result.replace_story_keys


def _rebuild_ticker_catalyst_state() -> None:
    annotated_feed, ticker_state = annotate_feed_with_ticker_catalyst_state(st.session_state.feed)
    st.session_state.feed = dedup_feed_items(annotated_feed)
    st.session_state["ticker_catalyst_state"] = ticker_state


def _rebuild_feed_states() -> None:
    rt_quotes, db_quotes = _load_reaction_quote_context(st.session_state.feed)
    derived = build_derived_feed_state(
        st.session_state.feed,
        cfg=st.session_state.get("cfg"),
        previous_reaction_state=st.session_state.get("ticker_reaction_state") or {},
        previous_resolution_state=st.session_state.get("ticker_resolution_state") or {},
        rt_quotes=rt_quotes,
        quote_map=db_quotes,
        market_hours=is_market_hours(),
    )
    st.session_state.feed = derived.feed
    st.session_state["live_story_state"] = derived.live_story_state
    st.session_state["ticker_catalyst_state"] = derived.ticker_catalyst_state
    st.session_state["ticker_reaction_state"] = derived.ticker_reaction_state
    st.session_state["ticker_resolution_state"] = derived.ticker_resolution_state
    st.session_state["ticker_posture_state"] = derived.ticker_posture_state
    st.session_state["ticker_attention_state"] = derived.ticker_attention_state


def _load_reaction_quote_context(
    rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    current_rows = list(rows if rows is not None else st.session_state.feed)
    tickers = sorted({
        str(row.get("ticker") or "").strip().upper()
        for row in current_rows
        if str(row.get("ticker") or "").strip().upper() not in ("", "MARKET")
    })[:200]
    if not tickers:
        return {}, {}

    rt_quotes: dict[str, dict[str, Any]] = {}
    try:
        rt_quotes = load_rt_quotes(max_age_s=180.0)
        rt_quotes = {sym: row for sym, row in rt_quotes.items() if sym in tickers}
    except Exception:
        logger.debug("Reaction RT quote load failed", exc_info=True)

    db_quotes: dict[str, dict[str, Any]] = {}
    missing = [sym for sym in tickers if sym not in rt_quotes]
    if missing and databento_available():
        try:
            db_quotes = fetch_databento_quote_map(missing)
        except Exception:
            logger.debug("Reaction Databento quote load failed", exc_info=True)
    return rt_quotes, db_quotes


def _rebuild_ticker_reaction_state() -> None:
    rt_quotes, db_quotes = _load_reaction_quote_context(st.session_state.feed)
    annotated_feed, ticker_state = annotate_feed_with_ticker_reaction_state(
        st.session_state.feed,
        rt_quotes=rt_quotes,
        quote_map=db_quotes,
        previous_state=st.session_state.get("ticker_reaction_state") or {},
    )
    annotated_feed, resolution_state = annotate_feed_with_ticker_resolution_state(
        annotated_feed,
        rt_quotes=rt_quotes,
        quote_map=db_quotes,
        previous_state=st.session_state.get("ticker_resolution_state") or {},
    )
    annotated_feed, posture_state = annotate_feed_with_ticker_posture_state(annotated_feed)
    annotated_feed, attention_state = annotate_feed_with_ticker_attention_state(annotated_feed)
    st.session_state.feed = dedup_feed_items(annotated_feed)
    st.session_state["ticker_reaction_state"] = ticker_state
    st.session_state["ticker_resolution_state"] = resolution_state
    st.session_state["ticker_posture_state"] = posture_state
    st.session_state["ticker_attention_state"] = attention_state


def _rebuild_ticker_resolution_state() -> None:
    _rebuild_ticker_reaction_state()


def _annotate_dict_rows_with_catalyst_state(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated_rows, _ = annotate_feed_with_ticker_catalyst_state(
        rows,
        st.session_state.get("ticker_catalyst_state") or {},
    )
    return annotated_rows


def _annotate_dict_rows_with_reaction_state(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated_rows, _ = annotate_feed_with_ticker_reaction_state(
        rows,
        st.session_state.get("ticker_reaction_state") or {},
    )
    return annotated_rows


def _annotate_dict_rows_with_resolution_state(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated_rows, _ = annotate_feed_with_ticker_resolution_state(
        rows,
        st.session_state.get("ticker_resolution_state") or {},
    )
    return annotated_rows


def _annotate_dict_rows_with_posture_state(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated_rows, _ = annotate_feed_with_ticker_posture_state(
        rows,
        st.session_state.get("ticker_posture_state") or {},
    )
    return annotated_rows


def _annotate_dict_rows_with_attention_state(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated_rows, _ = annotate_feed_with_ticker_attention_state(
        rows,
        st.session_state.get("ticker_attention_state") or {},
    )
    return annotated_rows


def _enrich_classified_items_with_catalyst_state(
    items: list[ClassifiedItem],
) -> list[ClassifiedItem]:
    ticker_state = st.session_state.get("ticker_catalyst_state") or {}
    enriched: list[ClassifiedItem] = []
    for item in items:
        state = ticker_state.get(str(item.ticker or "").strip().upper())
        if state is None:
            enriched.append(item)
            continue
        enriched.append(
            replace(
                item,
                catalyst_score=float(state.get("catalyst_score", 0.0) or 0.0),
                catalyst_direction=str(state.get("catalyst_direction", "") or ""),
                catalyst_confidence=float(state.get("catalyst_confidence", 0.0) or 0.0),
                catalyst_freshness=str(state.get("catalyst_freshness", "") or ""),
                catalyst_story_count=int(state.get("catalyst_story_count", 0) or 0),
                catalyst_provider_count=int(state.get("catalyst_provider_count", 0) or 0),
                catalyst_best_story_key=str(state.get("catalyst_best_story_key", "") or ""),
                catalyst_best_provider=str(state.get("catalyst_best_provider", "") or ""),
                catalyst_best_source=str(state.get("catalyst_best_source", "") or ""),
                catalyst_headline=str(state.get("catalyst_headline", "") or ""),
                catalyst_actionable=bool(state.get("catalyst_actionable", False)),
                catalyst_age_minutes=(
                    float(state.get("catalyst_age_minutes", 0.0) or 0.0)
                    if state.get("catalyst_age_minutes") is not None
                    else None
                ),
                catalyst_last_update_ts=(
                    float(state.get("catalyst_last_update_ts", 0.0) or 0.0)
                    if state.get("catalyst_last_update_ts") is not None
                    else None
                ),
                catalyst_expires_at=(
                    float(state.get("catalyst_expires_at", 0.0) or 0.0)
                    if state.get("catalyst_expires_at") is not None
                    else None
                ),
                catalyst_conflict=bool(state.get("catalyst_conflict", False)),
            )
        )
    return enriched


def _enrich_classified_items_with_reaction_state(
    items: list[ClassifiedItem],
) -> list[ClassifiedItem]:
    ticker_state = st.session_state.get("ticker_reaction_state") or {}
    enriched: list[ClassifiedItem] = []
    for item in items:
        state = ticker_state.get(str(item.ticker or "").strip().upper())
        if state is None:
            enriched.append(item)
            continue
        enriched.append(
            replace(
                item,
                reaction_state=str(state.get("reaction_state", "") or ""),
                reaction_alignment=str(state.get("reaction_alignment", "") or ""),
                reaction_score=(
                    float(state.get("reaction_score", 0.0) or 0.0)
                    if state.get("reaction_score") is not None
                    else None
                ),
                reaction_confidence=(
                    float(state.get("reaction_confidence", 0.0) or 0.0)
                    if state.get("reaction_confidence") is not None
                    else None
                ),
                reaction_price=(
                    float(state.get("reaction_price", 0.0) or 0.0)
                    if state.get("reaction_price") is not None
                    else None
                ),
                reaction_change_pct=(
                    float(state.get("reaction_change_pct", 0.0) or 0.0)
                    if state.get("reaction_change_pct") is not None
                    else None
                ),
                reaction_impulse_pct=(
                    float(state.get("reaction_impulse_pct", 0.0) or 0.0)
                    if state.get("reaction_impulse_pct") is not None
                    else None
                ),
                reaction_volume_ratio=(
                    float(state.get("reaction_volume_ratio", 0.0) or 0.0)
                    if state.get("reaction_volume_ratio") is not None
                    else None
                ),
                reaction_source=str(state.get("reaction_source", "") or ""),
                reaction_anchor_story_key=str(state.get("reaction_anchor_story_key", "") or ""),
                reaction_anchor_price=(
                    float(state.get("reaction_anchor_price", 0.0) or 0.0)
                    if state.get("reaction_anchor_price") is not None
                    else None
                ),
                reaction_anchor_ts=(
                    float(state.get("reaction_anchor_ts", 0.0) or 0.0)
                    if state.get("reaction_anchor_ts") is not None
                    else None
                ),
                reaction_peak_impulse_pct=(
                    float(state.get("reaction_peak_impulse_pct", 0.0) or 0.0)
                    if state.get("reaction_peak_impulse_pct") is not None
                    else None
                ),
                reaction_last_update_ts=(
                    float(state.get("reaction_last_update_ts", 0.0) or 0.0)
                    if state.get("reaction_last_update_ts") is not None
                    else None
                ),
                reaction_confirmed=(
                    bool(state.get("reaction_confirmed"))
                    if state.get("reaction_confirmed") is not None
                    else None
                ),
                reaction_actionable=(
                    bool(state.get("reaction_actionable"))
                    if state.get("reaction_actionable") is not None
                    else None
                ),
                reaction_reason=str(state.get("reaction_reason", "") or ""),
            )
        )
    return enriched


def _enrich_classified_items_with_resolution_state(
    items: list[ClassifiedItem],
) -> list[ClassifiedItem]:
    ticker_state = st.session_state.get("ticker_resolution_state") or {}
    enriched: list[ClassifiedItem] = []
    for item in items:
        state = ticker_state.get(str(item.ticker or "").strip().upper())
        if state is None:
            enriched.append(item)
            continue
        enriched.append(
            replace(
                item,
                resolution_state=str(state.get("resolution_state", "") or ""),
                resolution_score=(
                    float(state.get("resolution_score", 0.0) or 0.0)
                    if state.get("resolution_score") is not None
                    else None
                ),
                resolution_confidence=(
                    float(state.get("resolution_confidence", 0.0) or 0.0)
                    if state.get("resolution_confidence") is not None
                    else None
                ),
                resolution_window_minutes=(
                    float(state.get("resolution_window_minutes", 0.0) or 0.0)
                    if state.get("resolution_window_minutes") is not None
                    else None
                ),
                resolution_elapsed_minutes=(
                    float(state.get("resolution_elapsed_minutes", 0.0) or 0.0)
                    if state.get("resolution_elapsed_minutes") is not None
                    else None
                ),
                resolution_price=(
                    float(state.get("resolution_price", 0.0) or 0.0)
                    if state.get("resolution_price") is not None
                    else None
                ),
                resolution_change_pct=(
                    float(state.get("resolution_change_pct", 0.0) or 0.0)
                    if state.get("resolution_change_pct") is not None
                    else None
                ),
                resolution_impulse_pct=(
                    float(state.get("resolution_impulse_pct", 0.0) or 0.0)
                    if state.get("resolution_impulse_pct") is not None
                    else None
                ),
                resolution_peak_impulse_pct=(
                    float(state.get("resolution_peak_impulse_pct", 0.0) or 0.0)
                    if state.get("resolution_peak_impulse_pct") is not None
                    else None
                ),
                resolution_source=str(state.get("resolution_source", "") or ""),
                resolution_anchor_story_key=str(state.get("resolution_anchor_story_key", "") or ""),
                resolution_anchor_price=(
                    float(state.get("resolution_anchor_price", 0.0) or 0.0)
                    if state.get("resolution_anchor_price") is not None
                    else None
                ),
                resolution_anchor_ts=(
                    float(state.get("resolution_anchor_ts", 0.0) or 0.0)
                    if state.get("resolution_anchor_ts") is not None
                    else None
                ),
                resolution_last_update_ts=(
                    float(state.get("resolution_last_update_ts", 0.0) or 0.0)
                    if state.get("resolution_last_update_ts") is not None
                    else None
                ),
                resolution_resolved=(
                    bool(state.get("resolution_resolved"))
                    if state.get("resolution_resolved") is not None
                    else None
                ),
                resolution_actionable=(
                    bool(state.get("resolution_actionable"))
                    if state.get("resolution_actionable") is not None
                    else None
                ),
                resolution_reason=str(state.get("resolution_reason", "") or ""),
            )
        )
    return enriched


def _enrich_classified_items_with_posture_state(
    items: list[ClassifiedItem],
) -> list[ClassifiedItem]:
    ticker_state = st.session_state.get("ticker_posture_state") or {}
    enriched: list[ClassifiedItem] = []
    for item in items:
        state = ticker_state.get(str(item.ticker or "").strip().upper())
        if state is None:
            enriched.append(item)
            continue
        enriched.append(
            replace(
                item,
                posture_state=str(state.get("posture_state", "") or ""),
                posture_action=str(state.get("posture_action", "") or ""),
                posture_score=(
                    float(state.get("posture_score", 0.0) or 0.0)
                    if state.get("posture_score") is not None
                    else None
                ),
                posture_confidence=(
                    float(state.get("posture_confidence", 0.0) or 0.0)
                    if state.get("posture_confidence") is not None
                    else None
                ),
                posture_actionable=(
                    bool(state.get("posture_actionable"))
                    if state.get("posture_actionable") is not None
                    else None
                ),
                posture_reason=str(state.get("posture_reason", "") or ""),
                posture_last_update_ts=(
                    float(state.get("posture_last_update_ts", 0.0) or 0.0)
                    if state.get("posture_last_update_ts") is not None
                    else None
                ),
            )
        )
    return enriched


def _enrich_classified_items_with_attention_state(
    items: list[ClassifiedItem],
) -> list[ClassifiedItem]:
    ticker_state = st.session_state.get("ticker_attention_state") or {}
    enriched: list[ClassifiedItem] = []
    for item in items:
        state = ticker_state.get(str(item.ticker or "").strip().upper())
        if state is None:
            enriched.append(item)
            continue
        enriched.append(
            replace(
                item,
                attention_state=str(state.get("attention_state", "") or ""),
                attention_score=(
                    float(state.get("attention_score", 0.0) or 0.0)
                    if state.get("attention_score") is not None
                    else None
                ),
                attention_confidence=(
                    float(state.get("attention_confidence", 0.0) or 0.0)
                    if state.get("attention_confidence") is not None
                    else None
                ),
                attention_active=(
                    bool(state.get("attention_active"))
                    if state.get("attention_active") is not None
                    else None
                ),
                attention_featured=(
                    bool(state.get("attention_featured"))
                    if state.get("attention_featured") is not None
                    else None
                ),
                attention_dispatchable=(
                    bool(state.get("attention_dispatchable"))
                    if state.get("attention_dispatchable") is not None
                    else None
                ),
                attention_reason=str(state.get("attention_reason", "") or ""),
                attention_last_update_ts=(
                    float(state.get("attention_last_update_ts", 0.0) or 0.0)
                    if state.get("attention_last_update_ts") is not None
                    else None
                ),
            )
        )
    return enriched


def _enrich_classified_items_with_feed_state(
    items: list[ClassifiedItem],
) -> list[ClassifiedItem]:
    items = _enrich_classified_items_with_catalyst_state(items)
    items = _enrich_classified_items_with_reaction_state(items)
    items = _enrich_classified_items_with_resolution_state(items)
    items = _enrich_classified_items_with_posture_state(items)
    return _enrich_classified_items_with_attention_state(items)


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

    rt_quotes, db_quotes = _load_reaction_quote_context(st.session_state.feed)
    result = resync_feed_from_jsonl_core(
        st.session_state.feed,
        cfg.jsonl_path,
        cfg=cfg,
        previous_reaction_state=st.session_state.get("ticker_reaction_state") or {},
        previous_resolution_state=st.session_state.get("ticker_resolution_state") or {},
        rt_quotes=rt_quotes,
        quote_map=db_quotes,
        market_hours=is_market_hours(),
    )
    if not result.feed and not load_jsonl_feed(cfg.jsonl_path):
        st.session_state.last_resync_ts = time.time()
        return

    st.session_state.feed = result.feed
    st.session_state["live_story_state"] = result.live_story_state
    st.session_state["ticker_catalyst_state"] = result.ticker_catalyst_state
    st.session_state["ticker_reaction_state"] = result.ticker_reaction_state
    st.session_state["ticker_resolution_state"] = result.ticker_resolution_state
    st.session_state["ticker_posture_state"] = result.ticker_posture_state
    st.session_state["ticker_attention_state"] = result.ticker_attention_state
    if result.new_count > 0:
        logger.info("JSONL resync: merged %d items into session feed", result.new_count)

    # Only advance the session cursor when the background poller is
    # NOT running.  The BG poller maintains its own cursor; overwriting
    # session_state.cursor here would rewind it on the next rerun
    # (the main loop syncs session cursor back into the poller),
    # causing duplicate ingestion.
    if not st.session_state.get("use_bg_poller") or st.session_state.get("bg_poller") is None:
        if result.legacy_cursor:
            st.session_state["cursor"] = result.legacy_cursor
            st.session_state["provider_cursors"] = dict(result.provider_cursors)

    st.session_state.last_resync_ts = time.time()


if "cfg" not in st.session_state:
    st.session_state.cfg = TerminalConfig()
if "cursor" not in st.session_state:
    st.session_state.cursor = None
if "provider_cursors" not in st.session_state:
    st.session_state.provider_cursors = {}
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
        # Don't close — SqliteStore is a singleton; closing here would
        # break the shared connection used by the poller later.
        logger.info("Pruned SQLite dedup tables (keep_seconds=%.0f) on startup", _keep)
    _rt_quotes, _db_quotes = _load_reaction_quote_context(_restored)
    _restore_result = restore_feed_state(
        TerminalConfig().jsonl_path,
        cfg=TerminalConfig(),
        rt_quotes=_rt_quotes,
        quote_map=_db_quotes,
        market_hours=is_market_hours(),
    )
    st.session_state.feed = _restore_result.feed
    st.session_state.live_story_state = _restore_result.live_story_state
    st.session_state.ticker_catalyst_state = _restore_result.ticker_catalyst_state
    st.session_state.ticker_reaction_state = _restore_result.ticker_reaction_state
    st.session_state.ticker_resolution_state = _restore_result.ticker_resolution_state
    st.session_state.ticker_posture_state = _restore_result.ticker_posture_state
    st.session_state.ticker_attention_state = _restore_result.ticker_attention_state
    if _restore_result.legacy_cursor:
        st.session_state["cursor"] = _restore_result.legacy_cursor
        st.session_state["provider_cursors"] = dict(_restore_result.provider_cursors)
if "live_story_state" not in st.session_state:
    _, _story_state = _hydrate_feed_story_state(st.session_state.feed)
    st.session_state.live_story_state = _story_state
if "ticker_catalyst_state" not in st.session_state:
    _rebuild_ticker_catalyst_state()
if "ticker_reaction_state" not in st.session_state:
    _rebuild_ticker_reaction_state()
if "ticker_resolution_state" not in st.session_state:
    _rebuild_ticker_resolution_state()
if "ticker_posture_state" not in st.session_state:
    _rebuild_ticker_resolution_state()
if "ticker_attention_state" not in st.session_state:
    _rebuild_ticker_resolution_state()
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
    "provider_cursors": {},
    "auto_refresh": True,
    "last_poll_status": "—",
    "last_poll_error": "",
    "last_poll_duration_s": 0.0,
    "alert_log": [],
    "bg_poller": None,
    "bg_poller_last_failure": None,
    "bg_poller_restart_count": 0,
    "bg_poller_total_dropped": 0,
    "live_story_state": {},
    "ticker_catalyst_state": {},
    "ticker_reaction_state": {},
    "ticker_resolution_state": {},
    "ticker_posture_state": {},
    "ticker_attention_state": {},
    "notify_log": [],
    "intel_toggle": os.getenv("TERMINAL_OPTIONAL_INTEL", "1") != "0",
    "rt_engine_last_check_ts": 0.0,
    "tv_health_prev_status": "healthy",
    "tv_health_log": [],
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

# ── Auto-start RT signal engine (background process) ───────────
# Re-check periodically so transient startup failures and dead processes
# don't get stuck behind a one-shot session flag.
_is_cloud_rt = str(PROJECT_ROOT).startswith("/mount/src") or os.environ.get("STREAMLIT_SHARING_MODE")
if not _is_cloud_rt:
    _rt_now = time.time()
    _rt_last_check = float(st.session_state.get("rt_engine_last_check_ts", 0.0) or 0.0)
    if "rt_engine_started" not in st.session_state or (_rt_now - _rt_last_check) >= 60.0:
        _rt_started = ensure_rt_engine_running(project_root=PROJECT_ROOT)
        st.session_state.rt_engine_started = _rt_started
        st.session_state.rt_engine_last_check_ts = _rt_now
        if _rt_started:
            logger.info("RT signal engine ensure() completed from streamlit_terminal")


def _get_adapter() -> BenzingaRestAdapter | None:
    """Lazy-init the REST adapter."""
    cfg: TerminalConfig = st.session_state.cfg
    if not cfg.benzinga_api_key:
        return None
    if st.session_state.adapter is None:
        st.session_state.adapter = BenzingaRestAdapter(cfg.benzinga_api_key)
    return st.session_state.adapter  # type: ignore[no-any-return]


def _get_fmp_adapter() -> FmpAdapter | None:
    """Lazy-init the FMP live-news adapter."""
    cfg: TerminalConfig = st.session_state.cfg
    if not (cfg.fmp_enabled and cfg.fmp_api_key):
        return None
    if st.session_state.fmp_adapter is None:
        st.session_state.fmp_adapter = FmpAdapter(cfg.fmp_api_key)
    return st.session_state.fmp_adapter  # type: ignore[no-any-return]


def _get_store() -> SqliteStore:
    """Lazy-init the SQLite store."""
    if st.session_state.store is None:
        cfg: TerminalConfig = st.session_state.cfg
        os.makedirs(os.path.dirname(cfg.sqlite_path) or ".", exist_ok=True)
        st.session_state.store = SqliteStore(cfg.sqlite_path)
    return st.session_state.store  # type: ignore[no-any-return]


def _snapshot_bg_poller_state(poller: BackgroundPoller, *, reason: str, restarting: bool = False) -> None:
    dropped_count = int(getattr(poller, "total_items_dropped", 0) or 0)
    snapshot = {
        "reason": reason,
        "observed_at": time.time(),
        "poll_count": int(getattr(poller, "poll_count", 0) or 0),
        "poll_attempts": int(getattr(poller, "poll_attempts", 0) or 0),
        "last_poll_status": str(getattr(poller, "last_poll_status", "—") or "—"),
        "last_poll_error": str(getattr(poller, "last_poll_error", "") or ""),
        "last_poll_ts": float(getattr(poller, "last_poll_ts", 0.0) or 0.0),
        "total_items_dropped": dropped_count,
    }
    st.session_state["bg_poller_total_dropped"] = max(
        int(st.session_state.get("bg_poller_total_dropped", 0) or 0),
        dropped_count,
    )
    had_problem = bool(snapshot["last_poll_error"]) or snapshot["last_poll_status"] == "ERROR" or reason == "unexpected_exit"
    if had_problem:
        st.session_state["bg_poller_last_failure"] = snapshot
    if restarting:
        st.session_state["bg_poller_restart_count"] = int(st.session_state.get("bg_poller_restart_count", 0) or 0) + 1


# ── Sidebar ─────────────────────────────────────────────────────

with st.sidebar:
    st.title("📡 Terminal Config")

    cfg: TerminalConfig = st.session_state.cfg

    # API key status — re-read env vars directly so keys added after
    # session start are detected without requiring a full server restart.
    _bz_key = os.environ.get("BENZINGA_API_KEY", "") or cfg.benzinga_api_key
    _fmp_key = os.environ.get("FMP_API_KEY", "") or cfg.fmp_api_key
    _oai_key = os.environ.get("OPENAI_API_KEY", "") or cfg.openai_api_key
    _key_statuses = api_key_status(
        benzinga_key=_bz_key,
        databento_available=databento_available(),
        openai_key=_oai_key,
    )
    for _ks in _key_statuses:
        if _ks["configured"]:
            st.success(f"{_ks['name']}: {_ks['icon']} {_ks['message']}")
        elif _ks["icon"] == "❌":
            st.error(_ks["message"])
            if _ks["name"] == "News API":
                st.info("Set `BENZINGA_API_KEY` for Benzinga live news or `FMP_API_KEY` for FMP live polling.")
        else:
            st.caption(f"{_ks['name']}: {_ks['message']}")
    # Patch live config so downstream code sees keys added after session start
    _cfg_changed = False
    if _bz_key and not cfg.benzinga_api_key:
        cfg = replace(cfg, benzinga_api_key=_bz_key)
        _cfg_changed = True
    if _fmp_key and not cfg.fmp_api_key:
        cfg = replace(cfg, fmp_api_key=_fmp_key)
        _cfg_changed = True
    if _oai_key and not cfg.openai_api_key:
        cfg = replace(cfg, openai_api_key=_oai_key)
        _cfg_changed = True
    if _cfg_changed:
        st.session_state.cfg = cfg

    # Poll interval
    interval = st.slider(
        "Poll interval (seconds)",
        min_value=3,
        max_value=60,
        value=int(cfg.poll_interval_s),
        step=1,
    )

    # Auto-refresh toggle
    st.toggle("Auto-refresh", key="auto_refresh")

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
        st.session_state.provider_cursors = {}
        st.session_state.consecutive_empty_polls = 0
        _bp_reset_cursor = st.session_state.get("bg_poller")
        if _bp_reset_cursor is not None:
            _bp_reset_cursor.consecutive_empty_polls = 0
            _bp_reset_cursor.wake_and_reset_cursor()
        st.toast("Cursor reset — next poll will fetch latest articles", icon="🔃")
        st.rerun()

    st.divider()

    # Stats
    st.metric("Polls", st.session_state.poll_count)
    _poll_attempts = st.session_state.get("poll_attempts", 0)
    _poll_fails = poll_failure_count(_poll_attempts, st.session_state.poll_count)
    if _poll_fails is not None:
        if st.session_state.last_poll_status == "—":
            st.caption(f"Attempts: {_poll_attempts} (in progress…)")
        else:
            st.caption(f"Attempts: {_poll_attempts} (failures: {_poll_fails})")
    st.metric("Items in feed", len(st.session_state.feed))
    st.metric("Total ingested", st.session_state.total_items_ingested)
    _poll_ago = format_poll_ago(
        st.session_state.last_poll_ts,
        last_duration_s=st.session_state.get("last_poll_duration_s", 0.0),
    )
    if _poll_ago:
        st.caption(_poll_ago)

    # Feed staleness + cursor diagnostics
    _diag_feed = st.session_state.feed
    _diag_staleness = feed_staleness_minutes(_diag_feed)
    _stale_diag = feed_staleness_diagnostic(_diag_staleness, is_market_hours())
    if _stale_diag["label"]:
        if _stale_diag["severity"] == "warn":
            st.warning(_stale_diag["label"])
        else:
            st.caption(_stale_diag["label"])
    st.caption(cursor_diagnostic(st.session_state.cursor))
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
        sources.append("BZ")
    if cfg.fmp_enabled and cfg.fmp_api_key:
        sources.append("FMP")
    if databento_available():
        sources.append("Databento")
    if _collect_tv_news_symbols(cfg, st.session_state.feed):
        sources.append("TV")
    st.caption(f"Sources: {', '.join(sources) if sources else 'none'}")

    # TradingView health alert (with state-transition detection)
    _tv_hs = tv_health_status()
    _tv_prev = st.session_state.get("tv_health_prev_status", "healthy")
    _tv_cur = _tv_hs["status"]

    # Detect transitions and fire proactive alerts
    if _tv_cur != _tv_prev:
        _tv_log_entry = {
            "ts": time.time(),
            "prev": _tv_prev,
            "status": _tv_cur,
            "failures": _tv_hs["consecutive_failures"],
            "error": _tv_hs.get("last_error", ""),
            "uptime_pct": _tv_hs.get("uptime_pct", 0),
        }
        st.session_state.tv_health_log.insert(0, _tv_log_entry)
        if len(st.session_state.tv_health_log) > 50:
            st.session_state.tv_health_log = st.session_state.tv_health_log[:50]

        if _tv_cur == "down":
            st.toast(
                f"TradingView API DOWN — {_tv_hs['consecutive_failures']} consecutive failures. "
                f"Headlines will be unavailable until recovery.",
                icon="🚨",
            )
            # Also log to the main alert_log so it appears in the Alerts tab
            st.session_state.alert_log.insert(0, {
                "ts": time.time(),
                "ticker": "SYSTEM",
                "headline": f"TradingView API DOWN ({_tv_hs['consecutive_failures']} failures): {_tv_hs.get('last_error', 'unknown')}",
                "rule": "tv_health",
                "score": 0.0,
                "item_id": f"tv_down_{int(time.time())}",
            })
        elif _tv_cur == "degraded" and _tv_prev == "healthy":
            st.toast(
                f"TradingView API degraded — {_tv_hs['consecutive_failures']} failure(s)",
                icon="⚡",
            )
        elif _tv_cur == "healthy" and _tv_prev in ("down", "degraded"):
            st.toast("TradingView API recovered — headlines flowing again", icon="✅")
            st.session_state.alert_log.insert(0, {
                "ts": time.time(),
                "ticker": "SYSTEM",
                "headline": f"TradingView API RECOVERED (uptime {_tv_hs.get('uptime_pct', 0):.0f}%)",
                "rule": "tv_health",
                "score": 0.0,
                "item_id": f"tv_up_{int(time.time())}",
            })
        st.session_state.tv_health_prev_status = _tv_cur

    # Static sidebar indicator (always visible)
    if _tv_cur == "down":
        st.warning(f"⚠️ TradingView headlines unavailable ({_tv_hs['consecutive_failures']} failures). Last error: {_tv_hs['last_error']}")
    elif _tv_cur == "degraded":
        st.caption(f"⚡ TV degraded ({_tv_hs['consecutive_failures']} failures)")

    # Reset dedup DB (clears mark_seen so next poll re-ingests)
    if st.button("🗑️ Reset dedup DB", width='stretch'):
        # Stop background poller AND WAIT for it to finish so it
        # doesn't use the store/adapters after we close them.
        _bp_reset = st.session_state.get("bg_poller")
        if _bp_reset is not None:
            try:
                _bp_reset.stop_and_join(timeout=5.0)
            except Exception:
                logger.debug("bg_poller.stop_and_join() failed during reset", exc_info=True)
        # Close existing SQLite connection before deleting files
        if st.session_state.store is not None:
            try:
                st.session_state.store.close(force=True)
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
        st.session_state.provider_cursors = {}
        st.session_state.live_story_state = {}
        st.session_state.ticker_catalyst_state = {}
        st.session_state.ticker_reaction_state = {}
        st.session_state.ticker_resolution_state = {}
        st.session_state.ticker_posture_state = {}
        st.session_state.ticker_attention_state = {}
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
                # Cap alert rules at 100 to prevent unbounded memory growth
                if len(st.session_state.alert_rules) >= 100:
                    st.warning("Maximum of 100 alert rules reached. Please delete some before adding more.")
                else:
                    st.session_state.alert_rules.append(new_rule)
                    # Persist
                    try:
                        os.makedirs("artifacts", exist_ok=True)
                        Path("artifacts/alert_rules.json").write_text(
                            json.dumps(st.session_state.alert_rules, indent=2),
                        )
                    except OSError:
                        logger.warning("Failed to persist alert rules to disk", exc_info=True)
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
                try:
                    Path("artifacts/alert_rules.json").write_text(
                        json.dumps(st.session_state.alert_rules, indent=2),
                    )
                except OSError:
                    logger.warning("Failed to persist alert rules to disk", exc_info=True)
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

    st.toggle(
        "Background Polling",
        key="use_bg_poller",
        help="Run API polling in a background thread to prevent UI stalls.",
    )

    st.toggle(
        "News→Chart Auto-Webhook",
        key="news_chart_auto_webhook",
        help="Auto-fire webhook for score ≥ 0.85 actionable items (routes to TradersPost).",
    )

    _INTEL_ENABLED = st.toggle(
        "Optional intelligence modules — Turn off for fast mode, disables AI Insights",
        key="intel_toggle",
        help=(
            "Disabled = lowest latency (skips heavy NLP/trending/AI calls). "
            "Enable only when you want deeper analysis."
        ),
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
        _drop_count = max(
            int(st.session_state.get("bg_poller_total_dropped", 0) or 0),
            int(getattr(st.session_state.bg_poller, "total_items_dropped", 0) or 0),
        )
        if _drop_count:
            st.warning(f"BG Poller backlog dropped {_drop_count} queued item(s).")
    _last_bg_failure = st.session_state.get("bg_poller_last_failure")
    if isinstance(_last_bg_failure, dict):
        _failure_text = str(_last_bg_failure.get("last_poll_error") or _last_bg_failure.get("last_poll_status") or _last_bg_failure.get("reason") or "unknown")
        _restart_count = int(st.session_state.get("bg_poller_restart_count", 0) or 0)
        st.caption(f"Last BG restart cause: {_failure_text} | restarts: {_restart_count}")

    st.divider()

    # RT engine status — skip on Streamlit Cloud where the local engine can't run
    _is_cloud = str(PROJECT_ROOT).startswith("/mount/src") or os.environ.get("STREAMLIT_SHARING_MODE")
    if _is_cloud:
        st.caption("RT Engine: ☁️ Cloud mode (local-only feature)")
    else:
        _rt_status = get_rt_engine_status()
        _telemetry_status = get_rt_engine_telemetry_status()
        _rt_path = str(PROJECT_ROOT / "artifacts" / "open_prep" / "latest" / "latest_vd_signals.jsonl")
        _rt_quotes = load_rt_quotes(_rt_path)
        if _rt_status.get("running") and _rt_quotes:
            st.success(f"RT Engine: {len(_rt_quotes)} symbols live")
        elif _rt_status.get("running"):
            st.warning("RT Engine: process running, but no fresh signal snapshot is visible yet")
        else:
            _rt_error = str(_rt_status.get("error") or "not running")
            st.error(f"RT Engine: {_rt_error}")
        _telemetry_url = str(_telemetry_status.get("url") or "")
        _telemetry_error = str(_telemetry_status.get("error") or "")
        if _telemetry_url and _telemetry_error:
            st.caption(f"Telemetry: {_telemetry_url} ({_telemetry_error})")
        elif _telemetry_url:
            st.caption(f"Telemetry: {_telemetry_url}")
        elif _telemetry_error:
            st.warning(f"Telemetry: {_telemetry_error}")
        else:
            if os.path.isfile(_rt_path):
                _rt_age = time.time() - os.path.getmtime(_rt_path)
                if _rt_age < 300:
                    st.info(f"RT Engine: idle ({_rt_age:.0f}s since last update)")
                else:
                    _rt_mins = _rt_age / 60
                    st.caption(f"RT Engine: offline — last update {_rt_mins:.0f}min ago")
            else:
                st.info("RT Engine: not running (terminal poller is independent)")


# ── Sentiment helpers (imported from terminal_ui_helpers) ──────
# SENTIMENT_COLORS, MATERIALITY_COLORS, RECENCY_COLORS are
# imported at the top of the file from terminal_ui_helpers.
# Legacy aliases kept for backward compat inside this module.
_SENTIMENT_COLORS = SENTIMENT_COLORS
_MATERIALITY_COLORS = MATERIALITY_COLORS
_RECENCY_COLORS = RECENCY_COLORS


# ── Cached data wrappers (avoid re-fetching every Streamlit rerun) ──
# NOTE: Each wrapper catches exceptions so Streamlit never caches a raised
# exception for the full TTL — callers always get a safe fallback.

@st.cache_data(ttl=180, show_spinner=False)
def _cached_sector_perf(api_key: str) -> list[dict[str, Any]]:
    """Cache sector performance for 3 minutes."""
    try:
        return fetch_sector_performance(api_key)
    except Exception:
        logger.warning("_cached_sector_perf failed", exc_info=True)
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _cached_ticker_sectors(api_key: str, tickers_csv: str) -> dict[str, str]:
    """Cache ticker→GICS sector mapping for 5 minutes."""
    try:
        tickers = [t.strip() for t in tickers_csv.split(",") if t.strip()]
        return fetch_ticker_sectors(api_key, tickers)
    except Exception:
        logger.warning("_cached_ticker_sectors failed", exc_info=True)
        return {}





@st.cache_data(ttl=180, show_spinner=False)
def _cached_today_outlook(
    bz_key: str, fmp_key: str, _cache_buster: str = "",
) -> dict[str, Any]:
    """Cache today outlook for 3 minutes."""
    try:
        return compute_today_outlook(bz_key, fmp_key)
    except Exception:
        logger.warning("_cached_today_outlook failed", exc_info=True)
        return {}


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
        logger.warning("_cached_tomorrow_outlook failed", exc_info=True)
        return {}


def _safe_float_mov(val: Any, default: float = 0.0) -> float:
    """Safe float conversion for mover data."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _intel_enabled() -> bool:
    """Whether optional intelligence modules are enabled for this session.

    Reads the captured return value from the sidebar toggle widget.
    The variable ``_INTEL_ENABLED`` is set in the sidebar block above
    before any tab content renders, so it always reflects the current
    toggle position.
    """
    return bool(globals().get("_INTEL_ENABLED", False))


_ATTENTION_ICONS = {
    "ALERT": "🚨",
    "FOCUS": "🎯",
    "MONITOR": "👀",
    "BACKGROUND": "⚪",
    "SUPPRESS": "⛔",
}




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
        if not effective_attention_active(ci):
            continue

        effective_score = effective_attention_score(ci)
        effective_sentiment = effective_catalyst_sentiment(ci)
        attention_state = effective_attention_state(ci)
        attention_dispatchable = effective_attention_dispatchable(ci)
        for rule_idx, rule in enumerate(rules):
            tk_match = rule["ticker"] in ("*", ci.ticker)
            if not tk_match:
                continue

            # Dedup: skip if this item already fired for this rule
            pair_key = (str(ci.story_key or ci.item_id), rule_idx)
            if pair_key in seen_pairs:
                continue

            cond = rule["condition"]
            fired = False

            if match_alert_rule(
                rule,
                ticker=ci.ticker,
                news_score=effective_score,
                sentiment_label=effective_sentiment,
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
                    "score": effective_score,
                    "story_score": ci.news_score,
                    "sentiment": effective_sentiment,
                    "item_id": ci.item_id,
                    "story_key": ci.story_key,
                    "story_update_kind": ci.story_update_kind,
                    "attention_state": attention_state,
                    "attention_score": effective_score,
                    "attention_dispatchable": attention_dispatchable,
                    "attention_reason": ci.attention_reason or effective_attention_reason(ci),
                    "posture_state": ci.posture_state,
                    "posture_action": effective_posture_action(ci),
                    "reaction_state": ci.reaction_state,
                    "resolution_state": ci.resolution_state,
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
    items: list[ClassifiedItem],
    cfg: TerminalConfig,
    *,
    src_label: str = "BZ",
    replace_story_keys: list[str] | None = None,
    outbound_items: list[ClassifiedItem] | None = None,
) -> None:
    """Shared post-poll processing for foreground and background pollers.

    Handles: JSONL export (batched — item 13), global webhook,
    push notifications, news→chart webhook, feed trim/prune,
    VD snapshot.  Uses a single httpx.Client for all webhooks (item 14).
    """
    if not items and not outbound_items:
        return

    replace_story_key_set = {
        str(story_key).strip()
        for story_key in (replace_story_keys or [])
        if str(story_key).strip()
    }
    outbound_items = list(outbound_items if outbound_items is not None else items)

    raw_new_dicts = dedup_feed_items([ci.to_dict() for ci in items])
    new_dicts: list[dict[str, Any]] = []
    if raw_new_dicts or replace_story_key_set:
        rt_quotes, db_quotes = _load_reaction_quote_context(raw_new_dicts + st.session_state.feed)
        merge_result = merge_live_feed_rows(
            st.session_state.feed,
            raw_new_dicts,
            cfg=cfg,
            replace_story_keys=sorted(replace_story_key_set),
            previous_reaction_state=st.session_state.get("ticker_reaction_state") or {},
            previous_resolution_state=st.session_state.get("ticker_resolution_state") or {},
            rt_quotes=rt_quotes,
            quote_map=db_quotes,
            market_hours=is_market_hours(),
        )
        st.session_state.feed = merge_result.feed
        st.session_state["live_story_state"] = merge_result.live_story_state
        st.session_state["ticker_catalyst_state"] = merge_result.ticker_catalyst_state
        st.session_state["ticker_reaction_state"] = merge_result.ticker_reaction_state
        st.session_state["ticker_resolution_state"] = merge_result.ticker_resolution_state
        st.session_state["ticker_posture_state"] = merge_result.ticker_posture_state
        st.session_state["ticker_attention_state"] = merge_result.ticker_attention_state
        new_dicts = merge_result.annotated_new_rows

    outbound_items = _enrich_classified_items_with_feed_state(outbound_items)
    outbound_dicts = dedup_feed_items([ci.to_dict() for ci in outbound_items])

    # JSONL batch export (item 13 — only unique items reach disk)
    if cfg.jsonl_path and new_dicts:
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
                    for ci in outbound_items:
                        if _wh_budget <= 0:
                            logger.warning("%s global webhook budget exhausted", src_label)
                            break
                        if fire_webhook(ci, cfg.webhook_url, cfg.webhook_secret,
                                        _client=wh_client) is not None:
                            _wh_budget -= 1

                # News→Chart auto-webhook
                if _do_nc_wh:
                    _nc_budget = 5
                    for ci in outbound_items:
                        if _nc_budget <= 0:
                            break
                        if effective_attention_dispatchable(ci) and effective_attention_score(ci) >= 0.85:
                            fire_webhook(ci, _nc_webhook_url, cfg.webhook_secret,
                                         min_score=0.85, _client=wh_client)
                            _nc_budget -= 1
        except Exception as exc:
            logger.warning("Webhook client failed: %s", exc, exc_info=True)

    # Push notifications for high-score items
    if outbound_dicts:
        try:
            _nr = notify_high_score_items(
                outbound_dicts, config=st.session_state.notify_config,
            )
            if _nr:
                st.session_state.notify_log = (
                    _nr + st.session_state.notify_log
                )[:100]
        except Exception as exc:
            logger.warning("Push notification dispatch failed: %s", exc, exc_info=True)

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

    st.toast(f"📡 {len(items)} live story update(s) [{src_label}]", icon="✅")


def _should_poll(poll_interval: float) -> bool:
    """Determine if we should poll this cycle."""
    cfg: TerminalConfig = st.session_state.cfg
    if not _has_live_news_provider(cfg, st.session_state.feed):
        return False
    elapsed: float = time.time() - st.session_state.last_poll_ts
    return elapsed >= poll_interval  # type: ignore[no-any-return]


def _do_poll() -> None:
    """Execute one provider-neutral live-news poll cycle."""
    cfg: TerminalConfig = st.session_state.cfg
    adapter = _get_adapter()
    fmp_adapter = _get_fmp_adapter()
    tv_symbols = _collect_tv_news_symbols(cfg, st.session_state.feed)
    if adapter is None and fmp_adapter is None and not tv_symbols:
        return

    store = _get_store()

    st.session_state["poll_attempts"] = st.session_state.get("poll_attempts", 0) + 1

    try:
        items, provider_cursors, provider_counts = poll_and_classify_live_bus(
            benzinga_adapter=adapter,
            fmp_adapter=fmp_adapter,
            store=store,
            provider_cursors=st.session_state.provider_cursors,
            page_size=cfg.page_size,
            channels=cfg.channels or None,
            topics=cfg.topics or None,
            tv_symbols=tv_symbols,
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

    new_cursor = legacy_cursor_from_provider_cursors(provider_cursors)
    story_feed_items, alert_items, replace_story_keys = _apply_live_story_batch(items)
    st.session_state.provider_cursors = dict(provider_cursors)
    st.session_state.cursor = new_cursor
    st.session_state.poll_count += 1
    st.session_state.last_poll_ts = time.time()
    st.session_state.total_items_ingested += len(items)
    st.session_state.last_poll_error = ""

    src_label = live_news_source_label(provider_counts)
    st.session_state.last_poll_status = (
        f"{len(story_feed_items)} live / {len(items)} raw [{src_label}] (cursor={new_cursor})"
    )

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
            st.session_state.provider_cursors = {}
            logger.info(
                "Reset cursor + pruned SQLite (keep=%.0f) after %d consecutive empty polls",
                _prune_keep,
                st.session_state.consecutive_empty_polls,
            )
            st.session_state.consecutive_empty_polls = 0
    else:
        st.session_state.consecutive_empty_polls = 0

    # Shared post-poll processing (JSONL, webhooks, notifications, trim, VD)
    _process_new_items(
        story_feed_items,
        cfg,
        src_label=src_label,
        replace_story_keys=replace_story_keys,
        outbound_items=alert_items,
    )

    # Evaluate alert rules after feed/state rebuild so rules see the same
    # per-ticker feed-state interpretation as outbound webhooks/notifications.
    _evaluate_alerts(_enrich_classified_items_with_feed_state(alert_items))

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


def _stop_bg_poller_if_running(*, reason: str) -> None:
    """Stop and detach the background poller if it exists.

    Centralized helper to keep lifecycle transitions consistent when
    switching between BG and foreground polling modes.
    """
    _bp_existing = st.session_state.get("bg_poller")
    if _bp_existing is None:
        return
    try:
        _bp_existing.stop_and_join(timeout=5.0)
        logger.info("Background poller stopped (%s)", reason)
    except Exception:
        logger.warning("Background poller stop failed (%s)", reason, exc_info=True)
    finally:
        _snapshot_bg_poller_state(_bp_existing, reason=reason)
        st.session_state.bg_poller = None


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
    st.session_state.provider_cursors = {}
    st.session_state.live_story_state = {}
    st.session_state.ticker_catalyst_state = {}
    st.session_state.ticker_reaction_state = {}
    st.session_state.ticker_resolution_state = {}
    st.session_state.ticker_posture_state = {}
    st.session_state.ticker_attention_state = {}
    st.session_state.poll_count = 0
    _bp_sync = st.session_state.get("bg_poller")
    if _bp_sync is not None:
        _bp_sync.wake_and_reset_cursor()
    logger.info("Feed lifecycle: weekend data cleared")
elif _lc_result.get("feed_action") == "stale_recovery":
    st.session_state.cursor = None
    st.session_state.provider_cursors = {}
    st.session_state.live_story_state = {}
    st.session_state.ticker_catalyst_state = {}
    st.session_state.ticker_reaction_state = {}
    st.session_state.ticker_resolution_state = {}
    st.session_state.ticker_posture_state = {}
    st.session_state.ticker_attention_state = {}
    st.session_state.consecutive_empty_polls = 0
    # Clear stale items so feed_staleness_minutes() reflects the
    # recovery rather than re-measuring the same old timestamps.
    st.session_state.feed = []
    st.session_state.poll_count = 0
    _bp_sync = st.session_state.get("bg_poller")
    if _bp_sync is not None:
        # Atomic reset + wake: avoids BG thread overwriting cursor and
        # interrupts its sleep so the next poll is immediate.
        _bp_sync.consecutive_empty_polls = 0
        _bp_sync.wake_and_reset_cursor()
    logger.info("Feed lifecycle: stale-recovery — feed cleared + cursor reset + BG poller woken")

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
    and _has_live_news_provider(st.session_state.cfg, st.session_state.feed)
)

# ── Background poller mode ──────────────────────────────────────
if st.session_state.use_bg_poller:
    _live_tv_symbols = _collect_tv_news_symbols(st.session_state.cfg, st.session_state.feed)
    _has_live_provider = _has_live_news_provider(st.session_state.cfg, st.session_state.feed)
    # Foreground initial poll BEFORE creating the bg poller so both
    # don't race on the same SQLite store with cursor=None.
    if _feed_empty_needs_poll:
        with st.spinner("Loading latest news…"):
            _do_poll()

    _existing_bp = st.session_state.get("bg_poller")
    if _existing_bp is not None and not _existing_bp.is_alive:
        _snapshot_bg_poller_state(_existing_bp, reason="unexpected_exit", restarting=True)
        logger.warning(
            "Background poller died unexpectedly; restarting (last_status=%s)",
            getattr(_existing_bp, "last_poll_status", "—"),
        )
        st.session_state.bg_poller = None

    # Start background poller if not running
    if _has_live_provider and (st.session_state.bg_poller is None or not st.session_state.bg_poller.is_alive):
        _bp = BackgroundPoller(
            cfg=st.session_state.cfg,
            benzinga_adapter=_get_adapter(),
            fmp_adapter=_get_fmp_adapter(),
            store=_get_store(),
        )
        _bp.update_live_news_symbols(_live_tv_symbols)
        _bp.start(cursor=st.session_state.provider_cursors or st.session_state.cursor)
        st.session_state.bg_poller = _bp
        logger.info("Background poller initialized")
    elif not _has_live_provider:
        _stop_bg_poller_if_running(reason="missing_live_news_provider")

    if st.session_state.bg_poller is not None:
        st.session_state.bg_poller.update_adapters(
            benzinga_adapter=_get_adapter(),
            fmp_adapter=_get_fmp_adapter(),
        )
        st.session_state.bg_poller.update_live_news_symbols(_live_tv_symbols)
        # Update interval (may have changed via slider or off-hours adjustment)
        st.session_state.bg_poller.update_interval(_effective_interval)

    # Drain new items from background thread
    _bg_items = st.session_state.bg_poller.drain() if st.session_state.bg_poller is not None else []
    if _bg_items:
        _bg_feed_items, _bg_alert_items, _bg_replace_story_keys = _apply_live_story_batch(_bg_items)

        # Shared post-poll processing (JSONL, webhooks, notifications, trim, VD)
        _process_new_items(
            _bg_feed_items,
            st.session_state.cfg,
            src_label="BG",
            replace_story_keys=_bg_replace_story_keys,
            outbound_items=_bg_alert_items,
        )

        # Alert evaluation after the feed-state overlays have been rebuilt.
        _evaluate_alerts(_enrich_classified_items_with_feed_state(_bg_alert_items))

        # Only record ingest time for new or upgraded live stories.
        # Repeat/provider_seen observations do not refresh the operator
        # feed and therefore should not reset lifecycle staleness.
        if _bg_feed_items:
            _lm = st.session_state.get("lifecycle_mgr")
            if _lm is not None:
                _lm.notify_ingest()

    # Sync status from background poller for sidebar display
    _bp = st.session_state.bg_poller
    if _bp is not None:
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
        st.session_state["bg_poller_total_dropped"] = max(
            int(st.session_state.get("bg_poller_total_dropped", 0) or 0),
            int(getattr(_bp, "total_items_dropped", 0) or 0),
        )
        st.session_state.provider_cursors = _bp.provider_cursors
        st.session_state.cursor = legacy_cursor_from_provider_cursors(st.session_state.provider_cursors)

else:
    _stop_bg_poller_if_running(reason="bg_mode_disabled")
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

# ── TradingView headline supplement ────────────────────────────
# After the main poll cycle, fetch TradingView headlines for tickers
# already present in the feed.  TV results are merged into the feed
# with dedup so duplicate headlines are suppressed.  This runs on a
# separate cadence (every 3 min via its internal cache TTL) to avoid
# hammering the unofficial endpoint.
_tv_last_ts: float = st.session_state.get("tv_supplement_ts", 0.0)
_tv_live_bus_owned = bool(_collect_tv_news_symbols(st.session_state.cfg, st.session_state.feed))
if tv_available() and not _tv_live_bus_owned and time.time() - _tv_last_ts >= 180:  # 3 min cadence
    # Pick the 8 most-recently-seen tickers (newest feed items first)
    _tv_seen: dict[str, None] = {}  # ordered-dict trick for dedup
    for _fd in st.session_state.feed:
        _tk = _fd.get("ticker", "")
        if _tk and _tk not in ("MARKET", "") and _tk not in _tv_seen:
            _tv_seen[_tk] = None
            if len(_tv_seen) >= 8:
                break
    _tv_tickers = list(_tv_seen)
    if _tv_tickers:
        try:
            _tv_dicts = fetch_tv_feed_dicts(_tv_tickers, max_per_ticker=8, max_total=30)
            if _tv_dicts:
                # Dedup against existing feed by headline text
                _existing_hl = {
                    d.get("headline", "").strip().lower()
                    for d in st.session_state.feed if d.get("headline")
                }
                _existing_ids = {
                    d.get("item_id", "") for d in st.session_state.feed
                }
                _tv_unique = [
                    d for d in _tv_dicts
                    if d.get("item_id") not in _existing_ids
                    and d.get("headline", "").strip().lower() not in _existing_hl
                ]
                if _tv_unique:
                    st.session_state.feed = dedup_feed_items(
                        _tv_unique + st.session_state.feed
                    )
                    logger.info(
                        "TV supplement: added %d headlines for %s",
                        len(_tv_unique), ", ".join(_tv_tickers[:4]),
                    )
        except Exception as _tv_exc:
            logger.warning("TV supplement fetch failed: %s", _tv_exc, exc_info=True)
        st.session_state["tv_supplement_ts"] = time.time()


# ── Main display ────────────────────────────────────────────────

st.markdown("<style>h1 {margin-top: -1.2rem !important;}</style>", unsafe_allow_html=True)
st.markdown(
    '<p style="font-size:2.05rem; line-height:1.24; font-weight:400; color:inherit; margin-bottom:1.75rem;">'
    '📡 Real-Time News Intelligence Stock + Bitcoin Dashboard — AI supported</p>',
    unsafe_allow_html=True,
)

if not _has_live_news_provider(st.session_state.cfg, st.session_state.feed):
    _stop_bg_poller_if_running(reason="missing_live_news_provider")
    st.warning("No live news provider is configured. Enable Benzinga, FMP, or TradingView symbols to resume polling.")

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
    # ── Stats bar: Top 3 ranked symbols + key metrics ─────
    # Use the ranked list from session state (computed in Rankings tab on
    # the previous Streamlit rerun).  On the very first load, fall back to
    # a quick inline ranking from feed + spikes.
    _prev_ranked: list[dict[str, Any]] = st.session_state.get("_ranked_list") or []
    if _prev_ranked:
        # Take the exact top-3 from the ranking list (same order as the table)
        _top3_ranked = _prev_ranked[:3]
    else:
        # Fallback: quick inline ranking (first load only)
        _top3_all: dict[str, dict[str, Any]] = {}
        _top3_detector: SpikeDetector = st.session_state.spike_detector
        for _t3ev in _top3_detector.events[:50]:
            _t3s = _t3ev.symbol
            _t3x = _top3_all.get(_t3s)
            if not _t3x or abs(_t3ev.spike_pct) > abs(_t3x.get("chg_pct", 0)):
                _top3_all[_t3s] = {
                    "symbol": _t3s, "name": _t3ev.name[:30],
                    "price": _t3ev.price, "chg_pct": _t3ev.spike_pct,
                    "news_score": 0.0, "sentiment": "",
                }
        for _t3fi in feed:
            _t3tk = (_t3fi.get("ticker") or "").upper().strip()
            if not _t3tk or _t3tk == "MARKET":
                continue
            _t3ns = effective_posture_score(_t3fi)
            _t3sent = effective_catalyst_sentiment(_t3fi)
            _t3attention_state = effective_attention_state(_t3fi)
            _t3attention_score = effective_attention_score(_t3fi)
            if _t3tk in _top3_all:
                if _t3attention_score > _safe_float_mov(_top3_all[_t3tk].get("attention_score")):
                    _top3_all[_t3tk]["news_score"] = _t3ns
                    _top3_all[_t3tk]["sentiment"] = _t3sent
                    _top3_all[_t3tk]["attention_state"] = _t3attention_state
                    _top3_all[_t3tk]["attention_score"] = _t3attention_score
            else:
                _top3_all[_t3tk] = {
                    "symbol": _t3tk,
                    "name": (_t3fi.get("name") or _t3fi.get("company") or "")[:30],
                    "price": 0, "chg_pct": 0,
                    "news_score": _t3ns, "sentiment": _t3sent,
                    "attention_state": _t3attention_state,
                    "attention_score": _t3attention_score,
                }
        def _top3_sort(r: dict[str, Any]) -> tuple[float, float, int, float, float]:
            _chg = float(r.get("chg_pct") or 0)
            _ns = float(r.get("news_score") or 0)
            _attention_pri = float(effective_attention_priority(r))
            _attention_score = float(r.get("attention_score") or 0)
            _sent = (r.get("sentiment") or "").lower()
            _tier = 1 if _chg > 0 or _sent == "bullish" else (-1 if _chg < 0 or _sent == "bearish" else 0)
            return (-_attention_pri, -_attention_score, -_tier, -_ns, -_chg)
        _top3_ranked = sorted(_top3_all.values(), key=_top3_sort)[:3]
        # Databento enrichment for fallback top-3 cards
        if databento_available() and _top3_ranked:
            try:
                _t3_syms = [r["symbol"] for r in _top3_ranked]
                _t3_by_sym = fetch_databento_quote_map(_t3_syms)
                for _t3r in _top3_ranked:
                    _t3fq = _t3_by_sym.get(_t3r["symbol"])
                    if not _t3fq:
                        continue
                    if _t3r.get("price") == 0 and _t3fq.get("price"):
                        _t3r["price"] = _t3fq["price"]
                    if not _t3r.get("chg_pct"):
                        _cp = _t3fq.get("changesPercentage") or _t3fq.get("changePercentage")
                        if _cp is not None and _cp != 0:
                            _t3r["chg_pct"] = _cp
                    if not _t3r.get("name") and _t3fq.get("name"):
                        _t3r["name"] = str(_t3fq["name"])[:30]
            except Exception:
                logger.debug("Top-3 cards Databento enrichment failed", exc_info=True)

    _stats = compute_feed_stats(feed)

    if _top3_ranked:
        _t3_cols = st.columns(3)
        for _t3i, _t3r in enumerate(_top3_ranked):
            _t3_sym = _t3r["symbol"]
            _t3_sent = (_t3r.get("sentiment") or "").lower()
            _t3_sent_icon = "🟢" if _t3_sent == "bullish" else "🔴" if _t3_sent == "bearish" else "⚪"
            _t3_sent_label = _t3_sent.title() if _t3_sent else "Neutral"
            _t3_ns = _t3r.get("news_score", 0)
            _t3_attention_state = str(_t3r.get("attention_state") or "").strip().upper()
            _t3_attention_icon = _ATTENTION_ICONS.get(_t3_attention_state, "")
            _t3_price = _t3r.get("price", 0)
            _t3_name = _t3r.get("name", "")
            _t3_price_str = f"${_t3_price:.2f}" if _t3_price >= 1 else (f"${_t3_price:.4f}" if _t3_price > 0 else "")
            _t3_sub = f"{_t3_sent_icon} {_t3_sent_label}"
            if _t3_attention_state:
                _t3_sub = f"{_t3_attention_icon} {_t3_attention_state.title()} · " + _t3_sub
            if _t3_price_str:
                _t3_sub += f" · {_t3_price_str}"
            if _t3_ns > 0:
                _t3_sub += f" · Catalyst {_t3_ns:.2f}"
            _t3_name_safe = safe_markdown_text(_t3_name) if _t3_name else ""
            with _t3_cols[_t3i]:
                st.markdown(f"### #{_t3i+1} {_t3_sym}")
                if _t3_name_safe:
                    st.caption(_t3_name_safe)
                st.markdown(_t3_sub)
    else:
        st.caption("No ranked symbols yet — waiting for data…")

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
                _best = max(_tk_items, key=effective_catalyst_score)
                _hl = safe_markdown_text((_best.get("headline") or "")[:100])
                _u = safe_url(_best.get("url") or "")
                _link = f"[{_hl}]({_u})" if _u else _hl
                st.markdown(f"**{_tk_sym}** — {_link}")

    with _detail_cols[1]:
        with st.expander(f"Actionable ({_stats['actionable']})"):
            _act_items = dedup_feed_items([d for d in feed if _is_actionable_broad(d)])
            if _act_items:
                for _ai in _act_items:
                    _tk = _ai.get("ticker", "?")
                    _hl = safe_markdown_text((_ai.get("headline") or "")[:100])
                    _u = safe_url(_ai.get("url") or "")
                    _sc = effective_attention_score(_ai)
                    _att = effective_attention_state(_ai)
                    _link = f"[{_hl}]({_u})" if _u else _hl
                    if _att:
                        st.markdown(f"**{_tk}** ({_att.title()} · {_sc:.2f}) — {_link}")
                    else:
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
                    _sc = effective_catalyst_score(_hi)
                    _link = f"[{_hl}]({_u})" if _u else _hl
                    st.markdown(f"**{_tk}** ({_sc:.2f}) — {_link}")
            else:
                st.caption("No HIGH materiality items.")

    st.divider()

    # ── Tabs ────────────────────────────────────────────────
    _session_icons = SESSION_ICONS
    # Compute once per render — avoids 4+ redundant calls and cross-tab drift
    _current_session = market_session()

    def _get_tech_summary(symbol: str, interval: str = "15m") -> str:
        """Return cached tech summary badge for dataframe cells."""
        cache = st.session_state.get("_cached_technicals") or st.session_state.get("_cached_fmp_technicals") or {}
        entry = cache.get(symbol.upper().strip())
        if not entry:
            return "\u2014"
        sig = entry.get("summary", "")
        icon = signal_icon(sig)
        label = signal_label(sig)
        return f"{icon} {label}" if icon else (label or "\u2014")

    def _safe_tab(label: str, body_fn, *args, **kwargs) -> None:  # noqa: ANN001
        """Wrap a tab body in try/except so one failing tab doesn't crash others (item 7)."""
        try:
            body_fn(*args, **kwargs)
        except Exception as _tab_exc:
            st.error(f"⚠️ {label} tab failed to render.")
            import traceback as _tb
            st.code(_tb.format_exc(), language="python")
            logger.exception("Tab %s render error", label)

    @contextmanager
    def _tab_guard(label: str):
        """Context-manager equivalent of _safe_tab for inline tab bodies."""
        try:
            yield
        except Exception:
            st.error(f"⚠️ {label} tab failed to render.")
            import traceback as _tb
            st.code(_tb.format_exc(), language="python")
            logger.exception("Tab %s render error", label)

    tab_rank, tab_actionable, tab_ai, tab_segments, tab_outlook, tab_feed, tab_bitcoin, tab_alerts, tab_table = st.tabs(
        ["🏆 Rankings", "🎯 Actionable", "🧠 AI Insights", "🏗️ Segments", "🔮 Outlook",
         "📰 Live Feed", "₿ Bitcoin",
         "⚡ Alerts", "📊 Data Table"],
    )

    # ── TAB: Live Feed (with search + date filter) ──────────
    with tab_feed, _tab_guard("Live Feed"):
        # Search + filter controls
        fcol1, fcol2, fcol3, fcol4 = st.columns([3, 1.5, 1.5, 1])
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
        with fcol4:
            feed_sort = st.selectbox(
                "Sort by", ["Newest", "Score"],
                key="feed_sort",
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
            sort_by=feed_sort.lower(),
        )

        st.caption(f"Showing {len(filtered)} of {len(feed)} items")

        # ── Databento quote enrichment for feed tickers ──
        _feed_nlp: dict[str, Any] = {}
        _feed_tickers = sorted({
            str(item.get("ticker") or "").upper().strip()
            for item in filtered[:50]
            if str(item.get("ticker") or "").upper().strip() not in {"", "MARKET"}
        })
        if databento_available() and _feed_tickers:
            try:
                _feed_nlp = fetch_databento_quote_map(_feed_tickers[:200])
            except Exception:
                logger.debug("Live Feed Databento quotes failed", exc_info=True)

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
            with st.popover("**Price** ℹ️"):
                st.markdown(
                    "**Databento daily close price** — The most recent closing price "
                    "from Databento market data."
                )
        st.divider()

        for d in filtered[:50]:
            _effective_sentiment = effective_catalyst_sentiment(d)
            sent_icon = _SENTIMENT_COLORS.get(_effective_sentiment, "")
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
            score = effective_catalyst_score(d)
            relevance = d.get("relevance", 0)
            category = d.get("category", "other")
            headline = d.get("headline", "")
            event_label = d.get("event_label", "")
            source_tier = d.get("source_tier", "")
            _provider = d.get("provider", "")
            url = d.get("url", "")

            age_str = format_age_string(d.get("published_ts"))
            score_badge = format_score_badge(score, _effective_sentiment)
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
                    # Databento price enrichment
                    _db_data = _feed_nlp.get(ticker.upper())
                    if _db_data and _db_data.get("price"):
                        _db_p = _db_data["price"]
                        st.markdown(f"💲 `${_db_p:.2f}`" if _db_p >= 1 else f"💲 `${_db_p:.4f}`")
                    else:
                        st.markdown("")

    # ── TAB: Rankings (feed + spike based — no extra API calls) ─
    with tab_rank, _tab_guard("Rankings"):
        _session_label_rank = _session_icons.get(_current_session, _current_session)

        st.header("🏆 Rankings")
        st.caption(f"**{_session_label_rank}** — Symbols ranked by operator attention first, then directional state and composite score (price + catalyst + tech + RT signal). Feed + RT spike + realtime signals.")

        # Build unified symbol map from feed + RT spikes (zero API calls)
        _rank_now = time.time()
        _rank_all: dict[str, dict[str, Any]] = {}

        # 1) RT spike events (highest fidelity — real-time price data)
        _detector_rank: SpikeDetector = st.session_state.spike_detector
        for ev in _detector_rank.events[:50]:
            sym = ev.symbol
            existing = _rank_all.get(sym)
            if not existing or abs(ev.spike_pct) > abs(existing.get("chg_pct", 0)):
                _rank_all[sym] = {
                    "symbol": sym, "name": ev.name[:50],
                    "price": ev.price, "change": ev.change, "chg_pct": ev.spike_pct,
                    "volume": ev.volume, "mkt_cap": "",
                    "_ts": ev.ts, "_from_spike": True,
                }

        # 2) Feed items — extract unique tickers not already covered by spikes
        for _fi in feed:
            _fticker = (_fi.get("ticker") or "").upper().strip()
            if not _fticker or _fticker == "MARKET" or _fticker in _rank_all:
                continue
            _f_ts = _fi.get("published_ts") or _fi.get("created_ts") or 0
            _rank_all[_fticker] = {
                "symbol": _fticker,
                "name": (_fi.get("name") or _fi.get("company") or "")[:50],
                "price": 0, "change": 0, "chg_pct": 0,
                "volume": 0, "mkt_cap": "",
                "_ts": _f_ts,
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
                _nscore = effective_posture_score(_ni)
                _existing_news = _news_by_ticker.get(_nticker)
                if not _existing_news or _nscore > _safe_float_mov(_existing_news.get("posture_score")):
                    _news_by_ticker[_nticker] = {
                        "news_score": effective_catalyst_score(_ni),
                        "attention_score": effective_attention_score(_ni),
                        "attention_state": effective_attention_state(_ni),
                        "posture_score": _nscore,
                        "posture_state": effective_posture_state(_ni),
                        "reaction_score": effective_reaction_score(_ni),
                        "reaction_state": effective_reaction_state(_ni),
                        "resolution_score": effective_resolution_score(_ni),
                        "resolution_state": effective_resolution_state(_ni),
                        "headline": (_ni.get("catalyst_headline") or _ni.get("headline") or "")[:120],
                        "url": _ni.get("url") or "",
                        "sentiment": effective_catalyst_sentiment(_ni),
                    }

            # Enrich _rank_all with news data
            _news_match_count = 0
            for sym, row in _rank_all.items():
                news = _news_by_ticker.get(sym)
                if news:
                    row["news_score"] = news["news_score"]
                    row["attention_score"] = news["attention_score"]
                    row["attention_state"] = news["attention_state"]
                    row["posture_score"] = news["posture_score"]
                    row["posture_state"] = news["posture_state"]
                    row["reaction_score"] = news["reaction_score"]
                    row["reaction_state"] = news["reaction_state"]
                    row["resolution_score"] = news["resolution_score"]
                    row["resolution_state"] = news["resolution_state"]
                    row["headline"] = news["headline"]
                    row["url"] = news["url"]
                    row["sentiment"] = news["sentiment"]
                    _news_match_count += 1
                else:
                    row["news_score"] = 0.0
                    row["attention_score"] = 0.0
                    row["attention_state"] = ""
                    row["posture_score"] = 0.0
                    row["posture_state"] = ""
                    row["reaction_score"] = 0.0
                    row["reaction_state"] = ""
                    row["resolution_score"] = 0.0
                    row["resolution_state"] = ""
                    row["headline"] = ""
                    row["url"] = ""
                    row["sentiment"] = ""

            # ── Pre-sort Databento enrichment: fill price/change/volume for
            #    feed-only items (which have price=0) BEFORE sorting so the
            #    bullish/bearish sort and composite score use real data.
            _rank_fmp: dict[str, dict[str, Any]] = {}
            _rank_all_syms = list(_rank_all.keys())
            if databento_available() and _rank_all_syms:
                try:
                    _rank_fmp = fetch_databento_quote_map(_rank_all_syms[:200])
                except Exception:
                    logger.debug("Rankings Databento quotes (pre-sort) failed", exc_info=True)

            # Apply Databento data to all items before sorting
            for sym, row in _rank_all.items():
                _fq = _rank_fmp.get(sym)
                if not _fq:
                    continue
                if row.get("price") == 0 and _fq.get("price"):
                    row["price"] = _fq["price"]
                if row.get("change") == 0 and _fq.get("change") is not None:
                    row["change"] = _fq["change"]
                # changesPercentage from Databento; fallback: compute from change/price
                if not row.get("chg_pct"):
                    # Databento batch-quote uses "changePercentage" (no trailing 's')
                    _fq_chg_pct = _fq.get("changesPercentage") or _fq.get("changePercentage")
                    if _fq_chg_pct is not None and _fq_chg_pct != 0:
                        row["chg_pct"] = _fq_chg_pct
                    else:
                        # Derive from change / price (handles off-hours when Databento returns 0)
                        _chg_val = float(row.get("change") or _fq.get("change") or 0)
                        _price_val = float(row.get("price") or _fq.get("price") or 0)
                        if _price_val > 0 and _chg_val != 0:
                            row["chg_pct"] = round(_chg_val / _price_val * 100, 4)
                # Volume: try volume, then avgVolume as fallback
                if not row.get("volume"):
                    _fq_vol = _fq.get("volume") or _fq.get("avgVolume") or 0
                    if _fq_vol:
                        row["volume"] = _fq_vol
                if not row.get("name") and _fq.get("name"):
                    row["name"] = str(_fq["name"])[:50]
                # Only fill in a timestamp when the row has none at all
                # (feed items already carry their news-article publish time;
                # spike items carry their detection time).  Do NOT overwrite
                # with time.time() — that resets Age to 0:00:00:00 every
                # render cycle.
                if row.get("_ts", 0) == 0:
                    row["_ts"] = _fq.get("timestamp") or _rank_now

            # Composite ranking: 50% price move + 20% news + 15% RT technical + 15% RT signal
            # news_score is typically 0-1, scale to comparable range
            _RT_SIGNAL_BONUS = {"A0": 30.0, "A1": 15.0, "A2": 5.0}

            # Pre-load RT engine signals so composite / sort closures can reference them.
            # The dict is populated further down; this ensures it exists for the closures.
            _rt_sig_path = str(PROJECT_ROOT / "artifacts" / "open_prep" / "latest" / "latest_vd_signals.jsonl")
            _rt_signals: dict[str, str] = {}
            _rt_full: dict[str, dict[str, Any]] = {}  # full RT row per symbol
            try:
                _rt_raw = load_rt_quotes(_rt_sig_path, max_age_s=7200)  # 2h grace for signal display
                for _rts, _rtrow in _rt_raw.items():
                    if _rts.startswith("_"):
                        continue
                    _sig = _rtrow.get("signal", "")
                    if _sig:
                        _rt_signals[_rts] = _sig
                    _rt_full[_rts] = _rtrow
            except Exception:
                logger.debug("Failed to load RT JSONL quotes", exc_info=True)

            def _composite_score(r: dict[str, Any]) -> float:
                _chg = float(r.get("chg_pct") or 0)
                _ns = float(r.get("news_score") or 0)
                _tech = float(r.get("_rt_tech_score") or 0.5)
                _base = abs(_chg) * 0.50 + _ns * 100.0 * 0.20
                # Technical indicator contribution: direction-aware
                # Bullish tech (>0.5) adds to score; bearish tech (<0.5)
                # only adds when price direction aligns (short).
                _tech_dev = _tech - 0.5
                if _chg >= 0:
                    _tech_contrib = max(_tech_dev, 0) * 100.0 * 0.15
                else:
                    _tech_contrib = max(-_tech_dev, 0) * 100.0 * 0.15
                # RT signal tier bonus
                _sig = _rt_signals.get(r.get("symbol", ""), "")
                _sig_bonus = _RT_SIGNAL_BONUS.get(_sig, 0.0) * 0.15
                return _base + _tech_contrib + _sig_bonus

            # Default sort: bullish first (positive chg_pct), then best composite score
            def _bullish_nlp_key(r: dict[str, Any]) -> tuple[float, int, float, float, float, float, float, float, float, float, float, float]:
                _chg = float(r.get("chg_pct") or 0)
                _ns = float(r.get("news_score") or 0)
                _attention_score = float(r.get("attention_score") or 0)
                _attention_pri = float(effective_attention_priority(r))
                _posture_score = float(r.get("posture_score") or 0)
                _resolution_score = float(r.get("resolution_score") or 0)
                _reaction_score = float(r.get("reaction_score") or 0)
                _posture_pri = float(effective_posture_priority(r))
                _resolution_pri = float(effective_resolution_priority(r))
                _reaction_pri = float(effective_reaction_priority(r))
                _sent = (r.get("sentiment") or "").lower()
                # Tier: 1=bullish/positive move, 0=neutral, -1=bearish
                _tier = 1 if _chg > 0 or _sent == "bullish" else (-1 if _chg < 0 or _sent == "bearish" else 0)
                # A0/A1 signals get priority within their tier
                _sig_pri = {"A0": 2.0, "A1": 1.0}.get(_rt_signals.get(r.get("symbol", ""), ""), 0.0)
                # Composite score as final tiebreaker within same tier/signal/news
                _cs = _composite_score(r)
                return (-_attention_pri, -_tier, -_attention_score, -_posture_pri, -_resolution_pri, -_sig_pri, -_posture_score, -_resolution_score, -_reaction_pri, -_reaction_score, -_ns, -_cs)

            _ranked = sorted(
                _rank_all.values(),
                key=_bullish_nlp_key,
            )

            # Stash ranked list for top-3 cards (rendered earlier in layout)
            st.session_state["_ranked_list"] = _ranked

            # NLP sentiment enrichment removed (NewsAPI.ai no longer available)
            _rank_nlp: dict[str, Any] = {}

            # Databento quotes already fetched pre-sort (in _rank_fmp) — reuse them.
            _rank_top_syms = [m["symbol"] for m in _ranked[:50]]

            # Social sentiment — merge into shared cache with TTL
            _RANK_CACHE_TTL = 180  # 3 minutes — keep rankings data fresh
            _rank_social: dict[str, Any] = {}
            _social_ts = st.session_state.get("_cached_social_sent_ts", 0)
            if time.time() - _social_ts < _RANK_CACHE_TTL:
                _rank_social = st.session_state.get("_cached_social_sent") or {}
            _rank_social_missing = [t for t in _rank_top_syms[:15] if t not in _rank_social]
            if _rank_social_missing and _intel_enabled() and finnhub_available():
                try:
                    _raw_rs = fetch_social_sentiment_batch(_rank_social_missing)
                    if _raw_rs:
                        _new_social = {
                            sym: {"total_mentions": s.total_mentions, "score": s.score, "label": s.sentiment_label}
                            for sym, s in _raw_rs.items()
                        }
                        _rank_social = {**_rank_social, **_new_social}
                        st.session_state["_cached_social_sent"] = _rank_social
                        st.session_state["_cached_social_sent_ts"] = time.time()
                except Exception:
                    logger.debug("Rankings social sentiment failed", exc_info=True)

            # Analyst forecasts — merge into shared cache with TTL
            _rank_forecasts: dict[str, Any] = {}
            _forecasts_ts = st.session_state.get("_cached_forecasts_ts", 0)
            if time.time() - _forecasts_ts < _RANK_CACHE_TTL:
                _rank_forecasts = st.session_state.get("_cached_forecasts") or {}
            _rank_fc_missing = [t for t in _rank_top_syms[:10] if t not in _rank_forecasts]
            if _rank_fc_missing and _intel_enabled():
                try:
                    for _sym in _rank_fc_missing:
                        _fc = fetch_forecast(_sym)
                        if _fc.has_data and _fc.price_target:
                            _rank_forecasts[_sym] = {
                                "price_target": {
                                    "target_mean": _fc.price_target.target_mean,
                                    "upside_pct": round(_fc.price_target.upside_pct, 1),
                                },
                                "rating": {
                                    "consensus": _fc.rating.consensus if _fc.rating else "",
                                },
                            }
                    if _rank_forecasts:
                        st.session_state["_cached_forecasts"] = _rank_forecasts
                        st.session_state["_cached_forecasts_ts"] = time.time()
                except Exception:
                    logger.debug("Rankings forecasts failed", exc_info=True)

            # Also load structured signals from JSON for richer data
            _rt_json_signals: dict[str, dict[str, Any]] = {}
            try:
                _rt_disk = RealtimeEngine.load_signals_from_disk(max_age_s=7200)
                for _rs in (_rt_disk.get("signals") or []):
                    _rs_sym = str(_rs.get("symbol", "")).upper()
                    if _rs_sym:
                        _rt_json_signals[_rs_sym] = _rs
            except Exception:
                logger.debug("Failed to load RT JSON signals", exc_info=True)

            # Enrich _rank_all with RT engine data (price, direction, technical)
            for sym, row in _rank_all.items():
                _rt_row = _rt_full.get(sym, {})
                _rt_js = _rt_json_signals.get(sym, {})
                # Fill price/change from RT engine if feed didn't have it
                if row.get("price") == 0 and _rt_row.get("price"):
                    row["price"] = _rt_row["price"]
                if not row.get("chg_pct") and _rt_row.get("chg_pct"):
                    row["chg_pct"] = _rt_row["chg_pct"]
                # Technical data from RT engine
                row["_rt_tech_score"] = _rt_js.get("technical_score") or _rt_row.get("tech_score", 0.5)
                row["_rt_tech_signal"] = _rt_js.get("technical_signal") or _rt_row.get("tech_signal", "")
                row["_rt_rsi"] = _rt_js.get("rsi") or _rt_row.get("rsi")
                row["_rt_macd"] = _rt_js.get("macd_signal") or _rt_row.get("macd", "")
                row["_rt_direction"] = _rt_js.get("direction") or _rt_row.get("direction", "")
                row["_rt_vol_ratio"] = _rt_js.get("volume_ratio") or _rt_row.get("vol_ratio", 0)

            # (FMP-based tech enrichment removed — RT engine is the sole
            #  source for Tech/RSI when available; Databento covers pricing.)

            top_n = min(50, len(_ranked))
            _rank_rows = []
            for i, m in enumerate(_ranked[:top_n], 1):
                _dir = "🟢" if m.get("chg_pct", 0) > 0 else "🔴" if m.get("chg_pct", 0) < 0 else "⚪"
                _sent_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(
                    (m.get("sentiment") or "").lower(), ""
                )
                _hl_url = m.get("url", "")
                _hl_text = m.get("headline", "")
                _catalyst_col = ""
                _reaction_state = str(m.get("reaction_state") or "").strip().upper()
                _reaction_icon = {
                    "CONFIRMED": "✅",
                    "WATCH": "👀",
                    "IDLE": "⏳",
                    "FADE": "↘",
                    "CONFLICTED": "⚠️",
                }.get(_reaction_state, "")
                _reaction_col = f"{_reaction_icon} {_reaction_state.title()}" if _reaction_state else ""
                _attention_state = str(m.get("attention_state") or "").strip().upper()
                _attention_icon = _ATTENTION_ICONS.get(_attention_state, "")
                _attention_col = (
                    f"{_attention_icon} {_attention_state.title()}"
                    if _attention_state
                    else ""
                )
                _posture_state = str(m.get("posture_state") or "").strip().upper()
                _posture_icon = {
                    "LONG": "🟢",
                    "SHORT": "🔴",
                    "WATCH_LONG": "👀",
                    "WATCH_SHORT": "👀",
                    "NEUTRAL": "⚪",
                    "AVOID": "⛔",
                }.get(_posture_state, "")
                _posture_col = f"{_posture_icon} {_posture_state.replace('_', ' ').title()}" if _posture_state else ""
                _resolution_state = str(m.get("resolution_state") or "").strip().upper()
                _resolution_icon = {
                    "FOLLOW_THROUGH": "🚀",
                    "OPEN": "🕒",
                    "STALLED": "⏸️",
                    "FAILED": "❌",
                    "REVERSAL": "↩️",
                }.get(_resolution_state, "")
                _resolution_col = (
                    f"{_resolution_icon} {_resolution_state.replace('_', ' ').title()}"
                    if _resolution_state
                    else ""
                )
                # Use the feed item's news_score so the ranking
                # table is consistent with the header cards.
                _ns_fallback = float(m.get("news_score") or 0)
                if _ns_fallback > 0:
                    _ns_icon = "🟢" if _ns_fallback > 0.6 else ("🟡" if _ns_fallback > 0.3 else "⚪")
                    _catalyst_col = f"{_ns_icon} {_ns_fallback:.2f}"
                _r_price = m.get("price") or 0
                _r_sym = m.get("symbol", "?")

                # RT engine signal (A0/A1) + technicals
                _rt_sig_col = _rt_signals.get(_r_sym, "")
                _rt_tech = float(m.get("_rt_tech_score") or 0.5)
                _rt_tech_sig = m.get("_rt_tech_signal", "")
                _rt_rsi_val = m.get("_rt_rsi")
                _rt_macd_val = m.get("_rt_macd", "")
                _rt_dir = m.get("_rt_direction", "")

                # Format technical indicator column
                _tech_icon = {"STRONG_BUY": "🟢", "BUY": "🟢", "STRONG_SELL": "🔴", "SELL": "🔴"}.get(_rt_tech_sig, "🟡")
                _tech_col = f"{_tech_icon} {_rt_tech:.2f}" if _rt_tech_sig else ""

                # Format RSI column
                _rsi_col = ""
                if _rt_rsi_val is not None and _rt_rsi_val != "":
                    _rsi_v: float | None
                    try:
                        _rsi_v = float(_rt_rsi_val)
                    except (ValueError, TypeError):
                        _rsi_v = None
                    if _rsi_v is not None:
                        _rsi_icon = "🔴" if _rsi_v > 70 else ("🟢" if _rsi_v < 30 else "🟡")
                        _rsi_col = f"{_rsi_icon} {_rsi_v:.0f}"

                # Analyst forecast
                _raf = _rank_forecasts.get(_r_sym, {})
                _raf_pt = _raf.get("price_target", {})
                _raf_rating = _raf.get("rating", {})
                _analyst_col = ""
                if _raf_pt.get("upside_pct") is not None:
                    _up = _raf_pt["upside_pct"]
                    _up_icon = "🟢" if _up > 10 else "🔴" if _up < -10 else "🟡"
                    _consensus = _raf_rating.get("consensus", "")
                    _analyst_col = f"{_up_icon} {_up:+.0f}%"
                    if _consensus:
                        _analyst_col += f" {_consensus}"

                _rank_rows.append({
                    "#": i,
                    "Dir": _dir,
                    "Symbol": _r_sym,
                    "Signal": _rt_sig_col,
                    "Tech": _tech_col,
                    "RSI": _rsi_col,
                    "MACD": _rt_macd_val,
                    "Analyst": _analyst_col,
                    "Price": f"${_r_price:.2f}" if _r_price >= 1 else (f"${_r_price:.4f}" if _r_price > 0 else "—"),
                    "Change": f"{m.get('change', 0):+.2f}",
                    "Change %": f"{m.get('chg_pct', 0):+.2f}%",
                    "Score": round(_composite_score(m), 2),
                    "Attention": _attention_col,
                    "Age": format_age_string(m.get("_ts")),
                    "Sentiment": f"{_sent_icon} {m.get('sentiment', '')}" if m.get("sentiment") else "",
                    "Posture": _posture_col,
                    "Resolution": _resolution_col,
                    "Reaction": _reaction_col,
                    "Catalyst": _catalyst_col,
                    "Volume": f"{m.get('volume', 0):,}" if m.get("volume") else "",
                    "Name": m.get("name", ""),
                    "Headline": _hl_url if _hl_url else _hl_text,
                })

            df_rank = pd.DataFrame(_rank_rows)

            # Auto-hide columns that are entirely empty/blank
            _hideable_cols = ["Signal", "Tech", "RSI", "MACD", "Analyst"]
            _empty_cols = [
                c for c in _hideable_cols
                if c in df_rank.columns and df_rank[c].astype(str).str.strip().replace("", pd.NA).isna().all()
            ]
            if _empty_cols:
                df_rank = df_rank.drop(columns=_empty_cols)

            df_rank = df_rank.set_index("#")

            _n_rank_enriched = sum(1 for x in [_rank_fmp, _rank_forecasts] if x)
            if _rt_signals:
                _n_rank_enriched += 1
            if _rt_full:
                _n_rank_enriched += 1  # RT technicals layer
            st.caption(
                f"Top {top_n} of {len(_ranked)} symbols · "
                f"sorted: attention → directional tier → posture → resolution → RT signal → composite score · "
                f"{_news_match_count} with live state overlay · "
                f"{len(_rt_signals)} RT signals · "
                f"{_n_rank_enriched} enrichment layers"
            )

            with st.popover("ℹ️ Column guide"):
                st.markdown(
                    "- **Signal** — RT engine actionability tier (A0 = top conviction, A1 = secondary)\n"
                    "- **Attention** — Operator escalation state above posture (alert/focus/monitor/background/suppress)\n"
                    "- **Posture** — Final terminal posture derived above resolution (long/short/watch/neutral/avoid)\n"
                    "- **Resolution** — Outcome-state overlay after the initial reaction window (follow-through/open/stalled/failed/reversal)\n"
                    "- **Reaction** — Execution-state overlay from live quote confirmation (confirmed/watch/fade/conflicted)\n"
                    "- **Tech** — Technical indicator score (0–1, weighted: RSI 40%, MA 25%, MACD 15%, ADX 10%)\n"
                    "- **RSI** — RSI-14 (🟢 <30 oversold, 🔴 >70 overbought, 🟡 neutral)\n"
                    "- **MACD** — MACD signal direction (BUY/SELL/NEUTRAL)\n"
                    "- **Analyst** — Analyst consensus (upside %, rating)\n"
                    "- **Score** — Composite: 50% price + 20% catalyst + 15% technical + 15% signal\n"
                    "- **Catalyst** — Derived per-ticker live catalyst strength from the active story state\n"
                    "- **Sentiment** — Derived ticker-level catalyst direction when available\n"
                    "- **Volume** — Trading volume from market data source\n"
                    "- **Headline** — Latest matching news headline (clickable when URL is available)\n\n"
                    "Empty columns mean no matching data is available yet for that ticker."
                )

            # Build column config
            _rank_col_cfg: dict[str, Any] = {
                "Dir": st.column_config.TextColumn("Dir", width="small"),
                "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                "Signal": st.column_config.TextColumn("Signal", width="small"),
                "Attention": st.column_config.TextColumn("Attention", width="small"),
                "Posture": st.column_config.TextColumn("Posture", width="small"),
                "Resolution": st.column_config.TextColumn("Resolution", width="small"),
                "Reaction": st.column_config.TextColumn("Reaction", width="small"),
                "Tech": st.column_config.TextColumn("Tech", width="small"),
                "RSI": st.column_config.TextColumn("RSI", width="small"),
                "MACD": st.column_config.TextColumn("MACD", width="small"),
                "Analyst": st.column_config.TextColumn("Analyst", width="small"),
                "Change %": st.column_config.TextColumn("Change %", width="small"),
                "Score": st.column_config.NumberColumn("Score", width="small"),
                "Age": st.column_config.TextColumn("Age", width="small"),
                "Catalyst": st.column_config.TextColumn("Catalyst", width="small"),
                "Volume": st.column_config.TextColumn("Volume", width="small"),
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
            if _intel_enabled():
                _render_technicals_expander(_rank_symbols, key_prefix="tech_rank")
                _render_forecast_expander(_rank_symbols, key_prefix="fc_rank")
                _render_event_clusters_expander(_rank_symbols, key_prefix="ec_rank")
            else:
                st.caption("⚡ Low-latency mode: optional intelligence modules are disabled.")

    # ── TAB: Actionable ────────────────────────────────────
    with tab_actionable, _tab_guard("Actionable"):
        st.header("🎯 Actionable Items")

        # Broadened actionable criteria now prefer the derived ticker state
        # overlays when present and fall back to the raw story attributes.
        _act_feed = dedup_feed_items([d for d in feed if _is_actionable_broad(d)])
        # Sort by operator attention first, then deeper state quality and freshness.
        _act_feed.sort(
            key=lambda d: (
                -effective_attention_priority(d),
                -effective_attention_score(d),
                -effective_posture_priority(d),
                -effective_posture_score(d),
                -effective_resolution_priority(d),
                -(float(d.get("published_ts") or d.get("created_ts") or 0.0)),
            ),
        )
        if not _act_feed:
            st.info("No actionable items in the current feed.")
        else:
            # -- Collect unique tickers for enrichment batch calls --
            _act_tickers = list({
                (_ai.get("ticker") or "").upper().strip()
                for _ai in _act_feed
                if (_ai.get("ticker") or "").upper().strip() not in ("", "?", "MARKET", "N/A")
            })

            # Databento quotes (price, change%) — batch call
            _act_quotes: dict[str, dict[str, Any]] = {}
            if _act_tickers:
                try:
                    _act_quotes = fetch_databento_quote_map(_act_tickers[:200])
                except Exception:
                    logger.debug("Actionable Databento quotes failed", exc_info=True)

            # Social sentiment — merge into shared cache (not overwrite)
            _act_social: dict[str, Any] = st.session_state.get("_cached_social_sent") or {}
            _act_social_missing = [t for t in _act_tickers if t not in _act_social]
            if _act_social_missing and _intel_enabled() and finnhub_available():
                try:
                    _raw_soc = fetch_social_sentiment_batch(_act_social_missing[:15])
                    if _raw_soc:
                        _new_social = {
                            sym: {
                                "total_mentions": s.total_mentions,
                                "score": s.score,
                                "label": s.sentiment_label,
                            }
                            for sym, s in _raw_soc.items()
                        }
                        _act_social = {**_act_social, **_new_social}
                        st.session_state["_cached_social_sent"] = _act_social
                        st.session_state["_cached_social_sent_ts"] = time.time()
                except Exception:
                    logger.debug("Actionable social sentiment failed", exc_info=True)

            # Analyst forecasts — merge into shared cache (not overwrite)
            _act_forecasts: dict[str, Any] = st.session_state.get("_cached_forecasts") or {}
            _act_fc_missing = [t for t in _act_tickers[:10] if t not in _act_forecasts]
            if _act_fc_missing and _intel_enabled():
                try:
                    for _sym in _act_fc_missing:
                        _fc = fetch_forecast(_sym)
                        if _fc.has_data and _fc.price_target:
                            _act_forecasts[_sym] = {
                                "price_target": {
                                    "target_mean": _fc.price_target.target_mean,
                                    "upside_pct": round(_fc.price_target.upside_pct, 1),
                                },
                                "rating": {
                                    "consensus": _fc.rating.consensus if _fc.rating else "",
                                },
                            }
                    if _act_forecasts:
                        st.session_state["_cached_forecasts"] = _act_forecasts
                        st.session_state["_cached_forecasts_ts"] = time.time()
                except Exception:
                    logger.debug("Actionable forecasts failed", exc_info=True)

            # NLP sentiment removed (NewsAPI.ai no longer available)
            _act_nlp: dict[str, Any] = {}

            # Tech enrichment — rely on RT engine / TradingView only
            _ACT_TECH_KEY = "_cached_fmp_technicals"
            if _ACT_TECH_KEY not in st.session_state:
                st.session_state[_ACT_TECH_KEY] = {}
            _act_tech_cache: dict[str, dict[str, Any]] = st.session_state[_ACT_TECH_KEY]
            _act_tech_ttl = 300.0  # 5-min cache
            _act_tech_now = time.time()
            _need_act_tech = [
                t for t in _act_tickers
                if t not in _act_tech_cache
                or (_act_tech_now - _act_tech_cache[t].get("_ts", 0)) > _act_tech_ttl
            ]
            # (FMP RSI enrichment removed — RT engine / TradingView is sole source)

            _n_enriched = sum(1 for x in [_act_quotes, _act_social, _act_forecasts, _act_tech_cache] if x)
            st.caption(
                f"{len(_act_feed)} actionable items · "
                f"{_n_enriched} enrichment layers · "
                "sorted by attention, posture quality, then freshness"
            )

            _act_now = time.time()
            _act_rows = []
            for i, _ai in enumerate(_act_feed, 1):
                _ai_tk = (_ai.get("ticker") or "?").upper()
                _ai_sc = effective_attention_score(_ai)
                _ai_catalyst_sc = effective_catalyst_score(_ai)
                _ai_sent = effective_catalyst_sentiment(_ai)
                _ai_attention = effective_attention_state(_ai)
                _ai_reaction = effective_reaction_state(_ai)
                _ai_resolution = effective_resolution_state(_ai)
                _ai_posture = effective_posture_state(_ai)
                _ai_attention_icon = _ATTENTION_ICONS.get(_ai_attention, "")
                _ai_posture_icon = {
                    "LONG": "🟢",
                    "SHORT": "🔴",
                    "WATCH_LONG": "👀",
                    "WATCH_SHORT": "👀",
                    "NEUTRAL": "⚪",
                    "AVOID": "⛔",
                }.get(_ai_posture, "")
                _ai_resolution_icon = {
                    "FOLLOW_THROUGH": "🚀",
                    "OPEN": "🕒",
                    "STALLED": "⏸️",
                    "FAILED": "❌",
                    "REVERSAL": "↩️",
                }.get(_ai_resolution, "")
                _ai_reaction_icon = {
                    "CONFIRMED": "✅",
                    "WATCH": "👀",
                    "IDLE": "⏳",
                    "FADE": "↘",
                    "CONFLICTED": "⚠️",
                }.get(_ai_reaction, "")
                _ai_sent_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(_ai_sent, "")
                _ai_hl = (_ai.get("headline") or "")[:120]
                _ai_url = _ai.get("url") or ""
                _ai_cat = _ai.get("category") or ""
                _ai_mat = _ai.get("materiality") or ""

                # Databento quote enrichment
                _aq = _act_quotes.get(_ai_tk, {})
                _aq_price = _aq.get("price") or 0
                _aq_chg = _aq.get("changesPercentage") or _aq.get("change_pct") or 0
                _aq_pe = _aq.get("pe") or _aq.get("peRatio")
                _aq_vol = _aq.get("volume") or 0

                # Social sentiment
                _as = _act_social.get(_ai_tk, {})
                _as_label = _as.get("label", "")
                _as_mentions = _as.get("total_mentions", 0)
                _social_col = "⚪ —"
                if _as_label:
                    _soc_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(_as_label, "⚪")
                    _social_col = f"{_soc_icon} {_as_mentions}"

                # Analyst forecast
                _af = _act_forecasts.get(_ai_tk, {})
                _af_pt = _af.get("price_target", {})
                _af_rating = _af.get("rating", {})
                _analyst_col = ""
                if _af_pt.get("upside_pct") is not None:
                    _up = _af_pt["upside_pct"]
                    _up_icon = "🟢" if _up > 10 else "🔴" if _up < -10 else "🟡"
                    _consensus = _af_rating.get("consensus", "")
                    _analyst_col = f"{_up_icon} {_up:+.0f}%"
                    if _consensus:
                        _analyst_col += f" {_consensus}"

                _act_rows.append({
                    "#": i,
                    "Symbol": _ai_tk,
                    "Price": f"${_aq_price:.2f}" if _aq_price >= 1 else (f"${_aq_price:.4f}" if _aq_price > 0 else "—"),
                    "Chg%": f"{_aq_chg:+.2f}%" if _aq_chg else "—",
                    "Score": round(_ai_sc, 3),
                    "Catalyst": round(_ai_catalyst_sc, 3),
                    "Attention": f"{_ai_attention_icon} {_ai_attention.title()}" if _ai_attention else "",
                    "Posture": f"{_ai_posture_icon} {_ai_posture.replace('_', ' ').title()}" if _ai_posture else "",
                    "Resolution": f"{_ai_resolution_icon} {_ai_resolution.replace('_', ' ').title()}" if _ai_resolution else "",
                    "Reaction": f"{_ai_reaction_icon} {_ai_reaction.title()}" if _ai_reaction else "",
                    "Sentiment": f"{_ai_sent_icon} {_ai_sent.title()}" if _ai_sent else "",
                    "Category": _ai_cat,
                    "Materiality": _ai_mat,
                    "Headline": _ai_url if _ai_url else _ai_hl,
                    "Time": format_age_string(_ai.get("published_ts"), now=_act_now),
                    "Tech": _get_tech_summary(_ai_tk),
                    "Social": _social_col,
                    "Analyst": _analyst_col,
                    "P/E": f"{_aq_pe:.1f}" if _aq_pe and _aq_pe > 0 else "—",
                    "Vol": f"{_aq_vol:,.0f}" if _aq_vol else "—",
                })

            _df_act = pd.DataFrame(_act_rows).set_index("#")

            _act_col_cfg: dict[str, Any] = {
                "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                "Price": st.column_config.TextColumn("Price", width="small"),
                "Chg%": st.column_config.TextColumn("Chg%", width="small"),
                "Score": st.column_config.NumberColumn("Score", width="small", format="%.3f"),
                "Catalyst": st.column_config.NumberColumn("Catalyst", width="small", format="%.3f"),
                "Attention": st.column_config.TextColumn("Attention", width="small"),
                "Posture": st.column_config.TextColumn("Posture", width="small"),
                "Resolution": st.column_config.TextColumn("Resolution", width="small"),
                "Reaction": st.column_config.TextColumn("Reaction", width="small"),
                "Sentiment": st.column_config.TextColumn("Sentiment", width="small"),
                "Category": st.column_config.TextColumn("Category", width="small"),
                "Materiality": st.column_config.TextColumn("Materiality", width="small"),
                "Time": st.column_config.TextColumn("Time", width="small"),
                "Tech": st.column_config.TextColumn("Tech", width="small"),
                "Social": st.column_config.TextColumn("Social", width="small"),
                "Analyst": st.column_config.TextColumn("Analyst", width="small"),
                "P/E": st.column_config.TextColumn("P/E", width="small"),
                "Vol": st.column_config.TextColumn("Vol", width="small"),
            }
            if any(str(r.get("Headline", "")).startswith("http") for r in _act_rows):
                _act_col_cfg["Headline"] = st.column_config.LinkColumn(
                    "Headline",
                    display_text=r"https?://[^/]+/(.{0,60}).*",
                    width="large",
                )

            with st.popover("ℹ️ Column guide"):
                st.markdown(
                    "- **Price / Chg%** — Quote from Databento (price, daily change %)\n"
                    "- **Score** — Attention-aware ticker score used for surfacing, alerts, and prioritization\n"
                    "- **Attention** — Operator escalation state above posture\n"
                    "- **Posture** — Final terminal posture derived above resolution\n"
                    "- **Resolution** — Outcome-state overlay after the initial reaction window\n"
                    "- **Reaction** — Reaction confirmation state from live quote context\n"
                    "- **Tech** — TradingView technical signal (BUY/SELL/NEUTRAL)\n"
                    "- **Social** — Finnhub social sentiment (Reddit+Twitter icon + mention count)\n"
                    "- **Analyst** — Analyst consensus (upside %, rating)\n"
                    "- **P/E** — Price-to-Earnings ratio\n"
                    "- **Vol** — Trading volume"
                )

            st.dataframe(
                _df_act,
                width='stretch',
                height=min(800, 40 + 35 * len(_df_act)),
                column_config=_act_col_cfg,
            )

    # ── TAB: Segments ───────────────────────────────────────
    with tab_segments, _tab_guard("Segments"):
        st.header("🏗️ Segments")
        seg_rows = aggregate_segments(feed)

        # ── Sector Performance Plotly Chart (5-min TTL) ─────────────────
        _SECTOR_PERF_TTL = 300  # 5 minutes
        _seg_sector_perf: list[dict[str, Any]] = []
        _seg_sp_ts = st.session_state.get("_cached_sector_perf_ts", 0)
        if time.time() - _seg_sp_ts < _SECTOR_PERF_TTL:
            _seg_sector_perf = st.session_state.get("_cached_sector_perf") or []
        # (FMP sector performance removed — no Databento equivalent)

        if _seg_sector_perf:
            try:
                import plotly.express as px
                _sp_df = pd.DataFrame(_seg_sector_perf)
                _sp_df = _sp_df.rename(columns={"change_pct": "Change %"})
                _sp_df["Color"] = _sp_df["Change %"].apply(lambda x: "green" if x >= 0 else "red")
                _fig_sp = px.bar(
                    _sp_df, x="sector", y="Change %",
                    color="Color", color_discrete_map={"green": "#22c55e", "red": "#ef4444"},
                    title="📊 GICS Sector Performance (today)",
                )
                _fig_sp.update_layout(
                    showlegend=False, height=260, margin=dict(l=0, r=0, t=30, b=0),
                    xaxis_title=None, yaxis_title=None,
                    plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(_fig_sp, width='stretch', key="seg_sector_perf_chart")
            except Exception:
                # Fallback to metrics columns if plotly unavailable
                _sp_cols = st.columns(min(len(_seg_sector_perf), 6))
                for _sp_i, _sp in enumerate(_seg_sector_perf[:12]):
                    _sp_name = _sp.get("sector", "")
                    _sp_chg = _sp.get("change_pct", 0)
                    _sp_cols[_sp_i % len(_sp_cols)].metric(
                        _sp_name[:20],
                        f"{_sp_chg:+.2f}%",
                        delta=None,
                    )

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

            # Batch-fetch Databento quotes for all segment tickers
            _seg_all_tickers = list({
                (d.get("ticker") or "").upper().strip()
                for r in seg_rows
                for d in (r.get("_ticker_map") or {}).values()
                if (d.get("ticker") or "").upper().strip() not in ("", "?", "MARKET", "N/A")
            })
            _seg_fmp: dict[str, dict[str, Any]] = {}
            if _seg_all_tickers:
                try:
                    _seg_fmp = fetch_databento_quote_map(_seg_all_tickers[:200])
                except Exception:
                    logger.debug("Segments Databento quotes failed", exc_info=True)

            # Social sentiment — merge into shared cache (not overwrite)
            _seg_social: dict[str, Any] = st.session_state.get("_cached_social_sent") or {}
            _seg_social_missing = [t for t in _seg_all_tickers if t not in _seg_social]
            if _seg_social_missing and _intel_enabled() and finnhub_available():
                try:
                    _raw_seg_soc = fetch_social_sentiment_batch(_seg_social_missing[:15])
                    if _raw_seg_soc:
                        _new_seg_social = {
                            sym: {"total_mentions": s.total_mentions, "score": s.score, "label": s.sentiment_label}
                            for sym, s in _raw_seg_soc.items()
                        }
                        _seg_social = {**_seg_social, **_new_seg_social}
                        st.session_state["_cached_social_sent"] = _seg_social
                        st.session_state["_cached_social_sent_ts"] = time.time()
                except Exception:
                    logger.debug("Segments social sentiment failed", exc_info=True)

            # Analyst forecasts — merge into shared cache (not overwrite)
            _seg_forecasts: dict[str, Any] = st.session_state.get("_cached_forecasts") or {}
            _seg_fc_missing = [t for t in _seg_all_tickers[:10] if t not in _seg_forecasts]
            if _seg_fc_missing and _intel_enabled():
                try:
                    for _sym in _seg_fc_missing:
                        _fc = fetch_forecast(_sym)
                        if _fc.has_data and _fc.price_target:
                            _seg_forecasts[_sym] = {
                                "price_target": {
                                    "target_mean": _fc.price_target.target_mean,
                                    "upside_pct": round(_fc.price_target.upside_pct, 1),
                                },
                                "rating": {
                                    "consensus": _fc.rating.consensus if _fc.rating else "",
                                },
                            }
                    if _seg_forecasts:
                        st.session_state["_cached_forecasts"] = _seg_forecasts
                        st.session_state["_cached_forecasts_ts"] = time.time()
                except Exception:
                    logger.debug("Segments forecasts failed", exc_info=True)

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
                        _tk_sym = (d.get("ticker") or "?").upper()
                        sent_label = d.get("sentiment_label", "neutral")
                        raw_headline = (d.get("headline", "") or "")[:120]
                        article_url = d.get("url", "")
                        headline_display = (
                            f"[{raw_headline}]({article_url})"
                            if article_url
                            else raw_headline
                        )

                        # Databento quote enrichment
                        _sfq = _seg_fmp.get(_tk_sym, {})
                        _sfq_price = _sfq.get("price") or 0
                        _sfq_chg = _sfq.get("changesPercentage") or _sfq.get("change_pct") or 0
                        _sfq_pe = _sfq.get("pe")

                        # Social sentiment
                        _ss = _seg_social.get(_tk_sym, {})
                        _ss_label = _ss.get("label", "")
                        _ss_mentions = _ss.get("total_mentions", 0)
                        _social_col = ""
                        if _ss_label:
                            _soc_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(_ss_label, "⚪")
                            _social_col = f"{_soc_icon} {_ss_mentions}"

                        # Analyst consensus
                        _saf = _seg_forecasts.get(_tk_sym, {})
                        _saf_pt = _saf.get("price_target", {})
                        _analyst_col = ""
                        if _saf_pt.get("upside_pct") is not None:
                            _up = _saf_pt["upside_pct"]
                            _up_icon = "🟢" if _up > 10 else "🔴" if _up < -10 else "🟡"
                            _analyst_col = f"{_up_icon} {_up:+.0f}%"

                        tk_rows.append({
                            "Symbol": _tk_sym,
                            "Price": f"${_sfq_price:.2f}" if _sfq_price >= 1 else ("—" if _sfq_price == 0 else f"${_sfq_price:.4f}"),
                            "Chg%": f"{_sfq_chg:+.2f}%" if _sfq_chg else "—",
                            "Score": round(d.get("news_score", 0), 4),
                            "Sentiment": _SENTIMENT_COLORS.get(sent_label, "🟡") + " " + sent_label,
                            "Tech": _get_tech_summary(_tk_sym),
                            "Social": _social_col,
                            "Analyst": _analyst_col,
                            "P/E": f"{_sfq_pe:.1f}" if _sfq_pe and _sfq_pe > 0 else "—",
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
                                "Symbol": st.column_config.TextColumn("Symbol", width="small"),
                                "Price": st.column_config.TextColumn("Price", width="small"),
                                "Chg%": st.column_config.TextColumn("Chg%", width="small"),
                                "Tech": st.column_config.TextColumn("Tech", width="small"),
                                "Social": st.column_config.TextColumn("Social", width="small"),
                                "Analyst": st.column_config.TextColumn("Analyst", width="small"),
                                "P/E": st.column_config.TextColumn("P/E", width="small"),
                                "Headline": st.column_config.LinkColumn(
                                    "Headline",
                                    display_text=r"(.*)",
                                ),
                            },
                        )
                    else:
                        st.caption("No ticker data")

    # ── TAB: Outlook ────────────────────────────────────────
    with tab_outlook, _tab_guard("Outlook"):
        st.header("🔮 Outlook")

        bz_key = cfg.benzinga_api_key
        fmp_key = ""  # FMP removed — outlook uses Benzinga + yfinance fallback

        if not bz_key:
            st.warning("Configure Benzinga API key to compute the outlook.")
        else:
            _today_iso = datetime.now(UTC).strftime("%Y-%m-%d")

            # Fetch both outlooks (cached — 5 min TTL)
            today_outlook = _cached_today_outlook(bz_key, fmp_key, _cache_buster=_today_iso)
            outlook = _cached_tomorrow_outlook(bz_key, fmp_key, _cache_buster=_today_iso)

            # Compute live feed sentiment (shared between both sections)
            _feed_for_outlook = feed[-200:] if feed else []
            _feed_sentiment_items = list((st.session_state.get("ticker_catalyst_state") or {}).values())
            if not _feed_sentiment_items and _feed_for_outlook:
                _feed_sentiment_items = dedup_feed_items(_feed_for_outlook)
            if _feed_sentiment_items:
                _bear_c = sum(
                    1 for it in _feed_sentiment_items
                    if effective_catalyst_sentiment(it) == "bearish"
                )
                _bull_c = sum(
                    1 for it in _feed_sentiment_items
                    if effective_catalyst_sentiment(it) == "bullish"
                )
                _total_f = len(_feed_sentiment_items)
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

            # ────────────────────────────────────────────────
            # ── TODAY'S OUTLOOK ──
            # ────────────────────────────────────────────────
            if today_outlook:
                _to_label = today_outlook.get("outlook_label", "🟡 NEUTRAL")
                _to_color = today_outlook.get("outlook_color", "orange")
                _to_date = today_outlook.get("target_date", _today_iso)

                st.markdown(
                    f"<div style='padding:0.7rem 1.2rem;border-radius:0.6rem;"
                    f"background:{_to_color};color:white;font-weight:700;"
                    f"font-size:1.2rem;text-align:center;margin-bottom:0.8rem'>"
                    f"TODAY  {_to_label} — {_to_date}</div>",
                    unsafe_allow_html=True,
                )

                if _to_label != "⚪ MARKET CLOSED":
                    _to_cols = st.columns(5)
                    _to_cols[0].metric("Outlook Score", f"{today_outlook.get('outlook_score', 0):.2f}")
                    _to_cols[1].metric("Earnings Today", today_outlook.get("earnings_count", 0))
                    _to_cols[2].metric("Earnings BMO", today_outlook.get("earnings_bmo_count", 0))
                    _to_cols[3].metric("High-Impact Events", today_outlook.get("high_impact_events", 0))
                    _to_cols[4].metric("Feed Sentiment", _feed_sentiment_label)

                    # High-impact events for today
                    _to_hi: list[dict[str, Any]] = today_outlook.get("high_impact_events_details") or []
                    if _to_hi:
                        with st.expander(f"📋 Today's High-Impact Events ({len(_to_hi)})", expanded=False):
                            for _ev in _to_hi:
                                _ev_n = safe_markdown_text(str(_ev.get("event", "—")))
                                _ev_c = safe_markdown_text(str(_ev.get("country", "US")))
                                _ev_s = safe_markdown_text(str(_ev.get("source", "")))
                                st.markdown(f"- **{_ev_n}** ({_ev_c}) — {_ev_s}")

                    # Notable earnings today
                    _to_earn = today_outlook.get("notable_earnings") or []
                    if _to_earn:
                        with st.expander(f"📊 Earnings Reporting Today ({len(_to_earn)})", expanded=False):
                            _to_df = pd.DataFrame(_to_earn)
                            _to_disp = [c for c in ["ticker", "name", "timing"] if c in _to_df.columns]
                            st.dataframe(
                                _to_df[_to_disp] if _to_disp else _to_df,
                                width='stretch',
                                height=min(300, 40 + 35 * len(_to_df)),
                            )

                    # Today factors & mood
                    _to_reasons = today_outlook.get("reasons") or []
                    _to_mood = today_outlook.get("sector_mood", "neutral")
                    _to_mood_e = {"risk-on": "🟢", "risk-off": "🔴", "neutral": "🟡"}.get(_to_mood, "⚪")
                    st.caption(
                        f"**Factors:** {' · '.join(_to_reasons)}  ·  "
                        f"**Sector Mood:** {_to_mood_e} {_to_mood.title()}"
                    )

                st.divider()

            # ────────────────────────────────────────────────
            # ── TOMORROW'S OUTLOOK ──
            # ────────────────────────────────────────────────
            o_label = outlook.get("outlook_label", "🟡 NEUTRAL")
            o_color = outlook.get("outlook_color", "orange")
            next_td_str = outlook.get("next_trading_day", "—")

            st.markdown(
                f"<div style='padding:0.7rem 1.2rem;border-radius:0.6rem;"
                f"background:{o_color};color:white;font-weight:700;"
                f"font-size:1.2rem;text-align:center;margin-bottom:0.8rem'>"
                f"NEXT TRADING DAY  {o_label} — {next_td_str}</div>",
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

            # (Trending Themes section removed — NewsAPI.ai no longer available)

    # ── TAB: AI Insights (multi-layer enriched) ─────────────────
    with tab_ai:
        st.markdown('<div id="ai-insights"></div>', unsafe_allow_html=True)
        if _intel_enabled():
            from terminal_tabs.tab_fmp_ai import render as render_fmp_ai
            _safe_tab("AI Insights", render_fmp_ai, feed, current_session=_current_session)
        else:
            st.info("⚡ Low-latency mode: AI Insights are disabled. Enable optional intelligence modules in the sidebar.")

    # ── TAB: Bitcoin ────────────────────────────────────────
    with tab_bitcoin, _tab_guard("Bitcoin"):
        st.header("₿ Bitcoin Dashboard")
        st.caption("🟢 Market: 24/7 — always open")

        if not btc_available():
            st.warning("No data sources available. Install yfinance / tradingview_ta.")
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
                st.info("Fear & Greed data not available.")

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
                        st.markdown(f"- {_sent_icon} [{safe_markdown_text(_art_title[:120])}]({safe_url(_art_url)}){_source_str}{_date_str}")
                    else:
                        st.markdown(f"- {_sent_icon} {safe_markdown_text(_art_title[:120])}{_source_str}{_date_str}")
                    if _btc_art.get("text"):
                        st.caption(f"  {_btc_art['text'][:200]}...")
            else:
                st.info("No Bitcoin news available.")

            # (NewsAPI.ai Bitcoin breaking events removed)

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
                    st.info("No listing data available.")

    # ── TAB: Alerts ─────────────────────────────────────────
    with tab_alerts, _tab_guard("Alerts"):
        st.header("⚡ Alert Log")

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

        # ── TradingView Health Log ───────────────────────
        st.divider()
        st.subheader("📺 TradingView Health")
        _tv_h = tv_health_status()
        _tv_status_icon = {"healthy": "🟢", "degraded": "⚡", "down": "🔴"}.get(_tv_h["status"], "⚪")
        _tv_uptime = _tv_h.get("uptime_pct", 0)
        st.markdown(
            f"{_tv_status_icon} **Status: {_tv_h['status'].upper()}** "
            f"· Uptime: {_tv_uptime:.0f}% "
            f"· Requests: {_tv_h.get('total_requests', 0)} "
            f"· Failures: {_tv_h.get('consecutive_failures', 0)} consecutive"
        )
        if _tv_h.get("last_error"):
            st.caption(f"Last error: {_tv_h['last_error']}")

        _tv_hlog = st.session_state.tv_health_log
        if _tv_hlog:
            st.caption(f"{len(_tv_hlog)} state transition(s)")
            for _tl in _tv_hlog[:10]:
                _tl_ts = datetime.fromtimestamp(_tl["ts"], tz=UTC).strftime("%H:%M:%S")
                _tl_icon = {"healthy": "🟢", "degraded": "⚡", "down": "🔴"}.get(_tl["status"], "⚪")
                _tl_err = f" — {_tl['error']}" if _tl.get("error") else ""
                st.markdown(
                    f"{_tl_icon} `{_tl_ts}` {_tl['prev']} → **{_tl['status']}**{_tl_err}"
                )
        else:
            st.caption("No TV health transitions recorded.")

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
    with tab_table, _tab_guard("Data Table"):
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

if st.session_state.auto_refresh and _has_live_news_provider(
    st.session_state.cfg,
    st.session_state.feed,
):
    # Use st.fragment with run_every for non-blocking auto-refresh.
    # We compare the poller's poll_count against a snapshot we take
    # *after* each successful rerun trigger, so empty/repeat polls
    # that don't advance the counter don't re-trigger needlessly.
    _REFRESH_COOLDOWN_S = 6.0  # min seconds between full-page reruns

    @st.fragment(run_every=timedelta(seconds=5))
    def _auto_refresh_fragment() -> None:
        """Non-blocking auto-refresh fragment."""
        # ── Check if background AI analysis completed ──────────
        # The analysis runs in a daemon thread (ThreadPoolExecutor).
        # When done, trigger a full-page rerun so the render function
        # can harvest the result from the Future.
        _ai_future = st.session_state.get("_fmp_ai_future")
        if _ai_future is not None and _ai_future.done():
            try:
                st.session_state["fmp_ai_last_result"] = _ai_future.result()
            except Exception as _ai_exc:
                logger.warning("AI background task failed", exc_info=True)
                st.session_state["fmp_ai_last_result"] = {
                    "error": f"Background analysis failed: {_ai_exc}",
                    "question": st.session_state.get("fmp_ai_selected_question", ""),
                    "answer": "",
                    "model": "",
                    "cached": False,
                    "context_articles": 0,
                    "context_tickers": 0,
                    "fmp_tickers": 0,
                    "enrichment_layers": 0,
                }
            finally:
                st.session_state["_fmp_ai_executing"] = False
                st.session_state.pop("_fmp_ai_future", None)
                st.session_state.pop("_fmp_ai_submit_ts", None)
            st.session_state["_last_fragment_rerun_ts"] = time.time()
            st.rerun()

        # Safety: detect stale AI execution (worker hung > 180s)
        if st.session_state.get("_fmp_ai_executing", False):
            _submit_ts = st.session_state.get("_fmp_ai_submit_ts", 0)
            if _submit_ts and time.time() - _submit_ts > 180:
                logger.warning("Fragment: FMP AI worker stale (>180s) — force-resetting")
                if _ai_future is not None:
                    _ai_future.cancel()
                st.session_state["_fmp_ai_executing"] = False
                st.session_state.pop("_fmp_ai_future", None)
                st.session_state.pop("_fmp_ai_submit_ts", None)
                st.session_state["fmp_ai_last_result"] = {
                    "error": "Analysis timed out (>180s). The worker may have hung on a slow API call. Please try again.",
                    "question": st.session_state.get("fmp_ai_selected_question", ""),
                    "answer": "", "model": "", "cached": False,
                    "context_articles": 0, "context_tickers": 0, "fmp_tickers": 0, "enrichment_layers": 0,
                }
                st.session_state["_last_fragment_rerun_ts"] = time.time()
                st.rerun()

        if st.session_state.get("fmp_ai_pause_auto_refresh", False):
            return
        # Suppress while background AI thread is running — avoid
        # unnecessary full-page reruns that could confuse the user.
        if st.session_state.get("_fmp_ai_executing", False):
            return

        # Cooldown: skip if we triggered a full rerun very recently
        _now = time.time()
        _last_frag_rerun = st.session_state.get("_last_fragment_rerun_ts", 0.0)
        if _now - _last_frag_rerun < _REFRESH_COOLDOWN_S:
            return

        _need_rerun = False
        _bp_frag = st.session_state.get("bg_poller")
        if _bp_frag is not None:
            # Only rerun when the poller has completed a NEW poll (count advanced)
            # Use a dedicated snapshot key to avoid racing the main-script sync.
            _known = st.session_state.get("_frag_known_poll_count", 0)
            if _bp_frag.poll_count > _known:
                _need_rerun = True
        elif st.session_state.get("auto_refresh") and _should_poll(_effective_interval):
            _need_rerun = True

        if _need_rerun:
            # Snapshot the count we just observed so the next fragment
            # invocation won't immediately re-trigger.
            if _bp_frag is not None:
                st.session_state["_frag_known_poll_count"] = _bp_frag.poll_count
            st.session_state["_last_fragment_rerun_ts"] = _now
            st.rerun()

    _auto_refresh_fragment()
