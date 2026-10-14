"""Tab: Data Table — raw feed data in a searchable dataframe."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Data Table tab."""
    st.subheader("📋 Raw Feed Data")
    st.caption(f"Full dataset — {len(feed)} items")

    if not feed:
        st.info("No feed data yet.")
        return

    # Display columns of interest
    display_cols = [
        "ticker", "headline", "sentiment_label", "news_score",
        "category", "event_label", "provider", "published_ts",
        "segment_label", "is_wiim", "url",
    ]
    cols_present = [c for c in display_cols if any(c in d for d in feed[:5])]

    df = pd.DataFrame(feed)

    # Keep only columns that exist
    available_cols = [c for c in cols_present if c in df.columns]
    if available_cols:
        df = df[available_cols]

    st.dataframe(
        df,
        width="stretch",
        height=min(1000, 40 + 35 * min(len(df), 30)),
        hide_index=True,
    )

    # Download button
    csv = df.to_csv(index=False)
    st.download_button(
        label="Download CSV",
        data=csv,
        file_name="terminal_feed.csv",
        mime="text/csv",
        key="dl_csv",
    )
