from __future__ import annotations

import json
from collections import deque
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

    monkeypatch.setattr(http.server, "ThreadingHTTPServer", _fake_http_server)
    monkeypatch.setattr(threading, "Thread", _FakeThread)

    server = rs._start_telemetry_server(rs.ScoreTelemetry(), port=8099)
    assert server is not None
    assert attempts == [("0.0.0.0", 8099), ("0.0.0.0", 0)]

    telemetry = rs.get_rt_engine_telemetry_status()
    assert telemetry["enabled"] is True
    assert telemetry["active_port"] == 8123
    assert "requested port 8099 unavailable" in telemetry["error"].lower()


def test_start_telemetry_server_logs_active_port_for_zero_request(monkeypatch, caplog, tmp_path: Path) -> None:
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

    def _fake_http_server(_address, _handler):
        return _FakeServer(8123)

    import http.server
    import threading

    monkeypatch.setattr(http.server, "ThreadingHTTPServer", _fake_http_server)
    monkeypatch.setattr(threading, "Thread", _FakeThread)

    with caplog.at_level("INFO", logger="open_prep.realtime_signals"):
        server = rs._start_telemetry_server(rs.ScoreTelemetry(), port=0)

    assert server is not None
    telemetry = rs.get_rt_engine_telemetry_status()
    assert telemetry["active_port"] == 8123
    assert "http://0.0.0.0:8123" in caplog.text


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


def test_volume_regime_warns_when_all_avg_volumes_missing(monkeypatch, caplog) -> None:
    detector = rs.VolumeRegimeDetector()
    quotes = {
        "AAA": {"symbol": "AAA", "volume": 10_000, "avgVolume": 0},
        "BBB": {"symbol": "BBB", "volume": 20_000, "avgVolume": 0},
    }

    monkeypatch.setattr(rs.time, "monotonic", lambda: 42.0)

    with caplog.at_level("WARNING"):
        regime = detector.update(quotes)

    assert regime == "NORMAL"
    assert detector.thin_fraction == 0.0
    assert "avgvolume unavailable" in caplog.text.lower()


def test_volume_regime_uses_intraday_volume_pace(monkeypatch) -> None:
    detector = rs.VolumeRegimeDetector()
    # 22% of daily avg at 10:00 ET should not be considered thin when
    # the expected cumulative fraction is ~20%.
    quotes = {
        "AAA": {"symbol": "AAA", "volume": 220_000, "avgVolume": 1_000_000},
        "BBB": {"symbol": "BBB", "volume": 180_000, "avgVolume": 1_000_000},
    }
    monkeypatch.setattr(rs, "_expected_cumulative_volume_fraction", lambda: 0.20)

    regime = detector.update(quotes)
    assert regime == "NORMAL"
    assert detector.thin_fraction == 0.0


def test_resolve_expected_volume_fraction_prefers_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(rs, "_expected_cumulative_volume_fraction", lambda: 0.75)
    assert rs._resolve_expected_volume_fraction(0.30) == 0.30
    assert rs._resolve_expected_volume_fraction(None) == 0.75


def test_session_boundary_triggers_watchlist_rebuild(monkeypatch) -> None:
    monkeypatch.setattr(rs.RealtimeEngine, "_load_watchlist", lambda self: None)
    monkeypatch.setattr(rs.RealtimeEngine, "_restore_signals_from_disk", lambda self: None)

    engine = rs.RealtimeEngine(fmp_client=None)
    engine._was_outside_market = True
    engine._last_prices = {"AAA": 10.0}
    engine._price_history = {"AAA": deque([10.0])}
    engine._quote_hashes = {"AAA": "h"}
    engine._avg_vol_cache = {"AAA": 100_000}
    engine._earnings_today_cache = {"AAA": {"symbol": "AAA"}}
    engine._new_entrant_set = {"AAA"}

    called = {"reload": 0}

    def _reload() -> None:
        called["reload"] += 1

    monkeypatch.setattr(rs, "_is_within_market_hours", lambda: True)
    monkeypatch.setattr(engine, "reload_watchlist", _reload)
    monkeypatch.setattr(engine, "_fetch_realtime_quotes", lambda: {})
    monkeypatch.setattr(engine, "_save_signals", lambda *args, **kwargs: None)

    out = engine.poll_once()
    assert out == []
    assert called["reload"] == 1
    assert engine._last_prices == {}
    assert engine._quote_hashes == {}
    assert engine._avg_vol_cache == {"AAA": 100_000}  # preserved across session boundary (Fix #5)
    assert engine._new_entrant_set == {"AAA"}


def test_save_signals_sanitizes_non_finite_values(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rs.RealtimeEngine, "_load_watchlist", lambda self: None)
    monkeypatch.setattr(rs.RealtimeEngine, "_restore_signals_from_disk", lambda self: None)
    monkeypatch.setattr(rs, "SIGNALS_PATH", tmp_path / "latest_realtime_signals.json")
    monkeypatch.setattr(rs, "VD_SIGNALS_PATH", tmp_path / "latest_vd_signals.jsonl")

    engine = rs.RealtimeEngine(fmp_client=None)
    engine._watchlist = [{"symbol": "AAA"}]
    engine._vd_rows = {"AAA": {"symbol": "AAA", "score": float("nan"), "delta": float("inf")}}
    engine._active_signals = [
        rs.RealtimeSignal(
            symbol="AAA",
            level="A1",
            direction="LONG",
            pattern="BREAKOUT",
            price=100.0,
            prev_close=99.0,
            change_pct=1.0,
            volume_ratio=2.0,
            score=5.0,
            confidence_tier="HIGH_CONVICTION",
            atr_pct=0.5,
            freshness=1.0,
            fired_at="2026-01-01T00:00:00+00:00",
            fired_epoch=1.0,
            details={"adx": float("nan"), "nested": {"x": float("-inf")}},
        )
    ]

    engine._save_signals()

    signals_raw = rs.SIGNALS_PATH.read_text(encoding="utf-8")
    vd_raw = rs.VD_SIGNALS_PATH.read_text(encoding="utf-8")
    assert "NaN" not in signals_raw
    assert "Infinity" not in signals_raw
    assert "NaN" not in vd_raw
    assert "Infinity" not in vd_raw

    signals_payload = json.loads(signals_raw)
    assert signals_payload["signals"][0]["details"]["adx"] is None
    assert signals_payload["signals"][0]["details"]["nested"]["x"] is None


def test_save_signals_counts_a2_level(monkeypatch, tmp_path: Path) -> None:
    """The snapshot payload counts A2 (early-warning) alongside A0/A1 so the
    daemon can expose live_overlay_trading_signals_a2 (added 2026-07-08)."""
    monkeypatch.setattr(rs.RealtimeEngine, "_load_watchlist", lambda self: None)
    monkeypatch.setattr(rs.RealtimeEngine, "_restore_signals_from_disk", lambda self: None)
    monkeypatch.setattr(rs, "SIGNALS_PATH", tmp_path / "latest_realtime_signals.json")
    monkeypatch.setattr(rs, "VD_SIGNALS_PATH", tmp_path / "latest_vd_signals.jsonl")

    def _sig(symbol: str, level: str) -> rs.RealtimeSignal:
        return rs.RealtimeSignal(
            symbol=symbol, level=level, direction="LONG", pattern="BREAKOUT",
            price=100.0, prev_close=99.0, change_pct=1.0, volume_ratio=2.0,
            score=5.0, confidence_tier="HIGH_CONVICTION", atr_pct=0.5,
            freshness=1.0, fired_at="2026-01-01T00:00:00+00:00", fired_epoch=1.0,
            details={},
        )

    engine = rs.RealtimeEngine(fmp_client=None)
    engine._watchlist = []
    engine._vd_rows = {}
    engine._active_signals = [_sig("AAA", "A0"), _sig("BBB", "A1"), _sig("CCC", "A2"), _sig("DDD", "A2")]

    engine._save_signals()

    payload = json.loads(rs.SIGNALS_PATH.read_text(encoding="utf-8"))
    assert payload["signal_count"] == 4
    assert payload["a0_count"] == 1
    assert payload["a1_count"] == 1
    assert payload["a2_count"] == 2


def test_telemetry_server_is_threaded(monkeypatch, tmp_path: Path) -> None:
    """Regression: the telemetry endpoint must serve requests concurrently.

    A single-threaded HTTPServer let one slow /metrics scrape block /healthz
    past Railway's ~30s timeout. It is now a ThreadingHTTPServer.
    """
    import socketserver

    monkeypatch.setattr(rs, "_RT_ENGINE_TELEMETRY_FILE", tmp_path / "realtime_telemetry.json")

    # port=0 → ephemeral, always bindable, so this exercises the real server.
    server = rs._start_telemetry_server(rs.ScoreTelemetry(), port=0)
    assert server is not None
    try:
        assert isinstance(server, socketserver.ThreadingMixIn)
        assert getattr(server, "daemon_threads", False) is True
    finally:
        server.shutdown()
        server.server_close()


def test_volume_regime_empty_quotes_preserves_prior_regime() -> None:
    """A transient empty quote map (fetch hiccup) must NOT reset the regime to
    NORMAL — that would silently lift an active HOLIDAY_SUSPECT suspension on a
    single bad poll. The prior regime is kept unchanged."""
    detector = rs.VolumeRegimeDetector()
    detector.regime = "HOLIDAY_SUSPECT"
    detector.thin_fraction = 0.9
    assert detector.update({}) == "HOLIDAY_SUSPECT"
    assert detector.regime == "HOLIDAY_SUSPECT"
    assert detector.thin_fraction == 0.9  # no-op, not reset to 0.0


def test_async_poller_start_spawns_one_thread_under_concurrency(
    monkeypatch,
) -> None:
    """Concurrent start() calls must spawn exactly ONE background loop — a bare
    check-then-start races (two callers both see _thread is None). The lock makes
    the check-and-create atomic."""
    import threading

    poller = rs.AsyncNewsstackPoller()
    # Cheap blocking loop so a started thread stays alive across sibling starts.
    monkeypatch.setattr(poller, "_loop", lambda: poller._stop.wait())

    real_thread_cls = threading.Thread
    created: list = []

    def _counting_thread(*args, **kwargs):
        th = real_thread_cls(*args, **kwargs)
        if kwargs.get("name") == "newsstack-bg":
            created.append(th)
        return th

    monkeypatch.setattr(threading, "Thread", _counting_thread)
    barrier = threading.Barrier(8)

    def _racer() -> None:
        barrier.wait()
        poller.start()

    racers = [real_thread_cls(target=_racer) for _ in range(8)]
    try:
        for r in racers:
            r.start()
        for r in racers:
            r.join(timeout=5.0)
        assert len(created) == 1
    finally:
        poller.stop(timeout=2.0)


def _mk_a1(direction: str = "LONG") -> rs.RealtimeSignal:
    return rs.RealtimeSignal(
        symbol="AAA", level="A1", direction=direction, pattern="BREAKOUT",
        price=100.0, prev_close=99.0, change_pct=1.0, volume_ratio=2.0,
        score=5.0, confidence_tier="HIGH_CONVICTION", atr_pct=0.5,
        freshness=1.0, fired_at="2026-01-01T00:00:00+00:00", fired_epoch=1.0,
    )


def _news_upgrade_poll(monkeypatch, *, polarity: float, direction: str = "LONG"):
    monkeypatch.setattr(rs.RealtimeEngine, "_load_watchlist", lambda self: None)
    monkeypatch.setattr(rs.RealtimeEngine, "_restore_signals_from_disk", lambda self: None)
    monkeypatch.setattr(rs, "_is_within_market_hours", lambda: True)

    engine = rs.RealtimeEngine(fmp_client=None)
    engine._watchlist = [{"symbol": "AAA"}]

    class _NewsStub:
        def latest(self):
            return {"AAA": {
                "news_score": 0.9, "polarity": polarity,
                "category": "ma_deal", "headline": "h", "warn_flags": [],
            }}

    engine._async_newsstack = _NewsStub()
    monkeypatch.setattr(
        engine, "_fetch_realtime_quotes",
        lambda: {"AAA": {"symbol": "AAA", "price": 100.0, "volume": 1_000_000}},
    )
    monkeypatch.setattr(
        engine, "_detect_signal",
        lambda *a, **k: _mk_a1(direction),
    )
    monkeypatch.setattr(engine, "_save_signals", lambda *a, **k: None)
    signals = engine.poll_once()
    assert signals, "poll_once must yield the detected signal"
    return signals[0]


def test_news_catalyst_upgrade_requires_aligned_polarity(monkeypatch) -> None:
    # A strongly BEARISH headline (polarity<0) must NOT escalate a LONG A1 to
    # A0 — news_score is a direction-less magnitude; the sign is in polarity.
    sig = _news_upgrade_poll(monkeypatch, polarity=-0.9, direction="LONG")
    assert sig.level == "A1"
    assert sig.details.get("a0_upgrade_reason") != "news_catalyst"


def test_news_catalyst_upgrade_fires_on_aligned_polarity(monkeypatch) -> None:
    sig = _news_upgrade_poll(monkeypatch, polarity=0.9, direction="LONG")
    assert sig.level == "A0"
    assert sig.details.get("a0_upgrade_reason") == "news_catalyst"


def test_news_catalyst_upgrade_neutral_polarity_does_not_escalate(monkeypatch) -> None:
    sig = _news_upgrade_poll(monkeypatch, polarity=0.0, direction="LONG")
    assert sig.level == "A1"


def test_rt_engine_status_revalidates_stale_running_flag(monkeypatch, tmp_path: Path) -> None:
    # A crashed engine leaves running:true + a dead PID in the status file —
    # get_rt_engine_status must re-validate liveness instead of echoing it.
    status = tmp_path / "rt_engine_status.json"
    status.write_text(
        json.dumps({"running": True, "pid": 99_999_999, "error": "", "log_path": "x"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", status)
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: None)
    out = rs.get_rt_engine_status()
    assert out["running"] is False
    assert out["pid"] is None
