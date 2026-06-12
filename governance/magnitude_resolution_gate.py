"""ADR-0023 §2 — the pre-registered move-size acceptance-bar estimators.

This module implements the two estimators ADR-0023 deliberately left out of the
doc-only pre-registration: a bootstrap confidence interval on the score-alone
magnitude AUC (§2.1) and a label-permutation null on the score-alone Murphy
resolution (§2.2). Together with the existing leak-safe purged walk-forward
(``governance.family_calibration.walk_forward_ab`` with ``label="magnitude"``)
they decide, per family, whether the v1 geometry score resolves move-size
strongly enough to qualify for the additive tier-2 ``magnitude_resolution_floor``
sizing check.

Everything here is a MEASUREMENT. This module wires nothing into the score and
does not by itself gate anything; the promotion-gate consumes its verdict
separately. The bar is fixed in ADR-0023 §2 and is NOT re-tuned here:

1. Discrimination floor (data-independent): score-alone magnitude AUC point
   estimate >= ``MAG_AUC_FLOOR`` (0.60) AND the lower bound of its bootstrap
   95 % CI (B >= 1000, resampling OOS rows) >= ``MAG_AUC_CI_LOW_FLOOR`` (0.55).
2. Resolution floor (self-anchoring): score-alone ``baseline_resolution`` must
   exceed the ``PERM_NULL_PERCENTILE`` (95th) percentile of a label-permutation
   null (shuffle the magnitude labels, identical resolution bins, B >= 1000).
3. No direction regression: structurally guaranteed by the ADDITIVE design (the
   existing direction-Brier ``brier_threshold`` check is retained, never
   replaced — ADR-0023 §4). The score-alone direction-Brier is reported here for
   transparency, not re-tested as a blocker.
4. Minimum sample: ``MIN_OOS_SAMPLES`` (40) shared OOS points, else the family
   is INCONCLUSIVE — which is not a pass.

A family passes only on (1) AND (2) AND (4). A miss is a negative result; per
ADR-0023 §3 the bar is not re-tuned on a losing run.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from governance.family_calibration import (
    MIN_OOS_SAMPLES,
    _quantile,
    walk_forward_ab,
)
from governance.family_feature_ab import RESOLUTION_BINS, resolution
from ml.metrics import brier_score, roc_auc

# --- ADR-0023 §2 pre-registered bar constants (DO NOT re-tune on a losing run;
# any change requires a new superseding ADR — ADR-0023 §3). --------------------
MAG_AUC_FLOOR = 0.60
MAG_AUC_CI_LOW_FLOOR = 0.55
PERM_NULL_PERCENTILE = 0.95
DEFAULT_N_BOOTSTRAP = 1000
DEFAULT_N_PERMUTATION = 1000
# Deterministic default seed so a re-run reproduces the CI/null exactly. The
# digits spell the ADR number; the value itself carries no meaning.
DEFAULT_SEED = 230_022

MAGNITUDE_GATE_SOURCE_TAG = "adr0023_magnitude_resolution_floor_v1"


@dataclass(frozen=True)
class MagnitudeResolutionResult:
    """Per-family score-alone move-size resolution measurement (shadow).

    All metrics are out-of-sample on the purged walk-forward. ``passes`` is the
    AND of the three pre-registered conditions (AUC floor, AUC CI lower bound,
    resolution permutation null) gated on the minimum-sample precondition.
    """

    family: str
    n_oos: int
    mag_auc: float
    auc_ci_low: float
    auc_ci_high: float
    baseline_resolution: float
    perm_null_p95: float
    perm_p_value: float
    direction_brier: float
    n_bootstrap: int
    n_permutation: int
    auc_floor_pass: bool
    auc_ci_pass: bool
    resolution_pass: bool
    min_sample_pass: bool
    passes: bool
    verdict: str
    source: str


def bootstrap_auc_ci(
    outcomes: list[float],
    probabilities: list[float],
    *,
    n_boot: int = DEFAULT_N_BOOTSTRAP,
    rng: random.Random,
    ci: float = 0.95,
) -> tuple[float, float]:
    """ADR-0023 §2.1: percentile bootstrap CI of the AUC, resampling OOS rows.

    Draws ``n_boot`` row-with-replacement resamples of the paired
    ``(outcome, probability)`` OOS points and returns the ``(low, high)``
    percentile bounds of the resampled AUC at confidence ``ci``. A resample that
    collapses to a single outcome class yields the degenerate ``roc_auc`` of
    0.5 (handled by :func:`ml.metrics.roc_auc`), which conservatively pulls the
    lower bound down rather than discarding the draw — a thin or near-degenerate
    family is therefore penalised, never flattered.
    """
    n = len(outcomes)
    if n == 0:
        return 0.0, 0.0
    aucs: list[float] = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        boot_y = [outcomes[i] for i in idx]
        boot_p = [probabilities[i] for i in idx]
        aucs.append(roc_auc(boot_y, boot_p))
    tail = (1.0 - ci) / 2.0
    low = _quantile(aucs, tail)
    high = _quantile(aucs, 1.0 - tail)
    return low, high


def permutation_resolution_null(
    outcomes: list[float],
    probabilities: list[float],
    *,
    n_perm: int = DEFAULT_N_PERMUTATION,
    rng: random.Random,
    n_bins: int = RESOLUTION_BINS,
) -> list[float]:
    """ADR-0023 §2.2: label-permutation null of the Murphy resolution.

    Shuffles the magnitude labels ``n_perm`` times while holding the forecasts
    (and therefore the resolution bin assignment) fixed, recomputing
    :func:`governance.family_feature_ab.resolution` each time. Because a shuffle
    permutes the SAME label multiset, the base rate is invariant and only the
    label-to-bin coupling is destroyed: the resulting distribution is exactly the
    resolution attainable by chance at this family's base rate, sample size, and
    forecast histogram. No absolute resolution constant is hard-coded, so the
    bar self-calibrates and cannot be tuned.
    """
    null: list[float] = []
    shuffled = list(outcomes)
    for _ in range(n_perm):
        rng.shuffle(shuffled)
        null.append(resolution(shuffled, probabilities, n_bins=n_bins))
    return null


def _permutation_p_value(observed: float, null: list[float]) -> float:
    """One-sided permutation p-value: P(null resolution >= observed).

    Uses the conventional ``(#{null >= observed} + 1) / (B + 1)`` add-one
    estimator so the p-value is never exactly zero (the observed value is itself
    one realisation under the null).
    """
    if not null:
        return 1.0
    ge = sum(1 for v in null if v >= observed)
    return (ge + 1) / (len(null) + 1)


def evaluate_family_magnitude_resolution(
    family: str,
    scores: list[float],
    returns: list[float],
    anchor_ts: list[float],
    guard_end_ts: list[float],
    *,
    mag_q: float = 0.5,
    min_oos: int = MIN_OOS_SAMPLES,
    n_boot: int = DEFAULT_N_BOOTSTRAP,
    n_perm: int = DEFAULT_N_PERMUTATION,
    seed: int = DEFAULT_SEED,
) -> MagnitudeResolutionResult | None:
    """Run the ADR-0023 §2 acceptance bar for one family. ``None`` if too thin.

    The score-alone magnitude OOS arm is the BASELINE arm of the existing
    leak-safe paired walk-forward
    (:func:`governance.family_calibration.walk_forward_ab` with both arms set to
    the score and ``label="magnitude"``); this reuses the shipped purge / fold /
    train-only quantile logic verbatim, adding no new labelling. The direction
    arm is measured the same way with ``label="direction"`` purely to report the
    status-quo direction-Brier the additive design retains.
    """
    mag = walk_forward_ab(
        scores,
        scores,
        returns,
        anchor_ts,
        guard_end_ts,
        min_oos=min_oos,
        label="magnitude",
        mag_q=mag_q,
    )
    if mag is None:
        return None

    probs = mag["baseline"]["probabilities"]
    outcomes = mag["baseline"]["outcomes"]
    n_oos = len(outcomes)

    mag_auc = roc_auc(outcomes, probs)
    base_res = resolution(outcomes, probs)

    rng = random.Random(seed)
    auc_ci_low, auc_ci_high = bootstrap_auc_ci(
        outcomes, probs, n_boot=n_boot, rng=rng
    )
    null = permutation_resolution_null(outcomes, probs, n_perm=n_perm, rng=rng)
    perm_null_p95 = _quantile(null, PERM_NULL_PERCENTILE)
    perm_p_value = _permutation_p_value(base_res, null)

    # Direction-Brier (status quo gate metric), reported for transparency. The
    # additive design (ADR-0023 §4) retains the existing brier_threshold check,
    # so this is a guard sanity read, not a blocker recomputed here.
    direction_brier = float("nan")
    dir_arm = walk_forward_ab(
        scores,
        scores,
        returns,
        anchor_ts,
        guard_end_ts,
        min_oos=min_oos,
        label="direction",
    )
    if dir_arm is not None:
        direction_brier = brier_score(
            dir_arm["baseline"]["outcomes"], dir_arm["baseline"]["probabilities"]
        )

    min_sample_pass = n_oos >= min_oos
    auc_floor_pass = mag_auc >= MAG_AUC_FLOOR
    auc_ci_pass = auc_ci_low >= MAG_AUC_CI_LOW_FLOOR
    resolution_pass = base_res > perm_null_p95
    passes = (
        min_sample_pass and auc_floor_pass and auc_ci_pass and resolution_pass
    )

    if not min_sample_pass:
        verdict = "inconclusive_thin_sample"
    elif passes:
        verdict = "passes_magnitude_resolution_floor"
    else:
        failed = [
            name
            for name, ok in (
                ("auc_floor", auc_floor_pass),
                ("auc_ci", auc_ci_pass),
                ("resolution_null", resolution_pass),
            )
            if not ok
        ]
        verdict = "fails_" + "+".join(failed)

    return MagnitudeResolutionResult(
        family=family,
        n_oos=n_oos,
        mag_auc=mag_auc,
        auc_ci_low=auc_ci_low,
        auc_ci_high=auc_ci_high,
        baseline_resolution=base_res,
        perm_null_p95=perm_null_p95,
        perm_p_value=perm_p_value,
        direction_brier=direction_brier,
        n_bootstrap=n_boot,
        n_permutation=n_perm,
        auc_floor_pass=auc_floor_pass,
        auc_ci_pass=auc_ci_pass,
        resolution_pass=resolution_pass,
        min_sample_pass=min_sample_pass,
        passes=passes,
        verdict=verdict,
        source=MAGNITUDE_GATE_SOURCE_TAG,
    )


def magnitude_resolution_report(
    calibration_samples: dict[str, dict[str, list[float]]],
    *,
    mag_q: float = 0.5,
    min_oos: int = MIN_OOS_SAMPLES,
    n_boot: int = DEFAULT_N_BOOTSTRAP,
    n_perm: int = DEFAULT_N_PERMUTATION,
    seed: int = DEFAULT_SEED,
) -> dict[str, MagnitudeResolutionResult]:
    """Run the §2 bar for every measurable family.

    ``calibration_samples`` is the bundle
    :func:`governance.family_returns.extract_family_calibration_samples`
    produces (score-alone, no candidate feature required). Families too thin to
    assemble ``min_oos`` shared OOS points are omitted.
    """
    out: dict[str, MagnitudeResolutionResult] = {}
    for family, samples in sorted(calibration_samples.items()):
        result = evaluate_family_magnitude_resolution(
            family,
            samples["scores"],
            samples["returns"],
            samples["anchor_ts"],
            samples["guard_end_ts"],
            mag_q=mag_q,
            min_oos=min_oos,
            n_boot=n_boot,
            n_perm=n_perm,
            seed=seed,
        )
        if result is not None:
            out[family] = result
    return out


__all__ = [
    "DEFAULT_N_BOOTSTRAP",
    "DEFAULT_N_PERMUTATION",
    "DEFAULT_SEED",
    "MAGNITUDE_GATE_SOURCE_TAG",
    "MAG_AUC_CI_LOW_FLOOR",
    "MAG_AUC_FLOOR",
    "PERM_NULL_PERCENTILE",
    "MagnitudeResolutionResult",
    "bootstrap_auc_ci",
    "evaluate_family_magnitude_resolution",
    "magnitude_resolution_report",
    "permutation_resolution_null",
]
