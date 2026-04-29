"""Tests for ``scripts/walk_forward.py`` (Sprint C2 / T2)."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.walk_forward import WalkForwardSplit, WalkForwardSplitter


def _ts(n: int, *, start: int = 0, step: int = 1) -> np.ndarray:
    """Generate monotonically increasing integer timestamps."""

    return np.arange(start, start + n * step, step, dtype=np.int64)


# ---------------------------------------------------------------------------
# Construction validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"window_type": "diagonal"},
        {"n_splits": 0},
        {"train_size": 0},
        {"test_size": 0},
        {"purge_size": -1},
        {"embargo_size": -1},
    ],
)
def test_constructor_rejects_invalid_args(kwargs: dict) -> None:
    base = {"window_type": "rolling", "n_splits": 3, "train_size": 60, "test_size": 15}
    base.update(kwargs)
    with pytest.raises(ValueError):
        WalkForwardSplitter(**base)


def test_required_observations_matches_train_plus_n_splits_test() -> None:
    s = WalkForwardSplitter(n_splits=4, train_size=100, test_size=20)
    assert s.required_observations() == 100 + 4 * 20


# ---------------------------------------------------------------------------
# Basic chronology + counts
# ---------------------------------------------------------------------------


def test_rolling_split_yields_n_splits_disjoint_test_folds() -> None:
    s = WalkForwardSplitter(window_type="rolling", n_splits=4, train_size=50, test_size=10)
    folds = list(s.split(_ts(50 + 4 * 10)))
    assert len(folds) == 4
    seen: set[int] = set()
    last_test_end = -1
    for f in folds:
        assert isinstance(f, WalkForwardSplit)
        assert len(f.test_idx) == 10
        # Tests are strictly chronological and non-overlapping.
        assert int(f.test_idx[0]) > last_test_end
        last_test_end = int(f.test_idx[-1])
        # No test index re-used across folds.
        for i in f.test_idx.tolist():
            assert i not in seen
            seen.add(i)


def test_rolling_train_window_is_fixed_size() -> None:
    s = WalkForwardSplitter(window_type="rolling", n_splits=3, train_size=40, test_size=10)
    folds = list(s.split(_ts(40 + 3 * 10)))
    for f in folds:
        assert len(f.train_idx) == 40


def test_anchored_train_window_grows_each_fold() -> None:
    s = WalkForwardSplitter(window_type="anchored", n_splits=3, train_size=40, test_size=10)
    folds = list(s.split(_ts(40 + 3 * 10)))
    sizes = [len(f.train_idx) for f in folds]
    assert sizes == [40, 50, 60]


def test_train_and_test_indices_never_overlap() -> None:
    s = WalkForwardSplitter(window_type="rolling", n_splits=3, train_size=30, test_size=10)
    for f in s.split(_ts(30 + 3 * 10)):
        assert set(f.train_idx.tolist()).isdisjoint(set(f.test_idx.tolist()))


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------


def test_split_raises_when_too_few_observations() -> None:
    s = WalkForwardSplitter(n_splits=3, train_size=50, test_size=10)
    with pytest.raises(ValueError, match="need at least"):
        list(s.split(_ts(50 + 3 * 10 - 1)))


def test_split_rejects_non_monotonic_timestamps() -> None:
    s = WalkForwardSplitter(n_splits=2, train_size=10, test_size=5)
    bad = np.array([1, 2, 3, 5, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])
    with pytest.raises(ValueError, match="monotonically"):
        list(s.split(bad))


def test_empty_timestamps_yields_nothing() -> None:
    s = WalkForwardSplitter(n_splits=2, train_size=10, test_size=5)
    assert list(s.split(np.array([], dtype=np.int64))) == []


# ---------------------------------------------------------------------------
# Purging (index-based + exit-timestamp-based)
# ---------------------------------------------------------------------------


def test_index_purge_drops_immediate_pre_test_rows_from_training() -> None:
    s = WalkForwardSplitter(
        window_type="rolling", n_splits=2, train_size=20, test_size=5, purge_size=3
    )
    folds = list(s.split(_ts(20 + 2 * 5)))
    # Each train window should now be 17 rows, not 20.
    for f in folds:
        assert len(f.train_idx) == 17
        # And the dropped rows are exactly those immediately preceding test.
        assert int(f.train_idx[-1]) == int(f.test_idx[0]) - 1 - 3


def test_exit_purging_removes_training_trades_overlapping_test_window() -> None:
    """Trades whose exit lands inside the test window must be purged."""

    n = 30
    entries = _ts(n)
    exits = entries.copy()
    # Trade #19's exit slips into the next fold's test window.
    exits[19] = entries[22]

    s = WalkForwardSplitter(
        window_type="rolling", n_splits=2, train_size=20, test_size=5, purge_size=0
    )
    folds = list(s.split(entries, exit_timestamps=exits))
    # Fold 0 test = [20..24]. Train trade 19's exit == entries[22] → purged.
    fold0 = folds[0]
    assert 19 not in fold0.train_idx.tolist()
    # Trades whose exit is strictly before test_t0 must be kept.
    assert 18 in fold0.train_idx.tolist()


def test_exit_timestamps_length_must_match() -> None:
    s = WalkForwardSplitter(n_splits=2, train_size=10, test_size=5)
    with pytest.raises(ValueError, match="length"):
        list(s.split(_ts(20), exit_timestamps=_ts(19)))


# ---------------------------------------------------------------------------
# Embargo
# ---------------------------------------------------------------------------


def test_embargo_excludes_post_test_rows_from_anchored_future_training() -> None:
    s = WalkForwardSplitter(
        window_type="anchored",
        n_splits=3,
        train_size=20,
        test_size=5,
        embargo_size=2,
    )
    folds = list(s.split(_ts(20 + 3 * 5)))
    # Fold 1: test = [25..29]. Earlier fold 0 test ended at 24, embargo
    # blocks [25,26]. But those are *test indices* of fold 0, already
    # not in train set anyway — the embargo guards the *gap* between
    # fold 0 test end and the start of any later training set.
    # For fold 2: train should NOT include indices 25 or 26 (embargo
    # of fold 0) nor 30 or 31 (embargo of fold 1).
    fold2 = folds[2]
    train_set = set(fold2.train_idx.tolist())
    # Fold 1 test = [25..29], embargo [30,31] — those must be absent.
    assert 30 not in train_set
    assert 31 not in train_set


def test_rolling_embargo_shifts_train_start_back() -> None:
    s = WalkForwardSplitter(
        window_type="rolling",
        n_splits=3,
        train_size=20,
        test_size=5,
        embargo_size=2,
    )
    folds = list(s.split(_ts(20 + 3 * 5)))
    # Each successive rolling window shifts back by `embargo_size` to
    # avoid pulling embargoed observations into the new train set.
    for f_idx, f in enumerate(folds):
        if f_idx == 0:
            assert int(f.train_idx[0]) == 0
        else:
            # train_start = test_start - train_size - fold_idx*embargo_size
            test_start = int(f.test_idx[0])
            expected_start = max(0, test_start - 20 - f_idx * 2)
            assert int(f.train_idx[0]) == expected_start


# ---------------------------------------------------------------------------
# Determinism / property
# ---------------------------------------------------------------------------


def test_splitter_is_deterministic() -> None:
    s1 = WalkForwardSplitter(n_splits=4, train_size=30, test_size=10, purge_size=2, embargo_size=1)
    s2 = WalkForwardSplitter(n_splits=4, train_size=30, test_size=10, purge_size=2, embargo_size=1)
    folds1 = list(s1.split(_ts(80)))
    folds2 = list(s2.split(_ts(80)))
    assert len(folds1) == len(folds2)
    for a, b in zip(folds1, folds2, strict=False):
        assert a.fold_idx == b.fold_idx
        assert np.array_equal(a.train_idx, b.train_idx)
        assert np.array_equal(a.test_idx, b.test_idx)


@pytest.mark.parametrize("seed", list(range(20)))
def test_property_no_train_test_overlap_random_configs(seed: int) -> None:
    rng = np.random.default_rng(seed)
    n_splits = int(rng.integers(2, 6))
    train_size = int(rng.integers(20, 60))
    test_size = int(rng.integers(5, 15))
    purge_size = int(rng.integers(0, 5))
    embargo_size = int(rng.integers(0, 5))
    n = train_size + n_splits * test_size + 5

    for window in ("rolling", "anchored"):
        s = WalkForwardSplitter(
            window_type=window,
            n_splits=n_splits,
            train_size=train_size,
            test_size=test_size,
            purge_size=purge_size,
            embargo_size=embargo_size,
        )
        for f in s.split(_ts(n)):
            train_set = set(f.train_idx.tolist())
            test_set = set(f.test_idx.tolist())
            assert train_set.isdisjoint(test_set)
            # Purge guarantees no train index lands in the
            # `purge_size` rows immediately before the test fold.
            if purge_size > 0 and train_set:
                test_start = int(f.test_idx[0])
                purged_zone = set(range(test_start - purge_size, test_start))
                assert train_set.isdisjoint(purged_zone)
