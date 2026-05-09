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

import hashlib
import logging
from datetime import UTC
from typing import Any

from dateutil import parser as dtparser  # type: ignore[import-untyped]

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
            dt = dt.replace(tzinfo=UTC)
        return float(dt.timestamp())
    except Exception:
        logger.warning("Unparseable date %r — returning epoch 0.", s_stripped[:80])
        return 0.0


def _normalize_ticker_token(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text.lstrip("$")


def _normalize_source_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("title") or value.get("name") or value.get("uri") or value.get("domain") or "").strip()
    return str(value or "").strip()


def _extract_tickers(it: dict[str, Any]) -> list[str]:
    """Generously extract ticker list from various field shapes."""
    # FMP: single "symbol" string
    sym = it.get("symbol")
    if isinstance(sym, str) and sym.strip():
        normalized = _normalize_ticker_token(sym)
        return [normalized] if normalized else []

    # Benzinga REST: "stocks" may be list[dict] with "name" key, or list[str], or csv
    stocks = it.get("stocks") or it.get("tickers") or it.get("symbols") or []
    if isinstance(stocks, str):
        return [normalized for s in stocks.split(",") if (normalized := _normalize_ticker_token(s))]
    if isinstance(stocks, list):
        out: list[str] = []
        for s in stocks:
            if isinstance(s, dict):
                name = s.get("name") or s.get("ticker") or s.get("symbol") or ""
                if name:
                    normalized = _normalize_ticker_token(name)
                    if normalized:
                        out.append(normalized)
            elif isinstance(s, str) and s.strip():
                normalized = _normalize_ticker_token(s)
                if normalized:
                    out.append(normalized)
        return out
    return []


# ── FMP ─────────────────────────────────────────────────────────

def normalize_fmp(provider: str, it: dict[str, Any]) -> NewsItem:
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

    # Guard: FMP has no stable ``id``; if URL is also missing, generate a
    # deterministic fallback so dedup doesn't collapse unrelated items.
    if not item_id:
        _digest = hashlib.md5(headline.encode("utf-8", errors="replace"), usedforsecurity=False).hexdigest()[:8]
        item_id = f"fmp_{int(ts)}_{_digest}"

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

def normalize_benzinga_quantified(it: dict[str, Any]) -> NewsItem:
    """Normalise one Benzinga quantified news item (WP-NW6).

    Quantified items carry price-impact context (open_gap, range, volume)
    which is preserved in the ``raw`` dict for downstream scoring.
    """
    item_id = str(it.get("id") or it.get("uuid") or "").strip()
    headline = str(it.get("title") or it.get("headline") or "").strip()
    snippet = str(it.get("teaser") or it.get("summary") or it.get("body") or "").strip()
    url = it.get("url") or it.get("link") or None
    source = str(it.get("source") or it.get("author") or "benzinga_quantified").strip()
    tickers = _extract_tickers(it)

    published = str(it.get("created") or it.get("published") or "").strip()
    updated = str(it.get("updated") or published).strip()
    pts = _to_epoch(published)
    uts = _to_epoch(updated)

    return NewsItem(
        provider="benzinga_quantified",
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


def normalize_benzinga_rest(it: dict[str, Any]) -> NewsItem:
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

def normalize_benzinga_ws(msg: dict[str, Any]) -> NewsItem:
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


# ── NewsAPI.ai / Event Registry ────────────────────────────────

def normalize_newsapi_ai(it: dict[str, Any]) -> NewsItem:
    """Normalise one NewsAPI.ai / Event Registry article or event."""
    headline = str(it.get("title") or it.get("headline") or "").strip()
    snippet = str(it.get("body") or it.get("content") or it.get("summary") or "").strip()
    item_id = str(it.get("id") or it.get("uri") or it.get("url") or "").strip()
    published = str(it.get("published") or it.get("dateTime") or it.get("dateTimePub") or it.get("date") or "").strip()
    ts = _to_epoch(published)
    if not item_id:
        digest = hashlib.md5(headline.encode("utf-8", errors="replace"), usedforsecurity=False).hexdigest()[:8]
        item_id = f"newsapi_ai_{int(ts)}_{digest}"
    return NewsItem(
        provider="newsapi_ai",
        item_id=item_id,
        published_ts=ts,
        updated_ts=ts,
        headline=headline,
        snippet=snippet[:500],
        tickers=_extract_tickers(it),
        url=(str(it.get("url") or it.get("link") or "").strip() or None),
        source=_normalize_source_name(it.get("source")),
        raw=it,
    )


# ── Benzinga calendar canonical schema ─────────────────────────────
# Canonical Benzinga-calendar field aliases. Upstream Benzinga occasionally
# renames or A/B-tests these; we accept the variants so consumers see one shape.
_BZ_CAL_ALIASES: dict[str, tuple[str, ...]] = {
    "event_id": ("id", "event_id", "uuid"),
    "event_date": ("date", "event_date", "datetime", "time"),
    "symbol": ("ticker", "symbol"),
    "event_actual": ("actual", "actualValue", "actual_value"),
    "event_forecast": ("forecast", "consensus", "estimate", "forecastValue", "forecast_value"),
    "event_previous": ("previous", "prior", "previousValue", "previous_value"),
    "importance": ("importance", "impact", "severity"),
}


def _first_present(raw: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    for k in keys:
        if k in raw and raw[k] not in (None, ""):
            return raw[k]
    return None


def normalize_benzinga_calendar_item(raw: dict[str, Any], endpoint_kind: str) -> dict[str, Any]:
    """Return a back-compat dict with canonical keys + original keys preserved.

    The canonical keys (event_id, event_date, symbol, event_actual,
    event_forecast, event_previous, importance) are always populated when
    SOME variant of the source field is present. The original raw keys are
    left in place so legacy consumers reading e.g. ``item["actual"]``
    continue to work. ``kind`` records the source endpoint
    (ratings, earnings, ...).
    """
    if not isinstance(raw, dict):
        return {"kind": endpoint_kind, "raw": raw}
    out = dict(raw)  # back-compat: keep originals
    for canonical, aliases in _BZ_CAL_ALIASES.items():
        out[canonical] = _first_present(raw, aliases)
    out.setdefault("kind", endpoint_kind)
    return out


# ── Unusual Whales /news/headlines (B1, PR2 2026-05-09) ─────────────


def normalize_uw_news_headline(rec: dict[str, Any]) -> NewsItem:
    """Normalise one UW ``/news/headlines`` record.

    UW field shape (per public docs): ``id``, ``headline``, ``source``,
    ``url``, ``tags``, ``sentiment``, ``is_major``, ``created_at``,
    ``tickers``.  Falls back gracefully if any field is missing.
    ``raw`` preserves UW-specific fields (``is_major``, ``tags``,
    ``sentiment``) for downstream scoring/observability.
    """
    if not isinstance(rec, dict):
        return NewsItem(
            provider="uw_news", item_id="", published_ts=0.0, updated_ts=0.0,
            headline="", snippet="", tickers=[], url=None, source="Unusual Whales",
        )

    item_id = str(rec.get("id") or rec.get("uuid") or "").strip()
    headline = str(rec.get("headline") or rec.get("title") or "").strip()

    # If no stable id provided, derive a hash-based id from headline+url
    # so dedup still functions per-provider via mark_seen.
    if not item_id and headline:
        seed = f"{headline}|{rec.get('url') or ''}"
        item_id = hashlib.sha1(
            seed.encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:16]

    snippet = str(rec.get("description") or rec.get("teaser") or "").strip()
    url = rec.get("url") or rec.get("link") or None
    source = _normalize_source_name(
        rec.get("source") or rec.get("publisher") or "Unusual Whales"
    )

    tickers_raw = rec.get("tickers") or rec.get("symbols") or []
    if isinstance(tickers_raw, str):
        tickers = [t for t in (
            _normalize_ticker_token(s) for s in tickers_raw.split(",")
        ) if t]
    elif isinstance(tickers_raw, list):
        tickers = [t for t in (
            _normalize_ticker_token(x) for x in tickers_raw
        ) if t]
    else:
        tickers = _extract_tickers(rec)

    published = str(
        rec.get("created_at") or rec.get("published_at") or rec.get("date") or ""
    ).strip()
    pts = _to_epoch(published)

    return NewsItem(
        provider="uw_news",
        item_id=item_id,
        published_ts=pts,
        updated_ts=pts,
        headline=headline,
        snippet=snippet[:500],
        tickers=tickers,
        url=str(url) if url else None,
        source=source,
        raw=rec,
    )


# ── FMP political trades (Senate + House, PR3 2026-05-09) ────


def normalize_fmp_political_trade(rec: dict[str, Any], *, chamber: str) -> NewsItem:
    """Normalise one Senate or House congressional trade disclosure.

    chamber: "senate" or "house" — drives provider label and source.
    """
    provider = "fmp_senate_trade" if chamber == "senate" else "fmp_house_trade"
    source = "FMP Senate" if chamber == "senate" else "FMP House"

    first_name = str(rec.get("firstName") or "").strip()
    last_name = str(rec.get("lastName") or "").strip()
    person = f"{last_name} {first_name[:1]}." if first_name else last_name
    tx_type = str(rec.get("type") or "").strip()
    ticker_raw = rec.get("ticker") or rec.get("symbol") or ""
    ticker = _normalize_ticker_token(ticker_raw)
    amount = str(rec.get("amount") or "").strip()
    asset_desc = str(rec.get("assetDescription") or "").strip()

    headline_parts = [
        ("Senate" if chamber == "senate" else "House") + " trade:",
        person,
    ]
    if tx_type:
        headline_parts.append(tx_type)
    if ticker:
        headline_parts.append(ticker)
    elif asset_desc:
        headline_parts.append(asset_desc)
    if amount:
        headline_parts.append(amount)
    headline = " ".join(p for p in headline_parts if p).strip()

    url = rec.get("link") or None
    # FMP API has a typo: "dateRecieved" (sic) — keep both for forward compat.
    tx_date = str(
        rec.get("transactionDate")
        or rec.get("dateRecieved")
        or rec.get("dateReceived")
        or ""
    ).strip()
    ts = _to_epoch(tx_date)

    item_id_seed = f"{url or ''}|{tx_date}|{ticker}|{tx_type}|{person}"
    item_id = hashlib.sha1(
        item_id_seed.encode("utf-8", errors="replace"), usedforsecurity=False
    ).hexdigest()[:16]

    tickers = [ticker] if ticker else []

    return NewsItem(
        provider=provider,
        item_id=item_id,
        published_ts=ts,
        updated_ts=ts,
        headline=headline,
        snippet=asset_desc[:500],
        tickers=tickers,
        url=str(url) if url else None,
        source=source,
        raw=rec,
    )


# ── FMP SEC 8-K filings (B7, PR3 2026-05-09) ─────────────────


def normalize_fmp_filing_8k(rec: dict[str, Any]) -> NewsItem:
    """Normalise one FMP /sec-filings/8-K-latest record."""
    symbol_raw = rec.get("symbol") or rec.get("ticker") or ""
    symbol = _normalize_ticker_token(symbol_raw)
    headline = f"8-K filing: {symbol}" if symbol else "8-K filing"

    url = rec.get("finalLink") or rec.get("link") or None
    accepted = str(
        rec.get("acceptedDate") or rec.get("filingDate") or rec.get("date") or ""
    ).strip()
    ts = _to_epoch(accepted)

    item_id = str(url or "").strip()
    if not item_id:
        seed = f"{symbol}|{accepted}|{rec.get('cik', '')}"
        item_id = hashlib.sha1(
            seed.encode("utf-8", errors="replace"), usedforsecurity=False
        ).hexdigest()[:16]

    tickers = [symbol] if symbol else []

    return NewsItem(
        provider="fmp_8k_latest",
        item_id=item_id,
        published_ts=ts,
        updated_ts=ts,
        headline=headline,
        snippet="",
        tickers=tickers,
        url=str(url) if url else None,
        source="SEC EDGAR",
        raw=rec,
    )


# ── FMP SEC 13F-HR filings (B6, PR5 2026-05-09) ────────────


def normalize_fmp_filing_13f(rec: dict[str, Any]) -> NewsItem:
    """Normalise one FMP /sec-filings/13F-HR-latest record.

    13F-HR is institution-keyed (no symbol field), so ``tickers`` is
    always empty and the headline carries the filer name. Cross-provider
    hard-dedup (PR1) still applies via item_id.
    """
    name = str(rec.get("name") or rec.get("filerName") or "").strip()
    cik = str(rec.get("cik") or "").strip()
    headline = f"13F-HR filing: {name}" if name else "13F-HR filing"

    url = rec.get("finalLink") or rec.get("link") or None
    filed = str(
        rec.get("date") or rec.get("filingDate") or rec.get("acceptedDate") or ""
    ).strip()
    ts = _to_epoch(filed)

    item_id = str(url or "").strip()
    if not item_id:
        seed = f"{name}|{filed}|{cik}"
        item_id = hashlib.sha1(
            seed.encode("utf-8", errors="replace"), usedforsecurity=False
        ).hexdigest()[:16]

    return NewsItem(
        provider="fmp_13f_latest",
        item_id=item_id,
        published_ts=ts,
        updated_ts=ts,
        headline=headline,
        snippet="",
        tickers=[],
        url=str(url) if url else None,
        source="SEC EDGAR",
        raw=rec,
    )
