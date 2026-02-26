"""Bloomberg Terminal — Real-Time News Intelligence Dashboard.

Run with::

    streamlit run streamlit_terminal.py

Requires ``BENZINGA_API_KEY`` in ``.env`` or environment.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    append_jsonl, fire_webhook, load_rt_quotes, rotate_jsonl, save_vd_snapshot,
)
from terminal_poller import ClassifiedItem, TerminalConfig, poll_and_classify

logger = logging.getLogger(__name__)

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
    st.session_state.feed: list[dict[str, Any]] = []
if "poll_count" not in st.session_state:
    st.session_state.poll_count = 0
if "last_poll_ts" not in st.session_state:
    st.session_state.last_poll_ts = 0.0
if "adapter" not in st.session_state:
    st.session_state.adapter = None
if "store" not in st.session_state:
    st.session_state.store = None
if "total_items_ingested" not in st.session_state:
    st.session_state.total_items_ingested = 0
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = True
if "last_poll_status" not in st.session_state:
    st.session_state.last_poll_status = "—"
if "last_poll_error" not in st.session_state:
    st.session_state.last_poll_error = ""


def _get_adapter() -> BenzingaRestAdapter | None:
    """Lazy-init the REST adapter."""
    cfg: TerminalConfig = st.session_state.cfg
    if not cfg.benzinga_api_key:
        return None
    if st.session_state.adapter is None:
        st.session_state.adapter = BenzingaRestAdapter(cfg.benzinga_api_key)
    return st.session_state.adapter


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
        st.success(f"API Key: …{cfg.benzinga_api_key[-4:]}")
    else:
        st.error("No BENZINGA_API_KEY found in .env")
        st.info("Set `BENZINGA_API_KEY=your_key` in `.env` and restart.")

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
    force_poll = st.button("🔄 Poll Now", width="stretch")

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

    # Reset dedup DB (clears mark_seen so next poll re-ingests)
    if st.button("🗑️ Reset dedup DB", width="stretch"):
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


# ── Poll logic ──────────────────────────────────────────────────

def _should_poll() -> bool:
    """Determine if we should poll this cycle."""
    if not st.session_state.cfg.benzinga_api_key:
        return False
    elapsed = time.time() - st.session_state.last_poll_ts
    return elapsed >= interval


def _do_poll() -> None:
    """Execute one poll cycle."""
    adapter = _get_adapter()
    if adapter is None:
        return

    store = _get_store()
    cfg: TerminalConfig = st.session_state.cfg

    try:
        items, new_cursor = poll_and_classify(
            adapter=adapter,
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
    st.session_state.last_poll_status = f"{len(items)} items (cursor={new_cursor})"

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
        st.toast(f"📡 {len(items)} new item(s)", icon="✅")


# ── Execute poll if needed ──────────────────────────────────────

if force_poll or (st.session_state.auto_refresh and _should_poll()):
    _do_poll()


# ── Main display ────────────────────────────────────────────────

st.title("📡 News Terminal")

if not st.session_state.cfg.benzinga_api_key:
    st.warning("Set `BENZINGA_API_KEY` in `.env` to start polling.")
    st.stop()

feed = st.session_state.feed

if not feed:
    st.info("No items yet. Waiting for first poll…")
else:
    # ── Stats bar ───────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    unique_tickers = len(set(d["ticker"] for d in feed if d.get("ticker") != "MARKET"))
    actionable = sum(1 for d in feed if d.get("is_actionable"))
    high_mat = sum(1 for d in feed if d.get("materiality") == "HIGH")

    col1.metric("Feed items", len(feed))
    col2.metric("Unique tickers", unique_tickers)
    col3.metric("Actionable", actionable)
    col4.metric("HIGH materiality", high_mat)

    st.divider()

    # ── Tabs ────────────────────────────────────────────────
    tab_feed, tab_movers, tab_rank, tab_segments, tab_table = st.tabs(
        ["📰 Live Feed", "🔥 Top Movers", "🏆 Rankings", "🏗️ Segments", "📊 Data Table"],
    )

    with tab_feed:
        # Show latest items with classification badges
        for d in feed[:50]:
            sent_icon = _SENTIMENT_COLORS.get(d.get("sentiment_label", ""), "")
            mat_icon = _MATERIALITY_COLORS.get(d.get("materiality", ""), "")
            rec_icon = _RECENCY_COLORS.get(d.get("recency_bucket", ""), "")

            ticker = d.get("ticker", "?")
            score = d.get("news_score", 0)
            category = d.get("category", "other")
            headline = d.get("headline", "")
            event_label = d.get("event_label", "")
            source_tier = d.get("source_tier", "")
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

            with st.container():
                cols = st.columns([1, 6, 1, 1, 1])
                with cols[0]:
                    st.markdown(f"**{ticker}**")
                with cols[1]:
                    link = f"[{headline[:120]}]({url})" if url else headline[:120]
                    st.markdown(f"{sent_icon} {link}")
                with cols[2]:
                    st.markdown(f"`{category}`")
                with cols[3]:
                    st.markdown(score_badge)
                with cols[4]:
                    st.markdown(f"{rec_icon} {age_str}")

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

                with st.container():
                    c1, c2 = st.columns([2, 8])
                    with c1:
                        st.markdown(f"### {ticker}")
                        st.markdown(f"{sent_icon} {sentiment} | {mat_icon} {materiality}")
                        st.markdown(f"Score: **{score:.3f}** | {event_label} | {source_tier}")
                    with c2:
                        st.markdown(f"**{headline[:200]}**")
                        channels = ", ".join(d.get("channels", [])[:5])
                        tags = ", ".join(d.get("tags", [])[:5])
                        if channels:
                            st.caption(f"Channels: {channels}")
                        if tags:
                            st.caption(f"Tags: {tags}")
                    st.divider()

    with tab_rank:
        import pandas as pd
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
                width="stretch",
                height=min(600, 40 + 35 * len(df_rank)),
            )

    with tab_segments:
        import pandas as pd
        from collections import defaultdict

        # ── Build segment map from Benzinga channels ──────────────
        # Each article can belong to multiple channels (= industry segments).
        # We aggregate: best score, article count, sentiment, top tickers.
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
                # Unique tickers in this segment
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
                # Net sentiment: +1 per bullish, -1 per bearish
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
                    "_ticker_map": tickers_in_seg,  # for drill-down
                })

            # Sort by article count (most active segments first)
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
            st.dataframe(df_seg, width="stretch", height=min(400, 40 + 35 * len(df_seg)))

            st.divider()

            # ── Per-segment drill-down: top 10 symbols ──────────────
            # Show 3-column layout for leading / neutral / lagging
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

            # ── Detailed drill-down per segment (top 10 symbols each) ──
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
                        st.dataframe(df_tk, width="stretch", height=min(400, 40 + 35 * len(df_tk)))
                    else:
                        st.caption("No ticker data")

    with tab_table:
        import pandas as pd

        if feed:
            display_cols = [
                "ticker", "headline", "news_score", "sentiment_label",
                "category", "event_label", "materiality",
                "recency_bucket", "age_minutes", "source_tier",
                "novelty_count", "impact", "polarity",
            ]
            df = pd.DataFrame(feed)
            # Only show columns that exist
            show_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[show_cols],
                width="stretch",
                height=600,
            )
        else:
            st.info("No data yet.")


# ── Auto-refresh trigger ───────────────────────────────────────

if st.session_state.auto_refresh and st.session_state.cfg.benzinga_api_key:
    time.sleep(interval)
    st.rerun()
