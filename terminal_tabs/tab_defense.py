"""Tab: Defense — Aerospace & Defense sector watchlist."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from terminal_tabs._shared import (
    cached_defense_watchlist,
    cached_defense_watchlist_custom,
    cached_industry_performance,
    render_event_clusters_expander,
    render_forecast_expander,
    render_technicals_expander,
    safe_float,
)


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Defense tab."""
    cfg = st.session_state.cfg
    fmp_key = cfg.fmp_api_key

    if not fmp_key:
        st.info("Set `FMP_API_KEY` in `.env` for the Defense watchlist.")
        return

    st.subheader("🛡️ Aerospace & Defense")
    st.caption("Watchlist + industry screen for A&D sector.")

    # Custom tickers input
    custom = st.text_input(
        "Custom tickers (comma-separated, leave empty for defaults)",
        value="",
        key="defense_custom",
    )

    if custom.strip():
        watchlist = cached_defense_watchlist_custom(fmp_key, custom.strip())
    else:
        watchlist = cached_defense_watchlist(fmp_key)

    if not watchlist:
        st.info("No defense watchlist data available.")
        return

    # Build table
    rows: list[dict[str, Any]] = []
    for q in watchlist:
        sym = q.get("symbol", "")
        price = safe_float(q.get("price"))
        chg = safe_float(q.get("change"))
        chg_pct = safe_float(q.get("changesPercentage"))
        vol = int(safe_float(q.get("volume")))
        name = q.get("name", q.get("companyName", ""))

        dir_icon = "🟢" if chg_pct > 0 else ("🔴" if chg_pct < 0 else "⚪")
        rows.append({
            "Dir": dir_icon,
            "Symbol": sym,
            "Name": name[:40],
            "Price": f"${price:.2f}",
            "Change": f"{chg:+.2f}",
            "Change %": f"{chg_pct:+.2f}%",
            "Volume": f"{vol:,}" if vol else "",
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        width="stretch",
        height=min(600, 40 + 35 * len(df)),
        hide_index=True,
    )

    # Industry performance
    with st.expander("📊 Industry Screen", expanded=False):
        ind = cached_industry_performance(fmp_key, industry="Aerospace & Defense")
        if ind:
            ind_rows: list[dict[str, Any]] = []
            for i in ind[:30]:
                ind_rows.append({
                    "Symbol": i.get("symbol", ""),
                    "Name": (i.get("companyName") or i.get("name", ""))[:30],
                    "Price": f"${safe_float(i.get('price')):.2f}",
                    "Change %": f"{safe_float(i.get('changesPercentage')):+.2f}%",
                    "Mkt Cap": i.get("marketCap", ""),
                    "Sector": i.get("sector", ""),
                })
            st.dataframe(
                pd.DataFrame(ind_rows),
                width="stretch",
                hide_index=True,
                height=min(500, 40 + 35 * len(ind_rows)),
            )
        else:
            st.info("No industry screen results.")

    # Shared expanders
    def_syms = [q.get("symbol", "") for q in watchlist if q.get("symbol")][:50]
    render_technicals_expander(def_syms, key_prefix="tech_def")
    render_forecast_expander(def_syms, key_prefix="fc_def")
    render_event_clusters_expander(def_syms, key_prefix="ec_def")
