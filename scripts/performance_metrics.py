"""Performance metrics for walk-forward evaluation (Sprint C2 / T4).

Pure stdlib + numpy. Provides per-fold and aggregate metrics that the
walk-forward runner (T3) and the calibration report (T7) consume:

- ``compute_sharpe``               — annualised Sharpe ratio
- ``compute_max_drawdown``         — peak-to-trough drawdown on equity
- ``compute_walk_forward_efficiency`` — OOS / IS annualised return ratio
- ``compute_profit_factor``        — gross gain / gross loss
- ``compute_hit_rate``             — fraction of positive trades
- ``compute_avg_r_multiple``       — mean of supplied R-multiples

All functions return ``None`` when the input is too small or the metric
is undefined (e.g. zero variance for Sharpe, zero gross loss for
profit factor) so downstream code can branch without try/except.

References
----------
- TradeStation WFE definition:
  https://help.tradestation.com/09_01/tswfo/topics/walk-forward_summary_out-of-sample.htm
- Sharpe (1994), *The Sharpe Ratio*, Journal of Portfolio Management.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------


def compute_sharpe(
    returns: Sequence[float] | np.ndarray,
    *,
    periods_per_year: int = 252,
    risk_free_per_period: float = 0.0,
) -> float | None:
    """Annualised Sharpe ratio.

    Returns ``None`` if fewer than 2 observations or zero variance.
    """

    arr = np.asarray(returns, dtype=np.float64)
    if arr.size < 2:
        return None
    excess = arr - risk_free_per_period
    sd = float(np.std(excess, ddof=1))
    # Treat near-zero variance (e.g. all-equal floats with tiny rounding
    # noise) as degenerate so callers get a clean ``None`` instead of an
    # absurd ratio.
    if sd <= 1e-12 or not math.isfinite(sd):
        return None
    mean = float(np.mean(excess))
    return (mean / sd) * math.sqrt(periods_per_year)


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------


def compute_max_drawdown(equity: Sequence[float] | np.ndarray) -> float | None:
    """Maximum peak-to-trough drawdown (negative or zero).

    ``equity`` is the cumulative equity curve. Returns ``None`` for
    empty input. Uses arithmetic differences so it works for both
    PnL-cumsum and price-level series; for return-multiplicative
    series, pass the *level* curve, not the per-period returns.
    """

    arr = np.asarray(equity, dtype=np.float64)
    if arr.size == 0:
        return None
    running_max = np.maximum.accumulate(arr)
    drawdowns = arr - running_max
    return float(drawdowns.min())


# ---------------------------------------------------------------------------
# Walk-Forward Efficiency
# ---------------------------------------------------------------------------


def compute_walk_forward_efficiency(
    is_returns_per_fold: Sequence[Sequence[float] | np.ndarray],
    oos_returns_per_fold: Sequence[Sequence[float] | np.ndarray],
    *,
    periods_per_year: int = 252,
) -> float | None:
    """Walk-forward efficiency = annualised(OOS) / annualised(IS).

    Concatenates IS and OOS returns across folds, annualises the mean
    return for each set, and returns the ratio. Values > 1 indicate
    the OOS performance exceeded IS (rare; usually due to overfitting
    to losing IS folds). Healthy ratios sit in [0.5, 1.0]; below 0.5
    the strategy is heavily overfit.

    Returns ``None`` if either side is empty or IS mean is zero.
    """

    if len(is_returns_per_fold) == 0 or len(oos_returns_per_fold) == 0:
        return None
    if len(is_returns_per_fold) != len(oos_returns_per_fold):
        raise ValueError(
            "is_returns_per_fold and oos_returns_per_fold must have same length"
        )

    is_flat = np.concatenate([np.asarray(r, dtype=np.float64) for r in is_returns_per_fold])
    oos_flat = np.concatenate([np.asarray(r, dtype=np.float64) for r in oos_returns_per_fold])
    if is_flat.size == 0 or oos_flat.size == 0:
        return None

    is_ann = float(np.mean(is_flat)) * periods_per_year
    oos_ann = float(np.mean(oos_flat)) * periods_per_year
    if is_ann == 0.0 or not math.isfinite(is_ann):
        return None
    return oos_ann / is_ann


# ---------------------------------------------------------------------------
# Profit factor / hit rate / R-multiple
# ---------------------------------------------------------------------------


def compute_profit_factor(returns: Sequence[float] | np.ndarray) -> float | None:
    """Gross gain divided by absolute gross loss.

    Returns ``None`` when there are no losing trades (denominator
    undefined) or no trades at all. Returns ``0.0`` when there are
    losses but no wins.
    """

    arr = np.asarray(returns, dtype=np.float64)
    if arr.size == 0:
        return None
    wins = arr[arr > 0].sum()
    losses = -arr[arr < 0].sum()  # positive magnitude
    if losses == 0.0:
        return None
    return float(wins / losses)


def compute_hit_rate(returns: Sequence[float] | np.ndarray) -> float | None:
    """Fraction of trades with strictly positive return."""

    arr = np.asarray(returns, dtype=np.float64)
    if arr.size == 0:
        return None
    return float((arr > 0).sum()) / arr.size


def compute_avg_r_multiple(r_multiples: Sequence[float] | np.ndarray) -> float | None:
    """Mean of supplied R-multiples (assumes caller has computed R)."""

    arr = np.asarray(r_multiples, dtype=np.float64)
    if arr.size == 0:
        return None
    return float(np.mean(arr))


# ---------------------------------------------------------------------------
# Aggregate convenience
# ---------------------------------------------------------------------------


def compute_fold_metrics(
    returns: Sequence[float] | np.ndarray,
    *,
    periods_per_year: int = 252,
) -> dict[str, float | int | None]:
    """One-shot per-fold metrics dict for the walk-forward runner."""

    arr = np.asarray(returns, dtype=np.float64)
    if arr.ndim != 1:
        # C-sprint deep-review C2: a 2-D returns array silently
        # produces a multi-row ``cumsum`` that flattens to garbage
        # equity in the per-fold metrics. Fail loud at the boundary
        # so the upstream callsite gets a clear shape error.
        raise ValueError(
            f"compute_fold_metrics: returns must be 1-D; got shape {arr.shape}"
        )
    equity = np.cumsum(arr) if arr.size > 0 else arr
    return {
        "n": int(arr.size),
        "sharpe": compute_sharpe(arr, periods_per_year=periods_per_year),
        "max_drawdown": compute_max_drawdown(equity),
        "profit_factor": compute_profit_factor(arr),
        "hit_rate": compute_hit_rate(arr),
        "total_return": float(arr.sum()) if arr.size > 0 else 0.0,
    }
