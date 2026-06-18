"""Pure-numpy metrics shared by trainers/evaluators.

Avoids any sklearn/scipy dependency so the ML pipeline can be exercised on
machines that only have ``numpy``.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

_EPS = 1e-15


def _as_arrays(y_true: Sequence[float], y_prob: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    yt = np.asarray(y_true, dtype=float)
    yp = np.asarray(y_prob, dtype=float)
    if yt.shape != yp.shape:
        raise ValueError(f"shape mismatch: {yt.shape} vs {yp.shape}")
    if yt.size == 0:
        raise ValueError("empty arrays")
    if not np.isfinite(yt).all():
        raise ValueError("y_true contains NaN or Inf")
    if not np.isfinite(yp).all():
        raise ValueError("y_prob contains NaN or Inf")
    return yt, yp


def brier_score(y_true: Sequence[float], y_prob: Sequence[float]) -> float:
    yt, yp = _as_arrays(y_true, y_prob)
    return float(np.mean((yp - yt) ** 2))


def log_loss(y_true: Sequence[float], y_prob: Sequence[float]) -> float:
    yt, yp = _as_arrays(y_true, y_prob)
    yp = np.clip(yp, _EPS, 1.0 - _EPS)
    return float(-np.mean(yt * np.log(yp) + (1.0 - yt) * np.log(1.0 - yp)))


def roc_auc(y_true: Sequence[float], y_score: Sequence[float]) -> float:
    """Mann-Whitney U formulation, ties broken by averaging ranks.

    Returns 0.5 if only one class is present (degenerate AUC).
    """
    yt, ys = _as_arrays(y_true, y_score)
    pos = yt > 0.5
    n_pos = int(pos.sum())
    n_neg = int(yt.size - n_pos)
    if n_pos == 0 or n_neg == 0:
        return 0.5
    order = np.argsort(ys, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, ys.size + 1)
    # average tied ranks
    sorted_scores = ys[order]
    i = 0
    while i < ys.size:
        j = i + 1
        while j < ys.size and sorted_scores[j] == sorted_scores[i]:
            j += 1
        if j - i > 1:
            avg = ranks[order[i:j]].mean()
            ranks[order[i:j]] = avg
        i = j
    sum_pos_ranks = ranks[pos].sum()
    auc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(auc)


def expected_calibration_error(
    y_true: Sequence[float],
    y_prob: Sequence[float],
    n_bins: int = 10,
) -> float:
    """ECE with equal-width bins on [0, 1]."""
    yt, yp = _as_arrays(y_true, y_prob)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = yt.size
    for k in range(n_bins):
        lo, hi = edges[k], edges[k + 1]
        mask = (yp >= lo) & (yp <= hi) if k == n_bins - 1 else (yp >= lo) & (yp < hi)
        bin_n = int(mask.sum())
        if bin_n == 0:
            continue
        avg_p = float(yp[mask].mean())
        avg_y = float(yt[mask].mean())
        ece += (bin_n / n) * abs(avg_p - avg_y)
    return float(ece)


def population_stability_index(
    expected: Sequence[float],
    actual: Sequence[float],
    n_bins: int = 10,
) -> float:
    """PSI between two probability distributions."""
    e = np.asarray(expected, dtype=float)
    a = np.asarray(actual, dtype=float)
    if e.size == 0 or a.size == 0:
        raise ValueError("empty arrays")
    if not np.isfinite(e).all():
        raise ValueError("expected contains NaN or Inf")
    if not np.isfinite(a).all():
        raise ValueError("actual contains NaN or Inf")
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    edges[-1] += 1e-9
    e_hist, _ = np.histogram(e, bins=edges)
    a_hist, _ = np.histogram(a, bins=edges)
    e_pct = np.maximum(e_hist / e.size, 1e-6)
    a_pct = np.maximum(a_hist / a.size, 1e-6)
    psi = float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))
    return psi


__all__ = [
    "brier_score",
    "expected_calibration_error",
    "log_loss",
    "population_stability_index",
    "roc_auc",
]
