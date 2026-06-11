"""ADR-0023 §5 — calibrate empirical execution costs from paper sessions (CLI).

Reads one or more execution-session JSON files (the combined audit document
written by ``scripts/run_ibkr_open_execution.py``: ``{"submission": ...,
"supervisor": ...}``) and runs
:func:`governance.execution_costs.calibrate_costs` over the pooled fills.

The output JSON is the input for the §5 gate's ``--cost-calibration`` flag
(``scripts/run_epnl_after_cost_gate.py``), which uses the **conservative**
(CI-high) round-turn cost instead of the flat ``DEFAULT_COST_BPS``.

Exit codes
----------
* ``0`` -- calibration measurable (may be consumed by the §5 gate).
* ``2`` -- calibration produced but NOT measurable (too few fills or fill
  rate too low); the report is still written for transparency.
* ``1`` -- usage/config error (bad path, malformed JSON, no sessions).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from governance.execution_costs import (
    DEFAULT_N_BOOTSTRAP,
    DEFAULT_SEED,
    MIN_FILL_RATE,
    MIN_FILL_SAMPLES,
    calibrate_costs,
)


def _load_sessions(paths: list[str]) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict):
            raise ValueError(f"{path}: expected a JSON object, got {type(doc).__name__}")
        sessions.append(doc)
    return sessions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "sessions",
        nargs="+",
        help="execution-session JSON files written by run_ibkr_open_execution.py",
    )
    parser.add_argument(
        "--min-fill-samples",
        type=int,
        default=MIN_FILL_SAMPLES,
        help=f"minimum per-side cost samples (default: {MIN_FILL_SAMPLES})",
    )
    parser.add_argument(
        "--min-fill-rate",
        type=float,
        default=MIN_FILL_RATE,
        help=f"minimum entry fill rate (default: {MIN_FILL_RATE})",
    )
    parser.add_argument(
        "--n-bootstrap",
        type=int,
        default=DEFAULT_N_BOOTSTRAP,
        help=f"bootstrap resamples for the cost CI (default: {DEFAULT_N_BOOTSTRAP})",
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
        sessions = _load_sessions(args.sessions)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: could not load sessions: {exc}", file=sys.stderr)
        return 1

    if not sessions:
        print("error: no sessions supplied", file=sys.stderr)
        return 1

    calibration = calibrate_costs(
        sessions,
        min_fill_samples=args.min_fill_samples,
        min_fill_rate=args.min_fill_rate,
        n_bootstrap=args.n_bootstrap,
        seed=args.seed,
    )

    report = asdict(calibration)
    report["fail_reasons"] = list(calibration.fail_reasons)
    report["session_paths"] = list(args.sessions)

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.out == "-":
        print(rendered)
    else:
        from scripts.smc_atomic_write import atomic_write_text

        atomic_write_text(rendered + "\n", args.out)

    return 0 if calibration.measurable else 2


if __name__ == "__main__":
    raise SystemExit(main())
