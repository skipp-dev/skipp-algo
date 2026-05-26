"""Property tests for ``ml.walkforward.walk_forward_splits`` boundary invariants.

Guards the López-de-Prado embargo + per-sample horizon purging contract that
``ml/walkforward.py`` relies on. The split function is consumed transitively by
``ml/training/base.py`` and the PromotionGate pipeline, so a regression here
would only surface in family-smoke tests far downstream.

Invariants checked across randomized configurations:

1. ``train_idx`` and ``val_idx`` are disjoint.
2. If ``train_idx`` is non-empty: ``max(train_idx) + embargo < min(val_idx)``.
3. With ``outcome_horizon``: ``max(train_idx + horizon[train_idx]) < min(val_idx)``
   for every training sample (no label resolution leaking into val).
4. ``val_idx`` ranges are forward-only and non-overlapping across folds.
5. ``scheme='rolling'`` respects ``train_size``.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from ml.walkforward import (
    WalkForwardConfig,
    walk_forward_from_config,
    walk_forward_splits,
)


def _rng_configs(seed: int, count: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    configs: list[dict[str, object]] = []
    schemes = ("expanding", "anchored", "rolling")
    for _ in range(count):
        scheme = rng.choice(schemes)
        n_folds = rng.randint(2, 6)
        n_samples = rng.randint(n_folds * 8, n_folds * 40)
        embargo = rng.randint(0, 5)
        train_size = rng.randint(n_folds, n_samples) if scheme == "rolling" else None
        configs.append(
            {
                "n_samples": n_samples,
                "n_folds": n_folds,
                "embargo": embargo,
                "scheme": scheme,
                "train_size": train_size,
            }
        )
    return configs


@pytest.mark.parametrize("cfg", _rng_configs(seed=2026, count=40))
def test_train_val_disjoint_and_embargo_respected(cfg: dict[str, object]) -> None:
    folds = walk_forward_splits(
        n_samples=int(cfg["n_samples"]),
        n_folds=int(cfg["n_folds"]),
        embargo=int(cfg["embargo"]),
        scheme=cfg["scheme"],  # type: ignore[arg-type]
        train_size=cfg["train_size"],  # type: ignore[arg-type]
    )
    assert folds, "expected at least one fold"
    embargo = int(cfg["embargo"])
    for fold in folds:
        if fold.train_idx.size == 0:
            continue
        assert np.intersect1d(fold.train_idx, fold.val_idx).size == 0
        assert fold.train_idx.max() + embargo < fold.val_idx.min(), (
            f"embargo violated: max_train={fold.train_idx.max()} "
            f"embargo={embargo} min_val={fold.val_idx.min()}"
        )


@pytest.mark.parametrize("cfg", _rng_configs(seed=4242, count=30))
def test_outcome_horizon_purges_overlapping_labels(cfg: dict[str, object]) -> None:
    n_samples = int(cfg["n_samples"])
    horizon = np.random.default_rng(seed=int(cfg["n_folds"])).integers(
        low=0, high=10, size=n_samples
    )
    folds = walk_forward_splits(
        n_samples=n_samples,
        n_folds=int(cfg["n_folds"]),
        embargo=int(cfg["embargo"]),
        scheme=cfg["scheme"],  # type: ignore[arg-type]
        train_size=cfg["train_size"],  # type: ignore[arg-type]
        outcome_horizon=horizon,
    )
    for fold in folds:
        if fold.train_idx.size == 0:
            continue
        resolution = fold.train_idx + horizon[fold.train_idx]
        assert resolution.max() < fold.val_idx.min(), (
            f"purge violated: max_resolution={resolution.max()} "
            f"min_val={fold.val_idx.min()}"
        )


def test_val_windows_are_forward_only_and_non_overlapping() -> None:
    folds = walk_forward_splits(
        n_samples=200, n_folds=5, embargo=2, scheme="expanding"
    )
    val_starts = [int(f.val_idx.min()) for f in folds]
    val_ends = [int(f.val_idx.max()) for f in folds]
    assert val_starts == sorted(val_starts), "val windows must move forward"
    for prev_end, next_start in zip(val_ends, val_starts[1:]):
        assert next_start > prev_end, "val windows must not overlap"


def test_rolling_scheme_respects_train_size() -> None:
    train_size = 25
    folds = walk_forward_splits(
        n_samples=200,
        n_folds=4,
        embargo=1,
        scheme="rolling",
        train_size=train_size,
    )
    for fold in folds:
        assert fold.train_idx.size <= train_size


def test_walk_forward_from_config_matches_direct_call() -> None:
    cfg = WalkForwardConfig(
        scheme="rolling", n_folds=4, embargo_bars=3, train_size=30
    )
    a = walk_forward_from_config(n_samples=200, config=cfg)
    b = walk_forward_splits(
        n_samples=200,
        n_folds=4,
        embargo=3,
        scheme="rolling",
        train_size=30,
    )
    assert len(a) == len(b)
    for fa, fb in zip(a, b):
        assert np.array_equal(fa.train_idx, fb.train_idx)
        assert np.array_equal(fa.val_idx, fb.val_idx)


def test_negative_embargo_rejected() -> None:
    with pytest.raises(ValueError, match="embargo"):
        walk_forward_splits(n_samples=100, n_folds=4, embargo=-1)


def test_rolling_without_train_size_rejected() -> None:
    with pytest.raises(ValueError, match="train_size"):
        walk_forward_splits(n_samples=100, n_folds=4, scheme="rolling")
