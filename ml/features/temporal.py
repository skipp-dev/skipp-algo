"""Temporal feature encodings."""
from __future__ import annotations

from typing import Sequence

import numpy as np


def cyclical_encoding(values: Sequence[float], period: float) -> np.ndarray:
    """Sin/cos encoding of a periodic value (e.g. minute of day, day of week).

    Returns shape (n, 2) where column 0 is sin and column 1 is cos.
    """
    v = np.asarray(values, dtype=float)
    if period <= 0:
        raise ValueError("period must be positive")
    angle = 2.0 * np.pi * v / period
    return np.stack([np.sin(angle), np.cos(angle)], axis=1)


def session_marker(
    minute_of_day: Sequence[int],
    pre_open: int = 540,   # 09:00
    open_: int = 570,       # 09:30
    close: int = 960,       # 16:00
    after: int = 1020,      # 17:00
) -> np.ndarray:
    """Categorical session bucket: 0=overnight, 1=pre, 2=regular, 3=after."""
    m = np.asarray(minute_of_day, dtype=int)
    out = np.zeros_like(m, dtype=int)
    out[(m >= pre_open) & (m < open_)] = 1
    out[(m >= open_) & (m < close)] = 2
    out[(m >= close) & (m < after)] = 3
    return out


__all__ = ["cyclical_encoding", "session_marker"]
