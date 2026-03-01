"""Tab: Spike Scanner — FMP gainers/losers/actives with volume screening."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import streamlit as st

from terminal_spike_scanner import (
    SESSION_ICONS,
    build_spike_rows,
    filter_spike_rows,
    overlay_extended_hours_quotes,
)
from terminal_tabs._shared import (
    cached_spike_data,
    render_event_clusters_expander,
    render_forecast_expander,
    render_technicals_expander,
)


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Spike Scanner tab."""
    cfg = st.session_state.cfg
    fmp_key = cfg.fmp_api_key

    if not fmp_key:
        st.info("Set `FMP_API_KEY` in `.env` for the Spike Scanner.")
        return

    session_label = SESSION_ICONS.get(current_session, current_session)
    st.subheader("🔎 Spike Scanner")
    st.caption(
        f"**{session_label}** — FMP Gainers / Losers / Most Active "
        "with volume-weighted spike scoring."
    )

    data = cached_spike_data(fmp_key)
    if not data["gainers"] and not data["losers"] and not data["actives"]:
        st.info("No spike data available yet.")
        return

    # Overlay extended-hours quotes when applicable
    if current_session in ("pre-market", "after-hours"):
        for key in ("gainers", "losers", "actives"):
            data[key] = overlay_extended_hours_quotes(fmp_key, data[key])

    # Filter controls
    f1, f2, f3 = st.columns(3)
    with f1:
        min_vol = st.number_input(
            "Min Volume", value=100_000, step=50_000,
            key="spike_min_vol",
        )
    with f2:
        min_chg = st.number_input(
            "Min Change %", value=3.0, step=1.0,
            key="spike_min_chg",
        )
    with f3:
        min_price = st.number_input(
            "Min Price ($)", value=1.0, step=0.5,
            key="spike_min_price",
        )

    # Build combined rows
    all_rows = build_spike_rows(data)
    filtered_rows = filter_spike_rows(
        all_rows,
        min_volume=int(min_vol),
        min_change_pct=min_chg,
        min_price=min_price,
    )

    # Summary
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Screened", len(all_rows))
    m2.metric("After Filter", len(filtered_rows))
    m3.metric(
        "Top Spike",
        f"{filtered_rows[0]['symbol']} {filtered_rows[0]['chg_pct']:+.1f}%"
        if filtered_rows else "—",
    )

    if not filtered_rows:
        st.info("No spikes pass the current filter. Try lowering thresholds.")
        return

    # Build table
    now = time.time()
    table_rows: list[dict[str, Any]] = []
    for r in filtered_rows[:100]:
        dir_icon = "🟢" if r.get("chg_pct", 0) > 0 else "🔴"
        table_rows.append({
            "Dir": dir_icon,
            "Symbol": r["symbol"],
            "Name": (r.get("name") or "")[:40],
            "Price": f"${r['price']:.2f}" if r["price"] >= 1 else f"${r['price']:.4f}",
            "Change %": f"{r['chg_pct']:+.2f}%",
            "Volume": f"{r['volume']:,}" if r.get("volume") else "",
            "Mkt Cap": r.get("mkt_cap", ""),
            "Source": r.get("source", ""),
        })

    df = pd.DataFrame(table_rows)
    df.index = df.index + 1
    st.dataframe(
        df,
        width="stretch",
        height=min(800, 40 + 35 * len(df)),
    )

    # Shared expanders
    spike_syms = [r["symbol"] for r in filtered_rows[:50]]
    render_technicals_expander(spike_syms, key_prefix="tech_spike")
    render_forecast_expander(spike_syms, key_prefix="fc_spike")
    render_event_clusters_expander(spike_syms, key_prefix="ec_spike")
