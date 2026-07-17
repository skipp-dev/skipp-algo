#!/usr/bin/env python3
"""Run deterministic A0-Fast load/chaos scenarios and persist the report."""

from __future__ import annotations

import argparse
from pathlib import Path

from open_prep.a0_load_probe import (
    A0LoadBudget,
    default_a0_load_scenarios,
    run_a0_load_probe,
)
from scripts.smc_atomic_write import atomic_write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--duration-seconds", type=int, default=8)
    parser.add_argument("--all-symbol-count", type=int)
    parser.add_argument("--max-cpu-seconds", type=float, default=10.0)
    parser.add_argument("--max-peak-memory-mb", type=float, default=256.0)
    parser.add_argument("--max-wire-mb", type=float, default=500.0)
    parser.add_argument("--max-drop-fraction", type=float, default=0.50)
    parser.add_argument("--max-historical-requests", type=int, default=10_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    budget = A0LoadBudget(
        max_cpu_seconds=args.max_cpu_seconds,
        max_peak_memory_mb=args.max_peak_memory_mb,
        max_wire_mb=args.max_wire_mb,
        max_drop_fraction=args.max_drop_fraction,
        max_historical_requests=args.max_historical_requests,
    )
    scenarios = default_a0_load_scenarios(
        duration_seconds=args.duration_seconds,
        all_symbol_count=args.all_symbol_count,
    )
    report = run_a0_load_probe(scenarios, budget)
    atomic_write_json(report, args.output, indent=2, sort_keys=True, fsync=True)
    status = "PASS" if report["passed"] else "FAIL"
    print(f"A0 load probe: {status} ({len(report['scenarios'])} scenarios)")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
