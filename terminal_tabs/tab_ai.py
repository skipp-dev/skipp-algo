"""Tab: AI Insights — LLM-powered analysis of the live news feed."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
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

_SAVE_DIR = Path(os.getenv("AI_INSIGHTS_DIR", os.path.expanduser("~/Downloads")))


def _save_ai_result(question: str, answer: str, model: str,
                    n_articles: int, n_tickers: int) -> str:
    """Append an AI result to a timestamped text file and return the path."""
    _SAVE_DIR.mkdir(parents=True, exist_ok=True)
    fpath = _SAVE_DIR / "ai_trade_ideas.txt"
    now = datetime.now(timezone.utc)
    ts_display = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    separator = "=" * 72
    block = (
        f"\n{separator}\n"
        f"Saved:    {ts_display}\n"
        f"Model:    {model}\n"
        f"Articles: {n_articles}  |  Tickers: {n_tickers}\n"
        f"Question: {question}\n"
        f"{separator}\n\n"
        f"{answer}\n"
    )
    with open(fpath, "a", encoding="utf-8") as fh:
        fh.write(block)
    return str(fpath)


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

    # Persist AI workflow state across Streamlit reruns so results do not
    # disappear when auto-refresh triggers a rerender.
    st.session_state.setdefault("ai_selected_question", "")
    st.session_state.setdefault("ai_run_requested", False)
    st.session_state.setdefault("ai_last_result", None)
    st.session_state.setdefault("ai_last_context_json", "")
    st.session_state.setdefault("ai_pause_auto_refresh", False)

    # --- Preset question buttons ---
    st.markdown("##### Quick Analysis")
    cols = st.columns(3)
    for i, (label, question) in enumerate(PRESET_QUESTIONS):
        col = cols[i % 3]
        if col.button(label, key=f"ai_preset_{i}", use_container_width=True):
            st.session_state["ai_selected_question"] = question
            st.session_state["ai_run_requested"] = True

    # --- Custom question input ---
    st.markdown("##### Ask a Custom Question")
    custom_q = st.text_input(
        "Your question about the current market data:",
        placeholder="e.g. What are the key catalysts for NVDA today?",
        key="ai_custom_question",
    )

    _qa_c1, _qa_c2, _qa_c3 = st.columns([1, 1, 2])
    with _qa_c1:
        if st.button("▶️ Generate", key="ai_generate", use_container_width=True):
            _q = (custom_q or "").strip()
            if _q:
                st.session_state["ai_selected_question"] = _q
                st.session_state["ai_run_requested"] = True
            else:
                st.warning("Please enter a question first.")
    with _qa_c2:
        if st.button("🔁 Regenerate", key="ai_regenerate", use_container_width=True):
            _q = (st.session_state.get("ai_selected_question") or "").strip()
            if _q:
                st.session_state["ai_run_requested"] = True
            else:
                st.warning("No previous question available yet.")
    with _qa_c3:
        st.session_state.ai_pause_auto_refresh = st.toggle(
            "Pause auto-refresh while reviewing AI result",
            value=bool(st.session_state.get("ai_pause_auto_refresh", False)),
            key="ai_pause_auto_refresh_toggle",
            help=(
                "Prevents automatic page jumps while you read AI output. "
                "Background polling can continue; UI reruns are paused."
            ),
        )

    if st.button("🧹 Clear AI result", key="ai_clear_result"):
        st.session_state["ai_last_result"] = None
        st.session_state["ai_last_context_json"] = ""
        st.session_state["ai_selected_question"] = ""
        st.session_state["ai_run_requested"] = False

    # Determine run state
    question = str(st.session_state.get("ai_selected_question") or "").strip()
    run_requested = bool(st.session_state.get("ai_run_requested", False))

    # Run the LLM query only when explicitly requested. This prevents
    # repeated calls on every auto-refresh rerun.
    if run_requested and question:
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

        st.session_state["ai_last_result"] = {
            "answer": result.answer,
            "model": result.model,
            "cached": result.cached,
            "context_articles": result.context_articles,
            "context_tickers": result.context_tickers,
            "error": result.error,
            "question": question,
        }
        st.session_state["ai_last_context_json"] = context_json
        st.session_state["ai_run_requested"] = False

    # --- Display last persisted result ---
    last_result = st.session_state.get("ai_last_result")
    if not last_result:
        st.caption("Click a preset or enter a question and press Generate.")
        return

    _last_question = safe_markdown_text(str(last_result.get("question") or ""))
    if _last_question:
        st.markdown(f"**Question:** {_last_question}")

    if last_result.get("error"):
        st.error(f"⚠️ {safe_markdown_text(str(last_result.get('error') or 'Unknown AI error'))}")
        return

    result = LLMResponse(
        answer=str(last_result.get("answer") or ""),
        model=str(last_result.get("model") or ""),
        cached=bool(last_result.get("cached", False)),
        context_articles=int(last_result.get("context_articles", 0)),
        context_tickers=int(last_result.get("context_tickers", 0)),
        error="",
    )
    context_json = str(st.session_state.get("ai_last_context_json") or "")

    # Response metadata
    meta_parts = [f"Model: `{result.model}`"]
    if result.cached:
        meta_parts.append("⚡ cached")
    meta_parts.append(f"{result.context_articles} articles")
    meta_parts.append(f"{result.context_tickers} tickers")
    st.caption(" · ".join(meta_parts))

    # The answer
    st.markdown(result.answer)

    # --- Save to file ---
    if st.button("💾 Save AI result to file", key="ai_save_to_file"):
        try:
            saved_path = _save_ai_result(
                question=str(last_result.get("question") or ""),
                answer=result.answer,
                model=result.model,
                n_articles=result.context_articles,
                n_tickers=result.context_tickers,
            )
            st.success(f"Saved to `{saved_path}`")
        except Exception as exc:
            logger.warning("Failed to save AI result: %s", exc, exc_info=True)
            st.error(f"Could not save: {exc}")

    # --- Divider and context details ---
    with st.expander("📋 Context sent to AI"):
        st.caption(
            f"Top {min(40, len(feed))} articles by |score|, "
            f"up to 30 ticker summaries, top 15 segments."
        )
        st.json(context_json)
