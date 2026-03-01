"""AI Insights engine — structured reasoning over the live news feed.

Assembles a compact context snapshot from the current feed (articles,
tickers, sentiment scores) and optional technicals / macro data, then
queries an OpenAI-compatible chat-completions endpoint for analysis.

The module deliberately uses **httpx** (already a project dependency)
instead of the ``openai`` SDK to avoid an extra install.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_APIKEY_RE = re.compile(r"(apikey|api_key|token|key)=[^&\s]+", re.IGNORECASE)

# ---------------------------------------------------------------------------
# In-memory response cache (thread-safe)
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, str]] = {}   # hash -> (timestamp, response)
_CACHE_TTL_S = 300.0  # 5 minutes


def _cache_key(question: str, context_digest: str, model: str) -> str:
    raw = f"{model}|{question}|{context_digest}"
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
        # Evict old entries if cache grows too large
        if len(_cache) > 200:
            cutoff = time.time() - _CACHE_TTL_S
            expired = [k for k, (t, _) in _cache.items() if t < cutoff]
            for k in expired:
                del _cache[k]
        _cache[key] = (time.time(), text)


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def assemble_context(
    feed: list[dict[str, Any]],
    *,
    technicals: dict[str, Any] | None = None,
    macro: dict[str, Any] | None = None,
    max_articles: int = 40,
) -> str:
    """Build a compact JSON context string from the current terminal state.

    Returns a JSON string suitable for inclusion in an LLM prompt.
    Limits to *max_articles* (sorted by ``news_score`` descending) to
    stay within token budgets.
    """
    # --- Articles (compact representation) ---
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

    # --- Ticker sentiment summary ---
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

    # --- Segment summary ---
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
    if technicals:
        ctx["technicals"] = technicals
    if macro:
        ctx["macro"] = macro

    return json.dumps(ctx, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# LLM query
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior financial analyst assistant integrated into a real-time
news intelligence dashboard.  You have access to a live feed of classified news articles
with sentiment scores, ticker mentions, sector segments, and (when available)
technical indicators and macro data.

Your role:
- Provide concise, actionable analysis based on the data provided.
- Identify key themes, sentiment shifts, and notable signals.
- When technicals are available, cross-reference news sentiment with
  indicator signals (RSI, MACD, ADX, etc.).
- Be specific: cite tickers, scores, and article headlines when relevant.
- When articles have a "url" field, include the source link inline using
  markdown link syntax, e.g. [headline](url).  Always cite at least the
  key supporting articles so the user can verify the source.
- Use markdown formatting for readability.
- If the data is insufficient to answer confidently, say so.
- Never fabricate data not present in the context.

Current date/time context is provided in the user message.
"""

_DEFAULT_MODEL = "gpt-4o"
_API_TIMEOUT = 30.0  # seconds


@dataclass
class LLMResponse:
    """Container for an LLM response with metadata."""
    answer: str
    model: str
    cached: bool
    context_articles: int
    context_tickers: int
    error: str = ""


def query_llm(
    question: str,
    context_json: str,
    api_key: str,
    *,
    model: str = _DEFAULT_MODEL,
    max_tokens: int = 2500,
    temperature: float = 0.3,
) -> LLMResponse:
    """Send a question + context to the OpenAI chat-completions API.

    Returns an ``LLMResponse`` with the answer or an error message.
    Uses an in-memory cache keyed on (question, context digest, model).
    """
    if not api_key:
        return LLMResponse(
            answer="", model=model, cached=False,
            context_articles=0, context_tickers=0,
            error="No OpenAI API key configured.",
        )

    # Parse context for metadata
    try:
        ctx_data = json.loads(context_json)
    except json.JSONDecodeError:
        ctx_data = {}
    n_articles = ctx_data.get("total_articles", 0)
    n_tickers = len(ctx_data.get("ticker_summary", {}))

    # Check cache
    digest = hashlib.sha256(context_json.encode()).hexdigest()[:16]
    ck = _cache_key(question, digest, model)
    cached_text = _get_cached(ck)
    if cached_text is not None:
        return LLMResponse(
            answer=cached_text, model=model, cached=True,
            context_articles=n_articles, context_tickers=n_tickers,
        )

    # Build messages
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    user_message = (
        f"Current time: {now_str}\n\n"
        f"## Question\n{question}\n\n"
        f"## Data Context\n```json\n{context_json}\n```"
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
            answer = data["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as exc:
        _safe = _APIKEY_RE.sub(r"\1=***", str(exc))
        logger.warning("OpenAI API error: %s", _safe, exc_info=True)
        return LLMResponse(
            answer="", model=model, cached=False,
            context_articles=n_articles, context_tickers=n_tickers,
            error=f"OpenAI API error: {exc.response.status_code}",
        )
    except Exception as exc:
        _safe = _APIKEY_RE.sub(r"\1=***", str(exc))
        logger.warning("OpenAI query failed: %s", _safe, exc_info=True)
        return LLMResponse(
            answer="", model=model, cached=False,
            context_articles=n_articles, context_tickers=n_tickers,
            error=f"Query failed: {_safe}",
        )

    _set_cached(ck, answer)
    return LLMResponse(
        answer=answer, model=model, cached=False,
        context_articles=n_articles, context_tickers=n_tickers,
    )


# ---------------------------------------------------------------------------
# Preset questions
# ---------------------------------------------------------------------------

PRESET_QUESTIONS: list[tuple[str, str]] = [
    ("📊 Market Pulse", "Give a concise market pulse summary based on the current news feed. Highlight the dominant sentiment, most-mentioned tickers, and any notable theme shifts."),
    ("🔥 Top Movers", "Which tickers have the strongest positive or negative sentiment signals right now? List the top 5 bullish and top 5 bearish, with their scores and key headlines."),
    ("⚠️ Risk Signals", "Identify any risk signals, red flags, or negative catalysts in the current feed. Focus on high-impact items like earnings misses, regulatory actions, downgrades, or sector-wide concerns."),
    ("🏗️ Sector Themes", "What are the dominant sector themes in the current news cycle? Group by segment/industry and highlight cross-sector signals."),
    ("💡 Trade Ideas", "Based on the current sentiment data and any available technicals, suggest high-conviction trade ideas with rationale. Include both long and short opportunities. Provide at least 5 ideas (up to 10) when there are enough tickers with strong scores (|score| >= 0.3). For each idea cite the supporting article headlines with their source links."),
    ("🔮 Outlook", "What is the likely near-term direction based on the current news flow? Consider sentiment momentum, volume of coverage, and any macro signals."),
]
