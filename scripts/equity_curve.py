"""Equity curve and trade-stream aggregation helpers (Sprint C2 / T6).

Walk-forward backtests yield per-fold OOS trade streams. To produce a
single track-record artifact (Sharpe, MaxDD, Calmar) a downstream
consumer needs:

1. A chronologically concatenated equity curve across all OOS folds.
2. Per-fold equity end-points so fold contributions stay attributable.
3. Aggregate metrics that match what the live tracker computes (so
   the C9 drift watchdog can compare like-for-like).

This module deliberately stays small (pure stdlib + numpy) and depends
on nothing else in the C-series. It is consumed by the future
``walk_forward_runner.py`` (C2/T3) but is independently shippable.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FoldTrades:
    """OOS trade stream for a single walk-forward fold."""

    fold_idx: int
    timestamps: np.ndarray  # int64 monotonic per fold
    returns: np.ndarray  # per-trade return, same length as timestamps


@dataclass(frozen=True)
class EquityCurve:
    """Concatenated equity curve across folds.

    ``equity[0]`` is the starting capital (default 1.0). ``equity[i+1]``
    reflects the cumulative product of (1 + return_i) up to and
    including the i-th trade.
    """

    timestamps: np.ndarray
    returns: np.ndarray
    equity: np.ndarray
    fold_boundaries: np.ndarray  # indices in ``equity`` where each fold ends


# ---------------------------------------------------------------------------
# Concatenation
# ---------------------------------------------------------------------------


def concatenate_oos_folds(
    folds: Iterable[FoldTrades],
    *,
    starting_equity: float = 1.0,
) -> EquityCurve:
    """Stitch fold trade streams into a single equity curve.

    Folds are ordered by ``fold_idx``. Within a fold the trades are
    assumed to be in chronological order. A boundary check ensures the
    first timestamp of fold k+1 is >= last timestamp of fold k; a
    violation raises ``ValueError`` (track-record integrity).
    """

    ordered = sorted(folds, key=lambda f: f.fold_idx)
    if not ordered:
        return EquityCurve(
            timestamps=np.empty(0, dtype=np.int64),
            returns=np.empty(0, dtype=np.float64),
            equity=np.array([starting_equity], dtype=np.float64),
            fold_boundaries=np.empty(0, dtype=np.int64),
        )

    last_seen: int | None = None
    ts_parts: list[np.ndarray] = []
    ret_parts: list[np.ndarray] = []
    boundaries: list[int] = []
    running_count = 0

    for f in ordered:
        if f.timestamps.shape[0] != f.returns.shape[0]:
            raise ValueError(
                f"fold {f.fold_idx}: timestamps/returns length mismatch"
            )
        if f.timestamps.size == 0:
            # Empty folds are valid (no qualifying trades); skip.
            boundaries.append(running_count)
            continue
        if not np.all(np.diff(f.timestamps) >= 0):
            raise ValueError(f"fold {f.fold_idx}: timestamps not monotonic")
        first_ts = int(f.timestamps[0])
        if last_seen is not None and first_ts < last_seen:
            raise ValueError(
                f"fold {f.fold_idx} starts at {first_ts} which is "
                f"before previous fold end {last_seen}"
            )
        ts_parts.append(f.timestamps.astype(np.int64, copy=False))
        ret_parts.append(f.returns.astype(np.float64, copy=False))
        running_count += int(f.timestamps.size)
        boundaries.append(running_count)
        last_seen = int(f.timestamps[-1])

    if not ts_parts:
        return EquityCurve(
            timestamps=np.empty(0, dtype=np.int64),
            returns=np.empty(0, dtype=np.float64),
            equity=np.array([starting_equity], dtype=np.float64),
            fold_boundaries=np.array(boundaries, dtype=np.int64),
        )

    ts_all = np.concatenate(ts_parts)
    ret_all = np.concatenate(ret_parts)
    eq = np.empty(ret_all.size + 1, dtype=np.float64)
    eq[0] = starting_equity
    eq[1:] = starting_equity * np.cumprod(1.0 + ret_all)
    return EquityCurve(
        timestamps=ts_all,
        returns=ret_all,
        equity=eq,
        fold_boundaries=np.array(boundaries, dtype=np.int64),
    )


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


def total_return(curve: EquityCurve) -> float:
    """Final equity / starting equity − 1. Returns 0.0 when empty."""

    if curve.equity.size <= 1:
        return 0.0
    return float(curve.equity[-1] / curve.equity[0] - 1.0)


def max_drawdown(curve: EquityCurve) -> float:
    """Worst peak-to-trough on the equity curve. Returns 0.0 when empty."""

    if curve.equity.size <= 1:
        return 0.0
    running_peak = np.maximum.accumulate(curve.equity)
    drawdown = curve.equity / running_peak - 1.0
    return float(drawdown.min())


def per_fold_returns(curve: EquityCurve) -> list[float]:
    """Equity multiplier per fold − 1 (ordered by fold_idx)."""

    if curve.fold_boundaries.size == 0:
        return []
    out: list[float] = []
    prev_idx = 0
    for b in curve.fold_boundaries:
        b_int = int(b)
        if b_int == prev_idx:
            out.append(0.0)
        else:
            out.append(float(curve.equity[b_int] / curve.equity[prev_idx] - 1.0))
        prev_idx = b_int
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_fold(
    fold_idx: int,
    timestamps: Sequence[int],
    returns: Sequence[float],
) -> FoldTrades:
    """Convenience constructor for ``FoldTrades`` from python sequences."""

    return FoldTrades(
        fold_idx=fold_idx,
        timestamps=np.asarray(timestamps, dtype=np.int64),
        returns=np.asarray(returns, dtype=np.float64),
    )
