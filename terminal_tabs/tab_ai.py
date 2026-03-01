"""Tab: AI Insights — LLM-powered analysis of the live news feed."""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from terminal_ai_insights import (
    PRESET_QUESTIONS,
    LLMResponse,
    assemble_context,
    query_llm,
)
from terminal_ui_helpers import safe_markdown_text

logger = logging.getLogger(__name__)


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the AI Insights tab."""
    cfg = st.session_state.cfg
    api_key = getattr(cfg, "openai_api_key", "")
    if not api_key:
        st.warning("💡 Set `OPENAI_API_KEY` in your `.env` file to enable AI Insights.")
        st.info(
            "This tab uses the OpenAI API (GPT-4o by default) to provide "
            "AI-powered analysis of your live news feed, sentiment data, "
            "and technicals.  Add your key and restart."
        )
        return

    if not feed:
        st.info("No articles in the feed yet — wait for the first poll to complete.")
        return

    st.caption(f"Feed: {len(feed)} articles · Session: {current_session}")

    # --- Preset question buttons ---
    st.markdown("##### Quick Analysis")
    cols = st.columns(3)
    preset_clicked: str | None = None
    for i, (label, question) in enumerate(PRESET_QUESTIONS):
        col = cols[i % 3]
        if col.button(label, key=f"ai_preset_{i}", use_container_width=True):
            preset_clicked = question

    # --- Custom question input ---
    st.markdown("##### Ask a Custom Question")
    custom_q = st.text_input(
        "Your question about the current market data:",
        placeholder="e.g. What are the key catalysts for NVDA today?",
        key="ai_custom_question",
    )

    # Determine which question to run
    question = preset_clicked or custom_q
    if not question:
        st.caption("Click a preset or type a question above to get AI analysis.")
        return

    # --- Assemble context ---
    # Gather optional technicals and macro from session state
    technicals = st.session_state.get("_cached_technicals")
    macro = st.session_state.get("_cached_macro")

    with st.spinner("Assembling context and querying AI…"):
        context_json = assemble_context(
            feed,
            technicals=technicals,
            macro=macro,
            max_articles=40,
        )
        result: LLMResponse = query_llm(
            question=question,
            context_json=context_json,
            api_key=api_key,
        )

    # --- Display result ---
    if result.error:
        st.error(f"⚠️ {safe_markdown_text(result.error)}")
        return

    # Response metadata
    meta_parts = [f"Model: `{result.model}`"]
    if result.cached:
        meta_parts.append("⚡ cached")
    meta_parts.append(f"{result.context_articles} articles")
    meta_parts.append(f"{result.context_tickers} tickers")
    st.caption(" · ".join(meta_parts))

    # The answer
    st.markdown(result.answer)

    # --- Divider and context details ---
    with st.expander("📋 Context sent to AI"):
        st.caption(
            f"Top {min(40, len(feed))} articles by |score|, "
            f"up to 30 ticker summaries, top 15 segments."
        )
        st.json(context_json)
