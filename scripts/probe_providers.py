"""One-shot reachability + data-shape probe for every external data/news
provider used by the skipp-algo stack.

Run: PYTHONPATH=. python scripts/probe_providers.py

Exit code 0 = all providers reached at least at the connectivity layer.
Each row reports: PROVIDER | STATUS | LATENCY | DETAIL
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()

# ── Pretty output ───────────────────────────────────────────────────

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

ROW_FMT = "{name:<32} {status:<8} {latency:>8} {detail}"


def _emit(name: str, status: str, latency_ms: float | None, detail: str) -> None:
    color = {"OK": GREEN, "WARN": YELLOW, "FAIL": RED, "SKIP": DIM}.get(status, "")
    lat = f"{int(latency_ms)}ms" if latency_ms is not None else "—"
    print(ROW_FMT.format(
        name=name,
        status=f"{color}{status}{RESET}",
        latency=lat,
        detail=detail,
    ))


def _run(name: str, fn: Callable[[], tuple[str, str]]) -> tuple[str, float | None]:
    t0 = time.monotonic()
    try:
        status, detail = fn()
    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        msg = f"{type(exc).__name__}: {exc}"
        if len(msg) > 120:
            msg = msg[:117] + "..."
        _emit(name, "FAIL", latency_ms, msg)
        return ("FAIL", latency_ms)
    latency_ms = (time.monotonic() - t0) * 1000
    _emit(name, status, latency_ms, detail)
    return (status, latency_ms)


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
    return ("OK", f"AAPL price={price} mcap={row.get('marketCap'):,}")


def probe_fmp_treasury() -> tuple[str, str]:
    """FMP /stable/treasury-rates — Lane 1 retired-endpoint replacement."""
    import httpx
    from datetime import date, timedelta
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
    """Databento ohlcv-1d for AAPL — actual bar fetch."""
    key = os.getenv("DATABENTO_API_KEY", "")
    if not key:
        return ("SKIP", "DATABENTO_API_KEY missing")
    from terminal_databento import fetch_databento_daily_bars
    bars = fetch_databento_daily_bars(["AAPL", "MSFT"], lookback_days=5)
    if not bars:
        return ("WARN", "no bars returned (market closed or no data)")
    aapl = bars.get("AAPL", {})
    needed = {"price", "open", "high", "low", "close", "volume"}
    missing = needed - set(aapl.keys())
    if missing:
        return ("WARN", f"missing fields: {sorted(missing)}")
    return ("OK", f"AAPL close={aapl.get('close')} vol={aapl.get('volume'):,}")


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
    return ("OK", f"{len(data)} items, latest id={row.get('id')} ({row.get('created', '?')[:19]})")


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
        return ("WARN", f"HTTP 404 — endpoint moved or wrong shape")
    if r.status_code == 422:
        # 422 = endpoint reachable & authorised, but our params are insufficient → still "reachable"
        return ("OK", f"HTTP 422 — endpoint authorised, needs different params (entitlement OK)")
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


def probe_bz_ownership() -> tuple[str, str]:
    return _bz_get("/api/v2.1/ownership", {"symbols": "AAPL"})


def probe_bz_calendar_earnings() -> tuple[str, str]:
    return _bz_get("/api/v2.1/calendar/earnings", {"parameters[date_from]": "2026-04-27"})


def probe_bz_news_top() -> tuple[str, str]:
    return _bz_get("/api/v2/news/top", {"pageSize": 3})


def probe_bz_news_channels() -> tuple[str, str]:
    return _bz_get("/api/v2/news/channels")


def probe_bz_news_quantified() -> tuple[str, str]:
    return _bz_get("/api/v2/news/quantified", {"pageSize": 3})


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
        from tradingview_ta import TA_Handler, Interval
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


PROBES: list[tuple[str, Callable[[], tuple[str, str]]]] = [
    ("FMP /stable/quote", probe_fmp_quote),
    ("FMP /stable/treasury-rates", probe_fmp_treasury),
    ("FMP /stable/news/stock-latest", probe_fmp_news),
    ("FMP /stable/news/press-releases", probe_fmp_press),
    ("FMP /stable/company-screener", probe_fmp_screener),
    ("FMP /stable/technical-indicators", probe_fmp_technical),
    ("Databento metadata.list_datasets", probe_databento_metadata),
    ("Databento ohlcv-1d (AAPL,MSFT)", probe_databento_daily_bars),
    ("Benzinga /api/v2/news", probe_benzinga_news),
    ("Benzinga /api/v1/quoteDelayed", probe_benzinga_quotes),
    ("Benzinga /api/v1/market/movers", probe_benzinga_movers),
    ("Benzinga /api/v2/news/top", probe_bz_news_top),
    ("Benzinga /api/v2/news/channels", probe_bz_news_channels),
    ("Benzinga /api/v2/news/quantified", probe_bz_news_quantified),
    ("Benzinga /api/v2.1/calendar/earnings", probe_bz_calendar_earnings),
    ("Benzinga /api/v2.1/calendar/options_activity", probe_bz_options_activity),
    ("Benzinga /api/v2.1/fundamentals", probe_bz_fundamentals),
    ("Benzinga /api/v2.1/ownership", probe_bz_ownership),
    ("Benzinga /api/v2.1/instruments", probe_bz_instruments),
    ("Benzinga /api/v2/bars", probe_bz_bars),
    ("Benzinga /api/v2/search", probe_bz_search),
    ("Benzinga /api/v2/security", probe_bz_security),
    ("Benzinga /api/v2/tickerDetail", probe_bz_ticker_detail),
    ("Benzinga /api/v2/logos", probe_bz_logos),
    ("Finnhub /quote", probe_finnhub_quote),
    ("Finnhub /stock/social-sentiment", probe_finnhub_social),
    ("TradingView headlines (unofficial)", probe_tradingview_news),
    ("TradingView TA library", probe_tradingview_ta),
    ("NasdaqTrader symbol directory", probe_nasdaq_trader),
    ("OpenAI /v1/models", probe_openai),
    ("NewsAPI.ai (Event Registry)", probe_newsapi_ai),
]


def main() -> int:
    print(f"\n{BOLD}Provider reachability + data-shape probe{RESET}")
    print(ROW_FMT.format(name="PROVIDER", status="STATUS", latency="LATENCY", detail="DETAIL"))
    print("─" * 100)
    counts = {"OK": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    for name, fn in PROBES:
        status, _ = _run(name, fn)
        counts[status] = counts.get(status, 0) + 1
    print("─" * 100)
    print(
        f"{BOLD}Summary:{RESET} "
        f"{GREEN}{counts.get('OK', 0)} OK{RESET}, "
        f"{YELLOW}{counts.get('WARN', 0)} WARN{RESET}, "
        f"{RED}{counts.get('FAIL', 0)} FAIL{RESET}, "
        f"{DIM}{counts.get('SKIP', 0)} SKIP{RESET}"
    )
    return 0 if counts.get("FAIL", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
