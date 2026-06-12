"""Generate a consolidated human-readable performance report from measurement benchmark artifacts.

Reads the benchmark_run_manifest.json and all per-pair summaries, then produces:
  1. A Markdown report  (performance_report.md)
  2. A compact JSON digest (performance_report.json)

Usage:
    python scripts/generate_performance_report.py [--input-dir artifacts/ci/measurement_benchmark] [--output-dir artifacts/reports]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Bug-Hunt 2026-05-01 F-01: deferred so the script also works when
# invoked as `python scripts/X.py` (no PYTHONPATH=.) — sys.path.insert
# above must happen before any first-party `from scripts.` import.
from scripts.smc_atomic_write import atomic_write_text
from smc_core.schema_version import SCHEMA_VERSION
from smc_integration.release_policy import MeasurementShadowThresholds

# ── Thresholds ───────────────────────────────────────────────────────────────

THRESHOLDS = MeasurementShadowThresholds()

_GRADE_THRESHOLDS: list[tuple[str, float]] = [
    ("A", 0.15),
    ("B", 0.25),
    ("C", 0.40),
    ("D", 0.60),
]


def _grade(value: float, *, lower_is_better: bool = True) -> str:
    if math.isnan(value):
        return "–"
    for letter, limit in _GRADE_THRESHOLDS:
        if (lower_is_better and value <= limit) or (not lower_is_better and value >= (1.0 - limit)):
            return letter
    return "F"


def _pct(value: float) -> str:
    if math.isnan(value):
        return "–"
    return f"{value * 100:.1f}%"


def _fmt(value: float, decimals: int = 4) -> str:
    if math.isnan(value):
        return "–"
    return f"{value:.{decimals}f}"


def _pass_fail(value: float, threshold: float) -> str:
    if math.isnan(value):
        return "⚠️"
    return "✅" if value <= threshold else "❌"


# ── Data loading ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class PairReport:
    symbol: str
    timeframe: str
    n_events: int
    brier: float
    log_score: float
    hit_rate: float
    calibration_method: str
    calibrated_brier: float
    calibrated_ece: float
    raw_ece: float
    families_present: list[str]
    family_metrics: dict[str, dict[str, Any]]
    ensemble_score: float
    ensemble_tier: str
    stratified_dimensions: list[str]
    populated_buckets: int
    warnings: list[str]
    contextual_best_brier_dim: str
    contextual_best_ece_dim: str


def _nan(v: Any) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _load_pair(summary: dict[str, Any]) -> PairReport:
    s = summary["scoring"]
    cal = s.get("calibration", {})
    ctx = s.get("contextual_calibration_summary", {})
    eq = summary.get("ensemble_quality", {})
    strat = summary.get("stratification_coverage", {})
    return PairReport(
        symbol=summary["symbol"],
        timeframe=summary["timeframe"],
        n_events=int(s.get("n_events", 0)),
        brier=_nan(s.get("brier_score")),
        log_score=_nan(s.get("log_score")),
        hit_rate=_nan(s.get("hit_rate")),
        calibration_method=str(cal.get("method", "identity")),
        calibrated_brier=_nan(cal.get("calibrated_brier_score")),
        calibrated_ece=_nan(cal.get("calibrated_ece")),
        raw_ece=_nan(cal.get("raw_ece")),
        families_present=list(s.get("families_present", [])),
        family_metrics=dict(s.get("family_metrics", {})),
        ensemble_score=_nan(eq.get("score")),
        ensemble_tier=str(eq.get("tier", "–")),
        stratified_dimensions=list(strat.get("dimensions_present", [])),
        populated_buckets=int(strat.get("populated_bucket_count", 0)),
        warnings=list(summary.get("warnings", [])),
        contextual_best_brier_dim=str(ctx.get("best_dimension_by_adjusted_brier", "–")),
        contextual_best_ece_dim=str(ctx.get("best_dimension_by_adjusted_ece", "–")),
    )


def load_benchmark(input_dir: Path) -> list[PairReport]:
    manifest_path = input_dir / "benchmark_run_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No benchmark manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pairs: list[PairReport] = []
    for run in manifest.get("pair_runs", []):
        summary_path = input_dir / run["summary_path"]
        if not summary_path.exists():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        pairs.append(_load_pair(summary))
    return pairs


# ── Aggregation ──────────────────────────────────────────────────────────────


@dataclass(slots=True)
class AggregateReport:
    total_events: int
    pair_count: int
    symbol_count: int
    avg_brier: float
    avg_calibrated_brier: float
    avg_calibrated_ece: float
    avg_hit_rate: float
    avg_ensemble_score: float
    brier_gate: str
    ece_gate: str
    overall_grade: str
    warnings_total: int    # W4-1 (stat-review wave 4): n for pairs where hit_rate is NOT NaN —
    # the correct denominator for the SPRT test on avg_hit_rate.
    n_hit_rate_valid: int = 0

def _aggregate(pairs: list[PairReport]) -> AggregateReport:
    total = sum(p.n_events for p in pairs)
    symbols = set(p.symbol for p in pairs)

    def _wmean(attr: str) -> float:
        values = [(getattr(p, attr), p.n_events) for p in pairs]
        valid = [(v, w) for v, w in values if not math.isnan(v) and w > 0]
        if not valid:
            return float("nan")
        return sum(v * w for v, w in valid) / sum(w for _, w in valid)

    avg_brier = _wmean("brier")
    avg_cal_brier = _wmean("calibrated_brier")
    avg_cal_ece = _wmean("calibrated_ece")
    avg_hr = _wmean("hit_rate")
    avg_eq = _wmean("ensemble_score")
    warnings_total = sum(len(p.warnings) for p in pairs)
    # W4-1 (stat-review wave 4): count only events from pairs with a valid
    # (non-NaN) hit_rate — this is the correct SPRT denominator for
    # avg_hit_rate (see scripts/run_ab_comparison._sprt_decision).
    n_hr_valid = sum(
        p.n_events for p in pairs if not math.isnan(p.hit_rate) and p.n_events > 0
    )

    brier_gate = _pass_fail(avg_cal_brier, THRESHOLDS.max_calibrated_brier_score)
    ece_gate = _pass_fail(avg_cal_ece, THRESHOLDS.max_calibrated_ece)
    overall = _grade(avg_cal_brier)

    return AggregateReport(
        total_events=total,
        pair_count=len(pairs),
        symbol_count=len(symbols),
        avg_brier=avg_brier,
        avg_calibrated_brier=avg_cal_brier,
        avg_calibrated_ece=avg_cal_ece,
        avg_hit_rate=avg_hr,
        avg_ensemble_score=avg_eq,
        brier_gate=brier_gate,
        ece_gate=ece_gate,
        overall_grade=overall,
        warnings_total=warnings_total,
        n_hit_rate_valid=n_hr_valid,
    )


# ── Markdown rendering ───────────────────────────────────────────────────────


def _render_headline(agg: AggregateReport) -> str:
    return f"""## Headline

| Metric | Value | Gate |
|--------|-------|------|
| Overall Grade | **{agg.overall_grade}** | |
| Events | {agg.total_events:,} | |
| Pairs (symbol × tf) | {agg.pair_count} ({agg.symbol_count} symbols) | |
| Avg Hit Rate | {_pct(agg.avg_hit_rate)} | |
| Avg Brier (raw) | {_fmt(agg.avg_brier)} | |
| Avg Calibrated Brier | {_fmt(agg.avg_calibrated_brier)} | {agg.brier_gate} ≤ {_fmt(THRESHOLDS.max_calibrated_brier_score)} |
| Avg Calibrated ECE | {_fmt(agg.avg_calibrated_ece)} | {agg.ece_gate} ≤ {_fmt(THRESHOLDS.max_calibrated_ece)} |
| Avg Ensemble Quality | {_fmt(agg.avg_ensemble_score, 1)}/100 | |
| Warnings | {agg.warnings_total} | |"""


def _render_pair_table(pairs: list[PairReport]) -> str:
    rows = ["## Per-Symbol × Timeframe Breakdown", ""]
    rows.append("| Symbol | TF | Events | Hit Rate | Brier | Cal Brier | Cal ECE | Grade | Ensemble | Cal Method |")
    rows.append("|--------|-----|--------|----------|-------|-----------|---------|-------|----------|------------|")
    for p in sorted(pairs, key=lambda x: (x.symbol, x.timeframe)):
        rows.append(
            f"| {p.symbol} | {p.timeframe} | {p.n_events} | {_pct(p.hit_rate)} | {_fmt(p.brier)} | {_fmt(p.calibrated_brier)} | {_fmt(p.calibrated_ece)} | {_grade(p.calibrated_brier)} | {_fmt(p.ensemble_score, 1)} ({p.ensemble_tier}) | {p.calibration_method} |"
        )
    return "\n".join(rows)


def _render_family_table(pairs: list[PairReport]) -> str:
    all_families: set[str] = set()
    for p in pairs:
        all_families.update(p.family_metrics.keys())
    if not all_families:
        return ""

    family_agg: dict[str, dict[str, float]] = {}
    for fam in sorted(all_families):
        total_n = 0
        sum_brier = 0.0
        sum_hr = 0.0
        for p in pairs:
            fm = p.family_metrics.get(fam, {})
            n = int(fm.get("n_events", 0))
            if n > 0:
                total_n += n
                sum_brier += _nan(fm.get("brier_score")) * n
                sum_hr += _nan(fm.get("hit_rate")) * n
        if total_n > 0:
            family_agg[fam] = {
                "n_events": total_n,
                "brier": sum_brier / total_n,
                "hit_rate": sum_hr / total_n,
            }

    rows = ["## Per-Family Breakdown", ""]
    rows.append("| Family | Events | Hit Rate | Brier | Grade |")
    rows.append("|--------|--------|----------|-------|-------|")
    for fam in sorted(family_agg):
        a = family_agg[fam]
        rows.append(f"| {fam} | {int(a['n_events'])} | {_pct(a['hit_rate'])} | {_fmt(a['brier'])} | {_grade(a['brier'])} |")
    return "\n".join(rows)


def _render_stratification(pairs: list[PairReport]) -> str:
    rows = ["## Stratification Coverage", ""]
    rows.append("| Symbol | TF | Dimensions | Populated Buckets | Best Brier Dim | Best ECE Dim |")
    rows.append("|--------|-----|------------|-------------------|----------------|--------------|")
    for p in sorted(pairs, key=lambda x: (x.symbol, x.timeframe)):
        dims = ", ".join(p.stratified_dimensions) if p.stratified_dimensions else "–"
        rows.append(
            f"| {p.symbol} | {p.timeframe} | {dims} | {p.populated_buckets} | {p.contextual_best_brier_dim} | {p.contextual_best_ece_dim} |"
        )
    return "\n".join(rows)


def _render_warnings(pairs: list[PairReport]) -> str:
    has_warnings = [p for p in pairs if p.warnings]
    if not has_warnings:
        return "## Warnings\n\nNone."
    rows = ["## Warnings", ""]
    for p in has_warnings:
        rows.append(f"### {p.symbol} / {p.timeframe}")
        for w in p.warnings:
            rows.append(f"- {w}")
        rows.append("")
    return "\n".join(rows)


def render_report(pairs: list[PairReport], *, generated_at: str) -> str:
    agg = _aggregate(pairs)
    sections = [
        "# SMC Performance Report",
        "",
        f"Generated: {generated_at}  ",
        f"Schema: {SCHEMA_VERSION}",
        "",
        _render_headline(agg),
        "",
        _render_pair_table(pairs),
        "",
        _render_family_table(pairs),
        "",
        _render_stratification(pairs),
        "",
        _render_warnings(pairs),
        "",
        "---",
        "*Report generated by `scripts/generate_performance_report.py`*",
    ]
    return "\n".join(sections) + "\n"


# ── JSON digest ──────────────────────────────────────────────────────────────


def build_digest(pairs: list[PairReport], *, generated_at: str) -> dict[str, Any]:
    agg = _aggregate(pairs)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "generator": "scripts/generate_performance_report.py",
        "headline": {
            "overall_grade": agg.overall_grade,
            "total_events": agg.total_events,
            "pair_count": agg.pair_count,
            "symbol_count": agg.symbol_count,
            "avg_brier": round(agg.avg_brier, 6),
            "avg_calibrated_brier": round(agg.avg_calibrated_brier, 6),
            "avg_calibrated_ece": round(agg.avg_calibrated_ece, 6),
            "avg_hit_rate": round(agg.avg_hit_rate, 6),
            "avg_ensemble_score": round(agg.avg_ensemble_score, 2),
            "brier_gate_passed": agg.brier_gate == "✅",
            "ece_gate_passed": agg.ece_gate == "✅",
            "warnings_total": agg.warnings_total,
        },
        "pairs": [
            {
                "symbol": p.symbol,
                "timeframe": p.timeframe,
                "n_events": p.n_events,
                "brier": round(p.brier, 6),
                "calibrated_brier": round(p.calibrated_brier, 6),
                "calibrated_ece": round(p.calibrated_ece, 6),
                "hit_rate": round(p.hit_rate, 6),
                "ensemble_score": round(p.ensemble_score, 2),
                "ensemble_tier": p.ensemble_tier,
                "grade": _grade(p.calibrated_brier),
                "warning_count": len(p.warnings),
            }
            for p in sorted(pairs, key=lambda x: (x.symbol, x.timeframe))
        ],
        "thresholds": {
            "max_brier_score": THRESHOLDS.max_brier_score,
            "max_calibrated_brier_score": THRESHOLDS.max_calibrated_brier_score,
            "max_calibrated_ece": THRESHOLDS.max_calibrated_ece,
        },
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate consolidated performance report from benchmark artifacts.")
    parser.add_argument(
        "--input-dir",
        default="artifacts/ci/measurement_benchmark",
        help="Directory containing the benchmark_run_manifest.json and pair summaries.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/reports",
        help="Directory to write the performance_report.md and performance_report.json.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs = load_benchmark(input_dir)
    if not pairs:
        print("No benchmark pair summaries found.", file=sys.stderr)
        return 1

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    report_md = render_report(pairs, generated_at=generated_at)
    md_path = output_dir / "performance_report.md"
    atomic_write_text(report_md, md_path)
    print(f"Report written: {md_path}")

    digest = build_digest(pairs, generated_at=generated_at)
    json_path = output_dir / "performance_report.json"
    atomic_write_text(json.dumps(digest, indent=2) + "\n", json_path)
    print(f"Digest written: {json_path}")

    print(f"\n{report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
