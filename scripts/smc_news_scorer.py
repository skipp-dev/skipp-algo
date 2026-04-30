"""Batch news-sentiment scorer for SMC micro-profile generation.

Wraps ``newsstack_fmp.scoring.classify_and_score`` to compute per-ticker
polarity aggregates and a global heat score suitable for Pine Library
consumption.

Enhanced (WP-NW3): time-weighted polarity — recent news count more.
Enhanced (WP-NW4): category map, count map, breaking tickers, most-mentioned.
"""
from __future__ import annotations

import math
import time as _time
from typing import Any

from newsstack_fmp.scoring import classify_and_score

# Categories that qualify as "breaking" when impact is high enough.
_BREAKING_CATEGORIES = frozenset({"halt", "offering", "mna", "fda"})


def compute_news_sentiment(
    symbols: list[str],
    articles: list[dict[str, Any]],
    *,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    """Score *articles* and aggregate sentiment per ticker.

    Parameters
    ----------
    symbols:
        Universe of tickers to consider.  Articles referencing tickers
        outside this set are silently ignored.
    articles:
        Each dict must have at least ``headline`` (str) and ``tickers``
        (list[str]). Optional ``snippet`` / ``text`` / ``content`` fields
        are forwarded to the classifier as extra polarity context.
        Optional ``published_ts`` (float epoch) enables time-weighted
        scoring; when absent a 12 h default age is assumed.

    Returns
    -------
    dict with ``bullish_tickers``, ``bearish_tickers``, ``neutral_tickers``,
    ``news_heat_global``, ``ticker_heat_map``, plus WP-NW4 fields:
    ``news_category_map``, ``news_count_map``, ``breaking_tickers``,
    ``high_impact_news_count``, ``most_mentioned_ticker``.
    """
    universe = {s.upper() for s in symbols}

    article_count = len(articles)
    empty_headline_count = 0
    matched_article_count = 0
    unique_recognized_tickers: set[str] = set()
    recognized_ticker_mentions = 0
    polarity_distribution = {"positive": 0, "negative": 0, "neutral": 0}

    now_ts = _time.time()

    # Per-ticker aggregation buckets
    ticker_polarities: dict[str, list[tuple[float, float]]] = {}  # (polarity, weight)

    # WP-NW4: category & count tracking
    ticker_top_category: dict[str, tuple[str, float]] = {}  # ticker → (category, impact)
    ticker_article_count: dict[str, int] = {}
    breaking_tickers_set: set[str] = set()

    for article in articles:
        headline = str(article.get("headline") or "").strip()
        snippet = str(
            article.get("snippet") or article.get("text") or article.get("content") or ""
        ).strip()
        if not headline:
            empty_headline_count += 1
        art_tickers = article.get("tickers") or []
        valid_tickers = {
            raw_ticker.upper()
            for raw_ticker in art_tickers
            if raw_ticker and raw_ticker.upper() in universe
        }
        if not valid_tickers:
            continue

        matched_article_count += 1
        recognized_ticker_mentions += len(valid_tickers)
        unique_recognized_tickers.update(valid_tickers)

        scored_article = dict(article)
        scored_article["headline"] = headline
        scored_article["snippet"] = snippet
        result = classify_and_score(scored_article, cluster_count=1)
        if result.polarity > 0.1:
            polarity_distribution["positive"] += 1
        elif result.polarity < -0.1:
            polarity_distribution["negative"] += 1
        else:
            polarity_distribution["neutral"] += 1

        # WP-NW3: time-based recency weight
        published_ts = float(article.get("published_ts") or 0)
        # default age (12 h) when timestamp unknown
        age_hours = (
            max(0.0, (now_ts - published_ts) / 3600.0) if published_ts > 0 else 12.0
        )
        # Exponential decay: 1 h → 1.0, 6 h → 0.65, 12 h → 0.42, 24 h → 0.18
        recency_weight = max(0.1, math.exp(-0.07 * age_hours))

        for ticker in valid_tickers:
            ticker_polarities.setdefault(ticker, []).append(
                (result.polarity, recency_weight)
            )
            # WP-NW4: track article count + top category per ticker
            ticker_article_count[ticker] = ticker_article_count.get(ticker, 0) + 1
            prev = ticker_top_category.get(ticker)
            if prev is None or result.impact > prev[1]:
                ticker_top_category[ticker] = (result.category, result.impact)
            # Breaking detection
            if result.category in _BREAKING_CATEGORIES and result.impact >= 0.85:
                breaking_tickers_set.add(ticker)

    # WP-NW3: weighted average polarity per ticker
    ticker_scores: dict[str, float] = {}
    for ticker, pol_weights in ticker_polarities.items():
        total_weight = sum(w for _, w in pol_weights)
        if total_weight > 0:
            ticker_scores[ticker] = sum(p * w for p, w in pol_weights) / total_weight
        else:
            ticker_scores[ticker] = 0.0

    bullish: list[str] = []
    bearish: list[str] = []
    neutral: list[str] = []
    for ticker in sorted(ticker_scores):
        score = ticker_scores[ticker]
        if score > 0.1:
            bullish.append(ticker)
        elif score < -0.1:
            bearish.append(ticker)
        else:
            neutral.append(ticker)

    # Global heat = average of all ticker scores
    all_scores = list(ticker_scores.values())
    news_heat_global = sum(all_scores) / len(all_scores) if all_scores else 0.0

    # Pine-compatible heat map string
    heat_parts = [f"{t}:{ticker_scores[t]:.2f}" for t in sorted(ticker_scores)]
    ticker_heat_map = ",".join(heat_parts)

    # WP-NW4: category map, count map, breaking list, most-mentioned
    news_category_map = ",".join(
        f"{t}:{cat}" for t, (cat, _) in sorted(ticker_top_category.items())
    )
    news_count_map = ",".join(
        f"{t}:{n}" for t, n in sorted(ticker_article_count.items())
    )
    breaking_tickers = sorted(breaking_tickers_set)
    high_impact_news_count = sum(
        1 for n in ticker_article_count.values() if n >= 5
    )
    most_mentioned_ticker = (
        max(ticker_article_count, key=ticker_article_count.get)  # type: ignore[arg-type]
        if ticker_article_count
        else ""
    )

    payload: dict[str, Any] = {
        "bullish_tickers": bullish,
        "bearish_tickers": bearish,
        "neutral_tickers": neutral,
        "news_heat_global": round(news_heat_global, 4),
        "ticker_heat_map": ticker_heat_map,
        # WP-NW4 fields
        "news_category_map": news_category_map,
        "news_count_map": news_count_map,
        "breaking_tickers": breaking_tickers,
        "high_impact_news_count": high_impact_news_count,
        "most_mentioned_ticker": most_mentioned_ticker,
    }
    if include_diagnostics:
        payload["diagnostics"] = {
            "article_count": article_count,
            "matched_article_count": matched_article_count,
            "empty_headline_count": empty_headline_count,
            "recognized_ticker_mentions": recognized_ticker_mentions,
            "unique_recognized_ticker_count": len(unique_recognized_tickers),
            "polarity_distribution": dict(polarity_distribution),
        }
    return payload
