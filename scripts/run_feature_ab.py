"""ADR-0019 paired A/B driver: does a recorded candidate feature lift resolution?

This is the on-ramp that the harness (#2528, ``governance.family_returns`` +
``governance.family_feature_ab``) and the candidate feature (#2534,
``governance.family_momentum_ribbon_v2`` wired into
``governance.family_event_adapter``) were missing: a single command that turns
recorded :class:`~governance.family_returns.FamilyEvent` records into a
per-family pre-registered purged walk-forward A/B verdict.

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
* ``0`` -- at least one family returned ``candidate_lifts_resolution``.
* ``2`` -- families were measurable but NONE lifted resolution (``no_lift`` /
  ``regresses_calibration`` for all). The candidate is not validated.
* ``3`` -- no family produced a verdict (every paired sample was too thin).
* ``1`` -- usage/config error (bad path, malformed JSON, empty event list).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from governance.family_feature_ab import family_feature_ab_report
from governance.family_returns import DEFAULT_COST_BPS, extract_family_ab_samples


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
    events: list[dict[str, Any]], *, feature_key: str, cost_bps: float
) -> dict[str, Any]:
    """Assemble the paired samples and run the A/B for every measurable family."""
    ab_samples = extract_family_ab_samples(
        events, feature_key=feature_key, cost_bps=cost_bps
    )
    report = family_feature_ab_report(ab_samples)
    lifted = sorted(
        family
        for family, result in report.items()
        if result["verdict"] == "candidate_lifts_resolution"
    )
    return {
        "feature_key": feature_key,
        "cost_bps": cost_bps,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "events",
        help="path to a JSON list of FamilyEvent records, or '-' for stdin",
    )
    parser.add_argument(
        "--feature-key",
        default="momentum_ribbon",
        help="recorded candidate feature to A/B against the v1 score "
        "(default: momentum_ribbon)",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=DEFAULT_COST_BPS,
        help=f"round-trip cost in basis points (default: {DEFAULT_COST_BPS})",
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

    report = build_report(
        events, feature_key=args.feature_key, cost_bps=args.cost_bps
    )

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.out == "-":
        print(rendered)
    else:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")

    return _verdict_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
