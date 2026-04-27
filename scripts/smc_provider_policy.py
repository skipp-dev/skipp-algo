"""Provider policy matrix for V4 enrichment domains.

Declares which data provider is primary and fallback for each
enrichment domain.  Every fallback chain is explicit — there are no
implicit cascades.

Architecture note — provider_policy vs provider_matrix
------------------------------------------------------
provider_policy.py  = Orchestration policy (HOW providers are used at runtime).
  Declares primary/fallback chains per enrichment domain and controls
  runtime selection order + provenance recording.

smc_integration/provider_matrix.py  = Capability declaration (what each
  provider CAN supply).  Enumerates repo sources and their feature matrix.

No redundancy — policy controls runtime selection, matrix describes
provider features.  Both are needed and should not be merged.

Domain policies
---------------
* **base_scan / microstructure** → Databento primary, no fallback
* **regime** → FMP primary, no fallback (defaults used on failure)
* **news** → FMP primary, Benzinga fallback
* **calendar** → FMP primary, Benzinga fallback
* **technical** → FMP primary, TradingView fallback

Each adapter returns a ``(result_dict, provider_name)`` tuple so the
orchestrator can record provenance.  On failure, the adapter raises and
the caller catches + records the stale provider.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
from typing import Any

from scripts.smc_newsapi_ai import NewsApiAiProviderError

logger = logging.getLogger(__name__)


# ── Policy dataclass ────────────────────────────────────────────

@dataclass(frozen=True)
class DomainPolicy:
    """Declares the provider chain for a single enrichment domain."""

    domain: str
    primary: str
    fallbacks: tuple[str, ...]  # ordered; empty = no fallback

    @property
    def all_providers(self) -> tuple[str, ...]:
        return (self.primary, *self.fallbacks)


POLICY_BASE_SCAN = DomainPolicy("base_scan", primary="databento", fallbacks=())
POLICY_REGIME = DomainPolicy("regime", primary="fmp", fallbacks=())
POLICY_NEWS = DomainPolicy("news", primary="fmp", fallbacks=("benzinga", "newsapi_ai"))
POLICY_CALENDAR = DomainPolicy("calendar", primary="fmp", fallbacks=("benzinga",))
POLICY_TECHNICAL = DomainPolicy("technical", primary="fmp", fallbacks=("tradingview",))

ALL_POLICIES: dict[str, DomainPolicy] = {
    p.domain: p
    for p in (POLICY_BASE_SCAN, POLICY_REGIME, POLICY_NEWS, POLICY_CALENDAR, POLICY_TECHNICAL)
}


# ── Provider result wrapper ────────────────────────────────────

@dataclass
class ProviderResult:
    """Wrapper returned by every adapter call."""

    data: dict[str, Any]
    provider: str               # which provider actually delivered data
    ok: bool = True             # False when default data was used
    stale: list[str] = field(default_factory=list)  # providers that were tried and failed
    meta: dict[str, Any] = field(default_factory=dict)


_PROVIDER_DETAIL_RE = re.compile(r"(apikey|api_key|token|key)=[^&\s]+", flags=re.IGNORECASE)


def _sanitize_provider_detail(detail: str) -> str:
    return _PROVIDER_DETAIL_RE.sub(r"\1=***", str(detail or "")).strip()


def _classify_provider_failure(provider_name: str, exc: Exception) -> tuple[str, str, str]:
    if isinstance(exc, NewsApiAiProviderError):
        return (
            str(exc.provider_status or "http_error").strip() or "http_error",
            _sanitize_provider_detail(str(exc.detail or exc)),
            "provider_error",
        )

    detail = _sanitize_provider_detail(str(exc) or type(exc).__name__)
    lowered = detail.lower()

    if "not configured" in lowered:
        return "config_missing", detail, "configuration"
    if "not available" in lowered or "unavailable" in lowered:
        return "provider_unavailable", detail, "availability"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout", detail, "runtime"
    if "quota" in lowered:
        return "quota_exhausted", detail, "quota"
    if "rate limit" in lowered or "rate-limited" in lowered:
        return "rate_limited", detail, "quota"
    return "error", detail, "runtime"


def _provider_status_from_result(result: ProviderResult) -> tuple[str, str]:
    provider_status = str(result.meta.get("provider_status") or ("ok" if result.ok else "no_data")).strip()
    if not provider_status:
        provider_status = "ok" if result.ok else "no_data"
    status_detail = _sanitize_provider_detail(str(result.meta.get("status_detail") or ""))
    return provider_status, status_detail


def _provider_attempt_meta(result: ProviderResult) -> dict[str, Any]:
    selected_keys = (
        "last_seen_epoch",
        "last_seen_news_uri",
        "raw_record_count",
        "matched_record_count",
        "cursor_before_epoch",
        "cursor_before_uri",
    )
    return {
        key: result.meta[key]
        for key in selected_keys
        if key in result.meta
    }


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


# ── Regime adapters ─────────────────────────────────────────────

def fetch_regime_fmp(fmp: Any) -> ProviderResult:
    """Fetch regime data via FMP (primary for regime domain)."""
    from scripts.smc_macro_bias import macro_bias_with_components
    from scripts.smc_regime_classifier import classify_market_regime

    vix_level: float | None = None
    macro_bias = 0.0
    macro_events: list[dict[str, Any]] = []
    macro_analysis: dict[str, Any] = {
        "macro_bias": 0.0,
        "events_for_bias": [],
        "score_components": [],
    }
    sectors: list[dict[str, Any]] = []
    market_pe_forward: float | None = None
    stale: list[str] = []

    try:
        vix_row = fmp.get_index_quote("^VIX")
        raw = vix_row.get("price")
        if raw is not None:
            vix_level = float(raw)
    except Exception:
        logger.warning("FMP VIX fetch failed", exc_info=True)
        stale.append("fmp_vix")

    try:
        sectors = fmp.get_sector_performance()
    except Exception:
        logger.warning("FMP sector-performance fetch failed", exc_info=True)
        stale.append("fmp_sectors")

    try:
        today = datetime.now(_ET).date()
        macro_events = list(fmp.get_macro_calendar(today, today) or [])
        macro_analysis = macro_bias_with_components(macro_events)
        macro_bias = float(macro_analysis.get("macro_bias") or 0.0)
    except Exception:
        logger.warning("FMP macro-calendar fetch failed", exc_info=True)
        stale.append("fmp_macro")

    try:
        market_pe_forward = _coerce_optional_float(fmp.get_market_pe_forward())
    except Exception:
        logger.warning("FMP market P/E fetch failed", exc_info=True)
        stale.append("fmp_market_pe")

    regime = classify_market_regime(
        vix_level,
        macro_bias,
        sectors,
        market_pe_forward=market_pe_forward,
    )
    raw_sector_fetch = getattr(fmp, "_last_sector_performance_diagnostics", {})
    sector_fetch_diagnostics = dict(raw_sector_fetch) if isinstance(raw_sector_fetch, dict) else {}
    if not sector_fetch_diagnostics:
        sector_fetch_diagnostics = {
            "status": "ok" if sectors else "empty",
            "attempted_dates": [],
            "row_counts": {},
            "used_fallback_previous_trading_day": False,
            "selected_date": "",
            "returned_row_count": len(sectors),
            "error": "",
        }

    raw_macro_fetch = getattr(fmp, "_last_macro_calendar_diagnostics", {})
    macro_fetch_diagnostics = dict(raw_macro_fetch) if isinstance(raw_macro_fetch, dict) else {}
    raw_market_pe_fetch = getattr(fmp, "_last_market_pe_forward_diagnostics", {})
    market_pe_fetch_diagnostics = dict(raw_market_pe_fetch) if isinstance(raw_market_pe_fetch, dict) else {}
    if not market_pe_fetch_diagnostics:
        market_pe_fetch_diagnostics = {
            "status": "ok" if market_pe_forward is not None else "unavailable",
            "symbol": "SPY",
            "source_category": "unknown" if market_pe_forward is not None else "unavailable",
            "field": "",
            "price": None,
            "forward_eps": None,
            "estimate_count": 0,
            "error": "",
        }
    macro_input_diagnostics = dict(macro_analysis.get("input_diagnostics") or {})
    macro_event_audit = [dict(event) for event in list(macro_analysis.get("event_audit") or [])]

    diagnostics = {
        "vix_present": vix_level is not None,
        "vix_level": vix_level,
        "sector_row_count": len(sectors),
        "sector_fetch": sector_fetch_diagnostics,
        "macro_event_count": len(macro_events),
        "macro_events_considered": len(macro_analysis.get("events_for_bias", [])),
        "macro_inputs_used": [
            str(event.get("event") or event.get("name") or event.get("canonical_event") or "").strip()
            for event in macro_analysis.get("events_for_bias", [])
            if str(event.get("event") or event.get("name") or event.get("canonical_event") or "").strip()
        ],
        "macro_fetch": macro_fetch_diagnostics,
        "market_pe_fetch": market_pe_fetch_diagnostics,
        "market_pe_forward": regime.get("market_pe_forward"),
        "market_pe_regime": str(regime.get("market_pe_regime") or "UNKNOWN"),
        "macro_input_diagnostics": macro_input_diagnostics,
        "macro_event_audit": macro_event_audit,
        "macro_score_components": [
            {
                "canonical_event": str(component.get("canonical_event") or ""),
                "weight": float(component.get("weight") or 0.0),
                "contribution": float(component.get("contribution") or 0.0),
                "consensus_field": component.get("consensus_field"),
                "data_quality_flags": list(component.get("data_quality_flags") or []),
            }
            for component in macro_analysis.get("score_components", [])
        ],
        "macro_bias": float(regime.get("macro_bias") or 0.0),
        "macro_bias_raw": float(regime.get("macro_bias_raw") or 0.0),
        "macro_bias_pe_adjustment": float(regime.get("macro_bias_pe_adjustment") or 0.0),
        "sector_breadth": float(regime.get("sector_breadth") or 0.0),
    }
    return ProviderResult(
        data=regime,
        provider="fmp",
        stale=stale,
        meta={"diagnostics": diagnostics},
    )


# ── News adapters ───────────────────────────────────────────────

def fetch_news_fmp(fmp: Any, symbols: list[str]) -> ProviderResult:
    """Fetch news via FMP (primary for news domain)."""
    from scripts.smc_news_scorer import compute_news_sentiment

    articles: list[dict[str, Any]] = []
    raw = fmp.get_stock_latest_news(limit=100)
    for item in raw:
        headline = item.get("title") or item.get("headline") or ""
        snippet = item.get("text") or item.get("snippet") or item.get("content") or ""
        tickers = item.get("tickers") or []
        if isinstance(tickers, str):
            tickers = [t.strip() for t in tickers.split(",") if t.strip()]
        symbol_field = item.get("symbol") or ""
        if symbol_field and not tickers:
            tickers = [symbol_field]
        articles.append({"headline": headline, "snippet": str(snippet or ""), "tickers": tickers})

    result = compute_news_sentiment(symbols, articles, include_diagnostics=True)
    diagnostics = result.pop("diagnostics", {})
    return ProviderResult(data=result, provider="fmp", meta={"diagnostics": diagnostics})


def fetch_news_benzinga(api_key: str, symbols: list[str]) -> ProviderResult:
    """Fetch news via Benzinga REST (fallback for news domain)."""
    from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter
    from newsstack_fmp.scoring import classify_and_score

    adapter = BenzingaRestAdapter(api_key)
    try:
        items = adapter.fetch_news(page_size=100)
    finally:
        adapter.client.close()

    universe = {s.upper() for s in symbols}

    # Convert to the same article format the scorer expects
    articles: list[dict[str, Any]] = []
    for item in items:
        articles.append({
            "headline": item.headline,
            "tickers": [t for t in item.tickers if t.upper() in universe],
        })

    from scripts.smc_news_scorer import compute_news_sentiment
    result = compute_news_sentiment(symbols, articles, include_diagnostics=True)
    diagnostics = result.pop("diagnostics", {})
    return ProviderResult(data=result, provider="benzinga", meta={"diagnostics": diagnostics})


def fetch_news_newsapi_ai(
    api_key: str,
    symbols: list[str],
    *,
    article_feed_after_epoch: float | None = None,
    article_feed_after_uri: str = "",
) -> ProviderResult:
    """Fetch news via NewsAPI.ai / Event Registry (tertiary fallback for news)."""
    from newsstack_fmp.pipeline import _newsapi_operator_status
    from newsstack_fmp.normalize import normalize_newsapi_ai
    from scripts.smc_news_scorer import compute_news_sentiment
    from scripts.smc_newsapi_ai import extract_newsapi_feed_article_cursor_uri, fetch_newsapi_records

    try:
        feed_after_epoch = float(article_feed_after_epoch or 0.0)
    except (TypeError, ValueError):
        feed_after_epoch = 0.0

    records = fetch_newsapi_records(
        api_key,
        symbols,
        prefer_article_feed=feed_after_epoch > 0.0,
        article_feed_after_epoch=feed_after_epoch,
        article_feed_after_uri=article_feed_after_uri,
    )
    normalized_items = [normalize_newsapi_ai(record) for record in records]
    universe = {str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()}
    matched_record_count = sum(
        1
        for item in normalized_items
        if any(str(ticker or "").strip().upper() in universe for ticker in item.tickers or [])
    )
    provider_status, status_detail = _newsapi_operator_status(
        cursor=feed_after_epoch,
        raw_items=normalized_items,
        filtered_items=normalized_items,
        universe=universe,
    )

    articles = [
        {
            "headline": str(item.headline or "").strip(),
            "tickers": list(item.tickers or []),
        }
        for item in normalized_items
    ]
    result = compute_news_sentiment(symbols, articles, include_diagnostics=True)
    diagnostics = result.pop("diagnostics", {})
    last_seen_epoch = max((float(item.updated_ts or item.published_ts or 0.0) for item in normalized_items), default=0.0)
    return ProviderResult(
        data=result,
        provider="newsapi_ai",
        meta={
            "provider_status": provider_status,
            "status_detail": status_detail,
            "last_seen_epoch": last_seen_epoch,
            "last_seen_news_uri": extract_newsapi_feed_article_cursor_uri(records) or "",
            "raw_record_count": len(records),
            "matched_record_count": matched_record_count,
            "cursor_before_epoch": feed_after_epoch,
            "cursor_before_uri": str(article_feed_after_uri or "").strip(),
            "diagnostics": diagnostics,
        },
    )


# ── Calendar adapters ───────────────────────────────────────────

def fetch_calendar_fmp(fmp: Any, symbols: list[str]) -> ProviderResult:
    """Fetch calendar via FMP (primary for calendar domain)."""
    from scripts.smc_calendar_collector import collect_earnings_and_macro

    stale: list[str] = []
    earnings: list[dict[str, Any]] = []
    macro_events: list[dict[str, Any]] = []
    today = datetime.now(_ET).date()
    tomorrow = today + timedelta(days=1)

    try:
        raw = fmp.get_earnings_calendar(today, tomorrow)
        for row in raw:
            sym = row.get("symbol") or ""
            d = row.get("date") or ""
            timing = (row.get("time") or "").lower()
            if timing.startswith("before"):
                timing = "bmo"
            elif timing.startswith("after"):
                timing = "amc"
            earnings.append({"symbol": sym, "date": d, "timing": timing})
    except Exception:
        logger.warning("FMP earnings-calendar fetch failed", exc_info=True)
        stale.append("fmp_earnings")

    try:
        raw_macro = fmp.get_macro_calendar(today, today)
        for evt in raw_macro:
            name = evt.get("event") or evt.get("name") or ""
            time_utc = evt.get("date") or evt.get("time_utc") or ""
            macro_events.append({"name": name, "time_utc": time_utc})
    except Exception:
        logger.warning("FMP macro-calendar fetch failed", exc_info=True)
        stale.append("fmp_macro")

    result = collect_earnings_and_macro(symbols, earnings, macro_events, reference_date=today)
    return ProviderResult(data=result, provider="fmp", stale=stale)


def fetch_calendar_benzinga(api_key: str, symbols: list[str]) -> ProviderResult:
    """Fetch calendar via Benzinga (fallback for calendar domain)."""
    from newsstack_fmp.ingest_benzinga_calendar import BenzingaCalendarAdapter
    from scripts.smc_calendar_collector import collect_earnings_and_macro

    adapter = BenzingaCalendarAdapter(api_key)
    try:
        today = datetime.now(_ET).date()
        tomorrow = today + timedelta(days=1)
        today_str = today.isoformat()
        tomorrow_str = tomorrow.isoformat()

        raw_earnings = adapter.fetch_earnings(
            date_from=today_str,
            date_to=tomorrow_str,
            page_size=100,
        )
        earnings: list[dict[str, Any]] = []
        for row in raw_earnings:
            sym = row.get("ticker") or row.get("symbol") or ""
            d = row.get("date") or ""
            timing = (row.get("time") or "").lower()
            if timing.startswith("before"):
                timing = "bmo"
            elif timing.startswith("after"):
                timing = "amc"
            earnings.append({"symbol": sym, "date": d, "timing": timing})

        raw_econ = adapter.fetch_economics(
            date_from=today_str,
            date_to=today_str,
            page_size=50,
        )
        macro_events: list[dict[str, Any]] = []
        for evt in raw_econ:
            name = evt.get("event_name") or evt.get("event") or ""
            time_utc = evt.get("date") or evt.get("time_utc") or ""
            macro_events.append({"name": name, "time_utc": time_utc})
    finally:
        adapter.close()

    result = collect_earnings_and_macro(symbols, earnings, macro_events, reference_date=today)
    return ProviderResult(data=result, provider="benzinga")


# ── Technical adapters ──────────────────────────────────────────

def fetch_technical_fmp(fmp: Any, symbol: str = "SPY") -> ProviderResult:
    """Fetch technical summary via FMP (primary for technical domain)."""
    data = fmp.get_technical_indicator(symbol, "1day", "rsi", indicator_period=14)
    rsi_val = data.get("rsi") if data else None
    if rsi_val is not None:
        rsi = float(rsi_val)
        strength = min(abs(rsi - 50.0) / 50.0, 1.0)
        bias = "BULLISH" if rsi > 55 else ("BEARISH" if rsi < 45 else "NEUTRAL")
        return ProviderResult(
            data={"strength": strength, "bias": bias},
            provider="fmp",
        )
    raise ValueError("FMP returned no RSI data")


def fetch_technical_tradingview(symbol: str = "SPY") -> ProviderResult:
    """Fetch technical summary via the real TradingView adapter path.

    This fallback must remain independent from the FMP technical fallback.
    When the TradingView adapter is unavailable or returns an error, the
    provider is treated as unavailable rather than silently reusing FMP.
    """
    from terminal_technicals import _TV_AVAILABLE, fetch_technicals

    if not _TV_AVAILABLE:
        raise ValueError("TradingView technical adapter not available")

    data = fetch_technicals(symbol, "1D")
    if data.error:
        raise ValueError("TradingView technical fallback returned no data")

    summary_buy = int(data.summary_buy or 0)
    summary_sell = int(data.summary_sell or 0)
    summary_neutral = int(data.summary_neutral or 0)
    total = summary_buy + summary_sell + summary_neutral
    if total > 0:
        strength = abs(summary_buy - summary_sell) / total
        bias = "BULLISH" if summary_buy > summary_sell else ("BEARISH" if summary_sell > summary_buy else "NEUTRAL")
    else:
        strength = 0.5
        bias = "NEUTRAL"

    return ProviderResult(
        data={"strength": min(strength, 1.0), "bias": bias},
        provider="tradingview",
    )


# ── Domain orchestrators ────────────────────────────────────────

def resolve_domain(
    domain: str,
    *,
    fmp: Any | None = None,
    benzinga_api_key: str = "",
    newsapi_ai_key: str = "",
    symbols: list[str] | None = None,
    newsapi_ai_feed_after_epoch: float | None = None,
    newsapi_ai_feed_after_uri: str = "",
) -> ProviderResult:
    """Run the provider chain for *domain* and return the first success.

    On total failure, returns a ``ProviderResult`` with ``ok=False``
    and safe empty data.
    """
    policy = ALL_POLICIES.get(domain)
    if policy is None:
        raise ValueError(f"Unknown enrichment domain: {domain!r}")

    all_stale: list[str] = []
    attempt_rows: list[dict[str, Any]] = []
    syms = symbols or []

    # Attempt primary, then each fallback in order.
    for provider_name in policy.all_providers:
        try:
            result = _call_provider(domain, provider_name, fmp=fmp,
                                    benzinga_api_key=benzinga_api_key,
                                    newsapi_ai_key=newsapi_ai_key,
                                    symbols=syms,
                                    newsapi_ai_feed_after_epoch=newsapi_ai_feed_after_epoch,
                                    newsapi_ai_feed_after_uri=newsapi_ai_feed_after_uri)
            provider_status, status_detail = _provider_status_from_result(result)
            attempt_rows.append(
                {
                    "provider": provider_name,
                    "delivered_provider": result.provider,
                    "outcome": "success",
                    "provider_status": provider_status,
                    "status_detail": status_detail,
                    **_provider_attempt_meta(result),
                }
            )
            result.stale.extend(all_stale)
            result.meta = dict(result.meta)
            result.meta["attempts"] = list(attempt_rows)
            return result
        except Exception as exc:
            provider_status, status_detail, failure_class = _classify_provider_failure(provider_name, exc)
            attempt_rows.append(
                {
                    "provider": provider_name,
                    "delivered_provider": "none",
                    "outcome": "failed",
                    "provider_status": provider_status,
                    "status_detail": status_detail,
                    "failure_class": failure_class,
                    "error_type": type(exc).__name__,
                }
            )
            if isinstance(exc, NewsApiAiProviderError):
                logger.info(
                    "%s provider %r degraded — %s",
                    domain,
                    provider_name,
                    exc,
                )
            else:
                logger.warning(
                    "%s provider %r failed — trying next",
                    domain, provider_name, exc_info=True,
                )
            all_stale.append(provider_name)

    # All providers exhausted — return defaults
    return ProviderResult(
        data={},
        provider="none",
        ok=False,
        stale=all_stale,
        meta={
            "provider_status": "no_data",
            "status_detail": "All configured providers in the chain failed.",
            "attempts": attempt_rows,
        },
    )


def _call_provider(
    domain: str,
    provider_name: str,
    *,
    fmp: Any | None,
    benzinga_api_key: str,
    newsapi_ai_key: str,
    symbols: list[str],
    newsapi_ai_feed_after_epoch: float | None,
    newsapi_ai_feed_after_uri: str,
) -> ProviderResult:
    """Dispatch to the correct adapter for *domain* × *provider_name*."""
    if domain == "regime":
        if provider_name == "fmp":
            if fmp is None:
                raise RuntimeError("FMP client not available")
            return fetch_regime_fmp(fmp)
    elif domain == "news":
        if provider_name == "fmp":
            if fmp is None:
                raise RuntimeError("FMP client not available")
            return fetch_news_fmp(fmp, symbols)
        if provider_name == "benzinga":
            if not benzinga_api_key:
                raise RuntimeError("Benzinga API key not configured")
            return fetch_news_benzinga(benzinga_api_key, symbols)
        if provider_name == "newsapi_ai":
            if not newsapi_ai_key:
                raise RuntimeError("NewsAPI.ai API key not configured")
            return fetch_news_newsapi_ai(
                newsapi_ai_key,
                symbols,
                article_feed_after_epoch=newsapi_ai_feed_after_epoch,
                article_feed_after_uri=newsapi_ai_feed_after_uri,
            )
    elif domain == "calendar":
        if provider_name == "fmp":
            if fmp is None:
                raise RuntimeError("FMP client not available")
            return fetch_calendar_fmp(fmp, symbols)
        if provider_name == "benzinga":
            if not benzinga_api_key:
                raise RuntimeError("Benzinga API key not configured")
            return fetch_calendar_benzinga(benzinga_api_key, symbols)
    elif domain == "technical":
        if provider_name == "fmp":
            if fmp is None:
                raise RuntimeError("FMP client not available")
            return fetch_technical_fmp(fmp)
        if provider_name == "tradingview":
            return fetch_technical_tradingview()

    raise ValueError(f"No adapter for {domain}/{provider_name}")
