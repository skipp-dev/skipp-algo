"""Tests for ``scripts/equity_curve.py`` (Sprint C2 / T6)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from scripts.equity_curve import (
    FoldTrades,
    concatenate_oos_folds,
    make_fold,
    max_drawdown,
    per_fold_returns,
    total_return,
)

# ---------------------------------------------------------------------------
# concatenate_oos_folds
# ---------------------------------------------------------------------------


def test_empty_input_yields_starting_equity_only() -> None:
    curve = concatenate_oos_folds([])
    assert curve.equity.tolist() == [1.0]
    assert curve.timestamps.size == 0
    assert curve.returns.size == 0


def test_single_fold_compounds_correctly() -> None:
    f = make_fold(0, [1, 2, 3], [0.1, -0.05, 0.02])
    curve = concatenate_oos_folds([f])
    expected = [1.0, 1.1, 1.1 * 0.95, 1.1 * 0.95 * 1.02]
    assert np.allclose(curve.equity, expected)
    assert curve.fold_boundaries.tolist() == [3]


def test_multiple_folds_concatenated_in_index_order() -> None:
    f0 = make_fold(0, [1, 2], [0.1, 0.0])
    f1 = make_fold(1, [3, 4], [0.05, -0.1])
    # Pass out of order to verify sorting.
    curve = concatenate_oos_folds([f1, f0])
    assert curve.timestamps.tolist() == [1, 2, 3, 4]
    assert curve.fold_boundaries.tolist() == [2, 4]
    assert math.isclose(curve.equity[-1], 1.1 * 1.0 * 1.05 * 0.9)


def test_starting_equity_scales_curve() -> None:
    f = make_fold(0, [1], [0.5])
    curve = concatenate_oos_folds([f], starting_equity=10_000.0)
    assert curve.equity.tolist() == [10_000.0, 15_000.0]


def test_fold_overlap_raises() -> None:
    f0 = make_fold(0, [1, 5], [0.1, 0.0])
    f1 = make_fold(1, [3, 6], [0.05, 0.0])  # 3 < 5
    with pytest.raises(ValueError, match="before previous fold end"):
        concatenate_oos_folds([f0, f1])


def test_non_monotonic_within_fold_raises() -> None:
    f = FoldTrades(
        fold_idx=0,
        timestamps=np.array([5, 3, 4], dtype=np.int64),
        returns=np.array([0.1, 0.0, 0.0], dtype=np.float64),
    )
    with pytest.raises(ValueError, match="not monotonic"):
        concatenate_oos_folds([f])


def test_length_mismatch_raises() -> None:
    f = FoldTrades(
        fold_idx=0,
        timestamps=np.array([1, 2], dtype=np.int64),
        returns=np.array([0.1], dtype=np.float64),
    )
    with pytest.raises(ValueError, match="length mismatch"):
        concatenate_oos_folds([f])


def test_empty_folds_skipped_but_recorded() -> None:
    f0 = make_fold(0, [1], [0.1])
    f1 = make_fold(1, [], [])
    f2 = make_fold(2, [3], [-0.05])
    curve = concatenate_oos_folds([f0, f1, f2])
    assert curve.fold_boundaries.tolist() == [1, 1, 2]
    assert math.isclose(curve.equity[-1], 1.1 * 0.95)


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


def test_total_return_zero_for_empty_curve() -> None:
    curve = concatenate_oos_folds([])
    assert total_return(curve) == 0.0


def test_total_return_matches_compound() -> None:
    f = make_fold(0, [1, 2, 3], [0.1, -0.05, 0.02])
    curve = concatenate_oos_folds([f])
    assert math.isclose(total_return(curve), 1.1 * 0.95 * 1.02 - 1.0)


def test_max_drawdown_zero_for_monotonic_curve() -> None:
    f = make_fold(0, [1, 2], [0.1, 0.1])
    curve = concatenate_oos_folds([f])
    assert max_drawdown(curve) == 0.0


def test_max_drawdown_negative_on_loss_after_peak() -> None:
    f = make_fold(0, [1, 2, 3], [0.5, -0.5, 0.0])
    curve = concatenate_oos_folds([f])
    # Peak = 1.5, trough = 0.75 → DD = -0.5
    assert math.isclose(max_drawdown(curve), -0.5)


def test_max_drawdown_zero_for_empty_curve() -> None:
    assert max_drawdown(concatenate_oos_folds([])) == 0.0


def test_per_fold_returns_match_individual_fold_compounding() -> None:
    f0 = make_fold(0, [1, 2], [0.1, 0.0])
    f1 = make_fold(1, [3], [-0.2])
    curve = concatenate_oos_folds([f0, f1])
    assert per_fold_returns(curve) == pytest.approx([1.1 - 1.0, -0.2])


def test_per_fold_returns_handles_empty_fold() -> None:
    f0 = make_fold(0, [1], [0.1])
    f1 = make_fold(1, [], [])
    curve = concatenate_oos_folds([f0, f1])
    out = per_fold_returns(curve)
    assert out[0] == pytest.approx(0.1)
    assert out[1] == 0.0


def test_per_fold_returns_empty_when_no_folds() -> None:
    assert per_fold_returns(concatenate_oos_folds([])) == []
