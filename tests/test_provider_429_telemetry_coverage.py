"""429 rate-limit telemetry coverage for FMP / Databento / Finnhub.

The deep-review found _bz_http was the ONLY 429 choke point (Benzinga/Massive/UW),
so FMP (highest-volume), Databento and Finnhub 429s emitted no telemetry and never
tripped the lo-provider-rate-limited alert. Each provider's central HTTP/retry
path now records a hit (fail-soft), bucketed by its provider_usage name.
"""
from __future__ import annotations

import types
import urllib.error

import httpx
import pytest


def test_fmp_ingest_429_records_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    from newsstack_fmp import ingest_fmp, provider_usage

    hits: list[str] = []
    monkeypatch.setattr(provider_usage, "record_rate_limit_hit", lambda p: hits.append(p))
    monkeypatch.setattr(ingest_fmp.time, "sleep", lambda *_a: None)

    state = {"first": True}

    def _get(url: str, params: dict | None = None) -> httpx.Response:
        code = 429 if state["first"] else 200
        state["first"] = False
        return httpx.Response(code, request=httpx.Request("GET", url), json=[])

    adapter = ingest_fmp.FmpAdapter("k")
    monkeypatch.setattr(adapter, "client", types.SimpleNamespace(get=_get))
    adapter._safe_get("https://financialmodelingprep.com/stable/x", {})
    assert hits == ["fmp"]  # exactly one 429 recorded before the retry rescued it


def test_databento_429_records_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    import databento_client
    from newsstack_fmp import provider_usage

    hits: list[str] = []
    monkeypatch.setattr(provider_usage, "record_rate_limit_hit", lambda p: hits.append(p))
    monkeypatch.setattr(databento_client, "_normalize_tls_certificate_env", lambda: None)

    class _TS:
        def get_range(self, **_kw):
            raise RuntimeError("HTTP 429: too many requests")

    client = types.SimpleNamespace(timeseries=_TS())
    with pytest.raises(RuntimeError):
        databento_client._databento_get_range_with_retry(
            client, context="t", max_attempts=1, dataset="X", symbols=["A"], schema="ohlcv-1m"
        )
    assert hits == ["databento"]


def test_finnhub_429_records_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    import terminal_finnhub
    from newsstack_fmp import provider_usage

    hits: list[str] = []
    monkeypatch.setattr(provider_usage, "record_rate_limit_hit", lambda p: hits.append(p))

    def _raise(*_a, **_k):
        raise urllib.error.HTTPError("http://x", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(terminal_finnhub, "urlopen", _raise)
    terminal_finnhub._get("/quote", {"symbol": "AAPL"}, api_key="k")
    assert "finnhub" in hits


def test_benzinga_fetch_news_429_records_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    # The Benzinga/Massive news firehose (BenzingaRestAdapter.fetch_news) runs its
    # OWN retry loop and never flowed through _bz_http's shared 429 recorder, so the
    # highest-volume Benzinga lane emitted no throttle telemetry. Wire it here.
    from newsstack_fmp import ingest_benzinga, provider_usage

    hits: list[str] = []
    monkeypatch.setattr(provider_usage, "record_rate_limit_hit", lambda p: hits.append(p))
    monkeypatch.setattr(ingest_benzinga.time, "sleep", lambda *_a: None)

    adapter = ingest_benzinga.BenzingaRestAdapter("k", provider="massive")
    state = {"first": True}

    def _get(u: str, params: dict | None = None) -> httpx.Response:
        code = 429 if state["first"] else 200
        state["first"] = False
        return httpx.Response(code, request=httpx.Request("GET", adapter.base_url), json=[])

    monkeypatch.setattr(adapter, "client", types.SimpleNamespace(get=_get))
    assert adapter.fetch_news() == []
    assert hits == ["massive"]  # exactly one 429 recorded before the retry rescued it


def test_daemon_fmp_loader_429_records_hit_and_backs_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Grenzgänger-Sweep D3 (2026-08-18): the daemon's own FMP surface had no
    # 429 telemetry and a 0s-backoff retry — throttled load was doubled and
    # lo-provider-rate-limited stayed blind to the daemon.
    from newsstack_fmp import provider_usage
    from services.live_overlay_daemon import fmp_data_loader

    hits: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        provider_usage, "record_rate_limit_hit", lambda p, **_k: hits.append(p)
    )
    monkeypatch.setattr(provider_usage, "record", lambda p, **_k: None)
    monkeypatch.setattr(fmp_data_loader.time, "sleep", lambda s: sleeps.append(s))

    state = {"first": True}

    def _get(url: str, timeout: float | None = None) -> httpx.Response:
        code = 429 if state["first"] else 200
        headers = {"Retry-After": "7"} if state["first"] else {}
        state["first"] = False
        return httpx.Response(
            code, request=httpx.Request("GET", url), json=[], headers=headers
        )

    loader = fmp_data_loader.FMPDataLoader(api_key="k")
    monkeypatch.setattr(loader, "session", types.SimpleNamespace(get=_get))

    rows = loader._fetch_chart_rows("SPY", "5min", None, None)

    assert rows == []
    assert hits == ["fmp"]
    assert sleeps == [7.0]  # capped Retry-After honoured, not a 0s retry


def test_daemon_fmp_get_quote_429_records_hit_and_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from newsstack_fmp import provider_usage
    from services.live_overlay_daemon import fmp_data_loader

    hits: list[str] = []
    monkeypatch.setattr(
        provider_usage, "record_rate_limit_hit", lambda p, **_k: hits.append(p)
    )
    monkeypatch.setattr(provider_usage, "record", lambda p, **_k: None)

    def _get(url: str, timeout: float | None = None) -> httpx.Response:
        return httpx.Response(429, request=httpx.Request("GET", url), json=[])

    loader = fmp_data_loader.FMPDataLoader(api_key="k")
    monkeypatch.setattr(loader, "session", types.SimpleNamespace(get=_get))

    assert loader.get_quote("^VIX") is None
    assert hits == ["fmp"]


def test_daemon_fmp_loader_records_response_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Grenzgänger-Sweep D4 (2026-08-18): the monthly quota gate compared an
    # incomplete numerator — the daemon's 24/7 quote volume never counted.
    from newsstack_fmp import provider_usage
    from services.live_overlay_daemon import fmp_data_loader

    recorded: list[dict] = []
    monkeypatch.setattr(
        provider_usage,
        "record",
        lambda p, **k: recorded.append({"provider": p, **k}),
    )

    def _get(url: str, timeout: float | None = None) -> httpx.Response:
        return httpx.Response(
            200, request=httpx.Request("GET", url), json=[{"price": 15.5}]
        )

    loader = fmp_data_loader.FMPDataLoader(api_key="k")
    monkeypatch.setattr(loader, "session", types.SimpleNamespace(get=_get))

    assert loader.get_quote("^VIX") == 15.5
    assert len(recorded) == 1
    assert recorded[0]["provider"] == "fmp"
    assert recorded[0]["response_bytes"] > 0
    assert recorded[0]["consumer"] == "live_overlay_daemon.fmp_data_loader"
