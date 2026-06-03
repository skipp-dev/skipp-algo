"""Tests for the EV-24 walk-forward calibration of raw scores -> probabilities."""

from __future__ import annotations

import random

from governance.family_calibration import (
    CONFORMAL_MIN_SIDE,
    LIVE_TAIL_MIN_SAMPLES,
    MIN_OOS_SAMPLES,
    PSI_TREND_MIN_WINDOWS,
    _fit_logistic,
    _predict,
    partition_conformal,
    partition_live_tail,
    walk_forward_calibration,
    walk_forward_psi_trend,
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


# ---------------------------------------------------------------------------
# ADR-0017 / EV-25: live-incubation surrogate (partition_live_tail).
# ---------------------------------------------------------------------------


def _pooled_block(n: int) -> dict[str, dict[str, list[float]]]:
    """A synthetic pooled walk-forward block with ``n`` chronological pairs.

    The probabilities ramp 0..1 so the live tail (the last entries) is the
    distinct, most-recent slice -- this lets the split math be asserted exactly.
    """
    probs = [i / (n - 1) for i in range(n)]
    outcomes = [float(i % 2) for i in range(n)]
    return {"walkforward": {"probabilities": probs, "outcomes": outcomes}}


def test_partition_live_tail_splits_recent_tail_as_live() -> None:
    n = LIVE_TAIL_MIN_SAMPLES + MIN_OOS_SAMPLES + 7
    block = _pooled_block(n)
    split = partition_live_tail(block)
    assert split is not None
    wf = split["walkforward"]
    live = split["live"]
    # Live holds exactly the LIVE_TAIL_MIN_SAMPLES most-recent (highest) pairs.
    assert len(live["probabilities"]) == LIVE_TAIL_MIN_SAMPLES
    assert len(wf["probabilities"]) == n - LIVE_TAIL_MIN_SAMPLES
    cut = n - LIVE_TAIL_MIN_SAMPLES
    assert live["probabilities"] == block["walkforward"]["probabilities"][cut:]
    assert wf["probabilities"] == block["walkforward"]["probabilities"][:cut]
    assert live["outcomes"] == block["walkforward"]["outcomes"][cut:]
    # No pair is lost or duplicated across the split.
    assert len(wf["probabilities"]) + len(live["probabilities"]) == n


def test_partition_live_tail_none_when_pool_too_small() -> None:
    # One pair short of the combined floor -> no split, caller keeps full pool.
    n = LIVE_TAIL_MIN_SAMPLES + MIN_OOS_SAMPLES - 1
    assert partition_live_tail(_pooled_block(n)) is None


def test_partition_live_tail_keeps_walkforward_above_oos_floor() -> None:
    n = LIVE_TAIL_MIN_SAMPLES + MIN_OOS_SAMPLES
    split = partition_live_tail(_pooled_block(n))
    assert split is not None
    assert len(split["walkforward"]["probabilities"]) >= MIN_OOS_SAMPLES


def test_partition_live_tail_none_for_missing_walkforward() -> None:
    assert partition_live_tail({}) is None


# ---------------------------------------------------------------------------
# ADR-0018 / EV-26: split-conformal coverage (partition_conformal).
# ---------------------------------------------------------------------------


def test_partition_conformal_splits_pool_into_calibration_and_test() -> None:
    n = 2 * CONFORMAL_MIN_SIDE + 11
    block = _pooled_block(n)
    conf = partition_conformal(block)
    assert conf is not None
    assert 0.0 < conf["alpha"] < 1.0
    cal = conf["calibration"]
    test = conf["test"]
    cut = int(n * 0.5)
    # Earlier half calibrates, later half is the held-out coverage test.
    assert cal["probabilities"] == block["walkforward"]["probabilities"][:cut]
    assert test["probabilities"] == block["walkforward"]["probabilities"][cut:]
    assert cal["outcomes"] == block["walkforward"]["outcomes"][:cut]
    # No pair is lost or duplicated across the split.
    assert len(cal["probabilities"]) + len(test["probabilities"]) == n


def test_partition_conformal_both_sides_clear_min_side() -> None:
    n = 2 * CONFORMAL_MIN_SIDE
    conf = partition_conformal(_pooled_block(n))
    assert conf is not None
    assert len(conf["calibration"]["probabilities"]) >= CONFORMAL_MIN_SIDE
    assert len(conf["test"]["probabilities"]) >= CONFORMAL_MIN_SIDE


def test_partition_conformal_none_when_a_side_underpowered() -> None:
    # One pair short of two full sides -> the test half drops below min_side.
    n = 2 * CONFORMAL_MIN_SIDE - 1
    assert partition_conformal(_pooled_block(n)) is None


def test_partition_conformal_none_for_missing_walkforward() -> None:
    assert partition_conformal({}) is None


# ---------------------------------------------------------------------------
# EV#6: C9 PSI-trend producer (walk_forward_psi_trend).
# ---------------------------------------------------------------------------


def _population_samples(n: int, *, drift: bool, bar: float = 900.0):
    """Chronological (score, return, anchor) samples.

    A "high" event carries score ~2.0 and a positive return; a "low" event
    ~0.5 and a negative return, so a reference Platt lens fit on the earliest
    block learns high-score -> win. When ``drift`` is set, the SHARE of high
    events rises over time, shifting the score *population* (not the
    score->outcome map) so the fixed-lens probability distribution drifts
    upward -- exactly what PSI-trend must detect. ``drift=False`` holds the
    share at 0.5 so the population is stationary.
    """
    rng = random.Random(7)
    base = 1_700_000_000.0
    scores: list[float] = []
    returns: list[float] = []
    anchor_ts: list[float] = []
    for i in range(n):
        anchor_ts.append(base + i * 10 * bar)
        frac = i / (n - 1)
        p_high = (0.2 + 0.7 * frac) if drift else 0.5
        high = rng.random() < p_high
        scores.append((2.0 if high else 0.5) + rng.uniform(-0.15, 0.15))
        returns.append(0.01 if high else -0.01)
    return scores, returns, anchor_ts


def test_psi_trend_returns_none_below_min_samples() -> None:
    # Too few events to form a reference block plus >= 2 monitoring windows.
    s, r, a = _population_samples(20, drift=False)
    assert walk_forward_psi_trend(s, r, a) is None


def test_psi_trend_emits_reference_and_at_least_two_windows() -> None:
    s, r, a = _population_samples(200, drift=False)
    block = walk_forward_psi_trend(s, r, a)
    assert block is not None
    ref = block["reference_probabilities"]
    windows = block["windows"]
    assert len(ref) > 0
    assert all(0.0 <= p <= 1.0 for p in ref)
    assert len(windows) >= PSI_TREND_MIN_WINDOWS
    for w in windows:
        assert len(w) > 0
        assert all(0.0 <= p <= 1.0 for p in w)


def test_psi_trend_none_when_reference_block_is_single_class() -> None:
    # Every event a winner -> the reference lens has one outcome class and the
    # calibrator refuses to fabricate a mapping -> no block.
    rng = random.Random(3)
    base = 1_700_000_000.0
    s = [2.0 + rng.uniform(-0.1, 0.1) for _ in range(200)]
    r = [0.01 for _ in range(200)]
    a = [base + i * 9000.0 for i in range(200)]
    assert walk_forward_psi_trend(s, r, a) is None


def test_psi_trend_length_mismatch_raises() -> None:
    try:
        walk_forward_psi_trend([1.0, 2.0], [0.01], [1.0, 2.0])
    except ValueError as exc:
        assert "length mismatch" in str(exc)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("expected ValueError on mismatched input lengths")


def test_psi_trend_block_feeds_slice_and_detects_drift() -> None:
    """End-to-end: the producer block is consumed by the gate's PSI-trend
    slice, and a drifting score population yields a markedly larger positive
    slope than a stationary one -- the measurement is real, not cosmetic."""
    from scripts.build_family_metrics import _psi_trend_slice

    drift_block = walk_forward_psi_trend(*_population_samples(240, drift=True))
    stable_block = walk_forward_psi_trend(*_population_samples(240, drift=False))
    assert drift_block is not None and stable_block is not None

    drift_slope = _psi_trend_slice("BOS", drift_block)["psi_slope"]
    stable_slope = _psi_trend_slice("BOS", stable_block)["psi_slope"]
    assert drift_slope is not None and stable_slope is not None
    # Drift is detected as a rising PSI trend, and clearly above the stationary
    # baseline (which should hover near zero).
    assert drift_slope > 0.0
    assert drift_slope > stable_slope

