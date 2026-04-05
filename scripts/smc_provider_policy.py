"""Provider policy matrix for V4 enrichment domains.

Declares which data provider is primary and fallback for each
enrichment domain.  Every fallback chain is explicit — there are no
implicit cascades.

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
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

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


# ── Regime adapters ─────────────────────────────────────────────

def fetch_regime_fmp(fmp: Any) -> ProviderResult:
    """Fetch regime data via FMP (primary for regime domain)."""
    from scripts.smc_regime_classifier import classify_market_regime

    vix_level: float | None = None
    macro_bias = 0.0
    sectors: list[dict[str, Any]] = []
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

    regime = classify_market_regime(vix_level, macro_bias, sectors)
    return ProviderResult(data=regime, provider="fmp", stale=stale)


# ── News adapters ───────────────────────────────────────────────

def fetch_news_fmp(fmp: Any, symbols: list[str]) -> ProviderResult:
    """Fetch news via FMP (primary for news domain)."""
    from scripts.smc_news_scorer import compute_news_sentiment

    articles: list[dict[str, Any]] = []
    raw = fmp.get_stock_latest_news(limit=100)
    for item in raw:
        headline = item.get("title") or item.get("headline") or ""
        tickers = item.get("tickers") or []
        if isinstance(tickers, str):
            tickers = [t.strip() for t in tickers.split(",") if t.strip()]
        symbol_field = item.get("symbol") or ""
        if symbol_field and not tickers:
            tickers = [symbol_field]
        articles.append({"headline": headline, "tickers": tickers})

    result = compute_news_sentiment(symbols, articles)
    return ProviderResult(data=result, provider="fmp")


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
    result = compute_news_sentiment(symbols, articles)
    return ProviderResult(data=result, provider="benzinga")


def fetch_news_newsapi_ai(api_key: str, symbols: list[str]) -> ProviderResult:
    """Fetch news via NewsAPI.ai / Event Registry (tertiary fallback for news)."""
    from scripts.smc_news_scorer import compute_news_sentiment
    from scripts.smc_newsapi_ai import fetch_newsapi_articles

    articles = fetch_newsapi_articles(api_key, symbols)
    result = compute_news_sentiment(symbols, articles)
    return ProviderResult(data=result, provider="newsapi_ai")


# ── Calendar adapters ───────────────────────────────────────────

def fetch_calendar_fmp(fmp: Any, symbols: list[str]) -> ProviderResult:
    """Fetch calendar via FMP (primary for calendar domain)."""
    from scripts.smc_calendar_collector import collect_earnings_and_macro

    stale: list[str] = []
    earnings: list[dict[str, Any]] = []
    macro_events: list[dict[str, Any]] = []
    today = date.today()
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
        today = date.today()
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
    """Fetch technical summary via the TradingView-style fallback path.

    Currently backed by ``terminal_fmp_technicals.fetch_fmp_technicals``
    which returns summary buy/sell/neutral counts.  When a direct
    TradingView adapter becomes available this shim will be replaced.
    """
    from terminal_fmp_technicals import fetch_fmp_technicals

    data = fetch_fmp_technicals(symbol, "1D")
    if data is None or data.get("error"):
        raise ValueError("TradingView technical fallback returned no data")

    # Derive strength/bias from summary signals
    summary_buy = data.get("summary_buy", 0)
    summary_sell = data.get("summary_sell", 0)
    total = summary_buy + summary_sell + data.get("summary_neutral", 0)
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
) -> ProviderResult:
    """Run the provider chain for *domain* and return the first success.

    On total failure, returns a ``ProviderResult`` with ``ok=False``
    and safe empty data.
    """
    policy = ALL_POLICIES.get(domain)
    if policy is None:
        raise ValueError(f"Unknown enrichment domain: {domain!r}")

    all_stale: list[str] = []
    syms = symbols or []

    # Attempt primary, then each fallback in order.
    for provider_name in policy.all_providers:
        try:
            result = _call_provider(domain, provider_name, fmp=fmp,
                                    benzinga_api_key=benzinga_api_key,
                                    newsapi_ai_key=newsapi_ai_key,
                                    symbols=syms)
            result.stale.extend(all_stale)
            return result
        except Exception:
            logger.warning(
                "%s provider %r failed — trying next",
                domain, provider_name, exc_info=True,
            )
            all_stale.append(provider_name)

    # All providers exhausted — return defaults
    return ProviderResult(
        data={}, provider="none", ok=False, stale=all_stale,
    )


def _call_provider(
    domain: str,
    provider_name: str,
    *,
    fmp: Any | None,
    benzinga_api_key: str,
    newsapi_ai_key: str,
    symbols: list[str],
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
            return fetch_news_newsapi_ai(newsapi_ai_key, symbols)
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
