"""EV-06 (scaffold) — per-family PSR/MinTRL metrics producer.

This is the missing bridge between the C-sprint statistics and the X2
``PromotionGate``: it turns *real* per-family return series into the
PSR/MinTRL slice of a ``FamilyMetrics`` bundle that
``scripts/run_promotion_gate.py --metrics`` consumes.

Design contract — it does NOT fabricate data. The caller supplies the
forward-test return series per family; the producer:

1. asserts point-in-time validity of the return timestamps (EV-04) so a
   lookahead leak fails loudly before any statistic is computed;
2. builds the family's walk-forward folds (EV-05) to confirm the embargo
   config is applicable to the sample size;
3. computes PSR via :func:`probabilistic_sharpe` and the Minimum Track
   Record Length via :func:`min_trl` (both Bailey-López de Prado 2012),
   converting MinTRL observations to years.

It emits the metrics it genuinely measures: ``psr`` and ``mintrl_years``
(EV-06), and — added in EV-14 — ``fdr_pvalue``, the Benjamini-Hochberg
adjusted significance of a one-sided stationary-block bootstrap on the
same return series (C4). The raw per-family p-value is computed by
:func:`build_family_metrics_from_returns`; the BH adjustment is applied
across the families in :func:`build_bundle`, because a false discovery
rate is only defined over a set of tests, never one in isolation.

The remaining gate metrics (brier, ece, psi, live/wf) are filled by the
EV-15 calibration slice and the conformal coverage by the EV-16 conformal
slice — both ONLY when the caller supplies genuine ``(probability,
outcome)`` pairs per family; absent that evidence they stay ``None`` and
the gate honestly blocks the family as "not yet fully measured" rather
than being told a fabricated pass. The ``psi_slope`` field is filled by
the C9 PSI-trend slice (OLS slope of PSI over consecutive monitoring
windows) ONLY when the caller supplies those windows, else it stays
``None`` and the strict gate keeps blocking on "not measured".

The strict-mode provenance keys ``bootstrap_method``/``block_size``/
``stacked_used`` are NOT computed here — they describe upstream modelling
choices this producer cannot observe (it only receives the resulting
series). EV-17 therefore passes them through from a caller-declared
``provenance`` block, validated but never fabricated: absent → the key
stays undeclared → the strict gate blocks honestly. The producer still
refuses any caller attempt to override a key it computes itself
(:data:`PRODUCER_OWNED_PROVENANCE_KEYS`) so the audit trail cannot be
forged.

Roadmap pointer: Edge-Validation Roadmap, Phase 2 / stories EV-06, EV-14,
EV-15, EV-16, EV-17, EV-18 (C9 psi_slope).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from governance.family_significance import (
    block_bootstrap_pvalue,
    family_fdr_qvalues,
)
from governance.family_walkforward import family_outcome_horizon, get_family_config
from governance.point_in_time import TimestampLike, assert_point_in_time
from ml.calibration.conformal import SplitConformalClassifier
from ml.metrics import (
    brier_score,
    expected_calibration_error,
    population_stability_index,
)
from ml.walkforward import walk_forward_from_config
from open_prep.stats_helpers import (
    MIN_OBSERVATIONS_FOR_PSR,
    min_trl,
    probabilistic_sharpe,
)
from scripts.smc_atomic_write import atomic_write_json
from scripts.bootstrap_methods import stationary_block_bootstrap

# PSR method tag recorded in provenance for audit (matches the gate's
# expected ``psr_method`` provenance key, C6.1).
PSR_METHOD_TAG = "bailey_lopez_de_prado_2012"

# C4 significance provenance tags.
SIGNIFICANCE_METHOD_TAG = "stationary_block_bootstrap_one_sided"
FDR_METHOD_TAG = "benjamini_hochberg"
# Bootstrap resamples for the per-family significance p-value. 2000 gives a
# p-value resolution of ~1/2001 — well below the 0.05 FDR-q threshold.
DEFAULT_SIGNIFICANCE_B = 2000

# C3/C9 calibration provenance tag. Recorded only when the caller supplies
# genuine (probability, outcome) pairs so brier/ece/psi/live-wf are measured
# empirically rather than fabricated.
CALIBRATION_METHOD_TAG = "empirical_brier_ece_psi"

# GAP-4 block-bootstrap Brier CI (deferred follow-up in the EV-24 calibration
# review, now wired). The headline Brier is a point estimate; under serial
# dependence its sampling distribution is wide at the few-hundred-event scale.
# We resample the per-event Brier loss series with the stationary block
# bootstrap (Politis-Romano 1994) to preserve autocorrelation, then gate on
# the 95th-percentile upper bound. Constants are pinned for determinism.
BRIER_CI_B = 2000
BRIER_CI_MEAN_BLOCK_LENGTH = 5
BRIER_CI_ALPHA = 0.05  # upper bound = (1 - alpha) quantile = 95th percentile
BRIER_CI_SEED = 42
# Below this many OOS events the block-bootstrap CI is too noisy to trust, so
# we leave ``brier_ci_upper`` as None ("not yet measured") rather than ship a
# misleadingly tight or wild interval. Mirrors MIN_EVENTS_FOR_BOOTSTRAP.
BRIER_CI_MIN_SAMPLES = 30
BRIER_CI_METHOD_TAG = "stationary_block_bootstrap_brier_p95"

# C10 conformal provenance tag. Recorded only when the caller supplies a
# split-conformal calibration + test set so coverage is measured, not assumed.
CONFORMAL_METHOD_TAG = "split_conformal_vovk"

# C9 PSI-trend provenance tag. Recorded only when the caller supplies a
# reference distribution plus >=2 consecutive monitoring windows so the PSI
# drift slope is measured by OLS, not assumed.
PSI_TREND_METHOD_TAG = "ols_psi_window_slope"

# EV-17 provenance architecture.
#
# Provenance splits into two ownership classes:
#
#   1. PRODUCER-OWNED — keys this script COMPUTES from real config/data and
#      therefore declares itself. The caller must never override these, else
#      it could silently forge the audit trail (e.g. claim "purged_kfold"
#      while the producer actually ran "expanding").
#
#   2. CALLER-DECLARED — upstream MODELLING metadata this producer cannot
#      know because it only receives the resulting return/probability series,
#      not the training pipeline that produced them. The gate's strict mode
#      requires three such keys, each owned by an upstream sprint:
#        * bootstrap_method  → C3.1 BCa bootstrap for brier CIs
#        * block_size        → C4.1 block-permutation block size
#        * stacked_used      → C10.1 whether a stacking ensemble was used
#      These are PASSED THROUGH from spec.provenance, validated but never
#      fabricated: absent → the key stays absent → strict gate honestly
#      blocks the family as "provenance not declared".
PRODUCER_OWNED_PROVENANCE_KEYS = frozenset({
    "wf_scheme",
    "wf_embargo_bars",
    "psr_method",
    "significance_method",
    "significance_block_bars",
    "fdr_method",
    "calibration_method",
    "conformal_method",
    "psi_trend_method",
})


def _merge_caller_provenance(
    family: str,
    producer_provenance: dict[str, Any],
    caller_provenance: dict[str, Any] | None,
) -> None:
    """Merge caller-declared upstream provenance into ``producer_provenance``.

    Mutates ``producer_provenance`` in place. Refuses any key the producer
    owns itself (:data:`PRODUCER_OWNED_PROVENANCE_KEYS`) so a caller cannot
    overwrite a computed audit value with a fabricated one. Everything else
    (e.g. ``bootstrap_method``/``block_size``/``stacked_used`` plus any extra
    upstream metadata) is copied through verbatim.
    """
    if caller_provenance is None:
        return
    if not isinstance(caller_provenance, dict):
        raise ValueError(f"{family}: provenance must be a mapping")
    collisions = PRODUCER_OWNED_PROVENANCE_KEYS & caller_provenance.keys()
    if collisions:
        raise ValueError(
            f"{family}: provenance may not override producer-owned keys "
            f"{sorted(collisions)} (these are computed from real config/data)"
        )
    producer_provenance.update(caller_provenance)


def _binary_calibration_pairs(
    label: str, block: dict[str, Any]
) -> tuple[list[float], list[float]]:
    """Validate and extract a ``(probabilities, outcomes)`` calibration pair.

    Refuses anything that would make the resulting Brier/ECE a fabrication
    rather than a measurement: missing keys, length mismatch, empty input,
    probabilities outside ``[0, 1]`` or outcomes that are not binary.
    """
    probs = block.get("probabilities")
    outcomes = block.get("outcomes")
    if probs is None or outcomes is None:
        raise ValueError(
            f"{label}: calibration block needs both 'probabilities' and 'outcomes'"
        )
    p = [float(x) for x in probs]
    y = [float(x) for x in outcomes]
    if len(p) != len(y):
        raise ValueError(
            f"{label}: probabilities length {len(p)} != outcomes length {len(y)}"
        )
    if not p:
        raise ValueError(f"{label}: calibration block must be non-empty")
    if any(not 0.0 <= v <= 1.0 for v in p):
        raise ValueError(f"{label}: probabilities must lie in [0, 1]")
    if any(v not in (0.0, 1.0) for v in y):
        raise ValueError(f"{label}: outcomes must be binary (0 or 1)")
    return p, y


def _brier_block_bootstrap_ci_upper(
    probabilities: list[float], outcomes: list[float]
) -> float | None:
    """Upper bound of the block-bootstrap CI on the Brier score (GAP-4).

    Brier = mean of the per-event squared error ``(p - y)**2``. We resample
    that loss series with the stationary block bootstrap so within-block serial
    dependence is preserved, take each resample's mean (a bootstrapped Brier),
    and return the ``(1 - BRIER_CI_ALPHA)`` quantile as the one-sided upper
    bound the gate blocks on. Returns ``None`` below ``BRIER_CI_MIN_SAMPLES``
    so a too-noisy interval is reported as "not yet measured", never faked.
    """
    n = len(probabilities)
    if n < BRIER_CI_MIN_SAMPLES:
        return None
    import numpy as np

    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(outcomes, dtype=np.float64)
    squared_error = (p - y) ** 2
    resamples = stationary_block_bootstrap(
        squared_error,
        mean_block_length=BRIER_CI_MEAN_BLOCK_LENGTH,
        B=BRIER_CI_B,
        seed=BRIER_CI_SEED,
    )
    brier_distribution = resamples.mean(axis=1)
    return float(np.quantile(brier_distribution, 1.0 - BRIER_CI_ALPHA))


def _calibration_slice(
    family: str, calibration: dict[str, Any] | None
) -> dict[str, float | None]:
    """Compute the brier/ece/psi/live-wf gate slice from supplied pairs.

    Each sub-block is optional and filled ONLY from real data the caller
    provides; anything not supplied stays ``None`` so the gate keeps
    blocking on "not yet measured" rather than a fabricated pass.

      * ``walkforward`` {probabilities, outcomes} -> brier, ece,
        walkforward_brier (the headline gate Brier IS the walk-forward
        out-of-sample Brier; both slots carry the same measurement).
      * ``live`` {probabilities, outcomes} -> live_brier.
      * ``reference_probabilities`` (+ a ``live`` block) -> psi, the
        population-stability drift of the live probability distribution
        against the reference (training) distribution.
    """
    slice_out: dict[str, float | None] = {
        "brier": None,
        "brier_ci_upper": None,
        "brier_ci_method": None,
        "ece": None,
        "walkforward_brier": None,
        "live_brier": None,
        "psi": None,
        "calibration_method": None,
    }
    if calibration is None:
        return slice_out

    wf = calibration.get("walkforward")
    if wf is not None:
        p, y = _binary_calibration_pairs(f"{family} walkforward", wf)
        wf_brier = brier_score(y, p)
        slice_out["brier"] = wf_brier
        slice_out["walkforward_brier"] = wf_brier
        slice_out["ece"] = expected_calibration_error(y, p)
        brier_ci_upper = _brier_block_bootstrap_ci_upper(p, y)
        slice_out["brier_ci_upper"] = brier_ci_upper
        if brier_ci_upper is not None:
            slice_out["brier_ci_method"] = BRIER_CI_METHOD_TAG
        slice_out["calibration_method"] = CALIBRATION_METHOD_TAG

    live_probs: list[float] | None = None
    live = calibration.get("live")
    if live is not None:
        lp, ly = _binary_calibration_pairs(f"{family} live", live)
        slice_out["live_brier"] = brier_score(ly, lp)
        live_probs = lp
        slice_out["calibration_method"] = CALIBRATION_METHOD_TAG

    reference = calibration.get("reference_probabilities")
    if reference is not None:
        if live_probs is None:
            raise ValueError(
                f"{family}: PSI needs calibration.live.probabilities as the "
                "live distribution to compare against reference_probabilities"
            )
        ref = [float(x) for x in reference]
        if not ref:
            raise ValueError(f"{family}: reference_probabilities must be non-empty")
        if any(not 0.0 <= v <= 1.0 for v in ref):
            raise ValueError(f"{family}: reference_probabilities must lie in [0, 1]")
        slice_out["psi"] = population_stability_index(ref, live_probs)
        slice_out["calibration_method"] = CALIBRATION_METHOD_TAG

    return slice_out


def _ols_slope(values: list[float]) -> float:
    """OLS slope of ``values`` regressed on their 0-based index.

    Pure-Python (the module deliberately avoids a numpy dependency). The
    caller guarantees ``len(values) >= 2`` so the index variance ``den`` is
    strictly positive.
    """
    n = len(values)
    xbar = (n - 1) / 2.0
    ybar = sum(values) / n
    num = 0.0
    den = 0.0
    for i, v in enumerate(values):
        dx = i - xbar
        num += dx * (v - ybar)
        den += dx * dx
    return num / den


def _psi_trend_slice(
    family: str, psi_trend: dict[str, Any] | None
) -> dict[str, Any]:
    """Compute the C9 PSI-trend slope from a sequence of monitoring windows.

    Measures whether population drift is WORSENING over time rather than the
    single-snapshot drift that :func:`_calibration_slice` reports. PSI is
    computed for each consecutive monitoring window against a fixed reference
    (training) distribution, an OLS line is fit to that PSI series, and its
    per-window slope is returned as ``psi_slope``. A positive slope means
    drift is accelerating; the gate alarms above ``psi_slope_max``
    (0.05/window by default).

    Filled ONLY from supplied data; absent → ``psi_slope`` stays ``None`` so
    the strict gate keeps blocking the family on "not yet measured" rather
    than a fabricated stable trend.
    """
    slice_out: dict[str, Any] = {"psi_slope": None, "psi_trend_method": None}
    if psi_trend is None:
        return slice_out

    reference = psi_trend.get("reference_probabilities")
    windows = psi_trend.get("windows")
    if reference is None or windows is None:
        raise ValueError(
            f"{family}: psi_trend needs both 'reference_probabilities' and "
            "'windows'"
        )
    ref = [float(x) for x in reference]
    if not ref:
        raise ValueError(
            f"{family}: psi_trend reference_probabilities must be non-empty"
        )
    if any(not 0.0 <= v <= 1.0 for v in ref):
        raise ValueError(
            f"{family}: psi_trend reference_probabilities must lie in [0, 1]"
        )
    if not isinstance(windows, list) or len(windows) < 2:
        raise ValueError(
            f"{family}: psi_trend.windows needs at least 2 windows to fit a slope"
        )

    psi_series: list[float] = []
    for idx, window in enumerate(windows):
        w = [float(x) for x in window]
        if not w:
            raise ValueError(f"{family}: psi_trend.windows[{idx}] must be non-empty")
        if any(not 0.0 <= v <= 1.0 for v in w):
            raise ValueError(
                f"{family}: psi_trend.windows[{idx}] must lie in [0, 1]"
            )
        psi_series.append(population_stability_index(ref, w))

    slice_out["psi_slope"] = _ols_slope(psi_series)
    slice_out["psi_trend_method"] = PSI_TREND_METHOD_TAG
    return slice_out


def _conformal_slice(
    family: str, conformal: dict[str, Any] | None
) -> dict[str, float | None]:
    """Compute the conformal coverage gate slice from supplied pairs.

    Split-conformal (Vovk) is calibrated on the ``calibration`` block and
    its empirical marginal coverage is measured on the held-out ``test``
    block. The gate target is ``1 - alpha`` (the conformal guarantee).
    Returns all-``None`` when no conformal block is supplied so the gate
    keeps blocking on "not yet measured".
    """
    slice_out: dict[str, float | None] = {
        "conformal_coverage": None,
        "conformal_target": None,
        "conformal_method": None,
    }
    if conformal is None:
        return slice_out

    alpha = float(conformal.get("alpha", 0.1))
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"{family}: conformal alpha must be in (0, 1), got {alpha}")
    cal = conformal.get("calibration")
    test = conformal.get("test")
    if cal is None or test is None:
        raise ValueError(
            f"{family}: conformal block needs both 'calibration' and 'test' "
            "{{probabilities, outcomes}} sets"
        )
    cal_p, cal_y = _binary_calibration_pairs(f"{family} conformal calibration", cal)
    test_p, test_y = _binary_calibration_pairs(f"{family} conformal test", test)

    clf = SplitConformalClassifier(alpha=alpha)
    clf.calibrate(cal_p, cal_y)
    report = clf.evaluate(test_p, test_y)
    slice_out["conformal_coverage"] = float(report.empirical_coverage)
    slice_out["conformal_target"] = float(1.0 - alpha)
    slice_out["conformal_method"] = CONFORMAL_METHOD_TAG
    return slice_out


def build_family_metrics_from_returns(
    family: str,
    returns: list[float],
    *,
    periods_per_year: int = 252,
    sr_star: float = 0.0,
    alpha: float = 0.05,
    timestamps: list[TimestampLike] | None = None,
    as_of: TimestampLike | None = None,
    significance_B: int = DEFAULT_SIGNIFICANCE_B,
    significance_seed: int = 0,
    calibration: dict[str, Any] | None = None,
    conformal: dict[str, Any] | None = None,
    psi_trend: dict[str, Any] | None = None,
    regime_degraded: bool | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the PSR/MinTRL slice of a ``FamilyMetrics`` dict for *family*.

    Parameters
    ----------
    returns:
        Per-period forward-test returns at the chosen frequency.
    periods_per_year:
        Used to convert the MinTRL observation count to years (the unit
        the gate's ``mintrl_max_years`` threshold expects).
    timestamps / as_of:
        When both are given, the return timestamps are asserted to be at
        or before ``as_of`` (EV-04 lookahead tripwire) before any stat is
        computed.
    calibration:
        Optional per-family calibration evidence (EV-15). A mapping with
        any of ``walkforward`` / ``live`` (each ``{probabilities,
        outcomes}``) and ``reference_probabilities``. Supplied blocks are
        turned into ``brier``/``ece``/``walkforward_brier`` (walkforward),
        ``live_brier`` (live) and ``psi`` (reference-vs-live). Omitted
        blocks leave their gate fields ``None`` so the gate keeps blocking
        on "not yet measured".
    conformal:
        Optional per-family conformal evidence (EV-16). A mapping with
        ``alpha`` (default 0.1) plus ``calibration`` and ``test`` blocks
        (each ``{probabilities, outcomes}``). Split-conformal is fitted on
        the calibration block and its empirical coverage is measured on
        the test block, filling ``conformal_coverage`` and
        ``conformal_target`` (= 1 - alpha). Omitted leaves both ``None``.
    psi_trend:
        Optional per-family PSI-trend evidence (C9). A mapping with
        ``reference_probabilities`` plus ``windows`` (a list of >=2
        consecutive monitoring probability arrays). PSI is computed per
        window against the reference and an OLS slope is fit to the series,
        filling ``psi_slope``. Omitted leaves ``psi_slope`` ``None`` so the
        gate keeps blocking on "not yet measured".
    regime_degraded:
        Optional per-family C5.1 regime-degradation verdict (EV#7): a caller-
        computed ``bool`` (``True`` = the family has no edge in the regime it
        would trade next; ``False`` = measured, not degraded). Passed through
        verbatim to the gate. Omitted/``None`` leaves it undeclared so the gate
        keeps blocking on "regime_degraded not yet measured".
    provenance:
        Optional caller-declared upstream provenance (EV-17): metadata the
        producer cannot compute because it only receives the resulting
        series, not the training pipeline (e.g. ``bootstrap_method``,
        ``block_size``, ``stacked_used`` for the strict gate). Merged into
        the output provenance after validation; keys the producer owns
        itself are refused to prevent audit-trail forgery. Omitted leaves
        the strict provenance keys undeclared so the gate blocks honestly.

    Returns a ``FamilyMetrics``-shaped dict (numeric fields it does not
    measure are set to ``None``).
    """
    if periods_per_year <= 0:
        raise ValueError(
            f"{family}: periods_per_year must be positive, got {periods_per_year}"
        )
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"{family}: alpha must be in (0, 1), got {alpha}")

    # The EV-04 lookahead guard needs BOTH sides of the boundary. Supplying
    # only one silently skips the tripwire, so reject the half-specified case
    # rather than computing metrics with no point-in-time proof.
    if (timestamps is None) != (as_of is None):
        raise ValueError(
            f"{family}: timestamps and as_of must be provided together "
            "(or both omitted) for the EV-04 point-in-time guard"
        )
    if timestamps is not None and as_of is not None:
        if len(timestamps) != len(returns):
            raise ValueError(
                f"{family}: timestamps length {len(timestamps)} != returns "
                f"length {len(returns)}"
            )
        assert_point_in_time(timestamps, as_of, label=f"{family} return")

    n = len(returns)
    if n < MIN_OBSERVATIONS_FOR_PSR:
        raise ValueError(
            f"{family}: need at least {MIN_OBSERVATIONS_FOR_PSR} returns for "
            f"PSR, got {n}"
        )

    config = get_family_config(family)
    horizon = family_outcome_horizon(family)
    # Confirm the embargo config is applicable to this sample and purge
    # label-horizon overlap; raises if the sample is too small.
    walk_forward_from_config(n, config, outcome_horizon=horizon)

    psr_res = probabilistic_sharpe(returns, sr_star=sr_star)
    sr_hat = psr_res["sharpe_hat"]
    skew = psr_res["skew"]
    kurtosis = psr_res["kurtosis"]

    # C4 significance: one-sided stationary-block bootstrap p-value for
    # mean(net return) > 0. Block length = the family outcome horizon so
    # returns that overlap over the label window are resampled in blocks
    # (an i.i.d. bootstrap here would be anti-conservative). This is the RAW
    # per-family p-value; the FDR adjustment across families happens in
    # ``build_bundle`` (a false discovery rate is undefined for one test).
    raw_pvalue = block_bootstrap_pvalue(
        returns,
        block_length=horizon,
        B=significance_B,
        seed=significance_seed,
    )

    if sr_hat <= sr_star:
        # No detectable edge → MinTRL undefined. Leave None so the gate blocks
        # on "not measured" honestly. Any OTHER min_trl failure (bad alpha,
        # collapsed non-Gaussian variance term) is a real error and must
        # propagate rather than masquerade as an unmeasured edge.
        mintrl_years: float | None = None
    else:
        n_needed = min_trl(sr_hat, sr_star, skew, kurtosis, alpha=alpha)
        mintrl_years = n_needed / periods_per_year

    # EV-15 calibration slice: brier/ece/psi/live-wf measured ONLY from the
    # genuine (probability, outcome) pairs the caller supplies. Anything not
    # supplied stays None below so the gate still blocks on "not measured".
    cal = _calibration_slice(family, calibration)

    # EV-16 conformal slice: empirical split-conformal coverage vs target,
    # measured ONLY from supplied calibration+test pairs, else None.
    conf = _conformal_slice(family, conformal)

    # C9 PSI-trend slice: OLS slope of PSI over consecutive monitoring
    # windows vs a fixed reference, measured ONLY from supplied windows,
    # else None so the strict gate keeps blocking on "not measured".
    psi_trend_res = _psi_trend_slice(family, psi_trend)

    provenance_out: dict[str, Any] = {
        "wf_scheme": config.scheme,
        "wf_embargo_bars": config.embargo_bars,
        "psr_method": PSR_METHOD_TAG,
        "significance_method": SIGNIFICANCE_METHOD_TAG,
        "significance_block_bars": int(min(horizon, n - 1)),
        "fdr_method": FDR_METHOD_TAG,
    }
    if cal["calibration_method"] is not None:
        provenance_out["calibration_method"] = cal["calibration_method"]
    if cal["brier_ci_method"] is not None:
        provenance_out["brier_ci_method"] = cal["brier_ci_method"]
    if conf["conformal_method"] is not None:
        provenance_out["conformal_method"] = conf["conformal_method"]
    if psi_trend_res["psi_trend_method"] is not None:
        provenance_out["psi_trend_method"] = psi_trend_res["psi_trend_method"]

    # EV-17: merge caller-declared upstream provenance (bootstrap_method,
    # block_size, stacked_used, ...) the producer cannot compute itself.
    # Refuses collisions with producer-owned keys; absent keys stay absent.
    _merge_caller_provenance(family, provenance_out, provenance)

    return {
        "family": family,
        "psr": psr_res["psr"],
        "mintrl_years": mintrl_years,
        # EV-15: filled from supplied calibration pairs, else None.
        "brier": cal["brier"],
        # GAP-4: block-bootstrap Brier CI upper bound, else None.
        "brier_ci_upper": cal["brier_ci_upper"],
        "ece": cal["ece"],
        # fdr_pvalue stays None per family: a false discovery rate is only
        # defined over a SET of tests. build_bundle fills it by applying the
        # Benjamini-Hochberg adjustment to extras.raw_pvalue across families.
        "fdr_pvalue": None,
        "psi": cal["psi"],
        "live_brier": cal["live_brier"],
        "walkforward_brier": cal["walkforward_brier"],
        # C9: filled from supplied PSI monitoring windows, else None.
        "psi_slope": psi_trend_res["psi_slope"],
        # C5.1: caller-supplied regime-degradation verdict (EV#7), passed
        # through verbatim. None keeps the gate blocking "not yet measured".
        "regime_degraded": regime_degraded,
        "conformal_coverage": conf["conformal_coverage"],
        "conformal_target": conf["conformal_target"],
        "provenance": provenance_out,
        "extras": {
            "sharpe_hat": sr_hat,
            "skew": skew,
            "kurtosis": kurtosis,
            "n_returns": float(n),
            "periods_per_year": float(periods_per_year),
            "raw_pvalue": raw_pvalue,
        },
    }


def build_bundle(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a bundle list from an input spec.

    Spec shape::

        {
          "periods_per_year": 252,
          "significance_seed": 0,      # optional, bootstrap determinism
          "significance_B": 2000,      # optional, bootstrap resamples
          "families": {
            "BOS": {"returns": [...], "timestamps": [...]?, "as_of": "..."?,
                    "calibration": {                  # optional, EV-15
                       "walkforward": {"probabilities": [...], "outcomes": [...]},
                       "live": {"probabilities": [...], "outcomes": [...]},
                       "reference_probabilities": [...]
                    },
                    "conformal": {                    # optional, EV-16
                       "alpha": 0.1,
                       "calibration": {"probabilities": [...], "outcomes": [...]},
                       "test": {"probabilities": [...], "outcomes": [...]}
                    },
                    "psi_trend": {                    # optional, C9
                       "reference_probabilities": [...],
                       "windows": [[...], [...], ...]  # >=2 windows
                    },
                    "provenance": {                   # optional, EV-17
                       "bootstrap_method": "bca",      # C3.1 (caller-declared)
                       "block_size": 64,              # C4.1 (caller-declared)
                       "stacked_used": true           # C10.1 (caller-declared)
                    }},
            ...
          }
        }

    The returned bundle carries a BH-adjusted ``fdr_pvalue`` per family,
    controlled across exactly the families present in ``spec``.
    """
    periods_per_year = int(spec.get("periods_per_year", 252))
    significance_seed = int(spec.get("significance_seed", 0))
    significance_B = int(spec.get("significance_B", DEFAULT_SIGNIFICANCE_B))
    families = spec.get("families")
    if not isinstance(families, dict) or not families:
        raise ValueError("spec.families must be a non-empty object")

    bundle: list[dict[str, Any]] = []
    for family, payload in families.items():
        if not isinstance(payload, dict) or "returns" not in payload:
            raise ValueError(f"family {family!r} must provide a 'returns' list")
        bundle.append(
            build_family_metrics_from_returns(
                family,
                [float(r) for r in payload["returns"]],
                periods_per_year=periods_per_year,
                sr_star=float(payload.get("sr_star", 0.0)),
                alpha=float(payload.get("alpha", 0.05)),
                timestamps=payload.get("timestamps"),
                as_of=payload.get("as_of"),
                significance_B=significance_B,
                significance_seed=significance_seed,
                calibration=payload.get("calibration"),
                conformal=payload.get("conformal"),
                psi_trend=payload.get("psi_trend"),
                regime_degraded=payload.get("regime_degraded"),
                provenance=payload.get("provenance"),
            )
        )

    # C4 FDR control: adjust the raw per-family bootstrap p-values across the
    # families actually evaluated in this run, then write the BH q-value into
    # each family's gate-facing ``fdr_pvalue`` slot.
    raw_by_family = {m["family"]: m["extras"]["raw_pvalue"] for m in bundle}
    qvalues = family_fdr_qvalues(raw_by_family)
    for metric in bundle:
        metric["fdr_pvalue"] = qvalues[metric["family"]]

    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "EV-06 scaffold: compute the PSR/MinTRL slice of a FamilyMetrics "
            "bundle from real per-family return series."
        )
    )
    parser.add_argument(
        "--spec",
        type=Path,
        required=True,
        help="Path to an input JSON spec (periods_per_year + families.returns).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the FamilyMetrics bundle JSON (consumed by "
        "run_promotion_gate.py --metrics).",
    )
    args = parser.parse_args(argv)

    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        bundle = build_bundle(spec)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(bundle, args.output, indent=2, sort_keys=False)
    print(f"wrote {len(bundle)} family metric(s) to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
