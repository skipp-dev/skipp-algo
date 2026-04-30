"""Calibration metrics for SMC scorer outputs.

Provides three calibration error families:

* ``ece(...)``  — classical binned Expected Calibration Error (Naeini 2015).
  Kept for backwards comparability with existing CI artifacts.

* ``smooth_ece(...)`` — smooth ECE (smECE) per Błasiok & Nakkiran 2023
  (arXiv:2309.12236).  Kernel-density variant of ECE that is *consistent*
  (not bin-grid dependent) and is a sound primary metric for the Q3/Q4
  promotion gate.

* ``dce(...)`` — *testable* calibration error per Rossellini et al. 2025
  (arXiv:2502.19851).  Distance-to-calibration via isotonic projection on
  the empirical reliability curve; the report value is an upper bound that
  collapses to 0 iff the predictor is calibratable.

All functions are pure-stdlib (math + statistics + bisect) so the module
ships without scipy/sklearn dependencies and can be invoked from any CI
lane that already has the smc_core wheel.

Inputs
------
``predictions`` : iterable of float in [0, 1]
``outcomes``    : iterable of int/bool, 0 or 1, aligned with ``predictions``

The module is deliberately conservative: it raises ValueError on length
mismatch, on out-of-range probabilities, and on non-binary outcomes.  It
does not silently clamp — calibration metrics only mean something on
honest inputs.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import mean

__all__ = [
    "CalibrationReport",
    "calibration_report",
    "dce",
    "ece",
    "smooth_ece",
]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(predictions: Iterable[float], outcomes: Iterable[int]) -> tuple[list[float], list[int]]:
    preds = [float(p) for p in predictions]
    outs = [int(o) for o in outcomes]
    if len(preds) != len(outs):
        raise ValueError(
            f"predictions and outcomes length mismatch: {len(preds)} vs {len(outs)}"
        )
    if not preds:
        raise ValueError("at least one prediction is required")
    for p in preds:
        if not math.isfinite(p) or p < 0.0 or p > 1.0:
            raise ValueError(f"prediction out of range [0,1]: {p}")
    for o in outs:
        if o not in (0, 1):
            raise ValueError(f"outcome must be 0 or 1, got {o}")
    return preds, outs


# ---------------------------------------------------------------------------
# Classical binned ECE (kept as legacy reference)
# ---------------------------------------------------------------------------


def ece(predictions: Iterable[float], outcomes: Iterable[int], *, n_bins: int = 10) -> float:
    """Classical binned Expected Calibration Error.

    Bins predictions uniformly on [0, 1] and computes the weighted L1
    distance between mean predicted probability and empirical hit rate per
    non-empty bin.
    """

    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    preds, outs = _validate(predictions, outcomes)
    n = len(preds)
    edges = [i / n_bins for i in range(n_bins + 1)]
    total = 0.0
    for k in range(n_bins):
        lo, hi = edges[k], edges[k + 1]
        if k == n_bins - 1:
            members = [(p, o) for p, o in zip(preds, outs, strict=False) if lo <= p <= hi]
        else:
            members = [(p, o) for p, o in zip(preds, outs, strict=False) if lo <= p < hi]
        if not members:
            continue
        bin_mean_pred = mean(p for p, _ in members)
        bin_mean_out = mean(o for _, o in members)
        total += (len(members) / n) * abs(bin_mean_pred - bin_mean_out)
    return total


# ---------------------------------------------------------------------------
# Smooth ECE (Błasiok & Nakkiran 2023)
# ---------------------------------------------------------------------------


def _gaussian_kernel(distance: float, bandwidth: float) -> float:
    if bandwidth <= 0.0:
        raise ValueError("bandwidth must be positive")
    z = distance / bandwidth
    return math.exp(-0.5 * z * z) / (bandwidth * math.sqrt(2.0 * math.pi))


def _silverman_bandwidth(n: int) -> float:
    """Silverman's rule for [0,1]-supported predictions.

    ``h = 1.06 * sigma * n^(-1/5)`` clipped at sigma=0.25 (max for U[0,1]).
    The clip prevents the bandwidth from collapsing to 0 when the predictor
    is degenerate (all preds at the same value).
    """

    return max(1.06 * 0.25 * n ** (-1.0 / 5.0), 1e-3)


def smooth_ece(
    predictions: Iterable[float],
    outcomes: Iterable[int],
    *,
    bandwidth: float | None = None,
    n_grid: int = 101,
) -> float:
    """Smooth ECE (smECE) per Błasiok & Nakkiran 2023.

    Computes a kernel-smoothed reliability curve r̂(p) over a fixed grid on
    [0,1] and reports the empirical-density-weighted L1 distance between
    r̂(p) and p.  The kernel is a truncated Gaussian; ``bandwidth`` defaults
    to Silverman's rule.

    The metric is *consistent* (in the sense of Błasiok–Nakkiran §3): it
    does not depend on a bin grid, and it is robust to the pathological
    underestimation that classical binned ECE shows on small samples
    concentrated inside a single bin.
    """

    preds, outs = _validate(predictions, outcomes)
    n = len(preds)
    h = _silverman_bandwidth(n) if bandwidth is None else float(bandwidth)
    if h <= 0.0:
        raise ValueError("bandwidth must be positive")
    if n_grid < 2:
        raise ValueError("n_grid must be >= 2")

    grid = [i / (n_grid - 1) for i in range(n_grid)]
    total = 0.0
    total_weight = 0.0
    for g in grid:
        weights = [_gaussian_kernel(g - p, h) for p in preds]
        w_sum = sum(weights)
        if w_sum <= 0.0:
            continue
        r_hat = sum(w * o for w, o in zip(weights, outs, strict=False)) / w_sum
        total += w_sum * abs(r_hat - g)
        total_weight += w_sum
    if total_weight <= 0.0:
        return 0.0
    return total / total_weight


# ---------------------------------------------------------------------------
# Distance-to-calibration (Rossellini et al. 2025) — isotonic projection
# ---------------------------------------------------------------------------


def _pool_adjacent_violators(values: Sequence[float], weights: Sequence[float]) -> list[float]:
    """In-place PAV for monotone non-decreasing isotonic regression.

    Returns a list of length ``len(values)`` where index i holds the fitted
    isotonic value for the i-th input (assumed sorted by the regressor).
    """

    n = len(values)
    if n != len(weights):
        raise ValueError("values and weights length mismatch")
    # Use stack of (sum_weighted_value, sum_weight, length) blocks.
    stack: list[list[float]] = []  # each: [sum_wv, sum_w, length]
    for v, w in zip(values, weights, strict=False):
        block = [v * w, w, 1.0]
        while stack and stack[-1][0] / stack[-1][1] > block[0] / block[1]:
            top = stack.pop()
            block[0] += top[0]
            block[1] += top[1]
            block[2] += top[2]
        stack.append(block)
    fitted: list[float] = []
    for block in stack:
        mean_val = block[0] / block[1]
        fitted.extend([mean_val] * int(block[2]))
    return fitted


def dce(predictions: Iterable[float], outcomes: Iterable[int]) -> float:
    """Distance-to-calibration error (dCE) per Rossellini et al. 2025.

    Defined as the L1 distance between the empirical predictions and their
    isotonic projection onto the monotone-calibratable manifold.  Equals 0
    iff the predictor is *calibratable* (i.e. there exists a monotone
    transform that makes it perfectly calibrated on this sample); strictly
    positive otherwise.

    Implementation note: this is the upper-bound estimator from §4 of the
    paper.  Pool-Adjacent-Violators on (prediction, outcome) pairs sorted
    by prediction yields the isotonic regressor; reported value is the
    empirical-mean absolute deviation of predictions from that regressor.
    """

    preds, outs = _validate(predictions, outcomes)
    order = sorted(range(len(preds)), key=lambda i: preds[i])
    sorted_preds = [preds[i] for i in order]
    sorted_outs = [float(outs[i]) for i in order]
    weights = [1.0] * len(sorted_preds)
    isotonic = _pool_adjacent_violators(sorted_outs, weights)
    # Distance is mean |p - iso(p)| — the L1 projection cost.
    return sum(abs(p - i) for p, i in zip(sorted_preds, isotonic, strict=False)) / len(sorted_preds)


# ---------------------------------------------------------------------------
# Bundle reporter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationReport:
    n_samples: int
    ece: float
    smooth_ece: float
    dce: float


def calibration_report(
    predictions: Iterable[float],
    outcomes: Iterable[int],
    *,
    n_bins: int = 10,
    bandwidth: float | None = None,
) -> CalibrationReport:
    """Compute all three calibration metrics in one pass.

    Returns a frozen dataclass for downstream JSON serialisation.  The
    n_samples field lets the consumer apply the existing min-bucket rule
    (``insufficient`` flag is *not* set here — that is the dashboard's job).
    """

    preds, outs = _validate(predictions, outcomes)
    return CalibrationReport(
        n_samples=len(preds),
        ece=ece(preds, outs, n_bins=n_bins),
        smooth_ece=smooth_ece(preds, outs, bandwidth=bandwidth),
        dce=dce(preds, outs),
    )
