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

Coverage guards make a partial-artifact run fail loud instead of
silently producing a Phase-C decision over incomplete inputs:

    --expected-shards N    each run must contribute exactly N
                           ``cache_probe_shard_*.jsonl`` files.
    --require-same-shards  run-1 and run-2 must cover the same shard-id set.
    --min-lookups N        each run must have >= N total lookups.
    --no-strict-json       tolerate malformed lines (legacy pre-#2305 only).

Usage
-----
    gh run download <RUN1_ID> --dir baseline/run1 -p "cache-probe-shard-*"
    gh run download <RUN2_ID> --dir baseline/run2 -p "cache-probe-shard-*"
    python scripts/baseline_cache_probe.py \
        --expected-shards 6 --require-same-shards --min-lookups 1 \
        baseline/run1 baseline/run2

Or with explicit JSON output for piping into a report:

    python scripts/baseline_cache_probe.py --json baseline/run1 baseline/run2

Decision thresholds (per action plan):
    Hit-rate (lookup-weighted) >= 60 %  --> Phase C green-lit.
    Hit-rate < 60 %                     --> stop, persistent cache won't pay off.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_SHARD_ID_RE = re.compile(r"cache_probe_shard_(\d+)\.jsonl$")


def _shard_id_from_path(path: Path) -> int | None:
    match = _SHARD_ID_RE.search(path.name)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _load_run(
    run_dir: Path,
    *,
    strict_json: bool = True,
) -> tuple[set[str], list[str], dict[int, int]]:
    """Return (unique_paths, every_lookup_path_in_order, per_shard_lookup_counts)."""
    if not run_dir.exists():
        raise SystemExit(f"run dir not found: {run_dir}")
    unique: set[str] = set()
    lookups: list[str] = []
    per_shard: dict[int, int] = {}
    jsonl_files = sorted(run_dir.rglob("cache_probe_shard_*.jsonl"))
    if not jsonl_files:
        raise SystemExit(
            f"no cache_probe_shard_*.jsonl under {run_dir}; "
            "did you pass --pattern 'cache-probe-shard-*' to gh run download?"
        )
    for fp in jsonl_files:
        shard_id = _shard_id_from_path(fp)
        shard_lookups = 0
        for lineno, raw in enumerate(fp.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                if strict_json:
                    raise SystemExit(
                        f"malformed JSON at {fp}:{lineno}: {exc.msg} "
                        "(pass --no-strict-json to tolerate legacy pre-#2305 artifacts)"
                    ) from exc
                continue
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            unique.add(path)
            lookups.append(path)
            shard_lookups += 1
        if shard_id is not None:
            per_shard[shard_id] = per_shard.get(shard_id, 0) + shard_lookups
    return unique, lookups, per_shard


def _enforce_coverage(
    label: str,
    per_shard: dict[int, int],
    *,
    expected_shards: int | None,
    min_lookups: int,
    total_lookups: int,
) -> None:
    if expected_shards is not None and len(per_shard) != expected_shards:
        raise SystemExit(
            f"{label}: expected {expected_shards} shard files, "
            f"found {len(per_shard)} (shard_ids={sorted(per_shard)}). "
            "A missing shard usually means a producer matrix entry failed or "
            "its cache-probe JSONL was not uploaded."
        )
    if total_lookups < min_lookups:
        raise SystemExit(
            f"{label}: total lookups {total_lookups} < required min {min_lookups}. "
            "Empty JSONLs usually mean DATABENTO_CACHE_PROBE_LOG was unset in the "
            "producer environment (enable_cache_probe input was likely false)."
        )


def analyze(
    run1: Path,
    run2: Path,
    *,
    expected_shards: int | None = None,
    require_same_shards: bool = False,
    min_lookups: int = 0,
    strict_json: bool = True,
) -> dict[str, object]:
    r1_unique, r1_lookups, r1_per_shard = _load_run(run1, strict_json=strict_json)
    r2_unique, r2_lookups, r2_per_shard = _load_run(run2, strict_json=strict_json)

    _enforce_coverage(
        f"run1 ({run1})",
        r1_per_shard,
        expected_shards=expected_shards,
        min_lookups=min_lookups,
        total_lookups=len(r1_lookups),
    )
    _enforce_coverage(
        f"run2 ({run2})",
        r2_per_shard,
        expected_shards=expected_shards,
        min_lookups=min_lookups,
        total_lookups=len(r2_lookups),
    )
    if require_same_shards and set(r1_per_shard) != set(r2_per_shard):
        raise SystemExit(
            "run1 and run2 cover different shard-id sets "
            f"(run1={sorted(r1_per_shard)}, run2={sorted(r2_per_shard)}); "
            "hit-rate would compare apples to oranges. Re-download or re-run."
        )

    overlap_unique = r1_unique & r2_unique
    weighted_hits = sum(1 for p in r2_lookups if p in r1_unique)
    return {
        "run1": {
            "lookups": len(r1_lookups),
            "unique_paths": len(r1_unique),
            "per_shard_lookups": dict(sorted(r1_per_shard.items())),
        },
        "run2": {
            "lookups": len(r2_lookups),
            "unique_paths": len(r2_unique),
            "per_shard_lookups": dict(sorted(r2_per_shard.items())),
        },
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
    p.add_argument(
        "--expected-shards",
        type=int,
        default=None,
        help="fail when either run does not contribute exactly N cache_probe_shard_*.jsonl files",
    )
    p.add_argument(
        "--require-same-shards",
        action="store_true",
        help="fail when run-1 and run-2 cover different shard-id sets",
    )
    p.add_argument(
        "--min-lookups",
        type=int,
        default=0,
        help="fail when either run has fewer than N total probe lookups (default: 0, off)",
    )
    p.add_argument(
        "--strict-json",
        dest="strict_json",
        action="store_true",
        default=True,
        help="abort on malformed JSON lines (default)",
    )
    p.add_argument(
        "--no-strict-json",
        dest="strict_json",
        action="store_false",
        help="tolerate malformed JSON lines (legacy pre-#2305 artifacts only)",
    )
    args = p.parse_args(argv)

    result = analyze(
        args.run1,
        args.run2,
        expected_shards=args.expected_shards,
        require_same_shards=args.require_same_shards,
        min_lookups=args.min_lookups,
        strict_json=args.strict_json,
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    r1 = result["run1"]
    r2 = result["run2"]
    print("Phase-B baseline — sharded Databento file-cache")
    print("=" * 60)
    print(f"Run 1 ({args.run1}):  {r1['lookups']:>7} lookups   {r1['unique_paths']:>6} unique paths   shards={sorted(r1['per_shard_lookups'])}")
    print(f"Run 2 ({args.run2}):  {r2['lookups']:>7} lookups   {r2['unique_paths']:>6} unique paths   shards={sorted(r2['per_shard_lookups'])}")
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
