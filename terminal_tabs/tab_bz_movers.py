"""Tab: BZ Movers — Benzinga market movers with delayed quotes."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from terminal_tabs._shared import (
    bz_tier_warning,
    build_bz_mover_rows,
    cached_bz_movers,
    cached_bz_quotes,
    render_event_clusters_expander,
    render_forecast_expander,
    render_technicals_expander,
)


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the BZ Movers tab."""
    cfg = st.session_state.cfg
    bz_key = cfg.benzinga_api_key

    if not bz_key:
        st.info("Set `BENZINGA_API_KEY` in `.env` for Benzinga movers.")
        return

    st.subheader("📈 Benzinga Market Movers")
    st.caption("Most active gainers & losers from Benzinga with delayed quotes.")

    movers = cached_bz_movers(bz_key)
    gainers = movers.get("gainers", [])
    losers = movers.get("losers", [])

    if not gainers and not losers:
        bz_tier_warning(
            "market-movers",
            "No movers data available from Benzinga.",
        )
        return

    # Fetch delayed quotes for enrichment
    all_syms = list({
        (g.get("symbol") or g.get("ticker", "")).upper()
        for g in gainers + losers
        if g.get("symbol") or g.get("ticker")
    })
    quote_map: dict[str, dict[str, Any]] = {}
    if all_syms:
        quotes = cached_bz_quotes(bz_key, ",".join(all_syms[:40]))
        quote_map = {
            q.get("symbol", "").upper(): q for q in quotes if q.get("symbol")
        }

    # Gainers table (shared builder — item 11)
    st.markdown("### 🟢 Top Gainers")
    if gainers:
        g_rows = build_bz_mover_rows(gainers, quote_map)
        st.dataframe(
            pd.DataFrame(g_rows),
            width="stretch",
            hide_index=True,
            height=min(500, 40 + 35 * len(g_rows)),
        )
    else:
        st.caption("—")

    # Losers table (shared builder — item 11)
    st.markdown("### 🔴 Top Losers")
    if losers:
        l_rows = build_bz_mover_rows(losers, quote_map)
        st.dataframe(
            pd.DataFrame(l_rows),
            width="stretch",
            hide_index=True,
            height=min(500, 40 + 35 * len(l_rows)),
        )
    else:
        st.caption("—")

    # Shared expanders
    bz_syms = [
        (g.get("symbol") or g.get("ticker", "")).upper()
        for g in gainers + losers
        if g.get("symbol") or g.get("ticker")
    ][:50]
    render_technicals_expander(bz_syms, key_prefix="tech_bz")
    render_forecast_expander(bz_syms, key_prefix="fc_bz")
    render_event_clusters_expander(bz_syms, key_prefix="ec_bz")
