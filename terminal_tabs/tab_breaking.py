"""Tab: Breaking News — breaking stories from NewsAPI.ai."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_newsapi import (
    fetch_breaking_news,
    is_available as newsapi_available,
)
from terminal_ui_helpers import safe_markdown_text, safe_url


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Breaking News tab."""
    st.subheader("🔔 Breaking News")
    st.caption("Latest breaking stories from NewsAPI.ai — updates every cycle.")

    if not newsapi_available():
        st.info("Set `NEWSAPI_AI_KEY` in `.env` for breaking news.")
        return

    articles = fetch_breaking_news(count=30)
    if not articles:
        st.info("No breaking news available right now.")
        return

    for a in articles:
        title = a.get("title", "(no title)")[:120]
        url_str = a.get("url", "")
        source = a.get("source", {}).get("title", "")
        date_str = a.get("dateTimePub", a.get("date", ""))[:16]
        body = (a.get("body") or "")[:200]

        safe_title = safe_markdown_text(title)
        link = f"[{safe_title}]({safe_url(url_str)})" if url_str else safe_title

        with st.container():
            st.markdown(f"**{link}**")
            if source or date_str:
                st.caption(f"*{source}* · {date_str}")
            if body:
                st.markdown(body + "…" if len(body) >= 200 else body)
            st.divider()
