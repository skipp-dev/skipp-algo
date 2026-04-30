"""Extended coverage for `open_prep.macro`.

Targets the long tail of helper functions, the `_CircuitBreaker` state
machine, the request pipeline (`_build_url` / `_parse_payload` /
`_execute_get`), every `FMPClient.get_*` HTTP-wrapper getter, and all
`FinnhubClient` stubs. Pre-existing tests in `tests/test_macro_dedup.py`
already cover the dedup / bias / impact-filter logic.

Strategy
--------
- Pure-logic helpers: direct function calls, no mocks.
- `FMPClient.get_*` wrappers: monkeypatch `FMPClient._get` to a small
  recorder + canned-payload helper. This avoids any network/SSL setup
  while still exercising parameter shaping, return-value normalization,
  symbol-matching for dict-coalesce methods, and try/except fall-throughs.
- Request pipeline (URL building, payload parsing, retry, circuit
  breaker, transport): exercised separately with light fakes for
  `urlopen` so URL/headers/timeout assertions remain meaningful without
  real network.
"""

from __future__ import annotations

import io
import json
import logging
import time
import urllib.error
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from open_prep import macro
from open_prep.macro import (
    DEFAULT_HIGH_IMPACT_EVENTS,
    FinnhubClient,
    FMPClient,
    UpstreamPayloadError,
    _CircuitBreaker,
    _coerce_csv_value,
    _event_impact_rank,
    _log_feature_unavailable_once,
    _normalize_event_date_key,
    _parse_retry_after_seconds,
    _prev_us_equity_trading_day,
    _to_float,
)

# ---------------------------------------------------------------------------
# Pure-logic helpers (no mocks)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("abc", None),
        ("1.5", 1.5),
        ("1", 1.0),
        (2, 2.0),
        (3.14, 3.14),
        (float("nan"), float("nan")),
    ],
)
def test_to_float_handles_all_input_shapes(value: Any, expected: float | None) -> None:
    result = _to_float(value)
    if expected is None:
        assert result is None
    elif expected != expected:  # NaN check
        assert result is not None and result != result
    else:
        assert result == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("   ", ""),
        ("42", 42),
        (" 42 ", 42),
        ("3.14", 3.14),
        ("1e3", 1000.0),
        ("1E-2", 0.01),
        ("-7", -7),
        ("not-a-number", "not-a-number"),
        ("1.2.3", "1.2.3"),
    ],
)
def test_coerce_csv_value_branches(raw: str, expected: Any) -> None:
    assert _coerce_csv_value(raw) == expected


def test_parse_retry_after_seconds_numeric_and_negative_clamp() -> None:
    assert _parse_retry_after_seconds("0") == 0.0
    assert _parse_retry_after_seconds("12.5") == 12.5
    # Negative numeric is clamped to 0.0.
    assert _parse_retry_after_seconds("-5") == 0.0


def test_parse_retry_after_seconds_http_date_in_future_returns_seconds() -> None:
    future = datetime.now(UTC) + timedelta(seconds=120)
    raw = format_datetime(future, usegmt=True)
    result = _parse_retry_after_seconds(raw)
    assert result is not None
    # Allow ±5s clock slack — we just want a sane positive number close to 120.
    assert 60.0 <= result <= 180.0


def test_parse_retry_after_seconds_http_date_in_past_clamps_to_zero() -> None:
    past = datetime.now(UTC) - timedelta(seconds=600)
    raw = format_datetime(past, usegmt=True)
    assert _parse_retry_after_seconds(raw) == 0.0


@pytest.mark.parametrize(
    ("raw", "junk"),
    [
        (None, None),
        ("", None),
        ("definitely-not-a-date", None),
    ],
)
def test_parse_retry_after_seconds_returns_none_on_garbage(raw: Any, junk: Any) -> None:
    assert _parse_retry_after_seconds(raw) is junk


@pytest.mark.parametrize(
    ("raw_date", "fallback_index", "expected"),
    [
        (None, 7, "__missing_date__7"),
        ("", 0, "__missing_date__0"),
        ("   ", 1, "__missing_date__1"),
        ("2026-04-23", 0, "2026-04-23"),
        ("2026-04-23T13:30:00", 0, "2026-04-23"),
        ("2026-04-23 13:30:00", 0, "2026-04-23"),
        ("4/23/26", 0, "2026-04-23"),
        ("4/23/2026", 0, "2026-04-23"),
        ("13/45/2026", 0, "13/45/2026"),  # invalid M/D — falls through to literal
        ("not-a-date", 0, "not-a-date"),
    ],
)
def test_normalize_event_date_key(raw_date: Any, fallback_index: int, expected: str) -> None:
    assert _normalize_event_date_key(raw_date, fallback_index) == expected


@pytest.mark.parametrize(
    ("event", "rank"),
    [
        ({"impact": "high"}, 2),
        ({"importance": "HIGH"}, 2),
        ({"priority": "high"}, 2),
        ({"impact": "medium"}, 1),
        ({"impact": "MID"}, 1),
        ({"impact": "moderate"}, 1),
        ({"impact": "low"}, 0),
        ({"impact": ""}, 0),
        ({}, 0),
    ],
)
def test_event_impact_rank(event: dict[str, Any], rank: int) -> None:
    assert _event_impact_rank(event) == rank


def test_log_feature_unavailable_once_dedupes_per_key(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reset module-level cache so the test is order-independent.
    monkeypatch.setattr(macro, "_FMP_FEATURE_UNAVAILABLE_LOGGED", set())
    with caplog.at_level(logging.INFO, logger="open_prep.macro"):
        _log_feature_unavailable_once("featureA", "first message")
        _log_feature_unavailable_once("featureA", "second message — should be suppressed")
        _log_feature_unavailable_once("featureB", "different feature, fires")
    messages = [record.message for record in caplog.records]
    assert "first message" in messages
    assert "different feature, fires" in messages
    assert "second message — should be suppressed" not in messages


def test_prev_us_equity_trading_day_skips_weekends_via_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the calendar shim path to None so the manual loop runs.
    monkeypatch.setattr(macro, "_prev_trading_day", None)
    # Monday 2026-04-20 → previous trading day should be Friday 2026-04-17.
    monday = date(2026, 4, 20)
    assert _prev_us_equity_trading_day(monday) == date(2026, 4, 17)


def test_prev_us_equity_trading_day_uses_market_calendar_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = date(2025, 1, 1)
    monkeypatch.setattr(macro, "_prev_trading_day", lambda day: sentinel)
    assert _prev_us_equity_trading_day(date(2026, 4, 20)) is sentinel


# ---------------------------------------------------------------------------
# _CircuitBreaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_starts_closed_and_allows() -> None:
    breaker = _CircuitBreaker(cooldown_seconds=1.0)
    assert breaker.state == "CLOSED"
    assert breaker.allow_request() is True


def test_circuit_breaker_cooldown_floor_clamped_to_one_second() -> None:
    breaker = _CircuitBreaker(cooldown_seconds=0.01)
    assert breaker.cooldown_seconds == 1.0


def test_circuit_breaker_opens_on_failure_then_blocks_until_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    breaker = _CircuitBreaker(cooldown_seconds=10.0)
    fixed_now = 1_000_000.0
    monkeypatch.setattr(macro.time, "time", lambda: fixed_now)
    breaker.on_failure()
    assert breaker.state == "OPEN"
    assert breaker.allow_request() is False
    # Advance just under cooldown — still blocked.
    monkeypatch.setattr(macro.time, "time", lambda: fixed_now + 9.0)
    assert breaker.allow_request() is False
    # Advance past cooldown — moves to HALF_OPEN and allows.
    monkeypatch.setattr(macro.time, "time", lambda: fixed_now + 11.0)
    assert breaker.allow_request() is True
    assert breaker.state == "HALF_OPEN"


def test_circuit_breaker_on_success_resets_to_closed() -> None:
    breaker = _CircuitBreaker(cooldown_seconds=5.0)
    breaker.on_failure()
    assert breaker.state == "OPEN"
    breaker.on_success()
    assert breaker.state == "CLOSED"
    assert breaker._opened_at == 0.0


# ---------------------------------------------------------------------------
# FMPClient construction & URL/payload primitives
# ---------------------------------------------------------------------------


def test_from_env_reads_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FMP_API_KEY", "abc123")
    client = FMPClient.from_env()
    assert client.api_key == "abc123"


def test_from_env_defaults_to_empty_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    assert FMPClient.from_env().api_key == ""


def test_build_url_uses_stable_base_for_stable_paths_and_appends_apikey() -> None:
    client = FMPClient(api_key="KEY")
    url = client._build_url("/stable/profile", {"symbol": "AAPL"})
    assert url.startswith("https://financialmodelingprep.com/stable/profile?")
    assert "symbol=AAPL" in url
    assert "apikey=KEY" in url


def test_build_url_uses_v3_base_for_non_stable_paths() -> None:
    client = FMPClient(api_key="KEY")
    url = client._build_url("/quote/AAPL", {})
    assert url == "https://financialmodelingprep.com/api/v3/quote/AAPL?apikey=KEY"


def test_build_url_empty_query_with_no_apikey_returns_path_only() -> None:
    client = FMPClient(api_key="")
    url = client._build_url("/stable/profile-bulk", {})
    assert url == "https://financialmodelingprep.com/stable/profile-bulk"


def test_build_url_drops_none_valued_params_and_keeps_apikey() -> None:
    client = FMPClient(api_key="KEY")
    url = client._build_url("/stable/grades", {"symbol": None, "limit": 5})
    assert "symbol=" not in url
    assert "limit=5" in url
    assert "apikey=KEY" in url


def test_parse_payload_rejects_html() -> None:
    client = FMPClient(api_key="KEY")
    with pytest.raises(RuntimeError, match="HTML"):
        client._parse_payload("/p", "<!DOCTYPE html><html></html>")
    with pytest.raises(RuntimeError, match="HTML"):
        client._parse_payload("/p", "<html><body/></html>")


def test_parse_payload_returns_parsed_json_list() -> None:
    client = FMPClient(api_key="KEY")
    result = client._parse_payload("/p", json.dumps([{"x": 1}, {"x": 2}]))
    assert result == [{"x": 1}, {"x": 2}]


def test_parse_payload_falls_back_to_csv_when_json_fails() -> None:
    client = FMPClient(api_key="KEY")
    csv_payload = 'symbol,price\n"AAPL",150.5\n"MSFT",420\n'
    rows = client._parse_payload("/p", csv_payload)
    assert isinstance(rows, list)
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["price"] == 150.5
    assert rows[1]["price"] == 420


def test_parse_payload_raises_on_invalid_non_csv_text() -> None:
    client = FMPClient(api_key="KEY")
    with pytest.raises(RuntimeError, match="invalid JSON"):
        client._parse_payload("/p", "this is just garbage with no comma")


def test_parse_payload_raises_when_status_error_dict() -> None:
    client = FMPClient(api_key="KEY")
    with pytest.raises(RuntimeError, match="FMP API error"):
        client._parse_payload(
            "/p",
            json.dumps({"status": "error", "message": "rate limited"}),
        )


# ---------------------------------------------------------------------------
# _resolve_quote_fetch_workers
# ---------------------------------------------------------------------------


def test_resolve_quote_fetch_workers_default_when_no_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPEN_PREP_FMP_QUOTE_WORKERS", raising=False)
    monkeypatch.delenv("FMP_QUOTE_WORKERS", raising=False)
    client = FMPClient(api_key="K")
    assert client._resolve_quote_fetch_workers(symbol_count=10) == 4


def test_resolve_quote_fetch_workers_env_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPEN_PREP_FMP_QUOTE_WORKERS", "6")
    monkeypatch.delenv("FMP_QUOTE_WORKERS", raising=False)
    client = FMPClient(api_key="K")
    assert client._resolve_quote_fetch_workers(symbol_count=10) == 6


def test_resolve_quote_fetch_workers_caps_at_eight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPEN_PREP_FMP_QUOTE_WORKERS", "32")
    client = FMPClient(api_key="K")
    assert client._resolve_quote_fetch_workers(symbol_count=20) == 8


def test_resolve_quote_fetch_workers_clamps_to_symbol_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPEN_PREP_FMP_QUOTE_WORKERS", "8")
    client = FMPClient(api_key="K")
    assert client._resolve_quote_fetch_workers(symbol_count=2) == 2


def test_resolve_quote_fetch_workers_invalid_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPEN_PREP_FMP_QUOTE_WORKERS", "not-an-int")
    client = FMPClient(api_key="K")
    assert client._resolve_quote_fetch_workers(symbol_count=10) == 4


def test_resolve_quote_fetch_workers_minimum_one_for_zero_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPEN_PREP_FMP_QUOTE_WORKERS", raising=False)
    monkeypatch.delenv("FMP_QUOTE_WORKERS", raising=False)
    client = FMPClient(api_key="K")
    assert client._resolve_quote_fetch_workers(symbol_count=0) == 1


# ---------------------------------------------------------------------------
# Request pipeline: _request_once + _execute_get
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_request_once_builds_request_with_user_agent_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, *, timeout: float, context: Any) -> _FakeResponse:
        captured["full_url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["timeout"] = timeout
        captured["context_type"] = type(context).__name__
        return _FakeResponse(json.dumps([{"x": 1}]).encode("utf-8"))

    monkeypatch.setattr(macro, "urlopen", fake_urlopen)

    client = FMPClient(api_key="KEY", timeout_seconds=12.5)
    result = client._request_once("/stable/profile-bulk", {"limit": 2})

    assert result == [{"x": 1}]
    assert captured["timeout"] == 12.5
    # urllib normalizes header keys via Title-case in Request.headers.
    assert captured["headers"].get("User-agent") == "skipp-algo/1.0"
    assert "limit=2" in captured["full_url"]
    assert "apikey=KEY" in captured["full_url"]


def test_execute_get_succeeds_on_first_try_and_records_breaker_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K", retry_attempts=3, retry_backoff_seconds=0.0)
    monkeypatch.setattr(client, "_request_once", lambda path, params: ["ok"])
    assert client._execute_get("/x", {}, use_circuit_breaker=True) == ["ok"]
    assert client._circuit_breaker.state == "CLOSED"


def test_execute_get_retries_on_transient_http_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K", retry_attempts=3, retry_backoff_seconds=0.0)
    calls: list[int] = []

    def flaky(path: str, params: dict[str, Any]) -> Any:
        calls.append(1)
        if len(calls) < 2:
            raise urllib.error.HTTPError(
                url="http://x", code=503, msg="busy", hdrs=None, fp=None
            )
        return ["ok"]

    monkeypatch.setattr(client, "_request_once", flaky)
    monkeypatch.setattr(macro.time, "sleep", lambda _s: None)
    result = client._execute_get("/x", {}, use_circuit_breaker=True)
    assert result == ["ok"]
    assert len(calls) == 2


def test_execute_get_honors_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FMPClient(api_key="K", retry_attempts=2, retry_backoff_seconds=0.0)
    sleeps: list[float] = []
    calls: list[int] = []

    def flaky(path: str, params: dict[str, Any]) -> Any:
        calls.append(1)
        if len(calls) == 1:
            err = urllib.error.HTTPError(
                url="http://x", code=429, msg="rate", hdrs={"Retry-After": "0.25"}, fp=None
            )
            raise err
        return []

    monkeypatch.setattr(client, "_request_once", flaky)
    monkeypatch.setattr(macro.time, "sleep", lambda s: sleeps.append(s))
    client._execute_get("/x", {}, use_circuit_breaker=True)
    assert sleeps == [0.25]


def test_execute_get_non_transient_http_error_raises_runtime_and_keeps_breaker_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 4xx (except 408/429) are client/data errors — they must raise but must NOT
    # trip the circuit breaker, otherwise one stale endpoint nukes every other
    # FMP call for the cooldown window.
    client = FMPClient(api_key="K", retry_attempts=3, retry_backoff_seconds=0.0)
    fp = io.BytesIO(b"server-said-no")

    def fail(path: str, params: dict[str, Any]) -> Any:
        raise urllib.error.HTTPError(url="http://x", code=400, msg="bad", hdrs=None, fp=fp)

    monkeypatch.setattr(client, "_request_once", fail)
    with pytest.raises(RuntimeError, match="HTTP 400"):
        client._execute_get("/x", {}, use_circuit_breaker=True)
    assert client._circuit_breaker.state == "CLOSED"


def test_execute_get_429_opens_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    # 429 (rate-limit) IS a provider-outage signal — must trip the breaker after
    # retries are exhausted.
    client = FMPClient(api_key="K", retry_attempts=2, retry_backoff_seconds=0.0)

    def fail(path: str, params: dict[str, Any]) -> Any:
        raise urllib.error.HTTPError(url="http://x", code=429, msg="rate", hdrs=None, fp=None)

    monkeypatch.setattr(client, "_request_once", fail)
    monkeypatch.setattr(macro.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        client._execute_get("/x", {}, use_circuit_breaker=True)
    assert client._circuit_breaker.state == "OPEN"


def test_execute_get_transient_exhausts_retries_and_opens_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K", retry_attempts=2, retry_backoff_seconds=0.0)

    def fail(path: str, params: dict[str, Any]) -> Any:
        raise urllib.error.HTTPError(url="http://x", code=502, msg="upstream", hdrs=None, fp=None)

    monkeypatch.setattr(client, "_request_once", fail)
    monkeypatch.setattr(macro.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="HTTP 502"):
        client._execute_get("/x", {}, use_circuit_breaker=True)
    assert client._circuit_breaker.state == "OPEN"


def test_execute_get_url_error_retries_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FMPClient(api_key="K", retry_attempts=2, retry_backoff_seconds=0.0)

    def fail(path: str, params: dict[str, Any]) -> Any:
        raise urllib.error.URLError("dns lookup failed")

    monkeypatch.setattr(client, "_request_once", fail)
    monkeypatch.setattr(macro.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="network error"):
        client._execute_get("/x", {}, use_circuit_breaker=True)
    assert client._circuit_breaker.state == "OPEN"


def test_execute_get_upstream_payload_error_propagates_and_opens_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Contract: only UpstreamPayloadError (HTML / FMP status=error) trips the
    # breaker. Plain RuntimeError must NOT — see the companion test below.
    client = FMPClient(api_key="K", retry_attempts=3, retry_backoff_seconds=0.0)

    def fail(path: str, params: dict[str, Any]) -> Any:
        raise UpstreamPayloadError("payload was HTML")

    monkeypatch.setattr(client, "_request_once", fail)
    with pytest.raises(UpstreamPayloadError, match="HTML"):
        client._execute_get("/x", {}, use_circuit_breaker=True)
    assert client._circuit_breaker.state == "OPEN"


def test_execute_get_plain_runtime_error_propagates_without_tripping_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Parse errors / schema drift surface as plain RuntimeError; they are our
    # bug, not an upstream outage, so the breaker must stay CLOSED.
    client = FMPClient(api_key="K", retry_attempts=3, retry_backoff_seconds=0.0)

    def fail(path: str, params: dict[str, Any]) -> Any:
        raise RuntimeError("schema drift: missing field 'foo'")

    monkeypatch.setattr(client, "_request_once", fail)
    with pytest.raises(RuntimeError, match="schema drift"):
        client._execute_get("/x", {}, use_circuit_breaker=True)
    assert client._circuit_breaker.state == "CLOSED"


def test_parse_payload_html_raises_upstream_payload_error() -> None:
    client = FMPClient(api_key="K")
    with pytest.raises(UpstreamPayloadError, match="HTML"):
        client._parse_payload("/p", "<!DOCTYPE html><html></html>")


def test_parse_payload_status_error_raises_upstream_payload_error() -> None:
    client = FMPClient(api_key="K")
    with pytest.raises(UpstreamPayloadError, match="FMP API error"):
        client._parse_payload("/p", json.dumps({"status": "error", "message": "rate limited"}))


def test_parse_payload_invalid_json_raises_plain_runtime_error_not_upstream() -> None:
    client = FMPClient(api_key="K")
    with pytest.raises(RuntimeError, match="invalid JSON") as exc_info:
        client._parse_payload("/p", "this is just garbage with no comma")
    # Must NOT be the UpstreamPayloadError subclass — parse errors are our bug.
    assert not isinstance(exc_info.value, UpstreamPayloadError)


def test_execute_get_short_circuits_when_breaker_open(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FMPClient(api_key="K")
    client._circuit_breaker.on_failure()  # OPEN
    with pytest.raises(RuntimeError, match="circuit open"):
        client._execute_get("/x", {}, use_circuit_breaker=True)


# ---------------------------------------------------------------------------
# get_* HTTP wrappers — parametrized round-trip via monkeypatched _get
# ---------------------------------------------------------------------------


@pytest.fixture
def recorder() -> dict[str, Any]:
    """Mutable container to capture (path, params) seen by stubbed _get."""

    return {}


@pytest.fixture
def client_with_get(monkeypatch: pytest.MonkeyPatch, recorder: dict[str, Any]) -> FMPClient:
    """FMPClient whose _get returns whatever we stash in `recorder['return']`.

    Records the last (path, params) tuple as `recorder['call']`.
    """

    client = FMPClient(api_key="K")
    recorder["return"] = []

    def fake_get(path: str, params: dict[str, Any]) -> Any:
        recorder["call"] = (path, dict(params))
        if isinstance(recorder["return"], BaseException):
            raise recorder["return"]
        return recorder["return"]

    monkeypatch.setattr(client, "_get", fake_get)
    return client


def test_get_profile_bulk_passes_no_params_and_returns_list(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"symbol": "AAPL"}]
    rows = client_with_get.get_profile_bulk()
    assert recorder["call"] == ("/stable/profile-bulk", {})
    assert rows == [{"symbol": "AAPL"}]


def test_get_profile_bulk_swallows_runtime_error_and_logs_once(
    client_with_get: FMPClient,
    recorder: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(macro, "_FMP_FEATURE_UNAVAILABLE_LOGGED", set())
    recorder["return"] = RuntimeError("fail")
    assert client_with_get.get_profile_bulk() == []


def test_get_profiles_uppercases_and_iterates_per_symbol(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    # /stable/profile only accepts a single symbol; verify per-symbol calls.
    calls: list[tuple[str, dict[str, Any]]] = []
    original = recorder.get("return")

    def _record_get(path: str, params: dict[str, Any]) -> Any:
        calls.append((path, dict(params)))
        return [{"symbol": params.get("symbol")}]

    client_with_get._get = _record_get  # type: ignore[assignment]
    rows = client_with_get.get_profiles(["aapl", " msft ", "", "tsla"])
    assert calls == [
        ("/stable/profile", {"symbol": "AAPL"}),
        ("/stable/profile", {"symbol": "MSFT"}),
        ("/stable/profile", {"symbol": "TSLA"}),
    ]
    assert rows == [
        {"symbol": "AAPL"},
        {"symbol": "MSFT"},
        {"symbol": "TSLA"},
    ]
    recorder["return"] = original


def test_get_profiles_returns_empty_for_empty_input(client_with_get: FMPClient) -> None:
    assert client_with_get.get_profiles([]) == []
    assert client_with_get.get_profiles(["", "  "]) == []


def test_get_profiles_swallows_runtime_error(client_with_get: FMPClient, recorder: dict[str, Any]) -> None:
    recorder["return"] = RuntimeError("boom")
    assert client_with_get.get_profiles(["aapl"]) == []


def test_get_ratios_ttm_uppercases_and_short_circuits_on_blank(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"x": 1}]
    assert client_with_get.get_ratios_ttm("aapl") == [{"x": 1}]
    assert recorder["call"] == ("/stable/ratios-ttm", {"symbol": "AAPL"})
    assert client_with_get.get_ratios_ttm("   ") == []


def test_get_ratios_ttm_swallows_runtime_error(client_with_get: FMPClient, recorder: dict[str, Any]) -> None:
    recorder["return"] = RuntimeError("nope")
    assert client_with_get.get_ratios_ttm("aapl") == []


def test_get_company_screener_passes_kwargs_through(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"symbol": "X"}]
    rows = client_with_get.get_company_screener(marketCapMoreThan=100, sector="Technology")
    assert recorder["call"][0] == "/stable/company-screener"
    assert recorder["call"][1] == {"marketCapMoreThan": 100, "sector": "Technology"}
    assert rows == [{"symbol": "X"}]


def test_screener_alias_proxies_to_get_company_screener(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = []
    client_with_get.screener("ignored", limit=5)
    assert recorder["call"][1] == {"limit": 5}


def test_get_fmp_articles_clamps_limit_floor_to_one(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"a": 1}]
    client_with_get.get_fmp_articles(limit=0)
    assert recorder["call"] == ("/stable/fmp-articles", {"page": 0, "limit": 1})


def test_get_stock_latest_news_optional_symbol(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"n": 1}]
    client_with_get.get_stock_latest_news(symbol="aapl", limit=10)
    assert recorder["call"] == ("/stable/news/stock-latest", {"limit": 10, "symbol": "AAPL"})

    recorder.pop("call", None)
    client_with_get.get_stock_latest_news()
    assert recorder["call"] == ("/stable/news/stock-latest", {"limit": 50})


def test_get_batch_crypto_quotes(client_with_get: FMPClient, recorder: dict[str, Any]) -> None:
    recorder["return"] = [{"symbol": "BTCUSD"}]
    assert client_with_get.get_batch_crypto_quotes() == [{"symbol": "BTCUSD"}]
    assert recorder["call"] == ("/stable/batch-crypto-quotes", {})


def test_get_cryptocurrency_historical_price(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"d": 1}]
    client_with_get.get_cryptocurrency_historical_price("btcusd")
    assert recorder["call"] == ("/stable/historical-price-eod/full", {"symbol": "BTCUSD"})


def test_get_cryptocurrency_list(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = []
    client_with_get.get_cryptocurrency_list()
    assert recorder["call"] == ("/stable/cryptocurrency-list", {})
    # ``get_fear_and_greed_index`` removed in P-6 (2026-04-30): the FMP
    # endpoint is retired; crypto F&G now flows through alternative.me
    # in ``terminal_bitcoin.fetch_fear_greed``.


def test_get_technical_indicator_includes_period_when_provided(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"value": 1.23}]
    out = client_with_get.get_technical_indicator(
        "aapl", "1day", "rsi", indicator_period=14
    )
    assert recorder["call"] == (
        "/stable/technical-indicators/rsi",
        {"symbol": "AAPL", "timeframe": "1day", "periodLength": 14},
    )
    assert out == {"value": 1.23}


def test_get_technical_indicator_omits_period_when_none_and_unwraps_dict(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = {"value": 9}
    out = client_with_get.get_technical_indicator("aapl", "1hour", "macd")
    assert recorder["call"][1] == {"symbol": "AAPL", "timeframe": "1hour"}
    assert out == {"value": 9}


def test_get_technical_indicator_returns_empty_on_runtime_error(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = RuntimeError("fail")
    assert client_with_get.get_technical_indicator("aapl", "1day", "rsi") == {}


def test_get_eod_bulk_with_and_without_date(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = []
    client_with_get.get_eod_bulk(date(2026, 4, 23))
    assert recorder["call"] == ("/stable/eod-bulk", {"datatype": "json", "date": "2026-04-23"})
    client_with_get.get_eod_bulk(None)
    assert recorder["call"] == ("/stable/eod-bulk", {"datatype": "json"})


def test_get_earnings_calendar_passes_iso_dates(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"e": 1}]
    out = client_with_get.get_earnings_calendar(date(2026, 4, 1), date(2026, 4, 30))
    assert recorder["call"] == (
        "/stable/earnings-calendar",
        {"from": "2026-04-01", "to": "2026-04-30"},
    )
    assert out == [{"e": 1}]


def test_get_macro_calendar(client_with_get: FMPClient, recorder: dict[str, Any]) -> None:
    recorder["return"] = []
    client_with_get.get_macro_calendar(date(2026, 1, 1), date(2026, 1, 31))
    assert recorder["call"] == (
        "/stable/economic-calendar",
        {"from": "2026-01-01", "to": "2026-01-31"},
    )


def test_get_premarket_movers_and_batch_aftermarket_quote(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = []
    client_with_get.get_premarket_movers()
    assert recorder["call"] == ("/stable/most-actives", {})
    client_with_get.get_batch_aftermarket_quote(["aapl", "MSFT"])
    assert recorder["call"] == (
        "/stable/batch-aftermarket-quote",
        {"symbols": "AAPL,MSFT"},
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get_splits_calendar", "/stable/splits-calendar"),
        ("get_dividends_calendar", "/stable/dividends-calendar"),
        ("get_ipos_calendar", "/stable/ipos-calendar"),
    ],
)
def test_calendar_endpoints_with_date_range(
    client_with_get: FMPClient,
    recorder: dict[str, Any],
    method: str,
    path: str,
) -> None:
    recorder["return"] = []
    getattr(client_with_get, method)(date(2026, 4, 1), date(2026, 4, 30))
    assert recorder["call"] == (path, {"from": "2026-04-01", "to": "2026-04-30"})


def test_get_upgrades_downgrades_only_includes_provided_filters(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = []
    client_with_get.get_upgrades_downgrades()
    assert recorder["call"] == ("/stable/grades", {})

    client_with_get.get_upgrades_downgrades(
        symbol="aapl",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 4, 23),
        limit=5,
    )
    assert recorder["call"] == (
        "/stable/grades",
        {"symbol": "AAPL", "from": "2026-01-01", "to": "2026-04-23", "limit": 5},
    )


def test_get_insider_trading_latest_optional_symbol_and_limit_floor(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = []
    client_with_get.get_insider_trading_latest()
    assert recorder["call"] == ("/stable/insider-trading/latest", {"limit": 100, "page": 0})
    client_with_get.get_insider_trading_latest(symbol="aapl", limit=0)
    assert recorder["call"] == (
        "/stable/insider-trading/search",
        {"limit": 1, "page": 0, "symbol": "AAPL"},
    )


def test_get_institutional_ownership(client_with_get: FMPClient, recorder: dict[str, Any]) -> None:
    recorder["return"] = []
    client_with_get.get_institutional_ownership("aapl", limit=25)
    assert recorder["call"] == (
        "/stable/institutional-ownership/symbol-positions-summary",
        {"symbol": "AAPL"},
    )


def test_get_acquisition_of_beneficial_ownership(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"symbol": "AAPL", "filingDate": "2026-04-20"}]
    rows = client_with_get.get_acquisition_of_beneficial_ownership("aapl")
    assert recorder["call"] == (
        "/stable/acquisition-of-beneficial-ownership",
        {"symbol": "AAPL"},
    )
    assert rows == [{"symbol": "AAPL", "filingDate": "2026-04-20"}]
    assert client_with_get.get_acquisition_of_beneficial_ownership("   ") == []


def test_get_acquisition_of_beneficial_ownership_swallows_runtime_error(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = RuntimeError("retired")
    assert client_with_get.get_acquisition_of_beneficial_ownership("AAPL") == []


def test_get_senate_trades_latest_default_paging(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"symbol": "AAPL"}]
    rows = client_with_get.get_senate_trades_latest(limit=50)
    assert recorder["call"] == ("/stable/senate-latest", {"page": 0, "limit": 50})
    assert rows == [{"symbol": "AAPL"}]


def test_get_house_trades_latest_default_paging(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"symbol": "NVDA"}]
    rows = client_with_get.get_house_trades_latest(limit=0)
    # limit floored to 1
    assert recorder["call"] == ("/stable/house-latest", {"page": 0, "limit": 1})
    assert rows == [{"symbol": "NVDA"}]


def test_get_senate_trades_latest_swallows_runtime_error(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = RuntimeError("retired")
    assert client_with_get.get_senate_trades_latest() == []


def test_get_insider_trading_statistics_path(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"symbol": "AAPL", "year": 2026, "quarter": 1}]
    rows = client_with_get.get_insider_trading_statistics("aapl")
    assert recorder["call"] == ("/stable/insider-trading/statistics", {"symbol": "AAPL"})
    assert rows == [{"symbol": "AAPL", "year": 2026, "quarter": 1}]


def test_get_insider_trading_statistics_empty_symbol(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"x": 1}]  # would be returned if called
    assert client_with_get.get_insider_trading_statistics("  ") == []
    # _get must not have been invoked for empty symbol
    assert recorder.get("call") is None


def test_get_insider_trading_statistics_swallows_runtime_error(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = RuntimeError("retired")
    assert client_with_get.get_insider_trading_statistics("AAPL") == []


def test_get_treasury_rates_optional_dates(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = []
    client_with_get.get_treasury_rates()
    assert recorder["call"] == ("/stable/treasury-rates", {})
    client_with_get.get_treasury_rates(date(2026, 1, 1), date(2026, 4, 23))
    assert recorder["call"] == (
        "/stable/treasury-rates",
        {"from": "2026-01-01", "to": "2026-04-23"},
    )


def test_get_house_trading_clamps_limit(client_with_get: FMPClient, recorder: dict[str, Any]) -> None:
    recorder["return"] = []
    client_with_get.get_house_trading(limit=0)
    assert recorder["call"] == ("/stable/house-latest", {"limit": 1})


def test_get_dcf_unwraps_dict_or_first_list_dict(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = {"dcf": 100}
    assert client_with_get.get_dcf("aapl") == {"dcf": 100}
    assert recorder["call"] == ("/stable/discounted-cash-flow", {"symbol": "AAPL"})

    recorder["return"] = [{"dcf": 200}, {"dcf": 300}]
    assert client_with_get.get_dcf("aapl") == {"dcf": 200}

    recorder["return"] = []
    assert client_with_get.get_dcf("aapl") == {}

    recorder["return"] = RuntimeError("fail")
    assert client_with_get.get_dcf("aapl") == {}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get_company_profile", "/stable/profile"),
        ("get_price_target_consensus", "/stable/price-target-consensus"),
        ("get_price_target_summary", "/stable/price-target-summary"),
        ("get_grades_consensus", "/stable/grades-consensus"),
        ("get_index_quote", "/stable/quote"),
    ],
)
def test_symbol_matching_dict_unwrap_pattern(
    client_with_get: FMPClient,
    recorder: dict[str, Any],
    method: str,
    path: str,
) -> None:
    """Methods returning dict pick the matching symbol when API gives a list."""

    fn = getattr(client_with_get, method)

    # Direct dict — passthrough.
    recorder["return"] = {"symbol": "AAPL", "x": 1}
    assert fn("aapl") == {"symbol": "AAPL", "x": 1}
    assert recorder["call"] == (path, {"symbol": "AAPL"})

    # List with matching symbol — pick that row.
    recorder["return"] = [
        {"symbol": "MSFT", "x": 2},
        {"symbol": "AAPL", "x": 1},
    ]
    assert fn("aapl") == {"symbol": "AAPL", "x": 1}

    # List with no match — fall back to first dict.
    recorder["return"] = [{"symbol": "MSFT"}, {"symbol": "TSLA"}]
    assert fn("aapl") == {"symbol": "MSFT"}

    # Empty list — empty dict.
    recorder["return"] = []
    assert fn("aapl") == {}

    # RuntimeError swallow.
    recorder["return"] = RuntimeError("fail")
    assert fn("aapl") == {}


def test_get_analyst_estimates_defaults_and_overrides(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = []
    client_with_get.get_analyst_estimates("aapl")
    assert recorder["call"] == (
        "/stable/analyst-estimates",
        {"symbol": "AAPL", "period": "annual", "limit": 8},
    )
    client_with_get.get_analyst_estimates("aapl", period="annual", limit=0)
    assert recorder["call"][1] == {"symbol": "AAPL", "period": "annual", "limit": 1}


def test_get_analyst_estimates_blank_period_falls_back(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = []
    client_with_get.get_analyst_estimates("aapl", period="   ")
    assert recorder["call"][1]["period"] == "annual"


def test_get_analyst_estimates_quarter_normalised_to_quarterly(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = []
    client_with_get.get_analyst_estimates("aapl", period="quarter")
    assert recorder["call"][1]["period"] == "quarterly"


def test_get_earnings_report(client_with_get: FMPClient, recorder: dict[str, Any]) -> None:
    recorder["return"] = []
    client_with_get.get_earnings_report("aapl", limit=0)
    assert recorder["call"] == ("/stable/earnings", {"symbol": "AAPL", "limit": 1})


def test_get_historical_price_eod_full_returns_dict_when_api_returns_dict(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = {"historical": []}
    out = client_with_get.get_historical_price_eod_full(
        "aapl", date(2026, 1, 1), date(2026, 4, 23)
    )
    assert out == {"historical": []}
    assert recorder["call"] == (
        "/stable/historical-price-eod/full",
        {"symbol": "AAPL", "from": "2026-01-01", "to": "2026-04-23"},
    )


def test_get_historical_price_eod_full_returns_list_when_api_returns_list(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"d": 1}, {"d": 2}]
    out = client_with_get.get_historical_price_eod_full(
        "aapl", date(2026, 1, 1), date(2026, 4, 23)
    )
    assert out == [{"d": 1}, {"d": 2}]


def test_get_historical_price_eod_full_swallows_runtime_error(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = RuntimeError("fail")
    assert (
        client_with_get.get_historical_price_eod_full(
            "aapl", date(2026, 1, 1), date(2026, 4, 23)
        )
        == []
    )


def test_get_intraday_chart_with_and_without_day(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"k": 1}]
    client_with_get.get_intraday_chart("aapl")
    assert recorder["call"] == (
        "/stable/historical-chart/1min",
        {"symbol": "AAPL", "limit": 5000},
    )

    client_with_get.get_intraday_chart("aapl", interval="5min", day=date(2026, 4, 23), limit=0)
    assert recorder["call"] == (
        "/stable/historical-chart/5min",
        {"symbol": "AAPL", "limit": 1, "from": "2026-04-23", "to": "2026-04-23"},
    )


def test_get_sector_performance_snapshot(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    # `date` is required by FMP; without an explicit `as_of` we now default
    # to today (US/Eastern) instead of calling the endpoint with `{}`.
    recorder["return"] = []
    client_with_get.get_sector_performance_snapshot()
    call_path, call_params = recorder["call"]
    assert call_path == "/stable/sector-performance-snapshot"
    assert set(call_params.keys()) == {"date"}
    assert call_params["date"]  # non-empty ISO date
    client_with_get.get_sector_performance_snapshot(date(2026, 4, 23))
    assert recorder["call"] == (
        "/stable/sector-performance-snapshot",
        {"date": "2026-04-23"},
    )


# ---------------------------------------------------------------------------
# Methods that DO NOT swallow RuntimeError
# ---------------------------------------------------------------------------


def test_get_batch_aftermarket_trade_reraises_when_all_chunks_fail(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    # A *single* chunk failure must NOT bubble — otherwise one bad batch
    # (URL too long, gateway 414/401) poisons the whole pre-market context.
    # The chunk is logged + skipped, the rest of the batches still get
    # aggregated. But if EVERY chunk fails (likely a real misconfiguration
    # such as a bad apikey) we re-raise so the caller cannot mistake it for
    # "no data".
    recorder["return"] = RuntimeError("fail")
    with pytest.raises(RuntimeError):
        client_with_get.get_batch_aftermarket_trade(["AAPL"])


def test_get_batch_aftermarket_trade_returns_list(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"x": 1}]
    out = client_with_get.get_batch_aftermarket_trade(["aapl", "msft"])
    # Symbols are normalised (stripped + uppercased) before the URL is built.
    assert recorder["call"] == ("/stable/batch-aftermarket-trade", {"symbols": "AAPL,MSFT"})
    assert out == [{"x": 1}]


def test_get_batch_aftermarket_trade_returns_empty_when_payload_not_list(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = {"unexpected": "shape"}
    assert client_with_get.get_batch_aftermarket_trade(["AAPL"]) == []


def test_get_biggest_gainers_and_losers_propagate_runtime(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = RuntimeError("fail")
    with pytest.raises(RuntimeError):
        client_with_get.get_biggest_gainers()
    with pytest.raises(RuntimeError):
        client_with_get.get_biggest_losers()


def test_get_biggest_gainers_and_losers_return_lists(
    client_with_get: FMPClient, recorder: dict[str, Any]
) -> None:
    recorder["return"] = [{"symbol": "AAPL"}]
    assert client_with_get.get_biggest_gainers() == [{"symbol": "AAPL"}]
    assert recorder["call"] == ("/stable/biggest-gainers", {})
    assert client_with_get.get_biggest_losers() == [{"symbol": "AAPL"}]
    assert recorder["call"] == ("/stable/biggest-losers", {})


def test_get_sector_performance_uses_today_then_falls_back_to_prev_trading_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K")
    fixed_today = date(2026, 4, 23)
    monkeypatch.setattr(macro, "_today_et_date", lambda: fixed_today)
    monkeypatch.setattr(
        macro, "_prev_us_equity_trading_day", lambda d: date(2026, 4, 22)
    )

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_get(path: str, params: dict[str, Any]) -> Any:
        calls.append((path, dict(params)))
        # First call (today) returns empty, second (prev day) returns snapshot rows.
        if len(calls) == 1:
            return []
        return [
            {"sector": "Technology", "exchange": "NASDAQ", "averageChange": 1.2},
            {"sector": "Technology", "exchange": "NYSE", "averageChange": 0.8},
        ]

    monkeypatch.setattr(client, "_get", fake_get)
    rows = client.get_sector_performance()
    # Aggregated across exchanges → mean of 1.2 and 0.8 = 1.0
    assert rows == [{"sector": "Technology", "changesPercentage": 1.0}]
    assert calls == [
        ("/stable/sector-performance-snapshot", {"date": "2026-04-23"}),
        ("/stable/sector-performance-snapshot", {"date": "2026-04-22"}),
    ]


def test_get_sector_performance_returns_today_data_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K")
    monkeypatch.setattr(macro, "_today_et_date", lambda: date(2026, 4, 23))

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_get(path: str, params: dict[str, Any]) -> Any:
        calls.append((path, dict(params)))
        return [{"sector": "Energy", "exchange": "NYSE", "averageChange": -0.5}]

    monkeypatch.setattr(client, "_get", fake_get)
    rows = client.get_sector_performance()
    assert rows == [{"sector": "Energy", "changesPercentage": -0.5}]
    assert len(calls) == 1
    assert calls[0] == (
        "/stable/sector-performance-snapshot",
        {"date": "2026-04-23"},
    )


# ---------------------------------------------------------------------------
# get_batch_quotes — diagnostics + per-symbol fetch
# ---------------------------------------------------------------------------


def test_get_batch_quotes_serial_path_returns_matched_rows_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K")
    monkeypatch.setenv("OPEN_PREP_FMP_QUOTE_WORKERS", "1")

    def fake_execute(path: str, params: dict[str, Any], *, use_circuit_breaker: bool) -> Any:
        assert use_circuit_breaker is False
        symbol = params["symbol"]
        return [{"symbol": symbol, "price": 100.0}]

    monkeypatch.setattr(client, "_execute_get", fake_execute)
    rows = client.get_batch_quotes(["aapl", "msft", "aapl", ""])
    assert {row["symbol"] for row in rows} == {"AAPL", "MSFT"}
    diag = client.get_last_quote_fetch_diagnostics()
    assert diag["requested_symbols"] == ["AAPL", "MSFT", "AAPL"]
    assert diag["deduped_symbols"] == ["AAPL", "MSFT"]
    assert diag["fetched_unique_symbols"] == ["AAPL", "MSFT"]
    assert diag["failed_quote_symbols"] == []
    assert diag["partial_quote_fetch"] is False
    assert diag["quote_fetch_all_failed"] is False
    assert diag["endpoint_used"] == "/stable/quote"
    assert diag["quote_fetch_workers"] == 1


def test_get_batch_quotes_records_failed_symbols_and_partial_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K")
    monkeypatch.setenv("OPEN_PREP_FMP_QUOTE_WORKERS", "1")

    def fake_execute(path: str, params: dict[str, Any], *, use_circuit_breaker: bool) -> Any:
        if params["symbol"] == "BAD":
            return []
        if params["symbol"] == "MISMATCH":
            return [{"symbol": "OTHER", "price": 1.0}]
        return [{"symbol": params["symbol"], "price": 50.0}]

    monkeypatch.setattr(client, "_execute_get", fake_execute)
    rows = client.get_batch_quotes(["AAPL", "BAD", "MISMATCH"])
    assert [row["symbol"] for row in rows] == ["AAPL"]
    diag = client.get_last_quote_fetch_diagnostics()
    assert diag["failed_quote_symbols"] == ["BAD", "MISMATCH"]
    assert diag["partial_quote_fetch"] is True
    assert diag["quote_fetch_all_failed"] is False


def test_get_batch_quotes_marks_all_failed_when_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FMPClient(api_key="K")
    monkeypatch.setenv("OPEN_PREP_FMP_QUOTE_WORKERS", "1")
    monkeypatch.setattr(
        client, "_execute_get", lambda *a, **kw: []
    )
    rows = client.get_batch_quotes(["AAPL", "MSFT"])
    assert rows == []
    diag = client.get_last_quote_fetch_diagnostics()
    assert diag["quote_fetch_all_failed"] is True
    assert diag["partial_quote_fetch"] is False


def test_get_batch_quotes_empty_input_returns_empty_and_resets_diagnostics() -> None:
    client = FMPClient(api_key="K")
    rows = client.get_batch_quotes([])
    assert rows == []
    diag = client.get_last_quote_fetch_diagnostics()
    assert diag["requested_symbols"] == []
    assert diag["deduped_symbols"] == []


def test_get_batch_quotes_parallel_path_fetches_all_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FMPClient(api_key="K")
    monkeypatch.setenv("OPEN_PREP_FMP_QUOTE_WORKERS", "4")

    def fake_execute(path: str, params: dict[str, Any], *, use_circuit_breaker: bool) -> Any:
        return [{"symbol": params["symbol"], "price": 1.0}]

    monkeypatch.setattr(client, "_execute_get", fake_execute)
    rows = client.get_batch_quotes(["A", "B", "C"])
    assert {row["symbol"] for row in rows} == {"A", "B", "C"}
    diag = client.get_last_quote_fetch_diagnostics()
    assert diag["quote_fetch_workers"] >= 2


def test_get_last_quote_fetch_diagnostics_returns_copy() -> None:
    client = FMPClient(api_key="K")
    client._last_quote_fetch_diagnostics = {
        "requested_symbols": ["A"],
        "deduped_symbols": ["A"],
        "fetched_unique_symbols": ["A"],
        "failed_quote_symbols": [],
    }
    diag = client.get_last_quote_fetch_diagnostics()
    diag["requested_symbols"].append("MUTATED")
    assert client._last_quote_fetch_diagnostics["requested_symbols"] == ["A"]


# ---------------------------------------------------------------------------
# FinnhubClient stubs (all return empty defaults)
# ---------------------------------------------------------------------------


def test_finnhub_client_from_env_and_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "K")
    client = FinnhubClient.from_env()
    assert client.api_key == "K"
    assert client.available() is True

    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert FinnhubClient.from_env().available() is False


def test_finnhub_client_all_getters_return_empty_defaults() -> None:
    client = FinnhubClient(api_key="K")
    assert client.get_insider_sentiment("AAPL", "2026-01-01", "2026-04-23") == []
    assert client.get_peers("AAPL") == []
    assert client.get_social_sentiment("AAPL") == {}
    assert client.get_pattern_recognition("AAPL") == []
    assert client.get_support_resistance("AAPL") == {}
    assert client.get_aggregate_indicators("AAPL") == {}
    assert client.get_fda_calendar() == []


# ---------------------------------------------------------------------------
# Constant-shape sanity checks
# ---------------------------------------------------------------------------


def test_default_high_impact_events_includes_core_macro_releases() -> None:
    """Pin the high-impact event names so accidental list edits are caught."""

    expected_minimum = {
        "cpi",
        "core cpi",
        "ppi",
        "pce",
        "core pce",
        "nonfarm payroll",
        "initial jobless claims",
    }
    assert expected_minimum.issubset(set(DEFAULT_HIGH_IMPACT_EVENTS))


def test_normalize_tls_certificate_env_replaces_invalid_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    fake_certifi = MagicMock()
    fake_ca = tmp_path / "cacert.pem"
    fake_ca.write_text("dummy")
    fake_certifi.where.return_value = str(fake_ca)
    monkeypatch.setattr(macro, "certifi", fake_certifi)
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/path/that/should/be/replaced.pem")
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

    result = macro._normalize_tls_certificate_env()
    assert result == str(fake_ca)
    # Env was rewritten to the certifi path.
    import os as _os

    assert _os.environ["SSL_CERT_FILE"] == str(fake_ca)


def test_normalize_tls_certificate_env_keeps_existing_valid_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    fake_certifi = MagicMock()
    fake_ca = tmp_path / "cacert.pem"
    fake_ca.write_text("dummy")
    fake_certifi.where.return_value = str(fake_ca)
    monkeypatch.setattr(macro, "certifi", fake_certifi)

    other_ca = tmp_path / "other.pem"
    other_ca.write_text("dummy")
    monkeypatch.setenv("SSL_CERT_FILE", str(other_ca))
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

    result = macro._normalize_tls_certificate_env()
    assert result == str(fake_ca)
    import os as _os

    # Existing valid bundle path was NOT rewritten.
    assert _os.environ["SSL_CERT_FILE"] == str(other_ca)


def test_normalize_tls_certificate_env_no_certifi_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(macro, "certifi", None)
    assert macro._normalize_tls_certificate_env() is None


def test_build_tls_context_returns_ssl_context() -> None:
    ctx = macro._build_tls_context()
    import ssl as _ssl

    assert isinstance(ctx, _ssl.SSLContext)


def test_today_et_date_returns_date_in_us_eastern() -> None:
    today = macro._today_et_date()
    assert isinstance(today, date)


# Silence unused-import warning if ever applicable.
_ = (time, _CircuitBreaker)


# ---------------------------------------------------------------------------
# Supplementary coverage: canonical_event_name branches, _macro_weight,
# filter_us_high_impact_events, parametrized RuntimeError fall-throughs, and
# _execute_get URLError-then-success retry path.
# ---------------------------------------------------------------------------


from open_prep.macro import (
    _canonical_event_name,
    _macro_weight,
    filter_us_high_impact_events,
)


@pytest.mark.parametrize(
    ("event_name", "expected"),
    [
        # PCE family
        ("PCE Price Index YoY", "pce_yoy"),
        ("PCE MoM", "pce_mom"),
        ("PCE Price Index", "pce"),
        ("Core PCE YoY", "core_pce_yoy"),
        ("Core PCE MoM", "core_pce_mom"),
        ("Core PCE Price Index", "core_pce"),
        # CPI family
        ("CPI YoY", "cpi_yoy"),
        ("CPI MoM", "cpi_mom"),
        ("Core CPI YoY", "core_cpi_yoy"),
        ("Core CPI MoM", "core_cpi_mom"),
        ("Core CPI", "core_cpi"),
        # PPI family
        ("PPI YoY", "ppi_yoy"),
        ("PPI MoM", "ppi_mom"),
        ("PPI", "ppi"),
        ("Core PPI YoY", "core_ppi_yoy"),
        ("Core PPI MoM", "core_ppi_mom"),
        ("Core PPI", "core_ppi"),
        # Labor
        ("Nonfarm Payrolls", "nonfarm_payrolls"),
        ("Initial Jobless Claims", "jobless_claims"),
        # ISM / sentiment / regional
        ("ISM Services PMI", "ism_services"),
        ("ISM Non-Manufacturing PMI", "ism_services"),
        ("ISM Manufacturing PMI", "ism_manufacturing"),
        ("Michigan Consumer Sentiment", "consumer_sentiment"),
        ("Philadelphia Fed Business Outlook Survey", "philadelphia_fed"),
        # GDP family
        ("GDP Growth Rate QoQ", "gdp_qoq"),
        ("Gross Domestic Product", "gdp_qoq"),
        ("GDP", "gdp_qoq"),
        ("GDPNow", "gdpnow"),
        # PMI variants
        ("S&P Global Manufacturing PMI", "pmi_sp_global"),
        # Generic fall-through -> snake-case
        ("Some Random Event Name", "some_random_event_name"),
    ],
)
def test_canonical_event_name_covers_all_branches(event_name: str, expected: str) -> None:
    assert _canonical_event_name(event_name) == expected


def test_filter_us_high_impact_events_keeps_high_impact_and_named_events() -> None:
    events = [
        # impact=high, US country -> kept
        {"country": "US", "event": "Some Custom High", "impact": "high"},
        # impact=low but name is on the high-impact list -> kept
        {"currency": "USD", "event": "CPI YoY", "impact": "low"},
        # impact=medium and not on list -> dropped
        {"country": "US", "event": "Retail Sales", "impact": "medium"},
        # non-US -> dropped (filter_us_events removes it before this)
        {"country": "DE", "event": "ECB Press Conference", "impact": "high"},
    ]
    kept = filter_us_high_impact_events(events)
    kept_names = [event.get("event") for event in kept]
    assert "Some Custom High" in kept_names
    assert "CPI YoY" in kept_names
    assert "Retail Sales" not in kept_names
    assert "ECB Press Conference" not in kept_names


@pytest.mark.parametrize(
    ("allow_mid_impact", "include_headline_pce_confirm", "event", "expected_weight"),
    [
        # Headline PCE — included only when explicitly enabled
        (True, True, {"event": "PCE Price Index YoY", "impact": "high"}, 0.25),
        (True, False, {"event": "PCE MoM", "impact": "low"}, 0.0),
        # GDP QoQ — fixed 0.5 regardless of impact
        (True, True, {"event": "GDP", "impact": "low"}, 0.5),
        # YoY core CPI -> 0.25
        (True, True, {"event": "Core CPI YoY", "impact": "low"}, 0.25),
        # Sentiment buckets — depend on allow_mid_impact OR impact==high
        (False, True, {"event": "Consumer Sentiment", "impact": "low"}, 0.0),
        (True, True, {"event": "Consumer Sentiment", "impact": "low"}, 0.25),
        (False, True, {"event": "Consumer Sentiment", "impact": "high"}, 0.25),
        # Bare high-impact -> 1.0
        (True, True, {"event": "Some Custom Event", "impact": "high"}, 1.0),
        # impact==1 mid -> 0.25 only when allowed
        (True, True, {"event": "Random Mid Event", "impact": "medium"}, 0.25),
        (False, True, {"event": "Random Mid Event", "impact": "medium"}, 0.0),
        # Bare "CPI" with impact=low: canonical_event=="cpi" doesn't match
        # any specific bucket, impact_rank is 0, so falls through to the
        # final `_is_high_impact_event_name` check which DOES recognize
        # the bare "cpi" token -> returns 1.0.
        (False, True, {"event": "CPI", "impact": "low"}, 1.0),
    ],
)
def test_macro_weight_branches(
    allow_mid_impact: bool,
    include_headline_pce_confirm: bool,
    event: dict[str, Any],
    expected_weight: float,
) -> None:
    weight = _macro_weight(
        event,
        allow_mid_impact=allow_mid_impact,
        include_headline_pce_confirm=include_headline_pce_confirm,
    )
    assert weight == expected_weight


@pytest.mark.parametrize(
    ("method", "args", "kwargs"),
    [
        ("get_company_screener", (), {"sector": "Tech"}),
        ("get_fmp_articles", (50,), {}),
        ("get_stock_latest_news", (), {"symbol": "AAPL"}),
        ("get_batch_crypto_quotes", (), {}),
        ("get_cryptocurrency_historical_price", ("BTCUSD",), {}),
        ("get_cryptocurrency_list", (), {}),
        ("get_macro_calendar", (date(2026, 1, 1), date(2026, 1, 31)), {}),
        ("get_premarket_movers", (), {}),
        ("get_batch_aftermarket_quote", (["AAPL", "MSFT"],), {}),
        ("get_splits_calendar", (date(2026, 1, 1), date(2026, 4, 23)), {}),
        ("get_dividends_calendar", (date(2026, 1, 1), date(2026, 4, 23)), {}),
        ("get_ipos_calendar", (date(2026, 1, 1), date(2026, 4, 23)), {}),
        ("get_upgrades_downgrades", (), {"symbol": "AAPL"}),
        ("get_insider_trading_latest", (), {"symbol": "AAPL", "limit": 10}),
        ("get_institutional_ownership", ("AAPL",), {"limit": 25}),
        ("get_treasury_rates", (date(2026, 1, 1), date(2026, 4, 23)), {}),
        ("get_house_trading", (50,), {}),
        ("get_analyst_estimates", ("AAPL",), {"period": "annual", "limit": 4}),
        ("get_earnings_report", ("AAPL",), {"limit": 6}),
        ("get_intraday_chart", ("AAPL",), {"interval": "5min", "day": date(2026, 4, 23)}),
        ("get_sector_performance_snapshot", (date(2026, 4, 23),), {}),
        ("get_eod_bulk", (date(2026, 4, 23),), {}),
        ("get_earnings_calendar", (date(2026, 4, 1), date(2026, 4, 30)), {}),
    ],
)
def test_runtime_error_falls_through_to_empty_collection(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    """Every list-returning getter that wraps `_get` in try/except must
    return an empty list when `_get` raises `RuntimeError`."""

    client = FMPClient(api_key="K")

    def boom(path: str, params: dict[str, Any]) -> Any:
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(client, "_get", boom)
    # Reset feature-unavailable cache so log-once methods can fire deterministically
    monkeypatch.setattr(macro, "_FMP_FEATURE_UNAVAILABLE_LOGGED", set())
    result = getattr(client, method)(*args, **kwargs)
    assert result == [] or result == {}


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "feature_key"),
    [
        ("get_ratios_ttm", ("AAPL",), {}, "stable/ratios-ttm"),
        ("get_company_screener", (), {"sector": "Tech"}, "stable/company-screener"),
        ("get_stock_latest_news", (), {"symbol": "AAPL"}, "stable/news/stock-latest"),
        ("get_batch_crypto_quotes", (), {}, "stable/batch-crypto-quotes"),
        (
            "get_cryptocurrency_historical_price",
            ("BTCUSD",),
            {},
            "stable/historical-price-eod/full",
        ),
        ("get_cryptocurrency_list", (), {}, "stable/cryptocurrency-list"),
        (
            "get_technical_indicator",
            ("AAPL", "1day", "rsi"),
            {},
            "stable/technical-indicators/rsi",
        ),
        ("get_eod_bulk", (date(2026, 4, 23),), {}, "stable/eod-bulk"),
        (
            "get_macro_calendar",
            (date(2026, 1, 1), date(2026, 1, 31)),
            {},
            "stable/economic-calendar",
        ),
        ("get_premarket_movers", (), {}, "stable/most-actives"),
    ],
)
def test_silent_fallback_logs_once_per_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    feature_key: str,
) -> None:
    """Each FMP getter must emit `_log_feature_unavailable_once` exactly once
    when its endpoint raises RuntimeError, instead of silently returning []/{}."""

    client = FMPClient(api_key="K")

    def boom(path: str, params: dict[str, Any]) -> Any:
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(client, "_get", boom)
    monkeypatch.setattr(macro, "_FMP_FEATURE_UNAVAILABLE_LOGGED", set())

    with caplog.at_level(logging.INFO, logger="open_prep.macro"):
        getattr(client, method)(*args, **kwargs)
        getattr(client, method)(*args, **kwargs)

    matching = [r for r in caplog.records if feature_key in r.message]
    assert len(matching) == 1, (
        f"{method} should emit log-once for {feature_key} on RuntimeError; "
        f"got {len(matching)} log records"
    )
    assert feature_key in macro._FMP_FEATURE_UNAVAILABLE_LOGGED


def test_execute_get_url_error_first_attempt_then_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover the URLError retry-and-continue branch (non-exhausted)."""

    client = FMPClient(api_key="K", retry_attempts=3, retry_backoff_seconds=0.0)
    calls: list[int] = []

    def flaky(path: str, params: dict[str, Any]) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.URLError("transient dns")
        return ["recovered"]

    monkeypatch.setattr(client, "_request_once", flaky)
    monkeypatch.setattr(macro.time, "sleep", lambda _s: None)
    out = client._execute_get("/x", {}, use_circuit_breaker=True)
    assert out == ["recovered"]
    assert len(calls) == 2
    assert client._circuit_breaker.state == "CLOSED"
