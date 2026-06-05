"""Tests for the ADR-0019 regime-stratified score-resolution FILTER.

These exercise the leak-safe regime passthrough in ``walk_forward_ab`` and the
``family_feature_regime`` measurement: a feature that does not lift resolution
on its own can still flag a regime in which the v1 score is better resolved.
"""
from __future__ import annotations

import pytest

from governance.family_calibration import walk_forward_ab
from governance.family_feature_regime import (
    MIN_REGIME_RESOLUTION_SPREAD,
    REGIME_SOURCE_TAG,
    family_feature_regime,
    family_feature_regime_report,
)
from governance.family_returns import ABSamples


def _anchor(n: int) -> list[float]:
    return [float(i) for i in range(n)]


def _guard(n: int) -> list[float]:
    return [float(i) + 0.5 for i in range(n)]


def _samples(
    *, scores: list[float], features: list[float], returns: list[float]
) -> ABSamples:
    n = len(scores)
    return {
        "scores": scores,
        "features": features,
        "returns": returns,
        "anchor_ts": _anchor(n),
        "guard_end_ts": _guard(n),
    }


# --------------------------------------------------------------------------- #
# walk_forward_ab regime passthrough
# --------------------------------------------------------------------------- #
def test_regime_passthrough_is_aligned_and_optional() -> None:
    n = 400
    rets = [1.0 if i % 2 == 0 else -1.0 for i in range(n)]
    feat = [1.0 if r > 0 else 0.0 for r in rets]
    regime = [float(i) for i in range(n)]

    with_regime = walk_forward_ab(
        feat, feat, rets, _anchor(n), _guard(n), regime=regime
    )
    without_regime = walk_forward_ab(feat, feat, rets, _anchor(n), _guard(n))

    assert with_regime is not None
    assert without_regime is not None
    # The passthrough returns one regime value per shared OOS pair...
    assert len(with_regime["regime"]) == len(with_regime["baseline"]["outcomes"])
    # ...and never perturbs the calibration it rides alongside.
    assert with_regime["baseline"]["outcomes"] == without_regime["baseline"]["outcomes"]
    assert with_regime["baseline"]["probabilities"] == pytest.approx(
        without_regime["baseline"]["probabilities"]
    )
    # Absent regime -> no regime key leaks into the result.
    assert "regime" not in without_regime


def test_regime_length_mismatch_raises() -> None:
    n = 50
    rets = [1.0 if i % 2 == 0 else -1.0 for i in range(n)]
    feat = [1.0 if r > 0 else 0.0 for r in rets]
    with pytest.raises(ValueError, match="regime length mismatch"):
        walk_forward_ab(
            feat, feat, rets, _anchor(n), _guard(n), regime=[0.0] * (n - 1)
        )


# --------------------------------------------------------------------------- #
# family_feature_regime verdicts
# --------------------------------------------------------------------------- #
def _regime_dataset(*, conditioned: bool) -> ABSamples:
    """Build a 4-way cycle of (regime magnitude x outcome).

    Half the points carry a large ``|feature|`` (high-conviction regime), half a
    small one; outcome alternates win/loss independently. When ``conditioned``
    the score only tracks the outcome inside the large-|feature| regime, so the
    score-alone arm resolves outcomes there and not in the small regime.
    """
    n = 400
    scores: list[float] = []
    features: list[float] = []
    returns: list[float] = []
    for i in range(n):
        win = i % 2 == 0
        big = (i // 2) % 2 == 0
        returns.append(1.0 if win else -1.0)
        # Two well-separated, continuous |feature| clusters so the median split
        # is robust: high-conviction ~[1.5, 2.1], low-conviction ~[0.0, 0.3].
        jitter = (i % 7) * 0.1
        features.append((1.5 + jitter) if big else (jitter * 0.5))
        if conditioned:
            # Informative only in the big regime; pure noise (constant) in small.
            score = (0.9 if win else 0.1) if big else 0.5
        else:
            # Equally informative in both regimes -> no regime effect.
            score = 0.9 if win else 0.1
        scores.append(score)
    return _samples(scores=scores, features=features, returns=returns)


def test_regime_conditions_resolution_when_score_only_works_in_one_regime() -> None:
    result = family_feature_regime(_regime_dataset(conditioned=True))
    assert result is not None
    assert result["verdict"] == "regime_conditions_resolution"
    assert result["resolution_spread"] >= MIN_REGIME_RESOLUTION_SPREAD
    assert result["source"] == REGIME_SOURCE_TAG
    assert result["n_strata"] == 2
    # Strata partition every OOS point exactly once.
    assert sum(s["n_oos"] for s in result["strata"]) == result["n_oos"]
    # The high-conviction (large-|feature|) stratum is the better-resolved one.
    favorable = result["strata"][result["favorable_stratum"]]
    assert favorable["regime_hi"] >= 2.0


def test_no_regime_effect_when_score_resolves_uniformly() -> None:
    result = family_feature_regime(_regime_dataset(conditioned=False))
    assert result is not None
    assert result["verdict"] == "no_regime_effect"
    assert result["resolution_spread"] < MIN_REGIME_RESOLUTION_SPREAD


def test_degenerate_regime_returns_none() -> None:
    n = 400
    rets = [1.0 if i % 2 == 0 else -1.0 for i in range(n)]
    score = [0.9 if r > 0 else 0.1 for r in rets]
    feat = [1.0] * n  # constant -> |feature| cannot be split
    assert family_feature_regime(_samples(scores=score, features=feat, returns=rets)) is None


def test_thin_stratum_returns_none() -> None:
    result = family_feature_regime(
        _regime_dataset(conditioned=True), min_stratum_oos=100_000
    )
    assert result is None


def test_n_strata_below_two_raises() -> None:
    with pytest.raises(ValueError, match="n_strata"):
        family_feature_regime(_regime_dataset(conditioned=True), n_strata=1)


def test_report_omits_unmeasurable_families() -> None:
    n = 400
    rets = [1.0 if i % 2 == 0 else -1.0 for i in range(n)]
    score = [0.9 if r > 0 else 0.1 for r in rets]
    flat = [1.0] * n
    samples = {
        "BOS": _regime_dataset(conditioned=True),
        "OB": _samples(scores=score, features=flat, returns=rets),  # degenerate
        "FVG": _samples(scores=score[:10], features=score[:10], returns=rets[:10]),  # thin
    }
    report = family_feature_regime_report(samples)
    assert "BOS" in report
    assert "OB" not in report
    assert "FVG" not in report
