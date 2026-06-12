"""Unit tests for the pre-market smoke guard in run_ibkr_open_execution.

Copilot review #2691: ``_check_smoke_guard`` is safety-critical (it is the
only thing standing between a failed 08:00-ET smoke round-trip and a live
09:28-ET order submission) and had no direct coverage. Covers all four
paths: HALT sentinel present, missing today-JSONL, stale today-JSONL, and
the ``--skip-smoke-guard`` bypass (which must be loud but non-blocking).

Fully offline: no ib_async import is triggered by calling the guard.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import scripts.run_ibkr_open_execution as mod

_PINNED_DATE = "2026-06-11"


@pytest.fixture()
def guard_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the guard's module-level paths at an isolated tmp repo root."""
    monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_SMOKE_HALT_PATH", tmp_path / "cache" / "live" / "smoke_HALT")
    # Pin the date so a suite running across midnight UTC cannot flake
    # between JSONL creation and the guard's own date lookup.
    monkeypatch.setattr(mod, "_repo_date_utc", lambda: _PINNED_DATE)
    (tmp_path / "cache" / "live").mkdir(parents=True)
    return tmp_path


def _write_today_jsonl(root: Path, *, age_hours: float = 0.0) -> Path:
    jsonl = root / "cache" / "live" / f"smoke_{_PINNED_DATE}.jsonl"
    jsonl.write_text('{"event": "smoke_ok"}\n', encoding="utf-8")
    if age_hours:
        mtime = (datetime.now(UTC) - timedelta(hours=age_hours)).timestamp()
        os.utime(jsonl, (mtime, mtime))
    return jsonl


def test_halt_sentinel_blocks(guard_env: Path) -> None:
    mod._SMOKE_HALT_PATH.write_text("EXIT=3 leftover orders\n", encoding="utf-8")
    _write_today_jsonl(guard_env)  # fresh JSONL must NOT rescue a HALT
    with pytest.raises(SystemExit, match="smoke_HALT sentinel present"):
        mod._check_smoke_guard(skip=False)


def test_missing_today_jsonl_blocks(guard_env: Path) -> None:
    with pytest.raises(SystemExit, match="smoke has not run today"):
        mod._check_smoke_guard(skip=False)


def test_stale_today_jsonl_blocks(guard_env: Path) -> None:
    _write_today_jsonl(guard_env, age_hours=mod._SMOKE_JSONL_MAX_AGE_HOURS + 1)
    with pytest.raises(SystemExit, match="old"):
        mod._check_smoke_guard(skip=False)


def test_future_mtime_jsonl_blocks(guard_env: Path) -> None:
    # Clock skew: an mtime in the future must never count as "fresh".
    _write_today_jsonl(guard_env, age_hours=-2.0)
    with pytest.raises(SystemExit, match="FUTURE"):
        mod._check_smoke_guard(skip=False)


def test_fresh_today_jsonl_passes(guard_env: Path) -> None:
    _write_today_jsonl(guard_env)
    mod._check_smoke_guard(skip=False)  # must not raise


def test_skip_bypasses_halt_and_missing_jsonl(guard_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Worst case: HALT present AND no JSONL — bypass must still proceed,
    # but loudly.
    mod._SMOKE_HALT_PATH.write_text("EXIT=2 risk violation\n", encoding="utf-8")
    mod._check_smoke_guard(skip=True)  # must not raise
    assert "BYPASSED" in capsys.readouterr().out


def test_yesterdays_jsonl_does_not_count(guard_env: Path) -> None:
    # A JSONL keyed to yesterday's date must not satisfy the today-check,
    # regardless of mtime.
    jsonl = guard_env / "cache" / "live" / "smoke_2026-06-10.jsonl"
    jsonl.write_text('{"event": "smoke_ok"}\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="smoke has not run today"):
        mod._check_smoke_guard(skip=False)
