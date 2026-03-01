"""Tab: Tomorrow Outlook — pre-market preparation summary."""

from __future__ import annotations

import time
from typing import Any

import streamlit as st

from terminal_tabs._shared import cached_tomorrow_outlook


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Tomorrow Outlook tab."""
    cfg = st.session_state.cfg
    bz_key = cfg.benzinga_api_key
    fmp_key = cfg.fmp_api_key

    if not bz_key and not fmp_key:
        st.info(
            "Set `BENZINGA_API_KEY` and/or `FMP_API_KEY` in `.env` "
            "for tomorrow's outlook."
        )
        return

    st.subheader("🌅 Tomorrow Outlook")
    st.caption("Pre-market preparation: key data points for the next session.")

    cache_buster = str(int(time.time()) // 300)  # 5min window
    outlook = cached_tomorrow_outlook(
        bz_key or "", fmp_key or "", _cache_buster=cache_buster,
    )

    if not outlook:
        st.info("No outlook data available. Generating preview...")
        return

    # Summary metrics
    m1, m2, m3 = st.columns(3)
    if "bias" in outlook:
        bias = outlook["bias"]
        bias_icon = {"bullish": "🟢", "bearish": "🔴"}.get(bias, "⚪")
        m1.metric("Bias", f"{bias_icon} {bias.title()}")
    if "confidence" in outlook:
        m2.metric("Confidence", f"{outlook['confidence']:.0%}")
    if "event_count" in outlook:
        m3.metric("Key Events", outlook["event_count"])

    # Catalysts
    if outlook.get("catalysts"):
        st.markdown("### 📋 Key Catalysts")
        for cat in outlook["catalysts"]:
            icon = (
                "🟢" if cat.get("sentiment") == "bullish"
                else "🔴" if cat.get("sentiment") == "bearish"
                else "⚪"
            )
            st.markdown(f"- {icon} **{cat.get('title', '')}** — {cat.get('detail', '')}")

    # Earnings
    if outlook.get("earnings"):
        st.markdown("### 📊 Earnings Due")
        for e in outlook["earnings"][:20]:
            st.markdown(
                f"- **{e.get('symbol', '?')}** — {e.get('name', '')} "
                f"(*{e.get('time', '')}*)"
            )

    # Macro events
    if outlook.get("macro_events"):
        st.markdown("### 🌍 Macro Events")
        for me in outlook["macro_events"][:15]:
            impact_icon = {
                "high": "🔴", "medium": "🟡", "low": "🟢",
            }.get((me.get("impact") or "").lower(), "⚪")
            st.markdown(
                f"- {impact_icon} **{me.get('event', '')}** "
                f"({me.get('time', '')})"
            )

    # Risk factors
    if outlook.get("risks"):
        st.markdown("### ⚠️ Risk Factors")
        for r in outlook["risks"]:
            st.markdown(f"- {r}")

    # Raw JSON expander
    with st.expander("🔧 Raw Outlook Data"):
        st.json(outlook)
