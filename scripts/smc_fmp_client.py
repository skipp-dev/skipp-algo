"""Thin standalone FMP client for the v4 enrichment pipeline.

Covers the core FMP API methods consumed by ``smc_provider_policy``
adapters plus the best-effort market-P/E helper used by the active
production path. Uses only stdlib (``urllib``, ``json``, ``ssl``) so it
has **zero** runtime dependency on ``open_prep``.

The interface is method-compatible with ``open_prep.macro.FMPClient``
for the subset used by the v4 path — existing adapter code in
``smc_provider_policy.py`` works unchanged.
"""

from __future__ import annotations

import json
import logging
import math
import ssl
import time
import urllib.error
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from smc_core.resilient import resilient

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com"
# HTTP status codes worth a retry. Anything else is treated as fatal so
# we don't silently swallow auth/404 problems via the @resilient pilot.
_RETRIABLE_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})
_US_EASTERN = ZoneInfo("America/New_York")
_MARKET_PE_FORWARD_SYMBOL = "SPY"
_MARKET_PE_FORWARD_FALLBACK_SYMBOLS: tuple[str, ...] = (
    "SPY",
    "IVV",
    "VOO",
    "QQQ",
    "DIA",
    "^GSPC",
    "AAPL",
    "MSFT",
)
_DIRECT_FORWARD_PE_FIELDS: tuple[str, ...] = (
    "forwardPE",
    "forwardPe",
    "forwardPERatio",
    "forwardPeRatio",
    "priceToEarningsForward",
    "priceToEarningsRatioForward",
    "peForward",
)
_APPROXIMATE_PE_FIELDS: tuple[str, ...] = (
    "pe",
    "trailingPE",
    "priceEarningsRatioTTM",
    "priceToEarningsRatioTTM",
    "peRatioTTM",
    "peTTM",
)


def _build_tls_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def _today_et() -> date:
    return datetime.now(timezone.utc).astimezone(_US_EASTERN).date()


def _prev_trading_day(day: date) -> date:
    probe = day
    while True:
        probe = date.fromordinal(probe.toordinal() - 1)
        if probe.weekday() < 5:
            return probe


def _coerce_finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _aggregate_sector_snapshot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sector_totals: dict[str, list[float]] = {}
    for row in rows:
        sector = str(row.get("sector") or "").strip()
        if not sector:
            continue
        change = _coerce_finite_float(row.get("averageChange"))
        if change is None:
            change = _coerce_finite_float(row.get("changesPercentage"))
        if change is None:
            continue
        sector_totals.setdefault(sector, []).append(change)

    aggregated: list[dict[str, Any]] = []
    for sector, changes in sector_totals.items():
        aggregated.append(
            {"sector": sector, "changesPercentage": round(sum(changes) / len(changes), 4)}
        )
    return aggregated


@dataclass
class SMCFMPClient:
    """Minimal FMP client for the v4 enrichment pipeline.

    Drop-in replacement for the core methods that
    ``smc_provider_policy`` adapters call, plus a best-effort
    market-P/E helper for the active production path.
    """

    api_key: str
    retry_attempts: int = 2
    timeout_seconds: float = 12.0
    _last_sector_performance_diagnostics: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _last_macro_calendar_diagnostics: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _last_market_pe_forward_diagnostics: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    # ── HTTP layer ──────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        """E-3 migration: bounded retry via ``smc_core.resilient``.

        The previous hand-rolled loop used linear backoff
        (``0.5 * (attempt + 1)``) over the same retriable HTTP code set.
        ``@resilient`` provides bounded **exponential** backoff with full
        jitter and a single tested retry primitive across adapters.

        Semantics preserved:

        * Number of attempts honors instance-level
          ``self.retry_attempts`` (1 → no retries, 2 → one retry, …).
        * Only ``429 / 500 / 502 / 503 / 504`` and pure ``URLError`` are
          retried; ``404 / 401 / 403`` propagate immediately as fatal
          ``RuntimeError``.
        * After all retries are exhausted the call still raises
          ``RuntimeError`` (`on_failure` re-wraps the last exception),
          keeping the existing error contract consumers depend on.
        """
        query = {k: v for k, v in params.items() if v is not None}
        query.setdefault("apikey", self.api_key)
        url = f"{_BASE_URL}{path}?{urlencode(query, doseq=True)}"
        request = Request(url, headers={"User-Agent": "skipp-algo/1.0"})

        def _do_request() -> Any:
            try:
                with urlopen(
                    request,
                    timeout=self.timeout_seconds,
                    context=_build_tls_context(),
                ) as resp:
                    payload = resp.read().decode("utf-8")
                return self._parse(path, payload)
            except urllib.error.HTTPError as exc:
                if exc.code in _RETRIABLE_HTTP_CODES:
                    raise  # let @resilient retry
                # Non-retriable HTTP code → fail fast as before.
                raise RuntimeError(f"FMP HTTP {exc.code} on {path}") from exc

        def _on_failure(exc: BaseException) -> Any:
            if isinstance(exc, urllib.error.HTTPError):
                raise RuntimeError(f"FMP HTTP {exc.code} on {path}") from exc
            raise RuntimeError(f"FMP network error on {path}: {exc}") from exc

        # Build the decorator per-call so the runtime ``retry_attempts``
        # field stays honored. ``retries`` is *additional* attempts after
        # the first one, hence ``retry_attempts - 1`` (clamped to 0).
        max_extra = max(self.retry_attempts - 1, 0)
        wrapped = resilient(
            retries=max_extra,
            base_delay=0.5,
            max_delay=4.0,
            exceptions=(urllib.error.URLError,),  # covers HTTPError too
            on_failure=_on_failure,
            # Late-bound sleep lookup so test fixtures that monkey-patch
            # ``time.sleep`` after this module is imported still observe
            # the call (the decorator's default would otherwise capture
            # the original reference at construction time).
            sleep=lambda delay: time.sleep(delay),
        )(_do_request)
        return wrapped()

    @staticmethod
    def _parse(path: str, payload: str) -> Any:
        text = payload.strip()
        if text.lower().startswith("<!doctype") or text.lower().startswith("<html"):
            raise RuntimeError(f"FMP returned HTML on {path}")
        data = json.loads(text)
        if isinstance(data, dict) and str(data.get("status") or "").lower() == "error":
            raise RuntimeError(
                f"FMP error on {path}: {data.get('message', 'unknown')}"
            )
        return data

    # ── Pipeline methods (interface matches open_prep.macro.FMPClient) ──

    def get_index_quote(self, symbol: str = "^VIX") -> dict[str, Any]:
        sym = symbol.strip().upper()
        try:
            data = self._get("/stable/quote", {"symbol": sym})
        except RuntimeError:
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and str(row.get("symbol", "")).upper() == sym:
                    return dict(row)
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        requested_symbol = str(symbol).strip().upper()
        if not requested_symbol:
            return {}
        try:
            data = self._get("/stable/profile", {"symbol": requested_symbol})
        except RuntimeError:
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                if str(row.get("symbol") or "").strip().upper() == requested_symbol:
                    return dict(row)
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}

    def get_analyst_estimates(
        self,
        symbol: str,
        *,
        period: str = "quarter",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        requested_symbol = str(symbol).strip().upper()
        if not requested_symbol:
            return []
        params = {
            "symbol": requested_symbol,
            "period": str(period).strip() or "quarter",
            "limit": max(int(limit), 1),
        }
        try:
            data = self._get("/stable/analyst-estimates", params)
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_ratios_ttm(self, symbol: str) -> list[dict[str, Any]]:
        requested_symbol = str(symbol).strip().upper()
        if not requested_symbol:
            return []
        try:
            data = self._get("/stable/ratios-ttm", {"symbol": requested_symbol})
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_key_metrics_ttm(self, symbol: str) -> list[dict[str, Any]]:
        requested_symbol = str(symbol).strip().upper()
        if not requested_symbol:
            return []
        try:
            data = self._get("/stable/key-metrics-ttm", {"symbol": requested_symbol})
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_market_pe_forward(self, symbol: str | None = None) -> float | None:
        requested_symbol = str(symbol or _MARKET_PE_FORWARD_SYMBOL).strip().upper() or _MARKET_PE_FORWARD_SYMBOL
        candidate_symbols: list[str] = []
        for candidate in ((requested_symbol,) if symbol else _MARKET_PE_FORWARD_FALLBACK_SYMBOLS):
            normalized = str(candidate or "").strip().upper()
            if normalized and normalized not in candidate_symbols:
                candidate_symbols.append(normalized)
        diagnostics: dict[str, Any] = {
            "status": "unavailable",
            "requested_symbol": requested_symbol,
            "symbol": requested_symbol,
            "source_symbol": "",
            "attempted_symbols": list(candidate_symbols),
            "source_category": "unavailable",
            "field": "",
            "price": None,
            "forward_eps": None,
            "estimate_count": 0,
            "error": "",
        }

        for candidate_symbol in candidate_symbols:
            diagnostics["symbol"] = candidate_symbol
            diagnostics["source_symbol"] = candidate_symbol
            diagnostics["price"] = None
            diagnostics["forward_eps"] = None
            diagnostics["estimate_count"] = 0
            diagnostics["field"] = ""
            diagnostics["error"] = ""
            diagnostics["source_category"] = "unavailable"
            diagnostics["status"] = "unavailable"

            try:
                quote = self.get_index_quote(candidate_symbol)
                profile = self.get_company_profile(candidate_symbol)
                ratios_rows = self.get_ratios_ttm(candidate_symbol)
                ratios = dict(ratios_rows[0]) if ratios_rows and isinstance(ratios_rows[0], dict) else {}
                key_metrics_rows = self.get_key_metrics_ttm(candidate_symbol)
                key_metrics = dict(key_metrics_rows[0]) if key_metrics_rows and isinstance(key_metrics_rows[0], dict) else {}
                analyst_estimates = self.get_analyst_estimates(candidate_symbol, period="quarter", limit=4)
            except Exception as exc:
                diagnostics["status"] = "error"
                diagnostics["error"] = str(exc)
                self._last_market_pe_forward_diagnostics = dict(diagnostics)
                return None

            price = next(
                (
                    numeric
                    for numeric in (
                        _coerce_finite_float(quote.get("price")),
                        _coerce_finite_float(profile.get("price")),
                        _coerce_finite_float(quote.get("previousClose")),
                    )
                    if numeric is not None and numeric > 0
                ),
                None,
            )
            diagnostics["price"] = price

            for field_name in _DIRECT_FORWARD_PE_FIELDS:
                value = next(
                    (
                        numeric
                        for numeric in (
                            _coerce_finite_float(quote.get(field_name)),
                            _coerce_finite_float(profile.get(field_name)),
                            _coerce_finite_float(ratios.get(field_name)),
                            _coerce_finite_float(key_metrics.get(field_name)),
                        )
                        if numeric is not None and numeric > 0
                    ),
                    None,
                )
                if value is None:
                    continue
                diagnostics["status"] = "ok"
                diagnostics["source_category"] = "direct_forward"
                diagnostics["field"] = field_name
                self._last_market_pe_forward_diagnostics = dict(diagnostics)
                return value

            forward_eps_components = [
                numeric
                for numeric in (
                    _coerce_finite_float(row.get("epsAvg"))
                    for row in analyst_estimates
                    if isinstance(row, dict)
                )
                if numeric is not None and numeric > 0
            ]
            diagnostics["estimate_count"] = len(forward_eps_components)
            if price is not None and len(forward_eps_components) >= 4:
                forward_eps = sum(forward_eps_components[:4])
                diagnostics["forward_eps"] = forward_eps
                if forward_eps > 0:
                    diagnostics["status"] = "ok"
                    diagnostics["source_category"] = "analyst_derived"
                    diagnostics["field"] = "epsAvg"
                    self._last_market_pe_forward_diagnostics = dict(diagnostics)
                    return price / forward_eps

            for field_name in _APPROXIMATE_PE_FIELDS:
                value = next(
                    (
                        numeric
                        for numeric in (
                            _coerce_finite_float(quote.get(field_name)),
                            _coerce_finite_float(profile.get(field_name)),
                            _coerce_finite_float(ratios.get(field_name)),
                            _coerce_finite_float(key_metrics.get(field_name)),
                        )
                        if numeric is not None and numeric > 0
                    ),
                    None,
                )
                if value is None:
                    continue
                diagnostics["status"] = "ok"
                diagnostics["source_category"] = "approximate_ttm"
                diagnostics["field"] = field_name
                self._last_market_pe_forward_diagnostics = dict(diagnostics)
                return value

        self._last_market_pe_forward_diagnostics = diagnostics
        return None

    def get_sector_performance(self) -> list[dict[str, Any]]:
        today = _today_et()
        diagnostics: dict[str, Any] = {
            "status": "pending",
            "source_endpoint": "/stable/sector-performance-snapshot",
            "attempted_dates": [],
            "row_counts": {},
            "used_fallback_previous_trading_day": False,
            "selected_date": "",
            "raw_row_count": 0,
            "returned_row_count": 0,
            "error": "",
        }
        query_date = today
        for attempt in range(6):
            diagnostics["attempted_dates"].append(query_date.isoformat())
            if attempt > 0:
                diagnostics["used_fallback_previous_trading_day"] = True
            try:
                data = self._get(
                    "/stable/sector-performance-snapshot",
                    {"date": query_date.isoformat()},
                )
            except RuntimeError as exc:
                diagnostics["status"] = "error"
                diagnostics["error"] = str(exc)
                self._last_sector_performance_diagnostics = diagnostics
                return []

            raw_rows = list(data) if isinstance(data, list) else []
            diagnostics["row_counts"][query_date.isoformat()] = len(raw_rows)
            rows = _aggregate_sector_snapshot_rows(raw_rows)
            if rows:
                diagnostics["status"] = "ok"
                diagnostics["selected_date"] = query_date.isoformat()
                diagnostics["raw_row_count"] = len(raw_rows)
                diagnostics["returned_row_count"] = len(rows)
                self._last_sector_performance_diagnostics = diagnostics
                return rows
            query_date = _prev_trading_day(query_date)

        diagnostics["status"] = "empty"
        self._last_sector_performance_diagnostics = diagnostics
        return []

    def get_stock_latest_news(
        self, *, symbol: str | None = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": max(int(limit), 1)}
        if symbol:
            params["symbol"] = symbol.strip().upper()
        try:
            data = self._get("/stable/news/stock-latest", params)
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_earnings_calendar(
        self, from_date: date, to_date: date,
    ) -> list[dict[str, Any]]:
        params = {"from": from_date.isoformat(), "to": to_date.isoformat()}
        try:
            data = self._get("/stable/earnings-calendar", params)
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

    def get_macro_calendar(
        self, date_from: date, date_to: date,
    ) -> list[dict[str, Any]]:
        params = {"from": date_from.isoformat(), "to": date_to.isoformat()}
        try:
            data = self._get("/stable/economic-calendar", params)
        except RuntimeError as exc:
            self._last_macro_calendar_diagnostics = {
                "status": "error",
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
                "returned_row_count": 0,
                "error": str(exc),
            }
            return []
        rows = list(data) if isinstance(data, list) else []
        self._last_macro_calendar_diagnostics = {
            "status": "ok",
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "returned_row_count": len(rows),
            "error": "",
        }
        return rows

    def get_short_interest(self, symbols: list[str]) -> dict[str, float]:
        """Fetch short interest as % of float for a list of symbols.

        DEPRECATED (Lane 1, 2026-04-27): The FMP ``/stable/short-interest``
        endpoint has been fully retired (returns HTTP 404 with empty
        body). FMP no longer publishes a 1:1 replacement under
        ``/stable``; callers must treat short-interest enrichment as
        unavailable and degrade gracefully.

        This method now returns ``{}`` immediately and logs a one-shot
        warning so the failure is visible rather than silently producing
        empty enrichment fields.
        """
        if not getattr(self, "_short_interest_deprecation_logged", False):
            logger.warning(
                "FMP /stable/short-interest endpoint retired; "
                "short_interest enrichment is unavailable. Returning empty mapping."
            )
            self._short_interest_deprecation_logged = True
        return {}

    def get_treasury_yields(self) -> dict[str, Any]:
        """Fetch current US Treasury yields for 2Y and 10Y.

        Uses FMP ``/stable/treasury-rates`` endpoint (the legacy
        ``/stable/treasury`` path was retired and now returns HTTP 404).
        Returns ``{"2y": float, "10y": float, "spread": float, "inverted": bool}``.
        """
        today = _today_et()
        try:
            data = self._get(
                "/stable/treasury-rates",
                {"from": today.isoformat(), "to": today.isoformat()},
            )
            if data and isinstance(data, list) and len(data) > 0:
                latest = data[0]
                y2 = _coerce_finite_float(latest.get("year2")) or 0.0
                y10 = _coerce_finite_float(latest.get("year10")) or 0.0
                spread = round(y10 - y2, 4)
                return {"2y": round(y2, 4), "10y": round(y10, 4), "spread": spread, "inverted": spread < 0}
        except Exception:
            pass
        return {"2y": 0.0, "10y": 0.0, "spread": 0.0, "inverted": False}

    def get_institutional_holders(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch institutional ownership summary for a symbol.

        Uses FMP ``/stable/institutional-ownership/symbol-positions-summary``
        (the legacy ``/stable/institutional-holder`` per-row endpoint was
        retired and now returns HTTP 404).

        The new endpoint returns one *aggregated* row per (symbol, year,
        quarter) with ``numberOf13Fshares`` (current) and
        ``lastNumberOf13Fshares`` (previous quarter). To preserve the
        existing ``[{shares, previousShares}]`` shape that callers in
        ``smc_institutional_enrichment`` consume, we map the aggregated
        row to a single-element list with those legacy field names.

        Walks back at most 4 quarters from "current" until a quarter
        with data is found, then returns the most recent.
        """
        sym = str(symbol).strip().upper()
        if not sym:
            return []
        today = _today_et()
        # Most recent reported quarter is typically last quarter or two
        # ago (13F filings lag ~45 days). Walk back from current quarter.
        year = today.year
        quarter = (today.month - 1) // 3 + 1
        for _ in range(4):
            try:
                data = self._get(
                    "/stable/institutional-ownership/symbol-positions-summary",
                    {"symbol": sym, "year": year, "quarter": quarter},
                )
            except Exception:
                data = None
            if data and isinstance(data, list) and len(data) > 0:
                row = data[0]
                cur = _coerce_finite_float(row.get("numberOf13Fshares"))
                prev = _coerce_finite_float(row.get("lastNumberOf13Fshares"))
                if cur is not None and prev is not None:
                    return [{"shares": int(cur), "previousShares": int(prev)}]
            # Walk back one quarter.
            quarter -= 1
            if quarter == 0:
                quarter = 4
                year -= 1
        return []

    def get_insider_trading(self, symbol: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch recent insider transactions for a symbol.

        Uses FMP ``/stable/insider-trading/search`` endpoint (the legacy
        ``/stable/insider-trading`` symbol-filtered path was retired and
        now returns HTTP 404).
        """
        sym = str(symbol).strip().upper()
        if not sym:
            return []
        try:
            data = self._get(
                "/stable/insider-trading/search",
                {"symbol": sym, "limit": max(int(limit), 1)},
            )
            return list(data) if isinstance(data, list) else []
        except Exception:
            return []

    def get_technical_indicator(
        self,
        symbol: str,
        timeframe: str,
        indicator_type: str,
        *,
        indicator_period: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbol": symbol.strip().upper(),
            "timeframe": timeframe.strip(),
        }
        if indicator_period is not None:
            params["periodLength"] = int(indicator_period)
        try:
            data = self._get(
                f"/stable/technical-indicators/{indicator_type}", params,
            )
        except RuntimeError:
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}
