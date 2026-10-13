"""Tests for ADR-0019 step 3: the paired purged-walk-forward A/B harness.

Covers the resolution metric, the paired fold function (identical OOS index
sets across arms), the paired extractor, and the shadow verdict branches.
"""

from __future__ import annotations

import pytest

from governance.family_calibration import MIN_OOS_SAMPLES, walk_forward_ab
from governance.family_event_adapter import family_events_from_structure
from governance.family_event_score import ATR_PERIOD
from governance.family_feature_ab import (
    AB_SOURCE_TAG,
    family_feature_ab,
    family_feature_ab_report,
    resolution,
)
from governance.family_returns import ABSamples, extract_family_ab_samples

_T0 = 1_700_000_000.0
_STEP = 86_400.0


# --------------------------------------------------------------------------- #
# resolution metric
# --------------------------------------------------------------------------- #
def test_resolution_rewards_discrimination() -> None:
    outcomes = [1.0, 1.0, 0.0, 0.0]
    sharp = [0.9, 0.9, 0.1, 0.1]
    flat = [0.5, 0.5, 0.5, 0.5]
    assert resolution(outcomes, sharp) > resolution(outcomes, flat)


def test_resolution_constant_forecast_is_zero() -> None:
    assert resolution([1.0, 0.0, 1.0, 0.0], [0.5, 0.5, 0.5, 0.5]) == 0.0


def test_resolution_empty_is_zero() -> None:
    assert resolution([], []) == 0.0


# --------------------------------------------------------------------------- #
# walk_forward_ab pairing
# --------------------------------------------------------------------------- #
def _ab_samples(
    *, scores: list[float], features: list[float], returns: list[float]
) -> ABSamples:
    n = len(scores)
    return {
        "scores": scores,
        "features": features,
        "returns": returns,
        "anchor_ts": [float(i) for i in range(n)],
        "guard_end_ts": [float(i) + 0.5 for i in range(n)],
    }


def _balanced_returns(n: int) -> list[float]:
    # Alternating win/loss -> base rate 0.5, both classes in every prefix.
    return [1.0 if i % 2 == 0 else -1.0 for i in range(n)]


def test_walk_forward_ab_arms_share_identical_outcomes() -> None:
    n = 300
    rets = _balanced_returns(n)
    # Both arms strongly discriminating -> both fit on every fold.
    feat = [1.0 if r > 0 else 0.0 for r in rets]
    ab = walk_forward_ab(
        feat,
        feat,
        rets,
        [float(i) for i in range(n)],
        [float(i) + 0.5 for i in range(n)],
    )
    assert ab is not None
    assert ab["baseline"]["outcomes"] == ab["candidate"]["outcomes"]
    assert len(ab["baseline"]["outcomes"]) >= MIN_OOS_SAMPLES


def test_walk_forward_ab_returns_none_below_min_oos() -> None:
    n = 12  # far below MIN_OOS_SAMPLES
    rets = _balanced_returns(n)
    feat = [1.0 if r > 0 else 0.0 for r in rets]
    ab = walk_forward_ab(
        feat,
        feat,
        rets,
        [float(i) for i in range(n)],
        [float(i) + 0.5 for i in range(n)],
    )
    assert ab is None


def test_walk_forward_ab_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        walk_forward_ab([1.0, 2.0], [1.0], [1.0, -1.0], [0.0, 1.0], [0.5, 1.5])


# --------------------------------------------------------------------------- #
# walk_forward_ab magnitude label (ADR-0019 step 3, magnitude path)
# --------------------------------------------------------------------------- #
def test_walk_forward_ab_magnitude_label_is_wired() -> None:
    """The magnitude path must run end-to-end and keep the two arms paired.

    Outcome SIZE depends on the candidate while sign is a coin flip, so a
    magnitude-labelled A/B has signal a direction-labelled one cannot see.
    """
    import random

    rng = random.Random(9)
    n = 600
    base = [rng.gauss(0.0, 1.0) for _ in range(n)]
    cand = [rng.gauss(0.0, 1.0) for _ in range(n)]
    rets = [
        (1.0 if rng.random() < 0.5 else -1.0) * (0.2 + 0.9 * abs(cand[i]))
        for i in range(n)
    ]
    ats = [float(i) for i in range(n)]
    gts = [float(i) + 0.5 for i in range(n)]
    ab = walk_forward_ab(base, cand, rets, ats, gts, label="magnitude", mag_q=0.5)
    assert ab is not None
    # Pairing must survive the alternate label.
    assert ab["baseline"]["outcomes"] == ab["candidate"]["outcomes"]
    # Magnitude labels are {0,1} and not all one class at mag_q=0.5.
    outs = ab["candidate"]["outcomes"]
    assert set(outs) <= {0.0, 1.0}
    assert 0.0 < sum(outs) < len(outs)


def test_walk_forward_ab_magnitude_differs_from_direction() -> None:
    """The label actually switches the target: magnitude != direction outcomes.

    On one data set where sign and size are independent, the direction label
    (sign of return) and the magnitude label (|return| over the train median)
    must produce different OOS outcome vectors -- proof that ``label`` is wired
    through to the labelling rather than silently ignored.
    """
    import random

    rng = random.Random(4)
    n = 500
    base = [rng.gauss(0.0, 1.0) for _ in range(n)]
    cand = [rng.gauss(0.0, 1.0) for _ in range(n)]
    rets = [
        (1.0 if rng.random() < 0.5 else -1.0) * (0.2 + abs(rng.gauss(0.0, 1.0)))
        for _ in range(n)
    ]
    ats = [float(i) for i in range(n)]
    gts = [float(i) + 0.5 for i in range(n)]
    direction = walk_forward_ab(base, cand, rets, ats, gts, label="direction")
    magnitude = walk_forward_ab(base, cand, rets, ats, gts, label="magnitude", mag_q=0.5)
    assert direction is not None and magnitude is not None
    # Same OOS index set (same folds), but a different outcome labelling.
    assert (
        direction["candidate"]["outcomes"] != magnitude["candidate"]["outcomes"]
    )
    mag_outs = magnitude["candidate"]["outcomes"]
    assert 0.0 < sum(mag_outs) < len(mag_outs)


# --------------------------------------------------------------------------- #
# family_feature_ab verdicts
# --------------------------------------------------------------------------- #
def test_ab_flags_candidate_that_lifts_resolution() -> None:
    n = 300
    rets = _balanced_returns(n)
    # Candidate cleanly separates outcomes; baseline is near-constant noise.
    feat = [1.0 if r > 0 else 0.0 for r in rets]
    score = [0.5 + 0.001 * (i % 7) for i in range(n)]
    result = family_feature_ab(
        _ab_samples(scores=score, features=feat, returns=rets)
    )
    assert result is not None
    assert result["verdict"] == "candidate_lifts_resolution"
    assert result["resolution_delta"] >= 0.005
    assert result["no_regression"] is True
    assert result["candidate_auc"] > result["baseline_auc"]
    assert result["source"] == AB_SOURCE_TAG


def test_ab_reports_no_lift_when_arms_match() -> None:
    n = 300
    rets = _balanced_returns(n)
    feat = [1.0 if r > 0 else 0.0 for r in rets]
    # Identical arms -> zero resolution delta -> no lift, no regression.
    result = family_feature_ab(
        _ab_samples(scores=feat, features=list(feat), returns=rets)
    )
    assert result is not None
    assert result["verdict"] == "no_lift"
    assert abs(result["resolution_delta"]) < 0.005
    assert result["no_regression"] is True


def test_ab_flags_calibration_regression() -> None:
    n = 300
    rets = _balanced_returns(n)
    y = [1.0 if r > 0 else 0.0 for r in rets]
    # Candidate predicts outcome early but FLIPS in the second half, so the
    # Platt model fit on early folds is confidently wrong on later test folds.
    feat = [y[i] if i < n // 2 else (1.0 - y[i]) for i in range(n)]
    score = [0.5 + 0.001 * (i % 7) for i in range(n)]
    result = family_feature_ab(
        _ab_samples(scores=score, features=feat, returns=rets)
    )
    assert result is not None
    assert result["verdict"] == "regresses_calibration"
    assert result["no_regression"] is False


def test_ab_returns_none_for_thin_sample() -> None:
    n = 12
    rets = _balanced_returns(n)
    feat = [1.0 if r > 0 else 0.0 for r in rets]
    assert family_feature_ab(_ab_samples(scores=feat, features=list(feat), returns=rets)) is None


def test_ab_report_omits_thin_families() -> None:
    n = 300
    rets = _balanced_returns(n)
    feat = [1.0 if r > 0 else 0.0 for r in rets]
    score = [0.5 + 0.001 * (i % 7) for i in range(n)]
    samples = {
        "BOS": _ab_samples(scores=score, features=feat, returns=rets),
        "OB": _ab_samples(scores=feat[:12], features=feat[:12], returns=rets[:12]),
    }
    report = family_feature_ab_report(samples)
    assert "BOS" in report
    assert "OB" not in report  # thin -> omitted, never silently scored


# --------------------------------------------------------------------------- #
# extract_family_ab_samples pairing
# --------------------------------------------------------------------------- #
def test_extract_ab_samples_pairs_score_and_feature() -> None:
    n = ATR_PERIOD + 12
    closes = [100.0 + i for i in range(n)]
    volumes: list[float | None] = [100.0] * n
    anchor_bar = ATR_PERIOD + 2
    volumes[anchor_bar] = 300.0
    bars = [
        {
            "timestamp": _T0 + i * _STEP,
            "high": closes[i] + 1.0,
            "low": closes[i] - 1.0,
            "close": closes[i],
            "volume": volumes[i],
        }
        for i in range(n)
    ]
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [{"id": "b1", "time": anchor_ts, "price": closes[anchor_bar], "dir": "UP"}]
    }

    events = family_events_from_structure(structure, bars)
    samples = extract_family_ab_samples(events)

    assert "BOS" in samples
    assert len(samples["BOS"]["scores"]) == 1
    assert len(samples["BOS"]["features"]) == 1
    assert len(samples["BOS"]["guard_end_ts"]) == 1


def test_extract_ab_samples_excludes_event_missing_feature() -> None:
    # No volume anywhere -> no relative_volume -> event excluded from the A/B.
    n = ATR_PERIOD + 12
    closes = [100.0 + i for i in range(n)]
    bars = [
        {
            "timestamp": _T0 + i * _STEP,
            "high": closes[i] + 1.0,
            "low": closes[i] - 1.0,
            "close": closes[i],
        }
        for i in range(n)
    ]
    anchor_bar = ATR_PERIOD + 2
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [{"id": "b1", "time": anchor_ts, "price": closes[anchor_bar], "dir": "UP"}]
    }

    events = family_events_from_structure(structure, bars)
    samples = extract_family_ab_samples(events)

    assert samples == {}


# --------------------------------------------------------------------------- #
# magnitude label (ADR-0020): grade move SIZE, leak-safe per-fold threshold
# --------------------------------------------------------------------------- #
def _anchor(n: int) -> list[float]:
    return [float(i) for i in range(n)]


def _guard(n: int) -> list[float]:
    return [float(i) + 0.5 for i in range(n)]


def test_walk_forward_ab_magnitude_grades_size_not_sign() -> None:
    # Every return is a WIN, so the directional label is single-class and no
    # fold can fit. The magnitude label instead grades |return| against a
    # per-fold quantile, so the alternating small/large sizes give both classes.
    n = 300
    rets = [0.02 if i % 2 == 0 else 0.001 for i in range(n)]
    feat = [1.0 if r > 0.01 else 0.0 for r in rets]  # tracks size
    anchor, guard = _anchor(n), _guard(n)

    assert (
        walk_forward_ab(feat, feat, rets, anchor, guard, label="direction") is None
    )

    ab = walk_forward_ab(feat, feat, rets, anchor, guard, label="magnitude")
    assert ab is not None
    assert ab["baseline"]["outcomes"] == ab["candidate"]["outcomes"]
    outcomes = ab["baseline"]["outcomes"]
    assert all(o in (0.0, 1.0) for o in outcomes)
    assert any(o == 1.0 for o in outcomes)  # some moves cleared the threshold
    assert any(o == 0.0 for o in outcomes)  # some did not


def test_walk_forward_ab_magnitude_threshold_is_leak_safe_per_fold() -> None:
    # The per-fold threshold must come from TRAINING returns only. Inflating the
    # magnitude of only the LATEST events (which never enter an early fold's
    # expanding-window training set) must leave the earliest OOS outcomes
    # unchanged. A leaky global/test-aware threshold would shift them.
    n = 300
    base = [0.02 if i % 2 == 0 else 0.001 for i in range(n)]
    feat = [1.0 if r > 0.01 else 0.0 for r in base]
    anchor, guard = _anchor(n), _guard(n)

    ref = walk_forward_ab(feat, feat, base, anchor, guard, label="magnitude")
    assert ref is not None

    spiked = list(base)
    for i in range(int(n * 0.6), n):  # blow up the last 40% of |returns|
        spiked[i] = 100.0
    out = walk_forward_ab(feat, feat, spiked, anchor, guard, label="magnitude")
    assert out is not None

    # The earliest OOS outcomes depend only on early (unmutated) data, so a
    # leak-free per-fold threshold keeps them byte-identical.
    prefix = 20
    assert out["baseline"]["outcomes"][:prefix] == ref["baseline"]["outcomes"][:prefix]


def test_walk_forward_ab_mag_q_shifts_positive_rate() -> None:
    # A higher quantile threshold labels fewer moves "large".
    n = 300
    rets = [0.001 + 0.0001 * (i % 50) for i in range(n)]  # all wins, sawtooth size
    feat = [float(i % 2) for i in range(n)]
    anchor, guard = _anchor(n), _guard(n)

    low = walk_forward_ab(feat, feat, rets, anchor, guard, label="magnitude", mag_q=0.2)
    high = walk_forward_ab(feat, feat, rets, anchor, guard, label="magnitude", mag_q=0.8)
    assert low is not None and high is not None

    low_rate = sum(low["baseline"]["outcomes"]) / len(low["baseline"]["outcomes"])
    high_rate = sum(high["baseline"]["outcomes"]) / len(high["baseline"]["outcomes"])
    assert high_rate < low_rate


def test_family_feature_ab_threads_magnitude_label() -> None:
    # The label/mag_q selector must reach walk_forward_ab through the public
    # entry point: all-win returns are single-class under "direction" (no
    # result) but graded by size under "magnitude".
    n = 300
    rets = [0.02 if i % 2 == 0 else 0.001 for i in range(n)]
    feat = [1.0 if r > 0.01 else 0.0 for r in rets]  # cleanly separates size
    score = [0.5 + 0.001 * (i % 7) for i in range(n)]  # near-constant noise
    samples = _ab_samples(scores=score, features=feat, returns=rets)

    assert family_feature_ab(samples, label="direction") is None

    result = family_feature_ab(samples, label="magnitude")
    assert result is not None
    assert result["verdict"] == "candidate_lifts_resolution"
    assert result["candidate_auc"] > result["baseline_auc"]


def test_family_feature_ab_report_threads_magnitude_label() -> None:
    n = 300
    rets = [0.02 if i % 2 == 0 else 0.001 for i in range(n)]
    feat = [1.0 if r > 0.01 else 0.0 for r in rets]
    score = [0.5 + 0.001 * (i % 7) for i in range(n)]
    samples = {"BOS": _ab_samples(scores=score, features=feat, returns=rets)}

    # Direction label -> single-class -> family omitted as unmeasurable.
    assert family_feature_ab_report(samples, label="direction") == {}
    # Magnitude label -> measurable and graded.
    report = family_feature_ab_report(samples, label="magnitude")
    assert "BOS" in report
