"""Synchronous FMP news ingestion adapter.

Polls two endpoints:
 1. /stable/news/stock-latest            (latest stock news)
 2. /stable/news/press-releases-latest   (press releases)

Uses httpx synchronously so the adapter can be called from Streamlit
refresh cycles without needing asyncio.

Returns ``List[NewsItem]`` via the shared normalisation layer.
"""

from __future__ import annotations

import logging
from typing import Any, List

import httpx

from .common_types import NewsItem
from .normalize import normalize_fmp

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/stable"


def _as_list(x: Any) -> list:
    """Safely coerce *x* to a list."""
    return x if isinstance(x, list) else []


class FmpAdapter:
    """Synchronous adapter for FMP stock-news & press-release endpoints."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("FMP_API_KEY missing")
        self.api_key = api_key
        self.client = httpx.Client(timeout=10.0)

    # ── Endpoint helpers ────────────────────────────────────────

    def fetch_stock_latest(self, page: int, limit: int) -> List[NewsItem]:
        """GET /stable/news/stock-latest?page=…&limit=…"""
        url = f"{FMP_BASE}/news/stock-latest"
        r = self.client.get(
            url,
            params={"page": page, "limit": limit, "apikey": self.api_key},
        )
        r.raise_for_status()
        return [normalize_fmp("fmp_stock_latest", it) for it in _as_list(r.json())]

    def fetch_press_latest(self, page: int, limit: int) -> List[NewsItem]:
        """GET /stable/news/press-releases-latest?page=…&limit=…"""
        url = f"{FMP_BASE}/news/press-releases-latest"
        r = self.client.get(
            url,
            params={"page": page, "limit": limit, "apikey": self.api_key},
        )
        r.raise_for_status()
        return [normalize_fmp("fmp_press_latest", it) for it in _as_list(r.json())]

    def close(self) -> None:
        self.client.close()
