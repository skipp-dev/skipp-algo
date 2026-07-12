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
