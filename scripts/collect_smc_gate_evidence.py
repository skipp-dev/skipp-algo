from __future__ import annotations

import argparse
import glob
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from smc_integration.release_policy import (
    EVIDENCE_LOOKBACK_DAYS,
    EVIDENCE_MIN_DEEPER_OK_RUNS,
    EVIDENCE_MIN_RELEASE_OK_RUNS,
    EVIDENCE_MIN_SYMBOL_COVERAGE,
    EVIDENCE_MIN_TIMEFRAME_COVERAGE,
    REASON_INSUFFICIENT_RUNS,
    REASON_INSUFFICIENT_SYMBOLS,
    REASON_INSUFFICIENT_TIMEFRAMES,
    REASON_STALE_DATA,
    assess_measurement_shadow_degradations,
    get_measurement_shadow_thresholds,
    serialize_measurement_shadow_thresholds,
)


def _iso_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _parse_report_timestamp(report: dict[str, Any], path: Path) -> float | None:
    checked = report.get("checked_at")
    if isinstance(checked, (int, float)):
        return float(checked)

    refreshed = report.get("generated_at")
    if isinstance(refreshed, (int, float)):
        return float(refreshed)

    try:
        return float(path.stat().st_mtime)
    except Exception:
        return None


def _infer_report_kind(report: dict[str, Any]) -> str:
    explicit = str(report.get("report_kind", "")).strip()
    if explicit:
        return explicit
    if isinstance(report.get("refresh_manifests"), list):
        return "pre_release_refresh"
    if isinstance(report.get("gates"), list):
        return "release_gates"
    if isinstance(report.get("provider_domain_results"), list):
        return "ci_health"
    return "unknown"


def _iter_code_rows(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _extract_codes(report: dict[str, Any]) -> list[str]:
    codes: list[str] = []

    for key in ("failures", "warnings", "degradations_detected", "degradations", "measurement_degradations_detected"):
        for row in _iter_code_rows(report.get(key)):
            code = str(row.get("code", "")).strip()
            if code:
                codes.append(code)

    gates = report.get("gates")
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            details = gate.get("details")
            if not isinstance(details, dict):
                continue
            for key in ("failures", "warnings", "degradations_detected", "missing_smoke_failures", "measurement_degradations_detected"):
                for row in _iter_code_rows(details.get(key)):
                    code = str(row.get("code", "")).strip()
                    if code:
                        codes.append(code)

    deduped: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        deduped.append(code)
    return deduped


def _status_value(report: dict[str, Any]) -> str:
    raw = str(report.get("overall_status", "unknown")).strip().lower()
    if raw in {"ok", "warn", "fail"}:
        return raw
    return "unknown"


def _is_deeper_candidate(kind: str) -> bool:
    return kind == "ci_health"


def _is_release_candidate(kind: str) -> bool:
    return kind == "release_gates"


_STALE_DOMAIN_CODES = {
    "STALE_META_VOLUME_DOMAIN",
    "STALE_META_TECHNICAL_DOMAIN",
    "STALE_META_NEWS_DOMAIN",
}


def _is_core_failure_code(code: str) -> bool:
    upper = str(code).upper()
    if "MISSING" in upper:
        return True
    if "STALE" in upper:
        return True
    if "SMOKE" in upper:
        return True
    if upper in {
        "BUNDLE_BUILD_FAILED",
        "REFRESH_EXECUTION_FAILED",
        "REFRESH_INCOMPLETE_REFERENCE_SET",
        "REFRESH_MANIFEST_ERRORS",
    }:
        return True
    return False


def _measurement_gate_row(report: dict[str, Any]) -> dict[str, Any] | None:
    for gate in _iter_code_rows(report.get("gates")):
        if str(gate.get("name", "")).strip() == "measurement_lane":
            return gate
    return None


def _resolve_related_path(raw_path: Any, *, base_path: Path, fallback_base: Path | None = REPO_ROOT) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None

    candidate = Path(value)
    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        candidates.append(base_path / candidate)
        if fallback_base is not None:
            candidates.append(fallback_base / candidate)

    for resolved in candidates:
        if resolved.exists():
            return resolved
    return candidates[0] if candidates else None


def _load_json_dict(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "artifact root must be a JSON object"
    return payload, None


def _finite_metric(value: Any) -> float | None:
    try:
        metric = float(value)
    except (TypeError, ValueError):
        return None
    if metric != metric:
        return None
    return metric


def _summarize_benchmark_artifact(payload: dict[str, Any]) -> tuple[dict[str, int], dict[str, Any]]:
    event_counts: dict[str, int] = {}
    for row in payload.get("kpis", []):
        if not isinstance(row, dict):
            continue
        family = str(row.get("family", "")).strip()
        if not family:
            continue
        try:
            event_counts[family] = int(row.get("n_events", 0) or 0)
        except (TypeError, ValueError):
            event_counts[family] = 0

    bucket_event_counts: dict[str, int] = {}
    dimensions_present: set[str] = set()
    stratified = payload.get("stratified")
    if isinstance(stratified, dict):
        for bucket_key, bucket_rows in sorted(stratified.items()):
            dimension = str(bucket_key).split(":", 1)[0]
            dimensions_present.add(dimension)
            total_events = 0
            if isinstance(bucket_rows, list):
                for item in bucket_rows:
                    if not isinstance(item, dict):
                        continue
                    try:
                        total_events += int(item.get("n_events", 0) or 0)
                    except (TypeError, ValueError):
                        continue
            bucket_event_counts[str(bucket_key)] = total_events

    stratification_coverage = {
        "bucket_count": len(bucket_event_counts),
        "populated_bucket_count": sum(1 for value in bucket_event_counts.values() if value > 0),
        "dimensions_present": sorted(dimensions_present),
        "bucket_event_counts": bucket_event_counts,
    }
    return event_counts, stratification_coverage


def _normalize_family_metrics(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for family, metrics in sorted(raw.items()):
        if not isinstance(metrics, dict):
            continue
        normalized[str(family)] = {
            "n_events": int(metrics.get("n_events", 0) or 0),
            "brier_score": _finite_metric(metrics.get("brier_score")),
            "log_score": _finite_metric(metrics.get("log_score")),
            "hit_rate": _finite_metric(metrics.get("hit_rate")),
        }
    return normalized


def _extract_measurement_entry(
    report: dict[str, Any],
    path: Path,
    *,
    checked_at: float | None,
    commit: str | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    gate = _measurement_gate_row(report)
    if gate is None:
        return None, []

    raw_details = gate.get("details")
    details: dict[str, Any] = raw_details if isinstance(raw_details, dict) else {}
    symbol = str(details.get("symbol", "")).strip().upper()
    timeframe = str(details.get("timeframe", "")).strip()
    if not symbol or not timeframe:
        return None, []

    errors: list[dict[str, Any]] = []
    manifest_rel = str(details.get("measurement_manifest_path", "")).strip() or None
    manifest_present = bool(details.get("measurement_manifest_present"))
    manifest_payload: dict[str, Any] | None = None
    manifest_path = _resolve_related_path(manifest_rel, base_path=path.parent) if manifest_rel else None

    if manifest_path is not None and manifest_path.exists():
        manifest_payload, error = _load_json_dict(manifest_path)
        if error:
            errors.append({
                "artifact": "measurement_manifest",
                "path": manifest_rel or manifest_path.as_posix(),
                "message": error,
                "report": str(path),
            })
            manifest_payload = None
    elif manifest_rel and manifest_present:
        errors.append({
            "artifact": "measurement_manifest",
            "path": manifest_rel,
            "message": "measurement manifest not found",
            "report": str(path),
        })

    raw_manifest_artifacts = manifest_payload.get("artifacts") if isinstance(manifest_payload, dict) else None
    manifest_artifacts: dict[str, Any] = raw_manifest_artifacts if isinstance(raw_manifest_artifacts, dict) else {}
    raw_quality_summary = manifest_payload.get("quality_summary") if isinstance(manifest_payload, dict) else None
    quality_summary: dict[str, Any] = raw_quality_summary if isinstance(raw_quality_summary, dict) else {}

    benchmark_rel = None
    benchmark_present = bool(details.get("measurement_artifacts_present"))
    benchmark_manifest_rel = None
    benchmark_base = path.parent
    benchmark_artifact_info = manifest_artifacts.get("benchmark")
    if isinstance(benchmark_artifact_info, dict):
        benchmark_rel = str(benchmark_artifact_info.get("artifact_path", "")).strip() or None
        benchmark_manifest_rel = str(benchmark_artifact_info.get("manifest_path", "")).strip() or None
        benchmark_present = bool(benchmark_artifact_info.get("present"))
        if manifest_path is not None:
            benchmark_base = manifest_path.parent
    else:
        benchmark_rel = str(details.get("benchmark_artifact_path", "")).strip() or None
        benchmark_manifest_rel = str(details.get("benchmark_manifest_path", "")).strip() or None

    scoring_rel = None
    scoring_present = bool(details.get("scoring_artifacts_present"))
    scoring_base = path.parent
    scoring_artifact_info = manifest_artifacts.get("scoring")
    if isinstance(scoring_artifact_info, dict):
        scoring_rel = str(scoring_artifact_info.get("artifact_path", "")).strip() or None
        scoring_present = bool(scoring_artifact_info.get("present"))
        if manifest_path is not None:
            scoring_base = manifest_path.parent
    else:
        scoring_rel = str(details.get("scoring_artifact_path", "")).strip() or None

    benchmark_path = _resolve_related_path(benchmark_rel, base_path=benchmark_base) if benchmark_rel else None
    benchmark_manifest_path = _resolve_related_path(benchmark_manifest_rel, base_path=benchmark_base) if benchmark_manifest_rel else None
    scoring_path = _resolve_related_path(scoring_rel, base_path=scoring_base) if scoring_rel else None

    benchmark_payload: dict[str, Any] | None = None
    if benchmark_path is not None and benchmark_path.exists():
        benchmark_payload, error = _load_json_dict(benchmark_path)
        if error:
            errors.append({
                "artifact": "benchmark",
                "path": benchmark_rel or benchmark_path.as_posix(),
                "message": error,
                "report": str(path),
            })
            benchmark_payload = None
    elif benchmark_rel and benchmark_present:
        errors.append({
            "artifact": "benchmark",
            "path": benchmark_rel,
            "message": "benchmark artifact not found",
            "report": str(path),
        })

    scoring_payload: dict[str, Any] | None = None
    if scoring_path is not None and scoring_path.exists():
        scoring_payload, error = _load_json_dict(scoring_path)
        if error:
            errors.append({
                "artifact": "scoring",
                "path": scoring_rel or scoring_path.as_posix(),
                "message": error,
                "report": str(path),
            })
            scoring_payload = None
    elif scoring_rel and scoring_present:
        errors.append({
            "artifact": "scoring",
            "path": scoring_rel,
            "message": "scoring artifact not found",
            "report": str(path),
        })

    benchmark_event_counts: dict[str, int] = {}
    stratification_coverage = {
        "bucket_count": 0,
        "populated_bucket_count": 0,
        "dimensions_present": [],
        "bucket_event_counts": {},
    }
    if benchmark_payload is not None:
        benchmark_event_counts, stratification_coverage = _summarize_benchmark_artifact(benchmark_payload)
    else:
        raw_counts = details.get("benchmark_event_counts", quality_summary.get("benchmark_event_counts", {}))
        if isinstance(raw_counts, dict):
            benchmark_event_counts = {
                str(key): int(value or 0)
                for key, value in raw_counts.items()
            }
        raw_coverage = details.get("stratification_coverage", quality_summary.get("stratification_coverage", {}))
        if isinstance(raw_coverage, dict):
            stratification_coverage = {
                "bucket_count": int(raw_coverage.get("bucket_count", 0) or 0),
                "populated_bucket_count": int(raw_coverage.get("populated_bucket_count", 0) or 0),
                "dimensions_present": sorted(str(item) for item in raw_coverage.get("dimensions_present", []) if str(item).strip()),
                "bucket_event_counts": {
                    str(key): int(value or 0)
                    for key, value in dict(raw_coverage.get("bucket_event_counts", {})).items()
                },
            }

    n_events = 0
    brier_score = None
    log_score = None
    hit_rate = None
    family_metrics: dict[str, dict[str, Any]] = {}
    if scoring_payload is not None:
        n_events = int(scoring_payload.get("n_events", 0) or 0)
        brier_score = _finite_metric(scoring_payload.get("brier_score"))
        log_score = _finite_metric(scoring_payload.get("log_score"))
        hit_rate = _finite_metric(scoring_payload.get("hit_rate"))
        family_metrics = _normalize_family_metrics(scoring_payload.get("family_metrics"))
    else:
        n_events = int(details.get("scoring_event_count", quality_summary.get("n_events", 0)) or 0)
        brier_score = _finite_metric(details.get("brier_score", quality_summary.get("brier_score")))
        log_score = _finite_metric(details.get("log_score", quality_summary.get("log_score")))
        hit_rate = _finite_metric(details.get("scoring_hit_rate", quality_summary.get("hit_rate")))
        family_metrics = _normalize_family_metrics(
            details.get("scoring_family_metrics", quality_summary.get("family_metrics", {}))
        )

    warnings = manifest_payload.get("warnings") if isinstance(manifest_payload, dict) else details.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []

    entry = {
        "pair": f"{symbol}/{timeframe}",
        "symbol": symbol,
        "timeframe": timeframe,
        "status": str(gate.get("status", "unknown")).strip().lower() or "unknown",
        "checked_at": checked_at,
        "checked_at_iso": _iso_utc(checked_at),
        "git_commit": commit,
        "measurement_manifest_present": manifest_payload is not None or manifest_present,
        "measurement_manifest_path": manifest_rel,
        "measurement_evidence_present": bool(
            manifest_payload.get("measurement_evidence_present")
            if isinstance(manifest_payload, dict)
            else details.get("measurement_evidence_present")
        ),
        "benchmark_artifact_present": benchmark_payload is not None or benchmark_present,
        "benchmark_artifact_path": str(benchmark_rel or ""),
        "benchmark_manifest_path": str(benchmark_manifest_rel or ""),
        "scoring_artifact_present": scoring_payload is not None or scoring_present,
        "scoring_artifact_path": str(scoring_rel or ""),
        "benchmark_event_counts": benchmark_event_counts,
        "stratification_coverage": stratification_coverage,
        "n_events": n_events,
        "brier_score": brier_score,
        "log_score": log_score,
        "hit_rate": hit_rate,
        "family_metrics": family_metrics,
        "warnings": warnings,
    }
    return entry, errors


def _render(report: dict[str, Any], output: str) -> None:
    text = json.dumps(report, indent=2, sort_keys=True)
    if output == "-":
        print(text)
        return
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate SMC gate JSON reports into compact operational evidence.")
    parser.add_argument(
        "--input-glob",
        default="artifacts/ci/smc*_report.json",
        help="Glob pattern for gate report JSON files.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=EVIDENCE_LOOKBACK_DAYS,
        help="Lookback window used for GRUEN evidence readiness evaluation.",
    )
    parser.add_argument(
        "--min-deeper-ok-runs",
        type=int,
        default=EVIDENCE_MIN_DEEPER_OK_RUNS,
        help="Minimum number of successful deeper/nightly health runs in lookback window.",
    )
    parser.add_argument(
        "--min-release-ok-runs",
        type=int,
        default=EVIDENCE_MIN_RELEASE_OK_RUNS,
        help="Minimum number of successful strict release-gate runs in lookback window.",
    )
    parser.add_argument(
        "--fail-on-not-ready",
        action="store_true",
        help="Return exit code 1 when evidence is not green-ready.",
    )
    parser.add_argument("--output", default="-", help="Output path for JSON summary, or '-' for stdout.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    file_paths = sorted(Path(p) for p in glob.glob(str(args.input_glob)))
    now_ts = float(time.time())
    lookback_seconds = max(0, int(args.lookback_days)) * 24 * 60 * 60
    window_start_ts = now_ts - float(lookback_seconds)

    runs: list[dict[str, Any]] = []
    parse_failures: list[dict[str, Any]] = []
    measurement_entries: list[dict[str, Any]] = []
    measurement_artifact_failures: list[dict[str, Any]] = []
    # Track the most recent meta_domain_diagnostics per symbol/timeframe pair.
    latest_domain_diag: dict[str, dict[str, Any]] = {}  # key: "SYMBOL/TF"
    for path in file_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            parse_failures.append(
                {
                    "path": str(path),
                    "message": str(exc),
                }
            )
            continue

        if not isinstance(payload, dict):
            parse_failures.append(
                {
                    "path": str(path),
                    "message": "report root must be a JSON object",
                }
            )
            continue

        kind = _infer_report_kind(payload)
        status = _status_value(payload)
        checked_at = _parse_report_timestamp(payload, path)
        runtime_meta = payload.get("runtime_metadata")
        commit = None
        if isinstance(runtime_meta, dict):
            raw_commit = runtime_meta.get("git_commit")
            if isinstance(raw_commit, str) and raw_commit.strip():
                commit = raw_commit.strip()

        codes = _extract_codes(payload)
        run_row = {
            "path": str(path),
            "kind": kind,
            "status": status,
            "checked_at": checked_at,
            "checked_at_iso": _iso_utc(checked_at),
            "in_lookback_window": bool(checked_at is not None and checked_at >= window_start_ts),
            "git_commit": commit,
            "reference_symbols": payload.get("reference_symbols", []),
            "reference_timeframes": payload.get("reference_timeframes", []),
            "codes": codes,
        }

        measurement_entry, measurement_errors = _extract_measurement_entry(
            payload,
            path,
            checked_at=checked_at,
            commit=commit,
        )
        if measurement_entry is not None:
            run_row["measurement"] = measurement_entry
            measurement_entries.append(measurement_entry)
        measurement_artifact_failures.extend(measurement_errors)

        runs.append(run_row)

        # Collect meta_domain_diagnostics from smoke_test_results, keyed by
        # symbol/timeframe.  Only the most recent (highest checked_at) wins.
        smoke_results = payload.get("smoke_test_results")
        if isinstance(smoke_results, list):
            for sr in smoke_results:
                if not isinstance(sr, dict):
                    continue
                diag = sr.get("meta_domain_diagnostics")
                if not isinstance(diag, dict):
                    continue
                sym = str(sr.get("symbol", "")).strip().upper()
                tf = str(sr.get("timeframe", "")).strip()
                if not sym or not tf:
                    continue
                key = f"{sym}/{tf}"
                existing_ts = latest_domain_diag.get(key, {}).get("_checked_at")
                if existing_ts is None or (checked_at is not None and checked_at > existing_ts):
                    latest_domain_diag[key] = {**diag, "_checked_at": checked_at}

    runs.sort(key=lambda row: float(row.get("checked_at") or 0.0), reverse=True)

    status_counter: Counter[str] = Counter(str(row.get("status", "unknown")) for row in runs)
    kind_counter: Counter[str] = Counter(str(row.get("kind", "unknown")) for row in runs)

    runs_in_window = [row for row in runs if bool(row.get("in_lookback_window"))]
    deeper_ok_in_window = [row for row in runs_in_window if _is_deeper_candidate(str(row.get("kind", ""))) and row.get("status") == "ok"]
    release_ok_in_window = [row for row in runs_in_window if _is_release_candidate(str(row.get("kind", ""))) and row.get("status") == "ok"]

    recurring_failures: Counter[str] = Counter()
    stale_trend: Counter[str] = Counter()
    missing_trend: Counter[str] = Counter()
    smoke_trend: Counter[str] = Counter()
    stale_domain_trend: Counter[str] = Counter()
    stale_domain_runs: dict[str, list[dict[str, Any]]] = {code: [] for code in sorted(_STALE_DOMAIN_CODES)}

    for row in runs_in_window:
        codes = [str(code) for code in row.get("codes", [])]
        if str(row.get("status")) == "fail":
            recurring_failures.update(codes)
        for code in codes:
            upper = code.upper()
            if "STALE" in upper:
                stale_trend[code] += 1
            if "MISSING" in upper:
                missing_trend[code] += 1
            if "SMOKE" in upper:
                smoke_trend[code] += 1
            if code in _STALE_DOMAIN_CODES:
                stale_domain_trend[code] += 1
                stale_domain_runs[code].append({
                    "path": str(row.get("path", "")),
                    "checked_at_iso": row.get("checked_at_iso"),
                })

    unresolved_core_failures = [
        row
        for row in runs_in_window
        if row.get("status") != "ok" and any(_is_core_failure_code(str(code)) for code in row.get("codes", []))
    ]

    last_ok_at = next((row.get("checked_at") for row in runs if row.get("status") == "ok"), None)
    last_fail_at = next((row.get("checked_at") for row in runs if row.get("status") == "fail"), None)

    # Coverage analysis: which symbols and timeframes appeared in successful runs?
    covered_symbols: set[str] = set()
    covered_timeframes: set[str] = set()
    for row in runs_in_window:
        if row.get("status") == "ok":
            for sym in row.get("reference_symbols", []):
                covered_symbols.add(str(sym).upper())
            for tf in row.get("reference_timeframes", []):
                covered_timeframes.add(str(tf).strip())

    symbol_breadth_ok = len(covered_symbols) >= EVIDENCE_MIN_SYMBOL_COVERAGE
    timeframe_breadth_ok = len(covered_timeframes) >= EVIDENCE_MIN_TIMEFRAME_COVERAGE

    criteria = {
        "lookback_days": int(args.lookback_days),
        "min_deeper_ok_runs": int(args.min_deeper_ok_runs),
        "min_release_ok_runs": int(args.min_release_ok_runs),
        "min_symbol_coverage": EVIDENCE_MIN_SYMBOL_COVERAGE,
        "min_timeframe_coverage": EVIDENCE_MIN_TIMEFRAME_COVERAGE,
    }

    green_ready = (
        len(deeper_ok_in_window) >= int(args.min_deeper_ok_runs)
        and len(release_ok_in_window) >= int(args.min_release_ok_runs)
        and len(unresolved_core_failures) == 0
        and symbol_breadth_ok
        and timeframe_breadth_ok
    )

    # Build structured not-ready reasons for operator clarity.
    not_ready_reasons: list[dict[str, str]] = []
    if len(deeper_ok_in_window) < int(args.min_deeper_ok_runs):
        not_ready_reasons.append({
            "reason": REASON_INSUFFICIENT_RUNS,
            "detail": f"deeper OK runs: {len(deeper_ok_in_window)}/{args.min_deeper_ok_runs}",
        })
    if len(release_ok_in_window) < int(args.min_release_ok_runs):
        not_ready_reasons.append({
            "reason": REASON_INSUFFICIENT_RUNS,
            "detail": f"release OK runs: {len(release_ok_in_window)}/{args.min_release_ok_runs}",
        })
    if not symbol_breadth_ok:
        not_ready_reasons.append({
            "reason": REASON_INSUFFICIENT_SYMBOLS,
            "detail": f"covered {len(covered_symbols)} symbol(s), need >= {EVIDENCE_MIN_SYMBOL_COVERAGE}",
        })
    if not timeframe_breadth_ok:
        not_ready_reasons.append({
            "reason": REASON_INSUFFICIENT_TIMEFRAMES,
            "detail": f"covered {len(covered_timeframes)} timeframe(s), need >= {EVIDENCE_MIN_TIMEFRAME_COVERAGE}",
        })
    if unresolved_core_failures:
        not_ready_reasons.append({
            "reason": REASON_STALE_DATA,
            "detail": f"{len(unresolved_core_failures)} unresolved core failure(s)",
        })

    measurement_entries.sort(
        key=lambda row: (
            float(row.get("checked_at") or 0.0),
            str(row.get("pair", "")),
        ),
        reverse=True,
    )
    measurement_history_by_pair: dict[str, list[dict[str, Any]]] = {}
    for entry in measurement_entries:
        pair = str(entry.get("pair", "")).strip()
        if not pair:
            continue
        measurement_history_by_pair.setdefault(pair, []).append(entry)

    measurement_latest_by_pair = {
        pair: rows[0]
        for pair, rows in sorted(measurement_history_by_pair.items())
        if rows
    }
    measurement_shadow_thresholds = get_measurement_shadow_thresholds()
    measurement_degradations_detected: list[dict[str, Any]] = []
    for pair, rows in sorted(measurement_history_by_pair.items()):
        latest = rows[0]
        degradations, shadow_baseline = assess_measurement_shadow_degradations(
            latest,
            rows[1:],
            thresholds=measurement_shadow_thresholds,
        )
        latest["measurement_shadow_baseline"] = shadow_baseline
        latest["measurement_degradations_detected"] = degradations
        latest["degradations_detected"] = degradations
        if degradations:
            for degradation in degradations:
                measurement_degradations_detected.append(
                    {
                        **degradation,
                        "pair": pair,
                        "symbol": latest.get("symbol"),
                        "timeframe": latest.get("timeframe"),
                        "checked_at_iso": latest.get("checked_at_iso"),
                    }
                )

    measurement_history = {
        "runs_with_measurement_gate": len(measurement_entries),
        "runs_with_measurement_manifest": sum(1 for entry in measurement_entries if entry.get("measurement_manifest_present")),
        "runs_with_benchmark_artifact": sum(1 for entry in measurement_entries if entry.get("benchmark_artifact_present")),
        "runs_with_scoring_artifact": sum(1 for entry in measurement_entries if entry.get("scoring_artifact_present")),
        "pairs_observed": sorted(measurement_history_by_pair),
        "shadow_thresholds": serialize_measurement_shadow_thresholds(measurement_shadow_thresholds),
        "pairs_with_shadow_degradations": sorted({row["pair"] for row in measurement_degradations_detected}),
        "shadow_degradations_detected": measurement_degradations_detected,
        "latest_by_pair": measurement_latest_by_pair,
        "history_by_pair": {
            pair: rows
            for pair, rows in sorted(measurement_history_by_pair.items())
        },
        "artifact_load_failures": measurement_artifact_failures,
    }

    summary = {
        "generated_at": now_ts,
        "generated_at_iso": _iso_utc(now_ts),
        "report_kind": "gate_evidence_summary",
        "criteria": criteria,
        "runs_total": len(runs),
        "runs_ok": int(status_counter.get("ok", 0)),
        "runs_warn": int(status_counter.get("warn", 0)),
        "runs_fail": int(status_counter.get("fail", 0)),
        "runs_unknown": int(status_counter.get("unknown", 0)),
        "runs_by_kind": dict(kind_counter),
        "last_ok_at": last_ok_at,
        "last_ok_at_iso": _iso_utc(last_ok_at),
        "last_fail_at": last_fail_at,
        "last_fail_at_iso": _iso_utc(last_fail_at),
        "lookback_window_start": window_start_ts,
        "lookback_window_start_iso": _iso_utc(window_start_ts),
        "deeper_ok_runs_in_window": len(deeper_ok_in_window),
        "release_ok_runs_in_window": len(release_ok_in_window),
        "unresolved_core_failures_in_window": len(unresolved_core_failures),
        "covered_symbols": sorted(covered_symbols),
        "covered_timeframes": sorted(covered_timeframes),
        "symbol_breadth_ok": symbol_breadth_ok,
        "timeframe_breadth_ok": timeframe_breadth_ok,
        "recurring_failure_codes": dict(recurring_failures.most_common()),
        "stale_trend": dict(stale_trend),
        "stale_domain_trend": dict(stale_domain_trend),
        "stale_domain_runs": {code: runs_list for code, runs_list in stale_domain_runs.items() if runs_list},
        "missing_trend": dict(missing_trend),
        "smoke_trend": dict(smoke_trend),
        "green_ready": bool(green_ready),
        "not_ready_reasons": not_ready_reasons,
        "measurement_degradations_detected": measurement_degradations_detected,
        "measurement_history": measurement_history,
        "latest_domain_diagnostics": {
            key: {k: v for k, v in diag.items() if k != "_checked_at"}
            for key, diag in sorted(latest_domain_diag.items())
        } if latest_domain_diag else {},
        "parse_failures": parse_failures,
        "runs": runs,
    }

    _render(summary, str(args.output))

    if args.fail_on_not_ready and not green_ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
