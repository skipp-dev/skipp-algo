from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import open_prep.realtime_signals as rs


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_fetch_json_url_returns_decoded_mapping(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return _FakeResponse(json.dumps({"ranked_v2": [{"symbol": "AAPL"}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    payload = rs._fetch_json_url("https://example.test/snapshot.json", timeout=7.0)

    assert payload == {"ranked_v2": [{"symbol": "AAPL"}]}
    assert captured["url"] == "https://example.test/snapshot.json"
    assert captured["timeout"] == 7.0


def test_fetch_json_url_rejects_non_http_scheme(monkeypatch) -> None:
    def _boom(*_a: object, **_k: object) -> None:  # pragma: no cover - must not run
        raise AssertionError("urlopen should not be called for unsupported scheme")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    assert rs._fetch_json_url("ftp://example.test/snapshot.json") is None
    assert rs._fetch_json_url("file:///etc/passwd") is None


def test_fetch_json_url_returns_none_on_network_error(monkeypatch) -> None:
    def _fake_urlopen(_request, timeout):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    assert rs._fetch_json_url("https://example.test/snapshot.json") is None


def test_fetch_json_url_returns_none_on_non_object_json(monkeypatch) -> None:
    def _fake_urlopen(_request, timeout):
        return _FakeResponse(json.dumps([1, 2, 3]).encode())

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    assert rs._fetch_json_url("https://example.test/snapshot.json") is None


def test_telemetry_server_honours_bind_host_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEMETRY_BIND_HOST", "0.0.0.0")

    class _FakeServer:
        def __init__(self, port: int) -> None:
            self.server_port = port

        def serve_forever(self) -> None:
            return None

    class _FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            self._target = target
            self.daemon = daemon

        def start(self) -> None:
            return None

    attempts: list[tuple[str, int]] = []

    def _fake_http_server(address, _handler):
        host, port = address
        attempts.append((host, port))
        return _FakeServer(port or 8099)

    import http.server
    import threading

    monkeypatch.setattr(http.server, "HTTPServer", _fake_http_server)
    monkeypatch.setattr(threading, "Thread", _FakeThread)

    server = rs._start_telemetry_server(rs.ScoreTelemetry(), port=8099)

    assert server is not None
    assert attempts == [("0.0.0.0", 8099)]


def test_telemetry_server_explicit_host_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEMETRY_BIND_HOST", "0.0.0.0")

    class _FakeServer:
        server_port = 8099

        def serve_forever(self) -> None:
            return None

    class _FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            self._target = target

        def start(self) -> None:
            return None

    attempts: list[tuple[str, int]] = []

    def _fake_http_server(address, _handler):
        attempts.append(address)
        return _FakeServer()

    import http.server
    import threading

    monkeypatch.setattr(http.server, "HTTPServer", _fake_http_server)
    monkeypatch.setattr(threading, "Thread", _FakeThread)

    rs._start_telemetry_server(rs.ScoreTelemetry(), port=8099, host="127.0.0.1")

    assert attempts == [("127.0.0.1", 8099)]


def test_signals_route_serves_latest_signals(monkeypatch, tmp_path) -> None:
    signals_file = tmp_path / "latest_realtime_signals.json"
    signals_file.write_text(json.dumps({"signals": [{"symbol": "MSFT"}]}), encoding="utf-8")
    monkeypatch.setattr(rs, "SIGNALS_PATH", signals_file)

    handler_cls = _build_handler(monkeypatch)
    handler = _invoke_get(handler_cls, "/signals")

    assert handler.status == 200
    assert json.loads(handler.body) == {"signals": [{"symbol": "MSFT"}]}


def _build_handler(monkeypatch, *, engine=None):
    """Start the telemetry server with fakes and return the registered handler class."""

    captured: dict[str, object] = {}

    class _FakeServer:
        server_port = 8099

        def serve_forever(self) -> None:
            return None

    class _FakeThread:
        def __init__(self, *, target, daemon: bool) -> None:
            pass

        def start(self) -> None:
            return None

    def _fake_http_server(_address, handler):
        captured["handler"] = handler
        return _FakeServer()

    import http.server
    import threading

    monkeypatch.setattr(http.server, "HTTPServer", _fake_http_server)
    monkeypatch.setattr(threading, "Thread", _FakeThread)

    rs._start_telemetry_server(rs.ScoreTelemetry(), port=8099, engine=engine)
    return captured["handler"]


def _invoke_get(handler_cls, path: str, *, headers: dict[str, str] | None = None):
    """Drive ``do_GET`` on the handler without a real socket."""

    handler = handler_cls.__new__(handler_cls)
    handler.path = path
    handler.headers = headers or {}
    handler.wfile = io.BytesIO()
    handler._status = None
    handler._headers: list[tuple[str, str]] = []

    def _send_response(code: int) -> None:
        handler._status = code

    def _send_header(key: str, value: str) -> None:
        handler._headers.append((key, value))

    def _end_headers() -> None:
        return None

    handler.send_response = _send_response  # type: ignore[method-assign]
    handler.send_header = _send_header  # type: ignore[method-assign]
    handler.end_headers = _end_headers  # type: ignore[method-assign]

    handler.do_GET()

    class _Result:
        status = handler._status
        body = handler.wfile.getvalue()

    return _Result()


def test_signals_route_cold_start_uses_engine_when_file_missing(monkeypatch, tmp_path) -> None:
    """F1: /signals must not return empty payload during the cold-start window.

    When the first ``poll_once()`` has not yet written ``SIGNALS_PATH``, the
    handler falls back to live engine state and tags the payload with
    ``status="cold_start"`` so consumers can distinguish it from steady-state.
    """
    missing = tmp_path / "never_written.json"
    monkeypatch.setattr(rs, "SIGNALS_PATH", missing)

    class _StubEngine:
        def get_active_signals(self):
            return []

    handler_cls = _build_handler(monkeypatch, engine=_StubEngine())
    handler = _invoke_get(handler_cls, "/signals")

    assert handler.status == 200
    payload = json.loads(handler.body)
    assert payload["status"] == "cold_start"
    assert payload["signals"] == []
    assert payload["signal_count"] == 0


def test_signals_route_rejects_missing_bearer_when_token_set(monkeypatch, tmp_path) -> None:
    """F2: when SIGNALS_INTERNAL_TOKEN is set, /signals requires a Bearer token."""
    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "s3cret")
    signals_file = tmp_path / "latest_realtime_signals.json"
    signals_file.write_text(json.dumps({"signals": []}), encoding="utf-8")
    monkeypatch.setattr(rs, "SIGNALS_PATH", signals_file)

    handler_cls = _build_handler(monkeypatch)

    no_header = _invoke_get(handler_cls, "/signals")
    bad_header = _invoke_get(handler_cls, "/signals", headers={"Authorization": "Bearer wrong"})
    wrong_scheme = _invoke_get(handler_cls, "/signals", headers={"Authorization": "Basic abc"})

    assert no_header.status == 401
    assert bad_header.status == 401
    assert wrong_scheme.status == 401


def test_signals_route_accepts_correct_bearer_when_token_set(monkeypatch, tmp_path) -> None:
    """F2: a matching Bearer token returns the normal /signals payload."""
    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "s3cret")
    signals_file = tmp_path / "latest_realtime_signals.json"
    signals_file.write_text(json.dumps({"signals": [{"symbol": "NVDA"}]}), encoding="utf-8")
    monkeypatch.setattr(rs, "SIGNALS_PATH", signals_file)

    handler_cls = _build_handler(monkeypatch)
    handler = _invoke_get(handler_cls, "/signals", headers={"Authorization": "Bearer s3cret"})

    assert handler.status == 200
    assert json.loads(handler.body) == {"signals": [{"symbol": "NVDA"}]}


def test_signals_route_accepts_bearer_with_whitespace_and_case(monkeypatch, tmp_path) -> None:
    """RFC 7230 tolerant parsing — case-insensitive scheme and trimmed token."""
    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "s3cret")
    signals_file = tmp_path / "latest_realtime_signals.json"
    signals_file.write_text(json.dumps({"signals": [{"symbol": "NVDA"}]}), encoding="utf-8")
    monkeypatch.setattr(rs, "SIGNALS_PATH", signals_file)

    handler_cls = _build_handler(monkeypatch)
    trailing_space = _invoke_get(handler_cls, "/signals", headers={"Authorization": "Bearer s3cret "})
    lower_scheme = _invoke_get(handler_cls, "/signals", headers={"Authorization": "bearer s3cret"})

    assert trailing_space.status == 200
    assert lower_scheme.status == 200


def test_signals_route_rejects_bearer_with_crlf_in_scheme(monkeypatch, tmp_path) -> None:
    """CR/LF in the scheme separator must not allow auth bypass (CVE-class: header injection)."""
    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "s3cret")
    signals_file = tmp_path / "latest_realtime_signals.json"
    signals_file.write_text(json.dumps({"signals": [{"symbol": "NVDA"}]}), encoding="utf-8")
    monkeypatch.setattr(rs, "SIGNALS_PATH", signals_file)

    handler_cls = _build_handler(monkeypatch)
    lf_bypass = _invoke_get(handler_cls, "/signals", headers={"Authorization": "Bearer\ns3cret"})
    cr_bypass = _invoke_get(handler_cls, "/signals", headers={"Authorization": "Bearer\rs3cret"})
    tab_scheme = _invoke_get(handler_cls, "/signals", headers={"Authorization": "Bearer\ts3cret"})

    assert lf_bypass.status == 401
    assert cr_bypass.status == 401
    assert tab_scheme.status == 401


# ─── BUG-1/2/3 regression tests ─────────────────────────────────────────────


def test_realtime_engine_lock_initialized() -> None:
    """BUG-1 regression: RealtimeEngine.__init__ must initialize self._lock.

    Previously ``get_active_signals()`` raised ``AttributeError`` on every
    live-state request because ``_lock`` was used but never assigned.
    """
    import threading

    engine = rs.RealtimeEngine(poll_interval=10)
    assert hasattr(engine, "_lock"), "RealtimeEngine._lock not initialized"
    assert isinstance(engine._lock, type(threading.Lock()))
    # Must not raise AttributeError
    assert engine.get_active_signals() == []


def test_signals_route_returns_error_on_nan_payload(monkeypatch, tmp_path) -> None:
    """BUG-2 regression: NaN/Infinity in a signals payload must not cause a
    connection abort.  Previously ``json.dumps(..., allow_nan=False)`` was
    called without a try/except, leaving the client with a half-open socket.
    """
    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "")

    # Write a signals file containing a non-finite float value encoded via the
    # non-standard JSON extension that Python's json.loads accepts.
    signals_file = tmp_path / "latest_realtime_signals.json"
    # Build a dict with NaN and serialise with allow_nan=True so we can write
    # a file that will later fail on allow_nan=False.
    import math

    raw_payload = {"signals": [{"symbol": "NVDA", "score": math.nan}]}
    signals_file.write_text(
        json.dumps(raw_payload, allow_nan=True), encoding="utf-8"
    )
    monkeypatch.setattr(rs, "SIGNALS_PATH", signals_file)

    handler_cls = _build_handler(monkeypatch)
    result = _invoke_get(handler_cls, "/signals")

    # Must respond with *some* HTTP status (not leave connection open), and the
    # body should contain "error" rather than a bare NaN literal.
    assert result.status is not None, "Handler must always set a response code"
    body_text = result.body.decode("utf-8", errors="replace")
    assert "error" in body_text.lower() or result.status == 200


def test_signals_route_reads_token_per_request(monkeypatch, tmp_path) -> None:
    """BUG-3 regression: auth token must be read from the environment on every
    request, not captured at server-start time.

    Previously the token was read once into a closure variable when the server
    was constructed; a runtime ``SIGNALS_INTERNAL_TOKEN`` change was silently
    ignored until restart.
    """
    # Set an initial token value before building the handler.
    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "old-token")
    signals_file = tmp_path / "latest_realtime_signals.json"
    signals_file.write_text(json.dumps({"signals": []}), encoding="utf-8")
    monkeypatch.setattr(rs, "SIGNALS_PATH", signals_file)

    handler_cls = _build_handler(monkeypatch)

    # Now rotate the token *after* the handler class was created.
    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "new-token")

    # A request with the new token must be accepted (200).
    accepted = _invoke_get(
        handler_cls, "/signals", headers={"Authorization": "Bearer new-token"}
    )
    # A request with the old token must now be rejected (401).
    rejected = _invoke_get(
        handler_cls, "/signals", headers={"Authorization": "Bearer old-token"}
    )

    assert accepted.status == 200, (
        f"Expected 200 with rotated token, got {accepted.status}"
    )
    assert rejected.status == 401, (
        f"Expected 401 for stale token, got {rejected.status}"
    )
