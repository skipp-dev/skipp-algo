"""Aggregate cache-probe shard JSONL into per-run / per-family hit-rates.

Used for Phase-C re-validation of the universe-key cache redesign (#2334)
against the 60% pre-redesign baseline and the 86.8% simulated target.

The ``--overlap`` mode adds cross-run path-set intersection for #2293's
Variante D gate-check: it pairs the probe-log directories listed on the
CLI and reports ``|paths(A) intersect paths(B)| / |paths(B)|`` -- the
projected hit-rate a persistent cache keyed on the structural cache-path
layout would deliver.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys
from typing import Iterable

# Normalize separators so the same regex works on Linux/macOS (`/`) probe
# logs and any future Windows runs (`\\`). The leading `(?:^|/)` lets the
# pattern match probe paths that are either absolute, relative, or stored
# without a leading slash.
FAMILY_RE = re.compile(r"(?:^|/)databento_volatility_cache/([^/]+)/")


def fam(p: str) -> str:
    normalized = p.replace("\\", "/")
    m = FAMILY_RE.search(normalized)
    return m.group(1) if m else "unknown"


def _iter_records(run: pathlib.Path) -> Iterable[dict]:
    for shard in sorted(run.glob("cache-probe-shard-*/*.jsonl")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            yield json.loads(line)


def analyze(root: pathlib.Path) -> None:
    for run in sorted(root.iterdir()):
        if not run.is_dir():
            continue
        overall = collections.Counter()
        by_fam: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        n = 0
        for rec in _iter_records(run):
            n += 1
            key = "hit" if rec["hit"] else "miss"
            overall[key] += 1
            by_fam[fam(rec["path"])][key] += 1
        total = overall["hit"] + overall["miss"]
        rate = (overall["hit"] / total * 100) if total else 0.0
        print(f"== {run.name} ==  records={n}  hit={overall['hit']}  miss={overall['miss']}  rate={rate:.2f}%")
        for f, c in sorted(by_fam.items()):
            t = c["hit"] + c["miss"]
            r = (c["hit"] / t * 100) if t else 0.0
            print(f"   {f:32s}  hit={c['hit']:5d}  miss={c['miss']:5d}  rate={r:6.2f}%")


def collect_paths(run: pathlib.Path) -> set[str]:
    """Return the set of unique cache paths probed under ``run``."""
    return {rec["path"] for rec in _iter_records(run)}


def overlap_report(runs: list[pathlib.Path]) -> int:
    """Print pairwise cross-run path-set intersections."""
    if len(runs) < 2:
        print("error: --overlap needs at least two run directories", file=sys.stderr)
        return 2
    sets: list[tuple[str, set[str]]] = []
    for run in runs:
        paths = collect_paths(run)
        if not paths:
            print(f"error: no probe records under {run}", file=sys.stderr)
            return 2
        sets.append((run.name, paths))
        print(f"== {run.name} ==  unique_paths={len(paths)}")
    print()
    print("== pairwise overlap (intersection / |B|) ==")
    for i, (name_a, set_a) in enumerate(sets):
        for name_b, set_b in sets[i + 1 :]:
            inter = set_a & set_b
            denom = len(set_b)
            rate = (len(inter) / denom * 100) if denom else 0.0
            print(
                f"   {name_a} & {name_b}  inter={len(inter):4d}  "
                f"|B|={denom:4d}  rate={rate:6.2f}%"
            )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "root_or_runs",
        nargs="*",
        help="Without --overlap: a root directory whose children are per-run "
             "probe directories (default: 'baseline'). With --overlap: two or "
             "more per-run probe directories.",
    )
    parser.add_argument(
        "--overlap",
        action="store_true",
        help="Compute pairwise cross-run path-set overlap (#2293 gate-check).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.overlap:
        runs = [pathlib.Path(p) for p in args.root_or_runs]
        return overlap_report(runs)
    root = pathlib.Path(args.root_or_runs[0] if args.root_or_runs else "baseline")
    analyze(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
