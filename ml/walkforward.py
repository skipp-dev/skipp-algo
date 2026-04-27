"""Walk-forward splitting with embargo (López de Prado).

Pure-numpy. No sklearn dependency.

Sprint C2.1 hardening:
- ``scheme: Literal["rolling", "anchored", "expanding"]`` (anchored == expanding)
- ``embargo_bars`` (also exposed as legacy ``embargo``)
- Per-sample ``outcome_horizon`` purging removes any training sample whose
  label-resolution bar falls inside the validation window — direct
  Lopez-de-Prado leakage guard for overlapping setup outcomes.
- ``WalkForwardConfig`` dataclass for declarative use from PromotionGate /
  X3 run-manifest.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

Scheme = Literal["rolling", "anchored", "expanding"]


@dataclass(frozen=True)
class Fold:
    train_idx: np.ndarray
    val_idx: np.ndarray


@dataclass(frozen=True)
class WalkForwardConfig:
    """Declarative walk-forward configuration.

    ``scheme="anchored"`` is an alias for ``"expanding"``.
    ``embargo_bars`` recommended default = ``2 * max_event_horizon``.
    """

    scheme: Scheme = "expanding"
    n_folds: int = 5
    embargo_bars: int = 1
    min_train: int | None = None
    train_size: int | None = None  # required for scheme="rolling"

    def __post_init__(self) -> None:
        if self.scheme not in ("rolling", "anchored", "expanding"):
            raise ValueError(f"scheme must be rolling|anchored|expanding, got {self.scheme!r}")
        if self.n_folds < 1:
            raise ValueError("n_folds must be >= 1")
        if self.embargo_bars < 0:
            raise ValueError("embargo_bars must be >= 0")
        if self.scheme == "rolling" and (self.train_size is None or self.train_size < 1):
            raise ValueError("scheme='rolling' requires train_size >= 1")


def walk_forward_splits(
    n_samples: int,
    n_folds: int = 5,
    embargo: int = 1,
    min_train: int | None = None,
    *,
    scheme: Scheme = "expanding",
    train_size: int | None = None,
    outcome_horizon: np.ndarray | int | None = None,
) -> list[Fold]:
    """Generate ``n_folds`` walk-forward folds.

    Parameters
    ----------
    scheme:
        ``"expanding"`` (default) and ``"anchored"`` keep all earlier
        samples in train. ``"rolling"`` uses a fixed window of length
        ``train_size``.
    embargo:
        Number of bars dropped between train and val (anti-autocorrelation).
    outcome_horizon:
        Per-sample horizon (in bars) until the label is fully resolved. When
        provided, any training sample with ``i + horizon[i] >= val_start`` is
        purged. Either an int (constant horizon) or a 1-D array length
        ``n_samples``. ``None`` keeps the legacy behaviour.
    """
    if n_folds < 1:
        raise ValueError(f"n_folds must be >= 1, got {n_folds}")
    if n_samples < (n_folds + 1):
        raise ValueError(f"n_samples={n_samples} too small for n_folds={n_folds}")
    if embargo < 0:
        raise ValueError("embargo must be >= 0")
    if scheme not in ("rolling", "anchored", "expanding"):
        raise ValueError(f"scheme must be rolling|anchored|expanding, got {scheme!r}")
    if scheme == "rolling" and (train_size is None or train_size < 1):
        raise ValueError("scheme='rolling' requires train_size >= 1")

    horizons: np.ndarray | None
    if outcome_horizon is None:
        horizons = None
    elif np.isscalar(outcome_horizon):
        scalar = int(outcome_horizon)  # type: ignore[arg-type]
        if scalar < 0:
            raise ValueError("outcome_horizon must be >= 0")
        horizons = np.full(n_samples, scalar, dtype=np.int64)
    else:
        horizons = np.asarray(outcome_horizon, dtype=np.int64).ravel()
        if horizons.size != n_samples:
            raise ValueError(
                f"outcome_horizon length {horizons.size} != n_samples {n_samples}"
            )
        if np.any(horizons < 0):
            raise ValueError("outcome_horizon entries must be >= 0")

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

        if scheme == "rolling":
            if train_size is None:  # narrow for type-checker; production guard
                raise RuntimeError("rolling scheme requires train_size")
            train_start = max(0, train_end - train_size)
        else:  # expanding / anchored
            train_start = 0

        train_idx = np.arange(train_start, train_end, dtype=np.int64)

        if horizons is not None and train_idx.size > 0:
            # Drop training samples whose label horizon spills into val.
            resolution = train_idx + horizons[train_idx]
            keep = resolution < val_start
            train_idx = train_idx[keep]

        val_idx = np.arange(val_start, val_end, dtype=np.int64)
        folds.append(Fold(train_idx=train_idx, val_idx=val_idx))
    if not folds:
        raise ValueError("no folds produced; relax min_train or n_folds")
    return folds


def walk_forward_from_config(
    n_samples: int,
    config: WalkForwardConfig,
    *,
    outcome_horizon: np.ndarray | int | None = None,
) -> list[Fold]:
    """Convenience: build folds from a :class:`WalkForwardConfig`."""

    return walk_forward_splits(
        n_samples,
        n_folds=config.n_folds,
        embargo=config.embargo_bars,
        min_train=config.min_train,
        scheme=config.scheme,
        train_size=config.train_size,
        outcome_horizon=outcome_horizon,
    )


__all__ = [
    "Fold",
    "Scheme",
    "WalkForwardConfig",
    "walk_forward_from_config",
    "walk_forward_splits",
]
