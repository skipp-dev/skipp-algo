from __future__ import annotations

from pathlib import Path

import open_prep.realtime_signals as rs


def test_ensure_rt_engine_running_fails_when_lock_is_held_without_visible_process(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_LOCK_FILE", tmp_path / "realtime_engine.lock")
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", tmp_path / "realtime_engine_status.json")
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: None)

    def _fake_flock(_fd, _op):
        raise OSError("locked")

    monotonic_values = iter([0.0, 3.0])
    monkeypatch.setattr(rs.fcntl, "flock", _fake_flock)
    monkeypatch.setattr(rs.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(rs.time, "monotonic", lambda: next(monotonic_values, 3.0))

    assert rs.ensure_rt_engine_running(project_root=tmp_path) is False

    status = rs.get_rt_engine_status()
    assert status["running"] is False
    assert "lock held" in status["error"].lower()


def test_start_telemetry_server_falls_back_to_ephemeral_port(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_TELEMETRY_FILE", tmp_path / "realtime_telemetry.json")

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
        if port == 8099:
            raise OSError("address already in use")
        return _FakeServer(8123)

    import http.server
    import threading

    monkeypatch.setattr(http.server, "HTTPServer", _fake_http_server)
    monkeypatch.setattr(threading, "Thread", _FakeThread)

    server = rs._start_telemetry_server(rs.ScoreTelemetry(), port=8099)
    assert server is not None
    assert attempts == [("127.0.0.1", 8099), ("127.0.0.1", 0)]

    telemetry = rs.get_rt_engine_telemetry_status()
    assert telemetry["enabled"] is True
    assert telemetry["active_port"] == 8123
    assert "requested port 8099 unavailable" in telemetry["error"].lower()