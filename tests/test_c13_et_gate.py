"""Tests for automation/launchd/lib_c13_et_gate.sh (DST-robust ET gate).

The gate exists because launchd `StartCalendarInterval` fires in the Mac's
LOCAL timezone, but the C13 jobs are scheduled against US market (ET) time. On
a non-ET Mac (e.g. Europe/Berlin) the plists therefore fire at three candidate
local times bracketing the Berlin<->ET offset, and this gate lets exactly one
per ET weekday proceed. Root-caused 2026-07-07 (paper orders placed ~6h early).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_LIB = _REPO / "automation" / "launchd" / "lib_c13_et_gate.sh"


def _run_gate(tmp_repo: Path, now_et: str, dow: int, thh: str, tmm: str, tol: str) -> int:
    """Invoke the sourced gate with an injected ET clock; return its exit code."""
    script = (
        f'source "{_LIB}"; '
        f'c13_require_et_window "{tmp_repo}" {thh} {tmm} {tol} testjob'
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        env={
            "PATH": "/usr/bin:/bin",
            "C13_GATE_NOW_ET": now_et,
            "C13_GATE_NOW_DOW": str(dow),
        },
        capture_output=True,
        text=True,
    )
    return proc.returncode


def test_gate_passes_inside_window(tmp_path: Path) -> None:
    assert _run_gate(tmp_path, "09:30", 1, "09", "28", "10") == 0


def test_gate_passes_at_tolerance_edge(tmp_path: Path) -> None:
    assert _run_gate(tmp_path, "09:38", 1, "09", "28", "10") == 0


def test_gate_skips_just_outside_tolerance(tmp_path: Path) -> None:
    assert _run_gate(tmp_path, "09:39", 1, "09", "28", "10") != 0


def test_gate_skips_far_out_of_window(tmp_path: Path) -> None:
    # The exact pre-fix symptom: 09:28 Berlin == 03:28 ET, hours before the open.
    assert _run_gate(tmp_path, "03:28", 1, "09", "28", "10") != 0


def test_gate_skips_weekend(tmp_path: Path) -> None:
    assert _run_gate(tmp_path, "09:28", 6, "09", "28", "10") != 0  # Saturday


def test_gate_runs_exactly_once_per_et_day(tmp_path: Path) -> None:
    # Two in-window candidate fires (or a launchd catch-up) must not double-run
    # -- for phase-a that would mean duplicate paper orders.
    assert _run_gate(tmp_path, "09:28", 1, "09", "28", "10") == 0
    assert _run_gate(tmp_path, "09:28", 1, "09", "28", "10") != 0


# --------------------------------------------------------------------------- #
# The plist candidate LOCAL hours must bracket the ET target across DST so that
# exactly one candidate maps to the ET target regardless of the US/EU offset.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "plist_name,et_hour",
    [
        ("com.skippalgo.c13.phase-a.plist", 9),      # 09:28 ET
        ("com.skippalgo.c13.ibkr-smoke.plist", 8),   # 08:00 ET
    ],
)
def test_plist_candidate_hours_cover_dst_offsets(plist_name: str, et_hour: int) -> None:
    # Regex, not plistlib: the phase-a plist carries a pre-existing XML comment
    # with a literal ``--`` (``--phase``) that Apple's lenient launchd parser
    # accepts but strict expat rejects; the schedule entries are simple.
    text = (_REPO / "automation" / "launchd" / plist_name).read_text()
    entries = re.findall(
        r"<key>Weekday</key><integer>(\d+)</integer>"
        r"<key>Hour</key><integer>(\d+)</integer>"
        r"<key>Minute</key><integer>(\d+)</integer>",
        text,
    )
    assert entries, "no compact schedule entries found"
    hours = {int(h) for _w, h, _m in entries}
    weekdays = {int(w) for w, _h, _m in entries}
    # Berlin<->ET is +5h / +6h / +7h across the mismatched US/EU DST windows,
    # so exactly one candidate maps onto the ET target every day of the year.
    assert hours == {et_hour + 5, et_hour + 6, et_hour + 7}, hours
    # Mon-Fri only (launchd Weekday 1..5), no weekend fires.
    assert weekdays == {1, 2, 3, 4, 5}
