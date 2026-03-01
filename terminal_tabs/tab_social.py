"""Tab: Social — social-media buzz from NewsAPI.ai."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_newsapi import (
    fetch_social_ranked_articles,
    is_available as newsapi_available,
)
from terminal_ui_helpers import safe_markdown_text, safe_url


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Social Buzz tab."""
    st.subheader("💬 Social Buzz")
    st.caption("Most-shared financial news — ranked by social score.")

    if not newsapi_available():
        st.info("Set `NEWSAPI_AI_KEY` in `.env` for social buzz data.")
        return

    articles = fetch_social_ranked_articles(count=20)
    if not articles:
        st.info("No social buzz data available.")
        return

    for art in articles:
        safe_title = safe_markdown_text((art.title or "(no title)")[:120])
        link = f"[{safe_title}]({safe_url(art.url)})" if art.url else safe_title

        with st.container():
            cols = st.columns([4, 1, 1])
            with cols[0]:
                st.markdown(f"{art.sentiment_icon} **{link}**")
                parts: list[str] = []
                if art.source:
                    parts.append(f"*{art.source}*")
                if art.date:
                    parts.append(art.date[:16])
                if parts:
                    st.caption(" · ".join(parts))
            with cols[1]:
                if art.sentiment is not None:
                    st.metric("Sentiment", f"{art.sentiment:+.2f}")
            with cols[2]:
                if art.social_score:
                    st.metric("Buzz", f"{art.social_score:,}")
