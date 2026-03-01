"""Tab: Breaking News — breaking stories from NewsAPI.ai."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_newsapi import (
    fetch_breaking_events,
    is_available as newsapi_available,
)
from terminal_ui_helpers import safe_markdown_text


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Breaking News tab."""
    st.subheader("🔔 Breaking News")
    st.caption("Latest breaking events from NewsAPI.ai — updates every cycle.")

    if not newsapi_available():
        st.info("Set `NEWSAPI_AI_KEY` in `.env` for breaking news.")
        return

    events = fetch_breaking_events(count=30)
    if not events:
        st.info("No breaking news events available right now.")
        return

    for ev in events:
        safe_title = safe_markdown_text(ev.title or "(no title)")
        sent = f"{ev.sentiment_icon} {ev.sentiment_label}"
        cats = ", ".join(ev.categories[:3]) if ev.categories else ""

        with st.container():
            st.markdown(f"**{safe_title}**")
            parts: list[str] = []
            if ev.event_date:
                parts.append(ev.event_date[:16])
            if ev.article_count:
                parts.append(f"{ev.article_count} articles")
            parts.append(sent)
            if cats:
                parts.append(cats)
            if ev.location:
                parts.append(ev.location)
            st.caption(" · ".join(parts))
            if ev.summary:
                st.markdown(ev.summary[:300] + ("…" if len(ev.summary) > 300 else ""))
            st.divider()
