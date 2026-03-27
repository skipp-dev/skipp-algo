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

from smc_integration.artifact_resolution import resolve_structure_artifact_inputs
from smc_integration.release_policy import (
    RELEASE_REFERENCE_SYMBOLS,
    RELEASE_REFERENCE_TIMEFRAMES,
    csv_from_values,
    parse_csv,
    runtime_metadata,
)
from smc_integration.structure_batch import write_structure_artifacts_from_workbook


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _render(report: dict[str, Any], output: str) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if output == "-":
        print(rendered)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh release-reference structure artifacts before strict release gates.")
    parser.add_argument("--symbols", default=csv_from_values(RELEASE_REFERENCE_SYMBOLS), help="Comma-separated reference symbols.")
    parser.add_argument("--timeframes", default=csv_from_values(RELEASE_REFERENCE_TIMEFRAMES), help="Comma-separated reference timeframes.")
    parser.add_argument(
        "--structure-artifacts-dir",
        default="reports/smc_structure_artifacts",
        help="Directory where structure artifacts/manifest files are written.",
    )
    parser.add_argument("--workbook-path", default="", help="Optional explicit workbook path.")
    parser.add_argument("--export-bundle-root", default="", help="Optional explicit export bundle root path.")
    parser.add_argument("--structure-profile", default="hybrid_default", help="Structure profile used for refresh.")
    parser.add_argument(
        "--allow-missing-inputs",
        action="store_true",
        help="Allow missing workbook/export bundle and keep going with preexisting artifacts.",
    )
    parser.add_argument("--output", default="-", help="Output JSON path, or '-' for stdout.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    symbols = parse_csv(str(args.symbols), normalize_upper=True)
    timeframes = parse_csv(str(args.timeframes), normalize_upper=False)
    if not symbols:
        raise ValueError("release pre-refresh requires at least one reference symbol")
    if not timeframes:
        raise ValueError("release pre-refresh requires at least one reference timeframe")

    resolved_inputs = resolve_structure_artifact_inputs(
        explicit_workbook_path=str(args.workbook_path).strip() or None,
        explicit_export_bundle_root=str(args.export_bundle_root).strip() or None,
        explicit_structure_artifacts_dir=str(args.structure_artifacts_dir).strip() or None,
    )
    artifacts_dir = resolved_inputs.get("structure_artifacts_dir")
    if artifacts_dir is None:
        artifacts_dir = Path(str(args.structure_artifacts_dir)).expanduser()
    elif not isinstance(artifacts_dir, Path):
        artifacts_dir = Path(str(artifacts_dir)).expanduser()

    refresh_reports: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = list(resolved_inputs.get("warnings", []))

    generated_at = float(time.time())
    for timeframe in timeframes:
        try:
            manifest = write_structure_artifacts_from_workbook(
                workbook=resolved_inputs.get("workbook_path"),
                timeframe=timeframe,
                symbols=symbols,
                output_dir=artifacts_dir,
                export_bundle_root=resolved_inputs.get("export_bundle_root"),
                generated_at=generated_at,
                allow_missing_inputs=bool(args.allow_missing_inputs),
                structure_profile=str(args.structure_profile),
            )
            refresh_reports.append(manifest)
        except Exception as exc:
            failures.append(
                {
                    "code": "REFRESH_EXECUTION_FAILED",
                    "timeframe": timeframe,
                    "message": str(exc),
                }
            )
            continue

        manifest_errors = list(manifest.get("errors", []))
        if manifest_errors:
            failures.append(
                {
                    "code": "REFRESH_MANIFEST_ERRORS",
                    "timeframe": timeframe,
                    "details": manifest_errors,
                }
            )

        counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
        symbols_requested = int(counts.get("symbols_requested", 0))
        artifacts_written = int(counts.get("artifacts_written", 0))
        if artifacts_written < symbols_requested:
            failures.append(
                {
                    "code": "REFRESH_INCOMPLETE_REFERENCE_SET",
                    "timeframe": timeframe,
                    "symbols_requested": symbols_requested,
                    "artifacts_written": artifacts_written,
                }
            )

    checked_at = float(time.time())
    exit_code = 1 if failures else 0
    report = {
        "report_kind": "pre_release_refresh",
        "checked_at": checked_at,
        "checked_at_iso": _iso_utc(checked_at),
        "overall_status": "fail" if failures else "ok",
        "reference_symbols": symbols,
        "reference_timeframes": timeframes,
        "resolved_inputs": {
            "workbook_path": str(resolved_inputs.get("workbook_path")) if resolved_inputs.get("workbook_path") is not None else None,
            "export_bundle_root": str(resolved_inputs.get("export_bundle_root")) if resolved_inputs.get("export_bundle_root") is not None else None,
            "structure_artifacts_dir": str(artifacts_dir),
            "resolution_mode": str(resolved_inputs.get("resolution_mode", "unknown")),
        },
        "warnings": warnings,
        "failures": failures,
        "refresh_manifests": refresh_reports,
        "runner": {
            "script": "scripts/run_smc_pre_release_artifact_refresh.py",
            "mode": "pre_release_refresh",
            "exit_code": int(exit_code),
        },
        "runtime_metadata": runtime_metadata(),
    }

    _render(report, str(args.output))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
