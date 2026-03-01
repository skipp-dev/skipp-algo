"""Tab: Trending — trending concepts from NewsAPI.ai."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_newsapi import (
    fetch_trending_concepts,
    is_available as newsapi_available,
)
from terminal_ui_helpers import safe_markdown_text


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Trending Topics tab."""
    st.subheader("📈 Trending Topics")
    st.caption("Hot trending concepts across financial and business news.")

    if not newsapi_available():
        st.info("Set `NEWSAPI_AI_KEY` in `.env` for trending topics.")
        return

    concepts = fetch_trending_concepts(count=20)
    if not concepts:
        st.info("No trending topics available.")
        return

    for i, c in enumerate(concepts, 1):
        safe_label = safe_markdown_text(c.label or "?")
        score_txt = f" · score: `{c.trending_score:.1f}`" if c.trending_score else ""
        arts_txt = f" · {c.article_count} articles" if c.article_count else ""
        st.markdown(f"**{i}.** {c.type_icon} {safe_label}{score_txt}{arts_txt}")
