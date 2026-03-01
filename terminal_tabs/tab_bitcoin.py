"""Tab: Bitcoin — BTC terminal with live data from terminal_bitcoin."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_bitcoin import (
    fetch_btc_data,
    render_btc_chart,
    render_btc_metrics,
    render_btc_dominance,
    render_btc_fear_greed,
)


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Bitcoin tab."""
    cfg = st.session_state.cfg
    fmp_key = cfg.fmp_api_key

    st.subheader("₿ Bitcoin Terminal")
    st.caption("Real-time BTC price, dominance, fear/greed index.")

    if not fmp_key:
        st.info("Set `FMP_API_KEY` in `.env` for Bitcoin data.")
        return

    btc = fetch_btc_data(fmp_key)
    if not btc:
        st.info("No Bitcoin data available.")
        return

    render_btc_metrics(btc)
    render_btc_chart(btc)

    bc1, bc2 = st.columns(2)
    with bc1:
        render_btc_dominance(btc)
    with bc2:
        render_btc_fear_greed(btc)
