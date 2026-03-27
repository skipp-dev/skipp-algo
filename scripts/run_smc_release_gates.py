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
from smc_integration.release_policy import (
    RELEASE_REFERENCE_SYMBOLS,
    RELEASE_REFERENCE_TIMEFRAMES,
    RELEASE_STALE_AFTER_SECONDS,
    csv_from_values,
    parse_csv,
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
    symbols = _normalize_symbols(args.symbols) or list(RELEASE_REFERENCE_SYMBOLS)
    timeframes = _parse_csv(args.timeframes) or ["15m"]
    fail_on_warn = bool(args.fail_on_warn) and not bool(args.allow_warn)

    provider_report = run_provider_health_check(
        symbols=symbols,
        timeframes=timeframes,
        stale_after_seconds=args.stale_after_seconds,
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

    has_fail = any(gate.get("status") == "fail" for gate in gates)
    overall_status = "fail" if has_fail else "ok"
    exit_code = 1 if has_fail else 0

    report = {
        "report_kind": "release_gates",
        "checked_at": checked_at,
        "checked_at_iso": _iso_utc(checked_at),
        "overall_status": overall_status,
        "reference_symbols": symbols,
        "reference_timeframes": timeframes,
        "stale_after_seconds": int(args.stale_after_seconds),
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

    _render(report, args.output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
