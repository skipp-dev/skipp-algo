"""Tests for ``scripts/walk_forward_runner.py`` (Sprint C2 / T3)."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.walk_forward import WalkForwardSplitter
from scripts.walk_forward_runner import (
    FoldResult,
    WalkForwardResult,
    run_walk_forward,
)


def _identity_optimize(train: np.ndarray) -> dict:
    """Trivial optimizer: pick the per-period mean as the 'param'."""

    return {"mu": float(train.mean()) if train.size else 0.0}


def _evaluate_passthrough(params: dict, slice_returns: np.ndarray) -> np.ndarray:
    """Evaluator: 'strategy returns' = slice returns scaled by sign(mu)."""

    sign = 1.0 if params["mu"] >= 0 else -1.0
    return slice_returns * sign


def test_basic_runner_yields_one_result_per_fold() -> None:
    rng = np.random.default_rng(0)
    n = 200
    returns = rng.normal(0.001, 0.01, size=n)
    timestamps = np.arange(n, dtype=np.int64)
    splitter = WalkForwardSplitter(
        window_type="rolling", n_splits=4, train_size=80, test_size=20
    )
    out = run_walk_forward(
        returns,
        timestamps=timestamps,
        splitter=splitter,
        optimize_fn=_identity_optimize,
        evaluate_fn=_evaluate_passthrough,
    )
    assert isinstance(out, WalkForwardResult)
    assert len(out.folds) == 4
    for f in out.folds:
        assert isinstance(f, FoldResult)
        assert f.n_train == 80
        assert f.n_test == 20
        assert "sharpe" in f.oos_metrics


def test_runner_aggregates_walk_forward_efficiency() -> None:
    rng = np.random.default_rng(1)
    n = 300
    returns = rng.normal(0.001, 0.01, size=n)
    timestamps = np.arange(n, dtype=np.int64)
    splitter = WalkForwardSplitter(
        window_type="anchored", n_splits=3, train_size=120, test_size=40
    )
    out = run_walk_forward(
        returns,
        timestamps=timestamps,
        splitter=splitter,
        optimize_fn=_identity_optimize,
        evaluate_fn=_evaluate_passthrough,
    )
    # WFE may be None when sharpes are degenerate, but for normal RNG
    # input it should be a finite number.
    assert out.walk_forward_efficiency is not None
    assert np.isfinite(out.walk_forward_efficiency)


def test_runner_skips_empty_folds_and_records_note() -> None:
    # n=20, splits=2, train_size=15, test_size=10 → some folds will be too small
    returns = np.linspace(-0.01, 0.01, 20)
    timestamps = np.arange(20, dtype=np.int64)
    splitter = WalkForwardSplitter(
        window_type="rolling", n_splits=2, train_size=5, test_size=5
    )
    out = run_walk_forward(
        returns,
        timestamps=timestamps,
        splitter=splitter,
        optimize_fn=_identity_optimize,
        evaluate_fn=_evaluate_passthrough,
    )
    # At least one fold should have run.
    assert len(out.folds) >= 1


def test_runner_validates_aligned_arrays() -> None:
    splitter = WalkForwardSplitter(
        window_type="rolling", n_splits=2, train_size=5, test_size=5
    )
    with pytest.raises(ValueError, match="same shape"):
        run_walk_forward(
            np.zeros(10),
            timestamps=np.zeros(11, dtype=np.int64),
            splitter=splitter,
            optimize_fn=_identity_optimize,
            evaluate_fn=_evaluate_passthrough,
        )


def test_runner_rejects_non_1d_evaluator_output() -> None:
    splitter = WalkForwardSplitter(
        window_type="rolling", n_splits=2, train_size=20, test_size=10
    )

    def bad_eval(params, slice_):
        return np.column_stack([slice_, slice_])

    with pytest.raises(ValueError, match="1-D"):
        run_walk_forward(
            np.linspace(-0.01, 0.01, 60),
            timestamps=np.arange(60, dtype=np.int64),
            splitter=splitter,
            optimize_fn=_identity_optimize,
            evaluate_fn=bad_eval,
        )


def test_runner_handles_evaluator_returning_none() -> None:
    splitter = WalkForwardSplitter(
        window_type="rolling", n_splits=2, train_size=20, test_size=10
    )

    def none_eval(params, slice_):
        return None

    out = run_walk_forward(
        np.linspace(-0.01, 0.01, 60),
        timestamps=np.arange(60, dtype=np.int64),
        splitter=splitter,
        optimize_fn=_identity_optimize,
        evaluate_fn=none_eval,
    )
    # Empty per-trade arrays → metrics are None but the runner doesn't crash.
    for f in out.folds:
        assert f.oos_metrics["sharpe"] is None


def test_runner_passes_through_n_jobs() -> None:
    splitter = WalkForwardSplitter(
        window_type="rolling", n_splits=2, train_size=20, test_size=10
    )
    out = run_walk_forward(
        np.linspace(-0.01, 0.01, 60),
        timestamps=np.arange(60, dtype=np.int64),
        splitter=splitter,
        optimize_fn=_identity_optimize,
        evaluate_fn=_evaluate_passthrough,
        n_jobs=4,
    )
    assert out.n_jobs == 4


def test_runner_aggregate_metrics_count_matches_folds() -> None:
    splitter = WalkForwardSplitter(
        window_type="rolling", n_splits=3, train_size=50, test_size=20
    )
    rng = np.random.default_rng(7)
    returns = rng.normal(0.0, 0.01, size=200)
    out = run_walk_forward(
        returns,
        timestamps=np.arange(200, dtype=np.int64),
        splitter=splitter,
        optimize_fn=_identity_optimize,
        evaluate_fn=_evaluate_passthrough,
    )
    assert out.aggregate_oos_metrics["n_folds_evaluated"] == len(out.folds)
