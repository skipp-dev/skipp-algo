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
import random
import ssl
import threading
import time
import urllib.error
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from smc_core.resilient import resilient

logger = logging.getLogger(__name__)

# Lane 5 (provider-boundary audit, 2026-04-27): the helpers below
# silently swallow ``RuntimeError`` raised by ``_get`` and return an
# empty result so that downstream pipelines can degrade gracefully.
# That degradation was *too* graceful — the failure was completely
# invisible in logs, masking endpoint deprecations, network outages,
# and quota exhaustion. ``_log_endpoint_failure_once`` emits a single
# ``logger.warning`` per ``(endpoint, exception-type)`` per process so
# the failure is surfaced exactly once instead of either spamming or
# disappearing.
_LOGGED_SILENT_FAILURES: set[tuple[str, str]] = set()

# Audit #2670 W10: the one-shot log above surfaces the FIRST failure but
# callers still cannot distinguish "endpoint returned no data" from
# "fetch failed and was swallowed". This counter tracks EVERY swallowed
# failure per endpoint so health checks and tests can quantify
# degradation programmatically without changing the return contract.
_SILENT_FAILURE_COUNTS: dict[str, int] = {}
_silent_failure_lock = threading.Lock()


def get_silent_failure_counts() -> dict[str, int]:
    """Snapshot of per-endpoint counts of silently-swallowed fetch failures.

    A non-zero count for an endpoint means at least one ``RuntimeError``
    from ``_get`` was converted into an empty result (``[]`` / ``{}``)
    during this process's lifetime — i.e. empty results from that
    endpoint are ambiguous and may mean "fetch failed", not "no data".
    """
    with _silent_failure_lock:
        return dict(_SILENT_FAILURE_COUNTS)


def _log_endpoint_failure_once(endpoint: str, exc: BaseException) -> None:
    """Emit a one-shot warning for an FMP endpoint that silently degraded."""
    key = (endpoint, type(exc).__name__)
    with _silent_failure_lock:
        _SILENT_FAILURE_COUNTS[endpoint] = _SILENT_FAILURE_COUNTS.get(endpoint, 0) + 1
        if key in _LOGGED_SILENT_FAILURES:
            return
        _LOGGED_SILENT_FAILURES.add(key)
    logger.warning(
        "FMP %s degraded silently (%s: %s); returning empty result. "
        "Subsequent failures of the same kind will not be re-logged.",
        endpoint,
        type(exc).__name__,
        exc,
    )

def _normalise_analyst_estimates_period(period: object) -> str:
    """Normalise ``period`` to a value the FMP /stable/analyst-estimates endpoint accepts.

    The endpoint rejects anything other than ``annual`` or ``quarterly`` with HTTP 400.
    Historical callers (and the FMP docs for sibling endpoints) use ``quarter``; we
    coerce that — and any blank value — to a valid form so live callers do not silently
    return an empty list. Anything starting with 'q' (case-insensitive) becomes
    ``quarterly``; everything else (including blank) becomes ``annual``.
    """
    text = str(period).strip().lower() if period is not None else ""
    if text.startswith("q"):
        return "quarterly"
    return "annual"


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


def _parse_retry_after_seconds(raw_value: Any) -> float | None:
    """Parse an HTTP ``Retry-After`` header value into seconds.

    Accepts both the integer-seconds form (``"30"``) and the
    HTTP-date form (``"Wed, 21 Oct 2026 07:28:00 GMT"``) per RFC 9110
    §10.2.3. Returns ``None`` for empty / unparseable input so the
    caller can fall back to its own backoff schedule.
    """
    if raw_value is None or raw_value == "":
        return None
    try:
        seconds = float(raw_value)
    except (TypeError, ValueError):
        seconds = None
    if seconds is not None:
        # Reject NaN / +inf / -inf so callers fall through to the
        # default backoff instead of attempting time.sleep(nan), which
        # raises ``ValueError: Invalid value NaN`` on CPython.
        if math.isnan(seconds) or math.isinf(seconds):
            return None
        return max(seconds, 0.0)
    try:
        parsed = parsedate_to_datetime(str(raw_value))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds()
    if math.isnan(delta) or math.isinf(delta):
        return None
    return max(delta, 0.0)


def _today_et() -> date:
    return datetime.now(UTC).astimezone(_US_EASTERN).date()


def _prev_trading_day(day: date) -> date:
    probe = day
    for _ in range(10):
        probe = date.fromordinal(probe.toordinal() - 1)
        if probe.weekday() < 5:
            return probe
    raise RuntimeError(f"no trading day found within 10 days before {day}")


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

        Lane 9 (provider-boundary audit, 2026-04-27): when the provider
        returns ``Retry-After`` (most commonly on HTTP 429), respect it
        by waiting at least the suggested duration before the next
        attempt. The hint is captured into a closure variable on each
        failed attempt and consulted by the custom sleeper passed to
        ``@resilient`` so we never busy-retry against a server that has
        explicitly told us to back off.
        """
        query = {k: v for k, v in params.items() if v is not None}
        query.setdefault("apikey", self.api_key)
        url = f"{_BASE_URL}{path}?{urlencode(query, doseq=True)}"
        request = Request(url, headers={"User-Agent": "skipp-algo/1.0"})

        # Lane 9: closure-stored Retry-After hint, refreshed by each
        # failed attempt and consumed (then cleared) by ``_sleep``.
        retry_after_hint: list[float] = []

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
                    headers = getattr(exc, "headers", None) or {}
                    hint = _parse_retry_after_seconds(
                        headers.get("Retry-After") if hasattr(headers, "get") else None
                    )
                    if hint is not None:
                        retry_after_hint.append(hint)
                    raise  # let @resilient retry
                # Non-retriable HTTP code → fail fast as before.
                raise RuntimeError(f"FMP HTTP {exc.code} on {path}") from exc

        def _on_failure(exc: BaseException) -> Any:
            if isinstance(exc, urllib.error.HTTPError):
                raise RuntimeError(f"FMP HTTP {exc.code} on {path}") from exc
            raise RuntimeError(f"FMP network error on {path}: {exc}") from exc

        def _delay_from_exc(exc: BaseException) -> float | None:
            """Surface the captured ``Retry-After`` hint to ``@resilient``.

            Returning a non-``None`` value routes through the override
            branch of ``smc_core.resilient``, which sets the next delay
            to ``min(hint, max_delay)`` *independently* of the jitter
            RNG. This guarantees the hint is honored even when the
            full-jitter ``capped * rng()`` would otherwise land on 0
            (which would skip ``_sleep`` entirely and silently drop the
            hint). ``None`` falls back to the default jittered delay.
            """
            if not retry_after_hint:
                return None
            return retry_after_hint.pop(0)

        def _sleep(delay: float) -> None:
            time.sleep(delay)

        # Build the decorator per-call so the runtime ``retry_attempts``
        # field stays honored. ``retries`` is *additional* attempts after
        # the first one, hence ``retry_attempts - 1`` (clamped to 0).
        max_extra = max(self.retry_attempts - 1, 0)
        wrapped = resilient(
            retries=max_extra,
            base_delay=0.5,
            # Cap covers normal rate-limit cooldowns; ``delay_from_exc``
            # routes any honored ``Retry-After`` through this same cap.
            max_delay=60.0,
            exceptions=(urllib.error.URLError,),  # covers HTTPError too
            on_failure=_on_failure,
            sleep=_sleep,
            delay_from_exc=_delay_from_exc,
            # Resolve ``random.random`` at call time (not at decorator
            # default-argument evaluation time) so tests can pin the
            # jitter via ``monkeypatch.setattr("random.random", ...)``.
            rng=random.random,
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
        except RuntimeError as exc:
            _log_endpoint_failure_once("/stable/quote", exc)
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
        except RuntimeError as exc:
            _log_endpoint_failure_once("/stable/profile", exc)
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
        period: str = "annual",
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        requested_symbol = str(symbol).strip().upper()
        if not requested_symbol:
            return []
        params = {
            "symbol": requested_symbol,
            "period": _normalise_analyst_estimates_period(period),
            "limit": max(int(limit), 1),
        }
        try:
            data = self._get("/stable/analyst-estimates", params)
        except RuntimeError as exc:
            _log_endpoint_failure_once("/stable/analyst-estimates", exc)
            return []
        return list(data) if isinstance(data, list) else []

    def get_ratios_ttm(self, symbol: str) -> list[dict[str, Any]]:
        requested_symbol = str(symbol).strip().upper()
        if not requested_symbol:
            return []
        try:
            data = self._get("/stable/ratios-ttm", {"symbol": requested_symbol})
        except RuntimeError as exc:
            _log_endpoint_failure_once("/stable/ratios-ttm", exc)
            return []
        return list(data) if isinstance(data, list) else []

    def get_key_metrics_ttm(self, symbol: str) -> list[dict[str, Any]]:
        requested_symbol = str(symbol).strip().upper()
        if not requested_symbol:
            return []
        try:
            data = self._get("/stable/key-metrics-ttm", {"symbol": requested_symbol})
        except RuntimeError as exc:
            _log_endpoint_failure_once("/stable/key-metrics-ttm", exc)
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
                analyst_estimates = self.get_analyst_estimates(candidate_symbol, period="annual", limit=4)
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
        except RuntimeError as exc:
            _log_endpoint_failure_once("/stable/news/stock-latest", exc)
            return []
        return list(data) if isinstance(data, list) else []

    def get_earnings_calendar(
        self, from_date: date, to_date: date,
    ) -> list[dict[str, Any]]:
        params = {"from": from_date.isoformat(), "to": to_date.isoformat()}
        try:
            data = self._get("/stable/earnings-calendar", params)
        except RuntimeError as exc:
            _log_endpoint_failure_once("/stable/earnings-calendar", exc)
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

    def get_treasury_yields(self) -> dict[str, Any]:
        """Fetch most recent US Treasury yields for 2Y and 10Y.

        Uses FMP ``/stable/treasury-rates`` endpoint (the legacy
        ``/stable/treasury`` path was retired and now returns HTTP 404).
        Returns ``{"2y": float, "10y": float, "spread": float, "inverted": bool}``.

        Lane 6 (2026-04-27) — weekend-naive guard: querying a single
        ``today`` date returns an empty list on Saturdays, Sundays, and
        US market holidays (Treasury rates are only published on
        trading days). To avoid silently degrading to zero yields on
        non-trading days, query a 7-day rolling window and pick the
        most recent row.
        """
        today = _today_et()
        # 7-day window safely covers a 3-day weekend + observed federal
        # holiday (e.g. Thanksgiving Thu/Fri + weekend = up to 4
        # consecutive non-trading days). Rates list is descending by
        # date, so element 0 is the latest published trading day.
        window_start = today - timedelta(days=7)
        try:
            data = self._get(
                "/stable/treasury-rates",
                {"from": window_start.isoformat(), "to": today.isoformat()},
            )
            if data and isinstance(data, list) and len(data) > 0:
                latest = data[0]
                y2 = _coerce_finite_float(latest.get("year2")) or 0.0
                y10 = _coerce_finite_float(latest.get("year10")) or 0.0
                spread = round(y10 - y2, 4)
                return {"2y": round(y2, 4), "10y": round(y10, 4), "spread": spread, "inverted": spread < 0}
        except Exception as exc:
            _log_endpoint_failure_once("/stable/treasury-rates", exc)
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
            except Exception as exc:
                _log_endpoint_failure_once(
                    "/stable/institutional-ownership/symbol-positions-summary", exc
                )
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
        except Exception as exc:
            _log_endpoint_failure_once("/stable/insider-trading/search", exc)
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
        except RuntimeError as exc:
            _log_endpoint_failure_once(
                f"/stable/technical-indicators/{indicator_type}", exc
            )
            return {}
        if isinstance(data, dict):
            return dict(data)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict):
                    return dict(row)
        return {}
