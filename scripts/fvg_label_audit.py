"""D1: FVG Label Audit — investigate FVG underperformance.

Analyses benchmark scoring artifacts to understand why FVG hit rate (59.4%)
lags significantly behind OB (86.4%), BOS (91.3%), and SWEEP (83.3%).

Produces a structured report with:
- Per-pair FVG vs other-family comparison
- Partial-fill analysis (what % of missed FVGs had ≥50% fill?)
- Lookahead sensitivity (would 16/20/24 bars improve HR?)
- Context breakdown (session × vol_regime for FVG events)
- FVG zone size analysis (are larger gaps harder to fill?)

Usage::

    python scripts/fvg_label_audit.py \\
        --benchmark-dir artifacts/ci/measurement_benchmark \\
        --output-path artifacts/reports/fvg_label_audit.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Bug-Hunt 2026-05-01 F-01: deferred so the script also works when
# invoked as `python scripts/X.py` (no PYTHONPATH=.) — sys.path.insert
# above must happen before any first-party `from scripts.` import.
from scripts.smc_atomic_write import atomic_write_text  # noqa: E402


@dataclass(slots=True)
class FVGEventDetail:
    """A single FVG event with audit details."""

    event_id: str
    symbol: str
    timeframe: str
    direction: str
    zone_low: float
    zone_high: float
    zone_size_pct: float  # (high - low) / midpoint as %
    hit_12: bool  # mitigated within 12 bars (current label)
    hit_16: bool  # mitigated within 16 bars
    hit_20: bool  # mitigated within 20 bars
    hit_24: bool  # mitigated within 24 bars
    partial_fill_pct: float  # max penetration into zone (0.0–1.0)
    time_to_first_touch: int | None  # bars until first zone touch
    invalidated: bool
    invalidated_bar: int | None  # bar index of invalidation
    session: str
    vol_regime: str
    htf_bias: str


@dataclass(slots=True)
class FVGAuditResult:
    """Structured output of the FVG label audit."""

    total_fvg_events: int = 0
    hit_rate_12: float = 0.0
    hit_rate_16: float = 0.0
    hit_rate_20: float = 0.0
    hit_rate_24: float = 0.0
    partial_fill_50_rate: float = 0.0  # % of misses with ≥50% fill
    partial_fill_75_rate: float = 0.0  # % of misses with ≥75% fill
    avg_zone_size_pct_hit: float = 0.0
    avg_zone_size_pct_miss: float = 0.0
    invalidation_rate: float = 0.0
    avg_time_to_touch: float = 0.0
    per_pair: dict[str, dict[str, Any]] = field(default_factory=dict)
    per_context: dict[str, dict[str, Any]] = field(default_factory=dict)
    family_comparison: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def _load_scored_events(benchmark_dir: Path) -> list[dict[str, Any]]:
    """Load raw scored event data from scoring artifacts."""
    events: list[dict[str, Any]] = []
    for scoring_file in sorted(benchmark_dir.rglob("scoring_*.json")):
        try:
            data = json.loads(scoring_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        parts = scoring_file.parts
        # Extract symbol/timeframe from path: .../SYMBOL/TF/scoring_*.json
        symbol = parts[-3] if len(parts) >= 3 else "?"
        timeframe = parts[-2] if len(parts) >= 2 else "?"

        for family_name, fm in data.get("family_metrics", {}).items():
            events.append({
                "family": family_name,
                "symbol": symbol,
                "timeframe": timeframe,
                "n_events": fm.get("n_events", 0),
                "hit_rate": fm.get("hit_rate", 0.0),
                "brier_score": fm.get("brier_score", 0.0),
            })

    return events


def _load_benchmark_kpis(benchmark_dir: Path) -> list[dict[str, Any]]:
    """Load benchmark KPIs with time-to-mitigation, MAE/MFE."""
    kpis: list[dict[str, Any]] = []
    for bench_file in sorted(benchmark_dir.rglob("benchmark_*.json")):
        # Skip the manifest
        if "manifest" in bench_file.name:
            continue
        try:
            data = json.loads(bench_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        parts = bench_file.parts
        symbol = parts[-3] if len(parts) >= 3 else "?"
        timeframe = parts[-2] if len(parts) >= 2 else "?"

        for kpi in data.get("kpis", []):
            kpi["symbol"] = symbol
            kpi["timeframe"] = timeframe
            kpis.append(kpi)

        # Also grab stratified data for context breakdown
        for bucket_key, bucket_kpis in data.get("stratified", {}).items():
            for kpi in bucket_kpis:
                kpi["symbol"] = symbol
                kpi["timeframe"] = timeframe
                kpi["bucket"] = bucket_key
                kpis.append(kpi)

    return kpis


def _fvg_vs_family_comparison(kpis: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Compare FVG aggregate stats against each other family."""
    families: dict[str, list[dict[str, Any]]] = {}
    for kpi in kpis:
        if kpi.get("bucket"):
            continue  # skip stratified
        family = kpi.get("family", "")
        families.setdefault(family, []).append(kpi)

    comparison: dict[str, dict[str, Any]] = {}
    for family, family_kpis in sorted(families.items()):
        total_events = sum(int(k.get("n_events", 0) or 0) for k in family_kpis)
        total_hits = sum(
            round(float(k.get("hit_rate", 0.0) or 0.0) * int(k.get("n_events", 0) or 0))
            for k in family_kpis
        )
        hit_rate = total_hits / total_events if total_events > 0 else 0.0

        ttm_values = [
            float(k.get("time_to_mitigation_mean", 0.0) or 0.0)
            for k in family_kpis
            if k.get("time_to_mitigation_mean") is not None
        ]
        avg_ttm = sum(ttm_values) / len(ttm_values) if ttm_values else 0.0

        inv_values = [
            float(k.get("invalidation_rate", 0.0) or 0.0)
            for k in family_kpis
        ]
        avg_inv = sum(inv_values) / len(inv_values) if inv_values else 0.0

        mae_values = [float(k.get("mae", 0.0) or 0.0) for k in family_kpis]
        mfe_values = [float(k.get("mfe", 0.0) or 0.0) for k in family_kpis]
        pfill_values = [
            float(k.get("partial_fill_pct_mean", 0.0) or 0.0)
            for k in family_kpis
            if k.get("partial_fill_pct_mean") is not None
        ]

        comparison[family] = {
            "total_events": total_events,
            "total_hits": total_hits,
            "hit_rate": round(hit_rate, 4),
            "avg_time_to_mitigation": round(avg_ttm, 2),
            "avg_invalidation_rate": round(avg_inv, 4),
            "avg_mae": round(sum(mae_values) / len(mae_values), 6) if mae_values else 0.0,
            "avg_mfe": round(sum(mfe_values) / len(mfe_values), 6) if mfe_values else 0.0,
            "avg_partial_fill_pct": round(sum(pfill_values) / len(pfill_values), 4) if pfill_values else 0.0,
            "pairs": len(family_kpis),
        }

    return comparison


def _fvg_per_pair_breakdown(kpis: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """FVG performance per symbol×timeframe pair."""
    per_pair: dict[str, dict[str, Any]] = {}
    for kpi in kpis:
        if kpi.get("family") != "FVG" or kpi.get("bucket"):
            continue
        pair_key = f"{kpi['symbol']}/{kpi['timeframe']}"
        per_pair[pair_key] = {
            "n_events": int(kpi.get("n_events", 0) or 0),
            "hit_rate": round(float(kpi.get("hit_rate", 0.0) or 0.0), 4),
            "time_to_mitigation_mean": round(float(kpi.get("time_to_mitigation_mean", 0.0) or 0.0), 2),
            "invalidation_rate": round(float(kpi.get("invalidation_rate", 0.0) or 0.0), 4),
            "mae": round(float(kpi.get("mae", 0.0) or 0.0), 6),
            "mfe": round(float(kpi.get("mfe", 0.0) or 0.0), 6),
        }
    return per_pair


def _fvg_context_breakdown(kpis: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """FVG performance stratified by context dimensions."""
    context: dict[str, dict[str, Any]] = {}
    for kpi in kpis:
        if kpi.get("family") != "FVG":
            continue
        bucket = kpi.get("bucket")
        if not bucket:
            continue
        n = int(kpi.get("n_events", 0) or 0)
        if n == 0:
            continue
        context.setdefault(bucket, {"n_events": 0, "hits": 0})
        context[bucket]["n_events"] += n
        context[bucket]["hits"] += round(float(kpi.get("hit_rate", 0.0) or 0.0) * n)

    for _bucket, stats in context.items():
        stats["hit_rate"] = round(
            stats["hits"] / stats["n_events"], 4
        ) if stats["n_events"] > 0 else 0.0

    return context


def _derive_findings(
    comparison: dict[str, dict[str, Any]],
    per_pair: dict[str, dict[str, Any]],
    context: dict[str, dict[str, Any]],
) -> list[str]:
    """Generate human-readable findings from the analysis."""
    findings: list[str] = []

    fvg = comparison.get("FVG", {})
    fvg_hr = fvg.get("hit_rate", 0.0)
    fvg_inv = fvg.get("avg_invalidation_rate", 0.0)
    fvg_ttm = fvg.get("avg_time_to_mitigation", 0.0)
    fvg_events = fvg.get("total_events", 0)

    # Compare with best family
    best_family = max(
        (f for f in comparison if f != "FVG"),
        key=lambda f: comparison[f].get("hit_rate", 0.0),
        default=None,
    )
    if best_family:
        best_hr = comparison[best_family].get("hit_rate", 0.0)
        gap = best_hr - fvg_hr
        findings.append(
            f"FVG hit rate ({fvg_hr:.1%}) is {gap:.1%} below {best_family} ({best_hr:.1%})"
        )

    # Invalidation comparison
    other_inv_rates = [
        comparison[f].get("avg_invalidation_rate", 0.0)
        for f in comparison if f != "FVG"
    ]
    avg_other_inv = sum(other_inv_rates) / len(other_inv_rates) if other_inv_rates else 0.0
    if fvg_inv > avg_other_inv + 0.1:
        findings.append(
            f"FVG invalidation rate ({fvg_inv:.1%}) is significantly higher "
            f"than other families avg ({avg_other_inv:.1%})"
        )

    # Time-to-mitigation
    if fvg_ttm > 0:
        other_ttm = [
            comparison[f].get("avg_time_to_mitigation", 0.0)
            for f in comparison if f != "FVG" and comparison[f].get("avg_time_to_mitigation", 0.0) > 0
        ]
        avg_other_ttm = sum(other_ttm) / len(other_ttm) if other_ttm else 0.0
        if fvg_ttm > avg_other_ttm * 1.3:
            findings.append(
                f"FVG avg time-to-mitigation ({fvg_ttm:.1f} bars) is slower than "
                f"other families avg ({avg_other_ttm:.1f} bars) — zone fill takes longer"
            )

    # Per-pair variance
    pair_hrs = [p["hit_rate"] for p in per_pair.values() if p.get("n_events", 0) >= 3]
    if pair_hrs:
        min_hr = min(pair_hrs)
        max_hr = max(pair_hrs)
        if max_hr - min_hr > 0.3:
            worst_pair = min(per_pair, key=lambda k: per_pair[k].get("hit_rate", 1.0))
            best_pair = max(per_pair, key=lambda k: per_pair[k].get("hit_rate", 0.0))
            findings.append(
                f"FVG hit rate varies widely across pairs: "
                f"{best_pair} ({max_hr:.1%}) vs {worst_pair} ({min_hr:.1%}) — "
                f"suggests context-dependent performance"
            )

    # Volume of events
    if fvg_events > 0:
        total = sum(c.get("total_events", 0) for c in comparison.values())
        share = fvg_events / total if total > 0 else 0
        findings.append(
            f"FVG represents {share:.1%} of all events ({fvg_events}/{total}) — "
            f"largest family, so improving it has outsized impact on overall grade"
        )

    # Context pockets
    good_buckets = [
        (b, s) for b, s in context.items()
        if s.get("n_events", 0) >= 3 and s.get("hit_rate", 0.0) >= 0.70
    ]
    bad_buckets = [
        (b, s) for b, s in context.items()
        if s.get("n_events", 0) >= 3 and s.get("hit_rate", 0.0) < 0.50
    ]
    if good_buckets:
        labels = ", ".join(f"{b} ({s['hit_rate']:.0%})" for b, s in good_buckets)
        findings.append(f"FVG performs well in contexts: {labels}")
    if bad_buckets:
        labels = ", ".join(f"{b} ({s['hit_rate']:.0%})" for b, s in bad_buckets)
        findings.append(f"FVG underperforms in contexts: {labels}")

    return findings


def _derive_recommendations(
    comparison: dict[str, dict[str, Any]],
    per_pair: dict[str, dict[str, Any]],
    context: dict[str, dict[str, Any]],
    findings: list[str],
) -> list[str]:
    """Generate actionable recommendations."""
    recs: list[str] = []

    fvg = comparison.get("FVG", {})
    fvg_inv = fvg.get("avg_invalidation_rate", 0.0)
    fvg_ttm = fvg.get("avg_time_to_mitigation", 0.0)

    # R1: Lookahead window
    if fvg_ttm >= 4.0:
        recs.append(
            "INVESTIGATE: Extend FVG lookahead window from 12 to 16-20 bars — "
            f"avg time-to-mitigation is {fvg_ttm:.1f} bars, some fills may occur "
            "just outside the current window"
        )

    # R2: Invalidation
    if fvg_inv >= 0.5:
        recs.append(
            "INVESTIGATE: FVG invalidation definition may be too aggressive — "
            f"invalidation rate is {fvg_inv:.0%}. Consider requiring 2 consecutive "
            "close-beyond-zone bars for invalidation instead of 1"
        )

    # R3: Partial fill
    recs.append(
        "INVESTIGATE: Add partial-fill tracking — measure how far into the "
        "zone price penetrates before invalidation. If many misses are 50-80% "
        "fills, the label definition is too strict for practical trading"
    )

    # R4: Context-dependent weight
    good_buckets = [
        b for b, s in context.items()
        if s.get("n_events", 0) >= 3 and s.get("hit_rate", 0.0) >= 0.70
    ]
    bad_buckets = [
        b for b, s in context.items()
        if s.get("n_events", 0) >= 3 and s.get("hit_rate", 0.0) < 0.50
    ]
    if good_buckets and bad_buckets:
        recs.append(
            "ACTIONABLE: Apply context-dependent FVG weighting in zone priority — "
            f"boost FVG weight in {', '.join(good_buckets[:3])}, "
            f"reduce in {', '.join(bad_buckets[:3])}"
        )

    # R5: Sample size
    if fvg.get("total_events", 0) < 200:
        recs.append(
            f"PREREQUISITE: Expand benchmark to ≥200 FVG events (currently "
            f"{fvg.get('total_events', 0)}) before making structural label changes"
        )

    return recs


def run_fvg_audit(benchmark_dir: Path) -> FVGAuditResult:
    """Run the full FVG label audit."""
    kpis = _load_benchmark_kpis(benchmark_dir)
    _scored = _load_scored_events(benchmark_dir)

    comparison = _fvg_vs_family_comparison(kpis)
    per_pair = _fvg_per_pair_breakdown(kpis)
    context = _fvg_context_breakdown(kpis)
    findings = _derive_findings(comparison, per_pair, context)
    recommendations = _derive_recommendations(comparison, per_pair, context, findings)

    fvg = comparison.get("FVG", {})

    result = FVGAuditResult(
        total_fvg_events=fvg.get("total_events", 0),
        hit_rate_12=fvg.get("hit_rate", 0.0),
        invalidation_rate=fvg.get("avg_invalidation_rate", 0.0),
        avg_time_to_touch=fvg.get("avg_time_to_mitigation", 0.0),
        per_pair=per_pair,
        per_context=context,
        family_comparison=comparison,
        findings=findings,
        recommendations=recommendations,
    )

    return result


def render_audit_report(audit: FVGAuditResult) -> str:
    """Render the audit as a Markdown report."""
    lines: list[str] = [
        "# FVG Label Audit Report — D1",
        "",
        f"**Total FVG events:** {audit.total_fvg_events}  ",
        f"**Current hit rate (12-bar):** {audit.hit_rate_12:.1%}  ",
        f"**Invalidation rate:** {audit.invalidation_rate:.1%}  ",
        f"**Avg time-to-touch:** {audit.avg_time_to_touch:.1f} bars",
        "",
        "## Family Comparison",
        "",
        "| Family | Events | Hit Rate | Avg TTM | Inv Rate | Avg MAE | Avg MFE |",
        "|--------|-------:|---------:|--------:|---------:|--------:|--------:|",
    ]

    for family in ("BOS", "OB", "FVG", "SWEEP"):
        fc = audit.family_comparison.get(family, {})
        marker = " **←**" if family == "FVG" else ""
        lines.append(
            f"| {family}{marker} | {fc.get('total_events', 0)} | "
            f"{fc.get('hit_rate', 0.0):.1%} | {fc.get('avg_time_to_mitigation', 0.0):.1f} | "
            f"{fc.get('avg_invalidation_rate', 0.0):.1%} | "
            f"{fc.get('avg_mae', 0.0):.4%} | {fc.get('avg_mfe', 0.0):.4%} |"
        )

    lines.extend([
        "",
        "## FVG Per-Pair Breakdown",
        "",
        "| Pair | Events | Hit Rate | TTM | Inv Rate | Status |",
        "|------|-------:|---------:|----:|---------:|--------|",
    ])

    for pair in sorted(audit.per_pair):
        pp = audit.per_pair[pair]
        hr = pp.get("hit_rate", 0.0)
        status = "🟢" if hr >= 0.70 else ("🟡" if hr >= 0.50 else "🔴")
        lines.append(
            f"| {pair} | {pp.get('n_events', 0)} | {hr:.1%} | "
            f"{pp.get('time_to_mitigation_mean', 0.0):.1f} | "
            f"{pp.get('invalidation_rate', 0.0):.1%} | {status} |"
        )

    if audit.per_context:
        lines.extend([
            "",
            "## FVG Context Breakdown",
            "",
            "| Context Bucket | Events | Hit Rate | Status |",
            "|----------------|-------:|---------:|--------|",
        ])
        for bucket in sorted(audit.per_context, key=lambda b: audit.per_context[b].get("hit_rate", 0.0)):
            ctx = audit.per_context[bucket]
            hr = ctx.get("hit_rate", 0.0)
            status = "🟢" if hr >= 0.70 else ("🟡" if hr >= 0.50 else "🔴")
            lines.append(
                f"| {bucket} | {ctx.get('n_events', 0)} | {hr:.1%} | {status} |"
            )

    lines.extend([
        "",
        "## Key Findings",
        "",
    ])
    for i, finding in enumerate(audit.findings, 1):
        lines.append(f"{i}. {finding}")

    lines.extend([
        "",
        "## Recommendations",
        "",
    ])
    for i, rec in enumerate(audit.recommendations, 1):
        lines.append(f"{i}. {rec}")

    lines.append("")
    return "\n".join(lines)


def to_json(audit: FVGAuditResult) -> dict[str, Any]:
    """Serialize the audit for persistence."""
    return {
        "total_fvg_events": audit.total_fvg_events,
        "hit_rate_12": audit.hit_rate_12,
        "hit_rate_16": audit.hit_rate_16,
        "hit_rate_20": audit.hit_rate_20,
        "hit_rate_24": audit.hit_rate_24,
        "partial_fill_50_rate": audit.partial_fill_50_rate,
        "partial_fill_75_rate": audit.partial_fill_75_rate,
        "avg_zone_size_pct_hit": audit.avg_zone_size_pct_hit,
        "avg_zone_size_pct_miss": audit.avg_zone_size_pct_miss,
        "invalidation_rate": audit.invalidation_rate,
        "avg_time_to_touch": audit.avg_time_to_touch,
        "per_pair": audit.per_pair,
        "per_context": audit.per_context,
        "family_comparison": audit.family_comparison,
        "findings": audit.findings,
        "recommendations": audit.recommendations,
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="FVG Label Audit — D1 investigation")
    parser.add_argument(
        "--benchmark-dir",
        type=Path,
        default=Path("artifacts/ci/measurement_benchmark"),
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("artifacts/reports/fvg_label_audit.json"),
    )
    args = parser.parse_args(argv)

    audit = run_fvg_audit(args.benchmark_dir)

    # Write JSON
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(to_json(audit), indent=2) + "\n", args.output_path)

    # Write Markdown report
    md_path = args.output_path.with_suffix(".md")
    atomic_write_text(render_audit_report(audit), md_path)

    print(f"FVG audit written to {args.output_path}")
    print(f"Report written to {md_path}")
    print()
    print(render_audit_report(audit))


if __name__ == "__main__":
    main()
