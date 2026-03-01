"""Tab: Bitcoin — BTC terminal with live data from terminal_bitcoin."""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from terminal_bitcoin import (
    fetch_btc_quote,
    fetch_btc_technicals,
    fetch_btc_supply,
    fetch_btc_news,
    fetch_btc_outlook,
    fetch_fear_greed,
    format_btc_price,
    format_large_number,
    format_supply,
    is_available,
    technicals_signal_icon,
    technicals_signal_label,
)

log = logging.getLogger(__name__)


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Bitcoin tab."""
    st.subheader("₿ Bitcoin Terminal")
    st.caption("Real-time BTC price, dominance, fear/greed index, technicals.")

    if not is_available():
        st.info("Set `FMP_API_KEY` in `.env` or install `yfinance` / `tradingview_ta` for Bitcoin data.")
        return

    # ── Price metrics ────────────────────────────────────────────
    quote = fetch_btc_quote()
    if quote and quote.price > 0:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("BTC Price", format_btc_price(quote.price),
                  delta=f"{quote.change_pct:+.2f}%")
        m2.metric("24h Range", f"{format_btc_price(quote.day_low)} – {format_btc_price(quote.day_high)}")
        m3.metric("Volume", format_large_number(quote.volume))
        m4.metric("Market Cap", format_large_number(quote.market_cap))
    else:
        st.info("No BTC price data available.")

    # ── Fear & Greed ─────────────────────────────────────────────
    fg = fetch_fear_greed()
    if fg:
        st.markdown(
            f"### {fg.icon} Fear & Greed: **{fg.value:.0f}** — {fg.label}"
        )
        st.progress(fg.value / 100)
        if fg.timestamp:
            st.caption(f"Updated: {fg.timestamp}")

    # ── Technicals (1H) ─────────────────────────────────────────
    tech = fetch_btc_technicals("1h")
    if tech and not tech.error:
        st.markdown(f"### {tech.signal_icon} 1H Technicals: **{technicals_signal_label(tech.summary)}**")
        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("Buy / Sell / Neutral", f"{tech.buy} / {tech.sell} / {tech.neutral}")
        tc2.metric("Oscillators", f"{technicals_signal_label(tech.osc_signal)} ({tech.osc_buy}B/{tech.osc_sell}S)")
        tc3.metric("Moving Avgs", f"{technicals_signal_label(tech.ma_signal)} ({tech.ma_buy}B/{tech.ma_sell}S)")

        if tech.rsi is not None:
            ind1, ind2, ind3 = st.columns(3)
            ind1.metric("RSI", f"{tech.rsi:.1f}")
            if tech.macd is not None:
                ind2.metric("MACD", f"{tech.macd:.2f}")
            if tech.adx is not None:
                ind3.metric("ADX", f"{tech.adx:.1f}")
    elif tech and tech.error:
        st.warning(f"Technicals unavailable: {tech.error}")

    # ── Supply data ──────────────────────────────────────────────
    supply = fetch_btc_supply()
    if supply and supply.circulating_supply > 0:
        with st.expander("₿ Supply & On-Chain"):
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Circulating", format_supply(supply.circulating_supply))
            sc2.metric("Max Supply", format_supply(supply.total_supply))
            sc3.metric("% Mined", f"{supply.circulating_supply / supply.total_supply * 100:.1f}%")
            if supply.fifty_day_avg > 0:
                sa1, sa2 = st.columns(2)
                sa1.metric("50-Day Avg", format_btc_price(supply.fifty_day_avg))
                sa2.metric("200-Day Avg", format_btc_price(supply.two_hundred_day_avg))

    # ── Outlook ──────────────────────────────────────────────────
    outlook = fetch_btc_outlook()
    if outlook and not outlook.error:
        st.markdown(f"### {outlook.trend_icon} Outlook: **{outlook.trend_label}**")
        oc1, oc2, oc3 = st.columns(3)
        oc1.metric("Support", format_btc_price(outlook.support))
        oc2.metric("Resistance", format_btc_price(outlook.resistance))
        if outlook.rsi is not None:
            oc3.metric("RSI (1D)", f"{outlook.rsi:.1f}")
        if outlook.summary_text:
            st.caption(outlook.summary_text)
    elif outlook and outlook.error:
        st.warning(f"Outlook unavailable: {outlook.error}")

    # ── News ─────────────────────────────────────────────────────
    news = fetch_btc_news(limit=8)
    if news:
        with st.expander(f"📰 BTC News ({len(news)} articles)"):
            for art in news:
                title = art.get("title", "—")
                url = art.get("url", "")
                source = art.get("source", "")
                date = art.get("date", "")
                link = f"[{title}]({url})" if url else title
                st.markdown(f"- {link}  ·  {source}  ·  {date}")
