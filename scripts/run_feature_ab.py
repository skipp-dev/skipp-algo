"""ADR-0019 paired A/B driver: does a recorded candidate feature lift resolution?

This is the on-ramp on top of the harness (#2528, ``governance.family_returns``
+ ``governance.family_feature_ab``): a single command that turns recorded
:class:`~governance.family_returns.FamilyEvent` records into a per-family
pre-registered purged walk-forward A/B verdict for any feature the adapter
records (e.g. ``relative_volume``).

It is SHADOW-ONLY. It reads events, runs the leak-safe paired A/B, and prints a
verdict. It NEVER wires a feature into the gate or the score -- that wiring is
gated on a ``candidate_lifts_resolution`` verdict on REAL data, per ADR-0019.

Input
-----
A JSON file containing a list of ``FamilyEvent`` records (the same dicts the
adapter emits), OR ``-`` to read that list from stdin. Each event that carries
both a v1 ``score`` and the candidate ``--feature-key`` plus forward bars
contributes a paired sample.

Exit codes
----------
* ``0`` -- at least one family returned ``candidate_lifts_resolution`` (A/B
  mode) or ``regime_conditions_resolution`` (``--stratify-by`` mode).
* ``2`` -- families were measurable but NONE lifted resolution / showed a regime
  effect. The candidate is not validated.
* ``3`` -- no family produced a verdict (every paired sample was too thin).
* ``1`` -- usage/config error (bad path, malformed JSON, empty event list).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Literal

from governance.family_feature_ab import family_feature_ab_report
from governance.family_feature_regime import family_feature_regime_report
from governance.family_returns import DEFAULT_COST_BPS, extract_family_ab_samples
from scripts.smc_atomic_write import atomic_write_text


def _load_events(path: str) -> list[dict[str, Any]]:
    if path == "-":
        payload = json.load(sys.stdin)
    else:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(
            f"expected a JSON list of FamilyEvent records, got {type(payload).__name__}"
        )
    return payload


def build_report(
    events: list[dict[str, Any]],
    *,
    feature_key: str,
    cost_bps: float,
    label: Literal["direction", "magnitude"] = "direction",
    mag_q: float = 0.5,
) -> dict[str, Any]:
    """Assemble the paired samples and run the A/B for every measurable family.

    ``label`` selects the outcome the A/B grades against: ``"direction"`` (the
    sign of the net forward return, the default) or ``"magnitude"`` (whether the
    move's size clears a per-fold ``mag_q`` quantile of |return| -- a leak-safe,
    fold-relative volatility label). ``mag_q`` is ignored for ``"direction"``.
    """
    ab_samples = extract_family_ab_samples(
        events, feature_key=feature_key, cost_bps=cost_bps
    )
    report = family_feature_ab_report(ab_samples, label=label, mag_q=mag_q)
    lifted = sorted(
        family
        for family, result in report.items()
        if result["verdict"] == "candidate_lifts_resolution"
    )
    return {
        "feature_key": feature_key,
        "cost_bps": cost_bps,
        "label": label,
        "mag_q": mag_q,
        "families_measured": sorted(report),
        "families_lifted": lifted,
        "results": report,
    }


def _verdict_exit_code(report: dict[str, Any]) -> int:
    if not report["results"]:
        return 3
    if report["families_lifted"]:
        return 0
    return 2


def build_regime_report(
    events: list[dict[str, Any]],
    *,
    feature_key: str,
    cost_bps: float,
    stratify_by: Literal["abs_feature", "feature"],
    n_strata: int,
    label: Literal["direction", "magnitude"] = "direction",
    mag_q: float = 0.5,
) -> dict[str, Any]:
    """Run the regime-FILTER measurement for every measurable family.

    Instead of asking whether the feature lifts resolution on its own, this
    partitions the SCORE-ALONE arm by a regime derived from the feature and
    reports where the score is best resolved. ``conditioned`` lists the families
    whose verdict is ``regime_conditions_resolution``.
    """
    ab_samples = extract_family_ab_samples(
        events, feature_key=feature_key, cost_bps=cost_bps
    )
    report = family_feature_regime_report(
        ab_samples,
        n_strata=n_strata,
        stratify_by=stratify_by,
        label=label,
        mag_q=mag_q,
    )
    conditioned = sorted(
        family
        for family, result in report.items()
        if result["verdict"] == "regime_conditions_resolution"
    )
    return {
        "feature_key": feature_key,
        "cost_bps": cost_bps,
        "mode": "regime",
        "stratify_by": stratify_by,
        "n_strata": n_strata,
        "label": label,
        "mag_q": mag_q,
        "families_measured": sorted(report),
        "families_conditioned": conditioned,
        "results": report,
    }


def _regime_exit_code(report: dict[str, Any]) -> int:
    if not report["results"]:
        return 3
    if report["families_conditioned"]:
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "events",
        help="path to a JSON list of FamilyEvent records, or '-' for stdin",
    )
    parser.add_argument(
        "--feature-key",
        default="relative_volume",
        help="recorded candidate feature to A/B against the v1 score "
        "(default: relative_volume)",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=DEFAULT_COST_BPS,
        help=f"round-trip cost in basis points (default: {DEFAULT_COST_BPS})",
    )
    parser.add_argument(
        "--label",
        choices=("direction", "magnitude"),
        default="direction",
        help="outcome the A/B grades against: 'direction' (sign of the net "
        "forward return, default) or 'magnitude' (|return| over a per-fold "
        "quantile -- a leak-safe volatility label)",
    )
    parser.add_argument(
        "--mag-q",
        type=float,
        default=0.5,
        help="per-fold quantile of |return| used as the magnitude-label "
        "threshold; ignored unless --label magnitude (default: 0.5)",
    )
    parser.add_argument(
        "--stratify-by",
        choices=("none", "abs_feature", "feature"),
        default="none",
        help="regime-FILTER mode: partition the score-alone arm by a regime "
        "derived from the feature and compare the score's resolution across "
        "strata, instead of running the feature-vs-score A/B. 'abs_feature' "
        "splits on |feature| (conviction), 'feature' on the signed value "
        "(default: none -> ordinary A/B)",
    )
    parser.add_argument(
        "--n-strata",
        type=int,
        default=2,
        help="number of equal-frequency regime strata when --stratify-by is "
        "set (default: 2 -> median split)",
    )
    parser.add_argument(
        "--out",
        default="-",
        help="path to write the JSON report, or '-' for stdout (default: stdout)",
    )
    args = parser.parse_args(argv)

    try:
        events = _load_events(args.events)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: could not load events: {exc}", file=sys.stderr)
        return 1

    if not events:
        print("error: event list is empty", file=sys.stderr)
        return 1

    if args.stratify_by != "none":
        regime_report = build_regime_report(
            events,
            feature_key=args.feature_key,
            cost_bps=args.cost_bps,
            stratify_by=args.stratify_by,
            n_strata=args.n_strata,
            label=args.label,
            mag_q=args.mag_q,
        )
        rendered = json.dumps(regime_report, indent=2, sort_keys=True)
        if args.out == "-":
            print(rendered)
        else:
            atomic_write_text(rendered + "\n", args.out)
        return _regime_exit_code(regime_report)

    report = build_report(
        events,
        feature_key=args.feature_key,
        cost_bps=args.cost_bps,
        label=args.label,
        mag_q=args.mag_q,
    )

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.out == "-":
        print(rendered)
    else:
        atomic_write_text(rendered + "\n", args.out)

    return _verdict_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
