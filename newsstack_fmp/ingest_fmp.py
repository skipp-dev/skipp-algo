"""Synchronous FMP news ingestion adapter.

Polls three endpoints:
 1. /stable/news/stock-latest            (latest stock news)
 2. /stable/news/press-releases-latest   (press releases)
 3. /stable/fmp-articles                 (broad article feed)

Uses httpx synchronously so the adapter can be called from Streamlit
refresh cycles without needing asyncio.

Returns ``List[NewsItem]`` via the shared normalisation layer.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .common_types import NewsItem
from .normalize import normalize_fmp

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/stable"

# Regex to strip API keys from URLs before logging.
_APIKEY_RE = re.compile(r"(apikey|api_key|token|key)=[^&]+", re.IGNORECASE)


def _sanitize_url(url: str) -> str:
    """Remove apikey/token query params from a URL for safe logging."""
    return _APIKEY_RE.sub(r"\1=***", url)


def _parse_retry_after_seconds(raw_value: Any) -> float | None:
    """Parse an HTTP ``Retry-After`` header into seconds (RFC 9110 §10.2.3).

    Accepts both the integer-seconds form (``"30"``) and the HTTP-date
    form (``"Wed, 21 Oct 2026 07:28:00 GMT"``). Returns ``None`` when
    the value is empty or unparseable so the caller can fall back to
    its own backoff schedule.
    """
    if raw_value is None or raw_value == "":
        return None
    try:
        v = float(raw_value)
    except (TypeError, ValueError):
        v = None
    if v is not None:
        # Reject NaN/Inf — ``time.sleep(NaN)`` raises ValueError and
        # ``time.sleep(inf)`` would wedge the retry loop.
        if math.isnan(v) or math.isinf(v):
            return None
        return max(v, 0.0)
    try:
        parsed = parsedate_to_datetime(str(raw_value))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(
        (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds(),
        0.0,
    )


def _as_list(x: Any) -> list:
    """Safely coerce *x* to a list of dicts."""
    if not isinstance(x, list):
        if x is not None:
            logger.warning(
                "FMP returned %s instead of list — 0 items ingested.",
                type(x).__name__,
            )
        return []
    return [item for item in x if isinstance(item, dict)]


def _safe_json(r: httpx.Response) -> Any:
    """Parse JSON response; raise ValueError with sanitized URL on failure."""
    ct = r.headers.get("content-type", "")
    try:
        return r.json()
    except (json.JSONDecodeError, ValueError):
        raise ValueError(
            f"FMP returned non-JSON (content-type={ct!r}, "
            f"status={r.status_code}, url={_sanitize_url(str(r.url))})"
        ) from None


class FmpAdapter:
    """Synchronous adapter for FMP news endpoints."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("FMP_API_KEY missing")
        self.api_key = api_key
        self.client = httpx.Client(timeout=10.0)

    # ── Endpoint helpers ────────────────────────────────────────

    _RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})
    _MAX_RETRIES = 3

    def _safe_get(self, url: str, params: dict) -> httpx.Response:
        """GET with retry+backoff for transient failures, sanitized errors.

        When the response carries a ``Retry-After`` header (typically on
        HTTP 429), honor at least the suggested wait before the next
        attempt. The hint is capped at 60s so a misconfigured
        ``Retry-After: 86400`` cannot wedge the poller for a full day.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                r = self.client.get(url, params=params)
                if r.status_code in self._RETRYABLE_CODES and attempt < self._MAX_RETRIES:
                    backoff = 2 ** attempt  # 2s, 4s
                    hint = _parse_retry_after_seconds(r.headers.get("Retry-After"))
                    wait = max(backoff, min(hint, 60.0)) if hint is not None else backoff
                    logger.warning(
                        "FMP %d from %s — retry %d/%d in %.1fs",
                        r.status_code, _sanitize_url(str(r.url)),
                        attempt, self._MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r
            except httpx.HTTPStatusError as exc:
                raise httpx.HTTPStatusError(
                    message=f"HTTP {r.status_code} from {_sanitize_url(str(r.url))}",
                    request=exc.request,
                    response=exc.response,
                ) from None
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    wait = 2 ** attempt
                    logger.warning(
                        "FMP network error (%s) — retry %d/%d in %ds",
                        type(exc).__name__, attempt, self._MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue
        # All retries exhausted
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"FMP: all {self._MAX_RETRIES} retries exhausted for {_sanitize_url(url)}")

    def fetch_stock_latest(self, page: int, limit: int) -> list[NewsItem]:
        """GET /stable/news/stock-latest?page=…&limit=…"""
        url = f"{FMP_BASE}/news/stock-latest"
        r = self._safe_get(url, {"page": page, "limit": limit, "apikey": self.api_key})
        return [normalize_fmp("fmp_stock_latest", it) for it in _as_list(_safe_json(r))]

    def fetch_press_latest(self, page: int, limit: int) -> list[NewsItem]:
        """GET /stable/news/press-releases-latest?page=…&limit=…"""
        url = f"{FMP_BASE}/news/press-releases-latest"
        r = self._safe_get(url, {"page": page, "limit": limit, "apikey": self.api_key})
        return [normalize_fmp("fmp_press_latest", it) for it in _as_list(_safe_json(r))]

    def fetch_articles(self, limit: int) -> list[NewsItem]:
        """GET /stable/fmp-articles?page=0&limit=…"""
        url = f"{FMP_BASE}/fmp-articles"
        r = self._safe_get(url, {"page": 0, "limit": limit, "apikey": self.api_key})
        return [normalize_fmp("fmp_articles", it) for it in _as_list(_safe_json(r))]

    def fetch_general_latest(self, page: int, limit: int) -> list[NewsItem]:
        """GET /stable/news/general-latest?page=…&limit=… (B4, PR3 2026-05-09).

        Macro / market-wide news that complements the per-symbol
        ``fetch_stock_latest`` and corporate ``fetch_press_latest`` feeds.
        """
        url = f"{FMP_BASE}/news/general-latest"
        r = self._safe_get(url, {"page": page, "limit": limit, "apikey": self.api_key})
        return [normalize_fmp("fmp_general_latest", it) for it in _as_list(_safe_json(r))]

    def close(self) -> None:
        self.client.close()
