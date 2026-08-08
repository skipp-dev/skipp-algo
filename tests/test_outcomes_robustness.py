"""Robustness of open_prep.outcomes: retention parse, non-dated load, non-finite save.

Regression coverage for a bug-hunt on open_prep/outcomes.py (2026-07-09):
- retention env of "INF"/"1e309" overflowed int() (OverflowError escaped the catch)
- a non-dated ``outcomes_*.json`` was loaded in full, bypassing lookback_days
- NaN/inf in a record crashed json.dump(allow_nan=False), losing the whole day
"""
from __future__ import annotations

import datetime as _dt
import json
from datetime import date

from open_prep import outcomes


def _shadow(monkeypatch, tmp_path):
    """Redirect writes off the canonical CI dir (via #3332's env override)."""
    d = tmp_path / "shadow"
    monkeypatch.setenv("OPEN_PREP_OUTCOMES_DIR", str(d))
    return d


def test_retention_inf_does_not_crash(monkeypatch, tmp_path):
    _shadow(monkeypatch, tmp_path)
    monkeypatch.setenv("OPEN_PREP_OUTCOME_RETENTION_DAYS", "INF")
    # int(float("INF")) raises OverflowError — must be caught (was: crashed AFTER
    # the file had been written), falling back to the 90-day default.
    p = outcomes.store_daily_outcomes(date(2020, 1, 2), [{"symbol": "NVDA", "profitable_30m": True}])
    assert p.exists()


def test_retention_below_floor_warns_and_clamps(monkeypatch, tmp_path, caplog):
    shadow = _shadow(monkeypatch, tmp_path)
    monkeypatch.setenv("OPEN_PREP_OUTCOME_RETENTION_DAYS", "2")
    for i in range(10):
        outcomes.store_daily_outcomes(date(2020, 1, 1) + _dt.timedelta(days=i), [{"symbol": "X"}])
    with caplog.at_level("WARNING", logger="open_prep.outcomes"):
        outcomes.store_daily_outcomes(date(2020, 1, 20), [{"symbol": "Y"}])
    kept = sorted(shadow.glob("outcomes_*.json"))
    assert len(kept) == 7  # clamped to the 7-day floor, NOT the requested 2
    assert any("below the 7-day floor" in r.getMessage() for r in caplog.records)


def test_non_dated_file_is_skipped_and_does_not_bypass_lookback(monkeypatch, tmp_path):
    shadow = _shadow(monkeypatch, tmp_path)
    shadow.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        outcomes.store_daily_outcomes(date(2020, 2, 1) + _dt.timedelta(days=i), [{"symbol": f"S{i}"}])
    # A huge non-dated backup that previously loaded in full, bypassing the limit.
    (shadow / "outcomes_backup.json").write_text(json.dumps([{"symbol": "B"}] * 50))
    loaded = outcomes._load_outcomes_range(lookback_days=2)
    assert len(loaded) == 2  # only the 2 newest DATED files; backup skipped
    assert all(r["symbol"] != "B" for r in loaded)


def test_non_finite_record_field_is_nulled_not_crash(monkeypatch, tmp_path, caplog):
    _shadow(monkeypatch, tmp_path)
    with caplog.at_level("WARNING", logger="open_prep.outcomes"):
        p = outcomes.store_daily_outcomes(
            date(2020, 3, 1),
            [{"symbol": "NVDA", "gap_pct": float("nan"), "rvol": float("inf"), "ok": 1.5}],
        )
    assert p.exists()  # did not crash under allow_nan=False
    data = json.loads(p.read_text())
    assert data[0]["gap_pct"] is None and data[0]["rvol"] is None
    assert data[0]["ok"] == 1.5  # finite value preserved
    assert any("non-finite float" in r.getMessage() for r in caplog.records)


def test_compute_hit_rates_excludes_missing_gap_from_real_zero_bucket(monkeypatch):
    records = [
        {
            "symbol": "MISSING",
            "gap_pct": None,
            "rvol": 2.0,
            "profitable_30m": False,
            "pnl_30m_pct": -1.0,
        },
        {
            "symbol": "ZERO",
            "gap_pct": 0.0,
            "rvol": 2.0,
            "profitable_30m": True,
            "pnl_30m_pct": 1.0,
        },
    ]
    monkeypatch.setattr(outcomes, "_load_outcomes_range", lambda _days: records)

    buckets = outcomes.compute_hit_rates(lookback_days=20)

    assert sum(bucket["total"] for bucket in buckets.values()) == 1
    assert sum(bucket["profitable"] for bucket in buckets.values()) == 1
