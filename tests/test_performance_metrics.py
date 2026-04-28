"""Tests for ``scripts/performance_metrics.py`` (Sprint C2 / T4)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from scripts.performance_metrics import (
    compute_avg_r_multiple,
    compute_fold_metrics,
    compute_hit_rate,
    compute_max_drawdown,
    compute_profit_factor,
    compute_sharpe,
    compute_walk_forward_efficiency,
)

# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------


def test_sharpe_matches_hand_calculation() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0.001, 0.01, size=252)
    sr = compute_sharpe(returns, periods_per_year=252)
    expected = (returns.mean() / returns.std(ddof=1)) * math.sqrt(252)
    assert sr is not None
    assert math.isclose(sr, expected, rel_tol=1e-9)


def test_sharpe_returns_none_on_zero_variance() -> None:
    assert compute_sharpe([0.01] * 10) is None


def test_sharpe_returns_none_on_too_few_observations() -> None:
    assert compute_sharpe([]) is None
    assert compute_sharpe([0.01]) is None


def test_sharpe_respects_risk_free_rate() -> None:
    returns = np.array([0.02, 0.01, 0.03, 0.01, 0.02])
    no_rf = compute_sharpe(returns, periods_per_year=252)
    with_rf = compute_sharpe(returns, periods_per_year=252, risk_free_per_period=0.005)
    assert no_rf is not None and with_rf is not None
    assert with_rf < no_rf  # subtracting RF reduces excess


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------


def test_max_drawdown_known_equity_curve() -> None:
    # Peak at index 2 (=3.0), trough at index 4 (=-1.0) → DD = -4.0.
    equity = np.array([1.0, 2.0, 3.0, 1.0, -1.0, 0.5, 2.0])
    assert compute_max_drawdown(equity) == -4.0


def test_max_drawdown_monotonic_increase_is_zero() -> None:
    assert compute_max_drawdown([1.0, 2.0, 3.0, 4.0]) == 0.0


def test_max_drawdown_empty_returns_none() -> None:
    assert compute_max_drawdown([]) is None


# ---------------------------------------------------------------------------
# Walk-forward efficiency
# ---------------------------------------------------------------------------


def test_wfe_equals_one_when_oos_matches_is() -> None:
    is_folds = [[0.01, 0.02], [0.015, 0.005]]
    oos_folds = [[0.01, 0.02], [0.015, 0.005]]
    assert compute_walk_forward_efficiency(is_folds, oos_folds) == 1.0


def test_wfe_below_one_indicates_overfit() -> None:
    is_folds = [[0.05, 0.05]]
    oos_folds = [[0.01, 0.01]]
    wfe = compute_walk_forward_efficiency(is_folds, oos_folds)
    assert wfe is not None
    assert math.isclose(wfe, 0.2)


def test_wfe_returns_none_when_is_mean_zero() -> None:
    is_folds = [[0.01, -0.01]]
    oos_folds = [[0.005, -0.005]]
    assert compute_walk_forward_efficiency(is_folds, oos_folds) is None


def test_wfe_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="same length"):
        compute_walk_forward_efficiency([[0.01]], [[0.01], [0.02]])


def test_wfe_empty_returns_none() -> None:
    assert compute_walk_forward_efficiency([], []) is None


# ---------------------------------------------------------------------------
# Profit factor / hit rate / R-multiple
# ---------------------------------------------------------------------------


def test_profit_factor_two_to_one() -> None:
    # wins = 4, losses = 2 → PF = 2.0
    assert compute_profit_factor([3.0, 1.0, -1.0, -1.0]) == 2.0


def test_profit_factor_no_losses_is_none() -> None:
    assert compute_profit_factor([1.0, 2.0, 3.0]) is None


def test_profit_factor_no_wins_is_zero() -> None:
    assert compute_profit_factor([-1.0, -2.0]) == 0.0


def test_profit_factor_empty_is_none() -> None:
    assert compute_profit_factor([]) is None


def test_hit_rate_basic() -> None:
    assert compute_hit_rate([1.0, -1.0, 1.0, 1.0]) == 0.75
    assert compute_hit_rate([0.0, 0.0]) == 0.0  # zero is not a "hit"


def test_hit_rate_empty_is_none() -> None:
    assert compute_hit_rate([]) is None


def test_avg_r_multiple_basic() -> None:
    assert compute_avg_r_multiple([1.0, 2.0, -0.5, 1.5]) == 1.0


def test_avg_r_multiple_empty_is_none() -> None:
    assert compute_avg_r_multiple([]) is None


# ---------------------------------------------------------------------------
# Aggregate convenience
# ---------------------------------------------------------------------------


def test_compute_fold_metrics_returns_full_dict() -> None:
    returns = np.array([0.01, -0.005, 0.02, -0.01, 0.015])
    out = compute_fold_metrics(returns)
    assert out["n"] == 5
    assert out["sharpe"] is not None
    assert out["max_drawdown"] is not None and out["max_drawdown"] <= 0
    assert out["profit_factor"] is not None and out["profit_factor"] > 0
    assert out["hit_rate"] == 0.6
    assert math.isclose(out["total_return"], 0.03)


def test_compute_fold_metrics_handles_empty_returns() -> None:
    out = compute_fold_metrics([])
    assert out["n"] == 0
    assert out["sharpe"] is None
    assert out["max_drawdown"] is None
    assert out["total_return"] == 0.0


def test_compute_fold_metrics_rejects_2d_input() -> None:
    """C-sprint deep-review C2 regression: a 2-D returns array used to
    silently produce a multi-row equity flattened to garbage."""

    arr = np.zeros((3, 4), dtype=np.float64)
    with pytest.raises(ValueError, match="must be 1-D"):
        compute_fold_metrics(arr)
