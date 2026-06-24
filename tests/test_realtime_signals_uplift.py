"""First-wave coverage uplift for `open_prep.realtime_signals`.

Existing tests already cover the big spawn-locking, telemetry-server-fallback,
and stale-cache scoring branches. This file adds focused unit tests for the
pure helpers and the small state machines, which together represent the
densest easy-coverage wins in the module:

- atomic JSON I/O (`_write_json_atomically`, `_read_json_file`)
- RT-engine status / telemetry status writers + readers
- market-hours / cumulative-volume-fraction calendar helpers
- `_quote_hash`, `_format_age_hms`, `_noop_fetch`
- `QuoteDeltaTracker` full update cycle
- `DynamicCooldown` regime/oscillation/news/cooldown lifecycle
- `GateHysteresis` first-call / same-level / clear-vs-margin / hold paths
- `VolumeRegimeDetector.adjusted_thresholds`
- `ScoreTelemetry.record` + `snapshot`

Heavier surfaces (RealtimeEngine.poll_once, main(), `_detect_rt_engine_pid`
subprocess paths) are left for a follow-up pass.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from open_prep import realtime_signals as rs
from open_prep.realtime_signals import (
    DynamicCooldown,
    GateHysteresis,
    QuoteDeltaTracker,
    RealtimeSignal,
    ScoreTelemetry,
    VolumeRegimeDetector,
    _expected_cumulative_volume_fraction,
    _format_age_hms,
    _is_within_market_hours,
    _noop_fetch,
    _quote_hash,
    _read_json_file,
    _update_rt_engine_status,
    _update_telemetry_status,
    _write_json_atomically,
    get_rt_engine_status,
    get_rt_engine_telemetry_status,
)

# ---------------------------------------------------------------------------
# Atomic JSON I/O
# ---------------------------------------------------------------------------


def test_write_json_atomically_creates_parents_and_writes(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "out.json"
    payload = {"hello": "world", "n": 42}
    _write_json_atomically(target, payload)
    assert target.exists()
    assert json.loads(target.read_text()) == payload
    # No leftover tmp files in the parent dir.
    leftover = [p for p in target.parent.iterdir() if p.name != target.name]
    assert leftover == []


def test_write_json_atomically_cleans_tmp_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.json"

    def boom(_src: str, _dst: str) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(rs.os, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        _write_json_atomically(target, {"x": 1})
    # The mkstemp tmp file should have been cleaned up.
    leftovers = list(target.parent.iterdir())
    assert leftovers == []


def test_read_json_file_returns_none_when_missing(tmp_path: Path) -> None:
    assert _read_json_file(tmp_path / "missing.json") is None


def test_read_json_file_returns_parsed_payload(tmp_path: Path) -> None:
    target = tmp_path / "ok.json"
    target.write_text(json.dumps({"k": 1}))
    assert _read_json_file(target) == {"k": 1}


def test_read_json_file_returns_none_on_corrupt_payload(tmp_path: Path) -> None:
    target = tmp_path / "bad.json"
    target.write_text("not-json{{{")
    assert _read_json_file(target) is None


# ---------------------------------------------------------------------------
# RT-engine status + telemetry status
# ---------------------------------------------------------------------------


@pytest.fixture
def status_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect all module-level RT-engine state paths under tmp_path."""

    paths = {
        "status": tmp_path / "rt_engine_status.json",
        "telemetry": tmp_path / "rt_engine_telemetry.json",
        "pid": tmp_path / "rt_engine.pid",
    }
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", paths["status"])
    monkeypatch.setattr(rs, "_RT_ENGINE_TELEMETRY_FILE", paths["telemetry"])
    monkeypatch.setattr(rs, "_RT_ENGINE_PID_FILE", paths["pid"])
    return paths


def test_update_rt_engine_status_writes_running_and_pid(status_paths: dict[str, Path]) -> None:
    _update_rt_engine_status(running=True, pid=4242)
    payload = json.loads(status_paths["status"].read_text())
    assert payload["running"] is True
    assert payload["pid"] == 4242
    assert payload["error"] == ""
    assert "updated_at" in payload


def test_update_rt_engine_status_records_error(status_paths: dict[str, Path]) -> None:
    _update_rt_engine_status(running=False, pid=None, error="lock held by other")
    payload = json.loads(status_paths["status"].read_text())
    assert payload["running"] is False
    assert payload["pid"] is None
    assert payload["error"] == "lock held by other"


def test_get_rt_engine_status_falls_back_when_no_file(
    status_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # No status file written, pid detector returns None too.
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: None)
    out = get_rt_engine_status()
    assert isinstance(out, dict)
    assert out.get("running") is False or out.get("pid") in (None, 0)


def test_get_rt_engine_status_returns_status_when_file_present(
    status_paths: dict[str, Path],
) -> None:
    _update_rt_engine_status(running=True, pid=99)
    out = get_rt_engine_status()
    assert out["running"] is True
    assert out["pid"] == 99


def test_update_telemetry_status_records_active_port(status_paths: dict[str, Path]) -> None:
    _update_telemetry_status(enabled=True, requested_port=8099, active_port=8099)
    payload = json.loads(status_paths["telemetry"].read_text())
    assert payload["enabled"] is True
    assert payload["requested_port"] == 8099
    assert payload["active_port"] == 8099
    assert payload["url"] == "http://0.0.0.0:8099"
    assert payload["error"] == ""


def test_update_telemetry_status_records_fallback_with_error(
    status_paths: dict[str, Path],
) -> None:
    _update_telemetry_status(
        enabled=True,
        requested_port=8099,
        active_port=8123,
        error="Requested port 8099 unavailable; using fallback 8123.",
    )
    payload = json.loads(status_paths["telemetry"].read_text())
    assert payload["active_port"] == 8123
    assert payload["url"] == "http://0.0.0.0:8123"
    assert "fallback" in payload["error"]


def test_update_telemetry_status_uses_bind_host_from_env(
    status_paths: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEMETRY_BIND_HOST", "0.0.0.0")
    _update_telemetry_status(enabled=True, requested_port=8099, active_port=8099)
    payload = json.loads(status_paths["telemetry"].read_text())
    assert payload["url"] == "http://0.0.0.0:8099"


def test_update_telemetry_status_disabled_omits_url(status_paths: dict[str, Path]) -> None:
    _update_telemetry_status(enabled=False, requested_port=8099, active_port=None)
    payload = json.loads(status_paths["telemetry"].read_text())
    assert payload["enabled"] is False
    assert payload["active_port"] is None
    assert payload["url"] == ""


def test_get_telemetry_status_returns_empty_dict_when_missing(
    status_paths: dict[str, Path],
) -> None:
    assert get_rt_engine_telemetry_status() == {}


def test_get_telemetry_status_returns_payload_when_present(
    status_paths: dict[str, Path],
) -> None:
    _update_telemetry_status(enabled=True, requested_port=8099, active_port=8099)
    out = get_rt_engine_telemetry_status()
    assert out["enabled"] is True
    assert out["active_port"] == 8099


# ---------------------------------------------------------------------------
# Market-hours / cumulative-volume helpers
# ---------------------------------------------------------------------------


def _patch_now_to(monkeypatch: pytest.MonkeyPatch, dt: datetime) -> None:
    """Patch `datetime.now(UTC)` inside the module for time-of-day tests."""

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            base = dt if tz is None else dt.astimezone(tz)
            return base

    monkeypatch.setattr(rs, "datetime", _FrozenDateTime)


def test_is_within_market_hours_weekend_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Saturday 2026-04-25 14:00 UTC — outside Mon-Fri.
    _patch_now_to(monkeypatch, datetime(2026, 4, 25, 14, 0, tzinfo=UTC))
    assert _is_within_market_hours() is False


def test_is_within_market_hours_weekday_in_window_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Wednesday 2026-04-22 16:30 UTC = 12:30 ET (in 04:00–20:00 window).
    _patch_now_to(monkeypatch, datetime(2026, 4, 22, 16, 30, tzinfo=UTC))
    assert _is_within_market_hours() is True


def test_is_within_market_hours_pre_dawn_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Wednesday 2026-04-22 06:00 UTC = 02:00 ET — before 04:00.
    _patch_now_to(monkeypatch, datetime(2026, 4, 22, 6, 0, tzinfo=UTC))
    assert _is_within_market_hours() is False


def test_expected_cumulative_volume_fraction_weekend_returns_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_now_to(monkeypatch, datetime(2026, 4, 25, 18, 0, tzinfo=UTC))
    assert _expected_cumulative_volume_fraction() == 1.0


def test_expected_cumulative_volume_fraction_pre_open_returns_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Wed 2026-04-22 12:00 UTC = 08:00 ET (before 09:30).
    _patch_now_to(monkeypatch, datetime(2026, 4, 22, 12, 0, tzinfo=UTC))
    assert _expected_cumulative_volume_fraction() == pytest.approx(0.02)


def test_expected_cumulative_volume_fraction_open_30min_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Wed 2026-04-22 13:45 UTC = 09:45 ET (15 min after open) → linear 0.02→0.25 at 15/30 = 0.135
    _patch_now_to(monkeypatch, datetime(2026, 4, 22, 13, 45, tzinfo=UTC))
    out = _expected_cumulative_volume_fraction()
    assert 0.10 < out < 0.20


def test_expected_cumulative_volume_fraction_after_close_returns_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Wed 2026-04-22 22:00 UTC = 18:00 ET (after 16:00 close, > 390 min from open).
    _patch_now_to(monkeypatch, datetime(2026, 4, 22, 22, 0, tzinfo=UTC))
    assert _expected_cumulative_volume_fraction() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Misc small helpers
# ---------------------------------------------------------------------------


def test_noop_fetch_returns_none() -> None:
    assert _noop_fetch("AAPL") is None
    assert _noop_fetch("AAPL", "1H") is None


def test_quote_hash_stable_for_identical_payload() -> None:
    q1 = {"price": 100.0, "volume": 1000, "changesPercentage": 1.5, "lastPrice": 100.0}
    q2 = dict(q1)
    h1 = _quote_hash(q1)
    h2 = _quote_hash(q2)
    assert h1 == h2
    assert isinstance(h1, str) and len(h1) == 12


def test_quote_hash_changes_when_price_changes() -> None:
    base = {"price": 100.0, "volume": 1000, "changesPercentage": 1.5}
    other = {"price": 101.0, "volume": 1000, "changesPercentage": 1.5}
    assert _quote_hash(base) != _quote_hash(other)


def test_quote_hash_handles_missing_fields() -> None:
    # Should not raise on minimal dicts.
    assert isinstance(_quote_hash({}), str)
    assert isinstance(_quote_hash({"price": None}), str)


@pytest.mark.parametrize(
    ("seconds", "expected_substring"),
    [
        (0, "00:00:00"),
        (5, "00:00:05"),
        (65, "00:01:05"),
        (3661, "01:01:01"),
        (90061, "25:01:01"),  # > 24h: still HH grows past 24
    ],
)
def test_format_age_hms_matrix(seconds: int, expected_substring: str) -> None:
    assert _format_age_hms(float(seconds)) == expected_substring


def test_format_age_hms_handles_negative_or_nan_gracefully() -> None:
    # Implementation may clamp or just format; assert no exception.
    out = _format_age_hms(-1.0)
    assert isinstance(out, str)


# ---------------------------------------------------------------------------
# QuoteDeltaTracker
# ---------------------------------------------------------------------------


def test_quote_delta_tracker_first_update_is_baseline() -> None:
    tracker = QuoteDeltaTracker()
    delta = tracker.update("AAPL", price=100.0, volume=1000)
    assert delta["d_price"] == 0.0
    assert delta["d_price_pct"] == 0.0
    assert delta["d_volume"] == 0
    assert delta["tick"] == "="
    assert delta["streak"] == 0


def test_quote_delta_tracker_up_tick_streak_grows() -> None:
    tracker = QuoteDeltaTracker()
    tracker.update("AAPL", price=100.0, volume=1000)
    delta_up_1 = tracker.update("AAPL", price=101.0, volume=1500)
    assert delta_up_1["d_price"] == pytest.approx(1.0)
    assert delta_up_1["d_volume"] == 500
    assert delta_up_1["tick"] == "▲"
    assert delta_up_1["streak"] == 1
    delta_up_2 = tracker.update("AAPL", price=102.0, volume=2000)
    assert delta_up_2["tick"] == "▲"
    assert delta_up_2["streak"] == 2


def test_quote_delta_tracker_down_tick_resets_then_negative_streak() -> None:
    tracker = QuoteDeltaTracker()
    tracker.update("AAPL", price=100.0, volume=1000)
    tracker.update("AAPL", price=101.0, volume=1500)  # streak=1
    delta_down = tracker.update("AAPL", price=99.0, volume=2000)
    assert delta_down["tick"] == "▼"
    assert delta_down["streak"] == -1


def test_quote_delta_tracker_flat_resets_streak_to_zero() -> None:
    tracker = QuoteDeltaTracker()
    tracker.update("AAPL", price=100.0, volume=1000)
    tracker.update("AAPL", price=101.0, volume=1500)  # streak=1
    flat = tracker.update("AAPL", price=101.0, volume=1500)
    assert flat["tick"] == "="
    assert flat["streak"] == 0


def test_quote_delta_tracker_isolates_symbols() -> None:
    tracker = QuoteDeltaTracker()
    tracker.update("AAPL", price=100.0, volume=1000)
    tracker.update("MSFT", price=300.0, volume=500)
    out = tracker.update("AAPL", price=110.0, volume=1500)
    assert out["d_price"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# DynamicCooldown
# ---------------------------------------------------------------------------


def test_dynamic_cooldown_compute_default_uses_base() -> None:
    cd = DynamicCooldown(base_seconds=120.0, min_seconds=5.0, max_seconds=600.0)
    out = cd.compute("AAPL", volume_regime="NORMAL", has_news_catalyst=False)
    assert out == pytest.approx(120.0)


def test_dynamic_cooldown_thin_regime_increases_cooldown() -> None:
    cd = DynamicCooldown(base_seconds=120.0, min_seconds=5.0, max_seconds=600.0)
    out = cd.compute("AAPL", volume_regime="THIN", has_news_catalyst=False)
    assert out > 120.0


def test_dynamic_cooldown_high_regime_decreases_cooldown() -> None:
    cd = DynamicCooldown(base_seconds=120.0, min_seconds=5.0, max_seconds=600.0)
    out = cd.compute("AAPL", volume_regime="HIGH", has_news_catalyst=False)
    assert out < 120.0


def test_dynamic_cooldown_news_factor_shrinks_cooldown() -> None:
    cd = DynamicCooldown(base_seconds=120.0, min_seconds=5.0, max_seconds=600.0)
    out_no_news = cd.compute("AAPL", volume_regime="NORMAL", has_news_catalyst=False)
    out_news = cd.compute("AAPL", volume_regime="NORMAL", has_news_catalyst=True)
    assert out_news < out_no_news


def test_dynamic_cooldown_clamps_to_min_and_max() -> None:
    cd = DynamicCooldown(
        base_seconds=10000.0, min_seconds=5.0, max_seconds=30.0
    )
    capped = cd.compute("AAPL", volume_regime="THIN", has_news_catalyst=False)
    assert capped == pytest.approx(30.0)

    cd_low = DynamicCooldown(base_seconds=1.0, min_seconds=15.0, max_seconds=600.0)
    floored = cd_low.compute("AAPL", volume_regime="HIGH", has_news_catalyst=True)
    assert floored == pytest.approx(15.0)


def test_dynamic_cooldown_oscillation_factor_grows_with_flips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cd = DynamicCooldown(
        base_seconds=120.0,
        min_seconds=5.0,
        max_seconds=600.0,
        oscillation_window=6,
        oscillation_threshold=3,
    )
    fixed = 1_000_000.0
    monkeypatch.setattr(rs.time, "monotonic", lambda: fixed)
    # Record alternating directions to trigger >= threshold flips.
    for direction in ("UP", "DOWN", "UP", "DOWN", "UP", "DOWN"):
        cd.record_transition("AAPL", direction)
    out = cd.compute("AAPL", volume_regime="NORMAL", has_news_catalyst=False)
    # With 5 flips and threshold=3, multiplier > 1 → cooldown above base.
    assert out > 120.0


def test_dynamic_cooldown_check_active_then_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cd = DynamicCooldown(base_seconds=10.0, min_seconds=1.0, max_seconds=60.0)
    fixed = 1_000_000.0
    monkeypatch.setattr(rs.time, "monotonic", lambda: fixed)
    cd._last_a0["AAPL"] = fixed  # simulate just-fired A0
    active, remaining = cd.check_cooldown("AAPL", volume_regime="NORMAL", has_news_catalyst=False)
    assert active is True
    assert remaining > 0
    # Advance time past cooldown.
    monkeypatch.setattr(rs.time, "monotonic", lambda: fixed + 60.0)
    active2, remaining2 = cd.check_cooldown("AAPL", volume_regime="NORMAL", has_news_catalyst=False)
    assert active2 is False
    assert remaining2 == 0.0


def test_dynamic_cooldown_is_cooling_alias_matches_check() -> None:
    cd = DynamicCooldown(base_seconds=10.0, min_seconds=1.0, max_seconds=60.0)
    # No prior A0 → not cooling.
    assert cd.is_cooling("AAPL") is False


# ---------------------------------------------------------------------------
# GateHysteresis
# ---------------------------------------------------------------------------


def test_gate_hysteresis_first_call_accepts_proposed_level() -> None:
    gate = GateHysteresis(margin_pct=0.02, min_hold_seconds=30.0)
    out = gate.evaluate("AAPL", proposed_level="A1", volume_ratio=1.5, abs_change_pct=0.5)
    assert out == "A1"


def test_gate_hysteresis_same_level_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = GateHysteresis(margin_pct=0.02, min_hold_seconds=30.0)
    fixed = 1_000_000.0
    monkeypatch.setattr(rs.time, "monotonic", lambda: fixed)
    gate.record("AAPL", "A1")
    out = gate.evaluate("AAPL", proposed_level="A1", volume_ratio=1.5, abs_change_pct=0.5)
    assert out == "A1"


def test_gate_hysteresis_clear_a0_signal_transitions_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = GateHysteresis(margin_pct=0.02, min_hold_seconds=300.0)
    fixed = 1_000_000.0
    monkeypatch.setattr(rs.time, "monotonic", lambda: fixed)
    gate.record("AAPL", "A1")
    # Both metrics clearly above A0 thresholds × (1+margin) → immediate jump.
    out = gate.evaluate(
        "AAPL",
        proposed_level="A0",
        volume_ratio=10.0,  # >> A0 threshold * 1.02
        abs_change_pct=5.0,  # >> A0 threshold * 1.02
    )
    assert out == "A0"


def test_gate_hysteresis_holds_during_min_hold_when_marginal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # margin=0.10: a0_vol_margin = 3.0*0.9=2.7, a0_chg_margin = 1.5*0.9=1.35
    # vol=2.8, chg=1.45 → both > margin (not clearly_a1) but < 3.0*1.1=3.3 / 1.5*1.1=1.65 (not clearly_a0)
    # → within band, must hold prior level.
    gate = GateHysteresis(margin_pct=0.10, min_hold_seconds=10_000.0)
    fixed = 1_000_000.0
    monkeypatch.setattr(rs.time, "monotonic", lambda: fixed)
    gate.record("AAPL", "A0")
    out = gate.evaluate(
        "AAPL",
        proposed_level="A1",
        volume_ratio=2.8,
        abs_change_pct=1.45,
    )
    assert out == "A0"


def test_gate_hysteresis_allows_transition_after_min_hold_elapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = GateHysteresis(margin_pct=0.10, min_hold_seconds=10.0)
    base = 1_000_000.0
    monkeypatch.setattr(rs.time, "monotonic", lambda: base)
    gate.record("AAPL", "A0")
    # Advance past min_hold so even marginal metrics allow the transition.
    monkeypatch.setattr(rs.time, "monotonic", lambda: base + 30.0)
    out = gate.evaluate(
        "AAPL",
        proposed_level="A1",
        volume_ratio=2.8,
        abs_change_pct=1.45,
    )
    assert out == "A1"


# ---------------------------------------------------------------------------
# VolumeRegimeDetector.adjusted_thresholds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("regime", "expected_vol_mult", "expected_chg_mult"),
    [
        ("HOLIDAY_SUSPECT", 999.0, 999.0),
        ("LOW_VOLUME", 0.80, 0.80),
        ("NORMAL", 1.0, 1.0),
        ("anything_else", 1.0, 1.0),  # default branch
    ],
)
def test_volume_regime_adjusted_thresholds(
    regime: str, expected_vol_mult: float, expected_chg_mult: float
) -> None:
    detector = VolumeRegimeDetector()
    detector.regime = regime
    out = detector.adjusted_thresholds()
    assert out["vol_mult"] == expected_vol_mult
    assert out["chg_mult"] == expected_chg_mult


# ---------------------------------------------------------------------------
# ScoreTelemetry
# ---------------------------------------------------------------------------


def test_score_telemetry_initial_snapshot_is_empty() -> None:
    tel = ScoreTelemetry(maxlen=100)
    snap = tel.snapshot()
    assert snap["poll_count"] == 0
    assert snap["score_diff"]["count"] == 0
    assert snap["a0_rate"] == 0.0


def test_score_telemetry_records_signals_and_computes_a0_rate() -> None:
    tel = ScoreTelemetry(maxlen=100)
    a0_signal = MagicMock(spec=RealtimeSignal)
    a0_signal.level = "A0"
    a1_signal = MagicMock(spec=RealtimeSignal)
    a1_signal.level = "A1"

    tel.record(signals=[a0_signal], score_diff=1.2, volume_ratio=4.5, change_pct=2.0)
    tel.record(signals=[a1_signal], score_diff=0.5, volume_ratio=1.5, change_pct=0.5)
    tel.record(signals=[], score_diff=0.1, volume_ratio=0.8, change_pct=0.1)

    snap = tel.snapshot()
    assert snap["poll_count"] == 3
    assert snap["score_diff"]["count"] == 3
    assert snap["score_diff"]["max"] == pytest.approx(1.2)
    assert snap["volume_ratio"]["max"] == pytest.approx(4.5)
    assert snap["change_pct"]["max"] == pytest.approx(2.0)
    assert snap["a0_rate"] == pytest.approx(1.0 / 3.0, rel=1e-3)


def test_score_telemetry_respects_maxlen() -> None:
    tel = ScoreTelemetry(maxlen=2)
    for i in range(5):
        tel.record(signals=[], score_diff=float(i), volume_ratio=1.0, change_pct=0.1)
    snap = tel.snapshot()
    # poll_count tracks total calls, but the deque is capped at maxlen=2.
    assert snap["poll_count"] == 5
    assert snap["score_diff"]["count"] <= 2
