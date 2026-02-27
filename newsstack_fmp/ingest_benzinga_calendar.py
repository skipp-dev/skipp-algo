"""Benzinga Calendar & Market Data adapters.

Provides access to Benzinga API endpoints beyond the core news feed:

Calendar (all use ``parameters[updated]=<epoch>`` for delta sync):
    - Analyst Ratings:    ``/api/v2.1/calendar/ratings``
    - Earnings:           ``/api/v2.1/calendar/earnings``
    - Economics:          ``/api/v2.1/calendar/economics``
    - Conference Calls:   ``/api/v2.1/calendar/conference-calls``
    - Dividends:          ``/api/v2.1/calendar/dividends``
    - Splits:             ``/api/v2.1/calendar/splits``
    - IPO:                ``/api/v2.1/calendar/ipos``
    - Guidance:           ``/api/v2.1/calendar/guidance``
    - Retail:             ``/api/v2.1/calendar/retail``

Market Data:
    - Market Movers:      ``/api/v1/market/movers``
    - Delayed Quotes:     ``/api/v1/quoteDelayed``

All adapters are **optional** — they are only called when
``BENZINGA_API_KEY`` is set.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Regex to strip API keys/tokens from URLs before logging.
_TOKEN_RE = re.compile(r"(apikey|token)=[^&]+", re.IGNORECASE)


def _sanitize_url(url: str) -> str:
    """Remove apikey/token query params from a URL for safe logging."""
    return _TOKEN_RE.sub(r"\1=***", url)


def _sanitize_exc(exc: Exception) -> str:
    """Strip API keys/tokens from exception text for safe logging."""
    return re.sub(r"(apikey|token)=[^&\s]+", r"\1=***", str(exc), flags=re.IGNORECASE)


# =====================================================================
# Shared HTTP helpers
# =====================================================================

_RETRYABLE = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


def _request_with_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
) -> httpx.Response:
    """GET with exponential backoff on retryable status codes."""
    last_exc: Exception | None = None
    r: httpx.Response | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            r = client.get(url, params=params)
            if r.status_code in _RETRYABLE and attempt < _MAX_ATTEMPTS - 1:
                logger.warning(
                    "Benzinga HTTP %s (attempt %d/%d) – retrying in %ds",
                    r.status_code, attempt + 1, _MAX_ATTEMPTS, 2 ** attempt,
                )
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                logger.warning(
                    "Benzinga network error (attempt %d/%d): %s – retrying in %ds",
                    attempt + 1, _MAX_ATTEMPTS, exc, 2 ** attempt,
                )
                time.sleep(2 ** attempt)
                continue
            raise
        except httpx.HTTPStatusError:
            raise
    if r is not None:
        return r
    raise RuntimeError(
        "Benzinga: no response after retries"
        + (f" (last error: {last_exc})" if last_exc else "")
    )


# =====================================================================
# 1) Calendar Adapter (ratings, earnings, economics, conference calls)
# =====================================================================

# Base URL for calendar endpoints
CALENDAR_BASE = "https://api.benzinga.com/api/v2.1/calendar"


class BenzingaCalendarAdapter:
    """Synchronous adapter for Benzinga Calendar API endpoints.

    All endpoints support delta sync via ``parameters[updated]=<epoch>``.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError("BENZINGA_API_KEY missing")
        self.api_key = api_key
        self.client = httpx.Client(
            timeout=10.0,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.client.close()

    # ── Generic calendar fetcher ────────────────────────────

    def _fetch_calendar(
        self,
        endpoint: str,
        *,
        updated_since: int | None = None,
        tickers: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
        importance: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch items from a calendar endpoint.

        Parameters
        ----------
        endpoint : str
            Calendar sub-path, e.g. ``"ratings"`` or ``"conference-calls"``.
        updated_since : int, optional
            Unix epoch for delta sync.
        tickers : str, optional
            Comma-separated ticker list (max 50).
        date_from, date_to : str, optional
            Date range in YYYY-MM-DD format.
        page_size : int
            Max results (API limit varies, typically 100-1000).
        importance : int, optional
            Minimum importance level (0-5).

        Returns
        -------
        list[dict]
            Raw calendar items.
        """
        url = f"{CALENDAR_BASE}/{endpoint}"
        params: dict[str, Any] = {
            "token": self.api_key,
            "pagesize": str(page_size),
        }
        if updated_since is not None:
            params["parameters[updated]"] = str(updated_since)
        if tickers:
            params["parameters[tickers]"] = tickers
        if date_from:
            params["parameters[date_from]"] = date_from
        if date_to:
            params["parameters[date_to]"] = date_to
        if importance is not None:
            params["parameters[importance]"] = str(importance)

        r = _request_with_retry(self.client, url, params)

        try:
            data = r.json()
        except Exception:
            ct = r.headers.get("content-type", "")
            raise ValueError(
                f"Benzinga calendar/{endpoint} returned non-JSON "
                f"(content-type={ct!r}, status={r.status_code})"
            ) from None

        # Calendar responses wrap items in a key matching the endpoint name
        if isinstance(data, dict):
            # Try common wrapper keys
            for key in (endpoint, endpoint.replace("-", "_"), endpoint.rstrip("s")):
                if key in data and isinstance(data[key], list):
                    return list(data[key])
            # Fallback: find first list value
            for v in data.values():
                if isinstance(v, list):
                    return v
            return []
        if isinstance(data, list):
            return data
        return []

    # ── Typed fetchers ──────────────────────────────────────

    def fetch_ratings(
        self,
        *,
        updated_since: int | None = None,
        tickers: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
        importance: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch analyst ratings (upgrades, downgrades, initiations, PT changes).

        Returns list of dicts with keys: ticker, action_company, action_pt,
        analyst, analyst_name, pt_current, pt_prior, rating_current,
        rating_prior, importance, date, time, updated, etc.
        """
        return self._fetch_calendar(
            "ratings",
            updated_since=updated_since,
            tickers=tickers,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            importance=importance,
        )

    def fetch_earnings(
        self,
        *,
        updated_since: int | None = None,
        tickers: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
        importance: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch earnings calendar (EPS, revenue estimates/actuals/surprises).

        Returns list of dicts with keys: ticker, date, eps, eps_est,
        eps_prior, eps_surprise, revenue, revenue_est, period,
        period_year, importance, updated, etc.
        """
        return self._fetch_calendar(
            "earnings",
            updated_since=updated_since,
            tickers=tickers,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            importance=importance,
        )

    def fetch_economics(
        self,
        *,
        updated_since: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
        importance: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch economic calendar (GDP, NFP, CPI, FOMC, etc.).

        Returns list of dicts with keys: event_name, country, actual,
        consensus, prior, importance, date, time, updated, etc.
        """
        return self._fetch_calendar(
            "economics",
            updated_since=updated_since,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            importance=importance,
        )

    def fetch_conference_calls(
        self,
        *,
        updated_since: int | None = None,
        tickers: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch conference call schedule (earnings calls, webcast URLs).

        Returns list of dicts with keys: ticker, date, start_time,
        period, webcast_url, updated, etc.
        """
        return self._fetch_calendar(
            "conference-calls",
            updated_since=updated_since,
            tickers=tickers,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
        )

    # ── New calendar fetchers ───────────────────────────────

    def fetch_dividends(
        self,
        *,
        updated_since: int | None = None,
        tickers: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
        importance: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch dividend calendar.

        Returns list of dicts with keys: ticker, name, exchange,
        frequency, dividend, dividend_prior, dividend_type, dividend_yield,
        ex_date, payable_date, record_date, importance, updated, etc.
        """
        return self._fetch_calendar(
            "dividends",
            updated_since=updated_since,
            tickers=tickers,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            importance=importance,
        )

    def fetch_splits(
        self,
        *,
        updated_since: int | None = None,
        tickers: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
        importance: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch stock splits calendar.

        Returns list of dicts with keys: ticker, exchange, ratio,
        optionable, date_ex, date_recorded, date_distribution,
        importance, updated, etc.
        """
        return self._fetch_calendar(
            "splits",
            updated_since=updated_since,
            tickers=tickers,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            importance=importance,
        )

    def fetch_ipos(
        self,
        *,
        updated_since: int | None = None,
        tickers: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
        importance: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch IPO calendar.

        Returns list of dicts with keys: ticker, exchange, name,
        pricing_date, price_min, price_max, deal_status,
        insider_lockup_days, offering_value, offering_shares,
        lead_underwriters, importance, updated, etc.
        """
        return self._fetch_calendar(
            "ipos",
            updated_since=updated_since,
            tickers=tickers,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            importance=importance,
        )

    def fetch_guidance(
        self,
        *,
        updated_since: int | None = None,
        tickers: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
        importance: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch earnings/revenue guidance calendar.

        Returns list of dicts with keys: ticker, date, period,
        period_year, prelim, eps_guidance_est, eps_guidance_max,
        eps_guidance_min, revenue_guidance_est, revenue_guidance_max,
        revenue_guidance_min, importance, updated, etc.
        """
        return self._fetch_calendar(
            "guidance",
            updated_since=updated_since,
            tickers=tickers,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            importance=importance,
        )

    def fetch_retail(
        self,
        *,
        updated_since: int | None = None,
        tickers: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 100,
        importance: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch retail sales calendar.

        Returns list of dicts with keys: ticker, name, period,
        period_year, sss, sss_est, retail_surprise, importance,
        updated, etc.
        """
        return self._fetch_calendar(
            "retail",
            updated_since=updated_since,
            tickers=tickers,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            importance=importance,
        )


# =====================================================================
# 2) Market Movers
# =====================================================================

MOVERS_URL = "https://api.benzinga.com/api/v1/market/movers"


def fetch_benzinga_movers(api_key: str) -> dict[str, list[dict[str, Any]]]:
    """Fetch market movers (gainers, losers, most active).

    Returns dict with keys: ``gainers``, ``losers`` — each a list of
    dicts with keys: symbol, price, change, changePercent, volume,
    averageVolume, marketCap, companyName, gicsSectorName, etc.
    """
    with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
        try:
            r = _request_with_retry(client, MOVERS_URL, {"token": api_key})
            data = r.json()
        except Exception as exc:
            logger.warning("Benzinga movers fetch failed: %s", _sanitize_exc(exc))
            return {"gainers": [], "losers": []}

    result: dict[str, Any] = {}
    if isinstance(data, dict):
        inner = data.get("result", data)
        result["gainers"] = inner.get("gainers", []) if isinstance(inner, dict) else []
        result["losers"] = inner.get("losers", []) if isinstance(inner, dict) else []
    else:
        result = {"gainers": [], "losers": []}

    return result


# =====================================================================
# 3) Delayed Quotes
# =====================================================================

QUOTES_URL = "https://api.benzinga.com/api/v1/quoteDelayed"


def fetch_benzinga_quotes(
    api_key: str,
    symbols: list[str],
) -> list[dict[str, Any]]:
    """Fetch delayed quotes for a list of symbols.

    Parameters
    ----------
    api_key : str
        Benzinga API key.
    symbols : list[str]
        Ticker symbols (e.g. ["AAPL", "NVDA", "SPY"]).

    Returns
    -------
    list[dict]
        Flattened quote records with keys: symbol, name, last, change,
        changePercent, open, high, low, close, volume, fiftyTwoWeekHigh,
        fiftyTwoWeekLow, previousClose.
    """
    if not symbols:
        return []

    # API supports max ~50 symbols per call
    sym_str = ",".join(s.strip().upper() for s in symbols[:50])

    with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
        try:
            r = _request_with_retry(client, QUOTES_URL, {
                "token": api_key,
                "symbols": sym_str,
            })
            data = r.json()
        except Exception as exc:
            logger.warning("Benzinga quotes fetch failed: %s", _sanitize_exc(exc))
            return []

    # Flatten the nested {security, quote} structure
    quotes_raw: list[dict[str, Any]] = []
    if isinstance(data, dict):
        quotes_raw = data.get("quotes", [])
    elif isinstance(data, list):
        quotes_raw = data

    results: list[dict[str, Any]] = []
    for q in quotes_raw:
        if not isinstance(q, dict):
            continue
        sec = q.get("security", {}) or {}
        quote = q.get("quote", {}) or {}
        results.append({
            "symbol": sec.get("symbol", ""),
            "name": sec.get("name", ""),
            "last": quote.get("last") or quote.get("close"),
            "change": quote.get("change"),
            "changePercent": quote.get("changePercent"),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
            "fiftyTwoWeekHigh": quote.get("fiftyTwoWeekHigh"),
            "fiftyTwoWeekLow": quote.get("fiftyTwoWeekLow"),
            "previousClose": quote.get("previousClose"),
        })

    return results
