"""Tab: Heatmap — sector performance heatmap."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_tabs._shared import cached_sector_perf, safe_float


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Heatmap tab."""
    cfg = st.session_state.cfg
    fmp_key = cfg.fmp_api_key

    if not fmp_key:
        st.info("Set `FMP_API_KEY` in `.env` for sector heatmap data.")
        return

    st.subheader("🗺️ Sector Heatmap")
    st.caption("US market sector performance from FMP.")

    sectors = cached_sector_perf(fmp_key)
    if not sectors:
        st.info("No sector data available. Check your FMP API key & plan.")
        return

    # Sort by change %
    sorted_sectors = sorted(
        sectors,
        key=lambda x: safe_float(x.get("changesPercentage", x.get("change", 0))),
        reverse=True,
    )

    # Render as metric columns
    n_cols = min(6, len(sorted_sectors))
    for batch_start in range(0, len(sorted_sectors), n_cols):
        batch = sorted_sectors[batch_start: batch_start + n_cols]
        cols = st.columns(n_cols)
        for i, sec in enumerate(batch):
            name = sec.get("sector") or sec.get("name", "?")
            chg = safe_float(sec.get("changesPercentage", sec.get("change", 0)))
            icon = "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")
            with cols[i]:
                st.metric(name[:20], f"{icon} {chg:+.2f}%")

    # Also render as a bar chart
    try:
        import plotly.express as px

        labels = [
            (s.get("sector") or s.get("name", "?"))[:15]
            for s in sorted_sectors
        ]
        values = [
            safe_float(s.get("changesPercentage", s.get("change", 0)))
            for s in sorted_sectors
        ]
        colors = ["green" if v > 0 else "red" for v in values]

        fig = px.bar(
            x=labels,
            y=values,
            color=colors,
            color_discrete_map={"green": "#22c55e", "red": "#ef4444"},
            labels={"x": "Sector", "y": "Change %"},
            title="Sector Performance",
        )
        fig.update_layout(showlegend=False, height=400)
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.caption("Install `plotly` for a sector bar chart.")
