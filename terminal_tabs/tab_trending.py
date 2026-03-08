"""Tab: Trending — trending concepts (service decommissioned)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from terminal_newsapi import newsapi_available, fetch_trending_concepts

from terminal_ui_helpers import safe_markdown_text


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the Trending Topics tab."""
    st.subheader("📈 Trending Topics")
    st.caption("NewsAPI.ai trending integration has been decommissioned.")

    if not newsapi_available():
        st.info("Trending Topics is unavailable because the NewsAPI.ai service was removed.")
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
