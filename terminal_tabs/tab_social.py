"""Tab: Social — social-media buzz from NewsAPI.ai."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_newsapi import (
    fetch_social_buzz,
    is_available as newsapi_available,
)
from terminal_ui_helpers import safe_markdown_text, safe_url


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Social Buzz tab."""
    st.subheader("💬 Social Buzz")
    st.caption("Social-media sentiment and buzz tracking.")

    if not newsapi_available():
        st.info("Set `NEWSAPI_AI_KEY` in `.env` for social buzz data.")
        return

    buzz = fetch_social_buzz(count=20)
    if not buzz:
        st.info("No social buzz data available.")
        return

    for item in buzz:
        title = (item.get("title") or "")[:100]
        url_str = item.get("url", "")
        source = item.get("source", {}).get("title", "")
        sentiment = item.get("sentiment", 0)
        shares = item.get("shares", item.get("socialScore", 0))

        sent_icon = "🟢" if sentiment > 0 else ("🔴" if sentiment < 0 else "⚪")
        safe_title = safe_markdown_text(title)
        link = f"[{safe_title}]({safe_url(url_str)})" if url_str else safe_title

        with st.container():
            cols = st.columns([4, 1, 1])
            with cols[0]:
                st.markdown(f"{sent_icon} **{link}**")
                if source:
                    st.caption(f"*{source}*")
            with cols[1]:
                if sentiment:
                    st.metric("Sentiment", f"{sentiment:+.2f}")
            with cols[2]:
                if shares:
                    st.metric("Buzz", f"{shares:,}")
