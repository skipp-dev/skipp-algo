#!/usr/bin/env python3
"""OV7 — Compare measurement benchmark results between A/B experiment arms.

Reads two sets of benchmark artifacts (one per arm) and produces a
side-by-side KPI comparison table (Markdown + JSON).

Usage
-----
::

    python scripts/run_ab_comparison.py \\
        --control-dir  artifacts/ci/measurement_benchmark_control \\
        --treatment-dir artifacts/ci/measurement_benchmark_treatment \\
        --experiment-name news-benzinga-uplift \\
        --output-dir artifacts/reports

Output
------
- ``ab_comparison.md``  — human-readable diff table
- ``ab_comparison.json`` — machine-readable comparison digest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Re-use the report helpers from the performance report generator.
from scripts.generate_performance_report import (
    _aggregate,
    _grade,
    load_benchmark,
    PairReport,
)


def _delta(treatment: float, control: float) -> str:
    """Format delta as +/- with 4 decimals."""
    d = treatment - control
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.4f}"


def _better_arrow(metric: str, treatment: float, control: float) -> str:
    """Return ↑ / ↓ / = indicating whether treatment is better."""
    # For Brier / ECE: lower is better.  For hit_rate: higher is better.
    if metric in ("hit_rate_pct",):
        if treatment > control:
            return "↑ better"
        if treatment < control:
            return "↓ worse"
        return "="
    # Lower-is-better metrics.
    if treatment < control:
        return "↑ better"
    if treatment > control:
        return "↓ worse"
    return "="


def _dict_to_pair(d: dict[str, Any]) -> PairReport:
    """Convert a plain dict (e.g. from tests) into a PairReport."""
    return PairReport(
        symbol=d.get("symbol", ""),
        timeframe=d.get("timeframe", ""),
        n_events=int(d.get("n_events", 0)),
        brier=float(d.get("brier", float("nan"))),
        log_score=float(d.get("log_score", float("nan"))),
        hit_rate=float(d.get("hit_rate_pct", d.get("hit_rate", float("nan")))),
        calibration_method=str(d.get("calibration_method", "identity")),
        calibrated_brier=float(d.get("calibrated_brier", float("nan"))),
        calibrated_ece=float(d.get("calibrated_ece", float("nan"))),
        raw_ece=float(d.get("raw_ece", float("nan"))),
        families_present=d.get("families_present", []),
        family_metrics=d.get("family_metrics", {}),
        ensemble_score=float(d.get("ensemble_score", float("nan"))),
        ensemble_tier=str(d.get("ensemble_tier", "")),
        stratified_dimensions=d.get("stratified_dimensions", []),
        populated_buckets=int(d.get("populated_buckets", 0)),
        warnings=d.get("warnings", []),
        contextual_best_brier_dim=str(d.get("contextual_best_brier_dim", "")),
        contextual_best_ece_dim=str(d.get("contextual_best_ece_dim", "")),
    )


def compare(
    control_pairs: list[dict[str, Any]],
    treatment_pairs: list[dict[str, Any]],
    experiment_name: str,
) -> dict[str, Any]:
    """Build the comparison digest."""
    ctrl_reports = [_dict_to_pair(p) for p in control_pairs]
    treat_reports = [_dict_to_pair(p) for p in treatment_pairs]
    ctrl_agg = _aggregate(ctrl_reports)
    treat_agg = _aggregate(treat_reports)

    # Map metric keys to AggregateReport attribute names.
    _attr_map = {
        "brier": "avg_brier",
        "calibrated_brier": "avg_calibrated_brier",
        "calibrated_ece": "avg_calibrated_ece",
        "hit_rate_pct": "avg_hit_rate",
    }

    rows: list[dict[str, Any]] = []
    for key in ("brier", "calibrated_brier", "calibrated_ece", "hit_rate_pct"):
        attr = _attr_map[key]
        c = getattr(ctrl_agg, attr, 0.0)
        t = getattr(treat_agg, attr, 0.0)
        rows.append({
            "metric": key,
            "control": round(c, 4),
            "treatment": round(t, 4),
            "delta": round(t - c, 4),
            "direction": _better_arrow(key, t, c),
        })

    return {
        "experiment": experiment_name,
        "control_pairs": len(control_pairs),
        "treatment_pairs": len(treatment_pairs),
        "control_grade": _grade(getattr(ctrl_agg, "avg_calibrated_brier", 1.0)),
        "treatment_grade": _grade(getattr(treat_agg, "avg_calibrated_brier", 1.0)),
        "metrics": rows,
    }


def render_comparison(digest: dict[str, Any]) -> str:
    """Render the comparison digest as Markdown."""
    lines: list[str] = []
    lines.append(f"# A/B Comparison: {digest['experiment']}")
    lines.append("")
    lines.append(f"| Arm | Pairs | Grade |")
    lines.append(f"|-----|------:|-------|")
    lines.append(f"| Control   | {digest['control_pairs']} | {digest['control_grade']} |")
    lines.append(f"| Treatment | {digest['treatment_pairs']} | {digest['treatment_grade']} |")
    lines.append("")
    lines.append("## KPI Comparison")
    lines.append("")
    lines.append("| Metric | Control | Treatment | Delta | Direction |")
    lines.append("|--------|--------:|----------:|------:|-----------|")
    for row in digest["metrics"]:
        lines.append(
            f"| {row['metric']} | {row['control']:.4f} | "
            f"{row['treatment']:.4f} | {_delta(row['treatment'], row['control'])} | "
            f"{row['direction']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare A/B benchmark arms")
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--treatment-dir", type=Path, required=True)
    parser.add_argument("--experiment-name", type=str, default="unnamed")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/reports"))
    args = parser.parse_args(argv)

    control_pairs = load_benchmark(args.control_dir)
    treatment_pairs = load_benchmark(args.treatment_dir)

    if not control_pairs:
        print(f"ERROR: no benchmark pairs in {args.control_dir}", file=sys.stderr)
        sys.exit(1)
    if not treatment_pairs:
        print(f"ERROR: no benchmark pairs in {args.treatment_dir}", file=sys.stderr)
        sys.exit(1)

    digest = compare(control_pairs, treatment_pairs, args.experiment_name)
    report = render_comparison(digest)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "ab_comparison.md").write_text(report, encoding="utf-8")
    (args.output_dir / "ab_comparison.json").write_text(
        json.dumps(digest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Comparison written to {args.output_dir}")
    print(f"  Control grade:   {digest['control_grade']}")
    print(f"  Treatment grade: {digest['treatment_grade']}")


if __name__ == "__main__":
    main()
