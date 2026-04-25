"""Walk-forward runner (Sprint C2 / T3).

Orchestrates a walk-forward backtest:

1. Build folds via :class:`scripts.walk_forward.WalkForwardSplitter`.
2. For each fold call ``optimize_fn(train_returns) -> params``.
3. Apply ``evaluate_fn(params, test_returns) -> per-trade returns``.
4. Aggregate per-fold IS/OOS metrics via
   :func:`scripts.performance_metrics.compute_fold_metrics` and the
   walk-forward efficiency helper.

Pure stdlib + numpy. Sequential by default; ``n_jobs`` is reserved
for a future joblib swap (kept as an explicit parameter so the
signature is stable).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from scripts.performance_metrics import (
    compute_fold_metrics,
    compute_walk_forward_efficiency,
)
from scripts.walk_forward import WalkForwardSplit, WalkForwardSplitter

__all__ = [
    "FoldResult",
    "WalkForwardResult",
    "run_walk_forward",
]


OptimizeFn = Callable[[np.ndarray], Any]
EvaluateFn = Callable[[Any, np.ndarray], np.ndarray]


@dataclass(frozen=True)
class FoldResult:
    fold_idx: int
    params: Any
    is_metrics: dict[str, float | None]
    oos_metrics: dict[str, float | None]
    n_train: int
    n_test: int
    is_returns: np.ndarray
    oos_returns: np.ndarray


@dataclass(frozen=True)
class WalkForwardResult:
    folds: list[FoldResult]
    walk_forward_efficiency: float | None
    aggregate_oos_metrics: dict[str, float | None]
    n_jobs: int = 1
    notes: list[str] = field(default_factory=list)


def _safe_evaluate(
    evaluate_fn: EvaluateFn,
    params: Any,
    returns: np.ndarray,
) -> np.ndarray:
    out = evaluate_fn(params, returns)
    if out is None:
        return np.empty(0, dtype=np.float64)
    arr = np.asarray(out, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(
            f"evaluate_fn must return a 1-D array; got shape {arr.shape}"
        )
    return arr


def _run_single_fold(
    *,
    split: WalkForwardSplit,
    returns: np.ndarray,
    optimize_fn: OptimizeFn,
    evaluate_fn: EvaluateFn,
) -> FoldResult:
    train_ret = returns[split.train_idx]
    test_ret = returns[split.test_idx]
    params = optimize_fn(train_ret)
    is_eval = _safe_evaluate(evaluate_fn, params, train_ret)
    oos_eval = _safe_evaluate(evaluate_fn, params, test_ret)
    return FoldResult(
        fold_idx=split.fold_idx,
        params=params,
        is_metrics=compute_fold_metrics(is_eval),
        oos_metrics=compute_fold_metrics(oos_eval),
        n_train=int(split.train_idx.size),
        n_test=int(split.test_idx.size),
        is_returns=is_eval,
        oos_returns=oos_eval,
    )


def run_walk_forward(
    returns: Sequence[float] | np.ndarray,
    *,
    timestamps: Sequence[int] | np.ndarray,
    splitter: WalkForwardSplitter,
    optimize_fn: OptimizeFn,
    evaluate_fn: EvaluateFn,
    exit_timestamps: Sequence[int] | np.ndarray | None = None,
    n_jobs: int = 1,
) -> WalkForwardResult:
    """Run a walk-forward backtest and return per-fold + aggregate metrics.

    ``returns`` and ``timestamps`` must be aligned 1-D arrays of the
    same length. ``optimize_fn`` is called on the train slice, then
    ``evaluate_fn(params, slice)`` is called on both slices to
    produce per-trade returns for IS and OOS metrics.

    ``n_jobs`` is currently advisory (sequential execution) — the
    parameter is reserved so callers can opt-in to parallelism later
    without an API change.
    """

    ret_arr = np.asarray(returns, dtype=np.float64)
    ts_arr = np.asarray(timestamps, dtype=np.int64)
    if ret_arr.shape != ts_arr.shape:
        raise ValueError(
            f"returns and timestamps must have same shape; "
            f"got {ret_arr.shape} vs {ts_arr.shape}"
        )

    splits = list(
        splitter.split(
            ts_arr,
            exit_timestamps=(
                np.asarray(exit_timestamps, dtype=np.int64)
                if exit_timestamps is not None
                else None
            ),
        )
    )

    fold_results: list[FoldResult] = []
    notes: list[str] = []
    for split in splits:
        if split.train_idx.size == 0 or split.test_idx.size == 0:
            notes.append(
                f"fold {split.fold_idx}: empty train ({split.train_idx.size}) "
                f"or test ({split.test_idx.size}) — skipped"
            )
            continue
        fold_results.append(
            _run_single_fold(
                split=split,
                returns=ret_arr,
                optimize_fn=optimize_fn,
                evaluate_fn=evaluate_fn,
            )
        )

    populated = [
        f for f in fold_results
        if f.is_returns.size > 0 and f.oos_returns.size > 0
    ]
    if populated:
        wfe = compute_walk_forward_efficiency(
            [f.is_returns for f in populated],
            [f.oos_returns for f in populated],
        )
    else:
        wfe = None

    oos_sharpes = [
        f.oos_metrics.get("sharpe") for f in fold_results
        if f.oos_metrics.get("sharpe") is not None
    ]
    aggregate = {
        "sharpe_mean_of_folds": (
            float(np.mean(oos_sharpes)) if oos_sharpes else None
        ),
        "n_folds_evaluated": len(fold_results),
        "n_folds_with_oos_sharpe": len(oos_sharpes),
    }

    return WalkForwardResult(
        folds=fold_results,
        walk_forward_efficiency=wfe,
        aggregate_oos_metrics=aggregate,
        n_jobs=n_jobs,
        notes=notes,
    )
