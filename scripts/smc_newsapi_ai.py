from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import httpx

EVENT_REGISTRY_ARTICLES_URL = "https://eventregistry.org/api/v1/article/getArticles"
EVENT_REGISTRY_EVENTS_URL = "https://eventregistry.org/api/v1/event/getEvents"
EVENT_REGISTRY_ARTICLE_FEED_URL = "https://eventregistry.org/api/v1/minuteStreamArticles"
MAX_KEYWORDS_PER_REQUEST = 60
TARGET_KEYWORDS_PER_REQUEST = 6
MAX_ARTICLES_PER_REQUEST = 100
# Default articlesCount for public fetch entry points. Capped well below
# the API ceiling (MAX_ARTICLES_PER_REQUEST=100) so that broad keyword
# searches (e.g. "Apple" with ~9M matches) do not push the round-trip
# beyond the httpx timeout. See P-7 in docs/reviews/2026-04-24-system-review.md.
DEFAULT_ARTICLES_PER_REQUEST = 50
MAX_EVENTS_PER_REQUEST = 50
MAX_FEED_ARTICLES_PER_REQUEST = 2000
ARTICLE_FEED_MAX_AGE_SECONDS = 240 * 60
MIN_SYMBOL_LENGTH = 3
# Per-request httpx timeout for every Event Registry call. Bumped from 20.0s
# (2026-04-30) after live audit showed broad-keyword `getArticles` round-trips
# of up to ~24 s — see P-7 in docs/reviews/2026-04-24-system-review.md.
HTTPX_REQUEST_TIMEOUT_SECONDS = 45.0
_STRICT_MARKET_CONTEXT_SYMBOLS = {
    "AMT",
    "CAT",
    "LIN",
    "PG",
}
_MARKET_SOURCE_HINTS = (
    "benzinga",
    "bloomberg",
    "barron",
    "cnbc",
    "dow jones",
    "investing.com",
    "marketwatch",
    "reuters",
    "seeking alpha",
    "the fly",
    "wall street journal",
    "wsj",
    "zacks",
)
_STRICT_CONTEXT_MAX_SYMBOL_LENGTH = 3
_UPPERCASE_EXACT_MAX_SYMBOL_LENGTH = 4

_TOKEN_EXHAUSTED_HINTS = (
    "used all available tokens",
    "subscribe to a paid plan",
)

_RequestParam = tuple[str, str | int | float | bool | None]


class NewsApiAiProviderError(RuntimeError):
    def __init__(self, provider_status: str, detail: str, *, status_code: int | None = None) -> None:
        self.provider_status = str(provider_status or "http_error").strip() or "http_error"
        self.error_code = self.provider_status
        self.detail = str(detail or "").strip()
        self.status_code = status_code
        super().__init__(
            f"{self.provider_status}: {self.detail}" if self.detail else self.provider_status
        )


def _chunked(values: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [values[index : index + size] for index in range(0, len(values), size)]


def _balanced_keyword_chunks(
    values: list[str],
    *,
    target_size: int,
    total_result_limit: int,
) -> list[tuple[list[str], int]]:
    chunks = _chunked(values, target_size)
    if not chunks:
        return []
    per_chunk_limit = max(1, (max(int(total_result_limit), 1) + len(chunks) - 1) // len(chunks))
    return [(chunk, per_chunk_limit) for chunk in chunks]


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
    patterns: dict[str, re.Pattern[str]] = {}
    for symbol in symbols:
        escaped = re.escape(symbol)
        patterns[symbol] = re.compile(rf"(?<![A-Za-z0-9])\$?{escaped}(?![A-Za-z0-9])", re.IGNORECASE)
    return patterns


# Bounded cache (A-2): the per-symbol compiled-regex cache is keyed by ticker.
# Universe is ~500 symbols typical, ~1k worst-case. maxsize=1024 keeps memory
# bounded across long-running workers without measurable thrash for in-scope
# universes; oversized universes degrade to recompiling least-recently-used
# patterns (which is strictly cheaper than the previous unbounded growth).
@lru_cache(maxsize=1024)
def _strict_market_context_pattern(symbol: str) -> re.Pattern[str]:
    escaped = re.escape(symbol)
    return re.compile(
        rf"(?:\${escaped}\b|\b(?:NASDAQ|NYSE|NYSEAMERICAN|NYSEARCA|AMEX)\s*:?\s*{escaped}\b|\b{escaped}\s+(?:stock|shares?|equity|etf)\b)",
        re.IGNORECASE,
    )


@lru_cache(maxsize=1024)  # A-2: bounded; see _strict_market_context_pattern.
def _uppercase_exact_pattern(symbol: str) -> re.Pattern[str]:
    escaped = re.escape(symbol)
    return re.compile(rf"(?<![A-Za-z0-9])\$?{escaped}(?![A-Za-z0-9])")


def _has_market_source_hint(source_name: str) -> bool:
    lowered = str(source_name or "").strip().lower()
    return any(token in lowered for token in _MARKET_SOURCE_HINTS)


def _is_short_alpha_symbol(symbol: str) -> bool:
    return symbol.isalpha() and MIN_SYMBOL_LENGTH <= len(symbol) <= _UPPERCASE_EXACT_MAX_SYMBOL_LENGTH


def _match_symbol(text: str, symbol: str, pattern: re.Pattern[str], *, source_name: str) -> bool:
    if not text:
        return False
    if symbol in _STRICT_MARKET_CONTEXT_SYMBOLS:
        return bool(_strict_market_context_pattern(symbol).search(text))
    if _is_short_alpha_symbol(symbol):
        has_market_context = bool(_strict_market_context_pattern(symbol).search(text))
        if len(symbol) <= _STRICT_CONTEXT_MAX_SYMBOL_LENGTH:
            return has_market_context or (
                bool(_uppercase_exact_pattern(symbol).search(text)) and _has_market_source_hint(source_name)
            )
        return has_market_context or bool(_uppercase_exact_pattern(symbol).search(text))
    return bool(pattern.search(text))


def _match_symbols(title: str, patterns: dict[str, re.Pattern[str]], *, source_name: str = "") -> list[str]:
    if not title:
        return []
    return sorted(
        symbol
        for symbol, pattern in patterns.items()
        if _match_symbol(title, symbol, pattern, source_name=source_name)
    )


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("eng", "en", "title", "summary", "text", "value"):
            candidate = _coerce_text(value.get(key))
            if candidate:
                return candidate
        for nested in value.values():
            candidate = _coerce_text(nested)
            if candidate:
                return candidate
        return ""
    if isinstance(value, list):
        for nested in value:
            candidate = _coerce_text(nested)
            if candidate:
                return candidate
        return ""
    return str(value).strip()


def _article_source_name(item: dict[str, Any]) -> str:
    source = item.get("source")
    if isinstance(source, dict):
        return str(source.get("title") or source.get("name") or source.get("uri") or source.get("domain") or "").strip()
    return str(source or "").strip()


def _article_published_value(item: dict[str, Any]) -> str:
    return str(
        item.get("dateTimePub")
        or item.get("dateTime")
        or item.get("published")
        or item.get("date")
        or ""
    ).strip()


def _article_content(item: dict[str, Any]) -> str:
    return str(item.get("body") or item.get("content") or item.get("summary") or item.get("snippet") or "").strip()


def _extract_results(payload: dict[str, Any], container_key: str) -> list[dict[str, Any]]:
    container = payload.get(container_key)
    if isinstance(container, dict):
        results = container.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
    if isinstance(container, list):
        return [item for item in container if isinstance(item, dict)]
    fallback_results = payload.get("results")
    if isinstance(fallback_results, list):
        return [item for item in fallback_results if isinstance(item, dict)]
    return []


def _response_error_text(response: httpx.Response | Any) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = getattr(response, "text", "")
    detail = _coerce_text(payload)
    if detail:
        return detail
    return str(getattr(response, "text", "") or "").strip()


def _classify_http_error(status_code: int, detail: str) -> tuple[str, str]:
    lowered = str(detail or "").lower()
    if status_code == 403 and any(hint in lowered for hint in _TOKEN_EXHAUSTED_HINTS):
        return "quota_exhausted", "Event Registry token quota exhausted or paid plan required"
    if status_code == 401:
        return "auth_failed", "Event Registry authentication failed"
    if status_code == 429:
        return "rate_limited", "Event Registry rate limit hit"
    if status_code == 403:
        return "access_denied", "Event Registry access denied"
    if status_code >= 500:
        return "upstream_error", f"Event Registry upstream error ({status_code})"
    return "http_error", f"Event Registry HTTP {status_code}"


def _request_payload(
    client: httpx.Client | Any,
    url: str,
    *,
    params: list[_RequestParam],
) -> dict[str, Any]:
    response = client.get(url, params=params)
    status_code = int(getattr(response, "status_code", 200) or 200)
    if status_code >= 400:
        detail = _response_error_text(response)
        provider_status, safe_detail = _classify_http_error(status_code, detail)
        raise NewsApiAiProviderError(provider_status, safe_detail, status_code=status_code)
    payload = response.json()
    if isinstance(payload, dict):
        return payload
    return {}


def _can_use_article_feed(article_feed_after_epoch: float | None, *, now: datetime) -> bool:
    if article_feed_after_epoch is None:
        return False
    try:
        after_epoch = float(article_feed_after_epoch)
    except (TypeError, ValueError):
        return False
    if after_epoch <= 0.0:
        return False
    age_seconds = now.timestamp() - after_epoch
    return 0.0 <= age_seconds <= ARTICLE_FEED_MAX_AGE_SECONDS


def _article_feed_after_timestamp(article_feed_after_epoch: float, *, now: datetime) -> str:
    after_dt = datetime.fromtimestamp(float(article_feed_after_epoch), tz=UTC)
    effective_dt = min(after_dt, now)
    return effective_dt.strftime("%Y-%m-%dT%H:%M:%S")


def _build_feed_request_params(
    api_key: str,
    keyword_chunk: list[str],
    *,
    max_article_count: int,
    article_feed_after_epoch: float,
    article_feed_after_uri: str,
    now: datetime,
) -> tuple[list[_RequestParam], str, str]:
    params: list[_RequestParam] = [
        ("apiKey", api_key),
        ("recentActivityArticlesMaxArticleCount", str(max_article_count)),
        ("keywordOper", "or"),
        ("keywordLoc", "title"),
        ("lang", "eng"),
        ("isDuplicateFilter", "skipDuplicates"),
        ("dataType", "news"),
        ("includeArticleTitle", "true"),
    ]
    after_uri = str(article_feed_after_uri or "").strip()
    if after_uri:
        params.append(("recentActivityArticlesNewsUpdatesAfterUri", after_uri))
        cursor_mode = "uri"
        cursor_value = after_uri
    else:
        after_timestamp = _article_feed_after_timestamp(article_feed_after_epoch, now=now)
        params.append(("recentActivityArticlesUpdatesAfterTm", after_timestamp))
        cursor_mode = "timestamp"
        cursor_value = after_timestamp
    params.extend(("keyword", keyword) for keyword in keyword_chunk)
    return params, cursor_mode, cursor_value


def extract_newsapi_feed_article_cursor_uri(records: list[dict[str, Any]]) -> str | None:
    for record in records:
        if str(record.get("newsapi_fetch_mode") or "").strip() != "feed_articles":
            continue
        uri = str(record.get("uri") or "").strip()
        if uri:
            return uri
    return None


def fetch_newsapi_feed_article_probe(
    api_key: str,
    symbols: list[str],
    *,
    article_feed_after_epoch: float,
    article_feed_after_uri: str | None = None,
    max_articles: int = MAX_ARTICLES_PER_REQUEST,
    client: httpx.Client | None = None,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        return {"records": [], "diagnostics": []}

    now = current_time.astimezone(UTC) if current_time is not None else datetime.now(UTC)
    if not _can_use_article_feed(article_feed_after_epoch, now=now):
        return {"records": [], "diagnostics": []}

    patterns = _build_keyword_patterns(normalized_symbols)
    max_article_count = max(1, min(int(max_articles), MAX_FEED_ARTICLES_PER_REQUEST))

    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=HTTPX_REQUEST_TIMEOUT_SECONDS)

    seen_ids: set[str] = set()
    articles: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    after_uri = str(article_feed_after_uri or "").strip()

    try:
        for keyword_chunk, chunk_article_count in _balanced_keyword_chunks(
            normalized_symbols,
            target_size=min(TARGET_KEYWORDS_PER_REQUEST, MAX_KEYWORDS_PER_REQUEST),
            total_result_limit=max_article_count,
        ):
            params, cursor_mode, cursor_value = _build_feed_request_params(
                api_key,
                keyword_chunk,
                max_article_count=chunk_article_count,
                article_feed_after_epoch=article_feed_after_epoch,
                article_feed_after_uri=after_uri,
                now=now,
            )
            payload = _request_payload(client, EVENT_REGISTRY_ARTICLE_FEED_URL, params=params)
            results = _extract_results(payload, "articles")
            matched_results = 0
            accepted_results = 0

            for item in results:
                headline = str(item.get("title") or "").strip()
                matched_symbols = _match_symbols(headline, patterns, source_name=_article_source_name(item))
                if not headline or not matched_symbols:
                    continue
                matched_results += 1
                article_id = str(item.get("uri") or item.get("url") or headline)
                if article_id in seen_ids:
                    continue
                seen_ids.add(article_id)
                accepted_results += 1
                articles.append(
                    {
                        "id": article_id,
                        "uri": str(item.get("uri") or "").strip() or None,
                        "url": str(item.get("url") or item.get("link") or "").strip() or None,
                        "title": headline,
                        "headline": headline,
                        "body": _article_content(item),
                        "content": _article_content(item),
                        "published": _article_published_value(item),
                        "date": _article_published_value(item),
                        "source": _article_source_name(item),
                        "tickers": matched_symbols,
                        "newsapi_fetch_mode": "feed_articles",
                    }
                )

            diagnostics.append(
                {
                    "keyword_count": len(keyword_chunk),
                    "keywords": list(keyword_chunk),
                    "cursor_mode": cursor_mode,
                    "cursor_value": cursor_value,
                    "payload_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
                    "raw_result_count": len(results),
                    "matched_result_count": matched_results,
                    "accepted_record_count": accepted_results,
                    "sample_raw_titles": [str(item.get("title") or "") for item in results[:3]],
                    "sample_raw_uris": [str(item.get("uri") or item.get("url") or "") for item in results[:3]],
                    "sample_matched_titles": [
                        str(item.get("title") or "")
                        for item in results
                        if str(item.get("title") or "").strip()
                        and _match_symbols(str(item.get("title") or "").strip(), patterns, source_name=_article_source_name(item))
                    ][:3],
                    "sample_matched_uris": [
                        str(item.get("uri") or item.get("url") or "")
                        for item in results
                        if str(item.get("title") or "").strip()
                        and _match_symbols(str(item.get("title") or "").strip(), patterns, source_name=_article_source_name(item))
                    ][:3],
                }
            )
    finally:
        if own_client:
            client.close()

    return {"records": articles, "diagnostics": diagnostics}


def _event_title(item: dict[str, Any]) -> str:
    return _coerce_text(item.get("title") or item.get("eventTitle"))


def _event_summary(item: dict[str, Any]) -> str:
    return _coerce_text(item.get("summary") or item.get("body") or item.get("snippet") or item.get("description"))


def _event_published_value(item: dict[str, Any]) -> str:
    return _coerce_text(
        item.get("eventDate")
        or item.get("date")
        or item.get("dateTime")
        or item.get("reportingDate")
        or item.get("startDate")
    )


def _event_article_count(item: dict[str, Any]) -> int | None:
    for candidate in (
        item.get("totalArticleCount"),
        item.get("articleCount"),
        item.get("totalArticleCounts"),
    ):
        if candidate is None:
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def fetch_newsapi_article_records(
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
        client = httpx.Client(timeout=HTTPX_REQUEST_TIMEOUT_SECONDS)

    seen_ids: set[str] = set()
    articles: list[dict[str, Any]] = []

    try:
        for keyword_chunk, chunk_article_count in _balanced_keyword_chunks(
            normalized_symbols,
            target_size=min(TARGET_KEYWORDS_PER_REQUEST, MAX_KEYWORDS_PER_REQUEST),
            total_result_limit=max_articles,
        ):
            params: list[_RequestParam] = [
                ("apiKey", api_key),
                ("resultType", "articles"),
                ("articlesCount", str(chunk_article_count)),
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

            payload = _request_payload(client, EVENT_REGISTRY_ARTICLES_URL, params=params)
            results = _extract_results(payload, "articles")

            for item in results:
                headline = str(item.get("title") or "").strip()
                matched_symbols = _match_symbols(headline, patterns, source_name=_article_source_name(item))
                if not headline or not matched_symbols:
                    continue
                article_id = str(item.get("uri") or item.get("url") or headline)
                if article_id in seen_ids:
                    continue
                seen_ids.add(article_id)
                articles.append(
                    {
                        "id": article_id,
                        "uri": str(item.get("uri") or "").strip() or None,
                        "url": str(item.get("url") or item.get("link") or "").strip() or None,
                        "title": headline,
                        "headline": headline,
                        "body": _article_content(item),
                        "content": _article_content(item),
                        "published": _article_published_value(item),
                        "date": _article_published_value(item),
                        "source": _article_source_name(item),
                        "tickers": matched_symbols,
                        "newsapi_fetch_mode": "search_articles",
                    }
                )
    finally:
        if own_client:
            client.close()

    return articles


def fetch_newsapi_feed_article_records(
    api_key: str,
    symbols: list[str],
    *,
    article_feed_after_epoch: float,
    article_feed_after_uri: str | None = None,
    max_articles: int = MAX_ARTICLES_PER_REQUEST,
    client: httpx.Client | None = None,
    current_time: datetime | None = None,
) -> list[dict[str, Any]]:
    return list(
        fetch_newsapi_feed_article_probe(
            api_key,
            symbols,
            article_feed_after_epoch=article_feed_after_epoch,
            article_feed_after_uri=article_feed_after_uri,
            max_articles=max_articles,
            client=client,
            current_time=current_time,
        ).get("records")
        or []
    )


def fetch_newsapi_event_records(
    api_key: str,
    symbols: list[str],
    *,
    lookback_days: int = 2,
    events_per_request: int = MAX_EVENTS_PER_REQUEST,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        return []

    patterns = _build_keyword_patterns(normalized_symbols)
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=max(int(lookback_days), 1))
    max_events = max(1, min(int(events_per_request), MAX_EVENTS_PER_REQUEST))

    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=HTTPX_REQUEST_TIMEOUT_SECONDS)

    seen_ids: set[str] = set()
    events: list[dict[str, Any]] = []

    try:
        for keyword_chunk, chunk_event_count in _balanced_keyword_chunks(
            normalized_symbols,
            target_size=min(TARGET_KEYWORDS_PER_REQUEST, MAX_KEYWORDS_PER_REQUEST),
            total_result_limit=max_events,
        ):
            params: list[_RequestParam] = [
                ("apiKey", api_key),
                ("resultType", "events"),
                ("eventsCount", str(chunk_event_count)),
                ("eventsSortBy", "date"),
                ("keywordOper", "or"),
                ("keywordLoc", "title"),
                ("lang", "eng"),
                ("dateStart", start_date.isoformat()),
                ("dateEnd", end_date.isoformat()),
                ("includeEventTitle", "true"),
                ("includeEventSummary", "true"),
                ("includeEventDate", "true"),
                ("includeEventArticleCounts", "true"),
            ]
            params.extend(("keyword", keyword) for keyword in keyword_chunk)

            payload = _request_payload(client, EVENT_REGISTRY_EVENTS_URL, params=params)
            results = _extract_results(payload, "events")

            for item in results:
                headline = _event_title(item)
                summary = _event_summary(item)
                matched_symbols = _match_symbols(
                    " ".join(part for part in (headline, summary) if part),
                    patterns,
                    source_name="Event Registry",
                )
                if not headline or not matched_symbols:
                    continue
                published = _event_published_value(item)
                event_id = _coerce_text(item.get("uri") or item.get("eventUri") or item.get("id"))
                if not event_id:
                    event_id = f"event::{published}::{headline}"
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)
                events.append(
                    {
                        "id": event_id,
                        "uri": _coerce_text(item.get("uri") or item.get("eventUri")) or None,
                        "url": None,
                        "title": headline,
                        "headline": headline,
                        "body": summary,
                        "content": summary,
                        "summary": summary,
                        "published": published,
                        "date": published,
                        "source": "Event Registry",
                        "tickers": matched_symbols,
                        "kind": "event",
                        "event_article_count": _event_article_count(item),
                        "newsapi_fetch_mode": "search_events",
                    }
                )
    finally:
        if own_client:
            client.close()

    return events


def fetch_newsapi_records(
    api_key: str,
    symbols: list[str],
    *,
    lookback_days: int = 2,
    articles_per_request: int = MAX_ARTICLES_PER_REQUEST,
    events_per_request: int = MAX_EVENTS_PER_REQUEST,
    include_articles: bool = True,
    include_events: bool = True,
    prefer_article_feed: bool = False,
    article_feed_after_epoch: float | None = None,
    article_feed_after_uri: str | None = None,
    current_time: datetime | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=HTTPX_REQUEST_TIMEOUT_SECONDS)
    now = current_time.astimezone(UTC) if current_time is not None else datetime.now(UTC)

    try:
        records: list[dict[str, Any]] = []
        if include_articles:
            if prefer_article_feed and _can_use_article_feed(article_feed_after_epoch, now=now):
                feed_after_epoch = float(article_feed_after_epoch or 0.0)
                records.extend(
                    fetch_newsapi_feed_article_records(
                        api_key,
                        symbols,
                        article_feed_after_epoch=feed_after_epoch,
                        article_feed_after_uri=article_feed_after_uri,
                        max_articles=articles_per_request,
                        client=client,
                        current_time=now,
                    )
                )
            else:
                records.extend(
                    fetch_newsapi_article_records(
                        api_key,
                        symbols,
                        lookback_days=lookback_days,
                        articles_per_request=articles_per_request,
                        client=client,
                    )
                )
        if include_events:
            records.extend(
                fetch_newsapi_event_records(
                    api_key,
                    symbols,
                    lookback_days=lookback_days,
                    events_per_request=events_per_request,
                    client=client,
                )
            )
    finally:
        if own_client:
            client.close()

    seen_ids: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        record_id = str(record.get("id") or record.get("uri") or record.get("title") or "").strip()
        if not record_id or record_id in seen_ids:
            continue
        seen_ids.add(record_id)
        deduped.append(record)
    return deduped


def fetch_newsapi_articles(
    api_key: str,
    symbols: list[str],
    *,
    lookback_days: int = 2,
    articles_per_request: int = MAX_ARTICLES_PER_REQUEST,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    records = fetch_newsapi_article_records(
        api_key,
        symbols,
        lookback_days=lookback_days,
        articles_per_request=articles_per_request,
        client=client,
    )
    return [{"headline": record["headline"], "tickers": list(record["tickers"])} for record in records]
