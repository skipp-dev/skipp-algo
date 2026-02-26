from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from .playbook import classify_news_event, classify_recency, classify_source_quality

_TICKER_RE = re.compile(r"\b[A-Z][A-Z0-9.-]{0,5}\b")

# Sentinel for sorting articles with no parseable date (sorts last).
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Common English words that look like tickers but aren't actual US-listed
# symbols.  Excludes legitimate tickers like "A" (Agilent), "AI" (C3.ai),
# "ON" (ON Semi), "IT" (Gartner) etc.
_TICKER_BLACKLIST: frozenset[str] = frozenset({
    "AN", "AS", "AT", "BE", "BY", "DO", "IF",
    "IN", "IS", "MY", "NO", "OF", "OK", "OR", "SO",
    "TO", "UP", "US", "WE",
})

# ---------------------------------------------------------------------------
# Keyword-based financial-news sentiment classifier
# ---------------------------------------------------------------------------
# FMP's fmp-articles endpoint does NOT provide pre-rated sentiment.
# We classify sentiment from article title/content using domain-specific
# keyword matching.  This is intentionally conservative — only clear
# directional language moves the score away from neutral.

_BULLISH_KEYWORDS: frozenset[str] = frozenset({
    "upgrade", "upgrades", "upgraded", "beat", "beats", "beating",
    "raise", "raises", "raised", "record", "bullish", "buy",
    "outperform", "rally", "rallies", "surge", "surges", "surging",
    "growth", "profit", "profits", "strong", "strength", "positive",
    "exceeds", "exceeded", "above", "higher", "upbeat", "boost",
    "boosted", "breakout", "acquisition", "acquire", "approval",
    "approved", "partnership", "expand", "expansion", "dividend",
    "buyback", "repurchase", "upside",
})

_BEARISH_KEYWORDS: frozenset[str] = frozenset({
    "downgrade", "downgrades", "downgraded", "miss", "misses",
    "missed", "cut", "cuts", "cutting", "decline", "declined",
    "declining", "loss", "losses", "selloff", "bearish", "sell",
    "underperform", "warning", "warns", "weak", "weakness", "layoff",
    "layoffs", "lawsuit", "recall", "recalled", "fraud", "investigate",
    "investigation", "negative", "below", "lower", "disappointing",
    "disappointed", "fails", "failed", "failure", "bankruptcy", "debt",
    "restructuring", "delay", "delayed", "downside", "suspend",
    "suspended", "penalty", "fine", "fined", "subpoena",
    "plunge", "plunges", "plunged", "plummets", "plummeted",
    "tumble", "tumbles", "tumbled", "slump", "slumps", "slumped",
    "crash", "crashed", "fell", "shrink", "shrinks",
    "shrinking", "widening", "widened", "unprofitable",
})

# Negation words that flip the sentiment of the *next* keyword.
# E.g. "no growth" → negated bullish = bearish, "not weak" → negated bearish.
_NEGATION_WORDS: frozenset[str] = frozenset({
    "no", "not", "never", "neither", "without",
    "cannot", "hardly", "barely",
    "despite", "although",
})

# Bearish multi-word phrases — checked against lowered raw text.
# Each match contributes 2 bearish points (same weight as a title keyword).
_BEARISH_PHRASES: tuple[str, ...] = (
    "net loss",
    "operating loss",
    "wider loss",
    "widening loss",
    "missed estimates",
    "missed expectations",
    "below estimates",
    "below expectations",
    "fell short",
    "falling short",
    "falls short",
    "revenue miss",
    "eps miss",
    "earnings miss",
    "weaker than expected",
    "lower than expected",
    "worse than expected",
    "disappointing results",
    "revenue decline",
    "profit decline",
    "share price fell",
    "shares fell",
    "stock fell",
    "shares dropped",
    "stock dropped",
    "negative earnings",
    "negative eps",
    "not profitable",
    "guidance cut",
    "lowered guidance",
    "reduced guidance",
    "slashed guidance",
    "weak guidance",
    "warns of",
    "warning of",
)

_BULLISH_PHRASES: tuple[str, ...] = (
    "beat estimates",
    "beat expectations",
    "beats estimates",
    "beats expectations",
    "above estimates",
    "above expectations",
    "stronger than expected",
    "better than expected",
    "record revenue",
    "record earnings",
    "record profit",
    "raised guidance",
    "raises guidance",
    "positive guidance",
    "strong guidance",
    "upward revision",
)

_WORD_RE = re.compile(r"\b[a-z]+\b")


def _count_negation_aware(
    words: list[str],
    bull_kw: frozenset[str],
    bear_kw: frozenset[str],
    neg_words: frozenset[str],
) -> tuple[int, int]:
    """Count bullish/bearish keyword hits with negation awareness.

    When a negation word immediately precedes a keyword, the keyword's
    sentiment is flipped (bullish → bearish and vice versa).
    Returns (bull_count, bear_count).
    """
    bull = 0
    bear = 0
    prev_neg = False
    for w in words:
        if w in neg_words:
            prev_neg = True
            continue
        if w in bull_kw:
            if prev_neg:
                bear += 1   # "no growth" → bearish
            else:
                bull += 1
        elif w in bear_kw:
            if prev_neg:
                bull += 1   # "not weak" → bullish
            else:
                bear += 1
        else:
            prev_neg = False
            continue
        prev_neg = False
    return bull, bear


def _count_phrases(text: str, phrases: tuple[str, ...]) -> int:
    """Count how many distinct phrases from the list appear in lowered text."""
    count = 0
    for phrase in phrases:
        if phrase in text:
            count += 1
    return count


def classify_article_sentiment(title: str, content: str = "") -> tuple[str, float]:
    """Classify financial news sentiment from title and content.

    Returns ``(label, score)`` where:
    - label: ``"bullish"`` | ``"neutral"`` | ``"bearish"``
    - score: float in ``[-1.0, 1.0]``

    Uses negation-aware keyword matching and multi-word phrase detection.
    Title words receive 2x weight (headlines are the strongest signal).
    """
    title_lower = title.lower()
    content_lower = content[:1200].lower() if content else ""

    title_word_list = _WORD_RE.findall(title_lower)
    content_word_list = _WORD_RE.findall(content_lower) if content_lower else []

    # Negation-aware keyword counting
    t_bull, t_bear = _count_negation_aware(title_word_list, _BULLISH_KEYWORDS, _BEARISH_KEYWORDS, _NEGATION_WORDS)
    c_bull, c_bear = _count_negation_aware(content_word_list, _BULLISH_KEYWORDS, _BEARISH_KEYWORDS, _NEGATION_WORDS)

    # Title matches count double
    bull = t_bull * 2 + c_bull
    bear = t_bear * 2 + c_bear

    # Multi-word phrase matching (2 pts each for title, 1 pt for content)
    bull += _count_phrases(title_lower, _BULLISH_PHRASES) * 2
    bear += _count_phrases(title_lower, _BEARISH_PHRASES) * 2
    bull += _count_phrases(content_lower, _BULLISH_PHRASES)
    bear += _count_phrases(content_lower, _BEARISH_PHRASES)

    total = bull + bear
    if total == 0:
        return "neutral", 0.0

    net = bull - bear
    score = max(-1.0, min(1.0, net / max(total, 1)))

    if score > 0.15:
        return "bullish", round(score, 2)
    if score < -0.15:
        return "bearish", round(score, 2)
    return "neutral", round(score, 2)


def _sentiment_emoji(label: str) -> str:
    return {"bullish": "🟢", "bearish": "🔴"}.get(label, "🟡")


def _extract_symbols_from_tickers(raw: str) -> set[str]:
    """Parse FMP tickers metadata into plain symbols.

    Examples:
    - "NASDAQ:NVDA" -> {"NVDA"}
    - "NYSE:NMM, NASDAQ:PLTR" -> {"NMM", "PLTR"}
    """
    out: set[str] = set()
    for part in (raw or "").split(","):
        token = part.strip().upper()
        if not token:
            continue
        if ":" in token:
            token = token.split(":")[-1].strip()
        if token and _TICKER_RE.fullmatch(token) and token not in _TICKER_BLACKLIST:
            out.add(token)
    return out


def _parse_article_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(iso_text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        pass
    # FMP stable articles usually: "YYYY-MM-DD HH:MM:SS"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def build_news_scores(
    symbols: list[str],
    articles: list[dict[str, Any]],
    now_utc: datetime | None = None,
) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    """Build per-symbol catalyst scores from FMP articles.

    Returns:
      - news_score_by_symbol: score contribution (float)
      - news_metrics_by_symbol: explainability metrics
    """
    now = now_utc or datetime.now(UTC)
    window_24h = now - timedelta(hours=24)
    window_2h = now - timedelta(hours=2)

    universe = {s.strip().upper() for s in symbols if s.strip()}
    metrics: dict[str, dict[str, Any]] = {
        s: {
            "mentions_total": 0,
            "mentions_24h": 0,
            "mentions_2h": 0,
            "latest_article_utc": None,
            "news_catalyst_score": 0.0,
            "articles": [],
        }
        for s in universe
    }

    # Precompile regex patterns for fallback matching to avoid false positives (e.g. "A" in "APPLE")
    # Only match in titles (not full content) — content matching is too noisy
    # and causes O(N_symbols × N_articles × content_len) work.
    for article in articles:
        ticker_meta = str(article.get("tickers") or "")
        title = str(article.get("title") or "").upper()
        article_dt = _parse_article_datetime(article.get("date"))

        mentioned = _extract_symbols_from_tickers(ticker_meta)

        # Fallback: symbol mention in title only (content matching is too
        # noisy — e.g. "MSFT" mentioned in a story primarily about "AAPL").
        # Pre-extract word-boundary tokens from the title for O(1) lookup.
        title_tokens = set(_TICKER_RE.findall(title))
        for sym in title_tokens:
            if sym in universe and sym not in mentioned and sym not in _TICKER_BLACKLIST:
                mentioned.add(sym)

        for sym in mentioned:
            if sym not in universe:
                continue
            row = metrics[sym]
            row["mentions_total"] += 1

            # Capture article detail for explainability (newest first, max 5)
            raw_title = str(article.get("title") or "").strip()
            raw_content = str(article.get("content") or "").strip()
            sent_label, sent_score = classify_article_sentiment(raw_title, raw_content)
            source_str = str(article.get("source") or article.get("site") or "").strip()

            # --- Playbook enrichment: event class, recency, source quality ---
            event_info = classify_news_event(raw_title, raw_content)
            recency_info = classify_recency(article_dt, now)
            source_info = classify_source_quality(source_str, raw_title)

            article_info: dict[str, Any] = {
                "title": raw_title,
                "link": str(article.get("link") or article.get("url") or "").strip(),
                "source": source_str,
                "date": article_dt.isoformat() if article_dt else None,
                "sentiment": sent_label,
                "sentiment_score": sent_score,
                # Playbook fields
                "event_class": event_info["event_class"],
                "event_label": event_info["event_label"],
                "materiality": event_info["materiality"],
                "recency_bucket": recency_info["recency_bucket"],
                "age_minutes": recency_info["age_minutes"],
                "is_actionable": recency_info["is_actionable"],
                "source_tier": source_info["source_tier"],
                "source_rank": source_info["source_rank"],
            }
            # Collect all matching articles; we'll sort + trim after the loop.
            row["articles"].append(article_info)

            if article_dt is not None:
                # Guard against future-dated articles (provider timezone drift):
                # they count as mentions_total but must not inflate recency windows.
                if window_24h <= article_dt <= now:
                    row["mentions_24h"] += 1
                if window_2h <= article_dt <= now:
                    row["mentions_2h"] += 1

                latest_dt: datetime | None = row["latest_article_utc"]
                # Compare datetime objects to avoid the '.' vs '+' ASCII
                # ordering bug that occurs with ISO strings when microseconds
                # are present (e.g. '14:30:00.654321+00:00' > '14:30:00+00:00'
                # under naive string ordering despite representing the same or
                # an earlier moment than '15:30:00+00:00').
                if article_dt <= now and (
                    latest_dt is None or article_dt > latest_dt
                ):
                    row["latest_article_utc"] = article_dt

    scores: dict[str, float] = {}
    for sym, row in metrics.items():
        # Keep only the 5 newest articles (sort by date descending, None dates last).
        # Use the module-level _EPOCH sentinel for articles with no parseable date.
        # Sort key uses the already-stored ISO date string directly via
        # _parse_article_datetime (returns datetime | None).
        row["articles"].sort(
            key=lambda a: _parse_article_datetime(a.get("date")) or _EPOCH,
            reverse=True,
        )
        row["articles"] = row["articles"][:5]

        # Subtract 2h mentions from 24h count so articles are not double-counted
        # across both recency windows (2h articles are already boosted at 0.5).
        mentions_24h_only = max(row["mentions_24h"] - row["mentions_2h"], 0)
        score = min(2.0, row["mentions_2h"] * 0.5 + mentions_24h_only * 0.15)
        row["news_catalyst_score"] = round(score, 4)
        scores[sym] = round(score, 4)
        # Convert stored datetime → ISO string for serialisable output.
        if row["latest_article_utc"] is not None:
            row["latest_article_utc"] = row["latest_article_utc"].isoformat()

        # --- Per-symbol sentiment aggregation ---
        arts = row.get("articles") or []
        if arts:
            sent_scores = [a.get("sentiment_score", 0.0) for a in arts]
            avg_sent = sum(sent_scores) / len(sent_scores)
            if avg_sent > 0.15:
                row["sentiment_label"] = "bullish"
            elif avg_sent < -0.15:
                row["sentiment_label"] = "bearish"
            else:
                row["sentiment_label"] = "neutral"
            row["sentiment_emoji"] = _sentiment_emoji(row["sentiment_label"])
            row["sentiment_score"] = round(avg_sent, 2)

            # --- Per-symbol playbook aggregation (from best article) ---
            best = arts[0]  # newest-first after sort
            row["event_class"] = best.get("event_class", "UNKNOWN")
            row["event_label"] = best.get("event_label", "generic")
            row["materiality"] = best.get("materiality", "LOW")
            row["recency_bucket"] = best.get("recency_bucket", "UNKNOWN")
            row["age_minutes"] = best.get("age_minutes")
            row["is_actionable"] = best.get("is_actionable", False)
            row["source_tier"] = best.get("source_tier", "TIER_3")
            row["source_rank"] = best.get("source_rank", 3)

            # Collect all event labels across articles for full picture
            all_labels: list[str] = []
            for a in arts:
                lbl = a.get("event_label")
                if lbl and lbl not in all_labels:
                    all_labels.append(lbl)
            row["event_labels_all"] = all_labels
        else:
            row["sentiment_label"] = "neutral"
            row["sentiment_emoji"] = "🟡"
            row["sentiment_score"] = 0.0
            row["event_class"] = "UNKNOWN"
            row["event_label"] = "generic"
            row["materiality"] = "LOW"
            row["recency_bucket"] = "UNKNOWN"
            row["age_minutes"] = None
            row["is_actionable"] = False
            row["source_tier"] = "TIER_3"
            row["source_rank"] = 3
            row["event_labels_all"] = []

    return scores, metrics
