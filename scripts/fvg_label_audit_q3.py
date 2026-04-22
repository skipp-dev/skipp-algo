"""Aggregate FVG family KPIs across the latest 4-TF benchmark snapshot.

Used by ``docs/FVG_LABEL_AUDIT_Q3.md`` (Q3 Phase D1/D2/D3) to back the
audit numbers against actual artifacts under
``artifacts/ci/measurement_benchmark_combined_2026-04-21/``.

Run: ``python scripts/fvg_label_audit_q3.py [--root <dir>]``
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Iterable


DEFAULT_ROOT = Path("artifacts/ci/measurement_benchmark_combined_2026-04-21")


def _iter_benchmark_files(root: Path) -> Iterable[Path]:
    yield from sorted(root.glob("*/*/benchmark_*.json"))


def _weighted(rows: list[dict], key: str) -> float:
    total_n = sum(r["n_events"] for r in rows)
    if total_n == 0:
        return 0.0
    return sum(r.get(key, 0.0) * r["n_events"] for r in rows) / total_n


def aggregate(root: Path) -> dict:
    by_tf_family: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_strat_family: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for path in _iter_benchmark_files(root):
        data = json.loads(path.read_text())
        tf = data["timeframe"]
        for kpi in data.get("kpis", []):
            by_tf_family[(tf, kpi["family"])].append(kpi)
        for strat_key, kpis in data.get("stratified", {}).items():
            for kpi in kpis:
                by_strat_family[(strat_key, kpi["family"])].append(kpi)

    per_tf: dict[str, dict[str, dict]] = {}
    for (tf, fam), rows in sorted(by_tf_family.items()):
        per_tf.setdefault(tf, {})[fam] = {
            "n_events": sum(r["n_events"] for r in rows),
            "hit_rate": round(_weighted(rows, "hit_rate"), 4),
            "ttm_mean": round(_weighted(rows, "time_to_mitigation_mean"), 2),
            "partial_fill_pct_mean": round(
                _weighted(rows, "partial_fill_pct_mean"), 4,
            ),
            "invalidation_rate": round(_weighted(rows, "invalidation_rate"), 4),
        }

    fvg_per_strat: dict[str, dict] = {}
    for (strat_key, fam), rows in sorted(by_strat_family.items()):
        if fam != "FVG":
            continue
        n = sum(r["n_events"] for r in rows)
        if n == 0:
            continue
        fvg_per_strat[strat_key] = {
            "n_events": n,
            "hit_rate": round(_weighted(rows, "hit_rate"), 4),
            "partial_fill_pct_mean": round(
                _weighted(rows, "partial_fill_pct_mean"), 4,
            ),
        }

    overall_fvg = [r for (tf, fam), rows in by_tf_family.items()
                   if fam == "FVG" for r in rows]
    overall = {
        "n_events": sum(r["n_events"] for r in overall_fvg),
        "hit_rate": round(_weighted(overall_fvg, "hit_rate"), 4),
        "ttm_mean": round(_weighted(overall_fvg, "time_to_mitigation_mean"), 2),
        "partial_fill_pct_mean": round(
            _weighted(overall_fvg, "partial_fill_pct_mean"), 4,
        ),
    }
    return {"per_tf": per_tf, "fvg_per_context": fvg_per_strat,
            "fvg_overall": overall, "source_root": str(root),
            "n_files": sum(1 for _ in _iter_benchmark_files(root))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--format", choices=["json", "md"], default="md")
    args = parser.parse_args(argv)

    if not args.root.exists():
        print(f"ERROR: root not found: {args.root}")
        return 1

    result = aggregate(args.root)
    if args.format == "json":
        print(json.dumps(result, indent=2))
        return 0

    print(f"# FVG audit aggregate ({result['n_files']} benchmark files)\n")
    print(f"Source: `{result['source_root']}`\n")
    print("## Per-TF × per-family\n")
    print("| TF | Family | n | HR | TTM | partial_fill | inval_rate |")
    print("|---|---|---:|---:|---:|---:|---:|")
    for tf, fams in result["per_tf"].items():
        for fam, k in fams.items():
            print(f"| {tf} | {fam} | {k['n_events']} | "
                  f"{k['hit_rate']:.3f} | {k['ttm_mean']} | "
                  f"{k['partial_fill_pct_mean']:.3f} | "
                  f"{k['invalidation_rate']:.3f} |")
    print("\n## FVG per context\n")
    print("| Context | n | HR | partial_fill |")
    print("|---|---:|---:|---:|")
    for ctx, k in result["fvg_per_context"].items():
        print(f"| {ctx} | {k['n_events']} | {k['hit_rate']:.3f} | "
              f"{k['partial_fill_pct_mean']:.3f} |")
    print("\n## FVG overall\n")
    o = result["fvg_overall"]
    print(f"- n_events: {o['n_events']}")
    print(f"- hit_rate: {o['hit_rate']:.3f}")
    print(f"- TTM mean: {o['ttm_mean']}")
    print(f"- partial_fill_pct_mean: {o['partial_fill_pct_mean']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
