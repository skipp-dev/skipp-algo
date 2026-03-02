"""Tab: FMP AI — LLM analysis enriched with FMP financial data.

Mirrors the AI Insights tab (tab_ai.py) but fetches real-time quotes
and company profiles from Financial Modeling Prep before querying the LLM.
This allows side-by-side comparison of analysis with vs. without
institutional-grade financial data.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from terminal_ai_insights import PRESET_QUESTIONS
from terminal_fmp_insights import (
    FMPLLMResponse,
    assemble_context,
    assemble_fmp_data,
    query_fmp_llm,
)
from terminal_ui_helpers import safe_markdown_text

logger = logging.getLogger(__name__)

_SAVE_DIR = Path(os.getenv("AI_INSIGHTS_DIR", os.path.expanduser("~/Downloads")))


def _save_fmp_ai_result(question: str, answer: str, model: str,
                        n_articles: int, n_tickers: int,
                        n_fmp: int) -> str:
    """Append an FMP AI result to a timestamped text file and return the path."""
    _SAVE_DIR.mkdir(parents=True, exist_ok=True)
    fpath = _SAVE_DIR / "fmp_ai_trade_ideas.txt"
    now = datetime.now(timezone.utc)
    ts_display = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    separator = "=" * 72
    block = (
        f"\n{separator}\n"
        f"Saved:    {ts_display}\n"
        f"Model:    {model}\n"
        f"Articles: {n_articles}  |  Tickers: {n_tickers}  |  FMP: {n_fmp}\n"
        f"Question: {question}\n"
        f"{separator}\n\n"
        f"{answer}\n"
    )
    with open(fpath, "a", encoding="utf-8") as fh:
        fh.write(block)
    return str(fpath)


def render(feed: list[dict[str, Any]], *, current_session: str) -> None:
    """Render the FMP AI tab."""
    cfg = st.session_state.cfg

    # Need both FMP key (for data) and OpenAI key (for LLM)
    fmp_key = getattr(cfg, "fmp_api_key", "")
    openai_key = getattr(cfg, "openai_api_key", "")

    if not fmp_key:
        st.warning("💡 Set `FMP_API_KEY` in your `.env` file to enable FMP AI.")
        st.info(
            "This tab uses the FMP API to fetch real-time quotes, company "
            "profiles, and financial data — then sends the enriched context "
            "to the LLM for analysis.  Add your FMP key and restart."
        )
        return

    if not openai_key:
        st.warning("💡 Set `OPENAI_API_KEY` in your `.env` file to enable AI analysis.")
        st.info(
            "FMP AI enriches the context with financial data from FMP, "
            "then uses OpenAI (GPT-4o) for the actual analysis.  "
            "Both keys are required."
        )
        return

    if not feed:
        st.info("No articles in the feed yet — wait for the first poll to complete.")
        return

    st.caption(f"Feed: {len(feed)} articles · Session: {current_session} · 🏦 FMP-enriched")

    # Persist FMP AI workflow state (separate keys from AI Insights)
    st.session_state.setdefault("fmp_ai_selected_question", "")
    st.session_state.setdefault("fmp_ai_run_requested", False)
    st.session_state.setdefault("fmp_ai_last_result", None)
    st.session_state.setdefault("fmp_ai_last_context_json", "")
    st.session_state.setdefault("fmp_ai_pause_auto_refresh", False)

    # --- Preset question buttons ---
    st.markdown("##### Quick Analysis")
    cols = st.columns(3)
    for i, (label, question) in enumerate(PRESET_QUESTIONS):
        col = cols[i % 3]
        if col.button(label, key=f"fmp_ai_preset_{i}", width='stretch'):
            st.session_state["fmp_ai_selected_question"] = question
            st.session_state["fmp_ai_run_requested"] = True
            st.rerun()

    # --- Custom question input ---
    st.markdown("##### Ask a Custom Question")

    def _on_custom_q_submit():
        """Trigger FMP AI query when user presses Enter."""
        q = (st.session_state.get("fmp_ai_custom_question") or "").strip()
        if q:
            st.session_state["fmp_ai_selected_question"] = q
            st.session_state["fmp_ai_run_requested"] = True

    custom_q = st.text_input(
        "Your question about the current market data:",
        placeholder="e.g. What are the key catalysts for NVDA today?",
        key="fmp_ai_custom_question",
        on_change=_on_custom_q_submit,
    )

    _qa_c1, _qa_c2, _qa_c3 = st.columns([1, 1, 2])
    with _qa_c1:
        if st.button("▶️ Generate", key="fmp_ai_generate", width='stretch'):
            _q = (custom_q or "").strip()
            if _q:
                st.session_state["fmp_ai_selected_question"] = _q
                st.session_state["fmp_ai_run_requested"] = True
            else:
                st.warning("Please enter a question first.")
    with _qa_c2:
        if st.button("🔁 Regenerate", key="fmp_ai_regenerate", width='stretch'):
            _q = (st.session_state.get("fmp_ai_selected_question") or "").strip()
            if _q:
                st.session_state["fmp_ai_run_requested"] = True
            else:
                st.warning("No previous question available yet.")
    with _qa_c3:
        st.toggle(
            "Pause auto-refresh while reviewing AI result",
            key="fmp_ai_pause_auto_refresh",
            help=(
                "Prevents automatic page jumps while you read AI output. "
                "Background polling can continue; UI reruns are paused."
            ),
        )

    if st.button("🧹 Clear AI result", key="fmp_ai_clear_result"):
        st.session_state["fmp_ai_last_result"] = None
        st.session_state["fmp_ai_last_context_json"] = ""
        st.session_state["fmp_ai_selected_question"] = ""
        st.session_state["fmp_ai_run_requested"] = False
        st.rerun()

    # Determine run state
    question = str(st.session_state.get("fmp_ai_selected_question") or "").strip()
    run_requested = bool(st.session_state.get("fmp_ai_run_requested", False))

    if run_requested and question:
        macro = st.session_state.get("_cached_macro")

        # --- Fetch FMP financial data for top tickers ---
        fmp_data: dict[str, Any] | None = None
        _tk_scores: dict[str, float] = {}
        for _d in feed:
            _tk = (_d.get("ticker") or "").upper().strip()
            if not _tk or _tk in ("?", "N/A", ""):
                continue
            _sc = abs(float(_d.get("news_score") or _d.get("composite_score") or 0))
            _tk_scores[_tk] = max(_tk_scores.get(_tk, 0), _sc)
        _top_tickers = sorted(_tk_scores, key=_tk_scores.get, reverse=True)[:12]

        if _top_tickers:
            with st.spinner(f"Fetching FMP data for {len(_top_tickers)} tickers…"):
                fmp_data = assemble_fmp_data(fmp_key, _top_tickers)
                if fmp_data:
                    st.session_state["_cached_fmp_data"] = fmp_data
        # Fall back to cached FMP data if fresh fetch returned nothing
        if not fmp_data and st.session_state.get("_cached_fmp_data"):
            fmp_data = st.session_state["_cached_fmp_data"]

        with st.spinner("Assembling FMP-enriched context and querying AI…"):
            context_json = assemble_context(
                feed,
                fmp_data=fmp_data,
                macro=macro,
                max_articles=40,
            )
            result: FMPLLMResponse = query_fmp_llm(
                question=question,
                context_json=context_json,
                api_key=openai_key,
            )

        st.session_state["fmp_ai_last_result"] = {
            "answer": result.answer,
            "model": result.model,
            "cached": result.cached,
            "context_articles": result.context_articles,
            "context_tickers": result.context_tickers,
            "fmp_tickers": result.fmp_tickers,
            "error": result.error,
            "question": question,
        }
        st.session_state["fmp_ai_last_context_json"] = context_json
        st.session_state["fmp_ai_run_requested"] = False

    # --- Display last persisted result ---
    last_result = st.session_state.get("fmp_ai_last_result")
    if not last_result:
        st.caption("Click a preset or enter a question and press Generate.")
        return

    _last_question = safe_markdown_text(str(last_result.get("question") or ""))
    if _last_question:
        st.markdown(f"**Question:** {_last_question}")

    if last_result.get("error"):
        st.error(f"⚠️ {safe_markdown_text(str(last_result.get('error') or 'Unknown AI error'))}")
        return

    result = FMPLLMResponse(
        answer=str(last_result.get("answer") or ""),
        model=str(last_result.get("model") or ""),
        cached=bool(last_result.get("cached", False)),
        context_articles=int(last_result.get("context_articles", 0)),
        context_tickers=int(last_result.get("context_tickers", 0)),
        fmp_tickers=int(last_result.get("fmp_tickers", 0)),
        error="",
    )
    context_json = str(st.session_state.get("fmp_ai_last_context_json") or "")

    # Response metadata
    meta_parts = [f"Model: `{result.model}`"]
    if result.cached:
        meta_parts.append("⚡ cached")
    meta_parts.append(f"{result.context_articles} articles")
    meta_parts.append(f"{result.context_tickers} tickers")
    meta_parts.append(f"🏦 {result.fmp_tickers} FMP quotes")
    st.caption(" · ".join(meta_parts))

    # The answer
    st.markdown(result.answer)

    # --- Save to file ---
    if st.button("💾 Save FMP AI result to file", key="fmp_ai_save_to_file"):
        try:
            saved_path = _save_fmp_ai_result(
                question=str(last_result.get("question") or ""),
                answer=result.answer,
                model=result.model,
                n_articles=result.context_articles,
                n_tickers=result.context_tickers,
                n_fmp=result.fmp_tickers,
            )
            st.success(f"Saved to `{saved_path}`")
        except Exception as exc:
            logger.warning("Failed to save FMP AI result: %s", exc, exc_info=True)
            st.error(f"Could not save: {exc}")

    # --- Divider and context details ---
    with st.expander("📋 Context sent to AI (FMP-enriched)"):
        st.caption(
            f"Top {min(40, len(feed))} articles by |score|, "
            f"up to 30 ticker summaries, top 15 segments, "
            f"+ FMP quotes & profiles for top tickers."
        )
        st.json(context_json)
