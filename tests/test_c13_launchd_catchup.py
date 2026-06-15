"""Unit tests for the C13 launchd catch-up / backfill helper.

The helper (``automation/launchd/lib_c13_catchup.sh``) computes which business
days within a bounded look-back window still need to be (re)processed, so a
driver can replay every run-date missed while the workstation was asleep
instead of letting launchd coalesce the missed firings into a single wake.

The tests drive the shell functions directly via ``bash`` and compare against
expectations computed independently in Python, so they are deterministic
regardless of the calendar date or the platform's ``date`` flavour (BSD on
macOS where the drivers run, GNU on Linux CI).
"""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "automation" / "launchd" / "lib_c13_catchup.sh"


def _run_bash(snippet: str) -> subprocess.CompletedProcess[str]:
    """Source the helper and run ``snippet`` in a strict bash subprocess."""
    script = f'set -euo pipefail\nsource "{LIB}"\n{snippet}\n'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _business_days_in_window(lookback: int) -> list[str]:
    """Mon-Fri ISO dates in [today_utc - lookback, today_utc], oldest first."""
    today = dt.datetime.now(dt.UTC).date()
    days: list[str] = []
    for i in range(lookback, -1, -1):
        d = today - dt.timedelta(days=i)
        if d.weekday() < 5:  # Monday=0 .. Friday=4
            days.append(d.isoformat())
    return days


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def test_lib_exists_and_sources_cleanly() -> None:
    assert LIB.is_file(), f"missing helper: {LIB}"
    result = _run_bash(":")
    assert result.returncode == 0, result.stderr


def test_business_dates_in_window_match_python_and_are_weekdays() -> None:
    for lookback in (0, 3, 7, 14):
        result = _run_bash(f"c13_business_dates_in_window {lookback}")
        assert result.returncode == 0, result.stderr
        emitted = result.stdout.split()
        assert emitted == _business_days_in_window(lookback)
        for iso in emitted:
            weekday = dt.date.fromisoformat(iso).weekday()
            assert weekday < 5, f"{iso} is not a weekday"


def test_marker_is_ok_default_prefix(tmp_path: Path) -> None:
    ok = tmp_path / "ok_marker"
    ok.write_text("ok:pushed:2026-06-15T09:00:00Z:cache/x.jsonl\n")
    degraded = tmp_path / "degraded_marker"
    degraded.write_text("degraded:push-failed:2026-06-15T09:00:00Z\n")
    missing = tmp_path / "does_not_exist"

    assert _run_bash(f'c13_marker_is_ok "{ok}"').returncode == 0
    assert _run_bash(f'c13_marker_is_ok "{degraded}"').returncode == 1
    assert _run_bash(f'c13_marker_is_ok "{missing}"').returncode == 1


def test_marker_is_ok_custom_success_prefix(tmp_path: Path) -> None:
    success = tmp_path / "phase_a_marker"
    success.write_text("SUCCESS|incubation-complete:audit=cache/live/x.jsonl\n")
    degraded = tmp_path / "phase_a_degraded"
    degraded.write_text("DEGRADED|incubation-failed:audit=cache/live/x.jsonl\n")

    # With the SUCCESS prefix the success marker is "done"...
    assert _run_bash(f'c13_marker_is_ok "{success}" "SUCCESS"').returncode == 0
    assert _run_bash(f'c13_marker_is_ok "{degraded}" "SUCCESS"').returncode == 1
    # ...but under the default ``ok:`` prefix a SUCCESS| marker is NOT a match.
    assert _run_bash(f'c13_marker_is_ok "{success}"').returncode == 1


def test_missing_business_dates_detects_absent_and_degraded(tmp_path: Path) -> None:
    lookback = 14
    business = _business_days_in_window(lookback)
    assert len(business) >= 3, "window too small for this test"

    # Mark every business day as published except the two oldest: leave the
    # first absent and write a degraded marker for the second.
    absent, degraded = business[0], business[1]
    for iso in business[2:]:
        (tmp_path / f".push_status_{iso}").write_text(f"ok:pushed:{iso}\n")
    (tmp_path / f".push_status_{degraded}").write_text(f"degraded:push-failed:{iso}\n")

    result = _run_bash(
        f'c13_missing_business_dates "{tmp_path}" ".push_status_" {lookback}'
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [absent, degraded]


def test_missing_business_dates_custom_success_prefix(tmp_path: Path) -> None:
    lookback = 14
    business = _business_days_in_window(lookback)
    assert len(business) >= 2

    # All SUCCESS| -> nothing missing.
    for iso in business:
        (tmp_path / f".phase_a_status_{iso}").write_text(f"SUCCESS|done:{iso}\n")
    result = _run_bash(
        f'c13_missing_business_dates "{tmp_path}" ".phase_a_status_" {lookback} "SUCCESS"'
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == []

    # Demote the oldest to DEGRADED| -> exactly that date is missing.
    oldest = business[0]
    (tmp_path / f".phase_a_status_{oldest}").write_text(f"DEGRADED|failed:{oldest}\n")
    result = _run_bash(
        f'c13_missing_business_dates "{tmp_path}" ".phase_a_status_" {lookback} "SUCCESS"'
    )
    assert result.stdout.split() == [oldest]


def test_run_with_catchup_runs_today_when_all_ok(tmp_path: Path) -> None:
    lookback = 7
    business = _business_days_in_window(lookback)
    out = tmp_path / "processed.log"
    for iso in business:
        (tmp_path / f".push_status_{iso}").write_text(f"ok:pushed:{iso}\n")
    # Ensure today is marked ok too (it is a business day on weekdays).
    (tmp_path / f".push_status_{_today()}").write_text("ok:pushed:today\n")

    snippet = (
        f'cb() {{ echo "$1" >> "{out}"; }}\n'
        f'c13_run_with_catchup "{tmp_path}" ".push_status_" cb {lookback}'
    )
    result = _run_bash(snippet)
    assert result.returncode == 0, result.stderr
    processed = out.read_text().split() if out.exists() else []
    # Safety net: even with nothing missed, today is always attempted once.
    assert processed == [_today()]


def test_run_with_catchup_replays_only_missing_dates(tmp_path: Path) -> None:
    lookback = 14
    business = _business_days_in_window(lookback)
    assert len(business) >= 3
    out = tmp_path / "processed.log"

    # Everything ok except the two oldest business days (neither is today).
    missing = business[:2]
    for iso in business[2:]:
        (tmp_path / f".push_status_{iso}").write_text(f"ok:pushed:{iso}\n")

    snippet = (
        f'cb() {{ echo "$1" >> "{out}"; }}\n'
        f'c13_run_with_catchup "{tmp_path}" ".push_status_" cb {lookback}'
    )
    result = _run_bash(snippet)
    assert result.returncode == 0, result.stderr
    processed = out.read_text().split() if out.exists() else []
    assert processed == missing  # oldest-first, and today (ok) was NOT re-run


def test_run_with_catchup_reports_callback_failures(tmp_path: Path) -> None:
    lookback = 7
    business = _business_days_in_window(lookback)
    # Nothing marked done -> every business day in the window is missing.
    snippet = (
        'cb() { return 1; }\n'  # always fail
        f'c13_run_with_catchup "{tmp_path}" ".push_status_" cb {lookback} || echo "rc=$?"'
    )
    result = _run_bash(snippet)
    assert result.returncode == 0, result.stderr
    # The helper returns the count of failed dates; at least one business day
    # (today on weekdays, or the window's weekdays) must have failed.
    expected = len(business) if business else 1
    assert f"rc={expected}" in result.stdout, result.stdout


@pytest.mark.parametrize("lookback", [0, 1, 5, 10])
def test_business_dates_window_never_includes_weekend(lookback: int) -> None:
    result = _run_bash(f"c13_business_dates_in_window {lookback}")
    assert result.returncode == 0, result.stderr
    for iso in result.stdout.split():
        assert dt.date.fromisoformat(iso).weekday() < 5
