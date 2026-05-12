"""One-shot reachability + data-shape probe for every external data/news
provider used by the skipp-algo stack.

Usage:
    PYTHONPATH=. python scripts/probe_providers.py                # full table
    PYTHONPATH=. python scripts/probe_providers.py --preflight    # critical only
    PYTHONPATH=. python scripts/probe_providers.py --json         # machine-readable
    PYTHONPATH=. python scripts/probe_providers.py --preflight --notify

Exit codes:
    0 = all probed providers OK (or only OPTIONAL ones degraded)
    1 = at least one CRITICAL provider FAIL/SKIP/WARN

Each row reports: PROVIDER | STATUS | LATENCY | DETAIL
Probes are tagged ``critical=True`` for surfaces actually consumed by the
running workflows; the rest (entitlement-gated or retired Benzinga
endpoints) are kept for visibility but never block a launch.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from dotenv import load_dotenv

# ── Pretty output ───────────────────────────────────────────────────

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

ROW_FMT = "{name:<40} {status:<8} {latency:>8} {detail}"

logger = logging.getLogger("probe_providers")


@dataclass(frozen=True)
class Probe:
    """A single provider probe with its criticality tag.

    ``critical=True`` means: the running workflows depend on this surface and
    a non-OK status should block launch / fire an alert. ``critical=False``
    means: visibility only (e.g. entitlement-gated or retired endpoints).
    """

    name: str
    fn: Callable[[], tuple[str, str]]
    critical: bool = True


@dataclass(frozen=True)
class ProbeResult:
    name: str
    status: str  # OK | WARN | FAIL | SKIP
    latency_ms: float | None
    detail: str
    critical: bool

    @property
    def is_blocking(self) -> bool:
        """A critical probe blocks if it's anything other than OK."""
        return self.critical and self.status != "OK"


def _emit(name: str, status: str, latency_ms: float | None, detail: str, *,
          quiet: bool = False) -> None:
    if quiet:
        return
    color = {"OK": GREEN, "WARN": YELLOW, "FAIL": RED, "SKIP": DIM}.get(status, "")
    lat = f"{int(latency_ms)}ms" if latency_ms is not None else "—"
    print(ROW_FMT.format(
        name=name,
        status=f"{color}{status}{RESET}",
        latency=lat,
        detail=detail,
    ))


def _run(probe: Probe, *, quiet: bool = False) -> ProbeResult:
    t0 = time.monotonic()
    try:
        status, detail = probe.fn()
    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        msg = f"{type(exc).__name__}: {exc}"
        if len(msg) > 120:
            msg = msg[:117] + "..."
        _emit(probe.name, "FAIL", latency_ms, msg, quiet=quiet)
        return ProbeResult(probe.name, "FAIL", latency_ms, msg, probe.critical)
    latency_ms = (time.monotonic() - t0) * 1000
    _emit(probe.name, status, latency_ms, detail, quiet=quiet)
    return ProbeResult(probe.name, status, latency_ms, detail, probe.critical)


# ── Provider probes ─────────────────────────────────────────────────


def probe_fmp_quote() -> tuple[str, str]:
    """FMP /stable/quote/AAPL — basic equity quote."""
    import httpx
    key = os.getenv("FMP_API_KEY", "")
    if not key:
        return ("SKIP", "FMP_API_KEY missing")
    r = httpx.get(
        "https://financialmodelingprep.com/stable/quote",
        params={"symbol": "AAPL", "apikey": key},
        timeout=15.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if not isinstance(data, list) or not data:
        return ("FAIL", f"unexpected payload type={type(data).__name__}")
    row = data[0]
    needed = {"symbol", "price", "volume", "marketCap"}
    missing = needed - set(row.keys())
    if missing:
        return ("WARN", f"missing fields: {sorted(missing)}")
    price = row.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return ("WARN", f"price suspect: {price}")
    mcap = row.get('marketCap')
    mcap_str = f"{mcap:,.0f}" if isinstance(mcap, (int, float)) and not isinstance(mcap, bool) else "n/a"
    return ("OK", f"AAPL price={price} mcap={mcap_str}")


def probe_fmp_treasury() -> tuple[str, str]:
    """FMP /stable/treasury-rates — Lane 1 retired-endpoint replacement."""
    from datetime import date, timedelta

    import httpx
    key = os.getenv("FMP_API_KEY", "")
    if not key:
        return ("SKIP", "FMP_API_KEY missing")
    end = date.today()
    start = end - timedelta(days=7)
    r = httpx.get(
        "https://financialmodelingprep.com/stable/treasury-rates",
        params={"from": start.isoformat(), "to": end.isoformat(), "apikey": key},
        timeout=15.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if not isinstance(data, list) or not data:
        return ("WARN", "empty 7-day treasury window")
    row = data[0]
    if "year10" not in row:
        return ("WARN", f"missing year10 in {sorted(row.keys())[:6]}")
    return ("OK", f"{len(data)} rows, latest 10y={row.get('year10')}")


def probe_fmp_news() -> tuple[str, str]:
    """FMP /stable/news/stock-latest — newsstack ingestion endpoint."""
    import httpx
    key = os.getenv("FMP_API_KEY", "")
    if not key:
        return ("SKIP", "FMP_API_KEY missing")
    r = httpx.get(
        "https://financialmodelingprep.com/stable/news/stock-latest",
        params={"page": 0, "limit": 5, "apikey": key},
        timeout=15.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if not isinstance(data, list) or not data:
        return ("WARN", "empty news payload")
    row = data[0]
    needed = {"symbol", "publishedDate", "title", "site"}
    missing = needed - set(row.keys())
    if missing:
        return ("WARN", f"missing fields: {sorted(missing)}")
    return ("OK", f"{len(data)} items, latest={row.get('publishedDate')}")


def probe_fmp_press() -> tuple[str, str]:
    import httpx
    key = os.getenv("FMP_API_KEY", "")
    if not key:
        return ("SKIP", "FMP_API_KEY missing")
    r = httpx.get(
        "https://financialmodelingprep.com/stable/news/press-releases-latest",
        params={"page": 0, "limit": 5, "apikey": key},
        timeout=15.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if not isinstance(data, list) or not data:
        return ("WARN", "empty press-release payload")
    return ("OK", f"{len(data)} items, latest={data[0].get('publishedDate')}")


def probe_fmp_screener() -> tuple[str, str]:
    """FMP /stable/company-screener — universe building."""
    import httpx
    key = os.getenv("FMP_API_KEY", "")
    if not key:
        return ("SKIP", "FMP_API_KEY missing")
    r = httpx.get(
        "https://financialmodelingprep.com/stable/company-screener",
        params={"country": "US", "marketCapMoreThan": 1_000_000_000,
                "exchange": "NASDAQ", "isEtf": "false", "limit": 5,
                "apikey": key},
        timeout=15.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if not isinstance(data, list) or not data:
        return ("WARN", "empty screener result")
    return ("OK", f"{len(data)} rows, sample={data[0].get('symbol')}")


def probe_fmp_technical() -> tuple[str, str]:
    """FMP /stable/technical-indicators/rsi — fallback for TradingView."""
    import httpx
    key = os.getenv("FMP_API_KEY", "")
    if not key:
        return ("SKIP", "FMP_API_KEY missing")
    r = httpx.get(
        "https://financialmodelingprep.com/stable/technical-indicators/rsi",
        params={"symbol": "AAPL", "periodLength": 14, "timeframe": "1day",
                "apikey": key},
        timeout=15.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if not isinstance(data, list) or not data:
        return ("WARN", "empty RSI payload")
    row = data[0]
    if "rsi" not in row:
        return ("WARN", f"missing rsi in {sorted(row.keys())[:6]}")
    return ("OK", f"AAPL rsi(14)={row['rsi']:.2f}")


def _probe_fmp_list(path: str, label: str, expected_min: int = 1) -> tuple[str, str]:
    """Shared boilerplate for FMP list endpoints (movers + eod-bulk).

    2026-05-12 G2/D3 re-check: verifies that ``/stable/biggest-gainers``,
    ``/stable/biggest-losers``, ``/stable/most-actives`` and ``/stable/eod-bulk``
    — consumed by ``open_prep/run_open_prep.py::_build_mover_seed`` /
    ``_incremental_atr_from_eod_bulk`` and by ``terminal_spike_scanner.py``
    — remain reachable on the production FMP plan.
    """
    import httpx
    key = os.getenv("FMP_API_KEY", "")
    if not key:
        return ("SKIP", "FMP_API_KEY missing")
    params: dict[str, str] = {"apikey": key}
    if path == "/stable/eod-bulk":
        params["datatype"] = "json"
        params["date"] = date.today().isoformat()
    try:
        r = httpx.get(
            f"https://financialmodelingprep.com{path}",
            params=params,
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        return ("FAIL", f"HTTP error: {exc}")
    if r.status_code == 401:
        return ("FAIL", "HTTP 401 — FMP key invalid")
    if r.status_code == 402:
        return ("WARN", f"HTTP 402 — {label} not in plan tier")
    if r.status_code == 429:
        return ("WARN", "HTTP 429 — rate-limited")
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    try:
        data = r.json()
    except Exception:
        return ("WARN", "non-JSON response")
    if not isinstance(data, list):
        return ("WARN", f"unexpected payload type={type(data).__name__}")
    # eod-bulk is empty outside trading days — treat as WARN not FAIL.
    if len(data) < expected_min:
        return ("WARN", f"only {len(data)} rows (empty outside trading day for eod-bulk)")
    sample_sym = data[0].get("symbol") if isinstance(data[0], dict) else "n/a"
    return ("OK", f"{label} {len(data)} rows, sample={sample_sym}")


def probe_fmp_biggest_gainers() -> tuple[str, str]:
    """FMP /stable/biggest-gainers — mover-seed for run_open_prep."""
    return _probe_fmp_list("/stable/biggest-gainers", "biggest-gainers")


def probe_fmp_biggest_losers() -> tuple[str, str]:
    """FMP /stable/biggest-losers — mover-seed for run_open_prep."""
    return _probe_fmp_list("/stable/biggest-losers", "biggest-losers")


def probe_fmp_most_actives() -> tuple[str, str]:
    """FMP /stable/most-actives — premarket-mover seed (FMPClient.get_premarket_movers)."""
    return _probe_fmp_list("/stable/most-actives", "most-actives")


def probe_fmp_eod_bulk() -> tuple[str, str]:
    """FMP /stable/eod-bulk — incremental ATR feed for run_open_prep.

    Empty outside trading days; non-empty payload only required when the
    probe runs on a US session day.
    """
    return _probe_fmp_list("/stable/eod-bulk", "eod-bulk", expected_min=0)


def probe_databento_metadata() -> tuple[str, str]:
    """Databento metadata.list_datasets — auth + reachability."""
    key = os.getenv("DATABENTO_API_KEY", "")
    if not key:
        return ("SKIP", "DATABENTO_API_KEY missing")
    from databento_client import _make_databento_client
    client = _make_databento_client(key)
    datasets = client.metadata.list_datasets()
    if not datasets:
        return ("WARN", "empty dataset list")
    return ("OK", f"{len(datasets)} datasets, includes DBEQ.BASIC={'DBEQ.BASIC' in datasets}")


def probe_databento_daily_bars() -> tuple[str, str]:
    """Databento ohlcv-1d for AAPL — actual bar fetch.

    On weekends and US equity market holidays an empty result is the
    *expected* outcome (no bar exists yet), so we report ``OK`` instead of
    ``WARN`` to avoid false preflight alerts. On a regular trading day an
    empty result is genuinely degraded — most often a Databento incident
    delaying historical-data availability.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    key = os.getenv("DATABENTO_API_KEY", "")
    if not key:
        return ("SKIP", "DATABENTO_API_KEY missing")
    from terminal_databento import fetch_databento_daily_bars

    try:
        from newsstack_fmp._market_cal import is_us_equity_trading_day
        today_et = datetime.now(ZoneInfo("America/New_York")).date()
        is_trading_day = is_us_equity_trading_day(today_et)
    except Exception:
        # If the calendar import ever breaks, fall back to weekday-only check
        # so we still avoid the most common false positive (Sat/Sun).
        today_et = datetime.now(ZoneInfo("America/New_York")).date()
        is_trading_day = today_et.weekday() < 5

    bars = fetch_databento_daily_bars(["AAPL", "MSFT"], lookback_days=5)
    if not bars:
        if not is_trading_day:
            return ("OK", f"no bars expected ({today_et} is not a US trading day)")
        return ("WARN", "no bars returned on a trading day — check https://status.databento.com/")
    aapl = bars.get("AAPL", {})
    needed = {"price", "open", "high", "low", "close", "volume"}
    missing = needed - set(aapl.keys())
    if missing:
        return ("WARN", f"missing fields: {sorted(missing)}")
    vol = aapl.get('volume')
    vol_str = f"{vol:,.0f}" if isinstance(vol, (int, float)) and not isinstance(vol, bool) else "n/a"
    return ("OK", f"AAPL close={aapl.get('close')} vol={vol_str}")


def probe_benzinga_news() -> tuple[str, str]:
    """Benzinga /api/v2/news — primary news feed."""
    import httpx
    key = os.getenv("BENZINGA_API_KEY", "")
    if not key:
        return ("SKIP", "BENZINGA_API_KEY missing")
    r = httpx.get(
        "https://api.benzinga.com/api/v2/news",
        params={"token": key, "pageSize": 5, "displayOutput": "abstract"},
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if not isinstance(data, list) or not data:
        return ("WARN", "empty news list")
    row = data[0]
    if "id" not in row or "title" not in row:
        return ("WARN", f"unexpected shape: {sorted(row.keys())[:6]}")
    created = row.get('created') or ''
    created_str = str(created)[:19] if created else '?'
    return ("OK", f"{len(data)} items, latest id={row.get('id')} ({created_str})")


def probe_benzinga_quotes() -> tuple[str, str]:
    """Benzinga /api/v1/quoteDelayed — quotes endpoint (matches code path)."""
    import httpx
    key = os.getenv("BENZINGA_API_KEY", "")
    if not key:
        return ("SKIP", "BENZINGA_API_KEY missing")
    r = httpx.get(
        "https://api.benzinga.com/api/v1/quoteDelayed",
        params={"token": key, "symbols": "AAPL,MSFT"},
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if not data:
        return ("WARN", "empty quote payload")
    return ("OK", f"got quotes for {len(data) if hasattr(data, '__len__') else '?'} symbols")


def probe_benzinga_movers() -> tuple[str, str]:
    """Benzinga /api/v1/market/movers — movers endpoint (matches code path)."""
    import httpx
    key = os.getenv("BENZINGA_API_KEY", "")
    if not key:
        return ("SKIP", "BENZINGA_API_KEY missing")
    r = httpx.get(
        "https://api.benzinga.com/api/v1/market/movers",
        params={"token": key, "screenerQuery": "marketcap_gt_300000000",
                "from": "1d", "maxResults": 5},
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    if r.status_code in (400, 401, 403, 404):
        return ("WARN", f"HTTP {r.status_code} — likely tier-limited")
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    return ("OK", f"movers payload bytes={len(r.content)}")


def _bz_get(path: str, extra: dict[str, Any] | None = None) -> tuple[str, str]:
    """Generic Benzinga entitlement probe — returns OK/WARN/FAIL based on status."""
    import httpx
    key = os.getenv("BENZINGA_API_KEY", "")
    if not key:
        return ("SKIP", "BENZINGA_API_KEY missing")
    params: dict[str, Any] = {"token": key}
    if extra:
        params.update(extra)
    r = httpx.get(
        f"https://api.benzinga.com{path}",
        params=params,
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    if r.status_code == 200:
        body_len = len(r.content)
        # Try JSON shape sniff
        try:
            data = r.json()
            if isinstance(data, dict):
                summary = f"dict keys={sorted(data.keys())[:4]}"
            elif isinstance(data, list):
                summary = f"list len={len(data)}"
            else:
                summary = f"type={type(data).__name__}"
        except Exception:
            summary = f"non-JSON, bytes={body_len}"
        return ("OK", summary)
    if r.status_code in (401, 403):
        return ("WARN", f"HTTP {r.status_code} — token has no entitlement for this endpoint")
    if r.status_code == 404:
        return ("WARN", "HTTP 404 — endpoint moved or wrong shape")
    if r.status_code == 422:
        # 422 = endpoint reachable & authorised, but our params are insufficient → still "reachable"
        return ("OK", "HTTP 422 — endpoint authorised, needs different params (entitlement OK)")
    return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")


def probe_bz_fundamentals() -> tuple[str, str]:
    return _bz_get("/api/v2.1/fundamentals", {"symbols": "AAPL"})


def probe_bz_bars() -> tuple[str, str]:
    return _bz_get("/api/v2/bars", {"symbols": "AAPL", "interval": "1D", "from": "5d"})


def probe_bz_search() -> tuple[str, str]:
    return _bz_get("/api/v2/search", {"query": "Apple"})


def probe_bz_security() -> tuple[str, str]:
    return _bz_get("/api/v2/security", {"symbols": "AAPL"})


def probe_bz_instruments() -> tuple[str, str]:
    return _bz_get("/api/v2.1/instruments", {"query": "symbol:AAPL"})


def probe_bz_logos() -> tuple[str, str]:
    return _bz_get("/api/v2/logos", {"symbols": "AAPL"})


def probe_bz_ticker_detail() -> tuple[str, str]:
    return _bz_get("/api/v2/tickerDetail", {"symbols": "AAPL"})


def probe_bz_options_activity() -> tuple[str, str]:
    return _bz_get("/api/v2.1/calendar/options_activity", {"parameters[tickers]": "AAPL"})


def _uw_headers(key: str) -> dict[str, str]:
    """Standard UW header set (Bearer + mandatory client-id).

    v3 P-4a: ``UW-CLIENT-API-ID`` is documented as required in the UW
    public skill.md manifest. Set here so all UW probes are consistent
    with the production adapter (newsstack_fmp/ingest_unusual_whales.py).
    """
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "UW-CLIENT-API-ID": "100001",
    }


def probe_uw_options_flow() -> tuple[str, str]:
    """Unusual Whales /api/option-trades/flow-alerts — active UOA source.

    v3 P-3c: replaces the retired Benzinga ``/api/v2.1/calendar/options_activity``
    feed in production. Uses Bearer auth with ``UNUSUAL_WHALES_API_KEY``.
    """
    import httpx
    key = os.getenv("UNUSUAL_WHALES_API_KEY", "").strip()
    if not key:
        return ("SKIP", "UNUSUAL_WHALES_API_KEY missing")
    try:
        r = httpx.get(
            "https://api.unusualwhales.com/api/option-trades/flow-alerts",
            params={"ticker_symbol": "AAPL", "limit": "1"},
            headers=_uw_headers(key),
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        return ("FAIL", f"HTTP error: {exc}")
    if r.status_code == 401:
        return ("FAIL", "HTTP 401 — UW key invalid")
    if r.status_code == 403:
        return ("WARN", "HTTP 403 — endpoint not in plan tier")
    if r.status_code == 429:
        return ("WARN", "HTTP 429 — rate-limited")
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    try:
        data = r.json()
    except Exception:
        return ("WARN", "non-JSON response")
    if isinstance(data, dict):
        recs = data.get("data") or data.get("flow_alerts") or []
    else:
        recs = data if isinstance(data, list) else []
    return ("OK", f"AAPL flow-alerts {len(recs) if isinstance(recs, list) else '?'} record(s)")


def _uw_probe(path: str, params: dict[str, str] | None, label: str) -> tuple[str, str]:
    """Shared boilerplate for UW endpoint probes (v3 P-4b/d)."""
    import httpx
    key = os.getenv("UNUSUAL_WHALES_API_KEY", "").strip()
    if not key:
        return ("SKIP", "UNUSUAL_WHALES_API_KEY missing")
    try:
        r = httpx.get(
            f"https://api.unusualwhales.com{path}",
            params=params or {},
            headers=_uw_headers(key),
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        return ("FAIL", f"HTTP error: {exc}")
    if r.status_code == 401:
        return ("FAIL", "HTTP 401 — UW key invalid")
    if r.status_code == 403:
        return ("WARN", "HTTP 403 — endpoint not in plan tier")
    if r.status_code == 429:
        return ("WARN", "HTTP 429 — rate-limited")
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    try:
        data = r.json()
    except Exception:
        return ("WARN", "non-JSON response")
    if isinstance(data, dict):
        recs = data.get("data") or []
    else:
        recs = data if isinstance(data, list) else []
    n = len(recs) if isinstance(recs, list) else "?"
    return ("OK", f"{label} {n} record(s)")


def probe_uw_darkpool() -> tuple[str, str]:
    """Unusual Whales /api/darkpool/{ticker} — institutional prints (v3 P-4b)."""
    return _uw_probe("/api/darkpool/AAPL", {"limit": "1"}, "AAPL darkpool")


def probe_uw_spot_gex() -> tuple[str, str]:
    """Unusual Whales /api/stock/{ticker}/spot-exposures/strike — dealer GEX (v3 P-4b)."""
    return _uw_probe(
        "/api/stock/AAPL/spot-exposures/strike", None, "AAPL spot-gex",
    )


def probe_uw_market_tide() -> tuple[str, str]:
    """Unusual Whales /api/market/market-tide — net call/put premium (v3 P-4d)."""
    return _uw_probe("/api/market/market-tide", None, "market-tide")


def probe_uw_insider_transactions() -> tuple[str, str]:
    """Unusual Whales /api/insider/transactions — bulk Form-4 (v3 P-4c)."""
    return _uw_probe("/api/insider/transactions", {"limit": "1"}, "insider-tx")


def probe_bz_ownership() -> tuple[str, str]:
    return _bz_get("/api/v2.1/ownership", {"symbols": "AAPL"})


def probe_bz_calendar_earnings() -> tuple[str, str]:
    today = date.today().isoformat()
    return _bz_get(
        "/api/v2.1/calendar/earnings",
        {"parameters[date_from]": today, "parameters[date_to]": today},
    )


def probe_bz_news_top() -> tuple[str, str]:
    return _bz_get("/api/v2/news-top-stories", {"pageSize": 3})


def probe_bz_news_channels() -> tuple[str, str]:
    return _bz_get("/api/v2/channels")


def probe_bz_news_quantified() -> tuple[str, str]:
    """Benzinga /api/v2/newsquantified — quantified news analytics.

    Path is ``/api/v2/newsquantified`` (one word, per official docs and the
    benzinga-python-client). Auth uses ``?token=`` query param like the rest
    of the Benzinga endpoints — live tests confirmed both ``?token=`` and the
    ``Authorization`` header are accepted by the server, so we keep ``?token=``
    for consistency with the official client and the rest of our codebase.
    """
    return _bz_get("/api/v2/newsquantified", {"pagesize": 3})


def probe_finnhub_quote() -> tuple[str, str]:
    """Finnhub /quote — basic equity quote."""
    import httpx
    key = os.getenv("FINNHUB_API_KEY", "")
    if not key:
        return ("SKIP", "FINNHUB_API_KEY missing")
    r = httpx.get(
        "https://finnhub.io/api/v1/quote",
        params={"symbol": "AAPL", "token": key},
        timeout=15.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if "c" not in data:
        return ("WARN", f"missing c (current) in {sorted(data.keys())[:6]}")
    return ("OK", f"AAPL current={data.get('c')} prevClose={data.get('pc')}")


def probe_finnhub_social() -> tuple[str, str]:
    """Finnhub /stock/social-sentiment — premium endpoint, expect 403 on free tier."""
    import httpx
    key = os.getenv("FINNHUB_API_KEY", "")
    if not key:
        return ("SKIP", "FINNHUB_API_KEY missing")
    r = httpx.get(
        "https://finnhub.io/api/v1/stock/social-sentiment",
        params={"symbol": "AAPL", "token": key},
        timeout=15.0,
    )
    if r.status_code == 403:
        return ("WARN", "HTTP 403 — premium-only (expected on free tier; module disables this path)")
    if r.status_code == 429:
        return ("WARN", "HTTP 429 — rate-limited")
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if not isinstance(data, dict):
        return ("WARN", f"unexpected payload {type(data).__name__}")
    has_data = bool(data.get("reddit") or data.get("twitter"))
    return ("OK", f"social keys={sorted(data.keys())[:4]} has_data={has_data}")


def probe_tradingview_news() -> tuple[str, str]:
    """TradingView headlines (unofficial, no key)."""
    import httpx
    r = httpx.get(
        "https://news-headlines.tradingview.com/v2/view/headlines/symbol",
        params={"client": "web", "lang": "en", "symbol": "NASDAQ:AAPL"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15.0,
    )
    if r.status_code in (403, 503):
        return ("WARN", f"HTTP {r.status_code} — Cloudflare-blocked (intermittent)")
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    try:
        data = r.json()
    except Exception:
        return ("WARN", "non-JSON response")
    items = data.get("items") if isinstance(data, dict) else data
    if not items:
        return ("WARN", "empty headlines list")
    return ("OK", f"{len(items)} headlines for AAPL")


def probe_tradingview_ta() -> tuple[str, str]:
    """tradingview_ta library — TA summary fetch."""
    try:
        from tradingview_ta import Interval, TA_Handler
    except ImportError:
        return ("SKIP", "tradingview_ta not installed")
    h = TA_Handler(symbol="AAPL", screener="america", exchange="NASDAQ",
                   interval=Interval.INTERVAL_1_DAY)
    a = h.get_analysis()
    if not a:
        return ("WARN", "empty analysis")
    summ = a.summary
    return ("OK", f"AAPL 1D recommendation={summ.get('RECOMMENDATION')} buy={summ.get('BUY')} sell={summ.get('SELL')}")


def probe_nasdaq_trader() -> tuple[str, str]:
    """NasdaqTrader symbol directory — universe source."""
    import httpx
    r = httpx.get(
        "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt",
        timeout=20.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}")
    lines = r.text.splitlines()
    if len(lines) < 100:
        return ("WARN", f"only {len(lines)} lines")
    return ("OK", f"{len(lines):,} lines (header + symbols)")


def probe_openai() -> tuple[str, str]:
    """OpenAI /v1/models — auth + reachability (no token spend)."""
    import httpx
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        return ("SKIP", "OPENAI_API_KEY missing")
    r = httpx.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=15.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    models = [m.get("id") for m in data.get("data", [])]
    has_4o = any("gpt-4o" in m for m in models if m)
    return ("OK", f"{len(models)} models accessible, has gpt-4o={has_4o}")


def probe_newsapi_ai() -> tuple[str, str]:
    """NewsAPI.ai (Event Registry) — note: terminal stub is decommissioned,
    but scripts/smc_newsapi_ai.py is the active path."""
    import httpx
    key = os.getenv("NEWSAPI_AI_KEY", "")
    if not key:
        return ("SKIP", "NEWSAPI_AI_KEY missing")
    r = httpx.post(
        "https://eventregistry.org/api/v1/article/getArticles",
        json={
            "action": "getArticles",
            "keyword": "Apple",
            "articlesPage": 1,
            "articlesCount": 5,
            "articlesSortBy": "date",
            "lang": "eng",
            "apiKey": key,
        },
        timeout=45.0,
    )
    if r.status_code != 200:
        return ("FAIL", f"HTTP {r.status_code}: {r.text[:80]}")
    data = r.json()
    if isinstance(data, dict) and "error" in data:
        return ("WARN", f"API error: {data['error']}")
    articles = data.get("articles", {}).get("results", []) if isinstance(data, dict) else []
    if not articles:
        return ("WARN", "empty article list")
    return ("OK", f"{len(articles)} articles, latest={articles[0].get('date')}")


# ── Main ────────────────────────────────────────────────────────────


# Critical = a workflow surface we actually consume in prod.
# Non-critical = visibility only (entitlement-gated / retired endpoints kept
# in the table so a future re-grant or restoration is detected immediately).
PROBES: list[Probe] = [
    # FMP — universe, fundamentals, news, technicals
    Probe("FMP /stable/quote", probe_fmp_quote, critical=True),
    Probe("FMP /stable/treasury-rates", probe_fmp_treasury, critical=True),
    Probe("FMP /stable/news/stock-latest", probe_fmp_news, critical=True),
    Probe("FMP /stable/news/press-releases", probe_fmp_press, critical=True),
    Probe("FMP /stable/company-screener", probe_fmp_screener, critical=True),
    Probe("FMP /stable/technical-indicators", probe_fmp_technical, critical=True),
    # G2/D3 re-check 2026-05-12: mover seed + incremental ATR feeders.
    # Critical because run_open_prep falls back to per-symbol ATR fetches
    # (10× slower) if eod-bulk is missing, and mover_seed becomes empty.
    Probe("FMP /stable/biggest-gainers", probe_fmp_biggest_gainers, critical=True),
    Probe("FMP /stable/biggest-losers", probe_fmp_biggest_losers, critical=True),
    Probe("FMP /stable/most-actives", probe_fmp_most_actives, critical=True),
    Probe("FMP /stable/eod-bulk", probe_fmp_eod_bulk, critical=True),
    # Databento — primary market data
    Probe("Databento metadata.list_datasets", probe_databento_metadata, critical=True),
    Probe("Databento ohlcv-1d (AAPL,MSFT)", probe_databento_daily_bars, critical=True),
    # Benzinga — only news + earnings calendar are on the standard tier
    Probe("Benzinga /api/v2/news", probe_benzinga_news, critical=True),
    Probe("Benzinga /api/v2.1/calendar/earnings", probe_bz_calendar_earnings, critical=True),
    # Benzinga — entitlement-gated or retired (Pro-tier / data-license only).
    # Already short-circuited at runtime by _bz_http; kept here for visibility
    # so a future re-grant or URL restoration is detected immediately.
    Probe("Benzinga /api/v1/quoteDelayed", probe_benzinga_quotes, critical=False),
    Probe("Benzinga /api/v1/market/movers", probe_benzinga_movers, critical=False),
    Probe("Benzinga /api/v2/news/top", probe_bz_news_top, critical=False),
    Probe("Benzinga /api/v2/news/channels", probe_bz_news_channels, critical=False),
    Probe("Benzinga /api/v2/newsquantified", probe_bz_news_quantified, critical=False),
    Probe("Benzinga /api/v2.1/calendar/options_activity", probe_bz_options_activity, critical=False),
    # Unusual Whales — v3 P-3c: active UOA source replacing retired Benzinga options_activity
    Probe("UnusualWhales /api/option-trades/flow-alerts", probe_uw_options_flow, critical=True),
    # v3 P-4b/d: new UW surfaces — Basic-tier entitlement verified 2026-05-01
    # but not contractually guaranteed, so left non-critical.
    Probe("UnusualWhales /api/darkpool/{ticker}", probe_uw_darkpool, critical=False),
    Probe("UnusualWhales /api/stock/{ticker}/spot-exposures/strike", probe_uw_spot_gex, critical=False),
    Probe("UnusualWhales /api/market/market-tide", probe_uw_market_tide, critical=False),
    Probe("UnusualWhales /api/insider/transactions", probe_uw_insider_transactions, critical=False),
    Probe("Benzinga /api/v2.1/fundamentals", probe_bz_fundamentals, critical=False),
    Probe("Benzinga /api/v2.1/ownership", probe_bz_ownership, critical=False),
    Probe("Benzinga /api/v2.1/instruments", probe_bz_instruments, critical=False),
    Probe("Benzinga /api/v2/bars", probe_bz_bars, critical=False),
    Probe("Benzinga /api/v2/search", probe_bz_search, critical=False),
    Probe("Benzinga /api/v2/security", probe_bz_security, critical=False),
    Probe("Benzinga /api/v2/tickerDetail", probe_bz_ticker_detail, critical=False),
    Probe("Benzinga /api/v2/logos", probe_bz_logos, critical=False),
    # Finnhub
    Probe("Finnhub /quote", probe_finnhub_quote, critical=True),
    Probe("Finnhub /stock/social-sentiment", probe_finnhub_social, critical=False),
    # TradingView
    Probe("TradingView headlines (unofficial)", probe_tradingview_news, critical=True),
    Probe("TradingView TA library", probe_tradingview_ta, critical=True),
    # Misc
    Probe("NasdaqTrader symbol directory", probe_nasdaq_trader, critical=True),
    Probe("OpenAI /v1/models", probe_openai, critical=True),
    Probe("NewsAPI.ai (Event Registry)", probe_newsapi_ai, critical=True),
]


# ── Public Python entry points (importable by workflow runners) ─────


def run_probes(
    probes: list[Probe] | None = None,
    *,
    critical_only: bool = False,
    quiet: bool = False,
) -> list[ProbeResult]:
    """Run probes and return a list of :class:`ProbeResult`.

    ``critical_only=True`` skips probes tagged ``critical=False``.
    ``quiet=True`` suppresses the per-row pretty print (used by ``--json``).
    """
    selected = list(probes if probes is not None else PROBES)
    if critical_only:
        selected = [p for p in selected if p.critical]
    return [_run(p, quiet=quiet) for p in selected]


def summarise(results: list[ProbeResult]) -> dict[str, int]:
    counts = {"OK": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    counts["BLOCKING"] = sum(1 for r in results if r.is_blocking)
    return counts


def preflight_or_die(
    *,
    notify: bool = True,
    quiet: bool = True,
    raise_on_block: bool = True,
) -> list[ProbeResult]:
    """Run all CRITICAL probes; alert + raise if any are blocking.

    Designed to be called once at the top of any workflow runner::

        from scripts.probe_providers import preflight_or_die
        preflight_or_die()  # raises SystemExit(1) if a critical surface fails

    With ``raise_on_block=False`` the function returns the results without
    raising so callers can decide their own handling.
    """
    load_dotenv()
    results = run_probes(critical_only=True, quiet=quiet)
    blocking = [r for r in results if r.is_blocking]
    if blocking:
        _log_blocking(blocking)
        if notify:
            try:
                _notify_blocking(blocking)
            except Exception:
                logger.exception("preflight notification dispatch failed")
        if raise_on_block:
            raise SystemExit(1)
    return results


# ── Notification dispatch (reuses terminal_notifications channels) ──


# Maps a substring of the probe name to the provider's public status page.
# Surfaced in alert bodies so the on-call can one-click verify upstream
# state instead of guessing whether it's our pipeline or theirs.
_STATUS_PAGES: dict[str, str] = {
    "Databento": "https://status.databento.com/",
    "FMP": "https://status.financialmodelingprep.com/",
    "Benzinga": "https://status.benzinga.com/",
    "Finnhub": "https://status.finnhub.io/",
    "OpenAI": "https://status.openai.com/",
    "TradingView": "https://status.tradingview.com/",
}


def _status_pages_for(blocking: list[ProbeResult]) -> list[str]:
    """Return the de-duplicated set of status-page URLs that cover the
    blocking probes, in the order they first appear."""
    seen: list[str] = []
    for r in blocking:
        for tag, url in _STATUS_PAGES.items():
            if tag in r.name and url not in seen:
                seen.append(url)
    return seen


def _format_alert(blocking: list[ProbeResult]) -> tuple[str, str]:
    """Return (short_title, multi-line body) describing the failures."""
    title = f"⚠️ skipp-algo preflight: {len(blocking)} provider(s) down"
    lines = [title, ""]
    for r in blocking:
        lat = f"{int(r.latency_ms)}ms" if r.latency_ms is not None else "—"
        lines.append(f"• {r.name} [{r.status} {lat}] {r.detail}")
    pages = _status_pages_for(blocking)
    if pages:
        lines.append("")
        lines.append("Provider status pages:")
        for url in pages:
            lines.append(f"  {url}")
    return title, "\n".join(lines)


def _log_blocking(blocking: list[ProbeResult]) -> None:
    for r in blocking:
        logger.warning(
            "preflight BLOCK %s status=%s detail=%s", r.name, r.status, r.detail
        )


def _notify_blocking(blocking: list[ProbeResult]) -> None:
    """Best-effort dispatch via Telegram / Discord / Pushover if configured."""
    try:
        from terminal_notifications import (  # type: ignore[import-not-found]
            NotifyConfig,
            _send_discord,
            _send_pushover,
            _send_telegram,
        )
    except Exception:
        logger.warning("terminal_notifications unavailable; skipping push alert")
        return
    cfg = NotifyConfig()
    if not cfg.has_any_channel:
        logger.info("no notification channels configured; skipping alert")
        return
    title, body = _format_alert(blocking)
    if cfg.telegram_bot_token and cfg.telegram_chat_id:
        _send_telegram(cfg.telegram_bot_token, cfg.telegram_chat_id, body)
    if cfg.discord_webhook_url:
        _send_discord(cfg.discord_webhook_url, body)
    if cfg.pushover_app_token and cfg.pushover_user_key:
        _send_pushover(cfg.pushover_app_token, cfg.pushover_user_key, title, body)


# ── CLI ─────────────────────────────────────────────────────────────


def _print_summary(results: list[ProbeResult]) -> None:
    counts = summarise(results)
    print("─" * 100)
    print(
        f"{BOLD}Summary:{RESET} "
        f"{GREEN}{counts.get('OK', 0)} OK{RESET}, "
        f"{YELLOW}{counts.get('WARN', 0)} WARN{RESET}, "
        f"{RED}{counts.get('FAIL', 0)} FAIL{RESET}, "
        f"{DIM}{counts.get('SKIP', 0)} SKIP{RESET}  |  "
        f"{(RED if counts['BLOCKING'] else GREEN)}{counts['BLOCKING']} blocking{RESET}"
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Probe every external data/news provider used by skipp-algo.",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="only run CRITICAL probes; exit 1 if any are not OK.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit JSON results to stdout (suppresses the pretty table).",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="on blocking failure, push to Telegram/Discord/Pushover if "
             "TERMINAL_* env vars are set.",
    )
    args = parser.parse_args(argv)

    if not args.json:
        print(f"\n{BOLD}Provider reachability + data-shape probe{RESET}")
        print(ROW_FMT.format(
            name="PROVIDER", status="STATUS", latency="LATENCY", detail="DETAIL",
        ))
        print("─" * 100)

    results = run_probes(critical_only=args.preflight, quiet=args.json)
    counts = summarise(results)

    if args.json:
        print(json.dumps(
            {
                "results": [asdict(r) for r in results],
                "counts": counts,
            },
            indent=2,
            default=str,
        ))
    else:
        _print_summary(results)

    if counts["BLOCKING"] > 0 and args.notify:
        try:
            _notify_blocking([r for r in results if r.is_blocking])
        except Exception:
            logger.exception("notification dispatch failed")

    if args.preflight:
        return 1 if counts["BLOCKING"] > 0 else 0
    # Default mode preserves previous behaviour: only fail on hard FAIL.
    return 0 if counts.get("FAIL", 0) == 0 else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
