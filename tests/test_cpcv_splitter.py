"""Tests for ``scripts/cpcv_splitter.py`` (Sprint C2 / T5)."""

from __future__ import annotations

from math import comb

import numpy as np
import pytest

from scripts.cpcv_splitter import CombinatorialPurgedSplitter, CPCVSplit

# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_groups": 1},
        {"k_test_groups": 0},
        {"n_groups": 4, "k_test_groups": 4},  # k must be < n_groups
        {"n_groups": 4, "k_test_groups": 5},
        {"purge_size": -1},
        {"embargo_size": -1},
    ],
)
def test_constructor_rejects_invalid_args(kwargs: dict) -> None:
    base = {"n_groups": 6, "k_test_groups": 2}
    base.update(kwargs)
    with pytest.raises(ValueError):
        CombinatorialPurgedSplitter(**base)


# ---------------------------------------------------------------------------
# Path counting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n_groups, k_test_groups, expected",
    [
        (6, 2, 15),  # Lopez de Prado canonical example
        (5, 1, 5),
        (10, 3, 120),
    ],
)
def test_n_paths_equals_binomial_coefficient(
    n_groups: int, k_test_groups: int, expected: int
) -> None:
    s = CombinatorialPurgedSplitter(n_groups=n_groups, k_test_groups=k_test_groups)
    assert s.n_paths() == expected
    assert expected == comb(n_groups, k_test_groups)


def test_split_yields_exactly_n_paths_folds() -> None:
    s = CombinatorialPurgedSplitter(n_groups=6, k_test_groups=2)
    folds = list(s.split(n_observations=120))
    assert len(folds) == s.n_paths() == 15


# ---------------------------------------------------------------------------
# Fold structure
# ---------------------------------------------------------------------------


def test_split_returns_cpcv_split_with_expected_shape() -> None:
    s = CombinatorialPurgedSplitter(n_groups=5, k_test_groups=2)
    folds = list(s.split(n_observations=100))
    f0 = folds[0]
    assert isinstance(f0, CPCVSplit)
    assert f0.fold_idx == 0
    assert len(f0.test_groups) == 2
    # Test set is union of 2 of the 5 groups → 40% of observations.
    assert len(f0.test_idx) == 40
    # Train + test cover every observation in this no-purge case.
    assert len(f0.train_idx) + len(f0.test_idx) == 100


def test_train_test_indices_are_disjoint_for_all_folds() -> None:
    s = CombinatorialPurgedSplitter(n_groups=6, k_test_groups=2)
    for f in s.split(n_observations=120):
        assert set(f.train_idx.tolist()).isdisjoint(set(f.test_idx.tolist()))


def test_test_groups_combination_uniqueness() -> None:
    s = CombinatorialPurgedSplitter(n_groups=6, k_test_groups=2)
    seen: set[tuple[int, ...]] = set()
    for f in s.split(n_observations=120):
        assert f.test_groups not in seen
        seen.add(f.test_groups)
    assert len(seen) == 15


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------


def test_split_raises_when_too_few_observations() -> None:
    s = CombinatorialPurgedSplitter(n_groups=6, k_test_groups=2)
    with pytest.raises(ValueError, match="need at least"):
        list(s.split(n_observations=5))


# ---------------------------------------------------------------------------
# Purging + embargo
# ---------------------------------------------------------------------------


def test_purging_removes_rows_around_test_groups() -> None:
    s = CombinatorialPurgedSplitter(
        n_groups=5, k_test_groups=1, purge_size=2, embargo_size=0
    )
    folds = list(s.split(n_observations=50))
    # Fold targeting group 1 → test = [10..19]; purge zone = [8,9] pre
    # and [20,21] post. Those must be absent from training.
    fold_g1 = next(f for f in folds if f.test_groups == (1,))
    train_set = set(fold_g1.train_idx.tolist())
    for purged in (8, 9, 20, 21):
        assert purged not in train_set
    # And the actual test rows are not in training either.
    for tested in range(10, 20):
        assert tested not in train_set


def test_embargo_extends_post_test_purge_only() -> None:
    s = CombinatorialPurgedSplitter(
        n_groups=5, k_test_groups=1, purge_size=1, embargo_size=3
    )
    folds = list(s.split(n_observations=50))
    fold_g1 = next(f for f in folds if f.test_groups == (1,))
    train_set = set(fold_g1.train_idx.tolist())
    # Pre-purge: only 1 row (index 9). Post-purge + embargo: 4 rows
    # (purge_size=1 plus embargo_size=3) → indices [20,21,22,23] absent.
    assert 9 not in train_set  # pre-purge row absent
    assert 8 in train_set  # only 1 row pre-purge
    for blocked in (20, 21, 22, 23):
        assert blocked not in train_set
    assert 24 in train_set  # immediately after embargo zone


def test_purge_around_first_group_clamps_at_zero() -> None:
    s = CombinatorialPurgedSplitter(
        n_groups=5, k_test_groups=1, purge_size=5, embargo_size=0
    )
    # Should not crash on group 0 even though pre-zone goes negative.
    folds = list(s.split(n_observations=50))
    fold_g0 = next(f for f in folds if f.test_groups == (0,))
    # Group 0 = [0..9], purge_size=5 → post zone [10..14] absent.
    train_set = set(fold_g0.train_idx.tolist())
    for blocked in range(10, 15):
        assert blocked not in train_set


def test_purge_around_last_group_clamps_at_n_minus_one() -> None:
    s = CombinatorialPurgedSplitter(
        n_groups=5, k_test_groups=1, purge_size=5, embargo_size=10
    )
    folds = list(s.split(n_observations=50))
    fold_last = next(f for f in folds if f.test_groups == (4,))
    train_set = set(fold_last.train_idx.tolist())
    # Group 4 = [40..49]. Pre-purge → [35..39] absent; post extends
    # past n_observations and is clamped, no negative indexing.
    for blocked in range(35, 40):
        assert blocked not in train_set
    # Train consists only of [0..34].
    assert max(train_set) == 34


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_splitter_is_deterministic() -> None:
    s1 = CombinatorialPurgedSplitter(
        n_groups=6, k_test_groups=2, purge_size=2, embargo_size=1
    )
    s2 = CombinatorialPurgedSplitter(
        n_groups=6, k_test_groups=2, purge_size=2, embargo_size=1
    )
    folds1 = list(s1.split(n_observations=120))
    folds2 = list(s2.split(n_observations=120))
    assert len(folds1) == len(folds2)
    for a, b in zip(folds1, folds2):
        assert a.test_groups == b.test_groups
        assert np.array_equal(a.train_idx, b.train_idx)
        assert np.array_equal(a.test_idx, b.test_idx)


# ---------------------------------------------------------------------------
# Property: every test row appears across the full path set
# ---------------------------------------------------------------------------


def test_every_observation_is_tested_at_least_once_across_paths() -> None:
    """A defining feature of CPCV: each observation belongs to at least
    one test fold across the combinatorial enumeration."""

    s = CombinatorialPurgedSplitter(n_groups=6, k_test_groups=2)
    n = 60
    seen: set[int] = set()
    for f in s.split(n_observations=n):
        seen.update(f.test_idx.tolist())
    assert seen == set(range(n))
