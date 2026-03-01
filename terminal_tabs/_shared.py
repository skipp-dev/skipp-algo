"""Shared helpers for terminal tab modules.

Contains:
- Cached FMP/Benzinga data wrappers (``@st.cache_data``)
- Shared UI render helpers (technicals, forecasts, event clusters)
- Unified mover/ranking data builder
- Segment article renderer
- Common utilities
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import streamlit as st

from terminal_forecast import (
    fetch_forecast,
)
from terminal_newsapi import (
    fetch_event_clusters,
    is_available as newsapi_available,
)
from terminal_poller import (
    fetch_benzinga_delayed_quotes,
    fetch_benzinga_market_movers,
    fetch_defense_watchlist,
    fetch_economic_calendar,
    fetch_industry_performance,
    fetch_sector_performance,
    fetch_ticker_sectors,
    compute_tomorrow_outlook,
)
from terminal_spike_detector import SpikeDetector
from terminal_spike_scanner import (
    _YF_AVAILABLE,
    _yf_screen_movers,
    enrich_with_batch_quote,
    fetch_gainers,
    fetch_losers,
    fetch_most_active,
)
from terminal_technicals import (
    fetch_technicals,
    signal_icon,
    signal_label,
    INTERVAL_MAP,
)
from terminal_ui_helpers import (
    format_age_string,
    safe_markdown_text,
)
from newsstack_fmp._bz_http import _WARNED_ENDPOINTS

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Common utilities
# ═══════════════════════════════════════════════════════════════

def safe_float(val: Any, default: float = 0.0) -> float:
    """Safe float conversion for mover/quote data."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def bz_tier_warning(label: str, fallback: str) -> None:
    """Show tier-limited warning if endpoint is known-blocked, else info."""
    if label in _WARNED_ENDPOINTS:
        st.warning(f"⚠️ {label} – endpoint not available on your API plan.")
    else:
        st.info(fallback)


# ═══════════════════════════════════════════════════════════════
# Cached data wrappers (avoid re-fetching every Streamlit rerun)
# ═══════════════════════════════════════════════════════════════

@st.cache_data(ttl=60, show_spinner=False)
def cached_sector_perf(api_key: str) -> list[dict[str, Any]]:
    """Cache sector performance for 60 seconds."""
    try:
        return fetch_sector_performance(api_key)
    except Exception:
        logger.debug("cached_sector_perf failed", exc_info=True)
        return []


@st.cache_data(ttl=300, show_spinner=False)
def cached_ticker_sectors(api_key: str, tickers_csv: str) -> dict[str, str]:
    """Cache ticker→GICS sector mapping for 5 minutes."""
    try:
        tickers = [t.strip() for t in tickers_csv.split(",") if t.strip()]
        return fetch_ticker_sectors(api_key, tickers)
    except Exception:
        logger.debug("cached_ticker_sectors failed", exc_info=True)
        return {}


@st.cache_data(ttl=120, show_spinner=False)
def cached_defense_watchlist(api_key: str) -> list[dict[str, Any]]:
    """Cache Aerospace & Defense watchlist quotes for 2 minutes."""
    try:
        return fetch_defense_watchlist(api_key)
    except Exception:
        logger.debug("cached_defense_watchlist failed", exc_info=True)
        return []


@st.cache_data(ttl=120, show_spinner=False)
def cached_defense_watchlist_custom(api_key: str, tickers: str) -> list[dict[str, Any]]:
    """Cache custom Aerospace & Defense watchlist quotes for 2 minutes."""
    try:
        return fetch_defense_watchlist(api_key, tickers=tickers)
    except Exception:
        logger.debug("cached_defense_watchlist_custom failed", exc_info=True)
        return []


@st.cache_data(ttl=300, show_spinner=False)
def cached_industry_performance(api_key: str, industry: str = "Aerospace & Defense") -> list[dict[str, Any]]:
    """Cache industry screen results for 5 minutes."""
    try:
        return fetch_industry_performance(api_key, industry=industry)
    except Exception:
        logger.debug("cached_industry_performance failed", exc_info=True)
        return []


@st.cache_data(ttl=300, show_spinner=False)
def cached_econ_calendar(api_key: str, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Cache economic calendar for 5 minutes."""
    try:
        return fetch_economic_calendar(api_key, from_date, to_date)
    except Exception:
        logger.debug("cached_econ_calendar failed", exc_info=True)
        return []


@st.cache_data(ttl=90, show_spinner=False)
def cached_spike_data(api_key: str) -> dict[str, list[dict[str, Any]]]:
    """Cache gainers/losers/actives for 90 seconds.

    Uses yfinance (free, real-time) as primary source.  Falls back to
    FMP (15-min delayed) when yfinance is unavailable.
    """
    try:
        if _YF_AVAILABLE:
            yf_data = _yf_screen_movers()
            if yf_data["gainers"] or yf_data["losers"] or yf_data["actives"]:
                return yf_data
        if api_key:
            gainers = enrich_with_batch_quote(api_key, fetch_gainers(api_key))
            losers = enrich_with_batch_quote(api_key, fetch_losers(api_key))
            actives = enrich_with_batch_quote(api_key, fetch_most_active(api_key))
            return {"gainers": gainers, "losers": losers, "actives": actives}
        return {"gainers": [], "losers": [], "actives": []}
    except Exception:
        logger.debug("cached_spike_data failed", exc_info=True)
        return {"gainers": [], "losers": [], "actives": []}


@st.cache_data(ttl=300, show_spinner=False)
def cached_tomorrow_outlook(
    bz_key: str, fmp_key: str, _cache_buster: str = "",
) -> dict[str, Any]:
    """Cache tomorrow outlook for 5 minutes."""
    try:
        return compute_tomorrow_outlook(bz_key, fmp_key)
    except Exception:
        logger.debug("cached_tomorrow_outlook failed", exc_info=True)
        return {}


@st.cache_data(ttl=60, show_spinner=False)
def cached_bz_movers(api_key: str) -> dict[str, list[dict[str, Any]]]:
    """Cache market movers for 60 seconds."""
    try:
        return fetch_benzinga_market_movers(api_key)
    except Exception:
        logger.debug("cached_bz_movers failed", exc_info=True)
        return {}


@st.cache_data(ttl=60, show_spinner=False)
def cached_bz_quotes(api_key: str, symbols_csv: str) -> list[dict[str, Any]]:
    """Cache delayed quotes for 60 seconds."""
    try:
        syms = [s.strip() for s in symbols_csv.split(",") if s.strip()]
        return fetch_benzinga_delayed_quotes(api_key, syms)
    except Exception:
        logger.debug("cached_bz_quotes failed", exc_info=True)
        return []


# ═══════════════════════════════════════════════════════════════
# Unified mover/ranking data builder  (items 2 + 11)
# ═══════════════════════════════════════════════════════════════

def build_unified_movers(
    *,
    fmp_key: str | None,
    bz_key: str | None,
    current_session: str,
    spike_detector: SpikeDetector | None = None,
    include_mkt_cap: bool = False,
) -> dict[str, dict[str, Any]]:
    """Build a unified symbol → mover dict from all data sources.

    Used by both the Top Movers and Rankings tabs to avoid
    duplicating ~120 lines of data aggregation.
    """
    now = time.time()
    result: dict[str, dict[str, Any]] = {}

    # 1) FMP gainers/losers/actives (30s TTL)
    if fmp_key:
        fmp_data = cached_spike_data(fmp_key)
        for src_list, src_label in [
            (fmp_data["gainers"], "FMP-Gainer"),
            (fmp_data["losers"], "FMP-Loser"),
            (fmp_data["actives"], "FMP-Active"),
        ]:
            for item in src_list:
                sym = (item.get("symbol") or "").upper().strip()
                if not sym:
                    continue
                price = safe_float(item.get("price"))
                chg_pct = safe_float(item.get("changesPercentage"))
                chg = safe_float(item.get("change"))
                vol = int(safe_float(item.get("volume")))
                name = item.get("name") or item.get("companyName") or ""
                existing = result.get(sym)
                if not existing or abs(chg_pct) > abs(existing.get("chg_pct", 0)):
                    row: dict[str, Any] = {
                        "symbol": sym,
                        "name": name[:50],
                        "price": price,
                        "change": chg,
                        "chg_pct": chg_pct,
                        "volume": vol,
                        "source": src_label,
                        "_ts": now,
                    }
                    if include_mkt_cap:
                        row["mkt_cap"] = item.get("marketCap") or ""
                    result[sym] = row

    # 2) Benzinga market movers (60s TTL)
    if bz_key:
        bz_movers = cached_bz_movers(bz_key)
        for bz_list, bz_label in [
            (bz_movers.get("gainers", []), "BZ-Gainer"),
            (bz_movers.get("losers", []), "BZ-Loser"),
        ]:
            for item in bz_list:
                sym = (item.get("symbol") or item.get("ticker") or "").upper().strip()
                if not sym:
                    continue
                price = safe_float(item.get("price") or item.get("last"))
                chg_pct = safe_float(item.get("changePercent") or item.get("change_percent"))
                chg = safe_float(item.get("change"))
                vol = int(safe_float(item.get("volume")))
                name = item.get("companyName") or item.get("company_name") or ""
                existing = result.get(sym)
                # Delayed quotes are fresher during extended hours
                if not existing or (current_session in ("pre-market", "after-hours")):
                    row = {
                        "symbol": sym,
                        "name": name[:50],
                        "price": price,
                        "change": chg,
                        "chg_pct": chg_pct,
                        "volume": vol,
                        "source": bz_label,
                        "_ts": now,
                    }
                    if include_mkt_cap:
                        row["mkt_cap"] = item.get("marketCap") or item.get("market_cap") or ""
                        row["sector"] = item.get("gicsSectorName") or item.get("sector") or ""
                    result[sym] = row

    # 3) RT spike events from the detector
    if spike_detector is not None:
        for ev in spike_detector.events[:50]:
            sym = ev.symbol
            existing = result.get(sym)
            if not existing or abs(ev.spike_pct) > abs(existing.get("chg_pct", 0)):
                row = {
                    "symbol": sym,
                    "name": ev.name[:50],
                    "price": ev.price,
                    "change": ev.change,
                    "chg_pct": ev.spike_pct,
                    "volume": ev.volume,
                    "source": f"RT-Spike {ev.direction}",
                    "_ts": ev.ts,
                }
                if include_mkt_cap:
                    row["mkt_cap"] = ""
                result[sym] = row

    return result


def build_mover_table_rows(
    sorted_movers: list[dict[str, Any]],
    *,
    max_rows: int = 100,
) -> list[dict[str, Any]]:
    """Build display rows for a movers table (item 11 — DRY)."""
    now = time.time()
    rows: list[dict[str, Any]] = []
    for m in sorted_movers[:max_rows]:
        dir_icon = "🟢" if m.get("chg_pct", 0) > 0 else "🔴"
        rows.append({
            "Dir": dir_icon,
            "Symbol": m["symbol"],
            "Name": m.get("name", ""),
            "Price": f"${m['price']:.2f}" if m["price"] >= 1 else f"${m['price']:.4f}",
            "Change": f"{m['change']:+.2f}",
            "Change %": f"{m['chg_pct']:+.2f}%",
            "Age": format_age_string(m.get("_ts"), now=now),
            "Volume": f"{m['volume']:,}" if m.get("volume") else "",
            "Source": m.get("source", ""),
        })
    return rows


# ═══════════════════════════════════════════════════════════════
# Segment article renderer (item 3 — DRY)
# ═══════════════════════════════════════════════════════════════

def render_segment_articles(
    label: str,
    rows: list[dict[str, Any]],
    *,
    max_segments: int = 8,
    bold: bool = True,
) -> None:
    """Render a list of segment expanders with their articles."""
    st.markdown(f"**{label}**")
    if not rows:
        st.caption("None")
        return
    for r in rows[:max_segments]:
        segment_text = safe_markdown_text(r["segment"])
        title = f"**{segment_text}**" if bold else segment_text
        with st.expander(
            f"{title} — {r['articles']} articles, avg {r['avg_score']:.3f}"
        ):
            articles = sorted(
                r.get("_items", []),
                key=lambda d: d.get("news_score", 0),
                reverse=True,
            )[:20]
            for a in articles:
                hl = (a.get("headline") or "(no headline)")[:100]
                url = a.get("url", "")
                tk = a.get("ticker", "")
                sc = a.get("news_score", 0)
                if url:
                    st.markdown(
                        f"- [{safe_markdown_text(hl)}]({url}) · `{tk}` · {sc:.3f}"
                    )
                else:
                    st.markdown(
                        f"- {safe_markdown_text(hl)} · `{tk}` · {sc:.3f}"
                    )


def build_bz_mover_rows(
    items: list[dict[str, Any]],
    quote_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build display rows for BZ gainers/losers tables (item 11 — DRY)."""
    rows: list[dict[str, Any]] = []
    for g in items:
        sym = g.get("symbol") or g.get("ticker", "?")
        q = quote_map.get(sym.upper(), {})
        rows.append({
            "Symbol": sym,
            "Company": g.get("companyName", g.get("company_name", "")),
            "Price": q["last"] if "last" in q else g.get("price", g.get("last", "")),
            "Change": q["change"] if "change" in q else g.get("change", ""),
            "Change %": q["changePercent"] if "changePercent" in q else g.get(
                "changePercent", g.get("change_percent", "")
            ),
            "Age": format_age_string(time.time()),
            "Volume": q["volume"] if "volume" in q else g.get("volume", ""),
            "Avg Volume": g.get("averageVolume", g.get("average_volume", "")),
            "Mkt Cap": g.get("marketCap", g.get("market_cap", "")),
            "Sector": g.get("gicsSectorName", g.get("sector", "")),
        })
    return rows


# ═══════════════════════════════════════════════════════════════
# Shared render helpers
# ═══════════════════════════════════════════════════════════════

def render_technicals_expander(
    symbols: list[str], *, key_prefix: str = "tech"
) -> None:
    """Render a TradingView Technical Analysis expander for symbols."""
    if not INTERVAL_MAP or not symbols:
        return

    with st.expander("📊 Technical Data", expanded=False):
        tc1, tc2 = st.columns([1, 3])
        with tc1:
            sel_sym = st.selectbox("Symbol", symbols[:50], key=f"{key_prefix}_sym")
        with tc2:
            sel_iv = st.selectbox(
                "Interval",
                list(INTERVAL_MAP.keys()),
                index=list(INTERVAL_MAP.keys()).index("1D"),
                key=f"{key_prefix}_iv",
            )

        if sel_sym and sel_iv:
            tech = fetch_technicals(sel_sym, sel_iv)
            if tech.error:
                st.warning(f"No technical data: {tech.error}")
                return

            st.markdown(f"### {sel_sym} · Technical Data · {sel_iv}")

            g1, g2, g3 = st.columns(3)
            with g1:
                st.metric(
                    "Summary",
                    f"{signal_icon(tech.summary_signal)} {signal_label(tech.summary_signal)}",
                )
                st.caption(
                    f"Buy {tech.summary_buy} · Neutral {tech.summary_neutral} · Sell {tech.summary_sell}"
                )
            with g2:
                st.metric(
                    "Oscillators",
                    f"{signal_icon(tech.osc_signal)} {signal_label(tech.osc_signal)}",
                )
                st.caption(
                    f"Buy {tech.osc_buy} · Neutral {tech.osc_neutral} · Sell {tech.osc_sell}"
                )
            with g3:
                st.metric(
                    "Moving Averages",
                    f"{signal_icon(tech.ma_signal)} {signal_label(tech.ma_signal)}",
                )
                st.caption(
                    f"Buy {tech.ma_buy} · Neutral {tech.ma_neutral} · Sell {tech.ma_sell}"
                )

            # Multi-interval summary strip
            strip_intervals = ["1m", "15m", "1h", "4h", "1D"]
            strip_cols = st.columns(len(strip_intervals))
            for si, siv in enumerate(strip_intervals):
                with strip_cols[si]:
                    sr = tech if siv == sel_iv else fetch_technicals(sel_sym, siv)
                    if sr.error:
                        st.caption(f"**{siv}**\n—")
                    else:
                        st.caption(
                            f"**{siv}**\n{signal_icon(sr.summary_signal)} "
                            f"{signal_label(sr.summary_signal)}"
                        )

            # Oscillator + MA detail tables
            osc_tab, ma_tab = st.tabs(["Oscillators", "Moving Averages"])
            _render_indicator_table(osc_tab, tech.osc_detail, "oscillator")
            _render_indicator_table(ma_tab, tech.ma_detail, "moving average")


def _render_indicator_table(
    tab, detail: list[dict[str, Any]] | None, label: str
) -> None:
    """Render an oscillator or moving-average detail table inside a tab."""
    with tab:
        if detail:
            rows = []
            for d in detail:
                action = d["action"]
                icon = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "🟡"}.get(action, "")
                rows.append({
                    "Name": d["name"],
                    "Value": d["value"] if d["value"] is not None else "—",
                    "Action": f"{icon} {action}",
                })
            st.dataframe(
                pd.DataFrame(rows),
                width="stretch",
                hide_index=True,
                height=min(500, 40 + 35 * len(rows)),
            )
        else:
            st.info(f"No {label} data available.")


def render_event_clusters_expander(
    symbols: list[str], *, key_prefix: str = "ec"
) -> None:
    """Render an event-clustered news expander for symbols."""
    if not symbols or not newsapi_available():
        return

    with st.expander("📰 Event-Clustered News (NewsAPI.ai)", expanded=False):
        ec_sym = st.selectbox("Symbol", symbols[:50], key=f"{key_prefix}_sym")
        if not ec_sym:
            return

        clusters = fetch_event_clusters(ec_sym, count=8, hours=48)
        if not clusters:
            st.info(f"No event clusters found for {ec_sym} in the last 48h.")
            return

        st.caption(
            f"**{ec_sym}** — {len(clusters)} stories grouped by event · Source: NewsAPI.ai"
        )

        for ci, cluster in enumerate(clusters):
            c_title = cluster.title or "(Untitled event)"
            c_sources = ", ".join(cluster.sources[:3]) if cluster.sources else ""

            with st.expander(
                f"{cluster.sentiment_icon} **{c_title[:100]}** — "
                f"📰 {cluster.article_count} articles · {cluster.event_date}",
                expanded=(ci == 0),
            ):
                ec1, ec2, ec3 = st.columns(3)
                with ec1:
                    st.metric("Articles", cluster.article_count)
                with ec2:
                    if cluster.sentiment is not None:
                        st.metric("NLP Sentiment", f"{cluster.sentiment:+.2f}")
                    else:
                        st.metric("NLP Sentiment", "n/a")
                with ec3:
                    st.metric("Sources", len(cluster.sources))

                if cluster.summary:
                    st.markdown(f"**Summary:** {cluster.summary}")
                if c_sources:
                    st.caption(f"Sources: {c_sources}")
                if cluster.top_articles:
                    st.markdown("**Top articles:**")
                    for ta in cluster.top_articles:
                        if ta.get("url"):
                            st.markdown(
                                f"- [{ta['title'][:80]}]({ta['url']}) — "
                                f"*{ta.get('source', '')}*"
                            )
                        else:
                            st.markdown(
                                f"- {ta['title'][:80]} — *{ta.get('source', '')}*"
                            )


def render_forecast_expander(
    symbols: list[str], *, key_prefix: str = "fc"
) -> None:
    """Render an analyst forecast expander for symbols."""
    if not symbols:
        return

    with st.expander("🔮 Forecast", expanded=False):
        fc_sym = st.selectbox("Symbol", symbols[:50], key=f"{key_prefix}_sym")
        if not fc_sym:
            return

        fc = fetch_forecast(fc_sym)
        if fc.error:
            st.warning(f"No forecast data: {fc.error}")
            return
        if not fc.has_data:
            st.info("No forecast data available for this symbol.")
            return

        src_tag = f"  ·  *via {fc.source}*" if fc.source else ""
        st.caption(f"**{fc_sym}** — Analyst Forecast{src_tag}")

        # Price Target
        if fc.price_target and fc.price_target.target_mean > 0:
            pt = fc.price_target
            st.markdown("### 🎯 Price Target")
            pt1, pt2, pt3, pt4 = st.columns(4)
            pt1.metric("Current", f"${pt.current_price:.2f}")
            pt2.metric("Target (Avg)", f"${pt.target_mean:.2f}", f"{pt.upside_pct:+.1f}%")
            pt3.metric("Target High", f"${pt.target_high:.2f}", f"{pt.upside_high_pct:+.1f}%")
            pt4.metric("Target Low", f"${pt.target_low:.2f}", f"{pt.upside_low_pct:+.1f}%")

            if pt.last_month_count or pt.last_quarter_count or pt.last_year_count:
                pts_rows: list[dict[str, Any]] = []
                if pt.last_month_count:
                    pts_rows.append({
                        "Period": "Last Month",
                        "Avg Target": f"${pt.last_month_avg:.2f}",
                        "Analysts": pt.last_month_count,
                    })
                if pt.last_quarter_count:
                    pts_rows.append({
                        "Period": "Last Quarter",
                        "Avg Target": f"${pt.last_quarter_avg:.2f}",
                        "Analysts": pt.last_quarter_count,
                    })
                if pt.last_year_count:
                    pts_rows.append({
                        "Period": "Last Year",
                        "Avg Target": f"${pt.last_year_avg:.2f}",
                        "Analysts": pt.last_year_count,
                    })
                st.dataframe(
                    pd.DataFrame(pts_rows),
                    width="stretch",
                    hide_index=True,
                    height=min(180, 40 + 35 * len(pts_rows)),
                )

        # Analyst Rating
        if fc.rating and fc.rating.total > 0:
            rt = fc.rating
            st.markdown(f"### 📊 Analyst Rating — {rt.consensus_icon} {rt.consensus}")
            st.caption(f"Based on {rt.total} analysts")
            rt1, rt2, rt3, rt4, rt5 = st.columns(5)
            rt1.metric("Strong Buy", rt.strong_buy)
            rt2.metric("Buy", rt.buy)
            rt3.metric("Hold", rt.hold)
            rt4.metric("Sell", rt.sell)
            rt5.metric("Strong Sell", rt.strong_sell)

        # EPS Estimates
        if fc.eps_estimates:
            st.markdown("### 📈 EPS Estimates")
            eps_rows: list[dict[str, Any]] = []
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
                    row["Rev Est."] = (
                        f"${e.revenue_avg / 1e9:.1f}B"
                        if e.revenue_avg > 1e9
                        else f"${e.revenue_avg / 1e6:.0f}M"
                    )
                eps_rows.append(row)
            st.dataframe(
                pd.DataFrame(eps_rows),
                width="stretch",
                hide_index=True,
                height=min(350, 40 + 35 * len(eps_rows)),
            )

        # Upgrades / Downgrades
        if fc.upgrades_downgrades:
            st.markdown("### 📋 Recent Upgrades / Downgrades")
            action_icons = {
                "upgrade": "⬆️", "up": "⬆️",
                "downgrade": "⬇️", "down": "⬇️",
                "maintain": "➡️", "main": "➡️",
                "init": "🆕", "initiated": "🆕",
                "reiterate": "🔄", "reit": "🔄",
            }
            ud_rows: list[dict[str, Any]] = []
            for u in fc.upgrades_downgrades:
                icon = action_icons.get(u.action.lower(), "")
                ud_rows.append({
                    "Date": u.date,
                    "Firm": u.firm,
                    "Action": f"{icon} {u.action}",
                    "From": u.from_grade,
                    "To": u.to_grade,
                })
            st.dataframe(
                pd.DataFrame(ud_rows),
                width="stretch",
                hide_index=True,
                height=min(500, 40 + 35 * len(ud_rows)),
            )
