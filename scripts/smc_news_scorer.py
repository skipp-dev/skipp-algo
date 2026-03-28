"""Batch news-sentiment scorer for SMC micro-profile generation.

Wraps ``newsstack_fmp.scoring.classify_and_score`` to compute per-ticker
polarity aggregates and a global heat score suitable for Pine Library
consumption.
"""
from __future__ import annotations

from typing import Any

from newsstack_fmp.scoring import classify_and_score


def compute_news_sentiment(
    symbols: list[str],
    articles: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score *articles* and aggregate sentiment per ticker.

    Parameters
    ----------
    symbols:
        Universe of tickers to consider.  Articles referencing tickers
        outside this set are silently ignored.
    articles:
        Each dict must have at least ``headline`` (str) and ``tickers``
        (list[str]).

    Returns
    -------
    dict with ``bullish_tickers``, ``bearish_tickers``, ``neutral_tickers``,
    ``news_heat_global``, and ``ticker_heat_map``.
    """
    universe = {s.upper() for s in symbols}

    # Accumulate polarity per ticker
    ticker_polarities: dict[str, list[float]] = {t: [] for t in universe}

    for article in articles:
        result = classify_and_score(article, cluster_count=1)
        art_tickers = article.get("tickers") or []
        for raw_ticker in art_tickers:
            ticker = raw_ticker.upper()
            if ticker in ticker_polarities:
                ticker_polarities[ticker].append(result.polarity)

    # Average polarity per ticker
    ticker_scores: dict[str, float] = {}
    for ticker, pols in ticker_polarities.items():
        ticker_scores[ticker] = sum(pols) / len(pols) if pols else 0.0

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

    return {
        "bullish_tickers": bullish,
        "bearish_tickers": bearish,
        "neutral_tickers": neutral,
        "news_heat_global": round(news_heat_global, 4),
        "ticker_heat_map": ticker_heat_map,
    }
