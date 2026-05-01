"""WP-OV3: Generate a Markdown performance report from measurement benchmark output."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Bug-Hunt 2026-05-01 F-01: deferred so the script also works when
# invoked as `python scripts/X.py` (no PYTHONPATH=.) — sys.path.insert
# above must happen before any first-party `from scripts.` import.
from scripts.smc_atomic_write import atomic_write_text  # noqa: E402


def _fmt(value: Any, precision: int = 4) -> str:
    """Format a numeric value, returning '—' for NaN/None."""
    if value is None:
        return "—"
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return "—"
        return f"{f:.{precision}f}"
    except (TypeError, ValueError):
        return str(value)


def _section_signal_quality(summary: dict[str, Any]) -> list[str]:
    scoring = summary.get("scoring", {})
    calibration = scoring.get("calibration", {})
    lines = [
        "## Signal Quality",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Brier Score | {_fmt(scoring.get('brier_score'))} |",
        f"| Log Score | {_fmt(scoring.get('log_score'))} |",
        f"| Hit Rate | {_fmt(scoring.get('hit_rate'))} |",
        f"| Events | {scoring.get('n_events', 0)} |",
        f"| Calibration Method | {calibration.get('method', '—')} |",
        f"| Calibrated Brier | {_fmt(calibration.get('calibrated_brier_score'))} |",
        f"| Raw ECE | {_fmt(calibration.get('raw_ece'))} |",
        f"| Calibrated ECE | {_fmt(calibration.get('calibrated_ece'))} |",
        "",
    ]

    family_metrics = scoring.get("family_metrics", {})
    if family_metrics:
        lines += [
            "### Per-Family Metrics",
            "",
            "| Family | Hit Rate | Brier | Events |",
            "|--------|----------|-------|--------|",
        ]
        for family, metrics in sorted(family_metrics.items()):
            lines.append(
                f"| {family} | {_fmt(metrics.get('hit_rate'))} "
                f"| {_fmt(metrics.get('brier_score'))} "
                f"| {metrics.get('n_events', 0)} |"
            )
        lines.append("")

    return lines


def _section_regime_performance(summary: dict[str, Any]) -> list[str]:
    strat_summary = summary.get("scoring", {}).get(
        "stratified_calibration_summary", {}
    )
    dimensions = strat_summary.get("dimensions_present", [])
    lines = [
        "## Regime Performance",
        "",
    ]
    if not dimensions:
        lines.append("No stratified calibration dimensions available.")
        lines.append("")
        return lines

    lines.append(f"Dimensions present: {', '.join(dimensions)}")
    lines.append("")

    stratified = summary.get("scoring", {}).get("stratified_calibration", {})
    if stratified:
        lines += [
            "| Dimension | Brier | ECE | Events |",
            "|-----------|-------|-----|--------|",
        ]
        for dim_key, dim_data in sorted(stratified.items()):
            lines.append(
                f"| {dim_key} | {_fmt(dim_data.get('brier_score'))} "
                f"| {_fmt(dim_data.get('ece'))} "
                f"| {dim_data.get('n_events', '—')} |"
            )
        lines.append("")

    return lines


def _section_enrichment_value(summary: dict[str, Any]) -> list[str]:
    ensemble = summary.get("ensemble_quality", {})
    lines = ["## Enrichment Value", ""]
    if not ensemble:
        lines.append("No ensemble quality data available.")
        lines.append("")
        return lines

    lines += [
        f"- **Ensemble Score**: {_fmt(ensemble.get('score'))}",
        f"- **Tier**: {ensemble.get('tier', '—')}",
        f"- **Available Components**: {ensemble.get('available_components', '—')}",
    ]

    contributions = ensemble.get("contributions", {})
    if contributions:
        lines.append("")
        lines += [
            "| Component | Contribution |",
            "|-----------|-------------|",
        ]
        for component, value in sorted(contributions.items()):
            lines.append(f"| {component} | {_fmt(value)} |")

    lines.append("")
    return lines


def _section_trust_tier(summary: dict[str, Any]) -> list[str]:
    ensemble = summary.get("ensemble_quality", {})
    contextual = summary.get("scoring", {}).get(
        "contextual_calibration_summary", {}
    )
    lines = ["## Trust-Tier Correlation", ""]

    tier = ensemble.get("tier", "—")
    score = ensemble.get("score")
    lines.append(f"Ensemble tier: **{tier}** (score {_fmt(score)})")
    lines.append("")

    best_brier = contextual.get("best_dimension_by_adjusted_brier", "—")
    best_ece = contextual.get("best_dimension_by_adjusted_ece", "—")
    if best_brier != "—" or best_ece != "—":
        lines.append(f"- Best contextual dimension (Brier): {best_brier}")
        lines.append(f"- Best contextual dimension (ECE): {best_ece}")
        lines.append("")

    return lines


def _section_conclusion(summary: dict[str, Any]) -> list[str]:
    scoring = summary.get("scoring", {})
    brier = scoring.get("brier_score")
    hit_rate = scoring.get("hit_rate")
    n_events = scoring.get("n_events", 0)
    warnings = summary.get("warnings", [])

    lines = ["## Conclusion", ""]

    issues: list[str] = []
    if n_events == 0:
        issues.append("No scored events — measurement evidence may be missing.")
    if brier is not None and not math.isnan(float(brier)) and float(brier) > 0.30:
        issues.append(f"Brier score ({_fmt(brier)}) exceeds 0.30 threshold.")
    if hit_rate is not None and not math.isnan(float(hit_rate)) and float(hit_rate) < 0.40:
        issues.append(f"Hit rate ({_fmt(hit_rate)}) below 0.40 threshold.")
    if warnings:
        issues.append(f"{len(warnings)} warning(s) raised during evidence collection.")

    if not issues:
        lines.append("All signal quality metrics within acceptable ranges.")
    else:
        for issue in issues:
            lines.append(f"- ⚠ {issue}")

    lines.append("")
    return lines


def generate_performance_report(
    benchmark_summary: dict[str, Any],
    output_path: Path,
) -> Path:
    """Generate a Markdown performance report from a measurement benchmark summary.

    Args:
        benchmark_summary: Parsed JSON from measurement_summary_*.json.
        output_path: Path where the .md report will be written.

    Returns:
        The output_path that was written.
    """
    symbol = benchmark_summary.get("symbol", "unknown")
    timeframe = benchmark_summary.get("timeframe", "unknown")

    lines: list[str] = [
        f"# SMC Performance Report — {symbol} / {timeframe}",
        "",
        f"Generated from measurement benchmark "
        f"(schema v{benchmark_summary.get('schema_version', '?')}).",
        "",
    ]

    lines += _section_signal_quality(benchmark_summary)
    lines += _section_regime_performance(benchmark_summary)
    lines += _section_enrichment_value(benchmark_summary)
    lines += _section_trust_tier(benchmark_summary)
    lines += _section_conclusion(benchmark_summary)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text("\n".join(lines), output_path)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a Markdown performance report from benchmark output."
    )
    parser.add_argument(
        "summary_json",
        type=Path,
        help="Path to a measurement_summary_*.json file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .md path (default: <summary_dir>/performance_report.md).",
    )
    args = parser.parse_args()
    summary_path: Path = args.summary_json

    if not summary_path.exists():
        print(f"Error: {summary_path} not found", file=sys.stderr)
        return 1

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    out = args.output or summary_path.parent / "performance_report.md"
    generate_performance_report(summary, out)
    print(f"Report written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
