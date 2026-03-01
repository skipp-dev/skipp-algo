"""Tab: Segments — market-segment breakdown of the feed."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_tabs._shared import render_segment_articles


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Segments tab."""
    st.subheader("📊 Market Segments")
    st.caption(
        "Articles grouped by market segment with average sentiment scores."
    )

    if not feed:
        st.info("No feed data yet.")
        return

    # Build segments from feed
    segs: dict[str, dict[str, Any]] = {}
    for d in feed:
        segment = d.get("segment_label") or d.get("category", "other")
        if segment not in segs:
            segs[segment] = {
                "segment": segment,
                "articles": 0,
                "total_score": 0.0,
                "avg_score": 0.0,
                "_items": [],
            }
        segs[segment]["articles"] += 1
        segs[segment]["total_score"] += d.get("news_score", 0)
        segs[segment]["_items"].append(d)

    # Compute averages
    for s in segs.values():
        s["avg_score"] = s["total_score"] / max(s["articles"], 1)

    sorted_segs = sorted(segs.values(), key=lambda x: x["avg_score"], reverse=True)

    # Categorize into bullish / neutral / bearish
    bullish = [s for s in sorted_segs if s["avg_score"] >= 0.5]
    neutral = [s for s in sorted_segs if 0.2 <= s["avg_score"] < 0.5]
    bearish = [s for s in sorted_segs if s["avg_score"] < 0.2]

    # Summary metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Segments", len(sorted_segs))
    m2.metric("🟢 Bullish", len(bullish))
    m3.metric("⚪ Neutral", len(neutral))
    m4.metric("🔴 Bearish", len(bearish))

    # Render each group using shared helper (item 3)
    render_segment_articles("🟢 Bullish Segments", bullish)
    render_segment_articles("⚪ Neutral Segments", neutral)
    render_segment_articles("🔴 Bearish Segments", bearish)
