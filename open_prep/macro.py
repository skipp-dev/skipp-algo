from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import ssl
import threading
import time
import urllib.error
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi

logger = logging.getLogger("open_prep.macro")

_APIKEY_RE = re.compile(r"(apikey|token)=[^&\s]+", re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════════
# #5  Circuit Breaker — prevents hammering FMP during outages
# ═══════════════════════════════════════════════════════════════════════════

class CircuitBreaker:
    """State-machine circuit breaker for FMP API calls.

    States:
      CLOSED  — normal operation; failures increment counter.
      OPEN    — requests are immediately rejected; waits for recovery_timeout.
      HALF_OPEN — permits a single test request to decide next state.

    After *failure_threshold* consecutive failures the circuit opens.
    After *recovery_timeout* seconds it transitions to half-open; a single
    successful request re-closes it, a failure re-opens it.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._state: str = "CLOSED"         # "CLOSED" | "OPEN" | "HALF_OPEN"
        self._consecutive_failures: int = 0
        self._opened_at: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == "OPEN":
                if time.time() - self._opened_at >= self._recovery_timeout:
                    self._state = "HALF_OPEN"
            return self._state

    def allow_request(self) -> bool:
        """Return True if the request should be attempted.

        In HALF_OPEN state, only the first caller is permitted through;
        subsequent callers are rejected until a success/failure is recorded.
        """
        with self._lock:
            # Inline the OPEN→HALF_OPEN transition to avoid releasing the lock
            if self._state == "OPEN":
                if time.time() - self._opened_at >= self._recovery_timeout:
                    self._state = "HALF_OPEN"
            if self._state == "CLOSED":
                return True
            if self._state == "HALF_OPEN":
                # Atomically claim the single test slot
                self._state = "HALF_OPEN_TESTING"
                return True
            return False  # OPEN or HALF_OPEN_TESTING

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            if self._state in ("HALF_OPEN", "HALF_OPEN_TESTING", "OPEN"):
                logger.info("Circuit breaker: CLOSED (recovered)")
            self._state = "CLOSED"

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._state in ("HALF_OPEN", "HALF_OPEN_TESTING"):
                # Test request failed — re-open
                self._state = "OPEN"
                self._opened_at = time.time()
                logger.warning("Circuit breaker: OPEN (half-open test failed)")
            elif self._consecutive_failures >= self._failure_threshold:
                self._state = "OPEN"
                self._opened_at = time.time()
                logger.warning(
                    "Circuit breaker: OPEN after %d consecutive failures",
                    self._consecutive_failures,
                )

DEFAULT_HIGH_IMPACT_EVENTS: set[str] = {
    "CPI",
    "Core CPI",
    "PPI",
    "Core PPI",
    "Nonfarm Payrolls",
    "Unemployment Rate",
    "Average Hourly Earnings",
    "Retail Sales",
    "PCE",
    "Core PCE",
    "Personal Consumption Expenditures",
    "Initial Jobless Claims",
    "ISM Manufacturing PMI",
    "ISM Services PMI",
    "Philadelphia Fed Manufacturing Index",
    "JOLTS Job Openings",
    "GDP",
}

US_COUNTRY_CODES: set[str] = {"US", "USA", "UNITED STATES"}
US_CURRENCIES: set[str] = {"USD"}
HIGH_IMPACT_LEVELS: set[str] = {"high"}
MID_IMPACT_LEVELS: set[str] = {"medium", "mid", "moderate"}

HIGH_IMPACT_NAME_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("cpi",),
    ("consumer", "price", "index"),
    ("ppi",),
    ("producer", "price", "index"),
    ("nonfarm", "payroll"),
    ("unemployment", "rate"),
    ("average", "hourly", "earnings"),
    ("retail", "sales"),
    ("jobless", "claims"),
    ("initial", "claims"),
    ("ism", "manufacturing"),
    ("ism", "services"),
    ("philly", "fed"),
    ("philadelphia", "fed"),
    ("jolts",),
    ("job", "openings"),
    ("gross", "domestic", "product"),
    ("gdp",),
    ("pce",),
    ("personal", "consumption", "expenditures"),
)

MID_IMPACT_MACRO_NAME_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("ism", "manufacturing"),
    ("ism", "services"),
    ("philly", "fed"),
    ("philadelphia", "fed"),
    ("consumer", "sentiment"),
    ("consumer", "confidence"),
    ("inflation", "expectations"),
    ("new", "home", "sales"),
    ("existing", "home", "sales"),
    ("housing", "starts"),
    ("building", "permits"),
    ("durable", "goods"),
    ("factory", "orders"),
    ("leading", "indicators"),
    ("gdpnow",),
    ("atlanta", "fed", "gdpnow"),
)

MID_IMPACT_EXCLUDE_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("cftc",),
    ("speculative", "net", "positions"),
)

FORCED_HIGH_IMPACT_CANONICAL_KEYS: set[str] = {
    "core_pce_mom",
    "core_cpi_mom",
    "core_ppi_mom",
    "cpi_mom",
    "ppi_mom",
    "cpi",
    "core_cpi",
    "ppi",
    "core_ppi",
    "cpi_yoy",
    "core_cpi_yoy",
    "ppi_yoy",
    "core_ppi_yoy",
    "nfp",
    "unemployment",
    "hourly_earnings",
    "jobless_claims",
    "jolts",
    "ism",
    "philly_fed",
    "gdp_qoq",
    "retail_sales",
}

FORCED_MID_IMPACT_CANONICAL_KEYS: set[str] = {
    "pce_mom",
    "pmi_sp_global",
}

CONSENSUS_FIELD_CANDIDATES: tuple[str, ...] = (
    "consensus",
    "estimate",
    "forecast",
    "expected",
)


@dataclass(slots=True)
class FMPClient:
    """Minimal FMP client for economics calendar and quote snapshots."""

    # repr=False keeps the API key out of logs and tracebacks.
    api_key: str = field(repr=False)
    base_url: str = "https://financialmodelingprep.com"
    timeout_seconds: int = 20
    retry_attempts: int = 3
    retry_backoff_seconds: float = 1.0
    retry_backoff_max_seconds: float = 8.0
    # Cached once at construction; avoids re-parsing the CA bundle on every request.
    _ssl_ctx: ssl.SSLContext = field(init=False, repr=False)
    # #5 Circuit breaker — prevents hammering FMP during outages
    _circuit_breaker: CircuitBreaker = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        self._circuit_breaker = CircuitBreaker()

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff delay with ±25 % jitter (anti-thundering-herd)."""
        import random
        base = max(float(self.retry_backoff_seconds), 0.0)
        cap = max(float(self.retry_backoff_max_seconds), 0.0)
        delay = base * (2 ** max(attempt - 1, 0))
        delay = min(delay, cap)
        # Add ±25 % jitter so concurrent callers don't retry in lockstep
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return float(max(0.0, delay + jitter))

    @classmethod
    def from_env(cls, key_name: str = "FMP_API_KEY") -> FMPClient:
        value = os.environ.get(key_name)
        if not value:
            raise ValueError(
                f"Missing {key_name}. Add it to your shell or .env before running open prep."
            )
        return cls(api_key=value)

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        # ── #5 Circuit breaker check ──────────────────────────────
        if not self._circuit_breaker.allow_request():
            raise RuntimeError(
                f"FMP circuit breaker OPEN — request to {path} rejected. "
                f"Retry after {self._circuit_breaker._recovery_timeout}s."
            )

        query = dict(params)
        query["apikey"] = self.api_key
        url = f"{self.base_url}{path}?{urlencode(query)}"
        request = Request(url, headers={"Accept": "application/json"})
        attempts = max(int(self.retry_attempts), 1)
        transient_http_codes = {429, 500, 502, 503, 504}
        payload: str | None = None

        for attempt in range(1, attempts + 1):
            try:
                with urlopen(
                    request,
                    timeout=self.timeout_seconds,
                    context=self._ssl_ctx,
                ) as response:
                    payload = response.read().decode("utf-8")
                self._circuit_breaker.record_success()
                break
            except urllib.error.HTTPError as exc:
                should_retry = exc.code in transient_http_codes and attempt < attempts
                if should_retry:
                    time.sleep(self._backoff_delay(attempt))
                    continue
                try:
                    error_body = exc.read().decode("utf-8")
                    error_data = json.loads(error_body)
                    error_msg = error_data.get("Error Message") or error_data.get("message") or exc.reason
                except Exception:
                    error_msg = exc.reason
                # Client/plan/path errors (4xx) are not infrastructure outages.
                # Do not trip the global circuit breaker for these responses,
                # otherwise optional endpoint failures can block critical calls.
                if exc.code not in {400, 401, 402, 403, 404}:
                    self._circuit_breaker.record_failure()
                raise RuntimeError(
                    f"FMP API HTTP {exc.code} on {path}: {error_msg}"
                ) from exc
            except urllib.error.URLError as exc:
                # Catches timeout, DNS failure, connection reset, etc.
                # Never let the raw exception propagate — it contains the full URL
                # including the API key as a query parameter.
                if attempt < attempts:
                    time.sleep(self._backoff_delay(attempt))
                    continue
                self._circuit_breaker.record_failure()
                raise RuntimeError(
                    f"FMP API network error on {path}: {exc.reason}"
                ) from exc

        if payload is None:
            self._circuit_breaker.record_failure()
            raise RuntimeError(f"FMP API request failed on {path}: exhausted retries")

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            stripped = (payload or "").lstrip()

            # Detect HTML error pages (auth failure, maintenance, Cloudflare)
            _lower = stripped[:200].lower()
            if _lower.startswith("<!doctype") or _lower.startswith("<html") or _lower.startswith("<head"):
                raise RuntimeError(
                    f"FMP API returned HTML on {path} (likely auth/maintenance): "
                    f"{stripped[:120]!r}"
                ) from exc

            # FMP may return CSV even when JSON is requested (e.g. eod-bulk).
            # Detect CSV header and parse into list[dict] with numeric coercion.
            if stripped and (
                stripped.startswith('"') or stripped.startswith("symbol,")
            ):
                try:
                    reader = csv.DictReader(io.StringIO(payload))
                    rows: list[dict[str, Any]] = []
                    for csv_row in reader:
                        coerced: dict[str, Any] = {}
                        for k, v in csv_row.items():
                            if v is None:
                                coerced[k] = v
                                continue
                            try:
                                coerced[k] = int(v) if v.isdigit() else float(v)
                            except (ValueError, TypeError):
                                coerced[k] = v
                        rows.append(coerced)
                    data = rows
                except Exception:
                    raise RuntimeError(
                        f"FMP API returned invalid JSON on {path}: {payload[:100]}"
                    ) from exc
            else:
                raise RuntimeError(
                    f"FMP API returned invalid JSON on {path}: {payload[:100]}"
                ) from exc

        # FMP errors may be returned as dict payloads. Keep detection precise to
        # avoid false positives for successful payloads that include a generic
        # informational "message" field.
        if isinstance(data, dict):
            if "Error Message" in data:
                raise RuntimeError(f"FMP API error on {path}: {data}")
            status = str(data.get("status") or "").strip().lower()
            if status == "error":
                raise RuntimeError(f"FMP API error on {path}: {data}")
            if "message" in data and not any(
                key in data
                for key in (
                    "symbol",
                    "date",
                    "event",
                    "data",
                    "results",
                    "historical",
                    "financials",
                    "quotes",
                )
            ):
                raise RuntimeError(f"FMP API error on {path}: {data}")
        return data

    def get_macro_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        data = self._get(
            "/stable/economic-calendar",
            {"from": date_from.isoformat(), "to": date_to.isoformat()},
        )
        return data if isinstance(data, list) else []

    def get_batch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Fetch quotes for all symbols in a single batch request."""
        if not symbols:
            return []
        data = self._get("/stable/batch-quote", {"symbols": ",".join(symbols)})
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_fmp_articles(self, limit: int = 200) -> list[dict[str, Any]]:
        """Fetch latest cross-market articles from FMP stable endpoint.

        Note: this endpoint is not symbol-filtered; filtering is done locally
        using the article `tickers` metadata and title/content matching.
        """
        safe_limit = max(1, min(int(limit), 1000))
        data = self._get("/stable/fmp-articles", {"limit": safe_limit})
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_historical_price_eod_full(
        self,
        symbol: str,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        """Fetch full EOD history (OHLCV) from stable endpoint for one symbol."""
        data = self._get(
            "/stable/historical-price-eod/full",
            {
                "symbol": symbol,
                "from": date_from.isoformat(),
                "to": date_to.isoformat(),
            },
        )
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_premarket_movers(self) -> list[dict[str, Any]]:
        """Fetch top actively traded symbols from stable market performance API."""
        data = self._get("/stable/most-actives", {})
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_biggest_gainers(self) -> list[dict[str, Any]]:
        """Fetch top gainers from stable market performance API."""
        data = self._get("/stable/biggest-gainers", {})
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_biggest_losers(self) -> list[dict[str, Any]]:
        """Fetch top losers from stable market performance API."""
        data = self._get("/stable/biggest-losers", {})
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_batch_aftermarket_quote(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Fetch pre/post-market quotes for symbols from stable batch endpoint."""
        if not symbols:
            return []
        data = self._get("/stable/batch-aftermarket-quote", {"symbols": ",".join(symbols)})
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_batch_aftermarket_trade(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Fetch pre/post-market trades for symbols from stable batch endpoint."""
        if not symbols:
            return []
        data = self._get("/stable/batch-aftermarket-trade", {"symbols": ",".join(symbols)})
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_earnings_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        """Fetch earnings calendar for a date range."""
        try:
            data = self._get(
                "/stable/earnings-calendar",
                {"from": date_from.isoformat(), "to": date_to.isoformat()},
            )
        except RuntimeError as exc:
            msg = _APIKEY_RE.sub(r"\1=***", str(exc))
            if (
                "/stable/earnings-calendar" in msg
                and (
                    "HTTP 400" in msg
                    or "HTTP 402" in msg
                    or "HTTP 403" in msg
                    or "HTTP 404" in msg
                    or "circuit breaker OPEN" in msg
                )
            ):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_dividends_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        """Fetch dividends calendar for a date range."""
        data = self._get(
            "/stable/dividends-calendar",
            {"from": date_from.isoformat(), "to": date_to.isoformat()},
        )
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_splits_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        """Fetch stock splits calendar for a date range."""
        data = self._get(
            "/stable/splits-calendar",
            {"from": date_from.isoformat(), "to": date_to.isoformat()},
        )
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_ipos_calendar(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        """Fetch IPO calendar for a date range."""
        data = self._get(
            "/stable/ipos-calendar",
            {"from": date_from.isoformat(), "to": date_to.isoformat()},
        )
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_earnings_report(self, symbol: str, limit: int = 12) -> list[dict[str, Any]]:
        """Fetch company earnings report history from stable endpoint."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return []
        safe_limit = max(1, min(int(limit), 1000))
        data = self._get("/stable/earnings", {"symbol": sym, "limit": safe_limit})
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_price_target_summary(self, symbol: str) -> dict[str, Any]:
        """Fetch analyst price-target summary for a symbol."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return {}
        data = self._get("/stable/price-target-summary", {"symbol": sym})
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return {}

    def get_eod_bulk(self, as_of: date) -> list[dict[str, Any]]:
        """Fetch EOD bulk rows for a specific date."""
        try:
            data = self._get("/stable/eod-bulk", {"date": as_of.isoformat(), "datatype": "json"})
        except RuntimeError as exc:
            msg = _APIKEY_RE.sub(r"\1=***", str(exc))
            # Free-tier accounts can receive HTTP 402 (Payment Required) for this
            # endpoint.  FMP may also return CSV despite requesting JSON, which
            # triggers an "invalid JSON" error when CSV fallback parsing also
            # fails.  In both cases, degrade gracefully so callers can fall back
            # to per-symbol historical endpoint logic.
            if "/stable/eod-bulk" in msg and (
                "HTTP 402" in msg or "invalid JSON" in msg
            ):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_company_screener(
        self,
        *,
        country: str = "US",
        market_cap_more_than: float | int | None = None,
        exchange: str | None = "NASDAQ,NYSE,AMEX",
        is_etf: bool = False,
        is_fund: bool = False,
        limit: int = 1000,
        page: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch equity screener rows from FMP stable company screener."""
        params: dict[str, Any] = {
            "country": str(country).strip().upper(),
            "isEtf": "true" if is_etf else "false",
            "isFund": "true" if is_fund else "false",
            "isActivelyTrading": "true",
            "limit": max(1, min(int(limit), 1000)),
            "page": max(int(page), 0),
        }
        if exchange:
            params["exchange"] = str(exchange).strip().upper()
        if market_cap_more_than is not None:
            params["marketCapMoreThan"] = int(float(market_cap_more_than))

        data = self._get("/stable/company-screener", params)
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_intraday_chart(
        self,
        symbol: str,
        interval: str = "5min",
        day: date | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """Fetch intraday OHLCV bars from FMP stable endpoint.

        interval: "1min" or "5min" (recommend 5min for rate-safety).
        day: optional date filter; without it FMP returns the most recent bars.
        """
        sym = str(symbol or "").strip().upper()
        if not sym:
            return []
        safe_limit = max(1, min(int(limit), 5000))
        params: dict[str, Any] = {"symbol": sym, "limit": safe_limit}
        if day is not None:
            params["from"] = day.isoformat()
            params["to"] = day.isoformat()
        interval_clean = str(interval or "5min").strip().lower()
        data = self._get(f"/stable/historical-chart/{interval_clean}", params)
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_upgrades_downgrades(
        self,
        symbol: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch analyst upgrades/downgrades from FMP stable endpoint.

        Without a symbol, returns the latest analyst actions across all tickers.
        With date range, filters to that window.
        """
        params: dict[str, Any] = {}
        if symbol:
            sym = str(symbol).strip().upper()
            if sym:
                params["symbol"] = sym
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        try:
            data = self._get("/stable/grades", params)
        except RuntimeError as exc:
            msg = _APIKEY_RE.sub(r"\1=***", str(exc))
            if (
                "/stable/grades" in msg
                and (
                    "HTTP 400" in msg
                    or "HTTP 402" in msg
                    or "HTTP 403" in msg
                    or "HTTP 404" in msg
                    or "circuit breaker OPEN" in msg
                )
            ):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_sector_performance(self) -> list[dict[str, Any]]:
        """Fetch current sector performance snapshot from FMP stable endpoint."""
        from datetime import date as _date
        try:
            data = self._get("/stable/sector-performance-snapshot", {"date": _date.today().isoformat()})
        except RuntimeError as exc:
            msg = _APIKEY_RE.sub(r"\1=***", str(exc))
            if (
                "/stable/sector-performance-snapshot" in msg
                and (
                    "HTTP 400" in msg
                    or "HTTP 402" in msg
                    or "HTTP 403" in msg
                    or "HTTP 404" in msg
                    or "circuit breaker OPEN" in msg
                )
            ):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    # ------------------------------------------------------------------
    # New endpoints for v2 pipeline
    # ------------------------------------------------------------------

    def get_index_quote(self, symbol: str = "^VIX") -> dict[str, Any]:
        """Fetch a single index quote (e.g. ^VIX, ^GSPC).

        Returns the quote dict, or empty dict on failure.
        """
        sym = str(symbol or "^VIX").strip()
        try:
            data = self._get("/stable/quote", {"symbol": sym})
        except RuntimeError as exc:
            msg = _APIKEY_RE.sub(r"\1=***", str(exc))
            if "/stable/quote" in msg and (
                "HTTP 400" in msg
                or "HTTP 402" in msg
                or "HTTP 403" in msg
                or "HTTP 404" in msg
                or "circuit breaker OPEN" in msg
            ):
                return {}
            raise
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict) and data:
            return data
        return {}

    # ------------------------------------------------------------------
    # Public FMP convenience wrappers
    # ------------------------------------------------------------------
    # The following methods are intentionally provided for interactive
    # use (REPL, notebooks, external scripts) and may not be called from
    # within the codebase itself.  Do NOT remove as dead code.
    # ------------------------------------------------------------------

    def get_institutional_holders(
        self,
        symbol: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch top institutional holders for a symbol."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return []
        data = self._get(
            "/stable/institutional-holder",
            {"symbol": sym, "limit": max(1, min(int(limit), 100))},
        )
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_analyst_estimates(
        self,
        symbol: str,
        period: str = "quarter",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Fetch analyst earnings/revenue estimates for a symbol.

        Returns a list of estimate records sorted by date (most recent first).
        """
        sym = str(symbol or "").strip().upper()
        if not sym:
            return []
        data = self._get(
            "/stable/analyst-estimates",
            {
                "symbol": sym,
                "period": period,
                "limit": max(1, min(int(limit), 100)),
            },
        )
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        """Fetch company profile (sector, industry, etc.) for a single symbol."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return {}
        data = self._get("/stable/profile", {"symbol": sym})
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return {}

    # ------------------------------------------------------------------
    # Ultimate-tier endpoints (Phase 2 – bulk)
    # ------------------------------------------------------------------

    def get_profile_bulk(self) -> list[dict[str, Any]]:
        """Fetch all company profiles in a single bulk call (Ultimate)."""
        try:
            data = self._get("/stable/profile-bulk", {"datatype": "json"})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_scores_bulk(self) -> list[dict[str, Any]]:
        """Fetch financial scores for all tickers in bulk (Ultimate)."""
        try:
            data = self._get("/stable/scores-bulk", {"datatype": "json"})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_price_target_summary_bulk(self) -> list[dict[str, Any]]:
        """Fetch price-target summaries for all tickers in bulk (Ultimate)."""
        try:
            data = self._get("/stable/price-target-summary-bulk", {"datatype": "json"})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_earnings_surprises_bulk(self) -> list[dict[str, Any]]:
        """Fetch earnings surprises for all tickers in bulk (Ultimate)."""
        try:
            data = self._get("/stable/earnings-surprises-bulk", {"datatype": "json"})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_key_metrics_ttm_bulk(self) -> list[dict[str, Any]]:
        """Fetch key metrics TTM for all tickers in bulk (Ultimate)."""
        try:
            data = self._get("/stable/key-metrics-ttm-bulk", {"datatype": "json"})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_ratios_ttm_bulk(self) -> list[dict[str, Any]]:
        """Fetch financial ratios TTM for all tickers in bulk (Ultimate)."""
        try:
            data = self._get("/stable/ratios-ttm-bulk", {"datatype": "json"})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    # ------------------------------------------------------------------
    # Ultimate-tier endpoints (Phase 3 – new signals)
    # ------------------------------------------------------------------

    def get_insider_trading_latest(
        self,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch latest insider trades from SEC Form 4 filings.

        Without symbol returns broad market insider activity.
        """
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
        if symbol:
            sym = str(symbol).strip().upper()
            if sym:
                params["symbol"] = sym
        try:
            data = self._get("/stable/insider-trading", params)
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_insider_trade_statistics(
        self,
        symbol: str,
    ) -> dict[str, Any]:
        """Fetch aggregated insider trade statistics for a symbol."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return {}
        try:
            data = self._get("/stable/insider-trading-statistics", {"symbol": sym})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return {}
            raise
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return {}

    def get_institutional_ownership(
        self,
        symbol: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch institutional ownership (13F) data for a symbol."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return []
        try:
            data = self._get(
                "/stable/institutional-ownership",
                {"symbol": sym, "limit": max(1, min(int(limit), 100))},
            )
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_earnings_transcript(
        self,
        symbol: str,
        year: int | None = None,
        quarter: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch earnings call transcript(s) for a symbol.

        With year+quarter returns a specific transcript; without returns the latest.
        """
        sym = str(symbol or "").strip().upper()
        if not sym:
            return []
        params: dict[str, Any] = {"symbol": sym}
        if year is not None:
            params["year"] = int(year)
        if quarter is not None:
            params["quarter"] = int(quarter)
        try:
            data = self._get("/stable/earning-call-transcript", params)
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_etf_holdings(
        self,
        symbol: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch ETF holdings breakdown for an ETF symbol (e.g. SPY, QQQ)."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return []
        try:
            data = self._get(
                "/stable/etf-holdings",
                {"symbol": sym, "limit": max(1, min(int(limit), 500))},
            )
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_senate_trading(
        self,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch US Senate stock trading disclosures."""
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
        if symbol:
            sym = str(symbol).strip().upper()
            if sym:
                params["symbol"] = sym
        try:
            data = self._get("/stable/senate-trading", params)
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    # ------------------------------------------------------------------
    # Phase 1 — newly evaluated FMP endpoints (Gap-Analyse v1)
    # ------------------------------------------------------------------

    def get_house_trading(
        self,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch US House of Representatives stock trading disclosures.

        Mirrors get_senate_trading() for the lower chamber.
        Without a symbol returns the latest trades across all members.
        """
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
        if symbol:
            sym = str(symbol).strip().upper()
            if sym:
                params["symbol"] = sym
        try:
            data = self._get("/stable/house-trading", params)
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_treasury_rates(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch US Treasury yield curve rates (1M through 30Y).

        Returns daily snapshots with fields like month1, month3, year2,
        year5, year10, year30. Useful for yield-curve slope / inversion
        analysis (e.g. 2Y-10Y spread as recession indicator).
        """
        params: dict[str, Any] = {}
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        try:
            data = self._get("/stable/treasury-rates", params)
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_economic_indicators(
        self,
        name: str,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch historical economic indicator time-series from FMP.

        *name* is the indicator key (e.g. "GDP", "CPI", "unemploymentRate",
        "federalFundsRate", "inflationRate", "retailSales").
        Returns actual data points — not calendar events — enabling
        quantitative macro analysis (actual vs. forecast over time).
        """
        indicator = str(name or "").strip()
        if not indicator:
            return []
        params: dict[str, Any] = {"name": indicator}
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        try:
            data = self._get("/stable/economic-indicators", params)
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_technical_indicator(
        self,
        name: str,
        symbol: str,
        period_length: int = 14,
        timeframe: str = "1day",
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch a server-side technical indicator from FMP.

        *name* is one of: sma, ema, wma, dema, tema, rsi,
        standarddeviation, williams, adx.
        *timeframe*: 1min, 5min, 15min, 30min, 1hour, 4hour, 1day.

        Each response row contains OHLCV fields plus the computed
        indicator value keyed by the indicator name.
        """
        indicator = str(name or "").strip().lower()
        sym = str(symbol or "").strip().upper()
        if not indicator or not sym:
            return []
        valid_indicators = {
            "sma", "ema", "wma", "dema", "tema",
            "rsi", "standarddeviation", "williams", "adx",
        }
        if indicator not in valid_indicators:
            logger.warning(
                "Unknown FMP technical indicator %r (valid: %s)",
                indicator,
                ", ".join(sorted(valid_indicators)),
            )
            return []
        params: dict[str, Any] = {
            "symbol": sym,
            "periodLength": max(1, int(period_length)),
            "timeframe": str(timeframe or "1day").strip().lower(),
        }
        if date_from is not None:
            params["from"] = date_from.isoformat()
        if date_to is not None:
            params["to"] = date_to.isoformat()
        try:
            data = self._get(f"/stable/technical-indicators/{indicator}", params)
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def get_dcf(self, symbol: str) -> dict[str, Any]:
        """Fetch discounted-cash-flow intrinsic value for a symbol.

        Returns a dict with keys like dcf, stockPrice, date.
        Useful for value-deviation scoring (DCF vs. market price).
        """
        sym = str(symbol or "").strip().upper()
        if not sym:
            return {}
        try:
            data = self._get("/stable/discounted-cash-flow", {"symbol": sym})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return {}
            raise
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return {}

    def get_levered_dcf(self, symbol: str) -> dict[str, Any]:
        """Fetch levered DCF (debt-adjusted intrinsic value) for a symbol."""
        sym = str(symbol or "").strip().upper()
        if not sym:
            return {}
        try:
            data = self._get("/stable/levered-discounted-cash-flow", {"symbol": sym})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return {}
            raise
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return {}

    def get_price_target_consensus(self, symbol: str) -> dict[str, Any]:
        """Fetch aggregated analyst price-target consensus for a symbol.

        Returns a compact dict with targetHigh, targetLow, targetConsensus,
        targetMedian — lighter than get_price_target_summary().
        """
        sym = str(symbol or "").strip().upper()
        if not sym:
            return {}
        try:
            data = self._get("/stable/price-target-consensus", {"symbol": sym})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return {}
            raise
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return {}

    def get_index_constituents(
        self,
        index: str = "sp500",
    ) -> list[dict[str, Any]]:
        """Fetch index constituents (symbols, sectors, weights).

        *index*: "sp500", "nasdaq", "dowjones".
        """
        slug_map = {
            "sp500": "sp500-constituent",
            "nasdaq": "nasdaq-constituent",
            "dowjones": "dowjones-constituent",
        }
        key = str(index or "sp500").strip().lower()
        slug = slug_map.get(key)
        if not slug:
            logger.warning(
                "Unknown index %r for constituents (valid: %s)",
                key,
                ", ".join(sorted(slug_map)),
            )
            return []
        try:
            data = self._get(f"/stable/{slug}", {})
        except RuntimeError as exc:
            if "HTTP 402" in str(exc) or "HTTP 404" in str(exc):
                return []
            raise
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]


# ───────────────────────────────────────────────────────────────
# Finnhub Client — Alternative-Data provider (Phase 1 FREE + Phase 2 PREMIUM)
# ───────────────────────────────────────────────────────────────


class FinnhubClient:
    """Lightweight Finnhub REST client.

    Auth via ``?token=API_KEY`` query parameter.
    Free tier: 30 req/s, no daily limit.

    Environment variable: ``FINNHUB_API_KEY``.
    """

    BASE = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("FINNHUB_API_KEY", "")

    @classmethod
    def from_env(cls, key_name: str = "FINNHUB_API_KEY") -> "FinnhubClient":
        value = os.environ.get(key_name, "")
        return cls(api_key=value)

    # ── internal ─────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.api_key:
            logger.debug("FinnhubClient: no API key — skipping %s", path)
            return {}
        query: dict[str, Any] = dict(params or {})
        query["token"] = self.api_key
        url = f"{self.BASE}{path}?{urlencode(query)}"
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                logger.warning("Finnhub rate-limited (429) for %s — back off", path)
            elif exc.code in (401, 403):
                logger.debug("Finnhub auth error %s for %s", exc.code, path)
            else:
                logger.warning("Finnhub HTTP %s for %s: %s", exc.code, path, exc.reason)
            return {}
        except Exception as exc:
            logger.warning("Finnhub request failed for %s: %s", path, _APIKEY_RE.sub(r"\1=***", str(exc)))
            return {}

    def available(self) -> bool:
        """Return True when a Finnhub API key is configured."""
        return bool(self.api_key)

    # ── Phase 1: FREE endpoints ──────────────────────────────

    def get_insider_sentiment(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        """Insider sentiment (MSPR score -100 to +100).

        MSPR = Monthly Share Purchase Ratio. Positive means net buying.
        """
        data = self._get("/stock/insider-sentiment", {
            "symbol": symbol.upper(),
            "from": from_date,
            "to": to_date,
        })
        if isinstance(data, dict) and "data" in data:
            return data
        return {"data": [], "symbol": symbol.upper()}

    def get_peers(self, symbol: str) -> list[str]:
        """Company peers — same industry/sub-industry."""
        data = self._get("/stock/peers", {"symbol": symbol.upper()})
        if isinstance(data, list):
            return [str(s) for s in data if isinstance(s, str)]
        return []

    def get_market_status(self, exchange: str = "US") -> dict[str, Any]:
        """Current market status (open/closed/pre/post)."""
        data = self._get("/stock/market-status", {"exchange": exchange})
        return data if isinstance(data, dict) else {}

    def get_market_holiday(self, exchange: str = "US") -> list[dict[str, Any]]:
        """Upcoming market holidays."""
        data = self._get("/stock/market-holiday", {"exchange": exchange})
        return data if isinstance(data, list) else []

    def get_fda_calendar(self) -> list[dict[str, Any]]:
        """FDA advisory committee calendar (pharma/biotech)."""
        data = self._get("/fda-advisory-committee-calendar", {})
        return data if isinstance(data, list) else []

    def get_lobbying(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        """Senate lobbying activities for a company."""
        data = self._get("/stock/lobbying", {
            "symbol": symbol.upper(),
            "from": from_date,
            "to": to_date,
        })
        if isinstance(data, list):
            return data
        return data.get("data") or [] if isinstance(data, dict) else []

    def get_usa_spending(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        """US government contracts / spending for a company."""
        data = self._get("/stock/usa-spending", {
            "symbol": symbol.upper(),
            "from": from_date,
            "to": to_date,
        })
        if isinstance(data, list):
            return data
        return data.get("data") or [] if isinstance(data, dict) else []

    def get_patents(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        """USPTO patent grants for a company."""
        data = self._get("/stock/uspto-patent", {
            "symbol": symbol.upper(),
            "from": from_date,
            "to": to_date,
        })
        if isinstance(data, list):
            return data
        return data.get("data") or [] if isinstance(data, dict) else []

    # ── Phase 2: PREMIUM endpoints ───────────────────────────

    def get_social_sentiment(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        """Reddit + Twitter social sentiment (-1 to +1 score, mention count)."""
        params: dict[str, Any] = {"symbol": symbol.upper()}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        data = self._get("/stock/social-sentiment", params)
        if isinstance(data, dict) and ("reddit" in data or "twitter" in data):
            return data
        return {"reddit": [], "twitter": [], "symbol": symbol.upper()}

    def get_pattern_recognition(
        self,
        symbol: str,
        resolution: str = "D",
    ) -> dict[str, Any]:
        """Chart pattern recognition (double top/bottom, H&S, triangles etc.)."""
        data = self._get("/scan/pattern", {
            "symbol": symbol.upper(),
            "resolution": resolution,
        })
        return data if isinstance(data, dict) else {"points": []}

    def get_support_resistance(
        self,
        symbol: str,
        resolution: str = "D",
    ) -> dict[str, Any]:
        """Auto-computed support/resistance levels."""
        data = self._get("/scan/support-resistance", {
            "symbol": symbol.upper(),
            "resolution": resolution,
        })
        return data if isinstance(data, dict) else {"levels": []}

    def get_aggregate_indicators(
        self,
        symbol: str,
        resolution: str = "D",
    ) -> dict[str, Any]:
        """Composite buy/sell/neutral technical signal."""
        data = self._get("/scan/technical-indicator", {
            "symbol": symbol.upper(),
            "resolution": resolution,
        })
        return data if isinstance(data, dict) else {}

    def get_supply_chain(self, symbol: str) -> dict[str, Any]:
        """Customer/supplier supply-chain relationships."""
        data = self._get("/stock/supply-chain", {"symbol": symbol.upper()})
        return data if isinstance(data, dict) else {"data": []}

    def get_earnings_quality(
        self,
        symbol: str,
        freq: str = "quarterly",
    ) -> dict[str, Any]:
        """Earnings quality score."""
        data = self._get("/stock/earnings-quality-score", {
            "symbol": symbol.upper(),
            "freq": freq,
        })
        if isinstance(data, list) and data:
            entry = data[0]
            return dict(entry) if isinstance(entry, dict) else {}
        return data if isinstance(data, dict) else {}

    def get_news_sentiment(self, symbol: str) -> dict[str, Any]:
        """News sentiment with bullish/bearish percentages."""
        data = self._get("/news-sentiment", {"symbol": symbol.upper()})
        return data if isinstance(data, dict) else {}

    def get_esg(self, symbol: str) -> dict[str, Any]:
        """Company ESG score (current + historical)."""
        data = self._get("/stock/esg", {"symbol": symbol.upper()})
        if isinstance(data, list) and data:
            entry = data[0]
            return dict(entry) if isinstance(entry, dict) else {}
        return data if isinstance(data, dict) else {}


# ───────────────────────────────────────────────────────────────
# Alpaca Client — Market Data + News (Phase 3)
# ───────────────────────────────────────────────────────────────


class AlpacaClient:
    """Lightweight Alpaca Market Data client.

    Auth via ``APCA-API-KEY-ID`` + ``APCA-API-SECRET-KEY`` headers.
    Free tier: 200 req/min, IEX data.

    Environment variables: ``APCA_API_KEY_ID``, ``APCA_API_SECRET_KEY``.
    """

    DATA_BASE = "https://data.alpaca.markets"

    def __init__(
        self,
        key_id: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self.key_id = key_id or os.environ.get("APCA_API_KEY_ID", "")
        self.secret_key = secret_key or os.environ.get("APCA_API_SECRET_KEY", "")

    @classmethod
    def from_env(cls) -> "AlpacaClient":
        return cls()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.key_id or not self.secret_key:
            logger.debug("AlpacaClient: no API keys — skipping %s", path)
            return {}
        query_str = f"?{urlencode(params)}" if params else ""
        url = f"{self.DATA_BASE}{path}{query_str}"
        request = Request(url, headers={
            "Accept": "application/json",
            "APCA-API-KEY-ID": self.key_id,
            "APCA-API-SECRET-KEY": self.secret_key,
        })
        try:
            with urlopen(request, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            logger.warning("Alpaca HTTP %s for %s: %s", exc.code, path, exc.reason)
            return {}
        except Exception as exc:
            logger.warning("Alpaca request failed for %s: %s", path, type(exc).__name__)
            return {}

    def available(self) -> bool:
        """Return True when Alpaca API keys are configured."""
        return bool(self.key_id and self.secret_key)

    def get_news(
        self,
        symbols: list[str] | None = None,
        limit: int = 50,
        sort: str = "desc",
    ) -> list[dict[str, Any]]:
        """Fetch latest news articles (with sentiment + tickers)."""
        params: dict[str, Any] = {"limit": min(limit, 50), "sort": sort}
        if symbols:
            params["symbols"] = ",".join(s.upper() for s in symbols)
        data = self._get("/v1beta1/news", params)
        if isinstance(data, dict) and "news" in data:
            return list(data["news"])
        return data if isinstance(data, list) else []

    def get_most_active(self, top: int = 20) -> list[dict[str, Any]]:
        """Screener: most actively traded stocks."""
        data = self._get("/v1beta1/screener/stocks/most-actives", {"top": min(top, 100)})
        if isinstance(data, dict) and "most_actives" in data:
            return list(data["most_actives"])
        return data if isinstance(data, list) else []

    def get_top_movers(self, top: int = 20, market_type: str = "stocks") -> dict[str, Any]:
        """Screener: top movers (gainers + losers by %)."""
        data = self._get(f"/v1beta1/screener/{market_type}/movers", {"top": min(top, 50)})
        return data if isinstance(data, dict) else {}

    def get_option_chain(
        self,
        underlying: str,
        expiration_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch option chain snapshots for an underlying symbol."""
        params: dict[str, Any] = {}
        if expiration_date:
            params["expiration_date"] = expiration_date
        data = self._get(f"/v1beta1/options/snapshots/{underlying.upper()}", params)
        if isinstance(data, dict) and "snapshots" in data:
            return list(data["snapshots"])
        return data if isinstance(data, list) else []


CANONICAL_EVENT_PATTERNS = [
    ("core_pce_mom", [r"\bcore\b", r"\bpce\b", r"\bmom\b"]),
    ("pce_mom",      [r"(?<!core )\bpce\b", r"\bmom\b"]),
    # YoY PCE entries must come AFTER the MoM entries so the longer/more-specific
    # MoM patterns have priority when both "mom" and "yoy" appear in the same name.
    ("core_pce_yoy", [r"\bcore\b", r"\bpce\b", r"\byoy\b"]),
    ("pce_yoy",      [r"(?<!core )\bpce\b", r"\byoy\b"]),
    ("gdp_qoq",      [r"\bgdp\b|\bgross domestic product\b", r"\bqoq\b"]),
    ("jobless_claims", [r"\bjobless\b|\binitial claims\b|\bcontinuing claims\b"]),
    ("philly_fed",   [r"\bphiladelphia\b|\bphilly\b", r"\bfed\b"]),
    ("pmi_sp_global", [r"\bs&p\b|\bs and p\b", r"\bglobal\b", r"\bpmi\b"]),
    ("ism",          [r"\bism\b"]),
    ("retail_sales", [r"\bretail\b", r"\bsales\b"]),
    ("cpi_mom",      [r"(?<!core )\bcpi\b", r"\bmom\b"]),
    ("core_cpi_mom", [r"\bcore\b", r"\bcpi\b", r"\bmom\b"]),
    ("ppi_mom",      [r"(?<!core )\bppi\b", r"\bmom\b"]),
    ("core_ppi_mom", [r"\bcore\b", r"\bppi\b", r"\bmom\b"]),
    # YoY CPI/PPI patterns must come AFTER MoM but BEFORE the bare cpi/ppi
    # patterns, otherwise "CPI YoY" would fall through to the bare "cpi" key
    # and receive weight 1.0 instead of the intended 0.25 for derived prints.
    ("cpi_yoy",      [r"(?<!core )\bcpi\b", r"\byoy\b"]),
    ("core_cpi_yoy", [r"\bcore\b", r"\bcpi\b", r"\byoy\b"]),
    ("ppi_yoy",      [r"(?<!core )\bppi\b", r"\byoy\b"]),
    ("core_ppi_yoy", [r"\bcore\b", r"\bppi\b", r"\byoy\b"]),
    ("cpi",          [r"(?<!core )\bcpi\b"]),
    ("core_cpi",     [r"\bcore\b", r"\bcpi\b"]),
    ("ppi",          [r"(?<!core )\bppi\b"]),
    ("core_ppi",     [r"\bcore\b", r"\bppi\b"]),
    ("nfp",          [r"\bnonfarm\b", r"\bpayroll\b"]),
    ("unemployment", [r"\bunemployment\b", r"\brate\b"]),
    ("hourly_earnings", [r"\baverage\b", r"\bhourly\b", r"\bearnings\b"]),
    ("jolts",        [r"\bjolts\b|\bjob openings\b"]),
]

def canonicalize_event_name(raw: str) -> str | None:
    name = _normalize_event_name(raw)
    for key, pats in CANONICAL_EVENT_PATTERNS:
        if all(re.search(p, name) for p in pats):
            return key
    return None

def _impact_rank(v: str | None) -> int:
    v = (v or "").lower()
    return {"high": 3, "medium": 2, "mid": 2, "moderate": 2, "low": 1}.get(v, 0)


def get_consensus(event: dict[str, Any]) -> tuple[Any, str | None]:
    for fname in CONSENSUS_FIELD_CANDIDATES:
        value = event.get(fname)
        if value is not None:
            return value, fname
    return None, None


def _annotate_event_quality(event: dict[str, Any], actual: Any, consensus: Any, consensus_field: str | None) -> dict[str, Any]:
    """Return quality annotations without mutating the original event dict."""
    flags: list[str] = []
    if actual is None:
        flags.append("missing_actual")
    if consensus is None:
        flags.append("missing_consensus")
    if not event.get("unit"):
        flags.append("missing_unit")

    return {"consensus_field": consensus_field, "data_quality_flags": flags}

def _dedupe_quality(e: dict) -> tuple:
    """Sort key for duplicate-event selection: prefer higher impact, then
    more-complete data fields, then a stable alphabetic name tiebreaker."""
    actual = e.get("actual")
    cons, _ = get_consensus(e)
    return (
        _impact_rank(e.get("impact")),
        1 if actual is not None else 0,
        1 if cons is not None else 0,
        # Fall back to "name" field so events without an "event" key
        # are still disambiguated deterministically.
        e.get("event") or e.get("name") or "",
    )


def dedupe_events(events: list[dict]) -> list[dict]:
    buckets: dict[tuple[str, str, str], list[dict]] = {}
    passthrough: list[dict] = []
    for e in events:
        country_raw = str(e.get("country") or "").strip().upper()
        currency_raw = str(e.get("currency") or "").strip().upper()
        # Some providers omit `country` for US releases but still set `currency=USD`.
        # Preserve these events by assigning a stable US key so they can be deduped
        # and scored instead of being silently dropped.
        country = country_raw or ("US" if currency_raw in US_CURRENCIES else "")
        # Guard against date=None: the .get() default only fires when the key
        # is absent; if date IS present but None we must still substitute so
        # unrelated null-dated events are not incorrectly grouped together.
        # Truncate to 10 chars so that "2026-02-20" and "2026-02-20 08:30:00"
        # resolve to the same dedup key (providers may return either format).
        event_date_raw = str(e.get("date") or "")
        event_date = event_date_raw[:10] if event_date_raw else f"_no_date_{id(e)}"
        raw_name = e.get("event") or e.get("name") or ""
        key = canonicalize_event_name(raw_name)
        if not country:
            continue
        if not key:
            # Non-canonical events (e.g. Consumer Sentiment, Housing Starts)
            # are passed through unchanged so downstream mid-impact filters
            # and scoring can still see them.
            passthrough.append(e)
            continue
        buckets.setdefault((country, event_date, key), []).append(e)

    out = []
    for k, items in buckets.items():
        if len(items) == 1:
            single = dict(items[0])  # copy to avoid mutating caller's dict
            if not single.get("country"):
                single["country"] = k[0]
            single["canonical_event"] = k[2]
            out.append(single)
            continue

        sorted_items = sorted(items, key=_dedupe_quality, reverse=True)
        chosen = sorted_items[0]
        chosen = dict(chosen)  # copy
        if not chosen.get("country"):
            chosen["country"] = k[0]
        chosen["canonical_event"] = k[2]
        chosen["dedup"] = {
            "was_deduped": True,
            "duplicates_count": len(items),
            "duplicates": [i.get("event") for i in items],
            "chosen_event": chosen.get("event") or chosen.get("name"),
            "policy": "impact_then_fields_then_name",
        }
        out.append(chosen)

    return out + passthrough

def _normalize_event_name(name: str) -> str:
    lowered = name.lower()
    lowered = lowered.replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


# Pre-computed once at import time to avoid rebuilding the normalized set
# on every call to _is_high_impact_event_name (DEFAULT_HIGH_IMPACT_EVENTS is constant).
_DEFAULT_HIGH_IMPACT_EVENTS_NORMALIZED: frozenset[str] = frozenset(
    _normalize_event_name(e) for e in DEFAULT_HIGH_IMPACT_EVENTS
)


def _is_high_impact_event_name(name: str, watchlist: set[str]) -> bool:
    normalized = _normalize_event_name(name)
    # GDPNow is a real-time model estimate, not an official data release;
    # exclude it explicitly before any pattern matching.
    if "gdpnow" in normalized:
        return False
    # Use the pre-computed frozenset for the default watchlist; only fall
    # back to per-call set building for custom watchlists.
    if watchlist is DEFAULT_HIGH_IMPACT_EVENTS:
        if normalized in _DEFAULT_HIGH_IMPACT_EVENTS_NORMALIZED:
            return True
    else:
        if normalized in {_normalize_event_name(item) for item in watchlist}:
            return True

    return any(all(keyword in normalized for keyword in keywords) for keywords in HIGH_IMPACT_NAME_PATTERNS)


def _contains_keywords(normalized_name: str, pattern: tuple[str, ...]) -> bool:
    return all(keyword in normalized_name for keyword in pattern)


def filter_us_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep events that are likely US macro releases."""
    out: list[dict[str, Any]] = []
    for event in events:
        country = str(event.get("country") or "").strip().upper()
        currency = str(event.get("currency") or "").strip().upper()
        if country in US_COUNTRY_CODES or currency in US_CURRENCIES:
            out.append(event)
    return out


def filter_us_high_impact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """US-only and high-impact subset used for open-bias scoring.

    Priority:
    1) Provider-tagged high impact.
    2) Name-based fallback when impact tag is missing.
    """
    out: list[dict[str, Any]] = []
    for event in filter_us_events(events):
        impact_level = _event_impact_level(event)
        name = str(event.get("event") or event.get("name") or "")
        canonical_key = canonicalize_event_name(name)
        if impact_level in HIGH_IMPACT_LEVELS:
            out.append(event)
            continue
        if canonical_key in FORCED_HIGH_IMPACT_CANONICAL_KEYS and impact_level != "low":
            out.append(event)
            continue
        if not impact_level and _is_high_impact_event_name(name, watchlist=DEFAULT_HIGH_IMPACT_EVENTS):
            out.append(event)
    return out


def _event_impact_level(event: dict[str, Any]) -> str:
    impact = event.get("impact") or event.get("importance") or event.get("priority")
    return str(impact or "").strip().lower()


def filter_us_mid_impact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mid-impact US event subset based on provider impact tags and name patterns.

    Expects pre-filtered US events (e.g. output of filter_us_events / dedupe_events).
    No additional US country check is applied here; callers are responsible for
    passing US-scoped events.
    """
    out: list[dict[str, Any]] = []
    for event in events:
        name = str(event.get("event") or event.get("name") or "")
        canonical_key = canonicalize_event_name(name)
        if canonical_key in FORCED_MID_IMPACT_CANONICAL_KEYS:
            out.append(event)
            continue

        if _event_impact_level(event) not in MID_IMPACT_LEVELS:
            continue

        normalized_name = _normalize_event_name(name)

        if any(_contains_keywords(normalized_name, p) for p in MID_IMPACT_EXCLUDE_PATTERNS):
            continue

        if any(_contains_keywords(normalized_name, p) for p in MID_IMPACT_MACRO_NAME_PATTERNS):
            out.append(event)
    return out


def _events_for_bias(
    events: list[dict[str, Any]],
    include_mid_if_no_high: bool,
    include_headline_pce_confirm: bool = True,
) -> list[dict[str, Any]]:
    # Canonicalize+dedupe first across the full US event set so duplicates that
    # straddle provider impact buckets cannot slip through.
    us_events = dedupe_events(filter_us_events(events))

    high_impact_events = filter_us_high_impact_events(us_events)
    events_for_bias = list(high_impact_events)
    if include_mid_if_no_high and not high_impact_events:
        events_for_bias = filter_us_mid_impact_events(us_events)

    # Always include headline PCE as a lightweight confirm/check signal,
    # even when high-impact events are present.
    if include_headline_pce_confirm:
        existing_keys = {
            (
                str(e.get("country") or ""),
                str(e.get("date") or ""),
                str(e.get("canonical_event") or ""),
            )
            for e in events_for_bias
        }
        for event in us_events:
            if event.get("canonical_event") != "pce_mom":
                continue
            key = (
                str(event.get("country") or ""),
                str(event.get("date") or ""),
                str(event.get("canonical_event") or ""),
            )
            if key in existing_keys:
                continue
            events_for_bias.append(event)
            existing_keys.add(key)

    return events_for_bias


def macro_bias_with_components(
    events: list[dict[str, Any]],
    include_mid_if_no_high: bool = True,
    include_headline_pce_confirm: bool = True,
) -> dict[str, Any]:
    score = 0.0
    components: list[dict[str, Any]] = []
    # Make independent copies of every event so that:
    #  (a) passthrough events (non-canonical, appended by-reference in dedupe_events)
    #      do not get mutated from the caller's perspective, and
    #  (b) downstream consumers of macro_analysis["events_for_bias"] (e.g. the BEA
    #      audit) receive events that already carry computed data_quality_flags.
    events_for_bias = [dict(e) for e in _events_for_bias(
        events,
        include_mid_if_no_high=include_mid_if_no_high,
        include_headline_pce_confirm=include_headline_pce_confirm,
    )]

    for event in events_for_bias:
        raw_name = str(event.get("event") or event.get("name") or "")
        name = _normalize_event_name(raw_name)
        canonical_key = event.get("canonical_event")
        actual = event.get("actual")
        consensus, consensus_field = get_consensus(event)
        quality = _annotate_event_quality(event, actual=actual, consensus=consensus, consensus_field=consensus_field)
        # Annotate the (already-copied) event so that downstream consumers
        # such as build_bea_audit_payload can read data_quality_flags directly.
        event["data_quality_flags"] = quality["data_quality_flags"]
        event["consensus_field"] = quality["consensus_field"]

        component: dict[str, Any] = {
            "date": event.get("date"),
            "country": event.get("country"),
            "event": raw_name,
            "canonical_event": canonical_key,
            "impact": event.get("impact") or event.get("importance") or event.get("priority"),
            "actual": actual,
            "consensus_value": consensus,
            "consensus_field": consensus_field,
            "surprise": None,
            "weight": 0.0,
            "contribution": 0.0,
            "skip_reason": None,
            "data_quality_flags": quality["data_quality_flags"],
            "dedup": event.get("dedup"),
        }

        if actual is None or consensus is None:
            component["skip_reason"] = "missing_actual_or_consensus"
            components.append(component)
            continue

        try:
            surprise = float(actual) - float(consensus)
        except (TypeError, ValueError):
            component["skip_reason"] = "non_numeric_actual_or_consensus"
            components.append(component)
            continue

        component["surprise"] = round(surprise, 6)

        if surprise == 0.0:
            component["skip_reason"] = "on_consensus"
            components.append(component)
            continue

        weight = 0.0
        sign = 0.0

        if canonical_key in (
            "core_pce_mom",
            "cpi_mom",
            "core_cpi_mom",
            "ppi_mom",
            "core_ppi_mom",
            "cpi",
            "core_cpi",
            "ppi",
            "core_ppi",
        ):
            weight = 1.0
            sign = -1.0 if surprise > 0 else +1.0
        elif canonical_key in (
            "pce_mom", "pce_yoy", "core_pce_yoy",
            "cpi_yoy", "core_cpi_yoy",
            "ppi_yoy", "core_ppi_yoy",
        ):
            # YoY variants carry reduced weight — the MoM prints already carry
            # full 1.0 weight and YoY is derived from the same underlying data.
            # Headline PCE MoM (pce_mom) is also 0.25 since Core PCE is the
            # primary Fed-watch print at weight 1.0.
            weight = 0.25
            sign = -1.0 if surprise > 0 else +1.0
        elif canonical_key == "hourly_earnings" or "average hourly earnings" in name or canonical_key == "unemployment" or "unemployment rate" in name or canonical_key == "jobless_claims" or "jobless claims" in name or "initial claims" in name:
            weight = 0.5
            sign = -1.0 if surprise > 0 else +1.0
        elif canonical_key == "jolts" or "jolts" in name or "job openings" in name:
            weight = 0.5
            sign = +1.0 if surprise > 0 else -1.0
        elif canonical_key == "pmi_sp_global" or (
            "pmi" in name and ("s p global" in name or "s and p global" in name)
        ):
            weight = 0.25
            sign = +1.0 if surprise > 0 else -1.0
        elif canonical_key in ("ism", "philly_fed") or "philadelphia fed" in name or "philly fed" in name or "ism" in name or canonical_key == "nfp" or "nonfarm payroll" in name or canonical_key in ("retail_sales", "gdp_qoq") or "retail sales" in name or (
            "gdp" in name and "gdpnow" not in name
        ):
            weight = 0.5
            sign = +1.0 if surprise > 0 else -1.0
        elif any(_contains_keywords(name, p) for p in MID_IMPACT_MACRO_NAME_PATTERNS):
            weight = 0.25
            sign = +1.0 if surprise > 0 else -1.0
        elif canonical_key is None and ("ppi" in name or "cpi" in name or "pce" in name):
            # Non-canonical inflation variants (e.g. CPI YoY, PCE YoY) get
            # reduced weight — the MoM prints already carry full 1.0 weight
            # and YoY is derived from the same underlying data.
            weight = 0.25
            sign = -1.0 if surprise > 0 else +1.0
        else:
            component["skip_reason"] = "unmapped_event"
            components.append(component)
            continue

        contribution = sign * weight
        score += contribution

        component["weight"] = weight
        component["contribution"] = round(contribution, 6)
        components.append(component)

    normalized = max(-1.0, min(1.0, score / 2.0))
    return {
        "macro_bias": normalized,
        "raw_score": score,
        "events_for_bias": events_for_bias,
        "score_components": components,
    }


def macro_bias_score(
    events: list[dict[str, Any]],
    include_mid_if_no_high: bool = True,
    include_headline_pce_confirm: bool = True,
) -> float:
    """Return bias in range [-1, 1], where +1 means risk-on and -1 risk-off.

    Scoring weights:
      Core PCE / Core CPI / CPI MoM / PPI MoM : ±1.0  (primary inflation drivers)
      Headline PCE MoM / YoY variants          : ±0.25 (derived / secondary prints)
      Average Hourly Earnings                  : ±0.5  (wage inflation; hawkish on beat)
      Unemployment Rate                        : ±0.5  (higher = risk-off)
      Jobless Claims                           : ±0.5
      JOLTS / Job Openings                     : ±0.5  (tight labor = risk-on)
      NFP / ISM / PhillyFed                    : ±0.5
      GDP / Retail Sales                       : ±0.5
      Mid-impact fallback                      : ±0.25 (only when no high-impact events)

    Dividing by 2.0 normalises the range so a CPI + PPI double-beat saturates
    the output at +1.0 / -1.0 without overflow for typical trading days.
    """
    return float(
        macro_bias_with_components(
            events,
            include_mid_if_no_high=include_mid_if_no_high,
            include_headline_pce_confirm=include_headline_pce_confirm,
        )["macro_bias"]
    )
