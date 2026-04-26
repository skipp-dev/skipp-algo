"""Volatility features."""
from __future__ import annotations

from typing import Sequence

import numpy as np


def realized_volatility(close: Sequence[float], window: int = 20) -> np.ndarray:
    """Rolling realized volatility from log returns. Output aligned to input."""
    c = np.asarray(close, dtype=float)
    if c.size < 2:
        return np.zeros_like(c)
    log_ret = np.diff(np.log(np.maximum(c, 1e-12)), prepend=np.log(max(c[0], 1e-12)))
    out = np.zeros_like(c)
    for i in range(c.size):
        lo = max(0, i - window + 1)
        seg = log_ret[lo : i + 1]
        out[i] = float(np.std(seg, ddof=0)) if seg.size > 1 else 0.0
    return out


def garman_klass_volatility(
    high: Sequence[float],
    low: Sequence[float],
    open_: Sequence[float],
    close: Sequence[float],
) -> np.ndarray:
    """Per-bar Garman-Klass variance (Andersen-Bollerslev 1998).

    GK = 0.5 * (ln(H/L))^2 - (2*ln(2) - 1) * (ln(C/O))^2
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    o = np.asarray(open_, dtype=float)
    c = np.asarray(close, dtype=float)
    h = np.maximum(h, 1e-12)
    l = np.maximum(l, 1e-12)
    o = np.maximum(o, 1e-12)
    c = np.maximum(c, 1e-12)
    return 0.5 * np.log(h / l) ** 2 - (2.0 * np.log(2.0) - 1.0) * np.log(c / o) ** 2


def parkinson_volatility(high: Sequence[float], low: Sequence[float]) -> np.ndarray:
    """Per-bar Parkinson variance: (ln(H/L))^2 / (4 * ln(2))."""
    h = np.maximum(np.asarray(high, dtype=float), 1e-12)
    l = np.maximum(np.asarray(low, dtype=float), 1e-12)
    return np.log(h / l) ** 2 / (4.0 * np.log(2.0))


__all__ = ["realized_volatility", "garman_klass_volatility", "parkinson_volatility"]
