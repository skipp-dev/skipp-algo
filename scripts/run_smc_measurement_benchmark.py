from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
import sys
from typing import Any

import plotly.graph_objects as go

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from smc_core.benchmark import BenchmarkResult, build_benchmark, export_benchmark_artifacts
from smc_core.ensemble_quality import EnsembleQualityResult, export_ensemble_quality_artifact
from smc_core.scoring import (
    ScoredEvent,
    export_scoring_artifact,
    score_events,
    serialize_calibration_summary,
    serialize_contextual_calibration,
    serialize_stratified_calibration,
    summarize_contextual_calibration,
    summarize_stratified_calibration,
)
from smc_core.schema_version import SCHEMA_VERSION
from smc_integration.measurement_evidence import build_measurement_evidence
from smc_integration.release_policy import (
    RELEASE_REFERENCE_SYMBOLS,
    RELEASE_REFERENCE_TIMEFRAMES,
    csv_from_values,
    parse_csv,
)


def _path_token(raw: str) -> str:
    return str(raw).strip().replace("/", "_").replace(" ", "_")


def _pair_output_dir(output_root: Path, *, symbol: str, timeframe: str) -> Path:
    return output_root / _path_token(symbol) / _path_token(timeframe)


def _summarize_stratification(benchmark_result: BenchmarkResult) -> dict[str, Any]:
    bucket_event_counts: dict[str, int] = {}
    dimensions_present: set[str] = set()
    populated_bucket_count = 0

    for bucket_key, bucket_kpis in sorted(benchmark_result.stratified.items()):
        dimension = str(bucket_key).split(":", 1)[0]
        dimensions_present.add(dimension)
        event_count = sum(int(kpi.n_events or 0) for kpi in bucket_kpis)
        bucket_event_counts[str(bucket_key)] = event_count
        if event_count > 0:
            populated_bucket_count += 1

    return {
        "bucket_count": len(bucket_event_counts),
        "populated_bucket_count": populated_bucket_count,
        "dimensions_present": sorted(dimensions_present),
        "bucket_event_counts": bucket_event_counts,
    }


def _benchmark_event_counts(benchmark_result: BenchmarkResult) -> dict[str, int]:
    return {
        kpi.family: int(kpi.n_events or 0)
        for kpi in benchmark_result.kpis
    }


def _serialize_scoring_family_metrics(scoring_result: Any) -> dict[str, dict[str, Any]]:
    raw_metrics = getattr(scoring_result, "family_metrics", None)
    if not isinstance(raw_metrics, dict):
        return {}

    metrics: dict[str, dict[str, Any]] = {}
    for family, item in sorted(raw_metrics.items()):
        metrics[str(family)] = {
            "n_events": int(getattr(item, "n_events", 0) or 0),
            "brier_score": float(getattr(item, "brier_score", float("nan"))),
            "log_score": float(getattr(item, "log_score", float("nan"))),
            "hit_rate": float(getattr(item, "hit_rate", float("nan"))),
        }
    return metrics


def _write_csv(path: Path, *, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _kpi_rows(benchmark_result: BenchmarkResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kpi in benchmark_result.kpis:
        rows.append(
            {
                "bucket": "aggregate",
                "family": kpi.family,
                "hit_rate": kpi.hit_rate,
                "time_to_mitigation_mean": kpi.time_to_mitigation_mean,
                "invalidation_rate": kpi.invalidation_rate,
                "mae": kpi.mae,
                "mfe": kpi.mfe,
                "n_events": kpi.n_events,
            }
        )
    for bucket, bucket_kpis in sorted(benchmark_result.stratified.items()):
        for kpi in bucket_kpis:
            rows.append(
                {
                    "bucket": bucket,
                    "family": kpi.family,
                    "hit_rate": kpi.hit_rate,
                    "time_to_mitigation_mean": kpi.time_to_mitigation_mean,
                    "invalidation_rate": kpi.invalidation_rate,
                    "mae": kpi.mae,
                    "mfe": kpi.mfe,
                    "n_events": kpi.n_events,
                }
            )
    return rows


def _reliability_rows(scoring_result: Any, *, bin_count: int = 10) -> list[dict[str, Any]]:
    calibration = getattr(scoring_result, "calibration", None)
    calibration_bins = getattr(calibration, "bins", None) if calibration is not None else None
    if calibration_bins:
        return [
            {
                "bin_index": int(item.bin_index),
                "bin_label": f"{item.lower_bound:.1f}-{item.upper_bound:.1f}",
                "predicted_mean": float(item.predicted_mean),
                "observed_rate": float(item.observed_rate),
                "calibrated_mean": float(item.calibrated_mean),
                "n_events": int(item.n_events),
            }
            for item in calibration_bins
        ]

    events = list(getattr(scoring_result, "events", []) or [])
    if not events:
        return []

    buckets: dict[int, list[ScoredEvent]] = {}
    for event in events:
        clipped = min(max(float(event.predicted_prob), 0.0), 1.0)
        bucket_idx = min(bin_count - 1, int(math.floor(clipped * bin_count)))
        buckets.setdefault(bucket_idx, []).append(event)

    rows: list[dict[str, Any]] = []
    for bucket_idx in sorted(buckets):
        bucket_events = buckets[bucket_idx]
        if not bucket_events:
            continue
        n_events = len(bucket_events)
        predicted_mean = sum(float(event.predicted_prob) for event in bucket_events) / n_events
        observed_rate = sum(1.0 if event.outcome else 0.0 for event in bucket_events) / n_events
        rows.append(
            {
                "bin_index": bucket_idx,
                "bin_label": f"{bucket_idx / bin_count:.1f}-{(bucket_idx + 1) / bin_count:.1f}",
                "predicted_mean": round(predicted_mean, 6),
                "observed_rate": round(observed_rate, 6),
                "calibrated_mean": round(predicted_mean, 6),
                "n_events": n_events,
            }
        )
    return rows


def _write_reliability_plot(scoring_result: Any, output_path: Path) -> None:
    rows = _reliability_rows(scoring_result)
    calibration = serialize_calibration_summary(scoring_result.calibration)
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[0.0, 1.0],
            y=[0.0, 1.0],
            mode="lines",
            name="ideal_calibration",
            line={"dash": "dash", "color": "gray"},
        )
    )

    if rows:
        figure.add_trace(
            go.Scatter(
                x=[row["predicted_mean"] for row in rows],
                y=[row["observed_rate"] for row in rows],
                mode="lines+markers",
                name="raw",
                text=[f"bin={row['bin_label']}<br>n={row['n_events']}" for row in rows],
            )
        )
        if any(abs(float(row["calibrated_mean"]) - float(row["predicted_mean"])) > 1e-9 for row in rows):
            figure.add_trace(
                go.Scatter(
                    x=[row["calibrated_mean"] for row in rows],
                    y=[row["observed_rate"] for row in rows],
                    mode="lines+markers",
                    name="calibrated",
                    text=[f"bin={row['bin_label']}<br>n={row['n_events']}" for row in rows],
                )
            )
    else:
        figure.add_annotation(text="No scored events available", x=0.5, y=0.5, showarrow=False)

    calibration_method = str(calibration.get("method", "identity"))
    raw_ece = calibration.get("raw_ece")
    calibrated_ece = calibration.get("calibrated_ece")
    title = f"Reliability / Calibration ({calibration_method})"
    if raw_ece is not None and calibrated_ece is not None:
        title = f"{title} | ECE {raw_ece:.4f} -> {calibrated_ece:.4f}"

    figure.update_layout(
        title=title,
        xaxis_title="Predicted probability",
        yaxis_title="Observed hit rate",
        template="plotly_white",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(str(output_path), include_plotlyjs="cdn")


def _write_stratification_plot(benchmark_result: BenchmarkResult, output_path: Path) -> None:
    figure = go.Figure()
    bucket_keys = sorted(benchmark_result.stratified)
    if bucket_keys:
        families = sorted({kpi.family for rows in benchmark_result.stratified.values() for kpi in rows})
        for family in families:
            figure.add_trace(
                go.Bar(
                    x=bucket_keys,
                    y=[
                        sum(int(kpi.n_events or 0) for kpi in benchmark_result.stratified[bucket_key] if kpi.family == family)
                        for bucket_key in bucket_keys
                    ],
                    name=family,
                )
            )
    else:
        figure.add_annotation(text="No stratified benchmark buckets available", x=0.5, y=0.5, showarrow=False)

    figure.update_layout(
        title="Stratification Coverage",
        xaxis_title="Stratification bucket",
        yaxis_title="Event count",
        barmode="group",
        template="plotly_white",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(str(output_path), include_plotlyjs="cdn")


def _write_pair_summary_csv(path: Path, summary: dict[str, Any]) -> None:
    row = {
        "symbol": summary["symbol"],
        "timeframe": summary["timeframe"],
        "measurement_evidence_present": summary["measurement_evidence_present"],
        "bars_source_mode": summary["bars_source_mode"],
        "n_events": summary["scoring"]["n_events"],
        "brier_score": summary["scoring"]["brier_score"],
        "log_score": summary["scoring"]["log_score"],
        "calibration_method": summary["scoring"]["calibration"]["method"],
        "calibrated_brier_score": summary["scoring"]["calibration"]["calibrated_brier_score"],
        "calibrated_log_score": summary["scoring"]["calibration"]["calibrated_log_score"],
        "raw_ece": summary["scoring"]["calibration"]["raw_ece"],
        "calibrated_ece": summary["scoring"]["calibration"]["calibrated_ece"],
        "contextual_best_brier_dimension": summary["scoring"]["contextual_calibration_summary"]["best_dimension_by_adjusted_brier"],
        "contextual_best_ece_dimension": summary["scoring"]["contextual_calibration_summary"]["best_dimension_by_adjusted_ece"],
        "hit_rate": summary["scoring"]["hit_rate"],
        "families_present": "|".join(summary["scoring"]["families_present"]),
        "stratified_dimensions": "|".join(summary["scoring"]["stratified_calibration_summary"]["dimensions_present"]),
        "contextual_dimensions": "|".join(summary["scoring"]["contextual_calibration_summary"]["dimensions_present"]),
        "populated_bucket_count": summary["stratification_coverage"]["populated_bucket_count"],
        "warning_count": len(summary["warnings"]),
    }
    _write_csv(path, fieldnames=list(row.keys()), rows=[row])


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_pair_summary(
    *,
    symbol: str,
    timeframe: str,
    pair_dir: Path,
    evidence: Any,
    benchmark_result: BenchmarkResult,
    scoring_result: Any,
    artifacts: dict[str, str | None],
) -> dict[str, Any]:
    calibration = serialize_calibration_summary(scoring_result.calibration)
    stratified_calibration = serialize_stratified_calibration(
        getattr(scoring_result, "stratified_calibration", {}) or {}
    )
    stratified_calibration_summary = summarize_stratified_calibration(
        getattr(scoring_result, "stratified_calibration", {}) or {}
    )
    contextual_calibration = serialize_contextual_calibration(
        getattr(scoring_result, "contextual_calibration", {}) or {}
    )
    contextual_calibration_summary = summarize_contextual_calibration(
        getattr(scoring_result, "contextual_calibration", {}) or {}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": float(time.time()),
        "generator": "scripts/run_smc_measurement_benchmark.py",
        "symbol": symbol,
        "timeframe": timeframe,
        "artifact_dir": pair_dir.as_posix(),
        "measurement_evidence_present": bool(evidence.details.get("measurement_evidence_present")),
        "bars_source_mode": evidence.details.get("bars_source_mode"),
        "evaluated_event_counts": dict(evidence.details.get("evaluated_event_counts", {})),
        "benchmark_event_counts": _benchmark_event_counts(benchmark_result),
        "stratification_coverage": _summarize_stratification(benchmark_result),
        "scoring": {
            "n_events": int(getattr(scoring_result, "n_events", 0) or 0),
            "brier_score": float(getattr(scoring_result, "brier_score", float("nan"))),
            "log_score": float(getattr(scoring_result, "log_score", float("nan"))),
            "hit_rate": float(getattr(scoring_result, "hit_rate", float("nan"))),
            "families_present": sorted(_serialize_scoring_family_metrics(scoring_result).keys()),
            "family_metrics": _serialize_scoring_family_metrics(scoring_result),
            "calibration": calibration,
            "stratified_calibration": stratified_calibration,
            "stratified_calibration_summary": stratified_calibration_summary,
            "contextual_calibration": contextual_calibration,
            "contextual_calibration_summary": contextual_calibration_summary,
        },
        "ensemble_quality": dict(evidence.details.get("ensemble_quality", {})),
        "warnings": list(evidence.warnings),
        "artifacts": artifacts,
    }


def run_pair(symbol: str, timeframe: str, *, output_root: Path) -> dict[str, Any]:
    pair_dir = _pair_output_dir(output_root, symbol=symbol, timeframe=timeframe)
    pair_dir.mkdir(parents=True, exist_ok=True)

    evidence = build_measurement_evidence(symbol, timeframe)
    benchmark_result = build_benchmark(
        symbol,
        timeframe,
        events_by_family=evidence.events_by_family,
        stratified_events=evidence.stratified_events,
    )
    export_benchmark_artifacts(benchmark_result, pair_dir)

    scoring_result = score_events(evidence.scored_events)
    scoring_artifact_path = export_scoring_artifact(
        scoring_result,
        symbol=symbol,
        timeframe=timeframe,
        output_dir=pair_dir,
        schema_version=SCHEMA_VERSION,
    )

    ensemble_payload = evidence.details.get("ensemble_quality") if isinstance(evidence.details, dict) else None
    ensemble_artifact_path = None
    if isinstance(ensemble_payload, dict) and ensemble_payload:
        ensemble_artifact_path = export_ensemble_quality_artifact(
            EnsembleQualityResult(**ensemble_payload),
            symbol=symbol,
            timeframe=timeframe,
            output_dir=pair_dir,
            schema_version=SCHEMA_VERSION,
        )

    kpi_csv_path = pair_dir / f"benchmark_{symbol}_{timeframe}_kpis.csv"
    _write_csv(
        kpi_csv_path,
        fieldnames=["bucket", "family", "hit_rate", "time_to_mitigation_mean", "invalidation_rate", "mae", "mfe", "n_events"],
        rows=_kpi_rows(benchmark_result),
    )

    reliability_plot_path = pair_dir / f"reliability_{symbol}_{timeframe}.html"
    _write_reliability_plot(scoring_result, reliability_plot_path)

    stratification_plot_path = pair_dir / f"stratification_{symbol}_{timeframe}.html"
    _write_stratification_plot(benchmark_result, stratification_plot_path)

    artifacts = {
        "benchmark_json": f"benchmark_{symbol}_{timeframe}.json",
        "benchmark_manifest": "manifest.json",
        "benchmark_csv": kpi_csv_path.name,
        "scoring_json": scoring_artifact_path.name,
        "ensemble_quality_json": ensemble_artifact_path.name if ensemble_artifact_path is not None else None,
        "reliability_plot": reliability_plot_path.name,
        "stratification_plot": stratification_plot_path.name,
    }
    pair_summary = _build_pair_summary(
        symbol=symbol,
        timeframe=timeframe,
        pair_dir=pair_dir,
        evidence=evidence,
        benchmark_result=benchmark_result,
        scoring_result=scoring_result,
        artifacts=artifacts,
    )

    summary_json_path = pair_dir / f"measurement_summary_{symbol}_{timeframe}.json"
    _write_json(summary_json_path, pair_summary)
    summary_csv_path = pair_dir / f"measurement_summary_{symbol}_{timeframe}.csv"
    _write_pair_summary_csv(summary_csv_path, pair_summary)

    harness_manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": float(time.time()),
        "generator": "scripts/run_smc_measurement_benchmark.py",
        "symbol": symbol,
        "timeframe": timeframe,
        "inputs": {
            "symbol": symbol,
            "timeframe": timeframe,
        },
        "artifacts": [
            artifacts["benchmark_json"],
            artifacts["benchmark_manifest"],
            artifacts["benchmark_csv"],
            artifacts["scoring_json"],
            *([artifacts["ensemble_quality_json"]] if artifacts["ensemble_quality_json"] else []),
            summary_json_path.name,
            summary_csv_path.name,
            artifacts["reliability_plot"],
            artifacts["stratification_plot"],
        ],
    }
    _write_json(pair_dir / "harness_manifest.json", harness_manifest)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "artifact_dir": pair_dir.relative_to(output_root).as_posix(),
        "summary": pair_summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a persistent SMC measurement benchmark artifact set.")
    parser.add_argument(
        "--symbols",
        default=csv_from_values(RELEASE_REFERENCE_SYMBOLS[:1]),
        help="Comma-separated symbols for the measurement benchmark run.",
    )
    parser.add_argument(
        "--timeframes",
        default=csv_from_values(RELEASE_REFERENCE_TIMEFRAMES[:1]),
        help="Comma-separated timeframes for the measurement benchmark run.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/ci/measurement_benchmark",
        help="Directory where the benchmark harness writes its artifacts.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    symbols = parse_csv(str(args.symbols), normalize_upper=True)
    timeframes = parse_csv(str(args.timeframes), normalize_upper=False)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    pair_runs: list[dict[str, Any]] = []
    for symbol in symbols:
        for timeframe in timeframes:
            pair_runs.append(run_pair(symbol, timeframe, output_root=output_root))

    run_summary_rows = []
    for pair_run in pair_runs:
        summary = pair_run["summary"]
        run_summary_rows.append(
            {
                "symbol": summary["symbol"],
                "timeframe": summary["timeframe"],
                "artifact_dir": pair_run["artifact_dir"],
                "measurement_evidence_present": summary["measurement_evidence_present"],
                "n_events": summary["scoring"]["n_events"],
                "brier_score": summary["scoring"]["brier_score"],
                "log_score": summary["scoring"]["log_score"],
                "calibration_method": summary["scoring"]["calibration"]["method"],
                "calibrated_brier_score": summary["scoring"]["calibration"]["calibrated_brier_score"],
                "calibrated_log_score": summary["scoring"]["calibration"]["calibrated_log_score"],
                "raw_ece": summary["scoring"]["calibration"]["raw_ece"],
                "calibrated_ece": summary["scoring"]["calibration"]["calibrated_ece"],
                "hit_rate": summary["scoring"]["hit_rate"],
                "stratified_dimensions": "|".join(summary["scoring"]["stratified_calibration_summary"]["dimensions_present"]),
                "populated_bucket_count": summary["stratification_coverage"]["populated_bucket_count"],
                "warning_count": len(summary["warnings"]),
            }
        )

    summary_csv_path = output_root / "benchmark_run_summary.csv"
    _write_csv(summary_csv_path, fieldnames=list(run_summary_rows[0].keys()) if run_summary_rows else ["symbol", "timeframe"], rows=run_summary_rows)

    run_manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": float(time.time()),
        "generator": "scripts/run_smc_measurement_benchmark.py",
        "symbols": symbols,
        "timeframes": timeframes,
        "output_dir": output_root.as_posix(),
        "pair_runs": [
            {
                "symbol": pair_run["symbol"],
                "timeframe": pair_run["timeframe"],
                "artifact_dir": pair_run["artifact_dir"],
                "summary_path": f"{pair_run['artifact_dir']}/measurement_summary_{pair_run['symbol']}_{pair_run['timeframe']}.json",
                "harness_manifest_path": f"{pair_run['artifact_dir']}/harness_manifest.json",
            }
            for pair_run in pair_runs
        ],
        "artifacts": [summary_csv_path.name, "benchmark_run_manifest.json"],
    }
    _write_json(output_root / "benchmark_run_manifest.json", run_manifest)
    print(json.dumps(run_manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())