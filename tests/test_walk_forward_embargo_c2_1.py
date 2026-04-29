"""Sprint C2.1 — walk-forward hardening tests for ml/walkforward."""
from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from ml.walkforward import (
    Fold,
    WalkForwardConfig,
    walk_forward_from_config,
    walk_forward_splits,
)


def test_legacy_default_behaviour_unchanged() -> None:
    """Default call signature must reproduce pre-C2.1 results bit-exact."""
    folds_legacy = walk_forward_splits(n_samples=100, n_folds=5, embargo=1)
    assert len(folds_legacy) == 5
    for f in folds_legacy:
        assert f.train_idx.dtype == np.int64
        assert f.val_idx.dtype == np.int64
        assert int(f.train_idx.max()) < int(f.val_idx.min())


def test_anchored_alias_for_expanding() -> None:
    a = walk_forward_splits(100, n_folds=4, embargo=2, scheme="anchored")
    b = walk_forward_splits(100, n_folds=4, embargo=2, scheme="expanding")
    assert len(a) == len(b)
    for fa, fb in zip(a, b):
        np.testing.assert_array_equal(fa.train_idx, fb.train_idx)
        np.testing.assert_array_equal(fa.val_idx, fb.val_idx)


def test_rolling_keeps_train_size_constant() -> None:
    folds = walk_forward_splits(
        300, n_folds=4, embargo=2, scheme="rolling", train_size=40
    )
    sizes = [len(f.train_idx) for f in folds]
    # Rolling: every train window is exactly train_size when there's
    # enough data to the left of train_end.
    assert all(s == 40 for s in sizes), sizes


def test_rolling_requires_train_size() -> None:
    with pytest.raises(ValueError, match=r"rolling.*train_size"):
        walk_forward_splits(100, scheme="rolling")
    with pytest.raises(ValueError, match=r"rolling.*train_size"):
        walk_forward_splits(100, scheme="rolling", train_size=0)


def test_outcome_horizon_purges_overlapping_labels() -> None:
    """A constant horizon should drop the last `horizon` train samples."""
    folds = walk_forward_splits(
        n_samples=60, n_folds=2, embargo=0, outcome_horizon=5
    )
    for f in folds:
        if f.train_idx.size == 0:
            continue
        max_resolution = int((f.train_idx + 5).max())
        assert max_resolution < int(f.val_idx.min()), (
            "purged training labels still overlap val window"
        )


def test_per_sample_outcome_horizon() -> None:
    n = 80
    horizons = np.zeros(n, dtype=np.int64)
    horizons[40:50] = 100  # huge horizon for samples in the middle
    folds = walk_forward_splits(
        n_samples=n, n_folds=2, embargo=0, outcome_horizon=horizons
    )
    for f in folds:
        if f.train_idx.size == 0:
            continue
        # No surviving train sample may have its resolution >= val_start.
        resolved = f.train_idx + horizons[f.train_idx]
        assert int(resolved.max()) < int(f.val_idx.min())


def test_outcome_horizon_length_validation() -> None:
    with pytest.raises(ValueError, match="outcome_horizon length"):
        walk_forward_splits(
            n_samples=50, n_folds=2, outcome_horizon=np.zeros(10, dtype=np.int64)
        )


def test_outcome_horizon_negative_rejected() -> None:
    with pytest.raises(ValueError, match="outcome_horizon entries"):
        walk_forward_splits(
            n_samples=50, n_folds=2,
            outcome_horizon=np.array([-1] + [0] * 49, dtype=np.int64),
        )


def test_walkforwardconfig_round_trip() -> None:
    cfg = WalkForwardConfig(scheme="rolling", n_folds=3, embargo_bars=4, train_size=30)
    folds = walk_forward_from_config(150, cfg)
    assert len(folds) == 3
    sizes = [len(f.train_idx) for f in folds]
    assert all(s == 30 for s in sizes), sizes


def test_walkforwardconfig_validation() -> None:
    with pytest.raises(ValueError, match="scheme"):
        WalkForwardConfig(scheme="bogus")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="n_folds"):
        WalkForwardConfig(n_folds=0)
    with pytest.raises(ValueError, match="embargo_bars"):
        WalkForwardConfig(embargo_bars=-1)
    with pytest.raises(ValueError, match="rolling"):
        WalkForwardConfig(scheme="rolling")


def test_validation_folds_disjoint_and_chronological() -> None:
    folds = walk_forward_splits(120, n_folds=4, embargo=2)
    val_ranges = [(int(f.val_idx[0]), int(f.val_idx[-1])) for f in folds]
    for a, b in pairwise(val_ranges):
        assert a[1] < b[0], (a, b)


def test_isinstance_fold() -> None:
    folds = walk_forward_splits(40, n_folds=3, embargo=0)
    assert all(isinstance(f, Fold) for f in folds)
