"""Tracking-anchor test for the C9 threshold-lock-in milestone.

The C9 sprint plan parks production-threshold tuning until ~2026-07-25
(90 days of live outcomes accrued). This test is a no-op until that
date so the milestone surfaces in CI rather than living only in a
document. After the date, it asserts ``docs/c9_threshold_tuning.md``
records the lock-in (``Status: locked``) so the C9 stack does not
silently keep running on scaffolded thresholds.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

LOCK_BY = _dt.date(2026, 7, 25)
DOC = Path(__file__).resolve().parent.parent / "docs" / "c9_threshold_tuning.md"


def test_c9_thresholds_locked_after_2026_07_25() -> None:
    today = _dt.date.today()
    if today < LOCK_BY:
        pytest.skip(
            f"C9 threshold lock-in scheduled for {LOCK_BY.isoformat()}; "
            f"today is {today.isoformat()} — tracking only."
        )
    assert DOC.exists(), f"{DOC} missing after lock-in deadline"
    text = DOC.read_text(encoding="utf-8")
    assert "Status: locked" in text or "**Status:** locked" in text, (
        f"{DOC} still records scaffolded thresholds after the "
        f"{LOCK_BY.isoformat()} lock-in deadline. Run "
        "scripts/c9_threshold_replay.py against ≥90d of live outcomes "
        "and update the doc."
    )
