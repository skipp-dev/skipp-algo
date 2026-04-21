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
from scripts.smc_sprt_stop_rule import SPRTConfig, terminal_decision


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

    decision = decide_recommendation(rows)

    sprt = _sprt_decision(ctrl_agg, treat_agg)

    return {
        "experiment": experiment_name,
        "control_pairs": len(control_pairs),
        "treatment_pairs": len(treatment_pairs),
        "control_grade": _grade(getattr(ctrl_agg, "avg_calibrated_brier", 1.0)),
        "treatment_grade": _grade(getattr(treat_agg, "avg_calibrated_brier", 1.0)),
        "metrics": rows,
        "recommendation": decision["recommendation"],
        "recommendation_reason": decision["reason"],
        "kpi_thresholds": decision["kpi_thresholds"],
        "sprt": sprt,
    }


# ── G3/F2 SPRT terminal decision ───────────────────────────────────────────


# Wald SPRT parameters bound to the comparison output. p0/p1 follow plan
# §2.4 G3: minimum-detectable effect of +5 percentage points hit-rate
# improvement over a 0.55 baseline (the lifetime-corpus median across
# families). alpha=0.05, beta=0.20 are the conventional gate settings.
SPRT_P0 = 0.55
SPRT_P1 = 0.60
SPRT_ALPHA = 0.05
SPRT_BETA = 0.20


def _sprt_decision(ctrl_agg: Any, treat_agg: Any) -> dict[str, Any]:
    """Compute the terminal SPRT decision for the treatment arm.

    Single-arm Wald SPRT: tests treatment hit rate against the *fixed*
    baseline ``SPRT_P0`` (lifetime-corpus median), not against the
    in-experiment control. This matches the F2 promotion-gate semantics
    in ``docs/f2_contextual_promotion_decision_2026-04-21.md`` step 3.

    Returns a structured dict with the decision, totals, and the
    resolved Wald bounds. Hit-rate values arrive as percentages
    (0–100); we convert to fractions before deriving k.
    """
    n = int(getattr(treat_agg, "total_events", 0) or 0)
    hr_pct = float(getattr(treat_agg, "avg_hit_rate", 0.0) or 0.0)
    # avg_hit_rate is in percent; clamp into [0, 100] before conversion.
    hr_pct = max(0.0, min(100.0, hr_pct))
    k = round(n * hr_pct / 100.0)

    config = SPRTConfig(
        p0=SPRT_P0,
        p1=SPRT_P1,
        alpha=SPRT_ALPHA,
        beta=SPRT_BETA,
    )
    state, decision = terminal_decision(n=n, k=k, config=config)
    return {
        "decision": decision,
        "n": state.n,
        "k": state.k,
        "hit_rate": round(state.hit_rate, 4),
        "llr": round(state.llr, 4),
        "wald_upper": round(config.upper_bound, 4),
        "wald_lower": round(config.lower_bound, 4),
        "config": {
            "p0": SPRT_P0,
            "p1": SPRT_P1,
            "alpha": SPRT_ALPHA,
            "beta": SPRT_BETA,
        },
        # Mirror the control arm's totals so the report is self-contained.
        "control_n": int(getattr(ctrl_agg, "total_events", 0) or 0),
        "control_hit_rate": round(
            float(getattr(ctrl_agg, "avg_hit_rate", 0.0) or 0.0) / 100.0, 4
        ),
    }


# ── Promotion decision (ENG-WS4-04) ────────────────────────────────────────


# KPI thresholds binding the Promote / Hold / Rollback decision.
# Lower-is-better metrics (brier, calibrated_brier, calibrated_ece):
#   * PROMOTE if treatment improves both calibrated_brier AND calibrated_ece
#     by at least PROMOTE_IMPROVEMENT, AND hit_rate does not regress by
#     more than HIT_RATE_REGRESSION_TOLERANCE.
#   * ROLLBACK if either calibrated_brier OR calibrated_ece regresses by
#     more than ROLLBACK_REGRESSION.
#   * HOLD otherwise.
PROMOTE_IMPROVEMENT = 0.005
ROLLBACK_REGRESSION = 0.010
HIT_RATE_REGRESSION_TOLERANCE = 1.0  # percentage points


def _row_by_metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("metric") == key:
            return row
    return None


def decide_recommendation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Map a comparison-metric table to a Promote/Hold/Rollback decision.

    DoD: 'Comparison-Output enthaelt Promote/Hold/Rollback-Empfehlung'
    and 'die Entscheidung ist an klare KPI-Schwellen gebunden'.
    """
    cb = _row_by_metric(rows, "calibrated_brier") or {}
    ce = _row_by_metric(rows, "calibrated_ece") or {}
    hr = _row_by_metric(rows, "hit_rate_pct") or {}

    cb_delta = float(cb.get("delta") or 0.0)  # lower = better
    ce_delta = float(ce.get("delta") or 0.0)
    hr_delta = float(hr.get("delta") or 0.0)  # higher = better

    thresholds = {
        "promote_improvement": PROMOTE_IMPROVEMENT,
        "rollback_regression": ROLLBACK_REGRESSION,
        "hit_rate_regression_tolerance": HIT_RATE_REGRESSION_TOLERANCE,
    }

    # Rollback first — a regression on either calibration metric trumps.
    if cb_delta > ROLLBACK_REGRESSION or ce_delta > ROLLBACK_REGRESSION:
        return {
            "recommendation": "rollback",
            "reason": (
                f"calibrated_brier delta {cb_delta:+.4f} or calibrated_ece delta "
                f"{ce_delta:+.4f} exceeds rollback regression "
                f"{ROLLBACK_REGRESSION:+.4f}"
            ),
            "kpi_thresholds": thresholds,
        }

    # Promote when both calibration metrics improve materially AND hit_rate
    # does not regress more than the tolerance.
    promote_cb = cb_delta <= -PROMOTE_IMPROVEMENT
    promote_ce = ce_delta <= -PROMOTE_IMPROVEMENT
    hit_rate_ok = hr_delta >= -HIT_RATE_REGRESSION_TOLERANCE
    if promote_cb and promote_ce and hit_rate_ok:
        return {
            "recommendation": "promote",
            "reason": (
                f"calibrated_brier {cb_delta:+.4f} and calibrated_ece {ce_delta:+.4f} "
                f"both improve by ≥{PROMOTE_IMPROVEMENT} and hit_rate delta "
                f"{hr_delta:+.2f}pp within tolerance {HIT_RATE_REGRESSION_TOLERANCE}pp"
            ),
            "kpi_thresholds": thresholds,
        }

    return {
        "recommendation": "hold",
        "reason": (
            f"deltas (calibrated_brier={cb_delta:+.4f}, calibrated_ece={ce_delta:+.4f}, "
            f"hit_rate={hr_delta:+.2f}pp) do not meet promote thresholds and stay "
            f"within rollback bounds"
        ),
        "kpi_thresholds": thresholds,
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
    # ENG-WS4-04: Promote / Hold / Rollback decision section.
    rec = str(digest.get("recommendation") or "hold").upper()
    reason = str(digest.get("recommendation_reason") or "")
    thresholds = digest.get("kpi_thresholds") or {}
    lines.append("## Recommendation")
    lines.append("")
    lines.append(f"**Decision:** `{rec}`")
    lines.append("")
    if reason:
        lines.append(f"_{reason}_")
        lines.append("")
    if thresholds:
        lines.append("KPI thresholds:")
        for key, val in thresholds.items():
            lines.append(f"- `{key}` = {val}")
        lines.append("")
    sprt = digest.get("sprt") or {}
    if sprt:
        lines.append("## SPRT Stop-Rule (G3/F2)")
        lines.append("")
        lines.append(f"**Terminal decision:** `{str(sprt.get('decision') or '').upper()}`")
        lines.append("")
        lines.append(
            f"- treatment n={sprt.get('n')}, k={sprt.get('k')}, "
            f"hit_rate={sprt.get('hit_rate')}"
        )
        lines.append(
            f"- LLR = {sprt.get('llr')} (Wald bounds: "
            f"lower={sprt.get('wald_lower')}, upper={sprt.get('wald_upper')})"
        )
        cfg = sprt.get("config") or {}
        lines.append(
            f"- config: p0={cfg.get('p0')}, p1={cfg.get('p1')}, "
            f"alpha={cfg.get('alpha')}, beta={cfg.get('beta')}"
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
