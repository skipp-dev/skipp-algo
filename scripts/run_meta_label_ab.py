"""ADR-0022 paired meta-label driver: does a JOINT feature model lift resolution?

The companion to ``scripts/run_feature_ab.py``. Where that driver asks whether a
SINGLE recorded feature out-resolves the v1 score ALONE, this one asks the
incremental / meta-label question ADR-0019 explicitly deferred: does a
MULTIVARIATE model over ``[score] + feature_keys`` lift resolution ON TOP of the
score? Single-feature nulls do not answer this -- individually weak but mutually
orthogonal features can lift discrimination in combination.

It is SHADOW-ONLY. It reads events, runs the leak-safe paired joint A/B
(``governance.family_meta_label``), and prints a per-family verdict. It NEVER
wires anything into the gate or the score; production wiring stays gated on a
``candidate_lifts_resolution`` verdict on REAL data, per ADR-0019.

Input
-----
A JSON file containing a list of ``FamilyEvent`` records (the same dicts the
adapter emits), OR ``-`` to read that list from stdin. Each event that carries a
v1 ``score``, EVERY requested ``--feature-key``, and forward bars contributes a
paired complete-case sample.

Exit codes
----------
* ``0`` -- at least one family returned ``candidate_lifts_resolution``.
* ``2`` -- families were measurable but NONE lifted resolution. Not validated.
* ``3`` -- no family produced a verdict (every paired sample was too thin).
* ``1`` -- usage/config error (bad path, malformed JSON, empty event list,
  no ``--feature-key`` given).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from governance.family_meta_label import (
    extract_family_meta_samples,
    family_meta_ab_report,
)
from governance.family_returns import DEFAULT_COST_BPS
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
    feature_keys: list[str],
    cost_bps: float,
    label: str = "direction",
    mag_q: float = 0.5,
) -> dict[str, Any]:
    """Assemble complete-case joint samples and run the meta-label A/B.

    ``label`` selects the graded axis: ``"direction"`` (sign of the net forward
    return) or ``"magnitude"`` (``|return|`` at or above the ``mag_q`` train
    quantile). The same complete-case joint samples feed either axis.
    """
    meta_samples = extract_family_meta_samples(
        events, feature_keys=feature_keys, cost_bps=cost_bps
    )
    report = family_meta_ab_report(
        meta_samples, feature_keys, label=label, mag_q=mag_q
    )
    lifted = sorted(
        family
        for family, result in report.items()
        if result["verdict"] == "candidate_lifts_resolution"
    )
    return {
        "feature_keys": list(feature_keys),
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


def _parse_feature_keys(raw: list[str]) -> list[str]:
    """Flatten comma- or space-separated ``--feature-key`` values, de-duped."""
    keys: list[str] = []
    for chunk in raw:
        for key in chunk.split(","):
            key = key.strip()
            if key and key not in keys:
                keys.append(key)
    return keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "events",
        help="path to a JSON list of FamilyEvent records, or '-' for stdin",
    )
    parser.add_argument(
        "--feature-key",
        action="append",
        default=[],
        metavar="KEY",
        help="recorded feature to include in the JOINT model on top of the v1 "
        "score; repeat the flag or pass a comma-separated list to add several "
        "(e.g. --feature-key relative_volume --feature-key vpin)",
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
        help="outcome axis the joint A/B grades against: 'direction' (sign of "
        "the net forward return, default) or 'magnitude' (|return| at or above "
        "the per-fold train quantile -- the move-size / volatility axis)",
    )
    parser.add_argument(
        "--mag-q",
        type=float,
        default=0.5,
        help="per-fold quantile of |return| used as the magnitude-label "
        "threshold; ignored unless --label magnitude (default: 0.5)",
    )
    parser.add_argument(
        "--out",
        default="-",
        help="path to write the JSON report, or '-' for stdout (default: stdout)",
    )
    args = parser.parse_args(argv)

    feature_keys = _parse_feature_keys(args.feature_key)
    if not feature_keys:
        print(
            "error: at least one --feature-key is required for the joint model",
            file=sys.stderr,
        )
        return 1

    try:
        events = _load_events(args.events)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: could not load events: {exc}", file=sys.stderr)
        return 1

    if not events:
        print("error: event list is empty", file=sys.stderr)
        return 1

    report = build_report(
        events,
        feature_keys=feature_keys,
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
