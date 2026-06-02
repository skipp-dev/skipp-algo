"""Aggregate cache-probe shard JSONL into per-run / per-family hit-rates.

Used for Phase-C re-validation of the universe-key cache redesign (#2334)
against the 60% pre-redesign baseline and the 86.8% simulated target.

The ``--overlap`` mode adds cross-run path-set intersection for #2293's
Variante D gate-check: it pairs the probe-log directories listed on the
CLI and reports ``|paths(A) intersect paths(B)| / |paths(B)|`` -- the
projected hit-rate a persistent cache keyed on the structural cache-path
layout would deliver.

The ``--symbol-drift`` mode (#2398) isolates the per-symbol cache families
(``symbol_detail_*`` by default) and quantifies how much their *symbol*
selection -- not just the trade-date window -- shifts run-over-run. It
reports symbol Jaccard plus ``(symbol, trade_date)`` overlap, the latter
being the projected hit-rate for that selection-conditioned family.
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import pathlib
import re
import sys
from collections.abc import Iterable

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


# Per-symbol cache-path filename layout (see #2398):
#   <family>/<dataset>/<trade-date>__<SYMBOL>__<tz>__<...>.parquet
# The first two ``__``-separated filename fields are the trade-date and the
# symbol. Anything that does not match this shape is ignored by the
# symbol-drift report (universe-wide families have no per-symbol field).
def parse_symbol_date(path: str) -> tuple[str, str, str] | None:
    """Return ``(family, symbol, trade_date)`` for a per-symbol cache path.

    ``None`` when the path is not a recognised ``databento_volatility_cache``
    entry or its filename lacks the ``<date>__<symbol>__`` prefix.
    """
    normalized = path.replace("\\", "/")
    m = FAMILY_RE.search(normalized)
    if not m:
        return None
    family = m.group(1)
    filename = normalized.rsplit("/", 1)[-1]
    parts = filename.split("__")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    trade_date, symbol = parts[0], parts[1]
    return family, symbol, trade_date


def _symbol_sets(
    run: pathlib.Path, prefix: str
) -> dict[str, dict[str, set]]:
    """Collect ``{family: {"symbols": set, "pairs": set}}`` for ``run``.

    Only families whose name starts with ``prefix`` are retained. ``symbols``
    holds the distinct tickers; ``pairs`` holds ``(symbol, trade_date)``
    tuples (the unit a per-symbol cache key is actually addressed by).
    """
    out: dict[str, dict[str, set]] = {}
    for rec in _iter_records(run):
        parsed = parse_symbol_date(rec["path"])
        if parsed is None:
            continue
        family, symbol, trade_date = parsed
        if not family.startswith(prefix):
            continue
        bucket = out.setdefault(family, {"symbols": set(), "pairs": set()})
        bucket["symbols"].add(symbol)
        bucket["pairs"].add((symbol, trade_date))
    return out


def symbol_drift_report(runs: list[pathlib.Path], prefix: str) -> int:
    """Report per-family symbol-set drift across consecutive probe runs (#2398).

    For every family matching ``prefix`` and every adjacent run pair it prints
    the stable / new / dropped tickers, the symbol Jaccard, and the
    ``(symbol, trade_date)`` overlap -- the latter being the projected
    persistent-cache hit-rate for that per-symbol family.
    """
    if len(runs) < 2:
        print(
            "error: --symbol-drift needs at least two run directories",
            file=sys.stderr,
        )
        return 2
    per_run = [(run.name, _symbol_sets(run, prefix)) for run in runs]
    if not any(sets for _, sets in per_run):
        print(
            f"error: no per-symbol records matching prefix {prefix!r}",
            file=sys.stderr,
        )
        return 2
    families = sorted({fam for _, sets in per_run for fam in sets})
    for family in families:
        print(f"== {family} ==")
        for (name_a, sets_a), (name_b, sets_b) in itertools.pairwise(per_run):
            a = sets_a.get(family, {"symbols": set(), "pairs": set()})
            b = sets_b.get(family, {"symbols": set(), "pairs": set()})
            syms_a, syms_b = a["symbols"], b["symbols"]
            pairs_a, pairs_b = a["pairs"], b["pairs"]
            union = syms_a | syms_b
            jaccard = (len(syms_a & syms_b) / len(union) * 100) if union else 0.0
            pair_hit = (
                len(pairs_a & pairs_b) / len(pairs_b) * 100 if pairs_b else 0.0
            )
            print(
                f"   {name_a} -> {name_b}  "
                f"stable={sorted(syms_a & syms_b)}  "
                f"new={sorted(syms_b - syms_a)}  "
                f"dropped={sorted(syms_a - syms_b)}"
            )
            print(
                f"      symbol_jaccard={jaccard:6.2f}%  "
                f"(symbol,date) overlap={len(pairs_a & pairs_b)}/{len(pairs_b)} "
                f"= {pair_hit:6.2f}%  (projected per-symbol hit-rate)"
            )
    return 0


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
    parser.add_argument(
        "--symbol-drift",
        action="store_true",
        help="Report per-symbol family symbol-set drift across runs (#2398). "
             "Pairs adjacent run dirs and prints stable/new/dropped tickers, "
             "symbol Jaccard, and (symbol,date) overlap per family.",
    )
    parser.add_argument(
        "--family-prefix",
        default="symbol_detail_",
        help="Family-name prefix selecting the per-symbol cache families for "
             "--symbol-drift (default: 'symbol_detail_').",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.overlap:
        runs = [pathlib.Path(p) for p in args.root_or_runs]
        return overlap_report(runs)
    if args.symbol_drift:
        runs = [pathlib.Path(p) for p in args.root_or_runs]
        return symbol_drift_report(runs, args.family_prefix)
    root = pathlib.Path(args.root_or_runs[0] if args.root_or_runs else "baseline")
    analyze(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
