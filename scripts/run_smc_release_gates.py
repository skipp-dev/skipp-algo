from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.verify_smc_micro_publish_contract import verify_publish_contract
from smc_core.benchmark import build_benchmark, export_benchmark_artifacts
from smc_core.scoring import export_scoring_artifact, score_events
from smc_core.schema_version import SCHEMA_VERSION
from smc_integration.measurement_evidence import build_measurement_evidence
from smc_integration.release_policy import (
    RELEASE_REFERENCE_SYMBOLS,
    RELEASE_REFERENCE_TIMEFRAMES,
    RELEASE_STALE_AFTER_SECONDS,
    csv_from_values,
    diagnose_gate_failure,
    parse_csv,
    resolve_release_policy,
    runtime_metadata,
)
from smc_integration.provider_health import run_provider_health_check
from smc_integration.service import build_snapshot_bundle_for_symbol_timeframe


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _parse_csv(raw: str) -> list[str]:
    return parse_csv(raw, normalize_upper=False)


def _normalize_symbols(raw: str) -> list[str]:
    return parse_csv(raw, normalize_upper=True)


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


def _run_measurement_gate(symbol: str, timeframe: str) -> dict[str, Any]:
    """Generate benchmark + scoring artifacts and validate their structure.

    This gate is *soft* — it reports warnings but never blocks the release.
    It validates:
      - benchmark artifact can be produced and has valid structure
      - scoring artifact can be produced and has valid structure
      - brier_score is finite and in [0, 1] (if present)
      - log_score is finite and >= 0 (if present)
    """
    import math
    import tempfile

    warnings: list[str] = []
    details: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "measurement_artifacts_present": False,
        "scoring_artifacts_present": False,
        "measurement_evidence_present": False,
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
            events_by_family=evidence.events_by_family if evidence is not None else {"BOS": [], "OB": [], "FVG": [], "SWEEP": []},
            stratified_events=evidence.stratified_events if evidence is not None and evidence.stratified_events else None,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path as _P
            export_benchmark_artifacts(benchmark_result, _P(tmpdir))
            details["measurement_artifacts_present"] = True
            details["benchmark_families"] = len(benchmark_result.kpis)
            details["benchmark_schema_version"] = benchmark_result.schema_version
            details["benchmark_event_counts"] = {
                kpi.family: int(kpi.n_events)
                for kpi in benchmark_result.kpis
            }
    except Exception as exc:
        warnings.append(f"benchmark artifact generation failed: {exc}")

    # -- Scoring artifact ---------------------------------------------------
    try:
        scoring_result = score_events(evidence.scored_events if evidence is not None else [])
        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path as _P
            export_scoring_artifact(
                scoring_result,
                symbol=symbol,
                timeframe=timeframe,
                output_dir=_P(tmpdir),
                schema_version=SCHEMA_VERSION,
            )
            details["scoring_artifacts_present"] = True
            details["scoring_event_count"] = int(scoring_result.n_events)

        bs = scoring_result.brier_score
        ls = scoring_result.log_score
        if math.isfinite(bs) and not (0.0 <= bs <= 1.0):
            warnings.append(f"brier_score {bs:.6f} outside expected range [0, 1]")
        if math.isfinite(ls) and ls < 0:
            warnings.append(f"log_score {ls:.6f} is negative (expected >= 0)")
        details["brier_finite"] = math.isfinite(bs) if not math.isnan(bs) else "nan_empty"
        details["log_finite"] = math.isfinite(ls) if not math.isnan(ls) else "nan_empty"
    except Exception as exc:
        warnings.append(f"scoring artifact generation failed: {exc}")

    details["warnings"] = warnings
    # Measurement gate is soft — always "ok" or "warn", never "fail"
    status = "warn" if warnings else "ok"
    return {
        "name": "measurement_lane",
        "status": status,
        "blocking": False,
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
    gates.append(_run_measurement_gate(symbols[0], timeframes[0]))

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
