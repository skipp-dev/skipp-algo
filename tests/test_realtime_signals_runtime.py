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


def test_technical_scorer_uses_stale_cache_when_call_spacing_blocks_fetch(monkeypatch) -> None:
    scorer = rs.TechnicalScorer()
    now = 10_000.0
    key = "AAPL:1D"
    stale_payload = {
        "rsi": 42.0,
        "macd_signal": "BUY",
        "adx": 25.0,
        "williams": -35.0,
        "summary_signal": "BUY",
        "summary_buy": 8,
        "summary_sell": 2,
        "summary_neutral": 5,
        "ma_buy": 10,
        "ma_sell": 2,
        "technical_score": 0.77,
        "technical_signal": "BUY",
        "osc_detail": [],
        "ma_detail": [],
        "error": "",
    }
    scorer._cache[key] = (now - scorer._CACHE_TTL - 5.0, stale_payload)
    scorer._last_call_ts = now - 1.0
    monkeypatch.setattr(rs.time, "time", lambda: now)

    got = scorer.get_technical_data("AAPL", "1D")
    assert got == stale_payload


def test_volume_regime_warns_when_all_avg_volumes_missing(caplog) -> None:
    detector = rs.VolumeRegimeDetector()
    quotes = {
        "AAA": {"symbol": "AAA", "volume": 10_000, "avgVolume": 0},
        "BBB": {"symbol": "BBB", "volume": 20_000, "avgVolume": 0},
    }

    with caplog.at_level("WARNING"):
        regime = detector.update(quotes)

    assert regime == "NORMAL"
    assert detector.thin_fraction == 0.0
    assert "avgvolume unavailable" in caplog.text.lower()