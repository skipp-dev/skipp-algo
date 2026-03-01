"""Tab: Trending — trending topics from NewsAPI.ai."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_newsapi import (
    fetch_trending_topics,
    is_available as newsapi_available,
)
from terminal_ui_helpers import safe_markdown_text


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Trending Topics tab."""
    st.subheader("📈 Trending Topics")
    st.caption("Hot topics across financial and business news.")

    if not newsapi_available():
        st.info("Set `NEWSAPI_AI_KEY` in `.env` for trending topics.")
        return

    topics = fetch_trending_topics(count=20)
    if not topics:
        st.info("No trending topics available.")
        return

    for i, t in enumerate(topics, 1):
        label = t.get("label") or t.get("title") or t.get("topic", "?")
        weight = t.get("wgt", t.get("weight", 0))
        safe_label = safe_markdown_text(str(label))

        if weight:
            st.markdown(f"**{i}.** {safe_label} · weight: `{weight}`")
        else:
            st.markdown(f"**{i}.** {safe_label}")
