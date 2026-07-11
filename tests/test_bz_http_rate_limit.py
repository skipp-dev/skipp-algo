"""429 rate-limit telemetry: _bz_http counts a hit per 429, bucketed by URL host.

The vendors send no X-RateLimit-* headers (verified 2026-07-11), so a 429 counter
is the only "we are being throttled" signal. Recorded at the single 429 choke
point (_request_with_status_retry), shared by Benzinga / Massive / Unusual Whales.
"""
from __future__ import annotations

import types

import httpx
import pytest

from newsstack_fmp import _bz_http, provider_usage


def _client_429_then_ok() -> types.SimpleNamespace:
    """A client whose first GET is 429 and every later GET is 200."""
    state = {"first": True}

    def _get(url: str, params: dict | None = None) -> httpx.Response:
        code = 429 if state["first"] else 200
        state["first"] = False
        return httpx.Response(code, request=httpx.Request("GET", url))

    return types.SimpleNamespace(get=_get)


def _client_status(code: int) -> types.SimpleNamespace:
    state = {"first": True}

    def _get(url: str, params: dict | None = None) -> httpx.Response:
        c = code if state["first"] else 200
        state["first"] = False
        return httpx.Response(c, request=httpx.Request("GET", url))

    return types.SimpleNamespace(get=_get)


def test_429_records_one_rate_limit_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    hits: list[str] = []
    monkeypatch.setattr(provider_usage, "record_rate_limit_hit", lambda p: hits.append(p))
    monkeypatch.setattr(_bz_http, "_sleep", lambda s: None)
    monkeypatch.setattr(_bz_http, "_rng", lambda: 0.0)

    resp = _bz_http._request_with_status_retry(
        _client_429_then_ok(), "https://api.massive.com/benzinga/v2/news?limit=1", {}
    )
    assert resp.status_code == 200  # the retry rescued the call
    assert hits == ["massive"]  # exactly one 429 recorded, bucketed by URL host


def test_5xx_retryable_is_not_a_rate_limit_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    hits: list[str] = []
    monkeypatch.setattr(provider_usage, "record_rate_limit_hit", lambda p: hits.append(p))
    monkeypatch.setattr(_bz_http, "_sleep", lambda s: None)
    monkeypatch.setattr(_bz_http, "_rng", lambda: 0.0)

    _bz_http._request_with_status_retry(
        _client_status(503), "https://api.benzinga.com/api/v2/news", {}
    )
    assert hits == []  # a 5xx is retried but is NOT throttling


def test_provider_from_url_matches_usage_provider_buckets() -> None:
    assert _bz_http._provider_from_url("https://api.massive.com/benzinga/v2/news") == "massive"
    assert _bz_http._provider_from_url("https://api.unusualwhales.com/api/x") == "unusual_whales"
    assert _bz_http._provider_from_url("https://api.benzinga.com/api/v2/news") == "benzinga"
