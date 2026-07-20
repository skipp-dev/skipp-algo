"""Private producer-feed client for the News Terminal.

The terminal consumes the already fetched and scored news snapshot from the
signals producer instead of owning a second set of provider credentials.  The
client deliberately accepts only loopback or Railway private-network hosts so
the bearer token cannot be redirected to an arbitrary destination.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from newsstack_fmp.scoring import cluster_hash
from open_prep.news import classify_article_sentiment
from open_prep.playbook import classify_news_event, classify_recency, classify_source_quality
from terminal_poller import ClassifiedItem

_SCHEMA_VERSION = 1
_DEFAULT_MAX_RESPONSE_BYTES = 2_000_000
_MAX_ITEMS = 1_000
_ENDPOINT_PATHS = {"/news-feed", "/news-feed.json"}


class ProducerFeedError(RuntimeError):
    """A safe, operator-facing producer-feed failure."""


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def private_producer_url(raw_url: str, *, endpoint_path: str) -> str:
    """Return a private Producer URL with a fixed endpoint path."""
    value = str(raw_url or "").strip()
    if not value:
        raise ValueError("producer URL is empty")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("producer URL must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("producer URL must not contain credentials, query, or fragment")

    host = (parsed.hostname or "").rstrip(".").lower()
    private_host = host in {"localhost", "127.0.0.1", "::1"} or host.endswith(
        ".railway.internal"
    )
    if not private_host:
        raise ValueError("producer URL must target loopback or Railway private networking")

    endpoint = str(endpoint_path or "").strip()
    if not endpoint.startswith("/") or endpoint == "/":
        raise ValueError("producer endpoint path is invalid")

    return urlunsplit((parsed.scheme, parsed.netloc, endpoint, "", ""))


def _private_feed_url(raw_url: str) -> str:
    parsed = urlsplit(str(raw_url or "").strip())

    path = parsed.path.rstrip("/")
    if not path:
        path = "/news-feed.json"
    elif path not in _ENDPOINT_PATHS:
        raise ValueError("producer feed URL path must be /news-feed or /news-feed.json")
    return private_producer_url(raw_url, endpoint_path=path)


def _candidate_id(candidate: dict[str, Any], ticker: str, headline: str) -> str:
    identity = {
        "provider": str(candidate.get("news_provider") or ""),
        "ticker": ticker,
        "headline": headline,
        "url": str(candidate.get("news_url") or ""),
        "published_ts": _finite_float(candidate.get("published_ts")),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"producer-{digest[:32]}"


def candidate_to_classified_item(
    candidate: dict[str, Any],
    *,
    generated_ts: float,
) -> ClassifiedItem:
    """Convert one producer candidate without repeating provider ingestion."""
    ticker = str(candidate.get("ticker") or "").strip().upper()
    headline = str(candidate.get("headline") or "").strip()[:260]
    if not ticker or not headline:
        raise ProducerFeedError("producer feed contains an item without ticker or headline")

    snippet = str(candidate.get("snippet") or "").strip()[:260]
    provider = str(candidate.get("news_provider") or "producer").strip()[:80]
    source = str(candidate.get("news_source") or provider).strip()[:160]
    published_ts = _finite_float(candidate.get("published_ts"), generated_ts)
    updated_ts = _finite_float(candidate.get("updated_ts"), published_ts)
    effective_ts = updated_ts or published_ts or generated_ts
    article_dt = datetime.fromtimestamp(effective_ts, tz=UTC) if effective_ts > 0 else None

    sentiment_label, sentiment_score = classify_article_sentiment(headline, snippet)
    event = classify_news_event(headline, snippet)
    event_label = str(event.get("event_label") or "").strip()
    if not event_label:
        event_label = str(candidate.get("category") or "")
    recency = classify_recency(article_dt)
    source_quality = classify_source_quality(source, headline)
    score = min(1.0, max(0.0, _finite_float(candidate.get("news_score"))))
    novelty_count = max(1, int(_finite_float(candidate.get("novelty_cluster_count"), 1.0)))
    raw_tags = candidate.get("warn_flags")
    tags = (
        [str(value)[:80] for value in raw_tags if str(value).strip()]
        if isinstance(raw_tags, list)
        else []
    )

    return ClassifiedItem(
        item_id=_candidate_id(candidate, ticker, headline),
        ticker=ticker,
        tickers_all=[ticker],
        headline=headline,
        snippet=snippet,
        url=str(candidate.get("news_url") or "").strip() or None,
        source=source,
        published_ts=published_ts,
        updated_ts=updated_ts,
        provider=provider,
        category=str(candidate.get("category") or "other")[:80],
        impact=min(1.0, max(0.0, _finite_float(candidate.get("impact")))),
        clarity=min(1.0, max(0.0, _finite_float(candidate.get("clarity")))),
        polarity=max(-1.0, min(1.0, _finite_float(candidate.get("polarity")))),
        news_score=score,
        cluster_hash=cluster_hash(headline, [ticker]),
        novelty_count=novelty_count,
        relevance=min(1.0, max(0.0, _finite_float(candidate.get("relevance"), score))),
        entity_count=1,
        sentiment_label=sentiment_label,
        sentiment_score=sentiment_score,
        event_class=str(event.get("event_class") or "UNKNOWN"),
        event_label=event_label,
        materiality=str(event.get("materiality") or "LOW"),
        recency_bucket=str(recency.get("recency_bucket") or "UNKNOWN"),
        age_minutes=recency.get("age_minutes"),
        is_actionable=bool(recency.get("is_actionable")),
        source_tier=str(source_quality.get("source_tier") or "TIER_3"),
        source_rank=int(source_quality.get("source_rank") or 3),
        channels=[],
        tags=tags,
        is_wiim=False,
    )


class ProducerFeedClient:
    """Fetch and validate a bounded snapshot from the private producer."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout_s: float = 5.0,
        max_age_s: float = 300.0,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = _private_feed_url(url)
        self._token = str(token or "").strip()
        if not self._token:
            raise ValueError("producer feed token is empty")
        if timeout_s <= 0 or max_age_s <= 0 or max_response_bytes <= 0:
            raise ValueError("producer feed limits must be greater than zero")
        self._max_age_s = float(max_age_s)
        self._max_response_bytes = int(max_response_bytes)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(float(timeout_s)),
            follow_redirects=False,
        )
        self._fingerprints: dict[str, str] = {}
        self._state_lock = threading.Lock()

    def reset(self) -> None:
        """Forget the current snapshot so the next fetch replays it."""
        with self._state_lock:
            self._fingerprints = {}

    def fetch(self) -> tuple[list[ClassifiedItem], str]:
        """Return new or changed items plus the producer generation cursor."""
        try:
            with self._client.stream(
                "GET",
                self._url,
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise ProducerFeedError(
                        f"producer feed request failed with HTTP {response.status_code}"
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_response_bytes:
                        raise ProducerFeedError("producer feed response exceeds the size limit")
        except ProducerFeedError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise ProducerFeedError(f"producer feed transport failed ({type(exc).__name__})") from exc

        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProducerFeedError("producer feed returned invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
            raise ProducerFeedError("producer feed schema version is unsupported")
        if payload.get("status") != "ready":
            raise ProducerFeedError("producer feed is not ready")

        generated_ts = _finite_float(payload.get("generated_ts"))
        now = time.time()
        if generated_ts <= 0 or generated_ts > now + 60.0:
            raise ProducerFeedError("producer feed generated timestamp is invalid")
        if now - generated_ts > self._max_age_s:
            raise ProducerFeedError("producer feed snapshot is stale")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) > _MAX_ITEMS:
            raise ProducerFeedError("producer feed item list is invalid or too large")
        if payload.get("item_count") != len(raw_items):
            raise ProducerFeedError("producer feed item count is inconsistent")

        candidates: list[tuple[ClassifiedItem, str]] = []
        current_fingerprints: dict[str, str] = {}
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ProducerFeedError("producer feed contains a non-object item")
            item = candidate_to_classified_item(raw_item, generated_ts=generated_ts)
            fingerprint = hashlib.sha256(
                json.dumps(raw_item, sort_keys=True, separators=(",", ":"), default=str).encode(
                    "utf-8"
                )
            ).hexdigest()
            current_fingerprints[item.item_id] = fingerprint
            candidates.append((item, fingerprint))
        with self._state_lock:
            items = [
                item
                for item, fingerprint in candidates
                if self._fingerprints.get(item.item_id) != fingerprint
            ]
            self._fingerprints = current_fingerprints
        return items, str(generated_ts)
