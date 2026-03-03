"""Tab: FMP AI — LLM analysis enriched with multi-layer financial data.

Combines data from FMP, TradingView, Finnhub, and Benzinga to build
the richest possible context for LLM analysis.  Data layers include:
quotes, profiles, ratios, technicals, economic calendar, sector performance,
social sentiment, analyst forecasts, analyst ratings, earnings calendar,
insider trades, and congressional trades.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
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

try:
    from terminal_technicals import fetch_technicals
    _TV_AVAILABLE = True
except ImportError:
    _TV_AVAILABLE = False

try:
    from terminal_finnhub import fetch_social_sentiment_batch, is_available as _finnhub_available
    _FINNHUB_AVAILABLE = _finnhub_available()
except ImportError:
    _FINNHUB_AVAILABLE = False

try:
    from terminal_forecast import fetch_forecast
    _FORECAST_AVAILABLE = True
except ImportError:
    _FORECAST_AVAILABLE = False

try:
    from terminal_poller import (
        fetch_economic_calendar,
        fetch_sector_performance,
        fetch_benzinga_ratings,
        fetch_benzinga_earnings,
    )
    _POLLER_AVAILABLE = True
except ImportError:
    _POLLER_AVAILABLE = False

logger = logging.getLogger(__name__)

_SAVE_DIR = Path(os.getenv("AI_INSIGHTS_DIR", os.path.expanduser("~/Downloads")))


def _question_to_slug(question: str) -> str:
    """Derive a short filesystem-safe slug from the question."""
    # Try to match known preset labels
    _PRESET_SLUGS = {
        "market pulse": "MarketPulse",
        "top movers": "TopMovers",
        "risk signals": "RiskSignals",
        "sector themes": "SectorThemes",
        "trade ideas": "TradeIdeas",
        "outlook": "Outlook",
    }
    q_lower = question.lower()
    for keyword, slug in _PRESET_SLUGS.items():
        if keyword in q_lower:
            return slug
    # Fallback: first 30 chars normalised
    import re as _re
    slug = _re.sub(r"[^a-zA-Z0-9]+", "_", question[:30]).strip("_")
    return slug or "Custom"


def _save_fmp_ai_result(question: str, answer: str, model: str,
                        n_articles: int, n_tickers: int,
                        n_fmp: int) -> tuple[str, str]:
    """Build save content and filename. Returns (content, filename)."""
    now = datetime.now(timezone.utc)
    slug = _question_to_slug(question)
    ts_file = now.strftime("%Y%m%d_%H%M%S")
    ts_display = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    fname = f"AI_{slug}_{ts_file}.txt"
    separator = "=" * 72
    content = (
        f"{separator}\n"
        f"Saved:    {ts_display}\n"
        f"Model:    {model}\n"
        f"Articles: {n_articles}  |  Tickers: {n_tickers}  |  FMP: {n_fmp}\n"
        f"Question: {question}\n"
        f"{separator}\n\n"
        f"{answer}\n"
    )
    return content, fname


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

    # --- Custom question input (form ensures Enter triggers reliably) ---
    st.markdown("##### Ask a Custom Question")

    with st.form("fmp_ai_custom_form", clear_on_submit=False):
        custom_q = st.text_input(
            "Your question about the current market data:",
            placeholder="e.g. What are the key catalysts for NVDA today?",
            key="fmp_ai_custom_question",
        )
        _form_submitted = st.form_submit_button(
            "▶️ Ask AI", use_container_width=True,
        )
        if _form_submitted:
            _q = (custom_q or "").strip()
            if _q:
                st.session_state["fmp_ai_selected_question"] = _q
                st.session_state["fmp_ai_run_requested"] = True
            else:
                st.warning("Please enter a question first.")

    _qa_c1, _qa_c2 = st.columns([1, 2])
    with _qa_c1:
        if st.button("🔁 Ask Again", key="fmp_ai_regenerate", width='stretch',
                      help="Re-run the last question with fresh data"):
            _q = (st.session_state.get("fmp_ai_selected_question") or "").strip()
            if _q:
                st.session_state["fmp_ai_run_requested"] = True
                st.rerun()
            else:
                st.warning("No previous question — type one above and press Enter.")
    with _qa_c2:
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

    # Determine run state — consume flag immediately so a crash
    # doesn't leave it stuck True and cause infinite retry loops.
    question = str(st.session_state.get("fmp_ai_selected_question") or "").strip()
    run_requested = bool(st.session_state.get("fmp_ai_run_requested", False))
    if run_requested:
        st.session_state["fmp_ai_run_requested"] = False

    if run_requested and question:
        # Guard: suppress auto-refresh while this long-running block executes.
        # We use _fmp_ai_executing (checked by the auto-refresh fragment)
        # instead of touching fmp_ai_pause_auto_refresh, because that key
        # is bound to a st.toggle widget and cannot be set programmatically
        # after the widget has been instantiated.
        st.session_state["_fmp_ai_executing"] = True

        try:
            _status_ctr = st.status("Running AI analysis…", expanded=True)
            with _status_ctr:
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
                    st.write(f"📊 Fetching FMP data for {len(_top_tickers)} tickers…")
                    fmp_data = assemble_fmp_data(fmp_key, _top_tickers)
                    if fmp_data:
                        st.session_state["_cached_fmp_data"] = fmp_data
                # Fall back to cached FMP data if fresh fetch returned nothing
                if not fmp_data and st.session_state.get("_cached_fmp_data"):
                    fmp_data = st.session_state["_cached_fmp_data"]

                # --- Fetch TradingView technicals for top tickers ---
                technicals: dict[str, dict] | None = None
                if _TV_AVAILABLE and _top_tickers:
                    import time as _time
                    _TECH_BUDGET_S = 30.0
                    _tech_start = _time.time()
                    st.write(f"📈 Fetching technicals for {min(len(_top_tickers), 8)} tickers…")
                    _tech_ctx: dict[str, dict] = {}
                    for _sym in _top_tickers[:8]:
                        if _time.time() - _tech_start > _TECH_BUDGET_S:
                            logger.info("FMP AI technicals budget exceeded after %d tickers", len(_tech_ctx))
                            break
                        _r = fetch_technicals(_sym, "15m")
                        if _r.error:
                            continue
                        _indicators = {}
                        for _od in (_r.osc_detail or []):
                            _indicators[_od["name"]] = {
                                "value": _od["value"],
                                "action": _od["action"],
                            }
                        _tech_ctx[_sym] = {
                            "summary": _r.summary_signal,
                            "oscillators": _r.osc_signal,
                            "moving_averages": _r.ma_signal,
                            "indicators": _indicators,
                        }
                    if _tech_ctx:
                        technicals = _tech_ctx
                        st.session_state["_cached_fmp_technicals"] = _tech_ctx
                if technicals is None and st.session_state.get("_cached_fmp_technicals"):
                    technicals = st.session_state["_cached_fmp_technicals"]

                # --- Fetch economic calendar (today's macro events) ---
                st.write("📅 Fetching economic calendar…")
                econ_cal: list[dict[str, Any]] | None = None
                if _POLLER_AVAILABLE and fmp_key:
                    try:
                        _today = date.today().isoformat()
                        _raw_cal = fetch_economic_calendar(fmp_key, _today, _today)
                        if _raw_cal:
                            econ_cal = [
                                {
                                    "event": e.get("event", ""),
                                    "country": e.get("country", ""),
                                    "estimate": e.get("estimate"),
                                    "actual": e.get("actual"),
                                    "previous": e.get("previous"),
                                    "impact": e.get("impact", ""),
                                    "date": e.get("date", ""),
                                }
                                for e in _raw_cal
                                if (e.get("country") or "").upper() in ("US", "USA", "")
                                and e.get("event")
                            ][:25]
                            if econ_cal:
                                st.session_state["_cached_econ_cal"] = econ_cal
                    except Exception as exc:
                        logger.debug("FMP AI economic calendar fetch failed: %s", exc)
                if not econ_cal:
                    econ_cal = st.session_state.get("_cached_econ_cal")

                # --- Fetch sector performance ---
                sector_perf: list[dict[str, Any]] | None = None
                if _POLLER_AVAILABLE and fmp_key:
                    try:
                        _raw_sectors = fetch_sector_performance(fmp_key)
                        if _raw_sectors:
                            sector_perf = [
                                {"sector": s.get("sector", ""), "change_pct": round(s.get("changesPercentage", 0), 3)}
                                for s in _raw_sectors if s.get("sector")
                            ]
                            if sector_perf:
                                st.session_state["_cached_sector_perf"] = sector_perf
                    except Exception as exc:
                        logger.debug("FMP AI sector performance fetch failed: %s", exc)
                if not sector_perf:
                    sector_perf = st.session_state.get("_cached_sector_perf")

                # --- Fetch Finnhub social sentiment (Reddit + Twitter) ---
                st.write("💬 Fetching social sentiment…")
                social_sent: dict[str, Any] | None = None
                if _FINNHUB_AVAILABLE and _top_tickers:
                    try:
                        _raw_social = fetch_social_sentiment_batch(_top_tickers[:10])
                        if _raw_social:
                            social_sent = {
                                sym: {
                                    "reddit_mentions": s.reddit_mentions,
                                    "twitter_mentions": s.twitter_mentions,
                                    "total_mentions": s.total_mentions,
                                    "score": s.score,
                                    "label": s.sentiment_label,
                                }
                                for sym, s in _raw_social.items()
                            }
                            if social_sent:
                                st.session_state["_cached_social_sent"] = social_sent
                    except Exception as exc:
                        logger.debug("FMP AI social sentiment fetch failed: %s", exc)
                if not social_sent:
                    social_sent = st.session_state.get("_cached_social_sent")

                # --- Fetch analyst forecasts (price targets, ratings, upgrades) ---
                st.write("🔮 Fetching analyst forecasts…")
                forecasts_ctx: dict[str, Any] | None = None
                if _FORECAST_AVAILABLE and _top_tickers:
                    try:
                        _fc_data: dict[str, Any] = {}
                        for _sym in _top_tickers[:8]:
                            _fc = fetch_forecast(_sym)
                            if not _fc.has_data:
                                continue
                            _entry: dict[str, Any] = {}
                            if _fc.price_target:
                                _entry["price_target"] = {
                                    "current": _fc.price_target.current_price,
                                    "target_mean": _fc.price_target.target_mean,
                                    "target_high": _fc.price_target.target_high,
                                    "target_low": _fc.price_target.target_low,
                                    "upside_pct": round(_fc.price_target.upside_pct, 1),
                                }
                            if _fc.rating:
                                _entry["rating"] = {
                                    "consensus": _fc.rating.consensus,
                                    "strong_buy": _fc.rating.strong_buy,
                                    "buy": _fc.rating.buy,
                                    "hold": _fc.rating.hold,
                                    "sell": _fc.rating.sell,
                                    "strong_sell": _fc.rating.strong_sell,
                                }
                            if _fc.upgrades_downgrades:
                                _entry["recent_changes"] = [
                                    {
                                        "date": ud.date,
                                        "firm": ud.firm,
                                        "action": ud.action,
                                        "to": ud.to_grade,
                                        "from": ud.from_grade,
                                    }
                                    for ud in _fc.upgrades_downgrades[:5]
                                ]
                            if _entry:
                                _fc_data[_sym] = _entry
                        if _fc_data:
                            forecasts_ctx = _fc_data
                            st.session_state["_cached_forecasts"] = _fc_data
                    except Exception as exc:
                        logger.debug("FMP AI analyst forecast fetch failed: %s", exc)
                if not forecasts_ctx:
                    forecasts_ctx = st.session_state.get("_cached_forecasts")

                # --- Fetch Benzinga analyst ratings ---
                st.write("📊 Fetching Benzinga ratings & earnings…")
                bz_ratings: list[dict[str, Any]] | None = None
                if _POLLER_AVAILABLE:
                    _bz_key = getattr(cfg, "benzinga_api_key", "")
                    if _bz_key:
                        try:
                            _today_str = date.today().isoformat()
                            _week_ago = (date.today() - timedelta(days=7)).isoformat()
                            _raw_ratings = fetch_benzinga_ratings(
                                _bz_key, date_from=_week_ago, date_to=_today_str, page_size=30,
                            )
                            if _raw_ratings:
                                bz_ratings = [
                                    {
                                        "ticker": r.get("ticker", ""),
                                        "analyst": r.get("analyst", ""),
                                        "rating_current": r.get("rating_current", ""),
                                        "rating_prior": r.get("rating_prior", ""),
                                        "action": r.get("action_company", "") or r.get("action_pt", ""),
                                        "pt_current": r.get("pt_current", ""),
                                        "pt_prior": r.get("pt_prior", ""),
                                        "date": r.get("date", ""),
                                    }
                                    for r in _raw_ratings if r.get("ticker")
                                ][:20]
                                if bz_ratings:
                                    st.session_state["_cached_bz_ratings"] = bz_ratings
                        except Exception as exc:
                            logger.debug("FMP AI Benzinga ratings fetch failed: %s", exc)
                if not bz_ratings:
                    bz_ratings = st.session_state.get("_cached_bz_ratings")

                # --- Fetch Benzinga earnings calendar ---
                bz_earnings: list[dict[str, Any]] | None = None
                if _POLLER_AVAILABLE:
                    _bz_key = getattr(cfg, "benzinga_api_key", "")
                    if _bz_key:
                        try:
                            _today_str = date.today().isoformat()
                            _week_ahead = (date.today() + timedelta(days=7)).isoformat()
                            _week_ago = (date.today() - timedelta(days=3)).isoformat()
                            _raw_earn = fetch_benzinga_earnings(
                                _bz_key, date_from=_week_ago, date_to=_week_ahead, page_size=30,
                            )
                            if _raw_earn:
                                bz_earnings = [
                                    {
                                        "ticker": e.get("ticker", ""),
                                        "name": e.get("name", ""),
                                        "date": e.get("date", ""),
                                        "date_confirmed": e.get("date_confirmed", ""),
                                        "time": e.get("time", ""),
                                        "eps_estimate": e.get("eps_estimate"),
                                        "eps_actual": e.get("eps_actual"),
                                        "revenue_estimate": e.get("revenue_estimate"),
                                        "revenue_actual": e.get("revenue_actual"),
                                        "eps_surprise": e.get("eps_surprise"),
                                    }
                                    for e in _raw_earn if e.get("ticker")
                                ][:20]
                                if bz_earnings:
                                    st.session_state["_cached_bz_earnings"] = bz_earnings
                        except Exception as exc:
                            logger.debug("FMP AI Benzinga earnings fetch failed: %s", exc)
                if not bz_earnings:
                    bz_earnings = st.session_state.get("_cached_bz_earnings")

                # --- Fetch FMP insider trades (via open_prep.macro) ---
                st.write("🔍 Fetching insider & congressional trades…")
                insider_trades: list[dict[str, Any]] | None = None
                if fmp_key:
                    try:
                        from open_prep.macro import FMPClient
                        _fmp_c = FMPClient(api_key=fmp_key)
                        _raw_insider = _fmp_c.get_insider_trading_latest(limit=30)
                        if _raw_insider:
                            insider_trades = [
                                {
                                    "symbol": t.get("symbol", ""),
                                    "name": (t.get("reportingName") or t.get("ownerName", ""))[:40],
                                    "type": t.get("transactionType", ""),
                                    "shares": t.get("securitiesTransacted"),
                                    "price": t.get("price"),
                                    "value": t.get("value"),
                                    "date": t.get("filingDate", ""),
                                }
                                for t in _raw_insider if t.get("symbol")
                            ][:15]
                            if insider_trades:
                                st.session_state["_cached_insider_trades"] = insider_trades
                    except Exception as exc:
                        logger.debug("FMP AI insider trades fetch failed: %s", exc)
                if not insider_trades:
                    insider_trades = st.session_state.get("_cached_insider_trades")

                # --- Fetch Congressional trades (Senate + House) ---
                congress_trades: list[dict[str, Any]] | None = None
                if fmp_key:
                    try:
                        from open_prep.macro import FMPClient
                        _fmp_c = FMPClient(api_key=fmp_key)
                        _raw_senate = _fmp_c.get_senate_trading(limit=15)
                        _raw_house = _fmp_c.get_house_trading(limit=15)
                        _combined = []
                        for t in (_raw_senate or []) + (_raw_house or []):
                            if t.get("ticker") or t.get("symbol"):
                                _combined.append({
                                    "ticker": t.get("ticker") or t.get("symbol", ""),
                                    "member": (t.get("firstName", "") + " " + t.get("lastName", "")).strip()
                                              or t.get("representative", ""),
                                    "chamber": "Senate" if t in (_raw_senate or []) else "House",
                                    "type": t.get("type", "") or t.get("transactionType", ""),
                                    "amount": t.get("amount", ""),
                                    "date": t.get("transactionDate") or t.get("disclosureDate", ""),
                                })
                        if _combined:
                            congress_trades = _combined[:15]
                            st.session_state["_cached_congress_trades"] = congress_trades
                    except Exception as exc:
                        logger.debug("FMP AI congressional trades fetch failed: %s", exc)
                if not congress_trades:
                    congress_trades = st.session_state.get("_cached_congress_trades")

                # --- Count enrichment layers for metadata ---
                _n_layers = sum(1 for x in [
                    fmp_data, technicals, econ_cal, sector_perf,
                    social_sent, forecasts_ctx, bz_ratings, bz_earnings,
                    insider_trades, congress_trades, macro,
                ] if x)

                st.write(f"🤖 Assembling {_n_layers}-layer context and querying AI…")
                context_json = assemble_context(
                    feed,
                    fmp_data=fmp_data,
                    technicals=technicals,
                    macro=macro,
                    economic_calendar=econ_cal,
                    sector_performance=sector_perf,
                    social_sentiment=social_sent,
                    analyst_forecasts=forecasts_ctx,
                    analyst_ratings=bz_ratings,
                    earnings_calendar=bz_earnings,
                    insider_trades=insider_trades,
                    congressional_trades=congress_trades,
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
                    "enrichment_layers": _n_layers,
                    "error": result.error,
                    "question": question,
                }
                st.session_state["fmp_ai_last_context_json"] = context_json
                _status_ctr.update(label="AI analysis complete ✅", state="complete", expanded=False)
        finally:
            st.session_state["_fmp_ai_executing"] = False

    # --- Display last persisted result ---
    last_result = st.session_state.get("fmp_ai_last_result")
    if not last_result:
        st.caption("Click a preset or type a question and press Enter (or Ask AI).")
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
    _layers = int(last_result.get("enrichment_layers", 0))
    meta_parts = [f"Model: `{result.model}`"]
    if result.cached:
        meta_parts.append("⚡ cached")
    meta_parts.append(f"{result.context_articles} articles")
    meta_parts.append(f"{result.context_tickers} tickers")
    meta_parts.append(f"🏦 {result.fmp_tickers} FMP quotes")
    if _layers:
        meta_parts.append(f"🔗 {_layers} data layers")
    st.caption(" · ".join(meta_parts))

    # The answer
    st.markdown(result.answer)

    # --- Save to file ---
    _save_content, _save_fname = _save_fmp_ai_result(
        question=str(last_result.get("question") or ""),
        answer=result.answer,
        model=result.model,
        n_articles=result.context_articles,
        n_tickers=result.context_tickers,
        n_fmp=result.fmp_tickers,
    )
    st.download_button(
        "💾 Download AI report",
        data=_save_content,
        file_name=_save_fname,
        mime="text/plain",
        key="fmp_ai_save_to_file",
    )

    # --- Divider and context details ---
    with st.expander("📋 Context sent to AI (multi-layer enriched)"):
        st.caption(
            f"Top {min(40, len(feed))} articles by |score|, "
            f"up to 30 ticker summaries, top 15 segments, "
            f"+ FMP quotes/profiles, technicals, economic calendar, "
            f"sector performance, social sentiment, analyst forecasts, "
            f"Benzinga ratings/earnings, insider & congressional trades."
        )
        st.json(context_json)
