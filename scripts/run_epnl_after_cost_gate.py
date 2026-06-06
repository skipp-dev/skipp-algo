"""ADR-0023 §5 — E[PnL]-after-cost secondary check (CLI wrapper).

Reads a JSON list of ``FamilyEvent`` records, extracts the per-family
score/return calibration samples (same producer the §2 resolution gate uses),
and runs :func:`governance.epnl_after_cost.evaluate_family_epnl` per family.

The candidate families (BOS / SWEEP) are the promotion targets; the control
families (FVG / OB) are measured for transparency but never gate. A candidate
must clear *both* the §2 resolution bar **and** this §5 profitability bar before
real sizing is armed (handover §5: "statistically resolving != profitable after
costs").

Exit codes
----------
* ``0`` -- at least one candidate family PASSES.
* ``2`` -- candidates measurable but none passes.
* ``3`` -- every candidate family is too thin to measure.
* ``1`` -- usage/config error (bad path, empty events).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from governance.epnl_after_cost import (
    DEFAULT_N_BOOTSTRAP,
    DEFAULT_SEED,
    MIN_TRADES,
    evaluate_family_epnl,
)
from governance.family_returns import (
    DEFAULT_COST_BPS,
    extract_family_calibration_samples,
)
from scripts.run_magnitude_resolution_gate import _load_events
from scripts.run_magnitude_shadow_ledger import CANDIDATE_FAMILIES


def build_report(
    events: list[dict[str, Any]],
    *,
    cost_bps: float = DEFAULT_COST_BPS,
    min_trades: int = MIN_TRADES,
    n_boot: int = DEFAULT_N_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Run the §5 E[PnL]-after-cost check across all families."""
    samples = extract_family_calibration_samples(events, cost_bps=cost_bps)

    results: dict[str, dict[str, Any]] = {}
    for family, sample in sorted(samples.items()):
        result = evaluate_family_epnl(
            family,
            list(sample["scores"]),
            list(sample["returns"]),
            cost_bps=cost_bps,
            min_trades=min_trades,
            n_bootstrap=n_boot,
            seed=seed,
        )
        row = asdict(result)
        row["role"] = "candidate" if family in CANDIDATE_FAMILIES else "control"
        row["fail_reasons"] = list(result.fail_reasons)
        results[family] = row

    candidates_passed = sorted(
        family
        for family, r in results.items()
        if r["role"] == "candidate" and r["passes"]
    )
    candidates_measured = sorted(
        family
        for family, r in results.items()
        if r["role"] == "candidate" and r["min_sample_pass"]
    )

    return {
        "cost_bps": cost_bps,
        "min_trades": min_trades,
        "n_bootstrap": n_boot,
        "seed": seed,
        "epnl_ci_floor": 0.0,
        "families_measured": sorted(results),
        "candidates_measured": candidates_measured,
        "candidates_passed": candidates_passed,
        "results": results,
    }


def _verdict_exit_code(report: dict[str, Any]) -> int:
    if not report["candidates_measured"]:
        return 3
    if report["candidates_passed"]:
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
        "--min-trades",
        type=int,
        default=MIN_TRADES,
        help=f"minimum triggered setups to measure a family (default: {MIN_TRADES})",
    )
    parser.add_argument(
        "--n-bootstrap",
        type=int,
        default=DEFAULT_N_BOOTSTRAP,
        help=f"bootstrap resamples for the PnL CI (default: {DEFAULT_N_BOOTSTRAP})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"RNG seed for the bootstrap CI (default: {DEFAULT_SEED})",
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
        min_trades=args.min_trades,
        n_boot=args.n_bootstrap,
        seed=args.seed,
    )

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.out == "-":
        print(rendered)
    else:
        from scripts.smc_atomic_write import atomic_write_text

        atomic_write_text(rendered + "\n", args.out)

    return _verdict_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
