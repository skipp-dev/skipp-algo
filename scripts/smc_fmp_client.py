"""Thin standalone FMP client for the v4 enrichment pipeline.

Covers the **six** FMP API methods consumed by ``smc_provider_policy``
adapters.  Uses only stdlib (``urllib``, ``json``, ``ssl``) so it has
**zero** runtime dependency on ``open_prep``.

The interface is method-compatible with ``open_prep.macro.FMPClient``
for the subset used by the v4 path — existing adapter code in
``smc_provider_policy.py`` works unchanged.
"""

from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.error
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com"
_US_EASTERN = ZoneInfo("America/New_York")


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


@dataclass
class SMCFMPClient:
    """Minimal FMP client for the v4 enrichment pipeline.

    Drop-in replacement for the six methods that
    ``smc_provider_policy`` adapters call.
    """

    api_key: str
    retry_attempts: int = 2
    timeout_seconds: float = 12.0

    # ── HTTP layer ──────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        query = {k: v for k, v in params.items() if v is not None}
        query.setdefault("apikey", self.api_key)
        url = f"{_BASE_URL}{path}?{urlencode(query, doseq=True)}"
        request = Request(url, headers={"User-Agent": "skipp-algo/1.0"})

        max_attempts = max(self.retry_attempts, 1)
        for attempt in range(max_attempts):
            try:
                with urlopen(request, timeout=self.timeout_seconds,
                             context=_build_tls_context()) as resp:
                    payload = resp.read().decode("utf-8")
                return self._parse(path, payload)
            except urllib.error.HTTPError as exc:
                if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < max_attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(
                    f"FMP HTTP {exc.code} on {path}"
                ) from exc
            except urllib.error.URLError as exc:
                if attempt + 1 < max_attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(
                    f"FMP network error on {path}: {exc}"
                ) from exc
        raise RuntimeError(f"FMP retries exhausted on {path}")

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

    def get_sector_performance(self) -> list[dict[str, Any]]:
        today = _today_et()
        try:
            data = self._get("/stable/sector-performance", {"date": today.isoformat()})
        except RuntimeError:
            return []
        rows = list(data) if isinstance(data, list) else []
        if rows:
            return rows
        prev = _prev_trading_day(today)
        try:
            data = self._get("/stable/sector-performance", {"date": prev.isoformat()})
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

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
        except RuntimeError:
            return []
        return list(data) if isinstance(data, list) else []

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
