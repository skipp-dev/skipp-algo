"""Tests for scripts/databento_incremental_window.py (Option (b) cadence).

Pure date-arithmetic helper — no Databento access required, so these run in
full isolation. Mirrors the test discipline of
tests/test_a9b_2a_plan_shards.py.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

# Load the script as a module without requiring scripts/ on sys.path.
# Per /memories/python-testing.md: insert into sys.modules before
# exec_module so any annotation introspection inside the module sees a
# resolved entry.
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "databento_incremental_window.py"
_SPEC = importlib.util.spec_from_file_location("databento_incremental_window", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

REASON_COLD_START = _MOD.REASON_COLD_START
REASON_INCREMENTAL = _MOD.REASON_INCREMENTAL
REASON_WATERMARK_AHEAD = _MOD.REASON_WATERMARK_AHEAD
WindowPlan = _MOD.WindowPlan
main = _MOD.main
narrow_scan_window = _MOD.narrow_scan_window


def _inclusive_days(plan: WindowPlan) -> int:
    return (plan.end_date - plan.start_date).days + 1


# --------------------------------------------------------------------------- #
# Cold start                                                                  #
# --------------------------------------------------------------------------- #
def test_cold_start_uses_full_lookback() -> None:
    plan = narrow_scan_window(
        last_baked_day=None,
        today=date(2026, 6, 8),
        full_lookback_days=30,
    )
    assert plan.reason == REASON_COLD_START
    assert plan.end_date == date(2026, 6, 8)
    assert plan.start_date == date(2026, 5, 10)  # 8 Jun - 29 days
    assert plan.effective_lookback_days == 30
    assert _inclusive_days(plan) == 30


# --------------------------------------------------------------------------- #
# Steady-state incremental                                                     #
# --------------------------------------------------------------------------- #
def test_incremental_starts_after_watermark_with_overlap() -> None:
    # Watermark 5 Jun, today 8 Jun, overlap 1 -> re-scan from 5 Jun (overlap
    # includes the watermark day itself) through 8 Jun = 4 days.
    plan = narrow_scan_window(
        last_baked_day=date(2026, 6, 5),
        today=date(2026, 6, 8),
        full_lookback_days=30,
        safety_overlap_days=1,
    )
    assert plan.reason == REASON_INCREMENTAL
    assert plan.start_date == date(2026, 6, 5)
    assert plan.end_date == date(2026, 6, 8)
    assert plan.effective_lookback_days == 4
    assert _inclusive_days(plan) == 4


def test_incremental_zero_overlap_starts_strictly_after_watermark() -> None:
    plan = narrow_scan_window(
        last_baked_day=date(2026, 6, 5),
        today=date(2026, 6, 8),
        full_lookback_days=30,
        safety_overlap_days=0,
    )
    assert plan.reason == REASON_INCREMENTAL
    assert plan.start_date == date(2026, 6, 6)  # strictly after watermark
    assert plan.effective_lookback_days == 3


def test_incremental_never_exceeds_full_lookback() -> None:
    # Very old watermark would imply a huge window; the full lookback caps it.
    plan = narrow_scan_window(
        last_baked_day=date(2026, 1, 1),
        today=date(2026, 6, 8),
        full_lookback_days=30,
        safety_overlap_days=1,
    )
    assert plan.reason == REASON_INCREMENTAL
    assert plan.effective_lookback_days == 30
    assert plan.start_date == date(2026, 5, 10)
    assert _inclusive_days(plan) <= 30


def test_incremental_respects_min_refresh_floor() -> None:
    # Watermark == today-1 with zero overlap would imply a 1-day window; a
    # higher min_refresh_days floor widens it back out.
    plan = narrow_scan_window(
        last_baked_day=date(2026, 6, 7),
        today=date(2026, 6, 8),
        full_lookback_days=30,
        min_refresh_days=5,
        safety_overlap_days=0,
    )
    assert plan.reason == REASON_INCREMENTAL
    assert plan.effective_lookback_days == 5
    assert plan.start_date == date(2026, 6, 4)  # 8 Jun - 4 days


def test_incremental_same_day_watermark_minus_overlap() -> None:
    # Watermark yesterday, default overlap 1 -> start = yesterday (re-confirm).
    plan = narrow_scan_window(
        last_baked_day=date(2026, 6, 7),
        today=date(2026, 6, 8),
        full_lookback_days=30,
    )
    assert plan.start_date == date(2026, 6, 7)
    assert plan.effective_lookback_days == 2


# --------------------------------------------------------------------------- #
# Watermark at/after today                                                     #
# --------------------------------------------------------------------------- #
def test_watermark_equal_today_refreshes_minimum() -> None:
    plan = narrow_scan_window(
        last_baked_day=date(2026, 6, 8),
        today=date(2026, 6, 8),
        full_lookback_days=30,
        min_refresh_days=1,
    )
    assert plan.reason == REASON_WATERMARK_AHEAD
    assert plan.start_date == date(2026, 6, 8)
    assert plan.end_date == date(2026, 6, 8)
    assert plan.effective_lookback_days == 1


def test_watermark_ahead_of_today_refreshes_minimum_window() -> None:
    plan = narrow_scan_window(
        last_baked_day=date(2026, 6, 9),
        today=date(2026, 6, 8),
        full_lookback_days=30,
        min_refresh_days=3,
    )
    assert plan.reason == REASON_WATERMARK_AHEAD
    assert plan.end_date == date(2026, 6, 8)
    assert plan.start_date == date(2026, 6, 6)  # 8 Jun - 2 days
    assert plan.effective_lookback_days == 3


# --------------------------------------------------------------------------- #
# Invariants                                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("overlap", [0, 1, 2, 5])
@pytest.mark.parametrize("watermark_age", [0, 1, 3, 7, 45, 400])
def test_window_invariants_hold(overlap: int, watermark_age: int) -> None:
    from datetime import timedelta

    today = date(2026, 6, 8)
    full = 30
    min_refresh = 1
    wm = today - timedelta(days=watermark_age)
    plan = narrow_scan_window(
        last_baked_day=wm,
        today=today,
        full_lookback_days=full,
        min_refresh_days=min_refresh,
        safety_overlap_days=overlap,
    )
    # start never after end
    assert plan.start_date <= plan.end_date
    # end is always today
    assert plan.end_date == today
    # effective lookback within [min_refresh, full]
    assert min_refresh <= plan.effective_lookback_days <= full
    # effective lookback matches the inclusive day count
    assert plan.effective_lookback_days == _inclusive_days(plan)


# --------------------------------------------------------------------------- #
# Validation errors                                                            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kwargs",
    [
        {"full_lookback_days": 0},
        {"full_lookback_days": 30, "min_refresh_days": 0},
        {"full_lookback_days": 30, "min_refresh_days": 31},
        {"full_lookback_days": 30, "safety_overlap_days": -1},
    ],
)
def test_invalid_args_raise_value_error(kwargs: dict) -> None:
    base = {"last_baked_day": None, "today": date(2026, 6, 8)}
    base.update(kwargs)
    with pytest.raises(ValueError):
        narrow_scan_window(**base)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def test_main_cold_start_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--full-lookback-days", "30", "--end-date", "2026-06-08"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == REASON_COLD_START
    assert payload["start_date"] == "2026-05-10"
    assert payload["end_date"] == "2026-06-08"
    assert payload["effective_lookback_days"] == 30


def test_main_incremental_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "--full-lookback-days",
            "30",
            "--last-baked-day",
            "2026-06-05",
            "--end-date",
            "2026-06-08",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == REASON_INCREMENTAL
    assert payload["start_date"] == "2026-06-05"
    assert payload["effective_lookback_days"] == 4


def test_main_invalid_returns_rc2(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--full-lookback-days", "0"])
    assert rc == 2
    assert "error:" in capsys.readouterr().err


def test_script_runs_as_subprocess() -> None:
    # Smoke test the actual entrypoint the workflow would call.
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--full-lookback-days",
            "30",
            "--last-baked-day",
            "2026-06-05",
            "--end-date",
            "2026-06-08",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["reason"] == REASON_INCREMENTAL
