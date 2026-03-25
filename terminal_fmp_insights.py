"""FMP AI Insights engine — LLM analysis enriched with FMP financial data.

Mirrors the OpenAI-only ``terminal_ai_insights`` module but fetches
real-time quotes, company profiles, and key ratios from FMP's REST API
before sending the enriched context to the LLM.  This allows side-by-side
comparison of AI analysis with vs. without institutional-grade financial
data from Financial Modeling Prep.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from open_prep.macro import FMPClient

logger = logging.getLogger(__name__)

_APIKEY_RE = re.compile(r"(apikey|api_key|token|key)=[^&\s]+", re.IGNORECASE)

# ---------------------------------------------------------------------------
# In-memory response cache (thread-safe, separate from OpenAI cache)
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL_S = 300.0  # 5 minutes


def _cache_key(question: str, context_digest: str, model: str) -> str:
    raw = f"fmp|{model}|{question}|{context_digest}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _get_cached(key: str) -> str | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, text = entry
        if time.time() - ts > _CACHE_TTL_S:
            del _cache[key]
            return None
        return text


def _set_cached(key: str, text: str) -> None:
    with _cache_lock:
        if len(_cache) > 200:
            cutoff = time.time() - _CACHE_TTL_S
            expired = [k for k, (t, _) in _cache.items() if t < cutoff]
            for k in expired:
                del _cache[k]
        _cache[key] = (time.time(), text)


# ---------------------------------------------------------------------------
# FMP data fetching via shared client
# ---------------------------------------------------------------------------
_FMP_TIMEOUT = 12.0


def _make_fmp_client(api_key: str) -> FMPClient:
    return FMPClient(api_key=api_key, retry_attempts=1, timeout_seconds=_FMP_TIMEOUT)


def fetch_fmp_quotes(api_key: str, tickers: list[str]) -> list[dict[str, Any]]:
    """Fetch quotes from FMP for a list of tickers via the shared client."""
    if not api_key or not tickers:
        return []
    try:
        symbols = [t.upper().strip() for t in tickers[:20] if t and t.strip()]
        return _make_fmp_client(api_key).get_batch_quotes(symbols)
    except Exception as exc:
        logger.warning("FMP quote fetch failed: %s", exc)
        return []


def fetch_fmp_profiles(api_key: str, tickers: list[str]) -> list[dict[str, Any]]:
    """Fetch company profiles from FMP for a list of tickers."""
    if not api_key or not tickers:
        return []
    try:
        symbols = [t.upper().strip() for t in tickers[:20] if t and t.strip()]
        return _make_fmp_client(api_key).get_profiles(symbols)
    except Exception as exc:
        logger.warning("FMP profile failed: %s", exc)
        return []


def fetch_fmp_ratios(api_key: str, tickers: list[str]) -> list[dict[str, Any]]:
    """Fetch key financial ratios (TTM) from FMP for a list of tickers."""
    if not api_key or not tickers:
        return []
    results: list[dict[str, Any]] = []
    client = _make_fmp_client(api_key)
    for tk in tickers[:10]:
        requested_symbol = tk.upper().strip()
        if not requested_symbol:
            continue
        try:
            data = client.get_ratios_ttm(requested_symbol)
            if isinstance(data, list) and data:
                entry = data[0]
                entry["symbol"] = requested_symbol
                results.append(entry)
        except Exception as exc:
            logger.debug("FMP ratios-ttm(%s) failed: %s", requested_symbol, exc)
    return results


def assemble_fmp_data(
    api_key: str,
    tickers: list[str],
) -> dict[str, Any]:
    """Fetch quotes, profiles, and ratios for *tickers* and return merged dict.

    Returns a dict keyed by ticker, each containing combined financial data.
    """
    if not api_key or not tickers:
        return {}

    unique_tickers = list(dict.fromkeys(t.upper().strip() for t in tickers if t.strip()))[:15]

    quotes = fetch_fmp_quotes(api_key, unique_tickers)
    profiles = fetch_fmp_profiles(api_key, unique_tickers)

    # Index by symbol
    q_map: dict[str, dict] = {}
    for q in quotes:
        sym = (q.get("symbol") or "").upper()
        if sym:
            q_map[sym] = {
                "price": q.get("price"),
                "change": q.get("change"),
                "change_pct": q.get("changesPercentage"),
                "volume": q.get("volume"),
                "avg_volume": q.get("avgVolume"),
                "market_cap": q.get("marketCap"),
                "day_high": q.get("dayHigh"),
                "day_low": q.get("dayLow"),
                "year_high": q.get("yearHigh"),
                "year_low": q.get("yearLow"),
                "pe": q.get("pe"),
                "eps": q.get("eps"),
            }

    p_map: dict[str, dict] = {}
    for p in profiles:
        sym = (p.get("symbol") or "").upper()
        if sym:
            p_map[sym] = {
                "company_name": p.get("companyName"),
                "sector": p.get("sector"),
                "industry": p.get("industry"),
                "description": (p.get("description") or "")[:200],
                "full_time_employees": p.get("fullTimeEmployees"),
                "beta": p.get("beta"),
            }

    result: dict[str, Any] = {}
    for tk in unique_tickers:
        entry: dict[str, Any] = {}
        if tk in q_map:
            entry["quote"] = q_map[tk]
        if tk in p_map:
            entry["profile"] = p_map[tk]
        if entry:
            result[tk] = entry

    return result


# ---------------------------------------------------------------------------
# Context assembly (mirrors terminal_ai_insights.assemble_context but
# adds an "fmp_financials" key with real-time FMP data)
# ---------------------------------------------------------------------------

def assemble_context(
    feed: list[dict[str, Any]],
    *,
    fmp_data: dict[str, Any] | None = None,
    technicals: dict[str, Any] | None = None,
    macro: dict[str, Any] | None = None,
    economic_calendar: list[dict[str, Any]] | None = None,
    sector_performance: list[dict[str, Any]] | None = None,
    social_sentiment: dict[str, Any] | None = None,
    analyst_forecasts: dict[str, Any] | None = None,
    analyst_ratings: list[dict[str, Any]] | None = None,
    earnings_calendar: list[dict[str, Any]] | None = None,
    insider_trades: list[dict[str, Any]] | None = None,
    congressional_trades: list[dict[str, Any]] | None = None,
    max_articles: int = 40,
) -> str:
    """Build a compact JSON context string enriched with FMP financial data
    and multiple alternative data layers (social, analyst, macro, insider)."""
    sorted_feed = sorted(feed, key=lambda d: abs(d.get("news_score", 0)), reverse=True)
    articles: list[dict[str, Any]] = []
    for item in sorted_feed[:max_articles]:
        entry: dict[str, Any] = {
            "headline": (item.get("headline") or "")[:200],
            "ticker": item.get("ticker", ""),
            "score": round(item.get("news_score", 0), 3),
            "sentiment": item.get("sentiment", ""),
            "segment": item.get("segment", ""),
            "source": item.get("source", ""),
            "age_min": item.get("age_minutes", 0),
        }
        _url = item.get("url") or ""
        if _url:
            entry["url"] = _url
        articles.append(entry)

    ticker_scores: dict[str, list[float]] = {}
    for item in feed:
        tk = item.get("ticker", "")
        if tk:
            ticker_scores.setdefault(tk, []).append(item.get("news_score", 0))
    ticker_summary = {
        tk: {
            "count": len(scores),
            "avg_score": round(sum(scores) / len(scores), 3),
            "max_score": round(max(scores), 3),
            "min_score": round(min(scores), 3),
        }
        for tk, scores in sorted(
            ticker_scores.items(),
            key=lambda kv: abs(sum(kv[1]) / len(kv[1])),
            reverse=True,
        )[:30]
    }

    segment_counts: dict[str, int] = {}
    for item in feed:
        seg = item.get("segment", "")
        if seg:
            segment_counts[seg] = segment_counts.get(seg, 0) + 1
    top_segments = dict(
        sorted(segment_counts.items(), key=lambda kv: kv[1], reverse=True)[:15]
    )

    ctx: dict[str, Any] = {
        "total_articles": len(feed),
        "top_articles": articles,
        "ticker_summary": ticker_summary,
        "top_segments": top_segments,
    }
    if fmp_data:
        ctx["fmp_financials"] = fmp_data
    if technicals:
        ctx["technicals"] = technicals
    if macro:
        ctx["macro"] = macro
    if economic_calendar:
        ctx["economic_calendar"] = economic_calendar
    if sector_performance:
        ctx["sector_performance"] = sector_performance
    if social_sentiment:
        ctx["social_sentiment"] = social_sentiment
    if analyst_forecasts:
        ctx["analyst_forecasts"] = analyst_forecasts
    if analyst_ratings:
        ctx["analyst_ratings"] = analyst_ratings
    if earnings_calendar:
        ctx["earnings_calendar"] = earnings_calendar
    if insider_trades:
        ctx["insider_trades"] = insider_trades
    if congressional_trades:
        ctx["congressional_trades"] = congressional_trades

    return json.dumps(ctx, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# LLM query (same OpenAI endpoint but with FMP-enriched system prompt)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior financial analyst assistant integrated into a real-time
news intelligence dashboard with access to multi-layer institutional-grade
financial data from FMP, Benzinga, Finnhub, and TradingView.

You have access to (when available in the data context):
- A live feed of classified news articles with sentiment scores and ticker mentions
- Real-time FMP quotes (price, change, volume, market cap, P/E, EPS)
- Company profiles (sector, industry, beta, description)
- Technical indicators (RSI, MACD, Stochastic, ADX, moving averages) from TradingView/FMP
- Economic calendar (GDP, CPI, FOMC, NFP — today's macro events with estimates vs actuals)
- Sector performance (GICS sector % changes for rotation analysis)
- Social sentiment (Reddit + Twitter mention counts, bullish/bearish scores from Finnhub)
- Analyst forecasts (price targets, consensus ratings, EPS estimates, recent upgrades/downgrades)
- Analyst ratings from Benzinga (upgrades, downgrades, price target changes)
- Earnings calendar (upcoming/recent EPS and revenue estimates vs actuals)
- Insider trades (recent executive buys/sells with transaction values)
- Congressional trades (Senate/House member stock trades)
- Macro data (when available)

Your role:
- Provide concise, actionable analysis that cross-references ALL available
  data layers — news sentiment, price action, technicals, social sentiment,
  analyst consensus, and macro environment.
- When FMP quote data is available, always cite current prices, change %,
  volume vs average, and P/E ratios to support your analysis.
- When social sentiment data is present, note retail attention levels
  (mention counts) and sentiment divergences from institutional signals.
- When analyst forecasts are present, cite price target upside/downside,
  consensus ratings, and recent grade changes.
- When economic calendar events are present, assess their potential market
  impact on the tickers being discussed.
- Identify disconnects between data layers (e.g. bullish news + bearish
  technicals, insider selling + analyst upgrades, social hype + weak
  fundamentals).
- When articles have a "url" field, include the source link inline using
  markdown link syntax, e.g. [headline](url).
- Use markdown formatting for readability.
- Be specific: cite tickers, scores, prices, and article headlines.
- If the data is insufficient to answer confidently, say so.
- Never fabricate data not present in the context.

Current date/time context is provided in the user message.
"""

_DEFAULT_MODEL = "gpt-4o"
_API_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)


@dataclass
class FMPLLMResponse:
    """Container for an FMP-enriched LLM response with metadata."""
    answer: str
    model: str
    cached: bool
    context_articles: int
    context_tickers: int
    fmp_tickers: int
    error: str = ""


def query_fmp_llm(
    question: str,
    context_json: str,
    api_key: str,
    *,
    model: str = _DEFAULT_MODEL,
    max_tokens: int = 2500,
    temperature: float = 0.3,
) -> FMPLLMResponse:
    """Send a question + FMP-enriched context to the OpenAI chat-completions API.

    Returns an ``FMPLLMResponse`` with the answer or an error message.
    """
    if not api_key:
        return FMPLLMResponse(
            answer="", model=model, cached=False,
            context_articles=0, context_tickers=0, fmp_tickers=0,
            error="No OpenAI API key configured.",
        )

    try:
        ctx_data = json.loads(context_json)
    except json.JSONDecodeError:
        ctx_data = {}
    n_articles = ctx_data.get("total_articles", 0)
    n_tickers = len(ctx_data.get("ticker_summary", {}))
    n_fmp = len(ctx_data.get("fmp_financials", {}))

    # Check cache
    digest = hashlib.sha256(context_json.encode()).hexdigest()[:16]
    ck = _cache_key(question, digest, model)
    cached_text = _get_cached(ck)
    if cached_text is not None:
        return FMPLLMResponse(
            answer=cached_text, model=model, cached=True,
            context_articles=n_articles, context_tickers=n_tickers,
            fmp_tickers=n_fmp,
        )

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    user_message = (
        f"Current time: {now_str}\n\n"
        f"## Question\n{question}\n\n"
        f"## Data Context (multi-layer: FMP financials, technicals, social, analyst, macro)\n"
        f"```json\n{context_json}\n```"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    _MAX_RETRIES = 2
    for _attempt in range(1, _MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=_API_TIMEOUT) as client:
                resp = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    return FMPLLMResponse(
                        answer="", model=model, cached=False,
                        context_articles=n_articles, context_tickers=n_tickers,
                        fmp_tickers=n_fmp,
                        error="OpenAI returned empty choices",
                    )
                answer = choices[0].get("message", {}).get("content", "").strip()
                break  # success
        except httpx.ReadTimeout:
            if _attempt < _MAX_RETRIES:
                logger.warning("OpenAI read timeout (attempt %d/%d), retrying…", _attempt, _MAX_RETRIES)
                time.sleep(2)
                continue
            return FMPLLMResponse(
                answer="", model=model, cached=False,
                context_articles=n_articles, context_tickers=n_tickers,
                fmp_tickers=n_fmp,
                error="OpenAI API read timeout after retries — try a simpler question or retry.",
            )
        except httpx.HTTPStatusError as exc:
            _safe = _APIKEY_RE.sub(r"\1=***", str(exc))
            logger.warning("OpenAI API error (FMP AI): %s", _safe, exc_info=True)
            return FMPLLMResponse(
                answer="", model=model, cached=False,
                context_articles=n_articles, context_tickers=n_tickers,
                fmp_tickers=n_fmp,
                error=f"OpenAI API error: {exc.response.status_code}",
            )
        except Exception as exc:
            _safe = _APIKEY_RE.sub(r"\1=***", str(exc))
            logger.warning("OpenAI query failed (FMP AI): %s", _safe, exc_info=True)
            return FMPLLMResponse(
                answer="", model=model, cached=False,
                context_articles=n_articles, context_tickers=n_tickers,
                fmp_tickers=n_fmp,
                error=f"Query failed: {_safe}",
            )

    _set_cached(ck, answer)
    return FMPLLMResponse(
        answer=answer, model=model, cached=False,
        context_articles=n_articles, context_tickers=n_tickers,
        fmp_tickers=n_fmp,
    )
