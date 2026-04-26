"""Walk-forward splitting with embargo (López de Prado).

Pure-numpy. No sklearn dependency.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Fold:
    train_idx: np.ndarray
    val_idx: np.ndarray


def walk_forward_splits(
    n_samples: int,
    n_folds: int = 5,
    embargo: int = 1,
    min_train: int | None = None,
) -> list[Fold]:
    """Generate ``n_folds`` walk-forward folds with an integer ``embargo``.

    Each fold uses an expanding training window followed by an ``embargo``-bar
    gap and then a contiguous validation window. The validation windows are
    disjoint and tile the tail of the series.
    """
    if n_samples < (n_folds + 1):
        raise ValueError(f"n_samples={n_samples} too small for n_folds={n_folds}")
    if embargo < 0:
        raise ValueError("embargo must be >= 0")
    val_size = max(1, n_samples // (n_folds + 1))
    folds: list[Fold] = []
    for k in range(n_folds):
        val_start = n_samples - (n_folds - k) * val_size
        val_end = val_start + val_size
        train_end = max(0, val_start - embargo)
        if min_train is not None and train_end < min_train:
            continue
        if train_end <= 0:
            continue
        train_idx = np.arange(0, train_end, dtype=np.int64)
        val_idx = np.arange(val_start, val_end, dtype=np.int64)
        folds.append(Fold(train_idx=train_idx, val_idx=val_idx))
    if not folds:
        raise ValueError("no folds produced; relax min_train or n_folds")
    return folds


__all__ = ["Fold", "walk_forward_splits"]
