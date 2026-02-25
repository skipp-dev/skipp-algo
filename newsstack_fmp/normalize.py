"""Normalisation functions: raw provider payloads → NewsItem.

Each provider has its own normaliser.  The functions are intentionally
**schema-tolerant**: they try multiple field names so that minor API
changes don't silently drop data.  Nevertheless the *primary* field
names match the real API responses as of Feb 2026.

FMP (both endpoints):
    symbol, publishedDate, publisher, title, image, site, text, url
    No ``id`` field → ``url`` is used as stable item_id.

Benzinga REST (/api/v2/news):
    id, title, teaser, url, stocks, source, author, created, updated

Benzinga WS (news stream):
    Same field names as REST; payload may be wrapped in ``{"data": …}``.
"""

from __future__ import annotations

import logging
import time
from datetime import timezone
from typing import Any, Dict, List

from dateutil import parser as dtparser

from .common_types import NewsItem

logger = logging.getLogger(__name__)


# ── Shared helpers ──────────────────────────────────────────────

# Minimum length for a date string to be considered valid.
# Shortest valid format: "YYYYMMDD" = 8 chars.  Shorter strings like
# "5" or "12" are ambiguously parsed by dateutil (e.g. "5" → Feb 5)
# and can silently drift cursors.
_MIN_DATE_LEN = 8


def _to_epoch(s: str) -> float:
    """Parse a date/time string to epoch seconds.

    Returns ``0.0`` for empty, too-short, or unparseable strings so that
    the caller can detect 'no timestamp available' and avoid advancing
    cursors past real item timestamps.

    Naive datetimes (no timezone info) are assumed UTC to guarantee
    deterministic results regardless of server timezone.
    """
    if not s:
        return 0.0
    s_stripped = s.strip()
    if len(s_stripped) < _MIN_DATE_LEN:
        logger.warning("Date string too short (%d chars): %r — returning epoch 0.", len(s_stripped), s_stripped)
        return 0.0
    try:
        dt = dtparser.parse(s_stripped)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        logger.warning("Unparseable date %r — returning epoch 0.", s_stripped[:80])
        return 0.0


def _extract_tickers(it: Dict[str, Any]) -> List[str]:
    """Generously extract ticker list from various field shapes."""
    # FMP: single "symbol" string
    sym = it.get("symbol")
    if isinstance(sym, str) and sym.strip():
        return [sym.strip().upper()]

    # Benzinga REST: "stocks" may be list[dict] with "name" key, or list[str], or csv
    stocks = it.get("stocks") or it.get("tickers") or it.get("symbols") or []
    if isinstance(stocks, str):
        return [s.strip().upper() for s in stocks.split(",") if s.strip()]
    if isinstance(stocks, list):
        out: List[str] = []
        for s in stocks:
            if isinstance(s, dict):
                name = s.get("name") or s.get("ticker") or s.get("symbol") or ""
                if name:
                    out.append(str(name).strip().upper())
            elif isinstance(s, str) and s.strip():
                out.append(s.strip().upper())
        return out
    return []


# ── FMP ─────────────────────────────────────────────────────────

def normalize_fmp(provider: str, it: Dict[str, Any]) -> NewsItem:
    """Normalise one raw FMP item (stock-latest *or* press-releases-latest)."""
    # Stable item_id: FMP has no ``id`` — use ``url``
    item_id = str(it.get("url") or it.get("id") or it.get("uuid") or it.get("news_id") or "").strip()
    headline = str(it.get("title") or it.get("headline") or "").strip()
    snippet = str(it.get("text") or it.get("snippet") or it.get("content") or "").strip()
    url = it.get("url") or it.get("link") or it.get("newsURL") or None
    source = str(it.get("site") or it.get("source") or it.get("publisher") or "").strip()
    tickers = _extract_tickers(it)

    published = str(it.get("publishedDate") or it.get("published") or it.get("date") or "").strip()
    ts = _to_epoch(published)

    return NewsItem(
        provider=provider,
        item_id=item_id,
        published_ts=ts,
        updated_ts=ts,
        headline=headline,
        snippet=snippet[:500],
        tickers=tickers,
        url=str(url) if url else None,
        source=source,
        raw=it,
    )


# ── Benzinga REST ───────────────────────────────────────────────

def normalize_benzinga_rest(it: Dict[str, Any]) -> NewsItem:
    """Normalise one Benzinga REST /api/v2/news item."""
    item_id = str(it.get("id") or it.get("uuid") or "").strip()
    headline = str(it.get("title") or it.get("headline") or "").strip()
    snippet = str(it.get("teaser") or it.get("summary") or it.get("body") or "").strip()
    url = it.get("url") or it.get("link") or None
    source = str(it.get("source") or it.get("author") or "").strip()
    tickers = _extract_tickers(it)

    published = str(it.get("created") or it.get("published") or "").strip()
    updated = str(it.get("updated") or published).strip()
    pts = _to_epoch(published)
    uts = _to_epoch(updated)

    return NewsItem(
        provider="benzinga_rest",
        item_id=item_id,
        published_ts=pts,
        updated_ts=uts,
        headline=headline,
        snippet=snippet[:500],
        tickers=tickers,
        url=str(url) if url else None,
        source=source,
        raw=it,
    )


# ── Benzinga WebSocket ──────────────────────────────────────────

def normalize_benzinga_ws(msg: Dict[str, Any]) -> NewsItem:
    """Normalise one Benzinga WebSocket message.

    WS payload field names follow the REST schema; the message may
    arrive bare or wrapped in ``{"data": …}``.
    """
    item_id = str(msg.get("id") or msg.get("uuid") or msg.get("news_id") or "").strip()
    headline = str(msg.get("title") or msg.get("headline") or "").strip()
    snippet = str(msg.get("teaser") or msg.get("summary") or "").strip()
    url = msg.get("url") or msg.get("link") or None
    source = str(msg.get("source") or msg.get("publisher") or "").strip()
    tickers = _extract_tickers(msg)

    published = str(msg.get("created") or msg.get("published") or "").strip()
    updated = str(msg.get("updated") or published).strip()
    pts = _to_epoch(published)
    uts = _to_epoch(updated)

    return NewsItem(
        provider="benzinga_ws",
        item_id=item_id,
        published_ts=pts,
        updated_ts=uts,
        headline=headline,
        snippet=snippet[:500],
        tickers=tickers,
        url=str(url) if url else None,
        source=source,
        raw=msg,
    )
