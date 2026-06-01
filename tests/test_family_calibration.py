"""Tests for the EV-24 walk-forward calibration of raw scores -> probabilities."""

from __future__ import annotations

import random

from governance.family_calibration import (
    MIN_OOS_SAMPLES,
    _fit_logistic,
    _predict,
    walk_forward_calibration,
)


def test_fit_logistic_none_for_single_class() -> None:
    x = [float(i) for i in range(40)]
    y = [1.0] * 40  # one class only
    assert _fit_logistic(x, y) is None


def test_fit_logistic_none_for_too_few_points() -> None:
    assert _fit_logistic([0.0, 1.0], [0.0, 1.0]) is None


def test_fit_logistic_none_for_zero_variance_feature() -> None:
    x = [3.0] * 40
    y = [float(i % 2) for i in range(40)]
    assert _fit_logistic(x, y) is None


def test_fit_logistic_separates_a_separable_set() -> None:
    # Low feature -> class 0, high feature -> class 1.
    x = [0.0 + i * 0.01 for i in range(40)] + [5.0 + i * 0.01 for i in range(40)]
    y = [0.0] * 40 + [1.0] * 40
    model = _fit_logistic(x, y)
    assert model is not None
    lo, hi = _predict(model, [0.0, 5.0])
    assert lo < 0.5 < hi


def _separable_samples(n: int, *, bar: float = 900.0):
    rng = random.Random(11)
    base = 1_700_000_000.0
    scores: list[float] = []
    returns: list[float] = []
    anchor_ts: list[float] = []
    guard_end_ts: list[float] = []
    for i in range(n):
        anchor = base + i * 10 * bar
        win = i % 2 == 0
        scores.append((2.0 if win else 0.5) + rng.uniform(-0.15, 0.15))
        returns.append(0.01 if win else -0.01)
        anchor_ts.append(anchor)
        # label window ends well before the next event -> purge keeps train.
        guard_end_ts.append(anchor + 5 * bar)
    return scores, returns, anchor_ts, guard_end_ts


def test_walk_forward_returns_none_below_min_oos() -> None:
    s, r, a, g = _separable_samples(MIN_OOS_SAMPLES - 5)
    assert walk_forward_calibration(s, r, a, g) is None


def test_walk_forward_emits_valid_block_for_separable_data() -> None:
    s, r, a, g = _separable_samples(160)
    block = walk_forward_calibration(s, r, a, g)
    assert block is not None
    wf = block["walkforward"]
    probs, outcomes = wf["probabilities"], wf["outcomes"]
    assert len(probs) == len(outcomes) >= MIN_OOS_SAMPLES
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert all(o in (0.0, 1.0) for o in outcomes)
    # Out-of-sample Brier must beat the 0.25 coin-flip baseline on separable data.
    brier = sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs)
    assert brier < 0.25


def test_overlapping_label_purge_removes_leaking_train_events() -> None:
    """GAP 1: when every label window spans the whole series, the purge must
    drop ALL training events (none resolve before any test fold), so no fold
    can be fit and no block is produced -- proving the purge is time-based on
    the guard window, not a plain index split."""
    s, r, a, _g = _separable_samples(160)
    # Guard window of every event reaches past the last anchor -> total overlap.
    huge_guard = [max(a) + 1.0 for _ in a]
    assert walk_forward_calibration(s, r, a, huge_guard) is None

    # Same data, non-overlapping guard windows -> a block IS produced.
    tight_guard = [ts + 1.0 for ts in a]
    assert walk_forward_calibration(s, r, a, tight_guard) is not None
