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
from collections import defaultdict
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
        pass


_load_env_file(PROJECT_ROOT / ".env")

from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter
from newsstack_fmp.store_sqlite import SqliteStore
from terminal_export import (
    append_jsonl, fire_webhook, load_jsonl_feed, load_rt_quotes, rotate_jsonl, save_vd_snapshot,
)
from terminal_poller import (
    ClassifiedItem, TerminalConfig, poll_and_classify, poll_and_classify_multi,
    fetch_economic_calendar, fetch_sector_performance,
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

if "cfg" not in st.session_state:
    st.session_state.cfg = TerminalConfig()
if "cursor" not in st.session_state:
    st.session_state.cursor = None
if "feed" not in st.session_state:
    _restored = load_jsonl_feed(TerminalConfig().jsonl_path)
    st.session_state.feed = _restored  # type: list[dict[str, Any]]
    if _restored:
        # Derive cursor from restored feed so polling resumes from latest
        _ts_vals = [r.get("published", "") or r.get("created", "") for r in _restored]
        _ts_vals = [t for t in _ts_vals if t]
        if _ts_vals:
            st.session_state["cursor"] = max(_ts_vals)
if "poll_count" not in st.session_state:
    st.session_state.poll_count = 0
if "last_poll_ts" not in st.session_state:
    st.session_state.last_poll_ts = 0.0
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
            st.session_state.alert_rules = json.loads(_alert_path.read_text())
        except Exception:
            st.session_state.alert_rules = []
    else:
        st.session_state.alert_rules = []
if "alert_log" not in st.session_state:
    st.session_state.alert_log = []


def _get_adapter() -> BenzingaRestAdapter | None:
    """Lazy-init the REST adapter."""
    cfg: TerminalConfig = st.session_state.cfg
    if not cfg.benzinga_api_key:
        return None
    if st.session_state.adapter is None:
        st.session_state.adapter = BenzingaRestAdapter(cfg.benzinga_api_key)
    return st.session_state.adapter


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
    return st.session_state.store


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
    force_poll = st.button("🔄 Poll Now", use_container_width=True)

    st.divider()

    # Stats
    st.metric("Polls", st.session_state.poll_count)
    st.metric("Items in feed", len(st.session_state.feed))
    st.metric("Total ingested", st.session_state.total_items_ingested)
    if st.session_state.last_poll_ts:
        ago = time.time() - st.session_state.last_poll_ts
        st.caption(f"Last poll: {ago:.0f}s ago")

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
    if st.button("🗑️ Reset dedup DB", use_container_width=True):
        import pathlib
        db_path = pathlib.Path(cfg.sqlite_path)
        # Remove main DB + SQLite WAL/SHM journal files
        for suffix in ("", "-wal", "-shm"):
            p = pathlib.Path(str(db_path) + suffix)
            if p.exists():
                p.unlink()
        st.session_state.store = None
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
            if st.button("✕", key=f"del_rule_{i}"):
                st.session_state.alert_rules.pop(i)
                Path("artifacts/alert_rules.json").write_text(
                    json.dumps(st.session_state.alert_rules, indent=2),
                )
                st.rerun()

    st.divider()

    # Export paths
    st.caption(f"JSONL: `{cfg.jsonl_path}`")
    st.caption(f"VD snapshot: `artifacts/terminal_vd.jsonl`")
    st.caption(f"SQLite: `{cfg.sqlite_path}`")
    if cfg.webhook_url:
        st.caption(f"Webhook: `{cfg.webhook_url[:40]}…`")
    else:
        st.caption("Webhook: disabled")

    st.divider()

    # RT engine status
    _rt_path = "artifacts/open_prep/latest/latest_vd_signals.jsonl"
    _rt_quotes = load_rt_quotes(_rt_path)
    if _rt_quotes:
        st.success(f"RT Engine: {len(_rt_quotes)} symbols live")
    else:
        import os as _os
        if _os.path.isfile(_rt_path):
            st.warning("RT Engine: file exists but stale (>120s)")
        else:
            st.info("RT Engine: not running")


# ── Sentiment helpers ───────────────────────────────────────────

_SENTIMENT_COLORS = {
    "bullish": "🟢",
    "bearish": "🔴",
    "neutral": "🟡",
}

_MATERIALITY_COLORS = {
    "HIGH": "🔴",
    "MEDIUM": "🟠",
    "LOW": "⚪",
}

_RECENCY_COLORS = {
    "ULTRA_FRESH": "🔥",
    "FRESH": "🟢",
    "WARM": "🟡",
    "AGING": "🟠",
    "STALE": "⚫",
    "UNKNOWN": "❓",
}


# ── Alert evaluation ────────────────────────────────────────────

def _evaluate_alerts(items: list[ClassifiedItem]) -> None:
    """Check each new item against alert rules, fire webhooks + log."""
    import httpx as _httpx

    rules = st.session_state.alert_rules
    if not rules:
        return

    for ci in items:
        for rule in rules:
            tk_match = rule["ticker"] in ("*", ci.ticker)
            if not tk_match:
                continue

            cond = rule["condition"]
            fired = False

            if cond == "score >= threshold" and ci.news_score >= rule.get("threshold", 0.80):
                fired = True
            elif cond == "sentiment == bearish" and ci.sentiment_label == "bearish":
                fired = True
            elif cond == "sentiment == bullish" and ci.sentiment_label == "bullish":
                fired = True
            elif cond == "materiality == HIGH" and ci.materiality == "HIGH":
                fired = True
            elif cond == "category matches" and ci.category == rule.get("category", ""):
                fired = True

            if fired:
                log_entry = {
                    "ts": time.time(),
                    "ticker": ci.ticker,
                    "headline": ci.headline[:120],
                    "rule": cond,
                    "score": ci.news_score,
                }
                st.session_state.alert_log.insert(0, log_entry)
                # Cap alert log
                if len(st.session_state.alert_log) > 100:
                    st.session_state.alert_log = st.session_state.alert_log[:100]

                # Fire webhook if configured
                wh = rule.get("webhook_url", "")
                if wh:
                    try:
                        payload = json.dumps(log_entry, default=str).encode()
                        with _httpx.Client(timeout=5.0) as client:
                            client.post(wh, content=payload, headers={"Content-Type": "application/json"})
                    except Exception:
                        pass


# ── Poll logic ──────────────────────────────────────────────────

def _should_poll() -> bool:
    """Determine if we should poll this cycle."""
    cfg: TerminalConfig = st.session_state.cfg
    if not cfg.benzinga_api_key and not cfg.fmp_api_key:
        return False
    elapsed = time.time() - st.session_state.last_poll_ts
    return elapsed >= interval


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
        )
    except Exception as exc:
        logger.exception("Poll failed: %s", exc)
        st.session_state.last_poll_error = str(exc)
        st.session_state.last_poll_status = "ERROR"
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

    # Evaluate alert rules on new items
    _evaluate_alerts(items)

    # Append to feed (newest first) + cap at max_items
    for ci in items:
        d = ci.to_dict()
        st.session_state.feed.insert(0, d)

        # JSONL export
        if cfg.jsonl_path:
            append_jsonl(ci, cfg.jsonl_path)

        # Webhook
        if cfg.webhook_url:
            fire_webhook(ci, cfg.webhook_url, cfg.webhook_secret)

    # Trim feed
    max_items = cfg.max_items
    if len(st.session_state.feed) > max_items:
        st.session_state.feed = st.session_state.feed[:max_items]

    # Rotate JSONL periodically
    if cfg.jsonl_path and st.session_state.poll_count % 100 == 0:
        rotate_jsonl(cfg.jsonl_path)

    # Write per-symbol VisiData snapshot (atomic overwrite)
    save_vd_snapshot(st.session_state.feed)

    if items:
        st.toast(f"📡 {len(items)} new item(s) [{src_label}]", icon="✅")


# ── Execute poll if needed ──────────────────────────────────────

if force_poll or (st.session_state.auto_refresh and _should_poll()):
    _do_poll()


# ── Main display ────────────────────────────────────────────────

st.title("📡 News Terminal")

if not st.session_state.cfg.benzinga_api_key and not st.session_state.cfg.fmp_api_key:
    st.warning("Set `BENZINGA_API_KEY` and/or `FMP_API_KEY` in `.env` to start polling.")
    st.stop()

feed = st.session_state.feed

if not feed:
    st.info("No items yet. Waiting for first poll…")
else:
    # ── Stats bar ───────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    unique_tickers = len(set(d["ticker"] for d in feed if d.get("ticker") != "MARKET"))
    actionable = sum(1 for d in feed if d.get("is_actionable"))
    high_mat = sum(1 for d in feed if d.get("materiality") == "HIGH")
    avg_relevance = sum(d.get("relevance", 0) for d in feed) / max(1, len(feed))

    col1.metric("Feed items", len(feed))
    col2.metric("Unique tickers", unique_tickers)
    col3.metric("Actionable", actionable)
    col4.metric("HIGH materiality", high_mat)
    col5.metric("Avg relevance", f"{avg_relevance:.3f}")

    st.divider()

    # ── Tabs ────────────────────────────────────────────────
    tab_feed, tab_movers, tab_rank, tab_segments, tab_heatmap, tab_calendar, tab_alerts, tab_table = st.tabs(
        ["📰 Live Feed", "🔥 Top Movers", "🏆 Rankings", "🏗️ Segments",
         "🗺️ Heatmap", "📅 Calendar", "⚡ Alerts", "📊 Data Table"],
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
                "Category", ["all"] + sorted(set(d.get("category", "other") for d in feed)),
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

        # Apply filters
        filtered = feed
        if search_q:
            q_lower = search_q.lower()
            filtered = [
                d for d in filtered
                if q_lower in (d.get("headline", "") or "").lower()
                or q_lower in (d.get("ticker", "") or "").lower()
                or q_lower in (d.get("snippet", "") or "").lower()
            ]
        if filter_sentiment != "all":
            filtered = [d for d in filtered if d.get("sentiment_label") == filter_sentiment]
        if filter_category != "all":
            filtered = [d for d in filtered if d.get("category") == filter_category]

        # Date filter
        from_epoch = datetime.combine(date_from, datetime.min.time()).timestamp()
        to_epoch = datetime.combine(date_to, datetime.max.time()).timestamp()
        filtered = [
            d for d in filtered
            if from_epoch <= d.get("published_ts", 0) <= to_epoch
        ]

        st.caption(f"Showing {len(filtered)} of {len(feed)} items")

        # Show filtered items
        for d in filtered[:50]:
            sent_icon = _SENTIMENT_COLORS.get(d.get("sentiment_label", ""), "")
            mat_icon = _MATERIALITY_COLORS.get(d.get("materiality", ""), "")
            rec_icon = _RECENCY_COLORS.get(d.get("recency_bucket", ""), "")

            ticker = d.get("ticker", "?")
            score = d.get("news_score", 0)
            relevance = d.get("relevance", 0)
            category = d.get("category", "other")
            headline = d.get("headline", "")
            event_label = d.get("event_label", "")
            source_tier = d.get("source_tier", "")
            provider = d.get("provider", "")
            age_min = d.get("age_minutes")
            url = d.get("url", "")

            age_str = f"{age_min:.0f}m" if age_min is not None else "?"

            # Color the score
            if score >= 0.80:
                score_badge = f":red[**{score:.2f}**]"
            elif score >= 0.50:
                score_badge = f":orange[{score:.2f}]"
            else:
                score_badge = f"{score:.2f}"

            # Provider badge
            prov_icon = "🅱️" if "benzinga" in provider else ("📊" if "fmp" in provider else "")

            with st.container():
                cols = st.columns([1, 5, 1, 1, 1, 1])
                with cols[0]:
                    st.markdown(f"**{ticker}**")
                with cols[1]:
                    link = f"[{headline[:100]}]({url})" if url else headline[:100]
                    st.markdown(f"{sent_icon} {link}")
                with cols[2]:
                    st.markdown(f"`{category}`")
                with cols[3]:
                    st.markdown(score_badge)
                with cols[4]:
                    st.markdown(f"{rec_icon} {age_str}")
                with cols[5]:
                    st.markdown(f"{prov_icon} {event_label}")

    # ── TAB: Top Movers ─────────────────────────────────────
    with tab_movers:
        # Best-scored item per ticker in the last 30 minutes
        now_epoch = time.time()
        recent = [d for d in feed if (now_epoch - d.get("published_ts", 0)) < 1800]

        best_by_tk: dict[str, dict[str, Any]] = {}
        for d in recent:
            tk = d.get("ticker", "?")
            if tk == "MARKET":
                continue
            prev = best_by_tk.get(tk)
            if prev is None or d.get("news_score", 0) > prev.get("news_score", 0):
                best_by_tk[tk] = d

        if not best_by_tk:
            st.info("No movers in the last 30 minutes.")
        else:
            sorted_movers = sorted(
                best_by_tk.values(),
                key=lambda x: x.get("news_score", 0),
                reverse=True,
            )
            for d in sorted_movers[:20]:
                sent_icon = _SENTIMENT_COLORS.get(d.get("sentiment_label", ""), "")
                mat_icon = _MATERIALITY_COLORS.get(d.get("materiality", ""), "")
                ticker = d.get("ticker", "?")
                score = d.get("news_score", 0)
                headline = d.get("headline", "")
                event_label = d.get("event_label", "")
                materiality = d.get("materiality", "")
                sentiment = d.get("sentiment_label", "")
                source_tier = d.get("source_tier", "")
                relevance = d.get("relevance", 0)
                entity_count = d.get("entity_count", 0)

                with st.container():
                    c1, c2 = st.columns([2, 8])
                    with c1:
                        st.markdown(f"### {ticker}")
                        st.markdown(f"{sent_icon} {sentiment} | {mat_icon} {materiality}")
                        st.markdown(f"Score: **{score:.3f}** | Rel: {relevance:.2f}")
                        st.markdown(f"{event_label} | {source_tier} | 🏷️{entity_count}")
                    with c2:
                        st.markdown(f"**{headline[:200]}**")
                        channels = ", ".join(d.get("channels", [])[:5])
                        tags = ", ".join(d.get("tags", [])[:5])
                        if channels:
                            st.caption(f"Channels: {channels}")
                        if tags:
                            st.caption(f"Tags: {tags}")
                    st.divider()

    # ── TAB: Rankings ───────────────────────────────────────
    with tab_rank:
        from terminal_export import build_vd_snapshot, load_rt_quotes

        # Reuse the canonical build_vd_snapshot (includes RT merge)
        rt_quotes = load_rt_quotes()
        rank_rows = build_vd_snapshot(feed, rt_quotes=rt_quotes)

        if not rank_rows:
            st.info("No per-ticker data yet.")
        else:
            _MAT_MAP = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "⚪"}
            _REC_MAP = {
                "ULTRA_FRESH": "🔥", "FRESH": "🟢", "WARM": "🟡",
                "AGING": "🟠", "STALE": "⚫", "UNKNOWN": "❓",
            }

            # Enrich rows with display-friendly emoji prefixes
            for r in rank_rows:
                r["materiality"] = _MAT_MAP.get(r.get("materiality", ""), "") + " " + r.get("materiality", "")
                r["recency"] = _REC_MAP.get(r.get("recency", ""), "") + " " + r.get("recency", "")

            # Show top 20 ranked symbols
            top_n = min(20, len(rank_rows))
            df_rank = pd.DataFrame(rank_rows[:top_n])
            df_rank.index = df_rank.index + 1  # 1-based ranking

            rt_label = f" | RT: {len(rt_quotes)} symbols" if rt_quotes else ""
            st.caption(f"Top {top_n} of {len(rank_rows)} symbols ranked by best news_score — {len(feed)} total articles{rt_label}")
            st.dataframe(
                df_rank,
                use_container_width=True,
                height=min(600, 40 + 35 * len(df_rank)),
            )

    # ── TAB: Segments ───────────────────────────────────────
    with tab_segments:
        # ── Build segment map from Benzinga channels ──────────────
        _SKIP_CHANNELS = {"", "news", "general", "markets", "trading", "top stories"}

        seg_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for d in feed:
            tk = d.get("ticker", "?")
            if tk == "MARKET":
                continue
            chs = d.get("channels", [])
            if not chs:
                chs = [d.get("category", "other")]
            for ch in chs:
                ch_clean = ch.strip().title() if isinstance(ch, str) else str(ch)
                if ch_clean.lower() not in _SKIP_CHANNELS:
                    seg_items[ch_clean].append(d)

        if not seg_items:
            st.info("No segment data yet. Channels are populated by Benzinga articles.")
        else:
            # Aggregate per segment
            seg_rows: list[dict[str, Any]] = []
            for seg_name, items_list in seg_items.items():
                tickers_in_seg: dict[str, dict[str, Any]] = {}
                bull = bear = neut = 0
                total_score = 0.0
                for d in items_list:
                    tk = d.get("ticker", "?")
                    s = d.get("news_score", 0)
                    total_score += s
                    sent = d.get("sentiment_label", "neutral")
                    if sent == "bullish":
                        bull += 1
                    elif sent == "bearish":
                        bear += 1
                    else:
                        neut += 1
                    prev = tickers_in_seg.get(tk)
                    if prev is None or s > prev.get("news_score", 0):
                        tickers_in_seg[tk] = d

                n_articles = len(items_list)
                avg_score = total_score / n_articles if n_articles else 0
                net_sent = bull - bear
                sent_icon = "🟢" if net_sent > 0 else ("🔴" if net_sent < 0 else "🟡")

                seg_rows.append({
                    "segment": seg_name,
                    "articles": n_articles,
                    "tickers": len(tickers_in_seg),
                    "avg_score": round(avg_score, 4),
                    "sentiment": sent_icon,
                    "bull": bull,
                    "bear": bear,
                    "neut": neut,
                    "net_sent": net_sent,
                    "_ticker_map": tickers_in_seg,
                })

            seg_rows.sort(key=lambda r: r["articles"], reverse=True)

            # ── Overview table ──────────────────────────────────────
            summary_data = [{
                "Segment": r["segment"],
                "Articles": r["articles"],
                "Tickers": r["tickers"],
                "Avg Score": r["avg_score"],
                "Sentiment": r["sentiment"],
                "🟢": r["bull"],
                "🔴": r["bear"],
                "🟡": r["neut"],
            } for r in seg_rows]

            st.caption(f"{len(seg_rows)} segments across {len(feed)} articles")
            df_seg = pd.DataFrame(summary_data)
            df_seg.index = df_seg.index + 1
            st.dataframe(df_seg, use_container_width=True, height=min(400, 40 + 35 * len(df_seg)))

            st.divider()

            # ── Per-segment drill-down ──────────────────────────────
            leading = [r for r in seg_rows if r["net_sent"] > 0]
            lagging = [r for r in seg_rows if r["net_sent"] < 0]
            neutral_segs = [r for r in seg_rows if r["net_sent"] == 0]

            scols = st.columns(3)
            with scols[0]:
                st.markdown("**🟢 Bullish Segments**")
                if not leading:
                    st.caption("None")
                for r in leading[:8]:
                    st.markdown(f"**{r['segment']}** — {r['articles']} articles, avg {r['avg_score']:.3f}")
            with scols[1]:
                st.markdown("**🟡 Neutral Segments**")
                if not neutral_segs:
                    st.caption("None")
                for r in neutral_segs[:8]:
                    st.markdown(f"{r['segment']} — {r['articles']} articles, avg {r['avg_score']:.3f}")
            with scols[2]:
                st.markdown("**🔴 Bearish Segments**")
                if not lagging:
                    st.caption("None")
                for r in lagging[:8]:
                    st.markdown(f"**{r['segment']}** — {r['articles']} articles, avg {r['avg_score']:.3f}")

            st.divider()

            # ── Detailed drill-down per segment (top 10 symbols each)
            st.subheader("Top 10 Symbols per Segment")
            for r in seg_rows:
                ticker_map = r["_ticker_map"]
                sorted_tks = sorted(
                    ticker_map.values(),
                    key=lambda x: x.get("news_score", 0),
                    reverse=True,
                )[:10]

                with st.expander(f"{r['sentiment']} **{r['segment']}** — {r['tickers']} tickers, {r['articles']} articles"):
                    tk_rows = []
                    for d in sorted_tks:
                        sent_label = d.get("sentiment_label", "neutral")
                        tk_rows.append({
                            "Symbol": d.get("ticker", "?"),
                            "Score": round(d.get("news_score", 0), 4),
                            "Sentiment": _SENTIMENT_COLORS.get(sent_label, "🟡") + " " + sent_label,
                            "Event": d.get("event_label", ""),
                            "Materiality": d.get("materiality", ""),
                            "Headline": (d.get("headline", "") or "")[:100],
                        })
                    if tk_rows:
                        df_tk = pd.DataFrame(tk_rows)
                        df_tk.index = df_tk.index + 1
                        st.dataframe(df_tk, use_container_width=True, height=min(400, 40 + 35 * len(df_tk)))
                    else:
                        st.caption("No ticker data")

    # ── TAB: Sector Heatmap (treemap) ───────────────────────
    with tab_heatmap:
        try:
            import plotly.express as px  # type: ignore

            # Build treemap data from segment rows
            hm_data: list[dict[str, Any]] = []

            # If we have segment data from the Segments tab computation, reuse it
            # Otherwise recompute from feed
            _seg_data: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for d in feed:
                tk = d.get("ticker", "?")
                if tk == "MARKET":
                    continue
                chs = d.get("channels", [])
                if not chs:
                    chs = [d.get("category", "other")]
                for ch in chs:
                    ch_clean = ch.strip().title() if isinstance(ch, str) else str(ch)
                    skip = {"", "news", "general", "markets", "trading", "top stories"}
                    if ch_clean.lower() not in skip:
                        _seg_data[ch_clean].append(d)

            for seg_name, items_list in _seg_data.items():
                tickers_seen: dict[str, dict[str, Any]] = {}
                bull_count = bear_count = 0
                for d in items_list:
                    tk = d.get("ticker", "?")
                    s = d.get("news_score", 0)
                    sent = d.get("sentiment_label", "neutral")
                    if sent == "bullish":
                        bull_count += 1
                    elif sent == "bearish":
                        bear_count += 1
                    prev = tickers_seen.get(tk)
                    if prev is None or s > prev.get("news_score", 0):
                        tickers_seen[tk] = d

                # For treemap: each ticker is a leaf under its segment
                for tk, d in tickers_seen.items():
                    net = bull_count - bear_count
                    hm_data.append({
                        "sector": seg_name,
                        "ticker": tk,
                        "score": d.get("news_score", 0),
                        "sentiment": d.get("sentiment_label", "neutral"),
                        "net_sent": net,
                        "articles": len([x for x in items_list if x.get("ticker") == tk]),
                    })

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
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No segment data available for heatmap.")

            # ── FMP Sector Performance ──────────────────────────────
            fmp_key = st.session_state.cfg.fmp_api_key
            if fmp_key:
                st.subheader("📊 Market Sector Performance (FMP)")
                sector_data = fetch_sector_performance(fmp_key)
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
                        st.plotly_chart(fig_sp, use_container_width=True)
                    else:
                        st.dataframe(df_sp, use_container_width=True)
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

            cal_data = fetch_economic_calendar(
                fmp_key,
                from_date=cal_from.strftime("%Y-%m-%d"),
                to_date=cal_to.strftime("%Y-%m-%d"),
            )

            if cal_data:
                df_cal = pd.DataFrame(cal_data)

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
                    use_container_width=True,
                    height=min(600, 40 + 35 * len(df_cal)),
                )

                # ── Upcoming highlights ─────────────────────────────
                now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
                upcoming = df_cal[df_cal.get("date", pd.Series(dtype=str)) >= now_str] if "date" in df_cal.columns else pd.DataFrame()
                if not upcoming.empty:
                    st.subheader("⏰ Upcoming")
                    for _, row in upcoming.head(10).iterrows():
                        impact = row.get("impact", "")
                        impact_icon = "🔴" if impact == "High" else ("🟠" if impact == "Medium" else "🟡")
                        st.markdown(
                            f"{impact_icon} **{row.get('event', '?')}** — "
                            f"{row.get('country', '?')} | {row.get('date', '?')} | "
                            f"Prev: {row.get('previous', '?')} | Cons: {row.get('consensus', '?')}"
                        )
            else:
                st.info("No calendar events found for the selected range.")

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
            st.dataframe(rule_df, use_container_width=True)
        else:
            st.info("No alert rules configured. Add rules in the sidebar ➡️")

        st.divider()

        if alert_log:
            st.caption(f"{len(alert_log)} alert(s) fired")
            for entry in alert_log[:20]:
                ts = datetime.fromtimestamp(entry["ts"], tz=UTC).strftime("%H:%M:%S")
                st.markdown(
                    f"⚡ `{ts}` **{entry['ticker']}** — "
                    f"{entry['headline'][:80]} | Rule: {entry['rule']} | Score: {entry['score']:.3f}"
                )
        else:
            st.caption("No alerts fired yet.")

    # ── TAB: Data Table ─────────────────────────────────────
    with tab_table:
        if feed:
            display_cols = [
                "ticker", "headline", "news_score", "relevance",
                "sentiment_label", "category", "event_label", "materiality",
                "recency_bucket", "age_minutes", "source_tier", "provider",
                "entity_count", "novelty_count", "impact", "polarity",
            ]
            df = pd.DataFrame(feed)
            # Only show columns that exist
            show_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[show_cols],
                use_container_width=True,
                height=600,
            )
        else:
            st.info("No data yet.")


# ── Auto-refresh trigger ───────────────────────────────────────

if st.session_state.auto_refresh and st.session_state.cfg.benzinga_api_key:
    time.sleep(interval)
    st.rerun()
