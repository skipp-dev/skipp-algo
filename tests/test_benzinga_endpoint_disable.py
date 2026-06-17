"""Tests for the per-endpoint circuit-breaker added to ``newsstack_fmp._bz_http``.

The breaker prevents the terminal poller from wasting a network round-trip
on every cycle for endpoints that have permanently failed (401/403/404 or
retired URL shapes returning 400).  Once an endpoint's *label* is marked
disabled, subsequent calls to ``_request_with_retry`` raise
``BenzingaEndpointDisabledError`` immediately without invoking the HTTP client.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from newsstack_fmp._bz_http import (
    BenzingaEndpointDisabledError,
    _request_with_retry,
    clear_disabled_endpoints,
    is_endpoint_disabled,
    log_fetch_warning,
    mark_endpoint_disabled,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    clear_disabled_endpoints()
    yield
    clear_disabled_endpoints()


def _make_client_returning(status_code: int, body: bytes = b"{}") -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.headers = {}
    response.content = body
    response.text = body.decode("utf-8", errors="replace")
    response.url = "https://api.benzinga.com/probe?token=***"
    if status_code >= 400:
        request = MagicMock(spec=httpx.Request)
        request.url = response.url
        response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"HTTP {status_code}",
                request=request,
                response=response,
            )
        )
    else:
        response.raise_for_status = MagicMock(return_value=None)

    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(return_value=response)
    return client


# ── mark / is / clear ─────────────────────────────────────────────


def test_mark_and_is_endpoint_disabled() -> None:
    assert is_endpoint_disabled("Benzinga foo") is False
    mark_endpoint_disabled("Benzinga foo")
    assert is_endpoint_disabled("Benzinga foo") is True


def test_clear_disabled_endpoints_resets_flag() -> None:
    mark_endpoint_disabled("Benzinga foo")
    assert is_endpoint_disabled("Benzinga foo") is True
    clear_disabled_endpoints()
    assert is_endpoint_disabled("Benzinga foo") is False


# ── _request_with_retry short-circuit ─────────────────────────────


def test_request_with_retry_short_circuits_when_label_disabled() -> None:
    mark_endpoint_disabled("Benzinga movers")
    client = _make_client_returning(200)

    with pytest.raises(BenzingaEndpointDisabledError) as excinfo:
        _request_with_retry(client, "https://api.benzinga.com/api/v1/market/movers",
                            {"token": "x"}, label="Benzinga movers")

    assert excinfo.value.label == "Benzinga movers"
    # Critical assertion: NO network call was made
    client.get.assert_not_called()


def test_request_with_retry_no_label_still_calls_when_disabled_other_label() -> None:
    """A disabled label MUST NOT block calls that don't pass that label."""
    mark_endpoint_disabled("Benzinga foo")
    client = _make_client_returning(200)

    r = _request_with_retry(client, "https://api.benzinga.com/probe", {"token": "x"})

    assert r.status_code == 200
    client.get.assert_called_once()


def test_request_with_retry_marks_disabled_on_401() -> None:
    client = _make_client_returning(401)

    with pytest.raises(httpx.HTTPStatusError):
        _request_with_retry(client, "https://api.benzinga.com/probe",
                            {"token": "x"}, label="Benzinga quotes")

    assert is_endpoint_disabled("Benzinga quotes") is True


def test_request_with_retry_marks_disabled_on_403() -> None:
    client = _make_client_returning(403)
    with pytest.raises(httpx.HTTPStatusError):
        _request_with_retry(client, "https://api.benzinga.com/probe",
                            {"token": "x"}, label="Benzinga fundamentals")
    assert is_endpoint_disabled("Benzinga fundamentals") is True


def test_request_with_retry_marks_disabled_on_404() -> None:
    client = _make_client_returning(404)
    with pytest.raises(httpx.HTTPStatusError):
        _request_with_retry(client, "https://api.benzinga.com/probe",
                            {"token": "x"}, label="Benzinga search")
    assert is_endpoint_disabled("Benzinga search") is True


def test_request_with_retry_marks_disabled_on_400_retired_url() -> None:
    """The 3 retired /api/v2/news/{top,channels,quantified} endpoints return 400."""
    client = _make_client_returning(400)
    with pytest.raises(httpx.HTTPStatusError):
        _request_with_retry(client, "https://api.benzinga.com/api/v2/news/top",
                            {"token": "x"}, label="Benzinga top_news")
    assert is_endpoint_disabled("Benzinga top_news") is True


def test_request_with_retry_does_not_mark_disabled_on_500() -> None:
    """Server errors are transient — must NOT permanently disable the endpoint."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 500
    response.headers = {}
    request = MagicMock(spec=httpx.Request)
    request.url = "https://api.benzinga.com/probe"
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("HTTP 500", request=request, response=response)
    )
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(return_value=response)

    with pytest.raises(httpx.HTTPStatusError):
        _request_with_retry(client, "https://api.benzinga.com/probe",
                            {"token": "x"}, label="Benzinga foo")

    assert is_endpoint_disabled("Benzinga foo") is False


def test_request_with_retry_no_label_does_not_mark_anything() -> None:
    """Without a label, the function cannot mark anything disabled."""
    client = _make_client_returning(401)
    with pytest.raises(httpx.HTTPStatusError):
        _request_with_retry(client, "https://api.benzinga.com/probe", {"token": "x"})
    # No label was passed → no global state mutated
    assert is_endpoint_disabled("Benzinga foo") is False


# ── log_fetch_warning marks disabled + skips spam ─────────────────


def test_log_fetch_warning_marks_disabled_on_tier_limited() -> None:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 401
    request = MagicMock(spec=httpx.Request)
    request.url = "https://api.benzinga.com/probe"
    exc = httpx.HTTPStatusError("HTTP 401", request=request, response=response)

    log_fetch_warning("Benzinga test_label", exc)

    assert is_endpoint_disabled("Benzinga test_label") is True


def test_log_fetch_warning_skips_silently_for_disabled_exception(caplog: Any) -> None:
    """The synthetic BenzingaEndpointDisabledError exception must NOT spam WARNING."""
    import logging
    caplog.set_level(logging.WARNING, logger="newsstack_fmp._bz_http")
    log_fetch_warning("Benzinga foo", BenzingaEndpointDisabledError("Benzinga foo"))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == []


def test_log_fetch_warning_does_not_mark_on_5xx() -> None:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 503
    request = MagicMock(spec=httpx.Request)
    request.url = "https://api.benzinga.com/probe"
    exc = httpx.HTTPStatusError("HTTP 503", request=request, response=response)

    log_fetch_warning("Benzinga transient", exc)

    assert is_endpoint_disabled("Benzinga transient") is False


# ── Integration-ish: 2nd call avoids HTTP ─────────────────────────


def test_second_call_after_401_avoids_network() -> None:
    """After first 401, the second call MUST NOT touch the wire."""
    client = _make_client_returning(401)

    # First call: hits the wire, gets 401, marks disabled
    with pytest.raises(httpx.HTTPStatusError):
        _request_with_retry(client, "https://api.benzinga.com/probe",
                            {"token": "x"}, label="Benzinga movers")
    assert client.get.call_count == 1

    # Second call: short-circuits BEFORE any HTTP
    with pytest.raises(BenzingaEndpointDisabledError):
        _request_with_retry(client, "https://api.benzinga.com/probe",
                            {"token": "x"}, label="Benzinga movers")
    # Critical: still 1 — no second network call
    assert client.get.call_count == 1


# ── TTL-based re-enable ───────────────────────────────────────────


def test_disabled_endpoint_re_enables_after_ttl(monkeypatch: Any) -> None:
    """After _DISABLED_TTL_S seconds the endpoint must auto-re-enable."""
    import newsstack_fmp._bz_http as mod

    # Use a short TTL for the test
    monkeypatch.setattr(mod, "_DISABLED_TTL_S", 10.0)

    mark_endpoint_disabled("Benzinga ttl_test")
    assert is_endpoint_disabled("Benzinga ttl_test") is True

    # Advance the monotonic clock past the TTL by patching the stored timestamp
    with mod._disabled_lock:
        mod._DISABLED_ENDPOINTS["Benzinga ttl_test"] -= 11.0

    assert is_endpoint_disabled("Benzinga ttl_test") is False
