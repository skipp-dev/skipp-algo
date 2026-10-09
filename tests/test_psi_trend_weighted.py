"""Sprint C9.1 tests for psi_trend_alert + psi_weighted."""
from __future__ import annotations

import pytest

from ml.drift.trend import (
    psi_trend_alert,
    psi_weighted,
)

# ---------------------------------------------------------------------------
# psi_trend_alert
# ---------------------------------------------------------------------------


def test_flat_history_is_ok() -> None:
    alert = psi_trend_alert([0.05] * 10)
    assert alert.severity == "ok"
    assert alert.slope_per_day == pytest.approx(0.0)


def test_slow_climb_triggers_warn_before_level_threshold() -> None:
    """14-day climb 0.05 → 0.20 should fire trend_warn while still under PSI=0.25."""
    history = [0.05 + 0.011 * i for i in range(14)]  # slope ~0.011/day
    alert = psi_trend_alert(history, window=14, slope_warn=0.005, slope_alarm=0.020)
    assert alert.severity == "trend_warn"
    assert max(history) < 0.25  # still under canonical PSI alarm level
    assert alert.slope_per_day > 0.005


def test_sharp_climb_triggers_alarm() -> None:
    history = [0.0 + 0.030 * i for i in range(7)]  # slope 0.030/day
    alert = psi_trend_alert(history, window=7)
    assert alert.severity == "trend_alarm"


def test_negative_slope_is_ok() -> None:
    """A decreasing PSI (improving) must not trigger any trend alert."""
    history = [0.30 - 0.020 * i for i in range(8)]
    alert = psi_trend_alert(history, window=8)
    assert alert.severity == "ok"


def test_window_truncates_history() -> None:
    """Old samples outside the window must not affect the slope."""
    # First 20 samples are climbing, last 5 flat.
    history = [0.0 + 0.01 * i for i in range(20)] + [0.20] * 5
    alert = psi_trend_alert(history, window=5)
    assert alert.severity == "ok"
    assert alert.slope_per_day == pytest.approx(0.0)


def test_empty_history_is_ok() -> None:
    alert = psi_trend_alert([])
    assert alert.severity == "ok"
    assert alert.n_samples == 0


def test_validation() -> None:
    with pytest.raises(ValueError, match="window"):
        psi_trend_alert([0.1, 0.2], window=1)
    with pytest.raises(ValueError, match="slope_warn"):
        psi_trend_alert([0.1] * 5, slope_warn=0.0)
    with pytest.raises(ValueError, match="slope_warn"):
        psi_trend_alert([0.1] * 5, slope_warn=0.02, slope_alarm=0.01)


# ---------------------------------------------------------------------------
# psi_weighted
# ---------------------------------------------------------------------------


def test_psi_weighted_no_importance_is_equal_weighted_mean() -> None:
    psi = {"a": 0.10, "b": 0.20, "c": 0.30}
    assert psi_weighted(psi) == pytest.approx(0.20)


def test_psi_weighted_drops_low_importance_noise() -> None:
    """High-PSI noise on a feature with importance=0 must not poison aggregate."""
    psi = {"signal": 0.05, "noise": 0.50}
    importance = {"signal": 1.0, "noise": 0.0}
    assert psi_weighted(psi, importance) == pytest.approx(0.05)


def test_psi_weighted_normalises_weights() -> None:
    psi = {"a": 0.10, "b": 0.30}
    importance = {"a": 4.0, "b": 1.0}
    # weighted = (4*0.10 + 1*0.30) / 5 = 0.14
    assert psi_weighted(psi, importance) == pytest.approx(0.14)


def test_psi_weighted_missing_importance_keys_excluded() -> None:
    psi = {"a": 0.10, "b": 0.30, "c": 0.50}
    importance = {"a": 1.0, "b": 1.0}  # c missing
    # weighted = (1*0.10 + 1*0.30) / 2 = 0.20  (c excluded)
    assert psi_weighted(psi, importance) == pytest.approx(0.20)


def test_psi_weighted_negative_weights_clamped_to_zero() -> None:
    psi = {"a": 0.10, "b": 0.30}
    importance = {"a": 1.0, "b": -5.0}
    # b's negative weight is clamped → only a contributes
    assert psi_weighted(psi, importance) == pytest.approx(0.10)


def test_psi_weighted_empty_inputs_zero() -> None:
    assert psi_weighted({}) == 0.0
    assert psi_weighted({"a": 0.10}, {"b": 1.0}) == 0.0  # no overlap


def test_psi_weighted_all_zero_weights_returns_zero() -> None:
    psi = {"a": 0.50, "b": 0.50}
    importance = {"a": 0.0, "b": 0.0}
    assert psi_weighted(psi, importance) == 0.0
