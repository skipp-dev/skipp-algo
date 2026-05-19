#!/usr/bin/env python3
"""Phase-B baseline analyzer for the sharded Databento file-cache.

Reads the per-shard ``cache_probe_shard_<id>.jsonl`` artifacts from two
separate producer runs and prints the four numbers the action plan's
Phase-C go/no-go gate needs:

    * Run-1 lookups + unique paths
    * Run-2 lookups + unique paths
    * Set-overlap hit-rate (|R2 ∩ R1| / |R2|) -- conservative estimate
    * Lookup-weighted hit-rate (Σ lookups in R2 whose path ∈ R1) / Σ R2 --
      realistic estimate (hot paths weight more)

This is intentionally a single-file stdlib-only script with no test
coverage of its own: it runs locally against artifacts that an operator
has just downloaded from GitHub Actions; if it crashes the operator
re-downloads and re-runs. The Phase-C consumer
``scripts/cache_probe_analyze.py`` (separate PR, gated on this baseline)
will be the tested in-repo version.

Usage
-----
    gh run download <RUN1_ID> --dir baseline/run1 -p "cache-probe-shard-*"
    gh run download <RUN2_ID> --dir baseline/run2 -p "cache-probe-shard-*"
    python scripts/baseline_cache_probe.py baseline/run1 baseline/run2

Or with explicit JSON output for piping into a report:

    python scripts/baseline_cache_probe.py --json baseline/run1 baseline/run2

Decision thresholds (per action plan):
    Hit-rate (lookup-weighted) >= 60 %  --> Phase C green-lit.
    Hit-rate < 60 %                     --> stop, persistent cache won't pay off.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_run(run_dir: Path) -> tuple[set[str], list[str]]:
    """Return (unique_paths, every_lookup_path_in_order) for one run."""
    if not run_dir.exists():
        raise SystemExit(f"run dir not found: {run_dir}")
    unique: set[str] = set()
    lookups: list[str] = []
    jsonl_files = sorted(run_dir.rglob("cache_probe_shard_*.jsonl"))
    if not jsonl_files:
        raise SystemExit(
            f"no cache_probe_shard_*.jsonl under {run_dir}; "
            "did you pass --pattern 'cache-probe-shard-*' to gh run download?"
        )
    for fp in jsonl_files:
        for line in fp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                # Atomic-dump landed in PR-A so this should never trigger on
                # post-#2305 artifacts; still skip gracefully if some legacy
                # run is dragged in.
                continue
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            unique.add(path)
            lookups.append(path)
    return unique, lookups


def analyze(run1: Path, run2: Path) -> dict[str, object]:
    r1_unique, r1_lookups = _load_run(run1)
    r2_unique, r2_lookups = _load_run(run2)
    overlap_unique = r1_unique & r2_unique
    weighted_hits = sum(1 for p in r2_lookups if p in r1_unique)
    return {
        "run1": {"lookups": len(r1_lookups), "unique_paths": len(r1_unique)},
        "run2": {"lookups": len(r2_lookups), "unique_paths": len(r2_unique)},
        "hit_rate_set_overlap": (
            len(overlap_unique) / len(r2_unique) if r2_unique else 0.0
        ),
        "hit_rate_lookup_weighted": (
            weighted_hits / len(r2_lookups) if r2_lookups else 0.0
        ),
        "phase_c_gate_60pct": (
            (weighted_hits / len(r2_lookups) if r2_lookups else 0.0) >= 0.60
        ),
    }


def _format_pct(x: float) -> str:
    return f"{x * 100:6.2f} %"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run1", type=Path, help="dir containing run-1 cache-probe-shard-* artifacts")
    p.add_argument("run2", type=Path, help="dir containing run-2 cache-probe-shard-* artifacts")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of the report")
    args = p.parse_args(argv)

    result = analyze(args.run1, args.run2)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    r1 = result["run1"]
    r2 = result["run2"]
    print("Phase-B baseline — sharded Databento file-cache")
    print("=" * 60)
    print(f"Run 1 ({args.run1}):  {r1['lookups']:>7} lookups   {r1['unique_paths']:>6} unique paths")
    print(f"Run 2 ({args.run2}):  {r2['lookups']:>7} lookups   {r2['unique_paths']:>6} unique paths")
    print("-" * 60)
    print(f"Hit-rate (set-overlap, conservative):  {_format_pct(result['hit_rate_set_overlap'])}")
    print(f"Hit-rate (lookup-weighted, realistic): {_format_pct(result['hit_rate_lookup_weighted'])}")
    print("-" * 60)
    if result["phase_c_gate_60pct"]:
        print("Phase-C gate (>= 60 % lookup-weighted): PASS — proceed to Phase C.")
    else:
        print("Phase-C gate (>= 60 % lookup-weighted): FAIL — stop, persistent cache won't pay off.")
    print()
    print("Also collect per-shard wallclocks via:")
    print("    gh run view <RUN_ID> --json jobs --jq '.jobs[]|select(.name|startswith(\"producer\"))|{name,startedAt,completedAt}'")
    print("Phase D will need median + max shard wallclock to measure the >=30 % wallclock win.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
