from __future__ import annotations

import argparse
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.verify_smc_micro_publish_contract import verify_publish_contract
from smc_core.benchmark import EventFamily, build_benchmark, export_benchmark_artifacts
from smc_core.scoring import export_scoring_artifact, score_events
from smc_core.schema_version import SCHEMA_VERSION
from smc_integration.measurement_evidence import build_measurement_evidence
from smc_integration.release_policy import (
    RELEASE_REFERENCE_SYMBOLS,
    RELEASE_REFERENCE_TIMEFRAMES,
    RELEASE_STALE_AFTER_SECONDS,
    assess_measurement_shadow_degradations,
    csv_from_values,
    diagnose_gate_failure,
    get_measurement_shadow_thresholds,
    parse_csv,
    resolve_release_policy,
    runtime_metadata,
    serialize_measurement_shadow_thresholds,
)
from smc_integration.provider_health import run_provider_health_check
from smc_integration.service import build_snapshot_bundle_for_symbol_timeframe


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _parse_csv(raw: str) -> list[str]:
    return parse_csv(raw, normalize_upper=False)


def _normalize_symbols(raw: str) -> list[str]:
    return parse_csv(raw, normalize_upper=True)


def _finite_metric(value: Any) -> float | None:
    try:
        metric = float(value)
    except (TypeError, ValueError):
        return None
    return metric if math.isfinite(metric) else None


def _path_token(raw: str) -> str:
    return str(raw).strip().replace("/", "_").replace(" ", "_")


def _resolve_measurement_output_root(*, report_output: str, explicit_root: str | None) -> Path:
    if explicit_root:
        return Path(explicit_root)
    if report_output != "-":
        return Path(report_output).parent / "measurement"
    return Path("artifacts/ci/measurement")


def _measurement_output_dir(output_root: Path, *, symbol: str, timeframe: str) -> Path:
    return output_root / _path_token(symbol) / _path_token(timeframe)


def _path_for_report(path: Path, *, report_output: str) -> str:
    if report_output != "-":
        base = Path(report_output).parent
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _summarize_stratification(benchmark_result: Any) -> dict[str, Any]:
    bucket_event_counts: dict[str, int] = {}
    dimensions_present: set[str] = set()
    populated_bucket_count = 0

    stratified = getattr(benchmark_result, "stratified", {}) or {}
    for bucket_key, bucket_kpis in sorted(stratified.items()):
        dimension = str(bucket_key).split(":", 1)[0]
        dimensions_present.add(dimension)
        event_count = sum(int(getattr(kpi, "n_events", 0) or 0) for kpi in bucket_kpis)
        bucket_event_counts[str(bucket_key)] = event_count
        if event_count > 0:
            populated_bucket_count += 1

    return {
        "bucket_count": len(bucket_event_counts),
        "populated_bucket_count": populated_bucket_count,
        "dimensions_present": sorted(dimensions_present),
        "bucket_event_counts": bucket_event_counts,
    }


def _load_measurement_history_rows(
    baseline_summary_path: str | None,
    *,
    symbol: str,
    timeframe: str,
) -> tuple[list[dict[str, Any]], str | None]:
    if not baseline_summary_path:
        return [], None

    path = Path(baseline_summary_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], f"measurement baseline summary could not be loaded: {exc}"

    if not isinstance(payload, dict):
        return [], "measurement baseline summary root must be a JSON object"

    measurement_history = payload.get("measurement_history")
    if not isinstance(measurement_history, dict):
        return [], "measurement baseline summary missing measurement_history"

    history_by_pair = measurement_history.get("history_by_pair")
    if not isinstance(history_by_pair, dict):
        return [], "measurement baseline summary missing measurement_history.history_by_pair"

    pair = f"{symbol}/{timeframe}"
    rows = history_by_pair.get(pair, [])
    if not isinstance(rows, list):
        return [], f"measurement baseline history for {pair} must be a list"

    history_rows = [row for row in rows if isinstance(row, dict)]
    return history_rows, None


def _serialize_family_metrics(scoring_result: Any | None) -> dict[str, dict[str, Any]]:
    raw_metrics = getattr(scoring_result, "family_metrics", None)
    if not isinstance(raw_metrics, dict):
        return {}

    serialized: dict[str, dict[str, Any]] = {}
    for family, metrics in raw_metrics.items():
        serialized[str(family)] = {
            "n_events": int(getattr(metrics, "n_events", 0) or 0),
            "brier_score": _finite_metric(getattr(metrics, "brier_score", None)),
            "log_score": _finite_metric(getattr(metrics, "log_score", None)),
            "hit_rate": _finite_metric(getattr(metrics, "hit_rate", None)),
        }
    return serialized


def _write_measurement_manifest(
    *,
    output_dir: Path,
    symbol: str,
    timeframe: str,
    benchmark_artifact_path: Path,
    benchmark_manifest_path: Path,
    benchmark_artifact_present: bool,
    scoring_artifact_path: Path,
    scoring_artifact_present: bool,
    measurement_evidence_present: bool,
    evaluated_event_counts: dict[str, Any],
    bars_source_mode: str | None,
    warnings: list[str],
    benchmark_event_counts: dict[str, int],
    stratification_coverage: dict[str, Any],
    scoring_result: Any | None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "measurement_manifest.json"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": float(time.time()),
        "symbol": symbol,
        "timeframe": timeframe,
        "measurement_evidence_present": bool(measurement_evidence_present),
        "evaluated_event_counts": dict(evaluated_event_counts),
        "bars_source_mode": bars_source_mode,
        "artifacts": {
            "benchmark": {
                "present": bool(benchmark_artifact_present),
                "artifact_path": benchmark_artifact_path.name,
                "manifest_path": benchmark_manifest_path.name,
            },
            "scoring": {
                "present": bool(scoring_artifact_present),
                "artifact_path": scoring_artifact_path.name,
            },
        },
        "quality_summary": {
            "benchmark_event_counts": dict(benchmark_event_counts),
            "stratification_coverage": dict(stratification_coverage),
            "n_events": int(getattr(scoring_result, "n_events", 0) or 0),
            "brier_score": _finite_metric(getattr(scoring_result, "brier_score", None)),
            "log_score": _finite_metric(getattr(scoring_result, "log_score", None)),
            "hit_rate": _finite_metric(getattr(scoring_result, "hit_rate", None)),
            "family_metrics": _serialize_family_metrics(scoring_result),
        },
        "warnings": list(warnings),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def _missing_smoke_pairs(provider_report: dict[str, Any], *, symbols: list[str], timeframes: list[str]) -> list[dict[str, str]]:
    rows = provider_report.get("smoke_test_results", []) if isinstance(provider_report, dict) else []
    seen: set[tuple[str, str]] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        timeframe = str(item.get("timeframe", "")).strip()
        if symbol and timeframe:
            seen.add((symbol, timeframe))

    missing: list[dict[str, str]] = []
    for symbol in symbols:
        for timeframe in timeframes:
            if (symbol, timeframe) not in seen:
                missing.append({"symbol": symbol, "timeframe": timeframe})
    return missing


def _status_ok_or_warn(status: str, *, fail_on_warn: bool) -> bool:
    if status == "ok":
        return True
    if status == "warn" and not fail_on_warn:
        return True
    return False


def _run_publish_contract_gate(args: argparse.Namespace) -> dict[str, Any]:
    try:
        verify_publish_contract(
            manifest_path=Path(args.manifest),
            core_path=Path(args.core_engine),
        )
        return {
            "name": "publish_contract",
            "status": "ok",
            "details": {
                "manifest": args.manifest,
                "core_engine": args.core_engine,
            },
        }
    except Exception as exc:
        return {
            "name": "publish_contract",
            "status": "fail",
            "details": {
                "message": str(exc),
                "manifest": args.manifest,
                "core_engine": args.core_engine,
            },
        }


def _run_reference_bundle_gate(symbol: str, timeframe: str, generated_at: float) -> dict[str, Any]:
    try:
        bundle = build_snapshot_bundle_for_symbol_timeframe(
            symbol,
            timeframe,
            source="auto",
            generated_at=generated_at,
        )
    except Exception as exc:
        return {
            "name": "reference_bundle",
            "status": "fail",
            "details": {
                "symbol": symbol,
                "timeframe": timeframe,
                "message": str(exc),
            },
        }

    snapshot = bundle.get("snapshot")
    if not isinstance(snapshot, dict):
        return {
            "name": "reference_bundle",
            "status": "fail",
            "details": {
                "symbol": symbol,
                "timeframe": timeframe,
                "message": "bundle has no dict snapshot payload",
            },
        }

    if "structure_context" in snapshot:
        return {
            "name": "reference_bundle",
            "status": "fail",
            "details": {
                "symbol": symbol,
                "timeframe": timeframe,
                "message": "structure_context must be additive and may not exist inside snapshot",
            },
        }

    return {
        "name": "reference_bundle",
        "status": "ok",
        "details": {
            "symbol": symbol,
            "timeframe": timeframe,
            "snapshot_keys": sorted(snapshot.keys()),
        },
    }


def _run_measurement_gate(
    symbol: str,
    timeframe: str,
    *,
    output_root: Path,
    report_output: str = "-",
    baseline_summary_path: str | None = None,
    strict_measurement_shadow: bool = False,
) -> dict[str, Any]:
    """Generate benchmark + scoring artifacts and validate their structure.

    This gate is *soft* — it reports warnings but never blocks the release.
    It validates:
      - benchmark artifact can be produced and has valid structure
      - scoring artifact can be produced and has valid structure
      - brier_score is finite and in [0, 1] (if present)
      - log_score is finite and >= 0 (if present)
    """
    warnings: list[str] = []
    output_dir = _measurement_output_dir(output_root, symbol=symbol, timeframe=timeframe)
    benchmark_artifact_path = output_dir / f"benchmark_{symbol}_{timeframe}.json"
    benchmark_manifest_path = output_dir / "manifest.json"
    scoring_artifact_path = output_dir / f"scoring_{symbol}_{timeframe}.json"
    measurement_manifest_path = output_dir / "measurement_manifest.json"
    empty_events: dict[EventFamily, list[dict[str, Any]]] = {
        "BOS": [],
        "OB": [],
        "FVG": [],
        "SWEEP": [],
    }
    benchmark_event_counts: dict[str, int] = {}
    stratification_coverage = {
        "bucket_count": 0,
        "populated_bucket_count": 0,
        "dimensions_present": [],
        "bucket_event_counts": {},
    }
    scoring_result = None

    details: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "measurement_artifacts_present": False,
        "scoring_artifacts_present": False,
        "measurement_evidence_present": False,
        "measurement_manifest_present": False,
        "benchmark_event_counts": {},
        "stratification_coverage": stratification_coverage,
        "measurement_output_dir": _path_for_report(output_dir, report_output=report_output),
        "benchmark_artifact_path": _path_for_report(benchmark_artifact_path, report_output=report_output),
        "benchmark_manifest_path": _path_for_report(benchmark_manifest_path, report_output=report_output),
        "scoring_artifact_path": _path_for_report(scoring_artifact_path, report_output=report_output),
        "measurement_manifest_path": _path_for_report(measurement_manifest_path, report_output=report_output),
        "measurement_shadow_thresholds": serialize_measurement_shadow_thresholds(get_measurement_shadow_thresholds()),
        "measurement_shadow_baseline": {
            "available": False,
            "history_runs": 0,
            "required_history_runs": get_measurement_shadow_thresholds().min_history_runs,
            "brier_score": None,
            "log_score": None,
            "n_events": None,
            "populated_bucket_count": None,
        },
        "measurement_shadow_strict": bool(strict_measurement_shadow),
        "measurement_baseline_summary_path": baseline_summary_path,
        "measurement_degradations_detected": [],
        "degradations_detected": [],
    }

    try:
        evidence = build_measurement_evidence(symbol, timeframe)
        details.update(evidence.details)
        warnings.extend(evidence.warnings)
    except Exception as exc:
        evidence = None
        warnings.append(f"measurement evidence generation failed: {exc}")

    # -- Benchmark artifact -------------------------------------------------
    try:
        benchmark_result = build_benchmark(
            symbol,
            timeframe,
            events_by_family=evidence.events_by_family if evidence is not None else empty_events,
            stratified_events=evidence.stratified_events if evidence is not None and evidence.stratified_events else None,
        )
        export_benchmark_artifacts(benchmark_result, output_dir)
        details["measurement_artifacts_present"] = True
        details["benchmark_families"] = len(benchmark_result.kpis)
        details["benchmark_schema_version"] = benchmark_result.schema_version
        benchmark_event_counts = {
            kpi.family: int(kpi.n_events)
            for kpi in benchmark_result.kpis
        }
        stratification_coverage = _summarize_stratification(benchmark_result)
        details["benchmark_event_counts"] = benchmark_event_counts
        details["stratification_coverage"] = stratification_coverage
    except Exception as exc:
        warnings.append(f"benchmark artifact generation failed: {exc}")

    # -- Scoring artifact ---------------------------------------------------
    try:
        scoring_result = score_events(evidence.scored_events if evidence is not None else [])
        export_scoring_artifact(
            scoring_result,
            symbol=symbol,
            timeframe=timeframe,
            output_dir=output_dir,
            schema_version=SCHEMA_VERSION,
        )
        details["scoring_artifacts_present"] = True
        details["scoring_event_count"] = int(scoring_result.n_events)
        details["scoring_family_metrics"] = _serialize_family_metrics(scoring_result)
        details["scoring_families_present"] = sorted(details["scoring_family_metrics"].keys())

        bs = scoring_result.brier_score
        ls = scoring_result.log_score
        if math.isfinite(bs) and not (0.0 <= bs <= 1.0):
            warnings.append(f"brier_score {bs:.6f} outside expected range [0, 1]")
        if math.isfinite(ls) and ls < 0:
            warnings.append(f"log_score {ls:.6f} is negative (expected >= 0)")
        details["brier_score"] = _finite_metric(bs)
        details["log_score"] = _finite_metric(ls)
        details["scoring_hit_rate"] = _finite_metric(scoring_result.hit_rate)
        details["brier_finite"] = math.isfinite(bs) if not math.isnan(bs) else "nan_empty"
        details["log_finite"] = math.isfinite(ls) if not math.isnan(ls) else "nan_empty"
    except Exception as exc:
        warnings.append(f"scoring artifact generation failed: {exc}")

    try:
        _write_measurement_manifest(
            output_dir=output_dir,
            symbol=symbol,
            timeframe=timeframe,
            benchmark_artifact_path=benchmark_artifact_path,
            benchmark_manifest_path=benchmark_manifest_path,
            benchmark_artifact_present=bool(details["measurement_artifacts_present"]),
            scoring_artifact_path=scoring_artifact_path,
            scoring_artifact_present=bool(details["scoring_artifacts_present"]),
            measurement_evidence_present=bool(details.get("measurement_evidence_present")),
            evaluated_event_counts=details.get("evaluated_event_counts", {}) or {},
            bars_source_mode=str(details.get("bars_source_mode", "") or "") or None,
            warnings=warnings,
            benchmark_event_counts=benchmark_event_counts,
            stratification_coverage=stratification_coverage,
            scoring_result=scoring_result,
        )
        details["measurement_manifest_present"] = True
    except Exception as exc:
        warnings.append(f"measurement manifest export failed: {exc}")

    history_rows, history_error = _load_measurement_history_rows(
        baseline_summary_path,
        symbol=symbol,
        timeframe=timeframe,
    )
    if history_error:
        warnings.append(history_error)

    current_entry = {
        "pair": f"{symbol}/{timeframe}",
        "symbol": symbol,
        "timeframe": timeframe,
        "brier_score": details.get("brier_score"),
        "log_score": details.get("log_score"),
        "n_events": details.get("scoring_event_count", 0),
        "stratification_coverage": details.get("stratification_coverage", {}),
    }
    measurement_degradations, shadow_baseline = assess_measurement_shadow_degradations(
        current_entry,
        history_rows,
        thresholds=get_measurement_shadow_thresholds(),
    )
    details["measurement_shadow_baseline"] = shadow_baseline
    details["measurement_degradations_detected"] = measurement_degradations
    details["degradations_detected"] = measurement_degradations
    for degradation in measurement_degradations:
        detail = str(degradation.get("detail", degradation.get("code", "measurement degradation"))).strip()
        warnings.append(detail)

    details["warnings"] = warnings
    if strict_measurement_shadow and measurement_degradations:
        status = "fail"
    else:
        # Measurement gate is soft by default — "ok" or "warn" unless explicitly promoted.
        status = "warn" if warnings or measurement_degradations else "ok"
    return {
        "name": "measurement_lane",
        "status": status,
        "blocking": bool(strict_measurement_shadow and measurement_degradations),
        "details": details,
    }


def _render(report: dict[str, Any], output: str) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if output == "-":
        print(rendered)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run strict SMC release gates.")
    parser.add_argument(
        "--symbols",
        default=csv_from_values(RELEASE_REFERENCE_SYMBOLS),
        help="Comma-separated reference symbols used for strict release checks.",
    )
    parser.add_argument(
        "--timeframes",
        default=csv_from_values(RELEASE_REFERENCE_TIMEFRAMES),
        help="Comma-separated reference timeframes used for strict release checks.",
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=RELEASE_STALE_AFTER_SECONDS,
        help="Staleness threshold used by strict release provider health checks.",
    )
    parser.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Also fail strict release gates on non-core warnings.",
    )
    parser.add_argument(
        "--allow-warn",
        action="store_true",
        help="Deprecated compatibility flag. When provided, non-core warnings are not blocking.",
    )
    parser.add_argument(
        "--skip-publish-contract",
        action="store_true",
        help="Skip publish contract verification gate.",
    )
    parser.add_argument(
        "--manifest",
        default="pine/generated/smc_micro_profiles_generated.json",
        help="Path to micro publish manifest used by publish contract gate.",
    )
    parser.add_argument(
        "--core-engine",
        default="SMC_Core_Engine.pine",
        help="Path to core engine pine file used by publish contract gate.",
    )
    parser.add_argument(
        "--measurement-output-root",
        default=None,
        help="Directory where measurement artifacts are written. Defaults to <output-dir>/measurement or artifacts/ci/measurement when output is stdout.",
    )
    parser.add_argument(
        "--measurement-baseline-summary",
        default=None,
        help="Optional evidence summary JSON used as historical baseline for measurement shadow comparisons.",
    )
    parser.add_argument(
        "--strict-measurement-shadow",
        action="store_true",
        help="Promote measurement shadow degradations from warn-only to blocking failures.",
    )
    parser.add_argument("--output", default="-", help="Output path for JSON report, or '-' for stdout.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    checked_at = float(time.time())

    # Resolve effective policy: CLI args > env vars > defaults.
    policy = resolve_release_policy(
        symbols=args.symbols if args.symbols != csv_from_values(RELEASE_REFERENCE_SYMBOLS) else None,
        timeframes=args.timeframes if args.timeframes != csv_from_values(RELEASE_REFERENCE_TIMEFRAMES) else None,
        stale_after_seconds=args.stale_after_seconds if args.stale_after_seconds != RELEASE_STALE_AFTER_SECONDS else None,
    )
    symbols = policy["symbols"] or list(RELEASE_REFERENCE_SYMBOLS)
    timeframes = policy["timeframes"] or list(RELEASE_REFERENCE_TIMEFRAMES)
    stale_seconds = int(policy["stale_after_seconds"])
    fail_on_warn = bool(args.fail_on_warn) and not bool(args.allow_warn)
    measurement_output_root = _resolve_measurement_output_root(
        report_output=args.output,
        explicit_root=args.measurement_output_root,
    )

    provider_report = run_provider_health_check(
        symbols=symbols,
        timeframes=timeframes,
        stale_after_seconds=stale_seconds,
        checked_at=checked_at,
        strict_release_policy=True,
    )

    provider_status = str(provider_report.get("overall_status", "fail")).lower()
    missing_smoke_pairs = _missing_smoke_pairs(provider_report, symbols=symbols, timeframes=timeframes)
    missing_smoke_failures = [
        {
            "code": "MISSING_SMOKE_RESULT",
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
        }
        for row in missing_smoke_pairs
    ]

    gates: list[dict[str, Any]] = [
        {
            "name": "provider_health",
            "status": "ok" if _status_ok_or_warn(provider_status, fail_on_warn=fail_on_warn) and not missing_smoke_failures else "fail",
            "details": {
                "overall_status": provider_status,
                "failures": provider_report.get("failures", []),
                "warnings": provider_report.get("warnings", []),
                "degradations_detected": provider_report.get("degradations_detected", []),
                "missing_smoke_failures": missing_smoke_failures,
            },
        }
    ]

    gates.append(_run_reference_bundle_gate(symbols[0], timeframes[0], checked_at))

    if not args.skip_publish_contract:
        gates.append(_run_publish_contract_gate(args))

    # Measurement gate — soft, non-blocking
    gates.append(
        _run_measurement_gate(
            symbols[0],
            timeframes[0],
            output_root=measurement_output_root,
            report_output=args.output,
            baseline_summary_path=args.measurement_baseline_summary,
            strict_measurement_shadow=bool(args.strict_measurement_shadow),
        )
    )

    has_fail = any(gate.get("status") == "fail" for gate in gates if gate.get("blocking", True))
    overall_status = "fail" if has_fail else "ok"
    exit_code = 1 if has_fail else 0

    report = {
        "report_kind": "release_gates",
        "checked_at": checked_at,
        "checked_at_iso": _iso_utc(checked_at),
        "overall_status": overall_status,
        "reference_symbols": symbols,
        "reference_timeframes": timeframes,
        "stale_after_seconds": stale_seconds,
        "fail_on_warn": fail_on_warn,
        "gates": gates,
        "runner": {
            "script": "scripts/run_smc_release_gates.py",
            "mode": "strict_release_gates",
            "skip_publish_contract": bool(args.skip_publish_contract),
            "measurement_output_root": measurement_output_root.as_posix(),
            "measurement_baseline_summary": args.measurement_baseline_summary,
            "strict_measurement_shadow": bool(args.strict_measurement_shadow),
            "exit_code": int(exit_code),
        },
        "runtime_metadata": runtime_metadata(),
    }

    # Attach structured failure diagnostics so operators see *why* a gate failed.
    if overall_status == "fail":
        report["failure_reasons"] = diagnose_gate_failure(report)

    _render(report, args.output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
