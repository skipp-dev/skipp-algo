"""Automated Freeze-Exit Check (WP-16).

Evaluates the stability criteria from docs/freeze_exit_stability_criteria.md §2
against available CI artefacts and produces a machine-readable go/no-go verdict.

Usage:
    python -m scripts.run_freeze_exit_check [--artifacts-dir artifacts/ci]
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds from freeze_exit_stability_criteria.md §2
# ---------------------------------------------------------------------------
MIN_BENCHMARK_REPORTS = 2
BRIER_CEILING = 0.60
ECE_CEILING = 0.30
SMOKE_MIN_SCORE = 7
SMOKE_MAX_SCORE = 10


@dataclass
class CriterionResult:
    """Result of a single freeze-exit criterion check."""

    name: str
    passed: bool
    detail: str
    evidence_ref: str = ""


@dataclass
class FreezeExitVerdict:
    """Aggregate freeze-exit verdict."""

    freeze_exit_ready: bool
    blocking_reasons: list[str] = field(default_factory=list)
    advisory_reasons: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    criteria: list[dict[str, Any]] = field(default_factory=list)
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Criterion checkers
# ---------------------------------------------------------------------------

def _check_benchmark_reports(artifacts_dir: Path) -> CriterionResult:
    """§2.3 — At least MIN_BENCHMARK_REPORTS benchmark reports exist."""
    benchmark_dir = artifacts_dir / "measurement_benchmark"
    manifest = benchmark_dir / "benchmark_run_manifest.json"

    if not manifest.exists():
        return CriterionResult(
            name="benchmark_reports",
            passed=False,
            detail=f"No benchmark manifest found at {manifest}",
            evidence_ref=str(manifest),
        )

    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        runs = data.get("runs", []) if isinstance(data, dict) else data
        count = len(runs) if isinstance(runs, list) else 0
    except (json.JSONDecodeError, KeyError):
        count = 0

    passed = count >= MIN_BENCHMARK_REPORTS
    return CriterionResult(
        name="benchmark_reports",
        passed=passed,
        detail=f"{count} benchmark run(s) found (need ≥{MIN_BENCHMARK_REPORTS})",
        evidence_ref=str(manifest),
    )


def _check_benchmark_metrics(artifacts_dir: Path) -> CriterionResult:
    """§2.3 — Brier ≤ BRIER_CEILING and ECE ≤ ECE_CEILING across summaries."""
    summary_csv = artifacts_dir / "measurement_benchmark" / "benchmark_run_summary.csv"
    if not summary_csv.exists():
        return CriterionResult(
            name="benchmark_metrics",
            passed=False,
            detail=f"No benchmark summary at {summary_csv}",
            evidence_ref=str(summary_csv),
        )

    import csv

    violations: list[str] = []
    with summary_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            brier = float(row.get("brier_score", row.get("brier", "0")) or "0")
            ece = float(row.get("ece", row.get("calibration_ece", "0")) or "0")
            symbol = row.get("symbol", "?")
            tf = row.get("timeframe", "?")
            if brier > BRIER_CEILING:
                violations.append(f"{symbol}/{tf}: Brier {brier:.3f} > {BRIER_CEILING}")
            if ece > ECE_CEILING:
                violations.append(f"{symbol}/{tf}: ECE {ece:.3f} > {ECE_CEILING}")

    passed = len(violations) == 0
    detail = "All metrics within thresholds" if passed else "; ".join(violations[:5])
    return CriterionResult(
        name="benchmark_metrics",
        passed=passed,
        detail=detail,
        evidence_ref=str(summary_csv),
    )


def _check_smoke_test(artifacts_dir: Path) -> CriterionResult:
    """§2.4 — Smoke test score ≥ SMOKE_MIN_SCORE/SMOKE_MAX_SCORE."""
    smoke_report = artifacts_dir / "smoke_test" / "smoke_report.json"
    if not smoke_report.exists():
        return CriterionResult(
            name="smoke_test",
            passed=False,
            detail=f"No smoke report at {smoke_report}",
            evidence_ref=str(smoke_report),
        )

    try:
        data = json.loads(smoke_report.read_text(encoding="utf-8"))
        score = data.get("score", data.get("smoke_score", 0))
        if isinstance(score, str):
            # Handle "7/10" format
            score = int(score.split("/")[0])
    except (json.JSONDecodeError, ValueError, KeyError):
        score = 0

    passed = score >= SMOKE_MIN_SCORE
    return CriterionResult(
        name="smoke_test",
        passed=passed,
        detail=f"Smoke score: {score}/{SMOKE_MAX_SCORE} (need ≥{SMOKE_MIN_SCORE})",
        evidence_ref=str(smoke_report),
    )


def _check_release_gates(artifacts_dir: Path) -> CriterionResult:
    """Check latest release gates baseline report for blocking failures."""
    report_path = artifacts_dir / "smc_release_gates_baseline_report.json"
    if not report_path.exists():
        return CriterionResult(
            name="release_gates",
            passed=False,
            detail=f"No release gates report at {report_path}",
            evidence_ref=str(report_path),
        )

    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        status = data.get("status", data.get("gate_status", "unknown"))
    except (json.JSONDecodeError, KeyError):
        status = "unknown"

    passed = status in ("ok", "pass", "green", "warn")
    return CriterionResult(
        name="release_gates",
        passed=passed,
        detail=f"Release gate status: {status}",
        evidence_ref=str(report_path),
    )


def _check_quality_floor(artifacts_dir: Path) -> CriterionResult:
    """Advisory — Check quality floor tier from benchmark summary."""
    try:
        from smc_integration.release_policy import quality_tier_release_advisory
    except ImportError:
        return CriterionResult(
            name="quality_floor",
            passed=True,
            detail="Quality floor module not available (advisory only)",
        )

    summary_csv = artifacts_dir / "measurement_benchmark" / "benchmark_run_summary.csv"
    if not summary_csv.exists():
        return CriterionResult(
            name="quality_floor",
            passed=True,
            detail="No benchmark summary for quality floor check (advisory only)",
            evidence_ref=str(summary_csv),
        )

    import csv

    worst_tier = "production_grade"
    tier_order = ["production_grade", "acceptable", "minimal", "below_minimal"]

    with summary_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            brier = float(row.get("brier_score", row.get("brier", "0")) or "0")
            ece = float(row.get("ece", row.get("calibration_ece", "0")) or "0")
            n_events = int(row.get("n_events", row.get("event_count", "1")) or "1")
            result = quality_tier_release_advisory(brier, ece, n_events)
            tier = result["tier"]
            if tier_order.index(tier) > tier_order.index(worst_tier):
                worst_tier = tier

    passed = worst_tier != "below_minimal"
    return CriterionResult(
        name="quality_floor",
        passed=passed,
        detail=f"Worst quality tier: {worst_tier}",
        evidence_ref=str(summary_csv),
    )


def _check_publish_drift(artifacts_dir: Path) -> CriterionResult:
    """Advisory — Check publish manifest for drift."""
    manifest_path = Path("artifacts/publish_manifest.json")
    if not manifest_path.exists():
        return CriterionResult(
            name="publish_drift",
            passed=True,
            detail="No publish manifest (advisory — run detect_publish_drift.py)",
        )

    try:
        from scripts.detect_publish_drift import detect_drift

        drifted = detect_drift(manifest_path)
        passed = len(drifted) == 0
        detail = "No drift" if passed else f"{len(drifted)} file(s) drifted"
    except ImportError:
        passed = True
        detail = "Drift detector not available (advisory only)"

    return CriterionResult(
        name="publish_drift",
        passed=passed,
        detail=detail,
        evidence_ref=str(manifest_path),
    )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

BLOCKING_CHECKS = [
    _check_benchmark_reports,
    _check_benchmark_metrics,
    _check_smoke_test,
    _check_release_gates,
]

ADVISORY_CHECKS = [
    _check_quality_floor,
    _check_publish_drift,
]


def run_freeze_exit_check(
    artifacts_dir: Path | None = None,
) -> FreezeExitVerdict:
    """Execute all freeze-exit criteria and return a verdict."""
    if artifacts_dir is None:
        artifacts_dir = Path("artifacts/ci")

    results: list[CriterionResult] = []
    blocking: list[str] = []
    advisory: list[str] = []
    evidence: list[str] = []

    for check_fn in BLOCKING_CHECKS:
        result = check_fn(artifacts_dir)
        results.append(result)
        if result.evidence_ref:
            evidence.append(result.evidence_ref)
        if not result.passed:
            blocking.append(f"{result.name}: {result.detail}")

    for check_fn in ADVISORY_CHECKS:
        result = check_fn(artifacts_dir)
        results.append(result)
        if result.evidence_ref:
            evidence.append(result.evidence_ref)
        if not result.passed:
            advisory.append(f"{result.name}: {result.detail}")

    return FreezeExitVerdict(
        freeze_exit_ready=len(blocking) == 0,
        blocking_reasons=blocking,
        advisory_reasons=advisory,
        evidence_refs=evidence,
        criteria=[asdict(r) for r in results],
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


def write_verdict_markdown(verdict: FreezeExitVerdict, path: Path) -> None:
    """Write a compact markdown summary of the verdict."""
    status = "READY" if verdict.freeze_exit_ready else "BLOCKED"
    lines = [
        f"# Freeze-Exit Check — {status}",
        "",
        f"Checked: {verdict.checked_at}",
        "",
        "## Criteria",
        "",
        "| Criterion | Result | Detail |",
        "|-----------|--------|--------|",
    ]
    for c in verdict.criteria:
        icon = "✅" if c["passed"] else "❌"
        lines.append(f"| {c['name']} | {icon} | {c['detail']} |")

    if verdict.blocking_reasons:
        lines.extend(["", "## Blocking Reasons", ""])
        for r in verdict.blocking_reasons:
            lines.append(f"- {r}")

    if verdict.advisory_reasons:
        lines.extend(["", "## Advisory", ""])
        for r in verdict.advisory_reasons:
            lines.append(f"- {r}")

    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Freeze-Exit Check")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("artifacts/ci"),
        help="Path to CI artifacts directory.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write JSON verdict.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=None,
        help="Optional path to write Markdown summary.",
    )
    args = parser.parse_args()

    verdict = run_freeze_exit_check(artifacts_dir=args.artifacts_dir)
    print(json.dumps(verdict.to_dict(), indent=2))

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(verdict.to_dict(), indent=2) + "\n", encoding="utf-8"
        )

    if args.output_md:
        write_verdict_markdown(verdict, args.output_md)

    raise SystemExit(0 if verdict.freeze_exit_ready else 1)


if __name__ == "__main__":
    main()
