"""Tab: Top Movers — real-time gainers & losers ranked by price change."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from terminal_spike_scanner import SESSION_ICONS

from terminal_tabs._shared import (
    build_mover_table_rows,
    build_unified_movers,
    render_event_clusters_expander,
    render_forecast_expander,
    render_technicals_expander,
)


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Top Movers tab."""
    cfg = st.session_state.cfg
    fmp_key = cfg.fmp_api_key
    bz_key = cfg.benzinga_api_key
    session_label = SESSION_ICONS.get(current_session, current_session)

    if not fmp_key and not bz_key:
        st.info("Set `FMP_API_KEY` and/or `BENZINGA_API_KEY` in `.env` for real-time movers.")
        return

    st.subheader("🔥 Real-Time Top Movers")
    st.caption(
        f"**{session_label}** — Live gainers & losers ranked by absolute price change. "
        "Auto-refreshes each cycle."
    )

    mov_all = build_unified_movers(
        fmp_key=fmp_key,
        bz_key=bz_key,
        current_session=current_session,
        spike_detector=st.session_state.get("spike_detector"),
    )

    if not mov_all:
        st.info("No mover data available yet. Data sources are loading.")
        return

    # Sort by absolute change%
    sorted_movers = sorted(
        mov_all.values(),
        key=lambda x: abs(x.get("chg_pct", 0)),
        reverse=True,
    )

    # Summary metrics
    n_up = sum(1 for m in sorted_movers if m.get("chg_pct", 0) > 0)
    n_dn = sum(1 for m in sorted_movers if m.get("chg_pct", 0) < 0)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Movers", len(sorted_movers))
    m2.metric("🟢 Gainers", n_up)
    m3.metric("🔴 Losers", n_dn)
    if sorted_movers:
        top = sorted_movers[0]
        m4.metric("🏆 Top Mover", f"{top['symbol']} {top['chg_pct']:+.2f}%")

    # Build table
    mov_rows = build_mover_table_rows(sorted_movers)
    df_mov = pd.DataFrame(mov_rows)
    df_mov.index = df_mov.index + 1

    st.dataframe(
        df_mov,
        width="stretch",
        height=min(800, 40 + 35 * len(df_mov)),
        column_config={
            "Dir": st.column_config.TextColumn("Dir", width="small"),
            "Symbol": st.column_config.TextColumn("Symbol", width="small"),
            "Name": st.column_config.TextColumn("Name", width="medium"),
            "Change %": st.column_config.TextColumn("Change %", width="small"),
            "Age": st.column_config.TextColumn("Age", width="small"),
        },
    )

    # Shared expanders
    mov_symbols = [m["symbol"] for m in sorted_movers[:50]]
    render_technicals_expander(mov_symbols, key_prefix="tech_movers")
    render_forecast_expander(mov_symbols, key_prefix="fc_movers")
    render_event_clusters_expander(mov_symbols, key_prefix="ec_movers")
