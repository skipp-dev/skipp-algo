"""Synchronous FMP news ingestion adapter.

Polls two endpoints:
 1. /stable/news/stock-latest            (latest stock news)
 2. /stable/news/press-releases-latest   (press releases)

Uses httpx synchronously so the adapter can be called from Streamlit
refresh cycles without needing asyncio.

Returns ``List[NewsItem]`` via the shared normalisation layer.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, List

import httpx

from .common_types import NewsItem
from .normalize import normalize_fmp

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/stable"

# Regex to strip API keys from URLs before logging.
_APIKEY_RE = re.compile(r"(apikey|token)=[^&]+", re.IGNORECASE)


def _sanitize_url(url: str) -> str:
    """Remove apikey/token query params from a URL for safe logging."""
    return _APIKEY_RE.sub(r"\1=***", url)


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
        )


class FmpAdapter:
    """Synchronous adapter for FMP stock-news & press-release endpoints."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("FMP_API_KEY missing")
        self.api_key = api_key
        self.client = httpx.Client(timeout=10.0)

    # ── Endpoint helpers ────────────────────────────────────────

    def _safe_get(self, url: str, params: dict) -> httpx.Response:
        """GET with sanitized error messages (no API key in logs)."""
        r = self.client.get(url, params=params)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise httpx.HTTPStatusError(
                message=f"HTTP {r.status_code} from {_sanitize_url(str(r.url))}",
                request=exc.request,
                response=exc.response,
            ) from None
        return r

    def fetch_stock_latest(self, page: int, limit: int) -> List[NewsItem]:
        """GET /stable/news/stock-latest?page=…&limit=…"""
        url = f"{FMP_BASE}/news/stock-latest"
        r = self._safe_get(url, {"page": page, "limit": limit, "apikey": self.api_key})
        return [normalize_fmp("fmp_stock_latest", it) for it in _as_list(_safe_json(r))]

    def fetch_press_latest(self, page: int, limit: int) -> List[NewsItem]:
        """GET /stable/news/press-releases-latest?page=…&limit=…"""
        url = f"{FMP_BASE}/news/press-releases-latest"
        r = self._safe_get(url, {"page": page, "limit": limit, "apikey": self.api_key})
        return [normalize_fmp("fmp_press_latest", it) for it in _as_list(_safe_json(r))]

    def close(self) -> None:
        self.client.close()
