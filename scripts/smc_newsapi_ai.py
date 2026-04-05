from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx


EVENT_REGISTRY_ARTICLES_URL = "https://eventregistry.org/api/v1/article/getArticles"
MAX_KEYWORDS_PER_REQUEST = 60
MAX_ARTICLES_PER_REQUEST = 100
MIN_SYMBOL_LENGTH = 3


def _chunked(values: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [values[index : index + size] for index in range(0, len(values), size)]


def _normalize_symbols(symbols: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols:
        symbol = str(raw_symbol or "").strip().upper()
        if len(symbol) < MIN_SYMBOL_LENGTH or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _build_keyword_patterns(symbols: list[str]) -> dict[str, re.Pattern[str]]:
    return {
        symbol: re.compile(rf"(?<![A-Za-z0-9])\$?{re.escape(symbol)}(?![A-Za-z0-9])", re.IGNORECASE)
        for symbol in symbols
    }


def _match_symbols(title: str, patterns: dict[str, re.Pattern[str]]) -> list[str]:
    if not title:
        return []
    return sorted(symbol for symbol, pattern in patterns.items() if pattern.search(title))


def fetch_newsapi_articles(
    api_key: str,
    symbols: list[str],
    *,
    lookback_days: int = 2,
    articles_per_request: int = MAX_ARTICLES_PER_REQUEST,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        return []

    patterns = _build_keyword_patterns(normalized_symbols)
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=max(int(lookback_days), 1))
    max_articles = max(1, min(int(articles_per_request), MAX_ARTICLES_PER_REQUEST))

    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=20.0)

    seen_ids: set[str] = set()
    articles: list[dict[str, Any]] = []

    try:
        for keyword_chunk in _chunked(normalized_symbols, MAX_KEYWORDS_PER_REQUEST):
            params: list[tuple[str, str]] = [
                ("apiKey", api_key),
                ("resultType", "articles"),
                ("articlesCount", str(max_articles)),
                ("articlesSortBy", "date"),
                ("keywordOper", "or"),
                ("keywordLoc", "title"),
                ("lang", "eng"),
                ("dateStart", start_date.isoformat()),
                ("dateEnd", end_date.isoformat()),
                ("isDuplicateFilter", "skipDuplicates"),
                ("dataType", "news"),
                ("includeArticleTitle", "true"),
            ]
            params.extend(("keyword", keyword) for keyword in keyword_chunk)

            response = client.get(EVENT_REGISTRY_ARTICLES_URL, params=params)
            response.raise_for_status()
            payload = response.json()
            results = payload.get("articles", {}).get("results", [])
            if not isinstance(results, list):
                continue

            for item in results:
                if not isinstance(item, dict):
                    continue
                headline = str(item.get("title") or "").strip()
                matched_symbols = _match_symbols(headline, patterns)
                if not headline or not matched_symbols:
                    continue
                article_id = str(item.get("uri") or item.get("url") or headline)
                if article_id in seen_ids:
                    continue
                seen_ids.add(article_id)
                articles.append({"headline": headline, "tickers": matched_symbols})
    finally:
        if own_client:
            client.close()

    return articles