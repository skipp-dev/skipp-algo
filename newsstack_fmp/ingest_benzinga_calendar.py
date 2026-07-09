"""Benzinga Calendar & Market Data adapters.

Provides access to Benzinga API endpoints beyond the core news feed:

Calendar (direct delta sync via ``parameters[updated]=<epoch>``, EXCEPT
dividends/splits/ipos which are dual-transport — see :meth:`fetch_dividends`):
    - Dividends:  ``/api/v2.1/calendar/dividends`` OR Massive ``/v3/reference/dividends``
    - Splits:     ``/api/v2.1/calendar/splits``    OR Massive ``/v3/reference/splits``
    - IPO:        ``/api/v2.1/calendar/ipos``      OR Massive ``/vX/reference/ipos``
    - Earnings:   ``/api/v2.1/calendar/earnings``  (direct-only; outlook scorer /
                  movers classifier / open-prep calendar fallback)
    - Economics:  ``/api/v2.1/calendar/economics`` (direct-only; outlook scorer)
    - Ratings/Guidance/Retail/Conference Calls: direct-only, no Massive route.
      Retained as library methods, but the terminal calendar tabs/wrappers that
      used them were retired 2026-07-09 (the Benzinga free key is being replaced
      by Massive, which has no route for these) — no live app consumer left.

Market Data:
    - Market Movers:      ``/api/v1/market/movers``
    - Delayed Quotes:     ``/api/v1/quoteDelayed``

All adapters are **optional** — they are only called when
``BENZINGA_API_KEY`` is set.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from newsstack_fmp._bz_http import (
    BenzingaEndpointDisabledError,
    _request_with_retry,
    log_fetch_warning,
)
from newsstack_fmp.ingest_benzinga import benzinga_provider

from .normalize import normalize_benzinga_calendar_item

logger = logging.getLogger(__name__)

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
        endpoint_kind: str | None = None,
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
            Calendar items normalized via :func:`normalize_benzinga_calendar_item`:
            each row is the original raw payload enriched with stable canonical
            keys (``event_id``, ``event_date``, ``symbol``, ``event_actual``,
            ``event_forecast``, ``event_previous``, ``importance``) plus
            ``kind`` set to ``endpoint_kind``. Original raw fields are preserved
            for back-compat.
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

        r = _request_with_retry(self.client, url, params, label=f"Benzinga calendar/{endpoint}")

        if r.status_code != 200:
            logger.warning("Benzinga calendar/%s HTTP %d", endpoint, r.status_code)
            return []

        try:
            data = r.json()
        except Exception:
            ct = r.headers.get("content-type", "")
            raise ValueError(
                f"Benzinga calendar/{endpoint} returned non-JSON "
                f"(content-type={ct!r}, status={r.status_code})"
            ) from None

        # Calendar responses wrap items in a key matching the endpoint name
        rows: list[dict[str, Any]] = []
        if isinstance(data, dict):
            for key in (endpoint, endpoint.replace("-", "_"), endpoint.rstrip("s")):
                if key in data and isinstance(data[key], list):
                    rows = list(data[key])
                    break
            else:
                for v in data.values():
                    if isinstance(v, list):
                        rows = list(v)
                        break
        elif isinstance(data, list):
            rows = list(data)
        # Apply canonical-schema normalization so consumers see stable keys
        # even if upstream Benzinga renames variants (actual -> actualValue, etc.).
        kind = endpoint_kind or endpoint.replace("-", "_")
        return [normalize_benzinga_calendar_item(r, kind) for r in rows]

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

        With ``BENZINGA_PROVIDER=massive`` the rows come from Massive's native
        ``/v3/reference/dividends`` mapped to the column names the terminal tab
        consumes (ticker, date, ex_date, payable_date, record_date, dividend,
        frequency); the direct Benzinga path returns the fuller native schema.
        """
        if benzinga_provider() == "massive":
            return _massive_dividends(self.api_key, date_from, date_to, page_size)
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

        With ``BENZINGA_PROVIDER=massive`` the rows come from Massive's native
        ``/v3/reference/splits`` mapped to ticker/date/date_ex/ratio; the direct
        Benzinga path returns the fuller native schema.
        """
        if benzinga_provider() == "massive":
            return _massive_splits(self.api_key, date_from, date_to, page_size)
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

        With ``BENZINGA_PROVIDER=massive`` the rows come from Massive's native
        ``/vX/reference/ipos`` mapped to ticker/name/exchange/pricing_date/
        price_min/price_max/deal_status/offering_value; the direct Benzinga path
        returns the fuller native schema.
        """
        if benzinga_provider() == "massive":
            return _massive_ipos(self.api_key, date_from, date_to, page_size)
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

# Massive (ex-Polygon) native stock snapshots — the movers/quotes route when
# BENZINGA_PROVIDER=massive (the paid Massive key; api.benzinga.com answers it
# 401). Requires the Stocks Starter plan (15-min-delayed snapshots; verified
# live 2026-07-09: gainers/tickers 200, quote `updated` age ~15.1 min).
MASSIVE_SNAPSHOT_BASE = "https://api.massive.com/v2/snapshot/locale/us/markets/stocks"

# Massive (ex-Polygon) native reference endpoints — the dividends/splits/ipos
# calendar route when BENZINGA_PROVIDER=massive. Native to the subscribed plan
# (schema verified 2026-07-09 via massive.com/docs). The Benzinga free key is
# being retired, so Massive is the replacement for these three; rows are mapped
# to the same column names the terminal Benzinga-Intelligence tabs consume.
MASSIVE_REFERENCE_BASE = "https://api.massive.com/v3/reference"
MASSIVE_IPOS_URL = "https://api.massive.com/vX/reference/ipos"


def _massive_reference_rows(
    url: str, api_key: str, params: dict[str, Any], label: str
) -> list[dict[str, Any]]:
    """GET a Massive reference endpoint and return its ``results`` rows (fail-soft)."""
    request_params: dict[str, Any] = {"apiKey": api_key}
    request_params.update(params)
    with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
        try:
            r = _request_with_retry(client, url, request_params, label=label)
            data = r.json()
        except Exception as exc:
            log_fetch_warning(label, exc)
            return []
    rows = data.get("results") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def _massive_dividends(
    api_key: str, date_from: str | None, date_to: str | None, page_size: int
) -> list[dict[str, Any]]:
    """Massive /v3/reference/dividends -> the Benzinga-dividends row shape the UI consumes."""
    params: dict[str, Any] = {"limit": min(page_size, 1000), "order": "desc", "sort": "ex_dividend_date"}
    if date_from:
        params["ex_dividend_date.gte"] = date_from
    if date_to:
        params["ex_dividend_date.lte"] = date_to
    rows = _massive_reference_rows(
        f"{MASSIVE_REFERENCE_BASE}/dividends", api_key, params, "Massive dividends"
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ex = r.get("ex_dividend_date", "")
        out.append({
            "ticker": str(r.get("ticker", "") or "").upper(),
            "date": ex,
            "ex_date": ex,
            "payable_date": r.get("pay_date", ""),
            "record_date": r.get("record_date", ""),
            "dividend": r.get("cash_amount"),
            "frequency": r.get("frequency"),
        })
    return out


def _massive_splits(
    api_key: str, date_from: str | None, date_to: str | None, page_size: int
) -> list[dict[str, Any]]:
    """Massive /v3/reference/splits -> the Benzinga-splits row shape the UI consumes."""
    params: dict[str, Any] = {"limit": min(page_size, 1000), "order": "desc", "sort": "execution_date"}
    if date_from:
        params["execution_date.gte"] = date_from
    if date_to:
        params["execution_date.lte"] = date_to
    rows = _massive_reference_rows(
        f"{MASSIVE_REFERENCE_BASE}/splits", api_key, params, "Massive splits"
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        split_from = r.get("split_from")
        split_to = r.get("split_to")
        ratio = f"{split_to}:{split_from}" if split_from and split_to else ""
        ex = r.get("execution_date", "")
        out.append({
            "ticker": str(r.get("ticker", "") or "").upper(),
            "date": ex,
            "date_ex": ex,
            "ratio": ratio,
        })
    return out


def _massive_ipos(
    api_key: str, date_from: str | None, date_to: str | None, page_size: int
) -> list[dict[str, Any]]:
    """Massive /vX/reference/ipos -> the Benzinga-ipos row shape the UI consumes."""
    params: dict[str, Any] = {"limit": min(page_size, 1000), "order": "desc", "sort": "listing_date"}
    if date_from:
        params["listing_date.gte"] = date_from
    if date_to:
        params["listing_date.lte"] = date_to
    rows = _massive_reference_rows(MASSIVE_IPOS_URL, api_key, params, "Massive ipos")
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "ticker": str(r.get("ticker", "") or "").upper(),
            "name": r.get("issuer_name", ""),
            "exchange": r.get("primary_exchange", ""),
            "pricing_date": r.get("listing_date", ""),
            "price_min": r.get("lowest_offer_price"),
            "price_max": r.get("highest_offer_price"),
            "deal_status": r.get("ipo_status", ""),
            "offering_value": r.get("total_offer_size"),
        })
    return out


def _snap_num(value: Any) -> float | None:
    """Positive finite number or None (explicit — 0/None/'' are not prices)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def _massive_snapshot_tickers(client: httpx.Client, url: str, params: dict[str, Any], label: str) -> list[dict[str, Any]]:
    """GET a Massive snapshot endpoint and return its ticker rows (fail-soft)."""
    try:
        r = _request_with_retry(client, url, params, label=label)
        data = r.json()
    except Exception as exc:
        log_fetch_warning(label, exc)
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("tickers")
    return rows if isinstance(rows, list) else []


def _massive_snapshot_to_quote(t: dict[str, Any]) -> dict[str, Any]:
    """Map one Massive snapshot ticker row to the flat Benzinga-quote shape.

    ``min`` is the latest (15-min-delayed) minute bar -> best "last"; ``day``
    covers today's session; ``prevDay`` yesterday. Fields the snapshot does
    not carry (name, 52w high/low) stay ''/None — consumers .get() them.
    """
    day = t.get("day") if isinstance(t.get("day"), dict) else {}
    minute = t.get("min") if isinstance(t.get("min"), dict) else {}
    prev = t.get("prevDay") if isinstance(t.get("prevDay"), dict) else {}
    last = _snap_num(minute.get("c"))
    if last is None:
        last = _snap_num(day.get("c"))
    if last is None:
        last = _snap_num(prev.get("c"))
    # On the 15-min-delayed Starter feed the `day` aggregate is all-zero
    # intraday (verified live 2026-07-09); the accumulated session volume
    # lives in `min.av`. _snap_num turns those zeros into None (no bogus 0s).
    volume = _snap_num(day.get("v"))
    if volume is None:
        volume = _snap_num(minute.get("av"))
    return {
        "symbol": str(t.get("ticker", "") or "").upper(),
        "name": "",
        "last": last,
        "change": t.get("todaysChange"),
        "changePercent": t.get("todaysChangePerc"),
        "open": _snap_num(day.get("o")),
        "high": _snap_num(day.get("h")),
        "low": _snap_num(day.get("l")),
        "close": _snap_num(day.get("c")),
        "volume": volume,
        "fiftyTwoWeekHigh": None,
        "fiftyTwoWeekLow": None,
        "previousClose": _snap_num(prev.get("c")),
    }


def _massive_mover_row(t: dict[str, Any]) -> dict[str, Any]:
    """Map one Massive gainers/losers row to the Benzinga-movers row shape."""
    q = _massive_snapshot_to_quote(t)
    return {
        "symbol": q["symbol"],
        "price": q["last"],
        "change": q["change"],
        "changePercent": q["changePercent"],
        "volume": q["volume"],
        "averageVolume": None,
        "marketCap": None,
        "companyName": "",
        "gicsSectorName": "",
    }


def _fetch_massive_movers(api_key: str) -> dict[str, list[dict[str, Any]]]:
    """Movers via Massive snapshots (top-20 gainers + losers, 15-min delayed)."""
    out: dict[str, list[dict[str, Any]]] = {"gainers": [], "losers": []}
    with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
        for direction in ("gainers", "losers"):
            rows = _massive_snapshot_tickers(
                client,
                f"{MASSIVE_SNAPSHOT_BASE}/{direction}",
                {"apiKey": api_key},
                label=f"Massive movers {direction}",
            )
            out[direction] = [_massive_mover_row(t) for t in rows if isinstance(t, dict)]
    return out


def fetch_benzinga_movers(api_key: str) -> dict[str, list[dict[str, Any]]]:
    """Fetch market movers (gainers and losers only — no most-active list).

    Returns dict with keys: ``gainers``, ``losers`` — each a list of
    dicts with keys: symbol, price, change, changePercent, volume,
    averageVolume, marketCap, companyName, gicsSectorName, etc.

    With ``BENZINGA_PROVIDER=massive`` the data comes from the Massive
    snapshot endpoints instead (same row shape; snapshot-absent fields are
    None/'' — averageVolume, marketCap, companyName, gicsSectorName).
    """
    if benzinga_provider() == "massive":
        return _fetch_massive_movers(api_key)
    with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
        try:
            r = _request_with_retry(client, MOVERS_URL, {"token": api_key}, label="Benzinga movers")
            data = r.json()
        except Exception as exc:
            log_fetch_warning("Benzinga movers", exc)
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

    With ``BENZINGA_PROVIDER=massive`` the quotes come from the Massive
    full-market snapshot (15-min delayed on Stocks Starter; same record
    shape; name/52w-high/low are ''/None — the snapshot doesn't carry them).
    """
    if not symbols:
        return []

    # Benzinga's quoteDelayed endpoint accepts max ~50 symbols per call.
    # Chunk through the full list so callers passing >50 symbols (Streamlit
    # watchlists, terminal_tabs) don't silently drop the tail.
    cleaned: list[str] = []
    for s in symbols:
        if not s:
            continue
        stripped = s.strip()
        if stripped:
            cleaned.append(stripped.upper())
    if not cleaned:
        return []

    if benzinga_provider() == "massive":
        results_m: list[dict[str, Any]] = []
        with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
            for start in range(0, len(cleaned), 50):  # keep bz-direct chunking symmetry
                chunk = cleaned[start : start + 50]
                rows = _massive_snapshot_tickers(
                    client,
                    f"{MASSIVE_SNAPSHOT_BASE}/tickers",
                    {"apiKey": api_key, "tickers": ",".join(chunk)},
                    label=f"Massive quotes chunk {start}-{start + len(chunk)}",
                )
                results_m.extend(_massive_snapshot_to_quote(t) for t in rows if isinstance(t, dict))
        return results_m

    chunk_size = 50
    quotes_raw: list[dict[str, Any]] = []
    with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as client:
        for start in range(0, len(cleaned), chunk_size):
            chunk = cleaned[start : start + chunk_size]
            sym_str = ",".join(chunk)
            try:
                r = _request_with_retry(client, QUOTES_URL, {
                    "token": api_key,
                    "symbols": sym_str,
                }, label="Benzinga quotes")
                data = r.json()
            except BenzingaEndpointDisabledError as exc:
                # Endpoint marked disabled (tier-limited 4xx); subsequent
                # chunks would raise immediately. Leave a debug breadcrumb
                # here and break out rather than fast-failing every remaining
                # chunk. The operator-visible disable event is logged by the
                # code that marks the endpoint disabled; log_fetch_warning
                # short-circuits BenzingaEndpointDisabledError to DEBUG.
                log_fetch_warning(
                    f"Benzinga quotes chunk {start}-{start + len(chunk)} (debug: endpoint already disabled)",
                    exc,
                )
                break
            except Exception as exc:
                log_fetch_warning(
                    f"Benzinga quotes chunk {start}-{start + len(chunk)}", exc
                )
                continue
            if isinstance(data, dict):
                quotes_raw.extend(data.get("quotes", []) or [])
            elif isinstance(data, list):
                quotes_raw.extend(data)

    # Flatten the nested {security, quote} structure
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
