"""Tests for governance/measurement_oos.py (Stage #5, PR 4).

The pooled OOS calibration summary must reuse the audited leak-free calibrator
path (real forward timestamps -> purged/embargoed folds) and stay honestly
"not measured" whenever no family clears the OOS floor.
"""
from __future__ import annotations

from typing import Any

from governance.family_walkforward import family_outcome_horizon
from governance.measurement_oos import (
    OOS_CALIBRATION_SOURCE_TAG,
    build_oos_calibration_summary,
)

_BAR = 900.0
_BASE_TS = 1_700_000_000.0


def _bos_event(index: int, *, win: bool) -> dict[str, Any]:
    """A triggering BOS FamilyEvent with a discriminating score.

    Events are spaced 50 bars apart so each label+embargo guard window resolves
    before the next event (otherwise the walk-forward purge drops all training
    events and no calibration block forms).
    """
    horizon = family_outcome_horizon("BOS")
    n = horizon + 3
    anchor_ts = _BASE_TS + index * 50 * _BAR
    step = 0.6 if win else -0.6
    return {
        "family": "BOS",
        "direction": "BULL",
        "zone_low": 100.0,
        "zone_high": 101.0,
        "anchor_ts": anchor_ts,
        "forward_lows": [100.5] + [102.0 + i for i in range(n - 1)],
        "forward_highs": [101.0] + [103.0 + i for i in range(n - 1)],
        # every bar opens at the previous close; the entry is the open of bar 1
        "forward_opens": [100.9] + [100.8 + step * i for i in range(n - 1)],
        "forward_closes": [100.8 + step * i for i in range(n)],
        "forward_timestamps": [anchor_ts + (j + 1) * _BAR for j in range(n)],
        "score": 2.0 if win else 0.5,
    }


def test_measured_summary_on_separable_corpus() -> None:
    events = [_bos_event(i, win=(i % 2 == 0)) for i in range(80)]
    summary = build_oos_calibration_summary(events)
    assert summary["measured"] is True
    assert summary["families_measured"] == ["BOS"]
    assert summary["oos_calibration_n"] >= 40  # calibrator floor
    assert 0.0 <= summary["oos_calibrated_brier_score"] <= 1.0
    assert 0.0 <= summary["oos_calibrated_ece"] <= 1.0
    # Separable score -> OOS Brier must beat the 0.25 coin-flip baseline.
    assert summary["oos_calibrated_brier_score"] < 0.25
    assert summary["source"] == OOS_CALIBRATION_SOURCE_TAG


def test_unmeasured_below_oos_floor() -> None:
    # 10 events can never clear the 40-sample OOS floor -> honestly unmeasured.
    events = [_bos_event(i, win=(i % 2 == 0)) for i in range(10)]
    summary = build_oos_calibration_summary(events)
    assert summary["measured"] is False
    assert summary["oos_calibrated_brier_score"] is None
    assert summary["oos_calibrated_ece"] is None
    assert summary["oos_calibration_n"] == 0
    assert summary["families_measured"] == []


def test_unmeasured_on_empty_input() -> None:
    summary = build_oos_calibration_summary([])
    assert summary["measured"] is False
    assert summary["reason"] == "no family events"


def test_unmeasured_when_events_not_calibratable() -> None:
    # Events without a score (or forward timestamps) are excluded by
    # extract_family_calibration_samples -> nothing to calibrate.
    events = [{k: v for k, v in _bos_event(i, win=True).items() if k != "score"} for i in range(50)]
    summary = build_oos_calibration_summary(events)
    assert summary["measured"] is False
    assert summary["oos_calibrated_brier_score"] is None
