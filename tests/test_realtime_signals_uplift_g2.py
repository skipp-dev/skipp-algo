"""Bucket G #2 — additional uplift for `open_prep.realtime_signals`.

Targets `RealtimeEngine` instance methods that don't require the FMP
network: `_load_watchlist`, `reload_watchlist`, `_fetch_realtime_quotes`,
`_save_vd_snapshot`, `_enrich_watchlist_live`; plus
`_ensure_rt_engine_running_locked` (subprocess.Popen patched) and the
`_start_telemetry_server` HTTP server (bound to ephemeral port).

Engines are constructed via `__new__` to avoid the constructor's file I/O
side-effects; we then assign the minimal attributes each tested method
relies on. This keeps tests deterministic and isolated.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from open_prep import realtime_signals as rs

# ---------------------------------------------------------------------------
# Helper: build a barebones engine that bypasses __init__
# ---------------------------------------------------------------------------


def _make_engine(**overrides: Any) -> rs.RealtimeEngine:
    eng = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    eng.poll_interval = 20
    eng.top_n = 0
    eng.fast_mode = False
    eng.ultra_mode = False
    eng._client = None
    eng._client_disabled_reason = None
    eng._active_signals = []
    eng._watchlist = []
    eng._last_prices = {}
    eng._price_history = {}
    eng._was_outside_market = False
    eng._hysteresis = rs.GateHysteresis()
    eng._dynamic_cooldown = rs.DynamicCooldown(base_seconds=10.0)
    eng._volume_regime = rs.VolumeRegimeDetector()
    eng.telemetry = rs.ScoreTelemetry()
    eng._delta_tracker = rs.QuoteDeltaTracker()
    eng._async_newsstack = None
    eng._vd_rows = {}
    eng._vd_last_change_epoch = {}
    eng._poll_seq = 0
    eng._avg_vol_cache = {}
    eng._earnings_today_cache = {}
    eng._new_entrant_set = set()
    eng._technical_scorer = rs.TechnicalScorer()
    eng._quote_hashes = {}
    eng.last_poll_duration = 0.0
    for k, v in overrides.items():
        setattr(eng, k, v)
    return eng


# ---------------------------------------------------------------------------
# _load_watchlist
# ---------------------------------------------------------------------------


def test_load_watchlist_missing_file_warns_and_keeps_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "LATEST_RUN_PATH", tmp_path / "no.json")
    monkeypatch.setattr(rs, "_LEGACY_RUN_PATH", tmp_path / "also_no.json")
    eng = _make_engine()
    eng._load_watchlist()
    assert eng._watchlist == []


def test_load_watchlist_full_universe_with_overflow_and_quotes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = {
        "ranked_v2": [
            {"symbol": "AAA", "avg_volume": 5000},
            {"symbol": "aaa"},  # duplicate (case)
            {"symbol": "BBB"},
        ],
        "filtered_out_v2": [
            {"symbol": "CCC", "filter_reasons": ["below_top_n_cutoff"]},
            {"symbol": "ZZZ", "filter_reasons": ["bad_news"]},  # truly filtered
        ],
        "enriched_quotes": [
            {"symbol": "DDD", "price": 10.5, "avgVolume": 9000},
        ],
        "diff": {"new_entrants": ["bbb", "DDD"]},
    }
    p = tmp_path / "latest_open_prep_run.json"
    p.write_text(json.dumps(payload))
    monkeypatch.setattr(rs, "LATEST_RUN_PATH", p)
    monkeypatch.setattr(rs, "_LEGACY_RUN_PATH", tmp_path / "missing.json")

    eng = _make_engine()
    # Force `client` access in `_enrich_watchlist_live` to short-circuit
    eng._client_disabled_reason = "no_key"

    eng._load_watchlist()
    syms = [w["symbol"] for w in eng._watchlist]
    assert syms == ["AAA", "BBB", "CCC", "DDD"]
    assert eng._new_entrant_set == {"BBB", "DDD"}


def test_load_watchlist_top_n_slices(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = {"ranked_v2": [{"symbol": s} for s in ["A", "B", "C", "D"]]}
    p = tmp_path / "latest.json"
    p.write_text(json.dumps(payload))
    monkeypatch.setattr(rs, "LATEST_RUN_PATH", p)
    monkeypatch.setattr(rs, "_LEGACY_RUN_PATH", tmp_path / "x.json")
    eng = _make_engine(top_n=2, _client_disabled_reason="no_key")
    eng._load_watchlist()
    assert [w["symbol"] for w in eng._watchlist] == ["A", "B"]


def test_load_watchlist_invalid_json_logs_and_continues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    monkeypatch.setattr(rs, "LATEST_RUN_PATH", p)
    monkeypatch.setattr(rs, "_LEGACY_RUN_PATH", tmp_path / "x.json")
    eng = _make_engine()
    eng._load_watchlist()  # should not raise
    assert eng._watchlist == []


# ---------------------------------------------------------------------------
# reload_watchlist — prunes stale per-symbol tracker entries
# ---------------------------------------------------------------------------


def test_reload_watchlist_prunes_stale_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = {"ranked_v2": [{"symbol": "AAA"}]}
    p = tmp_path / "latest.json"
    p.write_text(json.dumps(payload))
    monkeypatch.setattr(rs, "LATEST_RUN_PATH", p)
    monkeypatch.setattr(rs, "_LEGACY_RUN_PATH", tmp_path / "x.json")

    eng = _make_engine(_client_disabled_reason="no_key")
    # Pre-seed stale keys
    eng._last_prices = {"AAA": 1.0, "OLD": 2.0}
    eng._price_history = {"AAA": [], "OLD": []}
    eng._quote_hashes = {"AAA": "x", "OLD": "y"}
    eng._delta_tracker._prev = {"AAA": {}, "OLD": {}}
    eng._delta_tracker._streaks = {"AAA": (0, "")}
    eng._delta_tracker._streaks["OLD"] = (0, "")
    eng._hysteresis._state = {"AAA": "A1", "OLD": "A0"}
    eng._dynamic_cooldown._transitions = {"AAA": [], "OLD": []}
    eng._dynamic_cooldown._last_a0 = {"AAA": 0.0, "OLD": 0.0}
    eng._vd_last_change_epoch = {"AAA": 0.0, "OLD": 0.0}
    eng._avg_vol_cache = {"AAA": 1000.0, "OLD": 999.0}

    eng.reload_watchlist()

    for d in (eng._last_prices, eng._price_history, eng._quote_hashes,
              eng._delta_tracker._prev, eng._delta_tracker._streaks,
              eng._hysteresis._state,
              eng._dynamic_cooldown._transitions,
              eng._dynamic_cooldown._last_a0,
              eng._vd_last_change_epoch,
              eng._avg_vol_cache):
        assert "OLD" not in d


# ---------------------------------------------------------------------------
# _fetch_realtime_quotes
# ---------------------------------------------------------------------------


def test_fetch_realtime_quotes_short_circuits_when_disabled() -> None:
    eng = _make_engine(_client_disabled_reason="no_key")
    eng._watchlist = [{"symbol": "AAA"}]
    assert eng._fetch_realtime_quotes() == {}


def test_fetch_realtime_quotes_empty_watchlist_returns_empty() -> None:
    eng = _make_engine()
    assert eng._fetch_realtime_quotes() == {}


def test_fetch_realtime_quotes_no_symbols_returns_empty() -> None:
    eng = _make_engine()
    eng._watchlist = [{"symbol": ""}, {"foo": "bar"}]
    assert eng._fetch_realtime_quotes() == {}


def test_fetch_realtime_quotes_aggregates_chunks_and_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rs, "_BATCH_QUOTE_CHUNK_SIZE", 2)

    class _FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def get_batch_quotes(self, syms: list[str]) -> list[dict[str, Any]]:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("transient")
            return [{"symbol": s, "price": 1.0} for s in syms]

    fake = _FakeClient()
    eng = _make_engine(_client=fake)
    eng._watchlist = [{"symbol": s} for s in ["A", "B", "C", "D"]]
    out = eng._fetch_realtime_quotes()
    assert set(out.keys()) == {"A", "B"}  # second chunk failed
    assert fake.calls == 2


# ---------------------------------------------------------------------------
# _save_vd_snapshot
# ---------------------------------------------------------------------------


def test_save_vd_snapshot_no_rows_is_noop(tmp_path: Path) -> None:
    eng = _make_engine()
    eng._save_vd_snapshot()  # must not raise


def test_save_vd_snapshot_writes_meta_and_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "vd.jsonl"
    monkeypatch.setattr(rs, "VD_SIGNALS_PATH", out)
    eng = _make_engine()
    eng._poll_seq = 7
    eng._vd_rows = {
        "AAA": {"symbol": "AAA", "signal": "A0", "last_change_age_s": 10},
        "BBB": {"symbol": "BBB", "signal": "A1", "last_change_age_s": 400},
    }
    eng._save_vd_snapshot()
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 3  # meta + 2 symbols
    meta = json.loads(lines[0])
    assert meta["poll_seq"] == 7
    assert "STALE" in meta["symbol"]  # 400s > 300s threshold
    assert "A0=1 A1=1" in meta["signal"]


# ---------------------------------------------------------------------------
# _enrich_watchlist_live
# ---------------------------------------------------------------------------


def test_enrich_watchlist_live_no_client_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eng = _make_engine()
    eng._watchlist = [{"symbol": "AAA", "avg_volume": 50}]

    # Force the `client` property to raise RuntimeError (caught by
    # `_enrich_watchlist_live`'s try/except).
    def boom(cls: Any) -> Any:
        raise RuntimeError("no key")

    monkeypatch.setattr(rs.FMPClient, "from_env", classmethod(boom))
    eng._enrich_watchlist_live()  # must not raise


def test_enrich_watchlist_live_uses_bulk_profile_and_earnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeClient:
        def get_profile_bulk(self) -> list[dict[str, Any]]:
            return [
                {"symbol": "AAA", "averageVolume": 50000},
                {"symbol": "BBB", "volAvg": 20000},
                {"symbol": "ZZZ", "averageVolume": 100},  # below 1000 → ignored
            ]

        def get_earnings_calendar(self, _start: Any, _end: Any) -> list[dict[str, Any]]:
            return [{"symbol": "AAA", "time": "BMO"}]

    eng = _make_engine(_client=_FakeClient())
    eng._watchlist = [
        {"symbol": "AAA", "avg_volume": 0},
        {"symbol": "BBB", "avg_volume": 0},
    ]
    eng._enrich_watchlist_live()
    assert eng._avg_vol_cache.get("AAA") == 50000
    assert eng._avg_vol_cache.get("BBB") == 20000
    aaa = next(w for w in eng._watchlist if w["symbol"] == "AAA")
    assert aaa["avg_volume"] == 50000
    assert aaa.get("earnings_today") is True
    assert aaa.get("earnings_timing") == "bmo"


def test_enrich_watchlist_live_falls_back_to_per_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rs.time, "sleep", lambda *_a, **_k: None)

    class _FakeClient:
        def get_profile_bulk(self) -> list[dict[str, Any]]:
            raise RuntimeError("bulk down")

        def get_company_profile(self, sym: str) -> dict[str, Any]:
            return {"symbol": sym, "averageVolume": 25000}

        def get_earnings_calendar(self, *_args: Any) -> list[dict[str, Any]]:
            return []

    eng = _make_engine(_client=_FakeClient())
    eng._watchlist = [{"symbol": "AAA", "avg_volume": 0}]
    eng._enrich_watchlist_live()
    assert eng._avg_vol_cache.get("AAA") == 25000


# ---------------------------------------------------------------------------
# _start_telemetry_server — bind ephemeral port and hit /healthz
# ---------------------------------------------------------------------------


def test_start_telemetry_server_serves_healthz_and_telemetry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_TELEMETRY_FILE", tmp_path / "tel.json")
    telemetry = rs.ScoreTelemetry()
    server = rs._start_telemetry_server(telemetry, port=0)  # 0 = ephemeral
    assert server is not None
    try:
        port = server.server_port
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as resp:
            assert resp.status == 200
            assert resp.read() == b"ok\n"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/telemetry.json", timeout=3) as resp:
            assert resp.status == 200
            assert json.loads(resp.read())  # parses
        # 404 path
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/missing", timeout=3)
        assert exc_info.value.code == 404
    finally:
        server.shutdown()


def test_start_telemetry_server_falls_back_when_port_busy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_TELEMETRY_FILE", tmp_path / "tel.json")

    # First HTTPServer raises; second succeeds on ephemeral port
    import http.server as hs
    real_cls = hs.HTTPServer
    state = {"calls": 0}

    class _FlakyHTTPServer(real_cls):  # type: ignore[misc, valid-type]
        def __init__(self, server_address: Any, RequestHandlerClass: Any) -> None:
            state["calls"] += 1
            if state["calls"] == 1:
                raise OSError("port busy")
            super().__init__(("127.0.0.1", 0), RequestHandlerClass)

    monkeypatch.setattr(hs, "HTTPServer", _FlakyHTTPServer)

    telemetry = rs.ScoreTelemetry()
    server = rs._start_telemetry_server(telemetry, port=8099)
    assert server is not None
    assert state["calls"] == 2
    try:
        assert server.server_port != 8099
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# _ensure_rt_engine_running_locked
# ---------------------------------------------------------------------------


def test_ensure_rt_engine_running_locked_returns_true_when_already_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(rs, "_RT_ENGINE_LOG_FILE", tmp_path / "rt.log")
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: 4242)
    out = rs._ensure_rt_engine_running_locked(
        poll_interval=20, project_root=tmp_path,
    )
    assert out is True


def test_ensure_rt_engine_running_locked_starts_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(rs, "_RT_ENGINE_LOG_FILE", tmp_path / "rt.log")
    monkeypatch.setattr(rs, "_RT_ENGINE_PID_FILE", tmp_path / "rt.pid")
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: None)
    monkeypatch.setattr(rs.time, "sleep", lambda *_a, **_k: None)

    class _FakeProc:
        pid = 9999

        def poll(self) -> int | None:
            return None  # still running

    captured: dict[str, Any] = {}

    def fake_popen(*args: Any, **kwargs: Any) -> _FakeProc:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeProc()

    import subprocess as sp
    monkeypatch.setattr(sp, "Popen", fake_popen)

    out = rs._ensure_rt_engine_running_locked(
        poll_interval=30, project_root=tmp_path,
    )
    assert out is True
    assert (tmp_path / "rt.pid").read_text() == "9999"
    assert "--interval" in captured["args"][0]
    assert "30" in captured["args"][0]


def test_ensure_rt_engine_running_locked_subprocess_exits_immediately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(rs, "_RT_ENGINE_LOG_FILE", tmp_path / "rt.log")
    monkeypatch.setattr(rs, "_RT_ENGINE_PID_FILE", tmp_path / "rt.pid")
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: None)
    monkeypatch.setattr(rs.time, "sleep", lambda *_a, **_k: None)

    class _FakeProc:
        pid = 1
        returncode = 2

        def poll(self) -> int:
            return 2  # exited immediately

    import subprocess as sp
    monkeypatch.setattr(sp, "Popen", lambda *a, **k: _FakeProc())

    out = rs._ensure_rt_engine_running_locked(
        poll_interval=10, project_root=tmp_path,
    )
    assert out is False
    payload = json.loads((tmp_path / "status.json").read_text())
    assert payload["running"] is False
    assert "exited immediately" in payload["error"]


def test_ensure_rt_engine_running_locked_handles_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(rs, "_RT_ENGINE_LOG_FILE", tmp_path / "rt.log")
    monkeypatch.setattr(rs, "_RT_ENGINE_PID_FILE", tmp_path / "rt.pid")
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: None)

    import subprocess as sp

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("Popen failed")

    monkeypatch.setattr(sp, "Popen", boom)
    out = rs._ensure_rt_engine_running_locked(
        poll_interval=10, project_root=tmp_path,
    )
    assert out is False


# ---------------------------------------------------------------------------
# ensure_rt_engine_running — wrapper (lock + delegation)
# ---------------------------------------------------------------------------


def test_ensure_rt_engine_running_returns_true_when_pid_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(rs, "_RT_ENGINE_LOG_FILE", tmp_path / "rt.log")
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: 12345)
    assert rs.ensure_rt_engine_running(poll_interval=20) is True


def test_ensure_rt_engine_running_uses_lock_and_delegates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_LOCK_FILE", tmp_path / "rt.lock")
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(rs, "_RT_ENGINE_LOG_FILE", tmp_path / "rt.log")
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: None)
    called: list[Any] = []

    def fake_locked(*, poll_interval: int, project_root: Path) -> bool:
        called.append((poll_interval, project_root))
        return True

    monkeypatch.setattr(rs, "_ensure_rt_engine_running_locked", fake_locked)
    assert rs.ensure_rt_engine_running(poll_interval=15, project_root=tmp_path) is True
    assert called == [(15, tmp_path)]
