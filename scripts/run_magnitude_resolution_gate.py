"""ADR-0023 confirmatory driver: does the v1 score clear the move-size bar?

Runs the pre-registered ADR-0023 §2 acceptance bar (score-alone magnitude AUC
floor + bootstrap CI, label-permutation resolution null) per family on real
events and prints a per-family verdict. SHADOW-ONLY: it reads events, runs the
leak-safe purged walk-forward magnitude arm
(``governance.magnitude_resolution_gate``), and reports whether each family
qualifies for the additive tier-2 ``magnitude_resolution_floor`` sizing check.
It wires NOTHING into the gate; production wiring is a deliberate, separate edit
gated on a passing verdict here, per ADR-0023 §3/§4.

Input
-----
A JSON file containing a list of ``FamilyEvent`` records (the dicts the adapter
emits), or ``-`` to read that list from stdin. Every event carrying a v1
``score`` and forward bars contributes a score-alone sample (no candidate
feature is required — the bar grades the score itself).

Exit codes
----------
* ``0`` -- at least one family PASSES the §2 bar.
* ``2`` -- families were measurable but NONE passes. Negative result; the v1
  direction-Brier gate stays in force.
* ``3`` -- no family produced a verdict (every sample was too thin).
* ``1`` -- usage/config error (bad path, malformed JSON, empty event list).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from governance.family_returns import (
    DEFAULT_COST_BPS,
    extract_family_calibration_samples,
)
from governance.magnitude_resolution_gate import (
    DEFAULT_N_BOOTSTRAP,
    DEFAULT_N_PERMUTATION,
    DEFAULT_SEED,
    magnitude_resolution_report,
)
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
    cost_bps: float = DEFAULT_COST_BPS,
    mag_q: float = 0.5,
    n_boot: int = DEFAULT_N_BOOTSTRAP,
    n_perm: int = DEFAULT_N_PERMUTATION,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Assemble score-alone calibration samples and run the §2 acceptance bar."""
    samples = extract_family_calibration_samples(events, cost_bps=cost_bps)
    report = magnitude_resolution_report(
        samples, mag_q=mag_q, n_boot=n_boot, n_perm=n_perm, seed=seed
    )
    passed = sorted(family for family, r in report.items() if r.passes)
    return {
        "cost_bps": cost_bps,
        "mag_q": mag_q,
        "n_bootstrap": n_boot,
        "n_permutation": n_perm,
        "seed": seed,
        "families_measured": sorted(report),
        "families_passed": passed,
        "results": {family: asdict(r) for family, r in sorted(report.items())},
    }


def _verdict_exit_code(report: dict[str, Any]) -> int:
    if not report["results"]:
        return 3
    if report["families_passed"]:
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "events",
        help="path to a JSON list of FamilyEvent records, or '-' for stdin",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=DEFAULT_COST_BPS,
        help=f"round-trip cost in basis points (default: {DEFAULT_COST_BPS})",
    )
    parser.add_argument(
        "--mag-q",
        type=float,
        default=0.5,
        help="per-fold quantile of |return| used as the magnitude-label "
        "threshold (default: 0.5, the ADR-0023 §1 pre-registered value)",
    )
    parser.add_argument(
        "--n-bootstrap",
        type=int,
        default=DEFAULT_N_BOOTSTRAP,
        help=f"AUC bootstrap resamples, ADR-0023 §2.1 (default: {DEFAULT_N_BOOTSTRAP})",
    )
    parser.add_argument(
        "--n-permutation",
        type=int,
        default=DEFAULT_N_PERMUTATION,
        help=f"resolution label-permutations, ADR-0023 §2.2 (default: {DEFAULT_N_PERMUTATION})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"RNG seed for the CI/null (default: {DEFAULT_SEED})",
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
        events,
        cost_bps=args.cost_bps,
        mag_q=args.mag_q,
        n_boot=args.n_bootstrap,
        n_perm=args.n_permutation,
        seed=args.seed,
    )

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.out == "-":
        print(rendered)
    else:
        atomic_write_text(rendered + "\n", args.out)

    return _verdict_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
