"""Tab: Rankings — sector + market-cap ranked view of movers."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from terminal_spike_scanner import SESSION_ICONS
from terminal_ui_helpers import format_age_string

from terminal_tabs._shared import (
    build_unified_movers,
    cached_ticker_sectors,
    render_event_clusters_expander,
    render_forecast_expander,
    render_technicals_expander,
)


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Rankings tab."""
    cfg = st.session_state.cfg
    fmp_key = cfg.fmp_api_key
    bz_key = cfg.benzinga_api_key

    if not fmp_key and not bz_key:
        st.info("Set `FMP_API_KEY` and/or `BENZINGA_API_KEY` in `.env` for rankings.")
        return

    st.subheader("🏅 Rankings — Sector & Market-Cap View")
    st.caption(
        f"**{SESSION_ICONS.get(current_session, current_session)}** — "
        "Movers ranked by magnitude with sector overlay."
    )

    rank_all = build_unified_movers(
        fmp_key=fmp_key,
        bz_key=bz_key,
        current_session=current_session,
        spike_detector=st.session_state.get("spike_detector"),
        include_mkt_cap=True,
    )

    if not rank_all:
        st.info("No ranking data yet.")
        return

    # Enrich with GICS sectors
    un_sectored = [
        sym for sym, m in rank_all.items()
        if not m.get("sector") and fmp_key
    ]
    if un_sectored and fmp_key:
        sector_map = cached_ticker_sectors(fmp_key, ",".join(un_sectored[:80]))
        for sym, sector in sector_map.items():
            if sym in rank_all:
                rank_all[sym]["sector"] = sector

    sorted_rank = sorted(
        rank_all.values(),
        key=lambda x: abs(x.get("chg_pct", 0)),
        reverse=True,
    )

    # Sector breakdown
    sectors_seen: dict[str, list[dict[str, Any]]] = {}
    for m in sorted_rank:
        s = m.get("sector") or "Unknown"
        sectors_seen.setdefault(s, []).append(m)

    if sectors_seen:
        sec_cols = st.columns(min(6, len(sectors_seen)))
        for idx, (sec_name, sec_items) in enumerate(
            sorted(sectors_seen.items(), key=lambda kv: len(kv[1]), reverse=True)
        ):
            with sec_cols[idx % len(sec_cols)]:
                avg_chg = sum(
                    x.get("chg_pct", 0) for x in sec_items
                ) / max(len(sec_items), 1)
                icon = "🟢" if avg_chg > 0 else "🔴"
                st.metric(
                    sec_name[:15],
                    f"{icon} {avg_chg:+.2f}%",
                    delta=f"{len(sec_items)} stocks",
                )

    # Rankings table
    import time
    now = time.time()
    rank_rows: list[dict[str, Any]] = []
    for rank, m in enumerate(sorted_rank[:100], 1):
        dir_icon = "🟢" if m.get("chg_pct", 0) > 0 else "🔴"
        rank_rows.append({
            "#": rank,
            "Dir": dir_icon,
            "Symbol": m["symbol"],
            "Name": m.get("name", ""),
            "Price": f"${m['price']:.2f}" if m["price"] >= 1 else f"${m['price']:.4f}",
            "Change %": f"{m['chg_pct']:+.2f}%",
            "Volume": f"{m['volume']:,}" if m.get("volume") else "",
            "Sector": (m.get("sector") or "")[:20],
            "Mkt Cap": m.get("mkt_cap", ""),
            "Age": format_age_string(m.get("_ts"), now=now),
            "Source": m.get("source", ""),
        })

    df_rank = pd.DataFrame(rank_rows)
    st.dataframe(
        df_rank,
        width="stretch",
        height=min(800, 40 + 35 * len(df_rank)),
        hide_index=True,
    )

    # Shared expanders
    rank_symbols = [m["symbol"] for m in sorted_rank[:50]]
    render_technicals_expander(rank_symbols, key_prefix="tech_rank")
    render_forecast_expander(rank_symbols, key_prefix="fc_rank")
    render_event_clusters_expander(rank_symbols, key_prefix="ec_rank")
