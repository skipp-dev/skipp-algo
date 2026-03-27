from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .provider_matrix import discover_provider_matrix
from .repo_sources import (
    discover_composite_source_plan,
    discover_structure_source_status,
    load_raw_meta_input_composite,
    load_raw_structure_input,
)
from .service import build_snapshot_bundle_for_symbol_timeframe
from .sources import structure_artifact_json

CANONICAL_STRUCTURE_KEYS = ("bos", "orderblocks", "fvg", "liquidity_sweeps")
_FATAL_ARTIFACT_HEALTH_CODES = {
    "INVALID_MANIFEST_JSON",
    "INVALID_MANIFEST_SHAPE",
    "INVALID_STRUCTURE_ARTIFACT",
    "INVALID_LEGACY_STRUCTURE_ARTIFACT",
}
_STRICT_RELEASE_WARNING_CODES = {
    "ARTIFACT_LOOKUP_FAILED",
    "MISSING_ARTIFACT",
    "MISSING_MANIFEST",
    "MISSING_MANIFEST_GENERATED_AT",
    "INVALID_MANIFEST_JSON",
    "INVALID_MANIFEST_SHAPE",
    "INVALID_STRUCTURE_ARTIFACT",
    "INVALID_LEGACY_STRUCTURE_ARTIFACT",
    "MISSING_META_ASOF_TS",
}

_STRICT_RELEASE_DEGRADATION_CODES = {
    "STALE_MANIFEST_GENERATED_AT",
    "STALE_MANIFEST_FILE_MTIME",
    "STALE_META_ASOF_TS",
    "STALE_META_TECHNICAL_DOMAIN",
    "STALE_META_NEWS_DOMAIN",
    "STALE_META_VOLUME_DOMAIN",
}


def _now_ts() -> float:
    return float(time.time())


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _status_from_lists(*, failures: list[dict[str, Any]], warnings: list[dict[str, Any]], degradations: list[dict[str, Any]]) -> str:
    if failures:
        return "fail"
    if warnings or degradations:
        return "warn"
    return "ok"


def _normalize_symbols(symbols: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols or ["IBG"]:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out or ["IBG"]


def _normalize_timeframes(timeframes: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in timeframes or ["15m"]:
        timeframe = str(raw).strip()
        if not timeframe or timeframe in seen:
            continue
        seen.add(timeframe)
        out.append(timeframe)
    return out or ["15m"]


def _shape_ok(raw_structure: Any) -> bool:
    if not isinstance(raw_structure, dict):
        return False
    return set(raw_structure.keys()) == set(CANONICAL_STRUCTURE_KEYS)


def _structure_is_empty(raw_structure: dict[str, Any]) -> bool:
    for key in CANONICAL_STRUCTURE_KEYS:
        value = raw_structure.get(key, [])
        if isinstance(value, list) and value:
            return False
    return True


def _provider_domain_results() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in discover_provider_matrix():
        status = "ok"
        if not entry.potential.can_supply_symbols:
            status = "warn"
        rows.append(
            {
                "provider": entry.name,
                "status": status,
                "path_hint": entry.path_hint,
                "structure_mode": entry.current.snapshot_structure_mode,
                "meta_mode": entry.current.snapshot_meta_mode,
                "maps_structure": bool(entry.current.currently_maps_structure),
                "maps_meta": bool(entry.current.currently_maps_meta),
                "maps_technical": bool(entry.current.currently_maps_technical),
                "maps_news": bool(entry.current.currently_maps_news),
                "known_gaps": list(entry.known_gaps),
            }
        )
    rows.sort(key=lambda item: str(item["provider"]))
    return rows


def _collect_artifact_health(
    *,
    symbols: list[str],
    timeframes: list[str],
    checked_at: float,
    stale_after_seconds: int | None,
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    missing_artifacts: list[dict[str, Any]] = []
    stale_artifacts: list[dict[str, Any]] = []

    summary = structure_artifact_json.discover_normalized_contract_summary()
    raw_health = summary.get("health", {}) if isinstance(summary, dict) else {}
    health_issues = raw_health.get("issues", []) if isinstance(raw_health, dict) else []
    health_issue_rows = [item for item in health_issues if isinstance(item, dict)]

    for issue in health_issue_rows:
        code = str(issue.get("code", "UNKNOWN_HEALTH_ISSUE"))
        record = {
            "code": code,
            "message": str(issue.get("message", "")),
            "path": issue.get("path"),
        }
        if code in _FATAL_ARTIFACT_HEALTH_CODES:
            failures.append(record)
        else:
            warnings.append(record)

    for symbol in symbols:
        for timeframe in timeframes:
            try:
                has_artifact = structure_artifact_json.has_artifact_for_symbol_timeframe(symbol, timeframe)
            except Exception as exc:
                failures.append(
                    {
                        "code": "ARTIFACT_LOOKUP_FAILED",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": str(exc),
                    }
                )
                continue

            if not has_artifact:
                row = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "code": "MISSING_ARTIFACT",
                }
                missing_artifacts.append(row)
                warnings.append(
                    {
                        "code": "MISSING_ARTIFACT",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "No structure artifact could be resolved for symbol/timeframe.",
                    }
                )

    manifest_rows: list[dict[str, Any]] = []
    for timeframe in timeframes:
        manifest_path = structure_artifact_json.STRUCTURE_ARTIFACTS_DIR / f"manifest_{timeframe}.json"
        manifest_info: dict[str, Any] = {
            "timeframe": timeframe,
            "manifest_path": str(manifest_path.as_posix()),
            "exists": manifest_path.exists(),
        }

        if not manifest_path.exists():
            warnings.append(
                {
                    "code": "MISSING_MANIFEST",
                    "timeframe": timeframe,
                    "message": f"Manifest does not exist: {manifest_path.as_posix()}",
                }
            )
            manifest_rows.append(manifest_info)
            continue

        stat = manifest_path.stat()
        mtime_age = max(0.0, float(checked_at) - float(stat.st_mtime))
        manifest_info["mtime_age_seconds"] = mtime_age

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(
                {
                    "code": "INVALID_MANIFEST_JSON",
                    "timeframe": timeframe,
                    "manifest_path": str(manifest_path.as_posix()),
                    "message": str(exc),
                }
            )
            manifest_rows.append(manifest_info)
            continue

        generated_at = payload.get("generated_at") if isinstance(payload, dict) else None
        if isinstance(generated_at, (int, float)):
            generated_age = max(0.0, float(checked_at) - float(generated_at))
            manifest_info["generated_at"] = float(generated_at)
            manifest_info["generated_age_seconds"] = generated_age
            if stale_after_seconds is not None and generated_age > float(stale_after_seconds):
                stale_generated_row: dict[str, Any] = {
                    "timeframe": timeframe,
                    "manifest_path": str(manifest_path.as_posix()),
                    "generated_age_seconds": generated_age,
                    "stale_after_seconds": int(stale_after_seconds),
                    "code": "STALE_MANIFEST_GENERATED_AT",
                }
                stale_artifacts.append(stale_generated_row)
                degradations.append(dict(stale_generated_row))
        else:
            warnings.append(
                {
                    "code": "MISSING_MANIFEST_GENERATED_AT",
                    "timeframe": timeframe,
                    "manifest_path": str(manifest_path.as_posix()),
                    "message": "Manifest has no numeric generated_at field.",
                }
            )

        if stale_after_seconds is not None and mtime_age > float(stale_after_seconds):
            stale_mtime_row: dict[str, Any] = {
                "timeframe": timeframe,
                "manifest_path": str(manifest_path.as_posix()),
                "mtime_age_seconds": mtime_age,
                "stale_after_seconds": int(stale_after_seconds),
                "code": "STALE_MANIFEST_FILE_MTIME",
            }
            stale_artifacts.append(stale_mtime_row)
            degradations.append(dict(stale_mtime_row))

        manifest_rows.append(manifest_info)

    if stale_after_seconds is None:
        warnings.append(
            {
                "code": "STALE_THRESHOLD_UNSET",
                "message": "No staleness threshold configured; timestamps are inspected but not hard-gated by age.",
            }
        )

    status = _status_from_lists(failures=failures, warnings=warnings, degradations=degradations)
    return {
        "status": status,
        "contract_summary": {
            "mapped_structure_categories": dict(summary.get("mapped_structure_categories", {})),
            "structure_profile_supported": bool(summary.get("structure_profile_supported", False)),
            "diagnostics_available": bool(summary.get("diagnostics_available", False)),
        },
        "health_issue_count": len(health_issue_rows),
        "health_issues": health_issue_rows,
        "manifests": manifest_rows,
        "missing_artifacts": missing_artifacts,
        "stale_artifacts": stale_artifacts,
        "warnings": warnings,
        "failures": failures,
        "degradations": degradations,
    }


def _run_smoke_checks(
    *,
    symbols: list[str],
    timeframes: list[str],
    checked_at: float,
    stale_after_seconds: int | None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []
    all_failures: list[dict[str, Any]] = []
    all_degradations: list[dict[str, Any]] = []

    for symbol in symbols:
        for timeframe in timeframes:
            warnings: list[dict[str, Any]] = []
            failures: list[dict[str, Any]] = []
            degradations: list[dict[str, Any]] = []

            row: dict[str, Any] = {
                "symbol": symbol,
                "timeframe": timeframe,
            }

            try:
                source_plan = discover_composite_source_plan(source="auto", symbol=symbol, timeframe=timeframe)
                row["source_plan"] = source_plan
            except Exception as exc:
                failures.append(
                    {
                        "code": "SOURCE_PLAN_RESOLUTION_FAILED",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": str(exc),
                    }
                )
                row["status"] = "fail"
                row["warnings"] = warnings
                row["failures"] = failures
                row["degradations"] = degradations
                results.append(row)
                all_failures.extend(failures)
                continue

            try:
                raw_structure = load_raw_structure_input(symbol, timeframe, source="auto")
            except Exception as exc:
                failures.append(
                    {
                        "code": "STRUCTURE_INPUT_LOAD_FAILED",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": str(exc),
                    }
                )
                row["status"] = "fail"
                row["warnings"] = warnings
                row["failures"] = failures
                row["degradations"] = degradations
                results.append(row)
                all_failures.extend(failures)
                continue

            row["structure_shape_ok"] = _shape_ok(raw_structure)
            if not row["structure_shape_ok"]:
                failures.append(
                    {
                        "code": "INVALID_STRUCTURE_SHAPE",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "raw_structure is missing canonical top-level categories.",
                    }
                )
            elif _structure_is_empty(raw_structure):
                degradation = {
                    "code": "EMPTY_STRUCTURE_INPUT",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "message": "raw_structure contains only empty canonical category arrays.",
                }
                warnings.append(dict(degradation))
                degradations.append(dict(degradation))

            try:
                raw_meta = load_raw_meta_input_composite(symbol, timeframe, source="auto")
            except Exception as exc:
                failures.append(
                    {
                        "code": "META_INPUT_LOAD_FAILED",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": str(exc),
                    }
                )
                raw_meta = None

            if isinstance(raw_meta, dict):
                asof_ts = raw_meta.get("asof_ts")
                if not isinstance(asof_ts, (int, float)):
                    warnings.append(
                        {
                            "code": "MISSING_META_ASOF_TS",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "message": "raw_meta has no numeric asof_ts.",
                        }
                    )
                elif stale_after_seconds is not None:
                    age = max(0.0, float(checked_at) - float(asof_ts))
                    if age > float(stale_after_seconds):
                        stale_meta_degradation: dict[str, Any] = {
                            "code": "STALE_META_ASOF_TS",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "age_seconds": age,
                            "stale_after_seconds": int(stale_after_seconds),
                        }
                        warnings.append(dict(stale_meta_degradation))
                        degradations.append(dict(stale_meta_degradation))

                # Per-domain staleness (technical / news).
                domain_diag = raw_meta.get("meta_domain_diagnostics")
                if isinstance(domain_diag, dict):
                    for domain in ("volume", "technical", "news"):
                        if domain_diag.get(f"{domain}_stale") is True:
                            code = f"STALE_META_{domain.upper()}_DOMAIN"
                            stale_domain_row: dict[str, Any] = {
                                "code": code,
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "message": f"{domain} domain meta is stale or missing.",
                            }
                            age_hours = domain_diag.get(f"{domain}_age_hours")
                            if age_hours is not None:
                                stale_domain_row["age_hours"] = age_hours
                            warnings.append(dict(stale_domain_row))
                            degradations.append(dict(stale_domain_row))

            if failures:
                row["status"] = "fail"
                row["warnings"] = warnings
                row["failures"] = failures
                row["degradations"] = degradations
                results.append(row)
                all_warnings.extend(warnings)
                all_failures.extend(failures)
                all_degradations.extend(degradations)
                continue

            try:
                bundle = build_snapshot_bundle_for_symbol_timeframe(
                    symbol,
                    timeframe,
                    source="auto",
                    generated_at=float(checked_at),
                )
            except Exception as exc:
                failures.append(
                    {
                        "code": "BUNDLE_BUILD_FAILED",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": str(exc),
                    }
                )
                row["status"] = "fail"
                row["warnings"] = warnings
                row["failures"] = failures
                row["degradations"] = degradations
                results.append(row)
                all_warnings.extend(warnings)
                all_failures.extend(failures)
                all_degradations.extend(degradations)
                continue

            snapshot = bundle.get("snapshot")
            if not isinstance(snapshot, dict):
                failures.append(
                    {
                        "code": "INVALID_BUNDLE_SNAPSHOT",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle has no dict snapshot payload.",
                    }
                )
            else:
                snapshot_structure = snapshot.get("structure")
                if not isinstance(snapshot_structure, dict) or set(snapshot_structure.keys()) != set(CANONICAL_STRUCTURE_KEYS):
                    failures.append(
                        {
                            "code": "INVALID_SNAPSHOT_STRUCTURE_SHAPE",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "message": "snapshot.structure does not expose canonical categories.",
                        }
                    )
                if "structure_context" in snapshot:
                    failures.append(
                        {
                            "code": "STRUCTURE_CONTEXT_POLLUTES_SNAPSHOT",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "message": "structure_context must stay additive and not exist inside snapshot.",
                        }
                    )

            if not isinstance(bundle.get("dashboard_payload"), dict):
                failures.append(
                    {
                        "code": "MISSING_DASHBOARD_PAYLOAD",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle has no dashboard_payload object.",
                    }
                )
            if not isinstance(bundle.get("pine_payload"), dict):
                failures.append(
                    {
                        "code": "MISSING_PINE_PAYLOAD",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle has no pine_payload object.",
                    }
                )

            bundle_plan = bundle.get("source_plan")
            if isinstance(bundle_plan, dict):
                if bundle_plan != row.get("source_plan"):
                    degradation = {
                        "code": "SOURCE_PLAN_MISMATCH",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle.source_plan differs from pre-resolved composite plan.",
                    }
                    warnings.append(dict(degradation))
                    degradations.append(dict(degradation))
            else:
                warnings.append(
                    {
                        "code": "MISSING_BUNDLE_SOURCE_PLAN",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle has no source_plan object.",
                    }
                )

            if "structure_context" in bundle and not isinstance(bundle.get("structure_context"), dict):
                warnings.append(
                    {
                        "code": "INVALID_STRUCTURE_CONTEXT_SHAPE",
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "message": "bundle structure_context exists but is not an object.",
                    }
                )

            row["status"] = _status_from_lists(failures=failures, warnings=warnings, degradations=degradations)
            row["warnings"] = warnings
            row["failures"] = failures
            row["degradations"] = degradations
            results.append(row)

            all_warnings.extend(warnings)
            all_failures.extend(failures)
            all_degradations.extend(degradations)

    return {
        "results": results,
        "warnings": all_warnings,
        "failures": all_failures,
        "degradations": all_degradations,
    }


def _sorted_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=True))


def _promote_release_strict_failures(
    *,
    warnings: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    degradations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    promoted_warnings: list[dict[str, Any]] = []
    promoted_failures = list(failures)
    promoted_degradations: list[dict[str, Any]] = []

    for row in warnings:
        code = str(row.get("code", ""))
        if code in _STRICT_RELEASE_WARNING_CODES:
            promoted_failures.append(
                {
                    **row,
                    "promoted_by": "release_strict_policy",
                }
            )
            continue
        promoted_warnings.append(row)

    for row in degradations:
        code = str(row.get("code", ""))
        if code in _STRICT_RELEASE_DEGRADATION_CODES:
            promoted_failures.append(
                {
                    **row,
                    "promoted_by": "release_strict_policy",
                }
            )
            continue
        promoted_degradations.append(row)

    return promoted_warnings, promoted_failures, promoted_degradations


def run_provider_health_check(
    *,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
    stale_after_seconds: int | None = None,
    checked_at: float | None = None,
    strict_release_policy: bool = False,
) -> dict[str, Any]:
    checked = float(checked_at) if checked_at is not None else _now_ts()
    resolved_symbols = _normalize_symbols(symbols)
    resolved_timeframes = _normalize_timeframes(timeframes)

    provider_results = _provider_domain_results()

    structure_status = discover_structure_source_status(
        source="auto",
        symbol=resolved_symbols[0],
        timeframe=resolved_timeframes[0],
    )

    artifact_health = _collect_artifact_health(
        symbols=resolved_symbols,
        timeframes=resolved_timeframes,
        checked_at=checked,
        stale_after_seconds=stale_after_seconds,
    )

    smoke = _run_smoke_checks(
        symbols=resolved_symbols,
        timeframes=resolved_timeframes,
        checked_at=checked,
        stale_after_seconds=stale_after_seconds,
    )

    warnings: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []

    warnings.extend(artifact_health.get("warnings", []))
    failures.extend(artifact_health.get("failures", []))
    degradations.extend(artifact_health.get("degradations", []))

    warnings.extend(smoke.get("warnings", []))
    failures.extend(smoke.get("failures", []))
    degradations.extend(smoke.get("degradations", []))

    selected_health_issue_count = int(structure_status.get("selected_health_issue_count", 0))
    if selected_health_issue_count > 0:
        degradations.append(
            {
                "code": "STRUCTURE_SOURCE_HEALTH_ISSUES",
                "message": f"selected structure source reports {selected_health_issue_count} health issue(s)",
                "count": selected_health_issue_count,
            }
        )

    if strict_release_policy:
        warnings, failures, degradations = _promote_release_strict_failures(
            warnings=warnings,
            failures=failures,
            degradations=degradations,
        )

    warnings = _sorted_records(warnings)
    failures = _sorted_records(failures)
    degradations = _sorted_records(degradations)

    overall_status = _status_from_lists(failures=failures, warnings=warnings, degradations=degradations)

    report = {
        "checked_at": checked,
        "checked_at_iso": _iso_utc(checked),
        "overall_status": overall_status,
        "reference_symbols": resolved_symbols,
        "reference_timeframes": resolved_timeframes,
        "strict_release_policy": bool(strict_release_policy),
        "provider_domain_results": provider_results,
        "structure_source_status": structure_status,
        "artifact_health": artifact_health,
        "missing_artifacts": list(artifact_health.get("missing_artifacts", [])),
        "stale_artifacts": list(artifact_health.get("stale_artifacts", [])),
        "smoke_test_results": list(smoke.get("results", [])),
        "warnings": warnings,
        "failures": failures,
        "degradations_detected": degradations,
    }
    return report


def provider_health_exit_code(report: dict[str, Any], *, fail_on_warn: bool = False) -> int:
    status = str(report.get("overall_status", "fail")).strip().lower()
    if status == "fail":
        return 1
    if fail_on_warn and status == "warn":
        return 2
    return 0


def write_provider_health_report(report: dict[str, Any], output_path: Path | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if output_path is None:
        print(rendered)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered + "\n", encoding="utf-8")
