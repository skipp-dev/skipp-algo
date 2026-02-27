"""Benzinga Financial Data adapter.

Provides access to Benzinga's Financial Data API endpoints:

Ticker-level data:
    - Price History:          ``/api/v2/bars``
    - Auto-Complete:          ``/api/v2/search``
    - Security:               ``/api/v2/security``
    - Chart:                  ``/api/v2/bars``
    - Quote:                  ``/api/v1/quoteDelayed``
    - Instruments:            ``/api/v2.1/instruments``

Fundamentals:
    - Fundamentals:           ``/api/v2.1/fundamentals``
    - Financials:             ``/api/v2.1/fundamentals/financials``
    - Valuation Ratios:       ``/api/v2.1/fundamentals/valuationRatios``
    - Earning Ratios:         ``/api/v2.1/fundamentals/earningRatios``
    - Operation Ratios:       ``/api/v2.1/fundamentals/operationRatios``
    - Share Class:            ``/api/v2.1/fundamentals/shareClass``
    - Earning Reports:        ``/api/v2.1/fundamentals/earningReports``
    - Alpha Beta:             ``/api/v2.1/fundamentals/alphaBeta``
    - Company Profile:        ``/api/v2.1/fundamentals/companyProfile``
    - Company:                ``/api/v2.1/fundamentals/company``
    - Share Class Profile:    ``/api/v2.1/fundamentals/shareClassProfileHistory``
    - Asset Classification:   ``/api/v2.1/fundamentals/assetClassification``
    - Summary:                ``/api/v2.1/fundamentals/summary``

Other:
    - Logos:                  ``/api/v2/logos``
    - Movers:                 ``/api/v1/market/movers``
    - Ticker Detail:          ``/api/v2/tickerDetail``
    - Options Activity:       ``/api/v2.1/calendar/options_activity``
    - SEC Insider Transactions: ``/api/v2.1/ownership``

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

from newsstack_fmp._bz_http import _TOKEN_RE, _sanitize_exc, _sanitize_url  # noqa: E402


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
# Base URLs
# =====================================================================

FUNDAMENTALS_BASE = "https://api.benzinga.com/api/v2.1/fundamentals"
BARS_URL = "https://api.benzinga.com/api/v2/bars"
SEARCH_URL = "https://api.benzinga.com/api/v2/search"
SECURITY_URL = "https://api.benzinga.com/api/v2/security"
INSTRUMENTS_URL = "https://api.benzinga.com/api/v2.1/instruments"
LOGOS_URL = "https://api.benzinga.com/api/v2/logos"
TICKER_DETAIL_URL = "https://api.benzinga.com/api/v2/tickerDetail"
OPTIONS_ACTIVITY_URL = "https://api.benzinga.com/api/v2.1/calendar/options_activity"
OWNERSHIP_URL = "https://api.benzinga.com/api/v2.1/ownership"


class BenzingaFinancialAdapter:
    """Synchronous adapter for Benzinga Financial Data API endpoints.

    Covers fundamentals, financials, ratios, company profiles,
    price history, instruments, options activity, and more.
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

    # ── Generic fetcher ─────────────────────────────────────

    def _fetch_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Fetch JSON from *url* with auth token + optional params."""
        p: dict[str, Any] = {"token": self.api_key}
        if params:
            p.update(params)
        r = _request_with_retry(self.client, url, p)
        try:
            return r.json()
        except Exception:
            ct = r.headers.get("content-type", "")
            raise ValueError(
                f"Benzinga returned non-JSON (content-type={ct!r}, "
                f"status={r.status_code}, url={_sanitize_url(str(r.url))})"
            ) from None

    def _extract_list(self, data: Any, *keys: str) -> list[dict[str, Any]]:
        """Extract a list of dicts from *data* trying *keys* in order."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in keys:
                if key in data and isinstance(data[key], list):
                    return list(data[key])
            # Fallback: first list value
            for v in data.values():
                if isinstance(v, list):
                    return v
        return []

    def _extract_dict(self, data: Any, *keys: str) -> dict[str, Any]:
        """Extract a dict from *data* trying *keys* in order."""
        if isinstance(data, dict):
            for key in keys:
                if key in data and isinstance(data[key], dict):
                    return dict(data[key])
            return data
        return {}

    # ── Fundamentals (ticker-level) ─────────────────────────

    def _fetch_fundamentals(
        self,
        endpoint: str,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
        period: str | None = None,
        report_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Generic fundamentals fetcher for ``/api/v2.1/fundamentals/<endpoint>``."""
        url = f"{FUNDAMENTALS_BASE}/{endpoint}" if endpoint else FUNDAMENTALS_BASE
        params: dict[str, Any] = {"symbols": tickers}
        if isin:
            params["isin"] = isin
        if cik:
            params["cik"] = cik
        if date_asof:
            params["asOf"] = date_asof
        if period:
            params["period"] = period
        if report_type:
            params["reportType"] = report_type
        data = self._fetch_json(url, params)
        return self._extract_list(data, "result", "fundamentals", "data")

    def fetch_fundamentals(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch overall fundamentals for a company.

        Returns list of dicts with keys: company, companyProfile,
        shareClass, earningReports, financialStatements, operation/
        earning/valuation ratios, alphaBeta.
        """
        return self._fetch_fundamentals(
            "", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_financials(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
        period: str | None = None,
        report_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch financial statements (balance sheet, income, cash flow).

        Parameters
        ----------
        period : str, optional
            ``"3M"``, ``"6M"``, ``"9M"``, ``"12M"``, ``"1Y"``.
        report_type : str, optional
            ``"TTM"``, ``"A"`` (annual, default), ``"R"``, ``"P"``.
        """
        return self._fetch_fundamentals(
            "financials", tickers, isin=isin, cik=cik,
            date_asof=date_asof, period=period, report_type=report_type,
        )

    def fetch_valuation_ratios(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch valuation ratios (P/E, P/B, EV/EBITDA, etc.)."""
        return self._fetch_fundamentals(
            "valuationRatios", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_earning_ratios(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch earning ratios."""
        return self._fetch_fundamentals(
            "earningRatios", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_operation_ratios(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch operation ratios (margins, asset turnover, etc.)."""
        return self._fetch_fundamentals(
            "operationRatios", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_share_class(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch share class information."""
        return self._fetch_fundamentals(
            "shareClass", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_earning_reports(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch detailed earning reports."""
        return self._fetch_fundamentals(
            "earningReports", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_alpha_beta(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch alpha/beta values for a ticker."""
        return self._fetch_fundamentals(
            "alphaBeta", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_company_profile(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch company profile (sector, industry, description, employees, etc.)."""
        return self._fetch_fundamentals(
            "companyProfile", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_company(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch company information."""
        return self._fetch_fundamentals(
            "company", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_share_class_profile_history(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch share class profile history."""
        return self._fetch_fundamentals(
            "shareClassProfileHistory", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_asset_classification(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch asset classification (GICS sector, industry group, etc.)."""
        return self._fetch_fundamentals(
            "assetClassification", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    def fetch_summary(
        self,
        tickers: str,
        *,
        isin: str | None = None,
        cik: str | None = None,
        date_asof: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch summary data for a ticker."""
        return self._fetch_fundamentals(
            "summary", tickers, isin=isin, cik=cik, date_asof=date_asof,
        )

    # ── Market Data ─────────────────────────────────────────

    def fetch_price_history(
        self,
        tickers: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, Any]]:
        """Fetch daily price bars for a ticker over a date range.

        Parameters
        ----------
        tickers : str
            Ticker symbol(s).
        date_from : str
            Start date ``"YYYY-MM-DD"``.
        date_to : str
            End date ``"YYYY-MM-DD"``.

        Returns
        -------
        list[dict]
            Daily candles: open, high, low, close, volume, dateTime, time.
        """
        params: dict[str, Any] = {
            "symbols": tickers,
            "from": date_from,
            "to": date_to,
        }
        data = self._fetch_json(BARS_URL, params)
        return self._extract_list(data, "result", "data", "bars")

    def fetch_chart(
        self,
        tickers: str,
        date_from: str,
        *,
        date_to: str | None = None,
        interval: str = "5M",
        session: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch intraday/period chart data.

        Parameters
        ----------
        date_from : str
            ``"YYYY-MM-DD"`` or shortcuts: ``"YTD"``, ``"1d"``, ``"5d"``, ``"1m"``.
        interval : str
            ``"1MONTH"``, ``"1W"``, ``"1D"``, ``"1H"``, ``"15M"``, ``"5M"`` (default).
        session : str, optional
            ``"ANY"`` or ``"REGULAR"``.
        """
        params: dict[str, Any] = {
            "symbols": tickers,
            "from": date_from,
            "interval": interval,
        }
        if date_to:
            params["to"] = date_to
        if session:
            params["session"] = session
        data = self._fetch_json(BARS_URL, params)
        return self._extract_list(data, "result", "data", "bars")

    def fetch_auto_complete(
        self,
        query: str,
        *,
        limit: int = 10,
        search_method: str | None = None,
        exchanges: str | None = None,
        types: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search/auto-complete for tickers and company names.

        Parameters
        ----------
        query : str
            Search query (ticker or company name).
        search_method : str, optional
            ``"SYMBOL"``, ``"SYMBOL_NAME"``, or ``"SYMBOL_WITHIN"``.
        exchanges : str, optional
            Limit to specific exchanges.
        types : str, optional
            ``"STOCK"``, ``"TYPE"``, ``"OEF"``.
        """
        params: dict[str, Any] = {
            "query": query,
            "limit": str(limit),
        }
        if search_method:
            params["searchMethod"] = search_method
        if exchanges:
            params["exchanges"] = exchanges
        if types:
            params["types"] = types
        data = self._fetch_json(SEARCH_URL, params)
        return self._extract_list(data, "result", "data", "search")

    def fetch_security(
        self,
        tickers: str,
        *,
        cusip: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch security information (exchange, country, currency, CUSIP).

        Returns list of dicts with keys: symbol, exchange, country,
        currency, cusip, description.
        """
        params: dict[str, Any] = {"symbols": tickers}
        if cusip:
            params["cusip"] = cusip
        data = self._fetch_json(SECURITY_URL, params)
        return self._extract_list(data, "result", "data", "securities")

    def fetch_instruments(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        date_asof: str | None = None,
        market_cap_gt: str | None = None,
        market_cap_lt: str | None = None,
        close_gt: str | None = None,
        sector: str | None = None,
        sort_field: str | None = None,
        sort_dir: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch screener/instruments data with price statistics.

        Supports filtering by market cap, sector, close price, etc.
        """
        params: dict[str, Any] = {}
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        if date_asof:
            params["asOf"] = date_asof
        if market_cap_gt:
            params["marketCapGt"] = market_cap_gt
        if market_cap_lt:
            params["marketCapLt"] = market_cap_lt
        if close_gt:
            params["closeGt"] = close_gt
        if sector:
            params["sector"] = sector
        if sort_field:
            params["sortField"] = sort_field
        if sort_dir:
            params["sortDir"] = sort_dir
        data = self._fetch_json(INSTRUMENTS_URL, params)
        return self._extract_list(data, "result", "data", "instruments")

    def fetch_logos(
        self,
        tickers: str,
        *,
        filters: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch company logo URLs.

        Returns list of dicts with logo attributes.
        """
        params: dict[str, Any] = {"symbols": tickers}
        if filters:
            params["filters"] = filters
        data = self._fetch_json(LOGOS_URL, params)
        return self._extract_list(data, "result", "data", "logos")

    def fetch_ticker_detail(
        self,
        tickers: str,
    ) -> list[dict[str, Any]]:
        """Fetch key statistics, peers, and percentile info for a ticker.

        Returns list of dicts with key stats, peer information, and
        percentile data.
        """
        params: dict[str, Any] = {"symbols": tickers}
        data = self._fetch_json(TICKER_DETAIL_URL, params)
        return self._extract_list(data, "result", "data", "tickers")

    def fetch_options_activity(
        self,
        tickers: str,
        *,
        page_size: int = 100,
        page: int = 0,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch options activity (unusual flow, large trades).

        Parameters
        ----------
        tickers : str
            Ticker symbol(s).
        page_size : int
            Max results (API limit 1000).
        date, date_from, date_to : str, optional
            Date filters in ``"YYYY-MM-DD"`` format.

        Returns
        -------
        list[dict]
            Options activity records.
        """
        params: dict[str, Any] = {
            "parameters[tickers]": tickers,
            "pagesize": str(page_size),
            "page": str(page),
        }
        if date:
            params["parameters[date]"] = date
        if date_from:
            params["parameters[date_from]"] = date_from
        if date_to:
            params["parameters[date_to]"] = date_to
        data = self._fetch_json(OPTIONS_ACTIVITY_URL, params)
        return self._extract_list(data, "options_activity", "result", "data")

    # ── SEC Insider Transactions (Ownership API) ────────────

    def fetch_insider_transactions(
        self,
        *,
        tickers: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        action: str | None = None,
        page_size: int = 100,
        page: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch SEC insider transactions (Form 4 filings).

        Parameters
        ----------
        tickers : str, optional
            Ticker symbol(s), comma-separated.
        date_from, date_to : str, optional
            Date range in ``"YYYY-MM-DD"`` format.
        action : str, optional
            Filter by transaction type: ``"S"`` (sale), ``"P"`` (purchase),
            ``"A"`` (grant/award), ``"D"`` (disposition), ``"M"`` (exercise).
        page_size : int
            Max results per page (default 100).
        page : int
            Page number (0-based).

        Returns
        -------
        list[dict]
            Insider transaction records with keys like:
            ``ticker``, ``company_name``, ``owner_name``, ``owner_title``,
            ``transaction_type``, ``date``, ``shares_traded``,
            ``price_per_share``, ``total_value``, ``shares_held``.
        """
        params: dict[str, Any] = {
            "pageSize": str(page_size),
            "page": str(page),
        }
        if tickers:
            params["symbols"] = tickers
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        if action:
            params["action"] = action
        data = self._fetch_json(OWNERSHIP_URL, params)
        return self._extract_list(data, "ownership", "data", "result")


# =====================================================================
# Convenience standalone functions (no adapter lifecycle management)
# ===================================================================


def fetch_benzinga_fundamentals(
    api_key: str,
    tickers: str,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch fundamentals — standalone wrapper."""
    adapter = BenzingaFinancialAdapter(api_key)
    try:
        return adapter.fetch_fundamentals(tickers, **kwargs)
    except Exception as exc:
        logger.warning("Benzinga fundamentals fetch failed: %s", _sanitize_exc(exc))
        return []
    finally:
        adapter.close()


def fetch_benzinga_financials(
    api_key: str,
    tickers: str,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch financial statements — standalone wrapper."""
    adapter = BenzingaFinancialAdapter(api_key)
    try:
        return adapter.fetch_financials(tickers, **kwargs)
    except Exception as exc:
        logger.warning("Benzinga financials fetch failed: %s", _sanitize_exc(exc))
        return []
    finally:
        adapter.close()


def fetch_benzinga_company_profile(
    api_key: str,
    tickers: str,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch company profile — standalone wrapper."""
    adapter = BenzingaFinancialAdapter(api_key)
    try:
        return adapter.fetch_company_profile(tickers, **kwargs)
    except Exception as exc:
        logger.warning("Benzinga company profile fetch failed: %s", _sanitize_exc(exc))
        return []
    finally:
        adapter.close()


def fetch_benzinga_options_activity(
    api_key: str,
    tickers: str,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch options activity — standalone wrapper."""
    adapter = BenzingaFinancialAdapter(api_key)
    try:
        return adapter.fetch_options_activity(tickers, **kwargs)
    except Exception as exc:
        logger.warning("Benzinga options activity fetch failed: %s", _sanitize_exc(exc))
        return []
    finally:
        adapter.close()


def fetch_benzinga_ticker_detail(
    api_key: str,
    tickers: str,
) -> list[dict[str, Any]]:
    """Fetch ticker detail — standalone wrapper."""
    adapter = BenzingaFinancialAdapter(api_key)
    try:
        return adapter.fetch_ticker_detail(tickers)
    except Exception as exc:
        logger.warning("Benzinga ticker detail fetch failed: %s", _sanitize_exc(exc))
        return []
    finally:
        adapter.close()


def fetch_benzinga_price_history(
    api_key: str,
    tickers: str,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    """Fetch price history bars — standalone wrapper."""
    adapter = BenzingaFinancialAdapter(api_key)
    try:
        return adapter.fetch_price_history(tickers, date_from, date_to)
    except Exception as exc:
        logger.warning("Benzinga price history fetch failed: %s", _sanitize_exc(exc))
        return []
    finally:
        adapter.close()


def fetch_benzinga_logos(
    api_key: str,
    tickers: str,
) -> list[dict[str, Any]]:
    """Fetch logos — standalone wrapper."""
    adapter = BenzingaFinancialAdapter(api_key)
    try:
        return adapter.fetch_logos(tickers)
    except Exception as exc:
        logger.warning("Benzinga logos fetch failed: %s", _sanitize_exc(exc))
        return []
    finally:
        adapter.close()


def fetch_benzinga_auto_complete(
    api_key: str,
    query: str,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch auto-complete search results — standalone wrapper."""
    adapter = BenzingaFinancialAdapter(api_key)
    try:
        return adapter.fetch_auto_complete(query, **kwargs)
    except Exception as exc:
        logger.warning("Benzinga auto-complete fetch failed: %s", _sanitize_exc(exc))
        return []
    finally:
        adapter.close()


def fetch_benzinga_insider_transactions(
    api_key: str,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch SEC insider transactions — standalone wrapper."""
    adapter = BenzingaFinancialAdapter(api_key)
    try:
        return adapter.fetch_insider_transactions(**kwargs)
    except Exception as exc:
        logger.warning("Benzinga insider transactions fetch failed: %s", _sanitize_exc(exc))
        return []
    finally:
        adapter.close()
