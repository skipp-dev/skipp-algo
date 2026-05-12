"""Tests for the G6 per-endpoint usage instrumentation on ``FMPClient``.

Provider-audit (2026-05-12) revealed that we could not observe which FMP
endpoints a given pipeline invocation actually exercises — only aggregate
plan-level counters at the provider dashboard. The G6 instrumentation adds
process-local per-path counters so end-of-run audits can capture exactly
which endpoints were hit and how often.

This test suite covers:

- Empty stats on a fresh client instance.
- ``calls`` increment on every ``_execute_get`` invocation.
- ``errors`` increment when the request raises (HTTPError, URLError,
  UpstreamPayloadError, and circuit-open RuntimeError).
- ``get_endpoint_usage_stats`` returns a deep copy so mutations by callers
  cannot corrupt internal state.
- Per-path bucketing keeps independent counters.
"""

from __future__ import annotations

import urllib.error
from typing import Any

import pytest

from open_prep import macro
from open_prep.macro import FMPClient, UpstreamPayloadError


def test_endpoint_usage_stats_empty_on_fresh_client() -> None:
    client = FMPClient(api_key="K")
    assert client.get_endpoint_usage_stats() == {}


def test_endpoint_usage_stats_counts_successful_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K", retry_attempts=1, retry_backoff_seconds=0.0)
    monkeypatch.setattr(client, "_request_once", lambda path, params: [{"ok": True}])

    client._execute_get("/stable/quote", {"symbol": "AAPL"}, use_circuit_breaker=False)
    client._execute_get("/stable/quote", {"symbol": "MSFT"}, use_circuit_breaker=False)
    client._execute_get("/stable/profile", {"symbol": "AAPL"}, use_circuit_breaker=False)

    stats = client.get_endpoint_usage_stats()
    assert stats == {
        "/stable/quote": {"calls": 2, "errors": 0, "empty_responses": 0},
        "/stable/profile": {"calls": 1, "errors": 0, "empty_responses": 0},
    }


def test_endpoint_usage_stats_records_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K", retry_attempts=1, retry_backoff_seconds=0.0)

    def boom(path: str, params: dict[str, Any]) -> Any:
        raise urllib.error.HTTPError(
            url="http://x", code=404, msg="not found", hdrs=None, fp=None
        )

    monkeypatch.setattr(client, "_request_once", boom)
    monkeypatch.setattr(macro.time, "sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="HTTP 404"):
        client._execute_get("/stable/retired-path", {}, use_circuit_breaker=False)

    stats = client.get_endpoint_usage_stats()
    assert stats["/stable/retired-path"] == {
        "calls": 1,
        "errors": 1,
        "empty_responses": 0,
    }


def test_endpoint_usage_stats_records_url_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K", retry_attempts=1, retry_backoff_seconds=0.0)

    def boom(path: str, params: dict[str, Any]) -> Any:
        raise urllib.error.URLError("dns")

    monkeypatch.setattr(client, "_request_once", boom)
    monkeypatch.setattr(macro.time, "sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="network error"):
        client._execute_get("/stable/quote", {}, use_circuit_breaker=False)

    stats = client.get_endpoint_usage_stats()
    assert stats["/stable/quote"]["errors"] == 1
    assert stats["/stable/quote"]["calls"] == 1


def test_endpoint_usage_stats_records_upstream_payload_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K", retry_attempts=1, retry_backoff_seconds=0.0)

    def boom(path: str, params: dict[str, Any]) -> Any:
        raise UpstreamPayloadError("garbled")

    monkeypatch.setattr(client, "_request_once", boom)

    with pytest.raises(UpstreamPayloadError):
        client._execute_get("/stable/profile", {}, use_circuit_breaker=False)

    stats = client.get_endpoint_usage_stats()
    assert stats["/stable/profile"]["errors"] == 1


def test_endpoint_usage_stats_records_circuit_open_as_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K", retry_attempts=1, retry_backoff_seconds=0.0)
    # Force the breaker into OPEN state.
    client._circuit_breaker.on_failure()
    client._circuit_breaker.on_failure()
    client._circuit_breaker.on_failure()
    client._circuit_breaker.on_failure()
    client._circuit_breaker.on_failure()

    with pytest.raises(RuntimeError, match="circuit open"):
        client._execute_get("/stable/quote", {}, use_circuit_breaker=True)

    stats = client.get_endpoint_usage_stats()
    # When the breaker short-circuits, no network call is issued but we still
    # record the attempt as a call with an error so the audit reflects intent.
    assert stats["/stable/quote"] == {"calls": 1, "errors": 1, "empty_responses": 0}


def test_get_endpoint_usage_stats_returns_deep_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller mutations must not leak into internal state."""

    client = FMPClient(api_key="K", retry_attempts=1, retry_backoff_seconds=0.0)
    monkeypatch.setattr(client, "_request_once", lambda path, params: [])
    client._execute_get("/stable/quote", {}, use_circuit_breaker=False)

    snapshot = client.get_endpoint_usage_stats()
    snapshot["/stable/quote"]["calls"] = 999
    snapshot["/stable/poisoned"] = {"calls": 1, "errors": 0, "empty_responses": 0}

    fresh = client.get_endpoint_usage_stats()
    assert fresh["/stable/quote"]["calls"] == 1
    assert "/stable/poisoned" not in fresh


def test_record_endpoint_event_increments_multiple_counters() -> None:
    """Direct kwargs path — useful for downstream callers that want to mark
    empty-response payloads on successful HTTP-200 responses."""

    client = FMPClient(api_key="K")
    client._record_endpoint_event("/stable/foo", calls=1)
    client._record_endpoint_event("/stable/foo", empty_responses=1)
    client._record_endpoint_event("/stable/foo", calls=1, errors=1)

    stats = client.get_endpoint_usage_stats()
    assert stats["/stable/foo"] == {"calls": 2, "errors": 1, "empty_responses": 1}
