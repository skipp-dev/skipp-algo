"""Coverage uplift for `open_prep.realtime_signals` (baseline 50%).

Bucket G — second-wave: focus on small pure helpers + `main()` smoke +
`_detect_rt_engine_pid` + market-hours / volume-fraction time branches.

Avoids touching the large `RealtimeEngine.poll_once` body — that needs a
proper FMP-mocking fixture and is best handled in a separate bucket.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from open_prep import realtime_signals as rs

# ---------------------------------------------------------------------------
# _quote_hash / _format_age_hms — pure helpers
# ---------------------------------------------------------------------------


def test_quote_hash_deterministic() -> None:
    q = {"price": 100.0, "lastPrice": 100.0, "volume": 1234, "changesPercentage": 1.5}
    assert rs._quote_hash(q) == rs._quote_hash(q)


def test_quote_hash_changes_with_price() -> None:
    q1 = {"price": 100.0, "lastPrice": 100.0, "volume": 1234, "changesPercentage": 1.5}
    q2 = {"price": 101.0, "lastPrice": 101.0, "volume": 1234, "changesPercentage": 1.5}
    assert rs._quote_hash(q1) != rs._quote_hash(q2)


def test_quote_hash_handles_missing_keys() -> None:
    assert isinstance(rs._quote_hash({}), str)
    assert len(rs._quote_hash({})) == 12


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00"),
        (-1, "00:00:00"),
        (59, "00:00:59"),
        (60, "00:01:00"),
        (3661, "01:01:01"),
        (3600 * 25, "25:00:00"),
    ],
)
def test_format_age_hms(seconds: float, expected: str) -> None:
    assert rs._format_age_hms(seconds) == expected


# ---------------------------------------------------------------------------
# _write_json_atomically / _read_json_file
# ---------------------------------------------------------------------------


def test_write_then_read_json_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "sub" / "out.json"
    rs._write_json_atomically(p, {"x": 1, "y": "z"})
    assert rs._read_json_file(p) == {"x": 1, "y": "z"}


def test_read_json_returns_none_when_missing(tmp_path: Path) -> None:
    assert rs._read_json_file(tmp_path / "missing.json") is None


def test_read_json_returns_none_when_invalid(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    assert rs._read_json_file(p) is None


def test_read_json_returns_none_when_not_dict(tmp_path: Path) -> None:
    p = tmp_path / "list.json"
    p.write_text(json.dumps([1, 2, 3]))
    assert rs._read_json_file(p) is None


# ---------------------------------------------------------------------------
# _update_rt_engine_status / _update_telemetry_status
# ---------------------------------------------------------------------------


def test_update_rt_engine_status_writes_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "rt_status.json"
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", target)
    monkeypatch.setattr(rs, "_RT_ENGINE_LOG_FILE", tmp_path / "rt.log")
    rs._update_rt_engine_status(running=True, pid=4242, error=None)
    payload = json.loads(target.read_text())
    assert payload["running"] is True
    assert payload["pid"] == 4242
    assert payload["error"] == ""


def test_update_rt_engine_status_handles_none_pid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "rt_status.json"
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", target)
    monkeypatch.setattr(rs, "_RT_ENGINE_LOG_FILE", tmp_path / "rt.log")
    rs._update_rt_engine_status(running=False, pid=None, error="boom")
    payload = json.loads(target.read_text())
    assert payload["pid"] is None
    assert payload["error"] == "boom"


def test_update_telemetry_status_writes_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "telemetry.json"
    monkeypatch.setattr(rs, "_RT_ENGINE_TELEMETRY_FILE", target)
    rs._update_telemetry_status(enabled=True, requested_port=8099, active_port=8099)
    payload = json.loads(target.read_text())
    assert payload["enabled"] is True
    assert payload["url"] == "http://127.0.0.1:8099"


def test_update_telemetry_status_no_active_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "telemetry.json"
    monkeypatch.setattr(rs, "_RT_ENGINE_TELEMETRY_FILE", target)
    rs._update_telemetry_status(
        enabled=False, requested_port=8099, active_port=None, error="port busy"
    )
    payload = json.loads(target.read_text())
    assert payload["enabled"] is False
    assert payload["active_port"] is None
    assert payload["url"] == ""
    assert payload["error"] == "port busy"


# ---------------------------------------------------------------------------
# _expected_cumulative_volume_fraction — time-of-day branches
# ---------------------------------------------------------------------------


class _FakeDateTime:
    """Module-level shim: only `now(tz)` is used inside the helpers."""

    _fixed: datetime

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return cls._fixed


def _patch_now_et(monkeypatch: pytest.MonkeyPatch, fixed: datetime) -> None:
    """Monkeypatch the module-bound `datetime` class so `.now(tz)` returns a fixed value.

    The helpers call `datetime.now(ZoneInfo("America/New_York"))`. By
    replacing the bound name `datetime` in the module with our shim, every
    such call returns `fixed` (already in ET).
    """
    cls = type("_DT", (_FakeDateTime,), {"_fixed": fixed})
    monkeypatch.setattr(rs, "datetime", cls)


def test_expected_cumulative_volume_fraction_weekend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saturday = datetime(2026, 4, 25, 12, 0)  # Saturday
    _patch_now_et(monkeypatch, saturday)
    assert rs._expected_cumulative_volume_fraction() == 1.0


def test_expected_cumulative_volume_fraction_premarket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Monday 08:00 ET — pre-market
    _patch_now_et(monkeypatch, datetime(2026, 4, 20, 8, 0))
    assert rs._expected_cumulative_volume_fraction() == 0.02


def test_expected_cumulative_volume_fraction_first_30min(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Monday 09:45 ET — 15 min into session → ~0.125
    _patch_now_et(monkeypatch, datetime(2026, 4, 20, 9, 45))
    out = rs._expected_cumulative_volume_fraction()
    assert 0.10 < out < 0.15


def test_expected_cumulative_volume_fraction_30_to_90min(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Monday 10:30 ET → 60 min in → 25 + 0.15*(30/60) = 0.325
    _patch_now_et(monkeypatch, datetime(2026, 4, 20, 10, 30))
    out = rs._expected_cumulative_volume_fraction()
    assert 0.30 < out < 0.35


def test_expected_cumulative_volume_fraction_midday(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Monday 13:00 ET → 210 min in → 0.4 + 0.6*(120/300) = 0.64
    _patch_now_et(monkeypatch, datetime(2026, 4, 20, 13, 0))
    out = rs._expected_cumulative_volume_fraction()
    assert 0.60 < out < 0.70


def test_expected_cumulative_volume_fraction_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Monday 16:30 ET — after close
    _patch_now_et(monkeypatch, datetime(2026, 4, 20, 16, 30))
    assert rs._expected_cumulative_volume_fraction() == 1.0


# ---------------------------------------------------------------------------
# _is_within_market_hours — weekday/hour branches
# ---------------------------------------------------------------------------


def test_is_within_market_hours_weekend(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_now_et(monkeypatch, datetime(2026, 4, 26, 12, 0))  # Sunday
    assert rs._is_within_market_hours() is False


def test_is_within_market_hours_pre_open_too_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_now_et(monkeypatch, datetime(2026, 4, 20, 3, 30))  # Monday 03:30
    assert rs._is_within_market_hours() is False


def test_is_within_market_hours_extended_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_now_et(monkeypatch, datetime(2026, 4, 20, 5, 0))  # Monday 05:00 ET
    assert rs._is_within_market_hours() is True


def test_is_within_market_hours_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_now_et(monkeypatch, datetime(2026, 4, 20, 21, 0))  # Monday 21:00
    assert rs._is_within_market_hours() is False


def test_is_within_market_hours_regular_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_now_et(monkeypatch, datetime(2026, 4, 20, 12, 0))  # Monday noon
    assert rs._is_within_market_hours() is True


# ---------------------------------------------------------------------------
# _detect_rt_engine_pid
# ---------------------------------------------------------------------------


def test_detect_rt_engine_pid_uses_pid_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pidfile = tmp_path / "rt.pid"
    pidfile.write_text(str(123456))
    monkeypatch.setattr(rs, "_RT_ENGINE_PID_FILE", pidfile)
    monkeypatch.setattr(rs.os, "kill", lambda pid, sig: None)
    assert rs._detect_rt_engine_pid() == 123456


def test_detect_rt_engine_pid_invalid_file_then_subprocess_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pidfile = tmp_path / "rt.pid"
    pidfile.write_text("not_an_int")
    monkeypatch.setattr(rs, "_RT_ENGINE_PID_FILE", pidfile)

    class _FakeProc:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(
        "subprocess.run", lambda *args, **kwargs: _FakeProc()
    )
    assert rs._detect_rt_engine_pid() is None
    # invalid pid file was unlinked
    assert not pidfile.exists()


def test_detect_rt_engine_pid_subprocess_failure_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_PID_FILE", tmp_path / "no.pid")

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("pgrep missing")

    monkeypatch.setattr("subprocess.run", boom)
    assert rs._detect_rt_engine_pid() is None


def test_detect_rt_engine_pid_subprocess_finds_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pidfile = tmp_path / "rt.pid"
    monkeypatch.setattr(rs, "_RT_ENGINE_PID_FILE", pidfile)

    class _FakeProc:
        returncode = 0
        stdout = "777\n888\n"

    killed: list[int] = []

    def fake_kill(pid: int, _sig: int) -> None:
        killed.append(pid)
        if pid == 777:
            raise OSError("not running")
        # 888 is "alive"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _FakeProc())
    monkeypatch.setattr(rs.os, "kill", fake_kill)

    assert rs._detect_rt_engine_pid() == 888
    assert pidfile.exists()
    assert pidfile.read_text() == "888"


# ---------------------------------------------------------------------------
# get_rt_engine_status / get_rt_engine_telemetry_status
# ---------------------------------------------------------------------------


def test_get_rt_engine_status_uses_status_file_when_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "status.json"
    target.write_text(json.dumps({"running": True, "pid": 1, "error": ""}))
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", target)
    out = rs.get_rt_engine_status()
    assert out["running"] is True
    assert out["pid"] == 1


def test_get_rt_engine_status_falls_back_to_pid_detection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_STATUS_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(rs, "_RT_ENGINE_LOG_FILE", tmp_path / "rt.log")
    monkeypatch.setattr(rs, "_detect_rt_engine_pid", lambda: 12345)
    out = rs.get_rt_engine_status()
    assert out["running"] is True
    assert out["pid"] == 12345


def test_get_rt_engine_telemetry_status_returns_dict_or_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rs, "_RT_ENGINE_TELEMETRY_FILE", tmp_path / "missing.json")
    assert rs.get_rt_engine_telemetry_status() == {}


# ---------------------------------------------------------------------------
# main() — argparse + early-exit smoke
# ---------------------------------------------------------------------------


class _FakeEngine:
    """Stand-in for `RealtimeEngine` that records construction args and
    exits the polling loop on the first poll via KeyboardInterrupt."""

    instances: ClassVar[list[_FakeEngine]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.poll_interval = kwargs.get("poll_interval", 1)
        self.poll_count = 0
        self.reload_count = 0
        self.last_poll_duration = 0.0
        self.telemetry: Any = object()
        self._async_newsstack: Any = None
        _FakeEngine.instances.append(self)

    def reload_watchlist(self) -> None:
        self.reload_count += 1

    def poll_once(self) -> None:
        self.poll_count += 1
        raise KeyboardInterrupt

    def get_active_signals(self) -> list[Any]:
        return []

    def start_async_newsstack(self, *, poll_interval: int) -> None:
        pass


def test_main_default_args_runs_one_poll_then_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeEngine.instances.clear()
    monkeypatch.setattr(rs, "RealtimeEngine", _FakeEngine)
    monkeypatch.setattr(rs, "_start_telemetry_server", lambda *a, **k: None)
    monkeypatch.setattr(rs.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr("sys.argv", ["realtime_signals"])

    rs.main()
    assert len(_FakeEngine.instances) == 1
    eng = _FakeEngine.instances[0]
    assert eng.kwargs["fast_mode"] is False
    assert eng.kwargs["ultra_mode"] is False
    assert eng.poll_count == 1


def test_main_ultra_flag_enables_fast_and_ultra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeEngine.instances.clear()
    monkeypatch.setattr(rs, "RealtimeEngine", _FakeEngine)
    monkeypatch.setattr(rs, "_start_telemetry_server", lambda *a, **k: None)
    monkeypatch.setattr(rs.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "realtime_signals",
            "--ultra",
            "--telemetry-port", "0",
            "--top-n", "10",
        ],
    )
    rs.main()
    eng = _FakeEngine.instances[-1]
    assert eng.kwargs["ultra_mode"] is True
    assert eng.kwargs["fast_mode"] is True
    assert eng.kwargs["top_n"] == 10


def test_main_fast_flag_starts_async_newsstack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeEngine.instances.clear()
    started: list[int] = []

    class _Engine(_FakeEngine):
        def start_async_newsstack(self, *, poll_interval: int) -> None:
            started.append(poll_interval)

    monkeypatch.setattr(rs, "RealtimeEngine", _Engine)
    monkeypatch.setattr(rs, "_start_telemetry_server", lambda *a, **k: None)
    monkeypatch.setattr(rs.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr("sys.argv", ["realtime_signals", "--fast", "--telemetry-port", "0"])
    rs.main()
    assert started == [60]
