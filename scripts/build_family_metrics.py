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

It deliberately emits ONLY the metrics it genuinely measures (``psr``,
``mintrl_years``) plus the walk-forward / PSR provenance it owns. The
remaining gate metrics (brier, ece, fdr_pvalue, psi, conformal, live/wf)
stay ``None`` — the gate then honestly blocks the family as "not yet
fully measured" rather than being told a fabricated pass. Those fields
are filled by their own C-sprint producers (C3 BCa bootstrap, C4 block
permutation, C9 PSI, C10 conformal) as the roadmap progresses.

Roadmap pointer: Edge-Validation Roadmap, Phase 2 / story EV-06.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from governance.family_walkforward import family_outcome_horizon, get_family_config
from governance.point_in_time import TimestampLike, assert_point_in_time
from ml.walkforward import walk_forward_from_config
from open_prep.stats_helpers import (
    MIN_OBSERVATIONS_FOR_PSR,
    min_trl,
    probabilistic_sharpe,
)

# PSR method tag recorded in provenance for audit (matches the gate's
# expected ``psr_method`` provenance key, C6.1).
PSR_METHOD_TAG = "bailey_lopez_de_prado_2012"


def build_family_metrics_from_returns(
    family: str,
    returns: list[float],
    *,
    periods_per_year: int = 252,
    sr_star: float = 0.0,
    alpha: float = 0.05,
    timestamps: list[TimestampLike] | None = None,
    as_of: TimestampLike | None = None,
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

    Returns a ``FamilyMetrics``-shaped dict (numeric fields it does not
    measure are set to ``None``).
    """
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

    try:
        n_needed = min_trl(sr_hat, sr_star, skew, kurtosis, alpha=alpha)
        mintrl_years: float | None = n_needed / periods_per_year
    except ValueError:
        # sr_hat <= sr_star: no detectable edge → MinTRL undefined.
        # Leave None so the gate blocks on "not measured" honestly.
        mintrl_years = None

    return {
        "family": family,
        "psr": psr_res["psr"],
        "mintrl_years": mintrl_years,
        # Honestly not measured by this producer (other C-sprints own them):
        "brier": None,
        "ece": None,
        "fdr_pvalue": None,
        "psi": None,
        "live_brier": None,
        "walkforward_brier": None,
        "psi_slope": None,
        "conformal_coverage": None,
        "conformal_target": None,
        "provenance": {
            "wf_scheme": config.scheme,
            "wf_embargo_bars": config.embargo_bars,
            "psr_method": PSR_METHOD_TAG,
        },
        "extras": {
            "sharpe_hat": sr_hat,
            "skew": skew,
            "kurtosis": kurtosis,
            "n_returns": float(n),
            "periods_per_year": float(periods_per_year),
        },
    }


def build_bundle(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a bundle list from an input spec.

    Spec shape::

        {
          "periods_per_year": 252,
          "families": {
            "BOS": {"returns": [...], "timestamps": [...]?, "as_of": "..."?},
            ...
          }
        }
    """
    periods_per_year = int(spec.get("periods_per_year", 252))
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
            )
        )
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
    args.output.write_text(
        json.dumps(bundle, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(bundle)} family metric(s) to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
