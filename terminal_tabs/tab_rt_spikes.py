"""Tab: RT Spikes — real-time spike detection from the SpikeDetector."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import streamlit as st

from terminal_spike_detector import SpikeDetector
from terminal_tabs._shared import (
    render_event_clusters_expander,
    render_forecast_expander,
    render_technicals_expander,
)
from terminal_ui_helpers import format_age_string


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the RT Spikes tab."""
    cfg = st.session_state.cfg
    spike_det: SpikeDetector | None = st.session_state.get("spike_detector")

    st.subheader("⚡ Real-Time Spike Detection")
    st.caption(
        "Symbols detected in the live feed that had abnormal price moves, "
        "scored by spike magnitude."
    )

    if spike_det is None or not spike_det.events:
        st.info("No spike events detected yet. Feed the scanner more data.")
        return

    events = spike_det.events
    now = time.time()

    # Summary
    m1, m2, m3 = st.columns(3)
    m1.metric("Active Spikes", len(events))
    m2.metric(
        "🟢 Up Spikes",
        sum(1 for e in events if e.direction == "up"),
    )
    m3.metric(
        "🔴 Down Spikes",
        sum(1 for e in events if e.direction == "down"),
    )

    # Build table
    rows: list[dict[str, Any]] = []
    for ev in events[:50]:
        dir_icon = "🟢" if ev.direction == "up" else "🔴"
        rows.append({
            "Dir": dir_icon,
            "Symbol": ev.symbol,
            "Name": ev.name[:40],
            "Price": f"${ev.price:.2f}" if ev.price >= 1 else f"${ev.price:.4f}",
            "Spike %": f"{ev.spike_pct:+.2f}%",
            "Change": f"{ev.change:+.2f}",
            "Volume": f"{ev.volume:,}" if ev.volume else "",
            "Age": format_age_string(ev.ts, now=now),
        })

    df = pd.DataFrame(rows)
    df.index = df.index + 1
    st.dataframe(
        df,
        width="stretch",
        height=min(600, 40 + 35 * len(df)),
    )

    # Shared expanders
    spike_syms = [ev.symbol for ev in events[:50]]
    render_technicals_expander(spike_syms, key_prefix="tech_rt_spk")
    render_forecast_expander(spike_syms, key_prefix="fc_rt_spk")
    render_event_clusters_expander(spike_syms, key_prefix="ec_rt_spk")
