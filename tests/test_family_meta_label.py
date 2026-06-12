"""Tests for ADR-0022: the paired JOINT meta-label A/B harness.

Covers the multivariate calibrator, the leak-safe paired joint walk-forward
(score-alone vs ``[score] + features``), the complete-case extractor, and the
shadow verdict branches. The decisive property under test: an orthogonal feature
that the score does NOT capture must lift joint resolution above score-alone,
while a leaked/future feature must NOT (the harness cannot manufacture lift).
"""

from __future__ import annotations

import random

import pytest

from governance.family_meta_label import (
    META_SOURCE_TAG,
    extract_family_meta_samples,
    family_meta_ab,
    family_meta_ab_report,
    walk_forward_meta_ab,
)

_T0 = 1_700_000_000.0
_STEP = 86_400.0


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _meta_samples(
    *,
    scores: list[float],
    feature_matrix: list[list[float]],
    returns: list[float],
) -> dict[str, list]:
    n = len(scores)
    return {
        "scores": scores,
        "feature_matrix": feature_matrix,
        "returns": returns,
        "anchor_ts": [float(i) for i in range(n)],
        "guard_end_ts": [float(i) + 0.5 for i in range(n)],
    }


def _logistic_draw(rng: random.Random, logit: float) -> float:
    p = 1.0 / (1.0 + pow(2.718281828459045, -logit))
    return 1.0 if rng.random() < p else -1.0


# --------------------------------------------------------------------------- #
# walk_forward_meta_ab — pairing + guards
# --------------------------------------------------------------------------- #
def test_meta_arms_share_identical_outcomes() -> None:
    n = 300
    rng = random.Random(7)
    scores = [rng.gauss(0.0, 1.0) for _ in range(n)]
    fm = [[rng.gauss(0.0, 1.0)] for _ in range(n)]
    rets = [_logistic_draw(rng, 0.8 * scores[i] + 0.8 * fm[i][0]) for i in range(n)]
    ab = walk_forward_meta_ab(
        scores,
        fm,
        rets,
        [float(i) for i in range(n)],
        [float(i) + 0.5 for i in range(n)],
    )
    assert ab is not None
    # Paired: both arms scored on the exact same OOS index set.
    assert ab["baseline"]["outcomes"] == ab["candidate"]["outcomes"]


def test_meta_returns_none_below_min_oos() -> None:
    n = 12
    rng = random.Random(1)
    scores = [rng.gauss(0.0, 1.0) for _ in range(n)]
    fm = [[rng.gauss(0.0, 1.0)] for _ in range(n)]
    rets = [1.0 if i % 2 == 0 else -1.0 for i in range(n)]
    ab = walk_forward_meta_ab(
        scores,
        fm,
        rets,
        [float(i) for i in range(n)],
        [float(i) + 0.5 for i in range(n)],
    )
    assert ab is None


def test_meta_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        walk_forward_meta_ab(
            [1.0, 2.0], [[1.0]], [1.0, -1.0], [0.0, 1.0], [0.5, 1.5]
        )


# --------------------------------------------------------------------------- #
# magnitude axis (--label magnitude): leak-safe per-fold quantile labelling
# --------------------------------------------------------------------------- #
def test_meta_magnitude_label_is_wired() -> None:
    """The magnitude axis must run end-to-end and keep the two arms paired.

    Magnitude grades ``|return|`` at the per-fold TRAIN quantile -- an axis the
    sign label cannot see -- so the harness must thread it through both arms and
    still pool the identical OOS index set.
    """
    n = 400
    rng = random.Random(19)
    scores = [rng.gauss(0.0, 1.0) for _ in range(n)]
    fm = [[rng.gauss(0.0, 1.0)] for _ in range(n)]
    # Move SIZE is large for half the events, small for the other half; the
    # sign is an independent coin flip, so direction carries no size signal.
    rets: list[float] = []
    for i in range(n):
        mag = 2.0 if i % 2 == 0 else 0.2
        sign = 1.0 if rng.random() < 0.5 else -1.0
        rets.append(sign * mag)
    ab = walk_forward_meta_ab(
        scores,
        fm,
        rets,
        [float(i) for i in range(n)],
        [float(i) + 0.5 for i in range(n)],
        label="magnitude",
        mag_q=0.5,
    )
    assert ab is not None
    assert ab["baseline"]["outcomes"] == ab["candidate"]["outcomes"]
    # The magnitude label is a genuine 0/1 over |return|: both classes appear.
    assert set(ab["baseline"]["outcomes"]) == {0.0, 1.0}


def test_meta_magnitude_differs_from_direction() -> None:
    """``label`` actually switches the graded target, not a silent re-grade.

    With sign decoupled from size, the direction and magnitude axes must label
    the SAME pooled OOS events differently; equal vectors would prove the
    magnitude path was never wired.
    """
    n = 400
    rng = random.Random(23)
    scores = [rng.gauss(0.0, 1.0) for _ in range(n)]
    fm = [[rng.gauss(0.0, 1.0)] for _ in range(n)]
    rets: list[float] = []
    for i in range(n):
        mag = 2.0 if i % 2 == 0 else 0.2
        sign = 1.0 if rng.random() < 0.5 else -1.0
        rets.append(sign * mag)
    common = (
        scores,
        fm,
        rets,
        [float(i) for i in range(n)],
        [float(i) + 0.5 for i in range(n)],
    )
    direction = walk_forward_meta_ab(*common, label="direction")
    magnitude = walk_forward_meta_ab(*common, label="magnitude", mag_q=0.5)
    assert direction is not None and magnitude is not None
    assert (
        direction["baseline"]["outcomes"] != magnitude["baseline"]["outcomes"]
    )


# --------------------------------------------------------------------------- #
# the decisive test: orthogonal feature lifts the JOINT model
# --------------------------------------------------------------------------- #
def test_orthogonal_feature_lifts_joint_resolution() -> None:
    """A feature carrying signal the score lacks must lift joint resolution.

    The score is pure noise w.r.t. the outcome; the extra feature drives it.
    Score-alone cannot resolve, the joint model can -> candidate_lifts_resolution.
    """
    n = 400
    rng = random.Random(11)
    scores = [rng.gauss(0.0, 1.0) for _ in range(n)]
    fm = [[rng.gauss(0.0, 1.0)] for _ in range(n)]
    # Outcome depends ONLY on the extra feature, not the score.
    rets = [_logistic_draw(rng, 1.4 * fm[i][0]) for i in range(n)]
    result = family_meta_ab(
        _meta_samples(scores=scores, feature_matrix=fm, returns=rets),
        ["orthogonal_signal"],
    )
    assert result is not None
    assert result["resolution_delta"] >= 0.005
    assert result["verdict"] == "candidate_lifts_resolution"
    assert result["candidate_auc"] > result["baseline_auc"]
    assert result["source"] == META_SOURCE_TAG
    assert result["n_features"] == 1


def test_leaked_future_feature_does_not_manufacture_lift() -> None:
    """A feature uncorrelated with the outcome must NOT lift resolution.

    Guards against a harness that flatters the joint arm: pure-noise extra
    features over a coin-flip outcome must land on ``no_lift``.
    """
    n = 400
    rng = random.Random(3)
    scores = [rng.gauss(0.0, 1.0) for _ in range(n)]
    fm = [[rng.gauss(0.0, 1.0)] for _ in range(n)]
    rets = [1.0 if rng.random() < 0.5 else -1.0 for _ in range(n)]
    result = family_meta_ab(
        _meta_samples(scores=scores, feature_matrix=fm, returns=rets),
        ["pure_noise"],
    )
    assert result is not None
    assert result["verdict"] == "no_lift"
    assert result["resolution_delta"] < 0.005


# --------------------------------------------------------------------------- #
# complete-case extractor honesty
# --------------------------------------------------------------------------- #
def _event(
    *,
    family: str,
    score: float,
    anchor_ts: float,
    extras: dict[str, float],
    up: bool,
) -> dict:
    # 'immediate' entry: the anchor bar IS the trigger, exit ``horizon`` bars
    # later. An up event closes above entry, a down event below, so
    # realized_return has a definite, non-None sign. BOS horizon is 8 bars.
    entry = 100.0
    exit_close = 101.0 if up else 99.0
    closes = [entry + 0.0 for _ in range(7)] + [exit_close]
    forward_ts = [anchor_ts + (k + 1) * _STEP for k in range(len(closes))]
    event = {
        "family": family,
        "score": score,
        "anchor_ts": anchor_ts,
        "direction": "long",
        "entry_mode": "immediate",
        "entry_price": entry,
        "forward_closes": closes,
        "forward_timestamps": forward_ts,
    }
    event.update(extras)
    return event


def test_extractor_excludes_events_missing_any_feature_key() -> None:
    """Complete-case: an event missing any requested key is dropped, not filled."""
    events = [
        _event(
            family="BOS",
            score=0.5,
            anchor_ts=_T0 + i * _STEP,
            extras={"relative_volume": 1.2, "vpin": 0.3},
            up=(i % 2 == 0),
        )
        for i in range(6)
    ]
    # One event is missing 'vpin' -> must be excluded from the joint sample.
    del events[2]["vpin"]
    samples = extract_family_meta_samples(
        events, feature_keys=["relative_volume", "vpin"]
    )
    assert "BOS" in samples
    # 6 events, 1 incomplete -> 5 complete-case rows, each with 2 feature columns.
    assert len(samples["BOS"]["scores"]) == 5
    assert all(len(row) == 2 for row in samples["BOS"]["feature_matrix"])


def test_extractor_requires_nonempty_feature_keys() -> None:
    with pytest.raises(ValueError, match="feature_keys is empty"):
        extract_family_meta_samples([], feature_keys=[])


# --------------------------------------------------------------------------- #
# report aggregation
# --------------------------------------------------------------------------- #
def test_report_omits_families_too_thin_to_measure() -> None:
    events = [
        _event(
            family="BOS",
            score=0.5,
            anchor_ts=_T0 + i * _STEP,
            extras={"relative_volume": 1.0 + 0.01 * i},
            up=(i % 2 == 0),
        )
        for i in range(8)
    ]
    samples = extract_family_meta_samples(events, feature_keys=["relative_volume"])
    report = family_meta_ab_report(samples, ["relative_volume"])
    # 8 paired points is far below MIN_OOS_SAMPLES -> no measurable family.
    assert report == {}
