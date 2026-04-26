"""Pin the single-writer-per-day contract of ``store_daily_outcomes``.

C-sprint deep-review MAJOR finding: the function is named/described as
the producer for a "live outcome stream", but its implementation is an
*atomic overwrite* of the per-day artefact, not an append. Two callers
on the same day will silently clobber each other.

These tests document and pin that contract so the next consumer cannot
mistake the function for a streaming append.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest

from open_prep import outcomes


def _record(symbol: str, *, profitable: bool = True) -> dict:
    return {
        "symbol": symbol,
        "gap_pct": 2.0,
        "rvol": 1.5,
        "score": 4.0,
        "gap_bucket_label": "small",
        "rvol_bucket_label": "normal",
        "profitable_30m": profitable,
        "pnl_30m_pct": 1.0 if profitable else -1.0,
    }


@pytest.fixture
def tmp_outcomes_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``OUTCOMES_DIR`` to a per-test temp directory."""
    monkeypatch.setattr(outcomes, "OUTCOMES_DIR", tmp_path)
    return tmp_path


def test_store_daily_outcomes_overwrites_within_same_day(
    tmp_outcomes_dir: Path,
) -> None:
    """Single-writer-per-day contract: two writes on the same date with
    *disjoint* records mean the second write wins entirely.

    This is the MAJOR finding from the C-sprint deep review surfaced
    as an explicit regression-pin: changing the implementation to
    append-and-merge requires updating this test (and presumably also
    the docstring + the cron contract).
    """
    run_date = date(2026, 4, 20)
    first = [_record("AAA"), _record("BBB")]
    second = [_record("CCC"), _record("DDD"), _record("EEE")]

    outcomes.store_daily_outcomes(run_date, first)
    outcomes.store_daily_outcomes(run_date, second)

    on_disk_path = tmp_outcomes_dir / f"outcomes_{run_date.isoformat()}.json"
    on_disk = json.loads(on_disk_path.read_text(encoding="utf-8"))

    symbols_on_disk = sorted(r["symbol"] for r in on_disk)
    assert symbols_on_disk == ["CCC", "DDD", "EEE"], (
        "store_daily_outcomes performs an atomic overwrite, not an "
        "append/merge. If this assertion fails, the implementation has "
        "changed semantics and the docstring + cron contract must be "
        "updated."
    )


def test_store_daily_outcomes_atomic_on_failure(
    tmp_outcomes_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mkstemp+os.replace pattern must not leave a partial file
    behind if the write phase raises.
    """
    run_date = date(2026, 4, 21)
    outcomes.store_daily_outcomes(run_date, [_record("XYZ")])
    target = tmp_outcomes_dir / f"outcomes_{run_date.isoformat()}.json"
    assert target.exists()
    original = target.read_text(encoding="utf-8")

    # Force os.replace to fail to simulate a mid-write crash.
    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError, match="simulated replace failure"):
        outcomes.store_daily_outcomes(run_date, [_record("AAA")])

    # Original file untouched, no .tmp leftovers.
    assert target.read_text(encoding="utf-8") == original
    leftovers = [p for p in tmp_outcomes_dir.iterdir() if p.suffix == ".tmp"]
    assert leftovers == [], f"unexpected .tmp leftovers: {leftovers}"
