"""Tab: FMP AI — LLM analysis enriched with multi-layer financial data.

Combines data from FMP, Finnhub, and Benzinga to build
the richest possible context for LLM analysis.  Data layers include:
quotes, profiles, ratios, technicals, economic calendar, sector performance,
social sentiment, analyst forecasts, analyst ratings, earnings calendar,
insider trades, and congressional trades.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo as _ZoneInfo

import streamlit as st

from open_prep_boundary import make_fmp_client
from terminal_ai_insights import PRESET_QUESTIONS
from terminal_fmp_insights import (
    FMPLLMResponse,
    assemble_context,
    assemble_fmp_data,
)
from terminal_internal_ai import ProducerAIInsightsClient
from terminal_ui_helpers import safe_markdown_text

try:
    from terminal_databento import fetch_databento_quote_map
    from terminal_databento import is_available as _databento_available
    _DATABENTO_AVAILABLE = _databento_available()
except ImportError:
    _DATABENTO_AVAILABLE = False

try:
    from terminal_technicals import fetch_technicals
    _TECHNICALS_AVAILABLE = True
except ImportError:
    _TECHNICALS_AVAILABLE = False

try:
    from terminal_finnhub import fetch_social_sentiment_batch
    from terminal_finnhub import is_available as _finnhub_available
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
    )
    _POLLER_AVAILABLE = True
except ImportError:
    _POLLER_AVAILABLE = False

logger = logging.getLogger(__name__)

_ET = _ZoneInfo("America/New_York")

# Wall-clock budget for the parallel enrichment phase (deep mode). The LLM
# call itself is bounded separately by the Producer client timeout (~150 s),
# so the UI hard timeout must stay above the sum of both.
_ENRICH_BUDGET_S = 45.0

# ── Background execution model ──────────────────────────────
# Each analysis run gets its OWN single-worker executor plus a cancel
# event. A hung run therefore never queues later runs behind it (the
# old module-level max_workers=1 pool did exactly that), and Cancel /
# hard-timeout can signal the worker to stop at the next checkpoint.
# Daemon threads keep the run immune to Streamlit's RerunException.


def _analysis_worker(
    *,
    feed: list[dict[str, Any]],
    question: str,
    fmp_key: str,
    producer_ai: ProducerAIInsightsClient,
    benzinga_key: str,
    macro: dict[str, Any] | None,
    cached: dict[str, Any],
    technicals_available: bool,
    finnhub_available: bool,
    forecast_available: bool,
    poller_available: bool,
    databento_available: bool,
    deep: bool = True,
    cancel: threading.Event | None = None,
    stage: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run AI analysis in a background thread.  **Thread-safe**: no Streamlit API calls."""
    return _analysis_worker_inner(
        feed=feed, question=question, fmp_key=fmp_key,
        producer_ai=producer_ai, benzinga_key=benzinga_key,
        macro=macro, cached=cached,
        technicals_available=technicals_available, finnhub_available=finnhub_available,
        forecast_available=forecast_available, poller_available=poller_available,
        databento_available=databento_available,
        deep=deep, cancel=cancel, stage=stage,
    )


def _analysis_worker_inner(
    *,
    feed: list[dict[str, Any]],
    question: str,
    fmp_key: str,
    producer_ai: ProducerAIInsightsClient,
    benzinga_key: str,
    macro: dict[str, Any] | None,
    cached: dict[str, Any],
    technicals_available: bool,
    finnhub_available: bool,
    forecast_available: bool,
    poller_available: bool,
    databento_available: bool,
    deep: bool = True,
    cancel: threading.Event | None = None,
    stage: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Inner worker — fetches enrichment layers (concurrently in deep mode),
    honours *cancel* between checkpoints, and reports progress via *stage*."""
    cancel = cancel or threading.Event()
    if stage is None:
        stage = {}
    cache_updates: dict[str, Any] = {}

    def _stage(label: str) -> None:
        stage["label"] = label

    # Session-state cache key per layer (fallback when a fresh fetch is
    # unavailable, fails, or deep mode is off).
    _CK = {
        "fmp_data": "_cached_fmp_data",
        "technicals": "_cached_fmp_technicals",
        "econ_cal": "_cached_econ_cal",
        "sector_perf": "_cached_sector_perf",
        "social_sent": "_cached_social_sent",
        "forecasts": "_cached_forecasts",
        "insider_trades": "_cached_insider_trades",
        "congress_trades": "_cached_congress_trades",
        "databento_quotes": "_cached_databento_quotes",
    }

    try:
        # --- Top tickers from feed ---
        _tk_scores: dict[str, float] = {}
        for _d in feed:
            _tk = (_d.get("ticker") or "").upper().strip()
            if not _tk or _tk in ("?", "N/A", ""):
                continue
            _sc = abs(float(_d.get("news_score") or _d.get("composite_score") or 0))
            _tk_scores[_tk] = max(_tk_scores.get(_tk, 0), _sc)
        _top_tickers = sorted(_tk_scores, key=_tk_scores.get, reverse=True)[:12]

        # --- Layer fetchers (each independent; run concurrently in deep mode) ---
        def _layer_fmp_data() -> dict[str, Any] | None:
            return assemble_fmp_data(fmp_key, _top_tickers) or None

        def _layer_technicals() -> dict[str, dict] | None:
            _TECH_BUDGET_S = 30.0
            _tech_start = time.time()
            _tech_ctx: dict[str, dict] = {}
            for _sym in _top_tickers[:8]:
                if cancel.is_set() or time.time() - _tech_start > _TECH_BUDGET_S:
                    break
                _r = fetch_technicals(_sym, "15m")
                if _r.error:
                    continue
                _indicators = {}
                for _od in (_r.osc_detail or []):
                    _indicators[_od["name"]] = {"value": _od["value"], "action": _od["action"]}
                _tech_ctx[_sym] = {
                    "summary": _r.summary_signal,
                    "oscillators": _r.osc_signal,
                    "moving_averages": _r.ma_signal,
                    "indicators": _indicators,
                }
            return _tech_ctx or None

        def _layer_econ_cal() -> list[dict[str, Any]] | None:
            _today = datetime.now(_ET).date().isoformat()
            _raw_cal = fetch_economic_calendar(fmp_key, _today, _today)
            if not _raw_cal:
                return None
            return [
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
            ][:25] or None

        def _layer_sector_perf() -> list[dict[str, Any]] | None:
            _raw_sectors = fetch_sector_performance(fmp_key)
            if not _raw_sectors:
                return None
            return [
                {"sector": s.get("sector", ""), "change_pct": round(s.get("changesPercentage", 0), 3)}
                for s in _raw_sectors if s.get("sector")
            ] or None

        def _layer_social_sent() -> dict[str, Any] | None:
            _raw_social = fetch_social_sentiment_batch(_top_tickers[:10])
            if not _raw_social:
                return None
            return {
                sym: {
                    "reddit_mentions": s.reddit_mentions,
                    "twitter_mentions": s.twitter_mentions,
                    "total_mentions": s.total_mentions,
                    "score": s.score,
                    "label": s.sentiment_label,
                }
                for sym, s in _raw_social.items()
            } or None

        def _layer_forecasts() -> dict[str, Any] | None:
            _fc_data: dict[str, Any] = {}
            for _sym in _top_tickers[:8]:
                if cancel.is_set():
                    break
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
            return _fc_data or None

        def _layer_insider() -> list[dict[str, Any]] | None:
            _fmp_c = make_fmp_client(fmp_key, timeout_seconds=10, retry_attempts=1)
            _raw_insider = _fmp_c.get_insider_trading_latest(limit=30)
            if not _raw_insider:
                return None
            return [
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
            ][:15] or None

        def _layer_congress() -> list[dict[str, Any]] | None:
            _fmp_c = make_fmp_client(fmp_key, timeout_seconds=10, retry_attempts=1)
            _raw_senate = _fmp_c.get_senate_trading(limit=15)
            _raw_house = _fmp_c.get_house_trading(limit=15)
            _combined: list[dict[str, Any]] = []
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
            return _combined[:15] or None

        def _layer_databento() -> dict[str, Any] | None:
            return fetch_databento_quote_map(_top_tickers[:30]) or None

        _jobs: dict[str, Any] = {}
        if fmp_key and _top_tickers:
            _jobs["fmp_data"] = _layer_fmp_data
        if technicals_available and _top_tickers:
            _jobs["technicals"] = _layer_technicals
        if poller_available and fmp_key:
            _jobs["econ_cal"] = _layer_econ_cal
            _jobs["sector_perf"] = _layer_sector_perf
        if finnhub_available and _top_tickers:
            _jobs["social_sent"] = _layer_social_sent
        if forecast_available and _top_tickers:
            _jobs["forecasts"] = _layer_forecasts
        if fmp_key:
            _jobs["insider_trades"] = _layer_insider
            _jobs["congress_trades"] = _layer_congress
        if databento_available and _top_tickers:
            _jobs["databento_quotes"] = _layer_databento

        _layers: dict[str, Any] = {}
        if deep and _jobs and not cancel.is_set():
            _stage(f"Fetching {len(_jobs)} market-data layers in parallel…")
            logger.info(
                "FMP AI worker: fetching %d layers in parallel (budget %.0fs)",
                len(_jobs), _ENRICH_BUDGET_S,
            )
            _pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=min(6, len(_jobs)), thread_name_prefix="fmp_ai_layer",
            )
            try:
                _futs = {_pool.submit(fn): name for name, fn in _jobs.items()}
                _deadline = time.time() + _ENRICH_BUDGET_S
                try:
                    for _fut in concurrent.futures.as_completed(_futs, timeout=_ENRICH_BUDGET_S):
                        _name = _futs[_fut]
                        try:
                            _val = _fut.result()
                        except Exception as _layer_exc:
                            logger.debug("FMP AI worker: layer %s failed: %s", _name, _layer_exc)
                            continue
                        if _val:
                            _layers[_name] = _val
                            cache_updates[_CK[_name]] = _val
                        _stage(f"Fetched {len(_layers)}/{len(_jobs)} data layers…")
                        if cancel.is_set() or time.time() > _deadline:
                            break
                except concurrent.futures.TimeoutError:
                    logger.warning(
                        "FMP AI worker: enrichment budget (%.0fs) exhausted — continuing with %d layers",
                        _ENRICH_BUDGET_S, len(_layers),
                    )
            finally:
                _pool.shutdown(wait=False, cancel_futures=True)

        def _resolved(name: str) -> Any:
            return _layers.get(name) or cached.get(_CK[name])

        fmp_data = _resolved("fmp_data")
        technicals = _resolved("technicals")
        econ_cal = _resolved("econ_cal")
        sector_perf = _resolved("sector_perf")
        social_sent = _resolved("social_sent")
        forecasts_ctx = _resolved("forecasts")
        insider_trades = _resolved("insider_trades")
        congress_trades = _resolved("congress_trades")
        databento_quotes = _resolved("databento_quotes")

        if cancel.is_set():
            return {
                "result_dict": {
                    "error": "Analysis cancelled.",
                    "question": question, "answer": "", "model": "", "cached": False,
                    "context_articles": 0, "context_tickers": 0,
                    "fmp_tickers": 0, "enrichment_layers": 0,
                },
                "context_json": "",
                "cache_updates": cache_updates,
            }

        # --- Enrichment layer count ---
        _n_layers = sum(1 for x in [
            fmp_data, technicals, econ_cal, sector_perf,
            social_sent, forecasts_ctx,
            insider_trades, congress_trades, macro, databento_quotes,
        ] if x)

        logger.info("FMP AI worker: assembling %d-layer context and querying LLM…", _n_layers)
        _stage(f"Querying the model with a {_n_layers}-layer context…")
        context_json = assemble_context(
            feed,
            fmp_data=fmp_data,
            databento_quotes=databento_quotes,
            technicals=technicals,
            macro=macro,
            economic_calendar=econ_cal,
            sector_performance=sector_perf,
            social_sentiment=social_sent,
            analyst_forecasts=forecasts_ctx,
            insider_trades=insider_trades,
            congressional_trades=congress_trades,
            max_articles=40,
        )
        result = producer_ai.query(
            question=question,
            context_json=context_json,
        )

        logger.info("FMP AI worker: analysis complete (model=%s, cached=%s)", result.model, result.cached)
        return {
            "result_dict": {
                "answer": result.answer,
                "model": result.model,
                "cached": result.cached,
                "context_articles": result.context_articles,
                "context_tickers": result.context_tickers,
                "fmp_tickers": result.fmp_tickers,
                "enrichment_layers": _n_layers,
                "error": result.error,
                "question": question,
            },
            "context_json": context_json,
            "cache_updates": cache_updates,
        }

    except Exception as exc:
        logger.exception("FMP AI worker failed")
        return {
            "result_dict": {
                "error": f"{type(exc).__name__}: {exc}",
                "question": question,
                "answer": "",
                "model": "",
                "cached": False,
                "context_articles": 0,
                "context_tickers": 0,
                "fmp_tickers": 0,
                "enrichment_layers": 0,
            },
            "context_json": "",
            "cache_updates": cache_updates,
        }


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
    now = datetime.now(UTC)
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

    # Market-data enrichment is optional per source; LLM egress is Producer-only.
    fmp_key = getattr(cfg, "fmp_api_key", "")
    producer_url = getattr(cfg, "producer_feed_url", "")
    producer_token = getattr(cfg, "producer_feed_token", "")

    if not fmp_key and not _DATABENTO_AVAILABLE:
        st.warning("💡 Configure FMP or Databento to enable market-data enrichment.")
        st.info(
            "AI Insights needs at least one market-data source. Configure "
            "`FMP_API_KEY` and/or `DATABENTO_API_KEY`, then restart."
        )
        return

    if not producer_url or not producer_token:
        st.warning("💡 The private Signals Producer AI route is not configured.")
        st.info(
            "Set `TERMINAL_PRODUCER_FEED_URL` and "
            "`TERMINAL_PRODUCER_FEED_TOKEN`. OpenAI and Cisco AI Defense "
            "remain on the Producer; no OpenAI key is required in the Terminal."
        )
        return

    if not feed:
        st.info("No articles in the feed yet — wait for the first poll to complete.")
        return

    _sources = ", ".join(
        source
        for source, available in (("Databento", _DATABENTO_AVAILABLE), ("FMP", bool(fmp_key)))
        if available
    )
    st.caption(
        f"Feed: {len(feed)} articles · Session: {current_session} · "
        f"Market data: {_sources} · AI via protected Signals Producer"
    )

    # Persist FMP AI workflow state (separate keys from AI Insights)
    st.session_state.setdefault("fmp_ai_selected_question", "")
    st.session_state.setdefault("fmp_ai_run_requested", False)
    st.session_state.setdefault("fmp_ai_last_result", None)
    st.session_state.setdefault("fmp_ai_last_context_json", "")
    st.session_state.setdefault("fmp_ai_pause_auto_refresh", False)

    # --- Preset question buttons ---
    # Use direct if-button() to set state in the SAME script run.
    # This avoids race conditions with auto-refresh that can lose
    # callback-set or rerun-set state between reruns.
    st.markdown("##### Quick Analysis")
    cols = st.columns(3)
    for i, (lbl, q) in enumerate(PRESET_QUESTIONS):
        col = cols[i % 3]
        if col.button(lbl, key=f"fmp_ai_preset_{i}"):
            st.session_state["fmp_ai_selected_question"] = q
            st.session_state["fmp_ai_run_requested"] = True
            logger.info("FMP AI preset clicked: [%d] %s", i, lbl)

    # --- Custom question input ---
    # Use on_change callback instead of st.form — forms inside tabs can
    # lose submission state when auto-refresh fires st.rerun() in the
    # background (the form_submit_button flag is transient and gets
    # cleared before the analysis block runs on the next rerun).
    st.markdown("##### Ask a Custom Question")

    def _on_custom_q_change() -> None:
        """Callback fires when user presses Enter in the text_input."""
        _q = (st.session_state.get("fmp_ai_custom_question") or "").strip()
        if _q:
            st.session_state["fmp_ai_selected_question"] = _q
            st.session_state["fmp_ai_run_requested"] = True
            logger.info("AI custom question submitted via Enter")

    st.text_input(
        "Your question about the current market data:",
        placeholder="e.g. What are the key catalysts for NVDA today?",
        key="fmp_ai_custom_question",
        on_change=_on_custom_q_change,
    )
    _qa_c1, _qa_c2 = st.columns([1, 1])
    with _qa_c1:
        if st.button("🔁 Ask Again", key="fmp_ai_regenerate",
                      help="Re-run the last question with fresh data"):
            _q = (st.session_state.get("fmp_ai_selected_question") or "").strip()
            if _q:
                st.session_state["fmp_ai_run_requested"] = True
    with _qa_c2:
        if st.button("🧹 Clear AI result", key="fmp_ai_clear_result"):
            st.session_state["fmp_ai_last_result"] = None
            st.session_state["fmp_ai_last_context_json"] = ""
            st.session_state["fmp_ai_selected_question"] = ""
            st.session_state["fmp_ai_run_requested"] = False

    st.toggle(
        "🔬 Deep analysis — fetch fresh FMP/technicals/social data layers (slower)",
        key="fmp_ai_deep_mode",
        help=(
            "Off: quick analysis from the live feed plus already-cached data "
            "layers (usually <30s). On: fetch all market-data layers fresh "
            "and in parallel before asking the model (up to ~3½ min)."
        ),
    )
    st.toggle(
        "Pause auto-refresh while reviewing AI result",
        key="fmp_ai_pause_auto_refresh",
        help=(
            "Prevents automatic page jumps while you read AI output. "
            "Background polling can continue; UI reruns are paused."
        ),
    )

    # ── Background-thread AI analysis ───────────────────────────
    # The analysis now runs in a daemon thread via ThreadPoolExecutor.
    # This makes it completely immune to Streamlit's RerunException
    # (raised by auto-refresh fragment's st.rerun()).
    #
    # Flow:
    #   1. Button click sets fmp_ai_run_requested = True
    #   2. On this render pass we submit _analysis_worker to _ai_pool
    #   3. Future is stored in session state
    #   4. On subsequent render passes (triggered by auto-refresh),
    #      we check Future.done() and harvest the result
    # ────────────────────────────────────────────────────────────

    # Step A: harvest completed background analysis
    _ai_future = st.session_state.get("_fmp_ai_future")
    if _ai_future is not None and _ai_future.done():
        try:
            _bg = _ai_future.result()
            st.session_state["fmp_ai_last_result"] = _bg["result_dict"]
            st.session_state["fmp_ai_last_context_json"] = _bg.get("context_json", "")
            for _ck, _cv in _bg.get("cache_updates", {}).items():
                st.session_state[_ck] = _cv
            logger.info("FMP AI background analysis harvested successfully")
        except Exception as _bg_exc:
            logger.exception("FMP AI background analysis raised")
            st.session_state["fmp_ai_last_result"] = {
                "error": f"{type(_bg_exc).__name__}: {_bg_exc}",
                "question": st.session_state.get("fmp_ai_selected_question", ""),
                "answer": "", "model": "", "cached": False,
                "context_articles": 0, "context_tickers": 0,
                "fmp_tickers": 0, "enrichment_layers": 0,
            }
        st.session_state["_fmp_ai_executing"] = False
        st.session_state.pop("_fmp_ai_future", None)
        st.toast("✅ AI analysis complete!")

    # Step B: start new analysis if requested and not already running
    question = str(st.session_state.get("fmp_ai_selected_question") or "").strip()
    run_requested = bool(st.session_state.get("fmp_ai_run_requested", False))

    if run_requested and question and not st.session_state.get("_fmp_ai_executing"):
        # Pre-fetch all cached data for the worker (thread-safe snapshot)
        _cache_keys = [
            "_cached_macro", "_cached_fmp_data", "_cached_fmp_technicals",
            "_cached_econ_cal", "_cached_sector_perf", "_cached_social_sent",
            "_cached_forecasts",
            "_cached_insider_trades", "_cached_congress_trades",
            "_cached_databento_quotes",
        ]
        _cached_snapshot = {k: st.session_state.get(k) for k in _cache_keys}
        _bz_key = getattr(cfg, "benzinga_api_key", "") if cfg else ""
        _producer_ai = ProducerAIInsightsClient(
            producer_url,
            producer_token,
            timeout_s=getattr(cfg, "producer_ai_timeout_s", 150.0),
        )

        # Per-run executor: a hung previous run can never queue this one
        # behind it (the executor is not shared), and shutdown(wait=False)
        # lets the daemon thread finish on its own.
        _cancel_event = threading.Event()
        _stage_ref: dict[str, str] = {"label": "Starting…"}
        _run_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="fmp_ai",
        )
        _submitted = _run_pool.submit(
            _analysis_worker,
            feed=list(feed),  # shallow copy — avoid concurrent mutation
            question=question,
            fmp_key=fmp_key,
            producer_ai=_producer_ai,
            benzinga_key=_bz_key,
            macro=_cached_snapshot.get("_cached_macro"),
            cached=_cached_snapshot,
            technicals_available=_TECHNICALS_AVAILABLE,
            finnhub_available=_FINNHUB_AVAILABLE,
            forecast_available=_FORECAST_AVAILABLE,
            poller_available=_POLLER_AVAILABLE,
            databento_available=_DATABENTO_AVAILABLE,
            deep=bool(st.session_state.get("fmp_ai_deep_mode", False)),
            cancel=_cancel_event,
            stage=_stage_ref,
        )
        _run_pool.shutdown(wait=False)
        st.session_state["_fmp_ai_future"] = _submitted
        st.session_state["_fmp_ai_cancel"] = _cancel_event
        st.session_state["_fmp_ai_stage"] = _stage_ref
        st.session_state["_fmp_ai_executing"] = True
        st.session_state["_fmp_ai_submit_ts"] = time.time()
        st.session_state["fmp_ai_run_requested"] = False  # consume immediately
        st.toast("🤖 AI analysis started in background…")
        logger.info("AI analysis submitted to background thread")

    # Step C: show progress if analysis is running
    # Budget: enrichment ≤ _ENRICH_BUDGET_S + Producer LLM timeout (~150 s)
    # + slack. The worker honours the cancel event at its checkpoints.
    _MAX_WORKER_SECONDS = 210
    if st.session_state.get("_fmp_ai_executing"):
        _elapsed = time.time() - st.session_state.get("_fmp_ai_submit_ts", time.time())
        _ai_f = st.session_state.get("_fmp_ai_future")
        # Safety: if the future completed between Step A and here, harvest now
        if _ai_f is not None and _ai_f.done():
            st.rerun()
        # Stale execution: cancel after hard timeout
        elif _elapsed > _MAX_WORKER_SECONDS:
            logger.warning("FMP AI worker exceeded %ds hard timeout — cancelling", _MAX_WORKER_SECONDS)
            _cancel_ev = st.session_state.get("_fmp_ai_cancel")
            if _cancel_ev is not None:
                _cancel_ev.set()
            if _ai_f is not None:
                _ai_f.cancel()
            st.session_state["_fmp_ai_executing"] = False
            st.session_state.pop("_fmp_ai_future", None)
            st.session_state.pop("_fmp_ai_submit_ts", None)
            st.session_state["fmp_ai_last_result"] = {
                "error": f"Analysis timed out after {int(_elapsed)}s. The background worker may have hung on a slow API call. Please try again.",
                "question": question, "answer": "", "model": "", "cached": False,
                "context_articles": 0, "context_tickers": 0, "fmp_tickers": 0, "enrichment_layers": 0,
            }
            st.rerun()
        else:
            _stage_label = str(
                (st.session_state.get("_fmp_ai_stage") or {}).get("label") or "Working…"
            )
            _budget_hint = (
                "up to ~3½ min" if st.session_state.get("fmp_ai_deep_mode") else "usually <30s"
            )
            st.info(
                f"⏳ AI analysis running… ({int(_elapsed)}s elapsed, {_budget_hint}) — {_stage_label}"
            )
            _cc1, _cc2 = st.columns([1, 3])
            with _cc1:
                if st.button("❌ Cancel", key="fmp_ai_cancel"):
                    _cancel_ev = st.session_state.get("_fmp_ai_cancel")
                    if _cancel_ev is not None:
                        _cancel_ev.set()
                    if _ai_f is not None:
                        _ai_f.cancel()
                    st.session_state["_fmp_ai_executing"] = False
                    st.session_state.pop("_fmp_ai_future", None)
                    st.session_state.pop("_fmp_ai_submit_ts", None)
                    st.toast("AI analysis cancelled.")
                    st.rerun()

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
