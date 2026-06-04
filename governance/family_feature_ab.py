"""ADR-0019 — paired A/B harness: does a v2 candidate feature lift resolution?

This module answers ONE pre-registered question, in shadow mode only: over a
purged walk-forward, does Platt-calibrating the recorded candidate feature
(e.g. ``relative_volume``) discriminate event outcomes BETTER than the current
v1 ``score``? "Better" is measured primarily by **resolution** -- the
discrimination component of the Murphy decomposition of the Brier score -- the
exact deficit the verified feature-gap analysis identified as the binding
promotion blocker (``docs/governance/resolution_feature_gap_analysis.md``).

Design (pre-registered, honest, non-gating):

- PAIRED: both arms are scored on the SAME events over the SAME purged folds
  (:func:`governance.family_calibration.walk_forward_ab`), so a resolution
  delta reflects the feature, not a differing event sample.
- PRIMARY metric: out-of-sample resolution lift ``candidate - baseline``.
- NO-REGRESSION guards: the candidate must not worsen the overall Brier (a
  proper scoring rule -- a real probability regression shows up here) beyond a
  small tolerance, AND must itself clear an ABSOLUTE calibration ceiling. The
  ECE guard is deliberately absolute, not relative to the baseline: a
  non-informative near-constant baseline trivially earns a tiny ECE, so
  comparing the candidate's ECE against it would perversely penalise a sharp,
  well-discriminating forecaster. A feature that discriminates but is itself
  badly miscalibrated is still rejected.
- SAMPLE-POWER guard: below ``min_oos`` shared out-of-sample points the family
  is not measurable yet -- :func:`family_feature_ab` returns ``None`` and
  :func:`family_feature_ab_report` omits it, so a thin family is never silently
  scored or assigned a verdict (GAP 3/4).
- SCOPE: this slice compares feature-ALONE vs score-ALONE. The *incremental*
  question (does the feature add resolution ON TOP of the score, i.e. a 2-D /
  meta-label model) is deliberately out of scope here and is the next slice.

Nothing here calibrates, scores, or gates production. v1 stays the default
until this A/B clears on real data under pre-registration.
"""
from __future__ import annotations

from typing import Literal, TypedDict

from governance.family_calibration import MIN_OOS_SAMPLES, walk_forward_ab
from governance.family_returns import ABSamples
from ml.metrics import brier_score, expected_calibration_error, roc_auc

# Pre-registered acceptance thresholds. Conservative by intent: the candidate
# must show a non-trivial resolution lift, must not regress the (proper-scoring)
# Brier, and must itself clear an absolute calibration ceiling.
MIN_RESOLUTION_LIFT = 0.005
BRIER_REGRESSION_TOLERANCE = 0.01
# Absolute ceiling on the candidate's own ECE (NOT relative to the baseline --
# see the module docstring: a near-constant baseline trivially wins on ECE).
ABS_ECE_CEILING = 0.10
RESOLUTION_BINS = 10

AB_SOURCE_TAG = "adr0019_paired_purged_walkforward_resolution_ab_v1"

Verdict = Literal[
    "candidate_lifts_resolution",
    "no_lift",
    "regresses_calibration",
]


class FamilyABResult(TypedDict):
    """Per-family A/B measurement (shadow). All metrics are out-of-sample."""

    n_oos: int
    baseline_brier: float
    candidate_brier: float
    brier_delta: float
    baseline_resolution: float
    candidate_resolution: float
    resolution_delta: float
    baseline_ece: float
    candidate_ece: float
    baseline_auc: float
    candidate_auc: float
    resolution_improved: bool
    no_regression: bool
    verdict: Verdict
    source: str


def resolution(outcomes: list[float], probabilities: list[float], *, n_bins: int = RESOLUTION_BINS) -> float:
    """Murphy resolution: ``(1/N) * sum_k n_k * (ybar_k - ybar)**2``.

    Forecasts are partitioned into ``n_bins`` equal-width probability bins; each
    bin contributes the squared distance of its observed outcome rate from the
    base rate, weighted by occupancy. Higher resolution = the forecasts sort
    winners from losers more sharply (better discrimination). Returns ``0.0``
    for an empty or single-point input.
    """
    n = len(outcomes)
    if n == 0:
        return 0.0
    base_rate = sum(outcomes) / n
    edges = [k / n_bins for k in range(n_bins + 1)]
    total = 0.0
    for k in range(n_bins):
        lo, hi = edges[k], edges[k + 1]
        if k == n_bins - 1:
            idx = [i for i in range(n) if lo <= probabilities[i] <= hi]
        else:
            idx = [i for i in range(n) if lo <= probabilities[i] < hi]
        if not idx:
            continue
        bin_rate = sum(outcomes[i] for i in idx) / len(idx)
        total += len(idx) * (bin_rate - base_rate) ** 2
    return total / n


def _arm_metrics(arm: dict[str, list[float]]) -> tuple[float, float, float, float]:
    """Return ``(brier, resolution, ece, auc)`` for one OOS arm."""
    probs = arm["probabilities"]
    outcomes = arm["outcomes"]
    return (
        brier_score(outcomes, probs),
        resolution(outcomes, probs),
        expected_calibration_error(outcomes, probs),
        roc_auc(outcomes, probs),
    )


def family_feature_ab(
    samples: ABSamples,
    *,
    min_oos: int = MIN_OOS_SAMPLES,
    min_resolution_lift: float = MIN_RESOLUTION_LIFT,
    ece_ceiling: float = ABS_ECE_CEILING,
    brier_tolerance: float = BRIER_REGRESSION_TOLERANCE,
    label: Literal["direction", "magnitude"] = "direction",
    mag_q: float = 0.5,
) -> FamilyABResult | None:
    """Run the paired A/B for one family. ``None`` when the sample is too thin.

    Returns ``None`` (not a verdict -- the family is simply not measurable yet)
    when :func:`walk_forward_ab` cannot assemble at least ``min_oos`` shared
    out-of-sample points. Otherwise returns a :class:`FamilyABResult` whose
    ``verdict`` is:

    - ``candidate_lifts_resolution`` -- resolution lift >= ``min_resolution_lift``
      AND no calibration/Brier regression beyond tolerance;
    - ``regresses_calibration`` -- the candidate regresses the proper-scoring
      Brier beyond ``brier_tolerance`` OR breaches the absolute ECE ceiling
      ``ece_ceiling`` (a discrimination gain that costs calibration is rejected);
    - ``no_lift`` -- calibration is fine but the resolution lift is too small.
    """
    ab = walk_forward_ab(
        samples["scores"],
        samples["features"],
        samples["returns"],
        samples["anchor_ts"],
        samples["guard_end_ts"],
        min_oos=min_oos,
        label=label,
        mag_q=mag_q,
    )
    if ab is None:
        return None

    base_brier, base_res, base_ece, base_auc = _arm_metrics(ab["baseline"])
    cand_brier, cand_res, cand_ece, cand_auc = _arm_metrics(ab["candidate"])

    resolution_delta = cand_res - base_res
    resolution_improved = resolution_delta >= min_resolution_lift
    no_regression = (
        cand_brier <= base_brier + brier_tolerance
        and cand_ece <= ece_ceiling
    )

    if not no_regression:
        verdict: Verdict = "regresses_calibration"
    elif resolution_improved:
        verdict = "candidate_lifts_resolution"
    else:
        verdict = "no_lift"

    return FamilyABResult(
        n_oos=len(ab["baseline"]["outcomes"]),
        baseline_brier=base_brier,
        candidate_brier=cand_brier,
        brier_delta=cand_brier - base_brier,
        baseline_resolution=base_res,
        candidate_resolution=cand_res,
        resolution_delta=resolution_delta,
        baseline_ece=base_ece,
        candidate_ece=cand_ece,
        baseline_auc=base_auc,
        candidate_auc=cand_auc,
        resolution_improved=resolution_improved,
        no_regression=no_regression,
        verdict=verdict,
        source=AB_SOURCE_TAG,
    )


def family_feature_ab_report(
    ab_samples: dict[str, ABSamples],
    *,
    min_oos: int = MIN_OOS_SAMPLES,
    min_resolution_lift: float = MIN_RESOLUTION_LIFT,
    ece_ceiling: float = ABS_ECE_CEILING,
    brier_tolerance: float = BRIER_REGRESSION_TOLERANCE,
    label: Literal["direction", "magnitude"] = "direction",
    mag_q: float = 0.5,
) -> dict[str, FamilyABResult]:
    """Run the paired A/B for every family that is measurable.

    Families whose paired sample is too thin (``family_feature_ab`` returns
    ``None``) are omitted -- the report carries only families that produced a
    real out-of-sample verdict, so a thin family is never silently scored as a
    pass or fail.
    """
    out: dict[str, FamilyABResult] = {}
    for family, samples in ab_samples.items():
        result = family_feature_ab(
            samples,
            min_oos=min_oos,
            min_resolution_lift=min_resolution_lift,
            ece_ceiling=ece_ceiling,
            brier_tolerance=brier_tolerance,
            label=label,
            mag_q=mag_q,
        )
        if result is not None:
            out[family] = result
    return out


__all__ = [
    "ABS_ECE_CEILING",
    "AB_SOURCE_TAG",
    "BRIER_REGRESSION_TOLERANCE",
    "MIN_RESOLUTION_LIFT",
    "RESOLUTION_BINS",
    "FamilyABResult",
    "Verdict",
    "family_feature_ab",
    "family_feature_ab_report",
    "resolution",
]
