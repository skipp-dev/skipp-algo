"""Fractional differentiation (López de Prado 2018, ch. 5).

Fixed-width window fractional differentiation (FFD): make a series
stationary while preserving the maximum amount of memory. Unlike an
integer first difference (``d = 1``), a fractional order ``0 < d < 1``
removes only as much memory as necessary to reach stationarity, leaving
predictive long-memory structure that an integer difference would
destroy.

Pure-numpy, O(n * width). No pandas, no heavy deps.
"""
from __future__ import annotations

import numpy as np
import numpy.typing as npt


def ffd_weights(d: float, threshold: float = 1e-5, max_width: int = 10_000) -> np.ndarray:
    """Fixed-width FFD weight vector for differentiation order ``d``.

    Weights follow the binomial recursion ``w_k = -w_{k-1} * (d - k + 1) / k``
    with ``w_0 = 1``. The series is truncated once ``|w_k| < threshold`` so
    the convolution window has a fixed, finite width.

    Returned ordering is oldest-to-newest (``w[-1]`` multiplies the current
    observation), ready for a dot product against a trailing window.
    """
    if d < 0.0:
        raise ValueError("d must be >= 0")
    if threshold <= 0.0:
        raise ValueError("threshold must be positive")
    if max_width < 1:
        raise ValueError("max_width must be >= 1")
    weights = [1.0]
    k = 1
    while k < max_width:
        w_k = -weights[-1] * (d - k + 1.0) / k
        if abs(w_k) < threshold:
            break
        weights.append(w_k)
        k += 1
    return np.asarray(weights[::-1], dtype=float)


def frac_diff_ffd(
    series: npt.ArrayLike,
    d: float,
    *,
    threshold: float = 1e-5,
    max_width: int = 10_000,
) -> np.ndarray:
    """Fixed-width fractionally differentiated series, aligned to input.

    The first ``width - 1`` positions lack a full window and are returned as
    ``nan`` (insufficient history), matching the López de Prado convention of
    dropping the warm-up region rather than back-filling it with biased
    partial windows. Downstream consumers should mask ``nan`` before use.

    - ``d == 0`` reproduces the input (identity).
    - ``d == 1`` reproduces the first difference on the valid region.
    """
    x = np.asarray(series, dtype=float)
    weights = ffd_weights(d, threshold=threshold, max_width=max_width)
    width = weights.size
    out = np.full(x.shape, np.nan, dtype=float)
    if x.size < width:
        return out
    for i in range(width - 1, x.size):
        window = x[i - width + 1 : i + 1]
        out[i] = float(np.dot(weights, window))
    return out


__all__ = ["ffd_weights", "frac_diff_ffd"]
