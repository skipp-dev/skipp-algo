"""ADR-0019 (regime slice) — is the v1 score better RESOLVED in some feature regime?

The paired A/B in :mod:`governance.family_feature_ab` asks whether a recorded
candidate feature, calibrated ALONE, discriminates outcomes better than the v1
``score`` alone. When a feature does NOT lift resolution on its own it can still
be useful as a FILTER: a variable that says *when the existing score is trust-
worthy* rather than *which way price goes*. This slice answers that second,
distinct question, in shadow mode only:

    Partition the out-of-sample points of the SCORE-ALONE arm by an exogenous
    regime derived from the feature (e.g. low vs high ``|signed_uoa_notional|``)
    and compare the score's RESOLUTION across the strata. A materially larger
    resolution in one stratum means the score sorts winners from losers better
    in that regime -- i.e. the feature conditions when to act.

Design (pre-registered, honest, non-gating):

- LEAK-SAFE & UNCONFOUNDED: the strata share ONE identical purged walk-forward
  fold set. :func:`governance.family_calibration.walk_forward_ab` carries the
  per-event regime value through the same sort/purge/pairing it already applies
  to outcomes and returns it aligned 1:1 with the OOS pairs; the regime value
  never enters any fit or prediction. Splitting AFTER a single shared
  calibration (rather than refitting folds per subset) keeps the cross-stratum
  comparison free of differing-fold confounding.
- PRIMARY metric: the spread ``max_stratum_resolution - min_stratum_resolution``
  of the score-alone arm. The candidate feature's own probabilities are not
  used here -- this measures the SCORE, conditioned on the regime.
- SAMPLE-POWER guard: the whole sample must clear ``min_oos`` (enforced by
  ``walk_forward_ab``) AND every stratum must clear ``min_stratum_oos``; below
  that the family is not measurable and the function returns ``None`` rather
  than inventing a verdict on a thin slice.

Nothing here calibrates, scores, or gates production. It is a measurement that
tells a human whether a recorded feature is worth keeping as a regime filter.
"""
from __future__ import annotations

from typing import Literal, TypedDict

from governance.family_calibration import (
    MIN_OOS_SAMPLES,
    _quantile,
    walk_forward_ab,
)
from governance.family_feature_ab import resolution
from governance.family_returns import ABSamples
from ml.metrics import brier_score, expected_calibration_error, roc_auc

# A stratum must resolve at least this much better than the weakest stratum for
# the regime to be judged to condition the score's discrimination.
MIN_REGIME_RESOLUTION_SPREAD = 0.01

REGIME_SOURCE_TAG = "adr0019_regime_stratified_score_resolution_filter_v1"

StratifyBy = Literal["abs_feature", "feature"]

RegimeVerdict = Literal[
    "regime_conditions_resolution",
    "no_regime_effect",
]


class RegimeStratum(TypedDict):
    """Score-alone OOS metrics within one regime stratum (all out-of-sample)."""

    index: int
    regime_lo: float
    regime_hi: float
    n_oos: int
    base_rate: float
    baseline_brier: float
    baseline_resolution: float
    baseline_ece: float
    baseline_auc: float


class FamilyRegimeResult(TypedDict):
    """Per-family regime-filter measurement (shadow). Score-alone arm only."""

    n_oos: int
    n_strata: int
    stratify_by: StratifyBy
    strata: list[RegimeStratum]
    resolution_spread: float
    favorable_stratum: int
    verdict: RegimeVerdict
    source: str


def _regime_series(features: list[float], stratify_by: StratifyBy) -> list[float]:
    """Map raw feature values to the scalar regime variable to stratify on."""
    if stratify_by == "abs_feature":
        return [abs(f) for f in features]
    return list(features)


def family_feature_regime(
    samples: ABSamples,
    *,
    n_strata: int = 2,
    stratify_by: StratifyBy = "abs_feature",
    min_oos: int = MIN_OOS_SAMPLES,
    min_stratum_oos: int = MIN_OOS_SAMPLES,
    min_resolution_spread: float = MIN_REGIME_RESOLUTION_SPREAD,
    label: Literal["direction", "magnitude"] = "direction",
    mag_q: float = 0.5,
) -> FamilyRegimeResult | None:
    """Stratify the score-alone arm by a feature regime and compare resolution.

    Returns ``None`` (family not measurable yet) when the paired walk-forward
    cannot assemble ``min_oos`` shared OOS points, when any stratum holds fewer
    than ``min_stratum_oos`` points, or when the regime is degenerate (a single
    distinct value). Otherwise returns a :class:`FamilyRegimeResult` whose
    ``verdict`` is ``regime_conditions_resolution`` if the score-alone
    resolution spread across strata is at least ``min_resolution_spread``, else
    ``no_regime_effect``.
    """
    if n_strata < 2:
        raise ValueError("family_feature_regime: n_strata must be >= 2")

    regime = _regime_series(samples["features"], stratify_by)
    ab = walk_forward_ab(
        samples["scores"],
        samples["features"],
        samples["returns"],
        samples["anchor_ts"],
        samples["guard_end_ts"],
        min_oos=min_oos,
        label=label,
        mag_q=mag_q,
        regime=regime,
    )
    if ab is None:
        return None

    probs: list[float] = ab["baseline"]["probabilities"]
    outcomes: list[float] = ab["baseline"]["outcomes"]
    regime_oos: list[float] = ab["regime"]

    # Interior quantile cuts of the OOS regime values define the strata. A point
    # falls into stratum k = number of cuts it is at or above (ties go up).
    cuts = [_quantile(regime_oos, k / n_strata) for k in range(1, n_strata)]
    if cuts and cuts[0] <= min(regime_oos) and cuts[-1] >= max(regime_oos):
        # Degenerate: the cuts collapse onto the data bounds (regime has too few
        # distinct values to split) -- not measurable as a regime.
        return None

    members: list[list[int]] = [[] for _ in range(n_strata)]
    for i, value in enumerate(regime_oos):
        k = sum(1 for c in cuts if value >= c)
        members[k].append(i)

    strata: list[RegimeStratum] = []
    for k, idx in enumerate(members):
        if len(idx) < min_stratum_oos:
            return None
        s_probs = [probs[i] for i in idx]
        s_out = [outcomes[i] for i in idx]
        s_regime = [regime_oos[i] for i in idx]
        strata.append(
            RegimeStratum(
                index=k,
                regime_lo=min(s_regime),
                regime_hi=max(s_regime),
                n_oos=len(idx),
                base_rate=sum(s_out) / len(s_out),
                baseline_brier=brier_score(s_out, s_probs),
                baseline_resolution=resolution(s_out, s_probs),
                baseline_ece=expected_calibration_error(s_out, s_probs),
                baseline_auc=roc_auc(s_out, s_probs),
            )
        )

    resolutions = [s["baseline_resolution"] for s in strata]
    spread = max(resolutions) - min(resolutions)
    favorable = max(range(n_strata), key=lambda k: resolutions[k])
    verdict: RegimeVerdict = (
        "regime_conditions_resolution"
        if spread >= min_resolution_spread
        else "no_regime_effect"
    )

    return FamilyRegimeResult(
        n_oos=len(outcomes),
        n_strata=n_strata,
        stratify_by=stratify_by,
        strata=strata,
        resolution_spread=spread,
        favorable_stratum=favorable,
        verdict=verdict,
        source=REGIME_SOURCE_TAG,
    )


def family_feature_regime_report(
    ab_samples: dict[str, ABSamples],
    *,
    n_strata: int = 2,
    stratify_by: StratifyBy = "abs_feature",
    min_oos: int = MIN_OOS_SAMPLES,
    min_stratum_oos: int = MIN_OOS_SAMPLES,
    min_resolution_spread: float = MIN_REGIME_RESOLUTION_SPREAD,
    label: Literal["direction", "magnitude"] = "direction",
    mag_q: float = 0.5,
) -> dict[str, FamilyRegimeResult]:
    """Run the regime-filter measurement for every measurable family.

    Families whose paired sample is too thin or whose regime is degenerate are
    omitted, so a family never receives a silent or invented regime verdict.
    """
    out: dict[str, FamilyRegimeResult] = {}
    for family, samples in ab_samples.items():
        result = family_feature_regime(
            samples,
            n_strata=n_strata,
            stratify_by=stratify_by,
            min_oos=min_oos,
            min_stratum_oos=min_stratum_oos,
            min_resolution_spread=min_resolution_spread,
            label=label,
            mag_q=mag_q,
        )
        if result is not None:
            out[family] = result
    return out


__all__ = [
    "MIN_REGIME_RESOLUTION_SPREAD",
    "REGIME_SOURCE_TAG",
    "FamilyRegimeResult",
    "RegimeStratum",
    "RegimeVerdict",
    "StratifyBy",
    "family_feature_regime",
    "family_feature_regime_report",
]
