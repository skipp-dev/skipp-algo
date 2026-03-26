from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from smc_integration.service import build_snapshot_bundle_for_symbol_timeframe
from smc_integration.artifact_resolution import resolve_structure_artifact_inputs


def export_snapshot_bundle(
    *,
    symbol: str,
    timeframe: str,
    source: str = "auto",
    output: Path | None = None,
    workbook_path: str | None = None,
    export_bundle_root: str | None = None,
    structure_artifacts_dir: str | None = None,
    fail_on_missing_structure_inputs: bool = False,
) -> Path:
    resolved_inputs = resolve_structure_artifact_inputs(
        explicit_workbook_path=workbook_path,
        explicit_export_bundle_root=export_bundle_root,
        explicit_structure_artifacts_dir=structure_artifacts_dir,
    )

    missing_required = any(str(item.get("code", "")) == "WORKBOOK_NOT_FOUND" for item in resolved_inputs.get("errors", [])) and (
        resolved_inputs.get("export_bundle_root") is None
    )
    if missing_required and fail_on_missing_structure_inputs:
        raise ValueError(
            "Missing structure inputs: no workbook and no export bundle root resolved. "
            "Provide --workbook-path or --export-bundle-root, or disable fail-on-missing mode."
        )

    bundle = build_snapshot_bundle_for_symbol_timeframe(
        symbol,
        timeframe,
        source=source,
    )
    bundle["resolved_inputs"] = {
        "workbook_path": str(resolved_inputs.get("workbook_path")) if resolved_inputs.get("workbook_path") is not None else None,
        "export_bundle_root": str(resolved_inputs.get("export_bundle_root")) if resolved_inputs.get("export_bundle_root") is not None else None,
        "structure_artifacts_dir": str(resolved_inputs.get("structure_artifacts_dir")) if resolved_inputs.get("structure_artifacts_dir") is not None else None,
    }
    bundle["resolution_mode"] = str(resolved_inputs.get("resolution_mode", "canonical"))
    bundle["errors"] = list(bundle.get("errors", [])) + list(resolved_inputs.get("errors", []))
    bundle["warnings"] = list(bundle.get("warnings", [])) + list(resolved_inputs.get("warnings", []))

    if output is None:
        safe_symbol = symbol.strip().upper() or "UNKNOWN"
        safe_timeframe = timeframe.strip() or "unknown"
        output = Path("reports") / f"smc_snapshot_bundle_{safe_symbol}_{safe_timeframe}.json"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    return output


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export SMC snapshot bundle for symbol/timeframe.")
    parser.add_argument("--symbol", required=True, help="Ticker symbol, e.g. AAPL")
    parser.add_argument("--timeframe", required=True, help="Timeframe, e.g. 15m")
    parser.add_argument("--source", default="auto", help="Integration source name or auto")
    parser.add_argument("--output", default="", help="Optional output JSON path")
    parser.add_argument("--workbook-path", default="", help="Optional explicit workbook path for structure upstream resolution")
    parser.add_argument("--export-bundle-root", default="", help="Optional explicit canonical export bundle root")
    parser.add_argument("--structure-artifacts-dir", default="", help="Optional explicit structure artifacts directory")
    parser.add_argument("--fail-on-missing-structure-inputs", action="store_true", help="Fail when structure upstream inputs cannot be resolved")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    output_path = Path(args.output).expanduser() if str(args.output).strip() else None
    written = export_snapshot_bundle(
        symbol=args.symbol,
        timeframe=args.timeframe,
        source=args.source,
        output=output_path,
        workbook_path=str(args.workbook_path).strip() or None,
        export_bundle_root=str(args.export_bundle_root).strip() or None,
        structure_artifacts_dir=str(args.structure_artifacts_dir).strip() or None,
        fail_on_missing_structure_inputs=bool(args.fail_on_missing_structure_inputs),
    )
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
