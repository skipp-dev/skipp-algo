"""Lane 9 (provider-boundary audit follow-up, 2026-04-27): regression tests
for ``Retry-After`` honoring in the newsstack HTTP retry helpers.

Two retry loops needed the same fix as ``scripts.smc_fmp_client._get``:

* ``newsstack_fmp.ingest_fmp.FmpAdapter._safe_get`` retried 429 with
  ``time.sleep(2 ** attempt)`` (2s, 4s) and ignored the server-supplied
  ``Retry-After`` header. On real rate-limits this burned through all
  retries in ~6s while the server was still asking us to wait 30+s.
* ``newsstack_fmp._bz_http._request_with_retry`` had the identical
  pattern for the Benzinga adapters.

Both now consult ``Retry-After`` (RFC 9110 §10.2.3, both seconds and
HTTP-date forms), wait at least the suggested duration, and cap at 60s
so a misconfigured ``Retry-After: 86400`` cannot wedge the poller.
"""

from __future__ import annotations

import httpx
import pytest
from datetime import UTC


# ── _parse_retry_after_seconds (both copies) ────────────────────────


@pytest.mark.parametrize(
    "module_path",
    [
        "newsstack_fmp.ingest_fmp",
        "newsstack_fmp._bz_http",
    ],
)
class TestParseRetryAfterSeconds:
    def test_accepts_integer_seconds_form(self, module_path):
        import importlib
        mod = importlib.import_module(module_path)
        assert mod._parse_retry_after_seconds("0") == 0.0
        assert mod._parse_retry_after_seconds("12") == 12.0
        assert mod._parse_retry_after_seconds("12.5") == 12.5

    def test_accepts_http_date_form(self, module_path):
        import importlib
        from datetime import datetime, timedelta, timezone
        from email.utils import format_datetime
        mod = importlib.import_module(module_path)
        future = datetime.now(UTC) + timedelta(seconds=30)
        out = mod._parse_retry_after_seconds(format_datetime(future, usegmt=True))
        assert out is not None
        assert 25 <= out <= 35  # tolerance for clock skew

    def test_returns_none_for_garbage(self, module_path):
        import importlib
        mod = importlib.import_module(module_path)
        for v in (None, "", "not-a-date", object()):
            assert mod._parse_retry_after_seconds(v) is None

    def test_clamps_negative_to_zero(self, module_path):
        import importlib
        from datetime import datetime, timedelta, timezone
        from email.utils import format_datetime
        mod = importlib.import_module(module_path)
        assert mod._parse_retry_after_seconds("-5") == 0.0
        past = datetime.now(UTC) - timedelta(seconds=30)
        assert mod._parse_retry_after_seconds(format_datetime(past, usegmt=True)) == 0.0


# ── _safe_get / _request_with_retry honor Retry-After ────────────────


def _fake_responses(*responses):
    """Build a fake httpx.Client.get that returns the given sequence."""
    iterator = iter(responses)
    def _get(url, params=None, **kwargs):
        return next(iterator)
    return _get


def _make_response(status: int, retry_after: str | None = None) -> httpx.Response:
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    request = httpx.Request("GET", "https://example.test/x")
    return httpx.Response(status_code=status, headers=headers, request=request, content=b"[]")


class TestFmpAdapterSafeGetHonorsRetryAfter:
    def test_429_with_retry_after_seconds_waits_at_least_hint(self, monkeypatch):
        from newsstack_fmp import ingest_fmp

        sleeps: list[float] = []
        monkeypatch.setattr(ingest_fmp.time, "sleep", lambda d: sleeps.append(d))

        adapter = ingest_fmp.FmpAdapter(api_key="k")
        monkeypatch.setattr(
            adapter.client,
            "get",
            _fake_responses(
                _make_response(429, retry_after="7"),
                _make_response(200),
            ),
        )
        adapter._safe_get("https://example.test/x", {"apikey": "k"})

        # Backoff is 2**1 == 2s; with the 7s hint we must sleep >=7s.
        assert sleeps and sleeps[0] >= 7.0, sleeps

    def test_429_without_retry_after_falls_back_to_exponential(self, monkeypatch):
        from newsstack_fmp import ingest_fmp

        sleeps: list[float] = []
        monkeypatch.setattr(ingest_fmp.time, "sleep", lambda d: sleeps.append(d))

        adapter = ingest_fmp.FmpAdapter(api_key="k")
        monkeypatch.setattr(
            adapter.client,
            "get",
            _fake_responses(
                _make_response(429),
                _make_response(200),
            ),
        )
        adapter._safe_get("https://example.test/x", {"apikey": "k"})

        # Pure exponential: 2**1 == 2s.
        assert sleeps == [2]

    def test_pathological_retry_after_capped_at_60s(self, monkeypatch):
        from newsstack_fmp import ingest_fmp

        sleeps: list[float] = []
        monkeypatch.setattr(ingest_fmp.time, "sleep", lambda d: sleeps.append(d))

        adapter = ingest_fmp.FmpAdapter(api_key="k")
        monkeypatch.setattr(
            adapter.client,
            "get",
            _fake_responses(
                _make_response(429, retry_after="86400"),
                _make_response(200),
            ),
        )
        adapter._safe_get("https://example.test/x", {"apikey": "k"})

        assert sleeps and all(d <= 60.0 for d in sleeps), sleeps


class TestBzHttpRequestWithRetryHonorsRetryAfter:
    def test_429_with_retry_after_seconds_waits_at_least_hint(self, monkeypatch):
        from newsstack_fmp import _bz_http

        sleeps: list[float] = []
        monkeypatch.setattr(_bz_http.time, "sleep", lambda d: sleeps.append(d))

        client = httpx.Client()
        monkeypatch.setattr(
            client,
            "get",
            _fake_responses(
                _make_response(429, retry_after="7"),
                _make_response(200),
            ),
        )
        _bz_http._request_with_retry(client, "https://example.test/x", {"token": "k"})

        # Backoff is 2**0 == 1s; with the 7s hint we must sleep >=7s.
        assert sleeps and sleeps[0] >= 7.0, sleeps

    def test_429_without_retry_after_falls_back_to_exponential(self, monkeypatch):
        from newsstack_fmp import _bz_http

        sleeps: list[float] = []
        monkeypatch.setattr(_bz_http.time, "sleep", lambda d: sleeps.append(d))
        # Pin the jitter source to a non-zero value so ``@resilient`` always
        # produces ``delay > 0`` and actually invokes ``sleep`` (otherwise the
        # full-jitter ``capped * rng()`` can land on 0.0 and skip the call,
        # leaving ``sleeps`` empty and flaking the assertion below).
        monkeypatch.setattr(_bz_http, "_rng", lambda: 0.5)

        client = httpx.Client()
        monkeypatch.setattr(
            client,
            "get",
            _fake_responses(
                _make_response(429),
                _make_response(200),
            ),
        )
        _bz_http._request_with_retry(client, "https://example.test/x", {"token": "k"})

        # Pure-exponential cap is 2**0 == 1s; with rng pinned to 0.5 the
        # delay is exactly 0.5s (well within the [0, 1.0) full-jitter window).
        assert sleeps and 0.0 < sleeps[0] <= 1.0, sleeps

    def test_pathological_retry_after_capped_at_60s(self, monkeypatch):
        from newsstack_fmp import _bz_http

        sleeps: list[float] = []
        monkeypatch.setattr(_bz_http.time, "sleep", lambda d: sleeps.append(d))

        client = httpx.Client()
        monkeypatch.setattr(
            client,
            "get",
            _fake_responses(
                _make_response(429, retry_after="86400"),
                _make_response(200),
            ),
        )
        _bz_http._request_with_retry(client, "https://example.test/x", {"token": "k"})

        assert sleeps and all(d <= 60.0 for d in sleeps), sleeps
