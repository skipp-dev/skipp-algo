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
