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
than being told a fabricated pass. The ``psi_slope`` field stays ``None``
(it needs the C9 PSI-trend producer), as do the strict-mode provenance
keys ``bootstrap_method``/``block_size``/``stacked_used`` which this
script does not own.

Roadmap pointer: Edge-Validation Roadmap, Phase 2 / stories EV-06, EV-14,
EV-15, EV-16.
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

# C10 conformal provenance tag. Recorded only when the caller supplies a
# split-conformal calibration + test set so coverage is measured, not assumed.
CONFORMAL_METHOD_TAG = "split_conformal_vovk"


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

    provenance: dict[str, Any] = {
        "wf_scheme": config.scheme,
        "wf_embargo_bars": config.embargo_bars,
        "psr_method": PSR_METHOD_TAG,
        "significance_method": SIGNIFICANCE_METHOD_TAG,
        "significance_block_bars": int(min(horizon, n - 1)),
        "fdr_method": FDR_METHOD_TAG,
    }
    if cal["calibration_method"] is not None:
        provenance["calibration_method"] = cal["calibration_method"]
    if conf["conformal_method"] is not None:
        provenance["conformal_method"] = conf["conformal_method"]

    return {
        "family": family,
        "psr": psr_res["psr"],
        "mintrl_years": mintrl_years,
        # EV-15: filled from supplied calibration pairs, else None.
        "brier": cal["brier"],
        "ece": cal["ece"],
        # fdr_pvalue stays None per family: a false discovery rate is only
        # defined over a SET of tests. build_bundle fills it by applying the
        # Benjamini-Hochberg adjustment to extras.raw_pvalue across families.
        "fdr_pvalue": None,
        "psi": cal["psi"],
        "live_brier": cal["live_brier"],
        "walkforward_brier": cal["walkforward_brier"],
        # Honestly not measured by this producer (other C-sprints own them):
        "psi_slope": None,
        "conformal_coverage": conf["conformal_coverage"],
        "conformal_target": conf["conformal_target"],
        "provenance": provenance,
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
