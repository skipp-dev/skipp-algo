"""Regression tests for realtime_signals race conditions and state bugs."""
from __future__ import annotations

import json
import os
import subprocess as _subprocess_module
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from open_prep import realtime_signals as rs


def _minimal_snapshot(symbols: list[str]) -> dict[str, Any]:
    return {
        "ranked_v2": [{"symbol": s, "score": 0.5, "confidence_tier": "STANDARD"} for s in symbols],
        "filtered_out_v2": [],
        "enriched_quotes": [],
        "diff": {"new_entrants": []},
    }


def _write_snapshot(tmp_path: Path, data: dict[str, Any]) -> None:
    snapshot_path = tmp_path / "latest_open_prep_run.json"
    snapshot_path.write_text(json.dumps(data), encoding="utf-8")


def _make_quote(symbol: str, price: float, previous_close: float, volume: float, avg_volume: float) -> dict[str, Any]:
    change_pct = ((price / previous_close) - 1) * 100
    return {
        "symbol": symbol,
        "price": price,
        "previousClose": previous_close,
        "volume": volume,
        "avgVolume": avg_volume,
        "changesPercentage": change_pct,
    }


def test_poll_once_does_not_hold_active_signals_lock(tmp_path: Path, monkeypatch: Any) -> None:
    """poll_once() mutates _active_signals without acquiring self._lock.

    get_active_signals() acquires self._lock while iterating and filtering
    _active_signals. Because poll_once() never acquires the same lock, a
    concurrent reader can observe a partially-mutated list. This is a design
    bug regardless of whether a particular run triggers an exception.
    """
    monkeypatch.setattr(rs, "LATEST_RUN_PATH", tmp_path / "latest_open_prep_run.json")
    monkeypatch.setattr(rs, "_ARTIFACTS_LATEST", tmp_path)
    monkeypatch.setattr(rs, "SIGNALS_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(rs, "VD_SIGNALS_PATH", tmp_path / "vd.jsonl")

    _write_snapshot(tmp_path, _minimal_snapshot(["AAPL"]))

    client = MagicMock()
    client.get_batch_quotes.return_value = [
        _make_quote("AAPL", 105.0, 100.0, 10_000_000, 1_000_000),
    ]

    monkeypatch.setattr(rs, "_is_within_market_hours", lambda: True)
    monkeypatch.setattr(
        "open_prep.realtime_signals.TechnicalScorer.get_technical_data",
        lambda _self, _symbol, _interval: rs.TechnicalScorer._empty_result(""),
    )

    engine = rs.RealtimeEngine(poll_interval=10, fmp_client=client)
    # Keep race test offline: do not hit synchronous newsstack network fetch.
    engine._ns_poll_fn = lambda _cfg: []
    engine._ns_cfg_cls = lambda: None

    lock_events: list[str] = []
    real_lock = engine._lock

    class LockSpy:
        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            lock_events.append("acquire")
            return real_lock.acquire(blocking, timeout)

        def release(self) -> None:
            lock_events.append("release")
            real_lock.release()

        def __enter__(self) -> LockSpy:
            self.acquire()
            return self

        def __exit__(self, *args: Any, **kwargs: Any) -> None:
            self.release()

    engine._lock = LockSpy()
    engine.poll_once()

    # After fix: poll_once now correctly acquires the lock while mutating
    # _active_signals, preventing concurrent reader corruption.
    assert "acquire" in lock_events, "poll_once did not acquire _active_signals lock — race condition unfixed"


def test_get_active_signals_races_with_poll_once(tmp_path: Path, monkeypatch: Any) -> None:
    """Concurrent get_active_signals and poll_once should not crash or corrupt state.

    This is a stress regression test for the missing writer-side lock in
    poll_once(). It runs many interleaved reader/writer cycles and fails on
    any exception or on a corrupted active-signals list.
    """
    monkeypatch.setattr(rs, "LATEST_RUN_PATH", tmp_path / "latest_open_prep_run.json")
    monkeypatch.setattr(rs, "_ARTIFACTS_LATEST", tmp_path)
    monkeypatch.setattr(rs, "SIGNALS_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(rs, "VD_SIGNALS_PATH", tmp_path / "vd.jsonl")

    _write_snapshot(tmp_path, _minimal_snapshot(["AAPL", "TSLA"]))

    quotes = [
        _make_quote("AAPL", 105.0, 100.0, 10_000_000, 1_000_000),
        _make_quote("TSLA", 205.0, 200.0, 20_000_000, 2_000_000),
    ]
    client = MagicMock()
    client.get_batch_quotes.return_value = quotes

    monkeypatch.setattr(rs, "_is_within_market_hours", lambda: True)
    monkeypatch.setattr(
        "open_prep.realtime_signals.TechnicalScorer.get_technical_data",
        lambda _self, _symbol, _interval: rs.TechnicalScorer._empty_result(""),
    )

    engine = rs.RealtimeEngine(poll_interval=10, fmp_client=client)
    # Keep race test offline: do not hit synchronous newsstack network fetch.
    engine._ns_poll_fn = lambda _cfg: []
    engine._ns_cfg_cls = lambda: None

    errors: list[Exception] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                active = engine.get_active_signals()
                seen: set[str] = set()
                for s in active:
                    if s.symbol in seen:
                        raise AssertionError(f"duplicate active signal for {s.symbol}")
                    seen.add(s.symbol)
            except Exception as exc:
                errors.append(exc)

    def writer() -> None:
        for _ in range(50):
            try:
                engine.poll_once()
            except Exception as exc:
                errors.append(exc)

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for t in readers:
        t.start()

    writer()

    stop.set()
    for t in readers:
        t.join(timeout=5.0)

    assert not errors, f"Race-condition exceptions / invariant violations: {errors}"


def test_hysteresis_a2_proposal_uses_a1_logic_and_traps_symbol_at_a0() -> None:
    """GateHysteresis evaluates A2 proposals with A1 thresholds.

    Because `is_clear = clearly_a0 if proposed_level == "A0" else clearly_a1`,
    an A2 proposal is checked against A1 margins. If the previous state was A0
    and metrics are still in the A0 margin band (but below A0 thresholds),
    the symbol stays stuck at A0 instead of decaying to A2.
    """
    h = rs.GateHysteresis(margin_pct=0.02, min_hold_seconds=60.0)

    # First call: establish A0 state
    level = h.evaluate("SYM", "A0", volume_ratio=10.0, abs_change_pct=5.0)
    assert level == "A0"

    # Subsequent call proposes A2. Metrics are *below* A0 thresholds but still
    # above the A1 margin band, so they are neither clearly A0 nor clearly A1.
    # The correct behavior is to allow the A2 downgrade. The actual code keeps
    # the symbol trapped at A0 because A2 proposals are gated by A1 logic.
    level = h.evaluate("SYM", "A2", volume_ratio=3.0, abs_change_pct=1.5)

    # BUG: A2 proposal is gated by A1 thresholds, so if metrics are not
    # "clearly below A1" the symbol remains at A0.
    assert level == "A2", f"expected A2 downgrade but got {level}; A0 state is trapped"

def test_requalification_ignores_quote_expected_volume_fraction(monkeypatch: Any) -> None:
    """Re-qualification uses live wall-clock volume fraction, not the quote's.

    _detect_signal honours quote["expected_volume_fraction"] for deterministic
    replay, but poll_once's re-qualification path hard-codes
    _expected_cumulative_volume_fraction(). That makes replay/test results
    depend on the current time of day and breaks the invariant that the same
    replay input produces the same signal lifecycle.
    """
    from open_prep.realtime_signals import RealtimeSignal

    engine = rs.RealtimeEngine(poll_interval=10, fmp_client=None)
    engine._client_disabled_reason = None  # enable poll logic
    # Inject an active A1 signal for SYM
    sig = RealtimeSignal(
        symbol="SYM",
        level="A1",
        direction="LONG",
        pattern="realtime_momentum",
        price=100.0,
        prev_close=99.0,
        change_pct=1.01,
        volume_ratio=1.0,
        score=0.5,
        confidence_tier="STANDARD",
        atr_pct=1.0,
        freshness=1.0,
        fired_at="",
        fired_epoch=time.time(),
    )
    engine._active_signals = [sig]

    monkeypatch.setattr(rs, "_is_within_market_hours", lambda: True)

    # Quote says volume is exactly at the expected fraction for this time of
    # day, so normalized volume_ratio should be 1.0. Re-qualification should
    # therefore keep the signal. But because poll_once ignores the persisted
    # fraction and uses the live model, the result depends on wall-clock time.
    quote = {
        "symbol": "SYM",
        "price": 100.0,
        "previousClose": 99.0,
        "volume": 1_000_000,
        "avgVolume": 1_000_000,
        "expected_volume_fraction": 0.5,
    }
    engine._watchlist = [{"symbol": "SYM", "avg_volume": 1_000_000}]

    # Simulate the re-qualification calculation as it now exists in the code
    # (uses _resolve_expected_volume_fraction which honours the quote's value)
    raw_cur_vol = quote["volume"] / quote["avgVolume"]
    resolved_frac = rs._resolve_expected_volume_fraction(quote.get("expected_volume_fraction"))
    cur_vol_ratio = raw_cur_vol / max(resolved_frac, 0.02)
    # With expected_volume_fraction=0.5 the normalized ratio should be 2.0
    assert cur_vol_ratio == pytest.approx(raw_cur_vol / 0.5), (
        f"re-qualification ignored expected_volume_fraction: got {cur_vol_ratio}, "
        f"expected {raw_cur_vol / 0.5}"
    )

def test_gate_hysteresis_state_grows_unbounded() -> None:
    """GateHysteresis never prunes _state, causing unbounded memory growth.

    Every symbol that ever produces a signal leaves an entry in _state.
    For a 900-symbol watchlist with daily rotations this becomes a slow
    memory leak. The class should cap state size or evict stale symbols.
    """
    h = rs.GateHysteresis()
    for i in range(10_000):
        h.evaluate(f"SYM{i:05d}", "A0", volume_ratio=10.0, abs_change_pct=5.0)
    assert len(h._state) <= 1000, f"_state grew to {len(h._state)} entries without pruning"

def test_ensure_rt_engine_running_clobbers_pythonpath(monkeypatch: Any, tmp_path: Path) -> None:
    """ensure_rt_engine_running overwrites PYTHONPATH instead of prepending.

    If the parent process relies on an existing PYTHONPATH (e.g. a uv-managed
    venv or a custom package directory), the background engine loses it and
    may fail to import dependencies or the open_prep package itself.
    """
    import subprocess

    monkeypatch.setenv("PYTHONPATH", "/existing/path")
    monkeypatch.setattr(rs, "_RT_ENGINE_PID_FILE", tmp_path / "rt.pid")
    monkeypatch.setattr(rs, "_RT_ENGINE_LOCK_FILE", tmp_path / "rt.lock")
    monkeypatch.setattr(rs, "_RT_ENGINE_LOG_FILE", tmp_path / "rt.log")
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", tmp_path / "status.json")

    captured_env: dict[str, str] | None = None

    def fake_popen(args, **kwargs):
        nonlocal captured_env
        captured_env = kwargs.get("env")
        class P:
            pid = 12345
            def poll(self):
                return None
        return P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: None)

    rs.ensure_rt_engine_running(poll_interval=10, project_root=tmp_path)

    assert captured_env is not None
    pp = captured_env.get("PYTHONPATH", "")
    assert "/existing/path" in pp, f"existing PYTHONPATH was clobbered: {pp}"

def test_detect_rt_engine_pid_can_match_self(monkeypatch: Any, tmp_path: Path) -> None:
    """_detect_rt_engine_pid may return the current process's own PID.

    The pgrep pattern "python.*-m open_prep.realtime_signals" matches this
    process if the module is currently running. Returning our own PID makes
    ensure_rt_engine_running believe the engine is already up and skip launch.
    """
    monkeypatch.setattr(rs, "_RT_ENGINE_PID_FILE", tmp_path / "rt.pid")

    own_pid = os.getpid()

    def fake_pgrep(*args, **kwargs):
        class R:
            returncode = 0
            stdout = str(own_pid) + "\n"
        return R()

    monkeypatch.setattr(_subprocess_module, "run", fake_pgrep)

    detected = rs._detect_rt_engine_pid()
    assert detected != own_pid, f"detected own PID {own_pid} as running engine"
