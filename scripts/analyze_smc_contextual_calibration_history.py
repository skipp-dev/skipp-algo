from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from smc_integration.release_policy import (
    ContextualCalibrationPromotionPolicy,
    ContextualCalibrationRecommendationPolicy,
    assess_contextual_calibration_promotion,
    get_contextual_calibration_promotion_policy,
    get_contextual_calibration_recommendation_policy,
    recommend_contextual_calibration,
    serialize_contextual_calibration_promotion_policy,
    serialize_contextual_calibration_recommendation_policy,
)


_KNOWN_DIMENSIONS: tuple[str, ...] = ("session", "htf_bias", "vol_regime")


def _iso_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _load_json_dict(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "artifact root must be a JSON object"
    return payload, None


def _render(payload: dict[str, Any], output: str) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if str(output).strip() == "-":
        print(rendered)
        return

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_csv(path: Path, *, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze contextual calibration recommendation and promotion history from a gate evidence summary.",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a gate evidence summary JSON file produced by collect_smc_gate_evidence.py.",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Where to write the analysis JSON. Use '-' for stdout.",
    )
    parser.add_argument(
        "--markdown-output",
        default="",
        help="Optional output path for a compact Markdown summary.",
    )
    parser.add_argument(
        "--pair-summary-csv",
        default="",
        help="Optional output path for a flat pair-summary CSV.",
    )
    return parser


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {
        key: int(value)
        for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    }


def _counter_mode(counter: Counter[str]) -> tuple[str | None, int]:
    if not counter:
        return None, 0
    dimension, count = min(
        ((key, int(value)) for key, value in counter.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return dimension, count


def _sorted_dimension_names(names: set[str]) -> list[str]:
    known = [name for name in _KNOWN_DIMENSIONS if name in names]
    unknown = sorted(name for name in names if name not in _KNOWN_DIMENSIONS)
    return [*known, *unknown]


def _sort_history_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(row.get("checked_at") or 0.0),
            str(row.get("pair", "")),
        ),
        reverse=True,
    )


def _format_ratio(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{numeric * 100.0:.1f}%"


def _markdown_counter_table(
    title: str,
    *,
    counts: dict[str, int],
    value_label: str,
) -> list[str]:
    lines = [f"## {title}", ""]
    if not counts:
        lines.extend([f"No {value_label.lower()} recorded.", ""])
        return lines

    lines.extend([
        f"| Value | {value_label} |",
        "| --- | ---: |",
    ])
    for key, value in counts.items():
        lines.append(f"| {key} | {value} |")
    lines.append("")
    return lines


def _render_markdown_summary(analysis: dict[str, Any]) -> str:
    dimensions = [str(item) for item in analysis.get("dimensions_observed", []) if str(item).strip()]
    lines = [
        "# Contextual Calibration History Analysis",
        "",
        f"- Generated at: {analysis.get('generated_at_iso') or 'n/a'}",
        f"- Source: {analysis.get('source_path') or 'n/a'}",
        f"- Source generated at: {analysis.get('source_generated_at_iso') or 'n/a'}",
        "",
        "## Headline",
        "",
        f"- Pairs total: {int(analysis.get('pairs_total', 0) or 0)}",
        f"- Pairs with latest recommendation: {int(analysis.get('pairs_with_latest_recommendation', 0) or 0)}",
        f"- Pairs with latest promotion-ready: {int(analysis.get('pairs_with_latest_promotion_ready', 0) or 0)}",
        f"- History runs total: {int(analysis.get('history_runs_total', 0) or 0)}",
        f"- Recommendation run rate: {_format_ratio(analysis.get('recommendation_run_rate'))}",
        f"- Promotion-ready run rate: {_format_ratio(analysis.get('promotion_ready_run_rate'))}",
        f"- Promotion-ready share of recommendations: {_format_ratio(analysis.get('promotion_ready_share_of_recommendations'))}",
        "",
        "## Dimension Distribution",
        "",
    ]
    if dimensions:
        lines.extend([
            "| Dimension | Recommendation runs | Promotion-ready runs | Latest recommendations | Latest promotion-ready |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        recommendation_counts = dict(analysis.get("recommendation_counts", {}))
        promotion_ready_counts = dict(analysis.get("promotion_ready_counts", {}))
        latest_recommendation_counts = dict(analysis.get("latest_recommendation_counts", {}))
        latest_promotion_ready_counts = dict(analysis.get("latest_promotion_ready_counts", {}))
        for dimension in dimensions:
            lines.append(
                "| "
                f"{dimension} | {int(recommendation_counts.get(dimension, 0) or 0)} | "
                f"{int(promotion_ready_counts.get(dimension, 0) or 0)} | "
                f"{int(latest_recommendation_counts.get(dimension, 0) or 0)} | "
                f"{int(latest_promotion_ready_counts.get(dimension, 0) or 0)} |"
            )
        lines.append("")
    else:
        lines.extend(["No contextual recommendation dimensions observed.", ""])

    lines.extend(
        _markdown_counter_table(
            "Recommendation Basis",
            counts=dict(analysis.get("basis_counts", {})),
            value_label="Runs",
        )
    )
    lines.extend(
        _markdown_counter_table(
            "Promotion Blockers",
            counts=dict(analysis.get("promotion_reason_counts", {})),
            value_label="Runs",
        )
    )

    flagged_pairs = {
        *[str(item) for item in analysis.get("pairs_with_recommendation_switches", [])],
        *[str(item) for item in analysis.get("pairs_latest_not_modal", [])],
        *[str(item) for item in analysis.get("pairs_latest_not_promotion_ready", [])],
    }
    lines.extend([
        "## Review Pairs",
        "",
        f"- Recommendation switches: {len(analysis.get('pairs_with_recommendation_switches', []))}",
        f"- Latest recommendation not modal: {len(analysis.get('pairs_latest_not_modal', []))}",
        f"- Latest recommendation not promotion-ready: {len(analysis.get('pairs_latest_not_promotion_ready', []))}",
        "",
    ])
    if flagged_pairs:
        lines.extend([
            "| Pair | Latest recommendation | Modal recommendation | Promotion-ready | Latest run ratio | Reasons |",
            "| --- | --- | --- | --- | ---: | --- |",
        ])
        pair_summaries = {
            str(row.get("pair")): row
            for row in analysis.get("pair_summaries", [])
            if isinstance(row, dict)
        }
        for pair in sorted(flagged_pairs):
            row = pair_summaries.get(pair, {})
            reasons = "; ".join(str(item) for item in row.get("latest_promotion_reasons", []) if str(item).strip()) or "-"
            lines.append(
                "| "
                f"{pair} | {row.get('latest_recommended_dimension') or '-'} | {row.get('modal_recommended_dimension') or '-'} | "
                f"{'yes' if row.get('latest_promotion_ready') else 'no'} | {_format_ratio(row.get('latest_recommended_run_ratio'))} | {reasons} |"
            )
        lines.append("")
    else:
        lines.extend(["No flagged pairs in the current analysis window.", ""])

    lines.extend([
        "## Files",
        "",
        "- JSON output: full analysis payload for machine-readable consumption.",
        "- Pair CSV: flat per-pair summary for spreadsheet filtering and sorting.",
        "- This Markdown: compact operator overview for quick review.",
    ])
    return "\n".join(lines)


def _build_pair_summary_csv(analysis: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    dimensions = _sorted_dimension_names(
        set(_KNOWN_DIMENSIONS)
        | {str(item) for item in analysis.get("dimensions_observed", []) if str(item).strip()}
    )
    fieldnames = [
        "pair",
        "symbol",
        "timeframe",
        "history_runs",
        "recommendation_runs",
        "promotion_ready_runs",
        "latest_recommended_dimension",
        "latest_recommendation_basis",
        "latest_metric_consensus",
        "latest_promotion_ready",
        "latest_recommended_run_ratio",
        "modal_recommended_dimension",
        "modal_recommendation_share",
        "metric_consensus_rate",
    ]
    for dimension in dimensions:
        fieldnames.append(f"recommendation_count_{dimension}")
    for dimension in dimensions:
        fieldnames.append(f"promotion_ready_count_{dimension}")
    fieldnames.extend([
        "basis_counts_json",
        "promotion_reason_counts_json",
        "latest_promotion_reasons_json",
    ])

    rows: list[dict[str, Any]] = []
    for pair_summary in analysis.get("pair_summaries", []):
        if not isinstance(pair_summary, dict):
            continue
        row = {
            "pair": pair_summary.get("pair"),
            "symbol": pair_summary.get("symbol"),
            "timeframe": pair_summary.get("timeframe"),
            "history_runs": pair_summary.get("history_runs"),
            "recommendation_runs": pair_summary.get("recommendation_runs"),
            "promotion_ready_runs": pair_summary.get("promotion_ready_runs"),
            "latest_recommended_dimension": pair_summary.get("latest_recommended_dimension"),
            "latest_recommendation_basis": pair_summary.get("latest_recommendation_basis"),
            "latest_metric_consensus": pair_summary.get("latest_metric_consensus"),
            "latest_promotion_ready": pair_summary.get("latest_promotion_ready"),
            "latest_recommended_run_ratio": pair_summary.get("latest_recommended_run_ratio"),
            "modal_recommended_dimension": pair_summary.get("modal_recommended_dimension"),
            "modal_recommendation_share": pair_summary.get("modal_recommendation_share"),
            "metric_consensus_rate": pair_summary.get("metric_consensus_rate"),
            "basis_counts_json": json.dumps(pair_summary.get("basis_counts", {}), sort_keys=True),
            "promotion_reason_counts_json": json.dumps(pair_summary.get("promotion_reason_counts", {}), sort_keys=True),
            "latest_promotion_reasons_json": json.dumps(pair_summary.get("latest_promotion_reasons", [])),
        }
        recommendation_counts = dict(pair_summary.get("recommendation_counts", {}))
        promotion_ready_counts = dict(pair_summary.get("promotion_ready_counts", {}))
        for dimension in dimensions:
            row[f"recommendation_count_{dimension}"] = int(recommendation_counts.get(dimension, 0) or 0)
        for dimension in dimensions:
            row[f"promotion_ready_count_{dimension}"] = int(promotion_ready_counts.get(dimension, 0) or 0)
        rows.append(row)
    return fieldnames, rows


def _recommendation_for_row(
    row: dict[str, Any],
    *,
    policy: Any,
) -> dict[str, Any]:
    existing = row.get("contextual_calibration_recommendation")
    if isinstance(existing, dict) and ("available" in existing or "recommended_dimension" in existing):
        return existing
    return recommend_contextual_calibration(row, policy=policy)


def _hydrate_recommendation_policy(raw: Any) -> ContextualCalibrationRecommendationPolicy:
    default_policy = get_contextual_calibration_recommendation_policy()
    if not isinstance(raw, dict):
        return default_policy

    values = {
        field.name: raw.get(field.name, getattr(default_policy, field.name))
        for field in fields(ContextualCalibrationRecommendationPolicy)
    }
    return ContextualCalibrationRecommendationPolicy(**values)


def _hydrate_promotion_policy(raw: Any) -> ContextualCalibrationPromotionPolicy:
    default_policy = get_contextual_calibration_promotion_policy()
    if not isinstance(raw, dict):
        return default_policy

    values = {
        field.name: raw.get(field.name, getattr(default_policy, field.name))
        for field in fields(ContextualCalibrationPromotionPolicy)
    }
    return ContextualCalibrationPromotionPolicy(**values)


def analyze_contextual_calibration_history(
    evidence_summary: dict[str, Any],
    *,
    source_path: str | None = None,
    now_ts: float | None = None,
) -> dict[str, Any]:
    measurement_history = evidence_summary.get("measurement_history")
    if not isinstance(measurement_history, dict):
        raise ValueError("evidence summary missing measurement_history")

    history_by_pair = measurement_history.get("history_by_pair")
    if not isinstance(history_by_pair, dict):
        raise ValueError("evidence summary missing measurement_history.history_by_pair")

    generated_at = float(now_ts if now_ts is not None else time.time())
    recommendation_policy = _hydrate_recommendation_policy(
        measurement_history.get("contextual_recommendation_policy")
    )
    promotion_policy = _hydrate_promotion_policy(
        measurement_history.get("contextual_promotion_policy")
    )

    recommendation_counts: Counter[str] = Counter()
    promotion_ready_counts: Counter[str] = Counter()
    latest_recommendation_counts: Counter[str] = Counter()
    latest_promotion_ready_counts: Counter[str] = Counter()
    basis_counts: Counter[str] = Counter()
    promotion_reason_counts: Counter[str] = Counter()
    metric_consensus_counts: Counter[str] = Counter()
    pair_summaries: list[dict[str, Any]] = []
    pairs_with_recommendation_switches: list[str] = []
    pairs_latest_not_promotion_ready: list[str] = []
    pairs_latest_not_modal: list[str] = []

    history_runs_total = 0
    recommendation_runs_total = 0
    promotion_ready_runs_total = 0

    for pair, raw_rows in sorted(history_by_pair.items()):
        if not isinstance(raw_rows, list):
            continue
        rows = _sort_history_rows([row for row in raw_rows if isinstance(row, dict)])
        if not rows:
            continue

        pair_recommendation_counts: Counter[str] = Counter()
        pair_promotion_ready_counts: Counter[str] = Counter()
        pair_basis_counts: Counter[str] = Counter()
        pair_promotion_reason_counts: Counter[str] = Counter()
        pair_recommendation_runs = 0
        pair_promotion_ready_runs = 0
        pair_metric_consensus_runs = 0

        latest_recommendation: dict[str, Any] | None = None
        latest_promotion: dict[str, Any] | None = None

        for idx, row in enumerate(rows):
            row.setdefault("pair", pair)
            history_runs_total += 1
            recommendation = _recommendation_for_row(row, policy=recommendation_policy)
            promotion = assess_contextual_calibration_promotion(
                row,
                rows[idx + 1 :],
                recommendation_policy=recommendation_policy,
                promotion_policy=promotion_policy,
            )

            recommended_dimension = str(recommendation.get("recommended_dimension", "")).strip()
            if recommendation.get("available") and recommended_dimension:
                recommendation_runs_total += 1
                pair_recommendation_runs += 1
                recommendation_counts[recommended_dimension] += 1
                pair_recommendation_counts[recommended_dimension] += 1

                basis = str(recommendation.get("basis", "")).strip()
                if basis:
                    basis_counts[basis] += 1
                    pair_basis_counts[basis] += 1

                metric_consensus = bool(recommendation.get("metric_consensus"))
                metric_consensus_counts["true" if metric_consensus else "false"] += 1
                if metric_consensus:
                    pair_metric_consensus_runs += 1

            promoted_dimension = str(promotion.get("recommended_dimension", "")).strip()
            if promotion.get("promotion_ready") and promoted_dimension:
                promotion_ready_runs_total += 1
                pair_promotion_ready_runs += 1
                promotion_ready_counts[promoted_dimension] += 1
                pair_promotion_ready_counts[promoted_dimension] += 1

            for reason in promotion.get("reasons", []):
                reason_key = str(reason).strip()
                if not reason_key:
                    continue
                promotion_reason_counts[reason_key] += 1
                pair_promotion_reason_counts[reason_key] += 1

            if idx == 0:
                latest_recommendation = recommendation
                latest_promotion = promotion
                if recommendation.get("available") and recommended_dimension:
                    latest_recommendation_counts[recommended_dimension] += 1
                if promotion.get("promotion_ready") and promoted_dimension:
                    latest_promotion_ready_counts[promoted_dimension] += 1

        modal_dimension, modal_count = _counter_mode(pair_recommendation_counts)
        latest_dimension = str((latest_recommendation or {}).get("recommended_dimension", "")).strip() or None
        latest_promotion_ready = bool((latest_promotion or {}).get("promotion_ready"))

        if len(pair_recommendation_counts) > 1:
            pairs_with_recommendation_switches.append(pair)
        if latest_dimension and modal_dimension and latest_dimension != modal_dimension:
            pairs_latest_not_modal.append(pair)
        if latest_dimension and not latest_promotion_ready:
            pairs_latest_not_promotion_ready.append(pair)

        pair_summaries.append(
            {
                "pair": pair,
                "symbol": rows[0].get("symbol"),
                "timeframe": rows[0].get("timeframe"),
                "history_runs": len(rows),
                "recommendation_runs": pair_recommendation_runs,
                "promotion_ready_runs": pair_promotion_ready_runs,
                "latest_checked_at": rows[0].get("checked_at"),
                "latest_checked_at_iso": rows[0].get("checked_at_iso") or _iso_utc(rows[0].get("checked_at")),
                "latest_recommended_dimension": latest_dimension,
                "latest_recommendation_basis": (latest_recommendation or {}).get("basis"),
                "latest_metric_consensus": bool((latest_recommendation or {}).get("metric_consensus")),
                "latest_promotion_ready": latest_promotion_ready,
                "latest_recommended_run_ratio": (latest_promotion or {}).get("recommended_run_ratio"),
                "latest_promotion_reasons": list((latest_promotion or {}).get("reasons", [])),
                "modal_recommended_dimension": modal_dimension,
                "modal_recommendation_share": round(modal_count / float(pair_recommendation_runs), 6)
                if pair_recommendation_runs > 0 and modal_dimension is not None
                else None,
                "recommendation_counts": _counter_dict(pair_recommendation_counts),
                "promotion_ready_counts": _counter_dict(pair_promotion_ready_counts),
                "basis_counts": _counter_dict(pair_basis_counts),
                "promotion_reason_counts": _counter_dict(pair_promotion_reason_counts),
                "metric_consensus_rate": round(pair_metric_consensus_runs / float(pair_recommendation_runs), 6)
                if pair_recommendation_runs > 0
                else None,
            }
        )

    pairs_total = len(pair_summaries)
    pairs_with_latest_recommendation = sum(1 for row in pair_summaries if row.get("latest_recommended_dimension"))
    pairs_with_latest_promotion_ready = sum(1 for row in pair_summaries if row.get("latest_promotion_ready"))
    dimensions_observed = _sorted_dimension_names(
        set(recommendation_counts)
        | set(promotion_ready_counts)
        | set(latest_recommendation_counts)
        | set(latest_promotion_ready_counts)
    )

    return {
        "generated_at": generated_at,
        "generated_at_iso": _iso_utc(generated_at),
        "report_kind": "contextual_calibration_history_analysis",
        "source_path": source_path,
        "source_report_kind": evidence_summary.get("report_kind"),
        "source_generated_at": evidence_summary.get("generated_at"),
        "source_generated_at_iso": evidence_summary.get("generated_at_iso") or _iso_utc(evidence_summary.get("generated_at")),
        "contextual_recommendation_policy": serialize_contextual_calibration_recommendation_policy(recommendation_policy),
        "contextual_promotion_policy": serialize_contextual_calibration_promotion_policy(promotion_policy),
        "pairs_total": pairs_total,
        "pairs_with_latest_recommendation": pairs_with_latest_recommendation,
        "pairs_with_latest_promotion_ready": pairs_with_latest_promotion_ready,
        "dimensions_observed": dimensions_observed,
        "history_runs_total": history_runs_total,
        "recommendation_runs_total": recommendation_runs_total,
        "promotion_ready_runs_total": promotion_ready_runs_total,
        "recommendation_run_rate": round(recommendation_runs_total / float(history_runs_total), 6)
        if history_runs_total > 0
        else None,
        "promotion_ready_run_rate": round(promotion_ready_runs_total / float(history_runs_total), 6)
        if history_runs_total > 0
        else None,
        "promotion_ready_share_of_recommendations": round(
            promotion_ready_runs_total / float(recommendation_runs_total),
            6,
        )
        if recommendation_runs_total > 0
        else None,
        "recommendation_counts": _counter_dict(recommendation_counts),
        "promotion_ready_counts": _counter_dict(promotion_ready_counts),
        "latest_recommendation_counts": _counter_dict(latest_recommendation_counts),
        "latest_promotion_ready_counts": _counter_dict(latest_promotion_ready_counts),
        "basis_counts": _counter_dict(basis_counts),
        "promotion_reason_counts": _counter_dict(promotion_reason_counts),
        "metric_consensus_counts": _counter_dict(metric_consensus_counts),
        "pairs_with_recommendation_switches": sorted(pairs_with_recommendation_switches),
        "pairs_latest_not_modal": sorted(pairs_latest_not_modal),
        "pairs_latest_not_promotion_ready": sorted(pairs_latest_not_promotion_ready),
        "pair_summaries": pair_summaries,
    }


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    payload, error = _load_json_dict(input_path)
    if error is not None or payload is None:
        print(f"failed to load evidence summary: {error}", file=sys.stderr)
        return 1

    try:
        analysis = analyze_contextual_calibration_history(payload, source_path=str(input_path))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _render(analysis, str(args.output))
    markdown_output = str(getattr(args, "markdown_output", "") or "").strip()
    if markdown_output:
        _write_text(Path(markdown_output), _render_markdown_summary(analysis))
    pair_summary_csv = str(getattr(args, "pair_summary_csv", "") or "").strip()
    if pair_summary_csv:
        fieldnames, rows = _build_pair_summary_csv(analysis)
        _write_csv(Path(pair_summary_csv), fieldnames=fieldnames, rows=rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())