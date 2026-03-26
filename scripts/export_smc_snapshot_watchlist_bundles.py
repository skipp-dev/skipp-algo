from __future__ import annotations

import argparse
import json
import csv
from pathlib import Path
from typing import Sequence

from smc_integration.batch import load_symbols_from_source, write_snapshot_bundles_for_symbols
from smc_integration.structure_batch import write_structure_artifacts_from_workbook
from smc_integration.artifact_resolution import resolve_watchlist_export_inputs


def _parse_symbols_csv(raw: str) -> list[str]:
    return [item.strip().upper() for item in str(raw).split(",") if item.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export SMC snapshot bundles for a watchlist/source.")
    parser.add_argument("--timeframe", required=True, help="Timeframe, e.g. 15m")
    parser.add_argument("--source", default="auto", help="Integration source name or auto")
    parser.add_argument("--output-dir", default="reports/smc_snapshot_bundles", help="Output directory for bundles and manifest")
    parser.add_argument("--generated-at", type=float, default=None, help="Optional fixed generated_at timestamp")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol override")
    parser.add_argument("--workbook-path", default="", help="Optional explicit workbook path for structure artifact generation")
    parser.add_argument("--structure-workbook", default="", help="Deprecated alias for --workbook-path")
    parser.add_argument("--export-bundle-root", default="", help="Optional explicit canonical export bundle root")
    parser.add_argument("--structure-artifacts-dir", default="reports/smc_structure_artifacts", help="Output directory for structure artifacts and manifest")
    parser.add_argument("--structure-output-dir", default="", help="Deprecated alias for --structure-artifacts-dir")
    parser.add_argument("--symbols-source", default="", help="Optional explicit symbols CSV path")
    parser.add_argument("--allow-missing-structure-inputs", action="store_true", help="Allow missing workbook/export-bundle and report structured errors")
    parser.add_argument("--fail-on-missing-structure-inputs", action="store_true", help="Fail export when required structure inputs are missing")
    return parser


def _load_symbols_from_csv(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return [str(row.get("symbol", "")).strip().upper() for row in rows if str(row.get("symbol", "")).strip()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    explicit_workbook = str(args.workbook_path).strip() or str(args.structure_workbook).strip()
    explicit_structure_dir = str(args.structure_artifacts_dir).strip() or str(args.structure_output_dir).strip() or "reports/smc_structure_artifacts"
    explicit_symbols_source = str(args.symbols_source).strip()

    resolved_inputs = resolve_watchlist_export_inputs(
        explicit_symbols_source_path=explicit_symbols_source,
        explicit_workbook_path=explicit_workbook,
        explicit_export_bundle_root=str(args.export_bundle_root).strip(),
        explicit_structure_artifacts_dir=explicit_structure_dir,
    )

    if str(args.symbols).strip():
        symbols = _parse_symbols_csv(args.symbols)
    elif explicit_symbols_source and resolved_inputs.get("symbols_source_path") is not None:
        symbols = _load_symbols_from_csv(Path(resolved_inputs["symbols_source_path"]))
    else:
        symbols = load_symbols_from_source(args.source)

    if not symbols:
        print(json.dumps({
            "error": "NO_SYMBOLS_RESOLVED",
            "message": "No symbols could be resolved from --symbols, --symbols-source, or source defaults.",
            "resolved_inputs": {
                "symbols_source_path": str(resolved_inputs.get("symbols_source_path")) if resolved_inputs.get("symbols_source_path") is not None else None,
                "workbook_path": str(resolved_inputs.get("workbook_path")) if resolved_inputs.get("workbook_path") is not None else None,
                "export_bundle_root": str(resolved_inputs.get("export_bundle_root")) if resolved_inputs.get("export_bundle_root") is not None else None,
                "structure_artifacts_dir": str(resolved_inputs.get("structure_artifacts_dir")) if resolved_inputs.get("structure_artifacts_dir") is not None else None,
            },
            "errors": resolved_inputs.get("errors", []),
            "warnings": resolved_inputs.get("warnings", []),
        }, indent=2, sort_keys=True))
        return 2

    allow_missing_inputs = bool(args.allow_missing_structure_inputs) or not bool(args.fail_on_missing_structure_inputs)
    try:
        structure_manifest = write_structure_artifacts_from_workbook(
            workbook=Path(resolved_inputs["workbook_path"]).expanduser() if resolved_inputs.get("workbook_path") is not None else None,
            timeframe=args.timeframe,
            symbols=symbols,
            output_dir=Path(explicit_structure_dir).expanduser(),
            export_bundle_root=Path(resolved_inputs["export_bundle_root"]).expanduser() if resolved_inputs.get("export_bundle_root") is not None else None,
            generated_at=args.generated_at,
            allow_missing_inputs=allow_missing_inputs,
        )
    except ValueError as exc:
        print(json.dumps({
            "error": "MISSING_STRUCTURE_INPUTS",
            "message": str(exc),
            "resolved_inputs": {
                "symbols_source_path": str(resolved_inputs.get("symbols_source_path")) if resolved_inputs.get("symbols_source_path") is not None else None,
                "workbook_path": str(resolved_inputs.get("workbook_path")) if resolved_inputs.get("workbook_path") is not None else None,
                "export_bundle_root": str(resolved_inputs.get("export_bundle_root")) if resolved_inputs.get("export_bundle_root") is not None else None,
                "structure_artifacts_dir": str(resolved_inputs.get("structure_artifacts_dir")) if resolved_inputs.get("structure_artifacts_dir") is not None else None,
            },
            "resolution_mode": resolved_inputs.get("resolution_mode"),
            "errors": list(resolved_inputs.get("errors", [])),
            "warnings": list(resolved_inputs.get("warnings", [])),
        }, indent=2, sort_keys=True))
        return 2

    missing_inputs_error = any(str(item.get("code", "")) == "MISSING_STRUCTURE_INPUTS" for item in structure_manifest.get("errors", []))
    if missing_inputs_error and bool(args.fail_on_missing_structure_inputs):
        print(json.dumps({
            "error": "MISSING_STRUCTURE_INPUTS",
            "message": "Structure inputs are missing and --fail-on-missing-structure-inputs is enabled.",
            "resolved_inputs": {
                "symbols_source_path": str(resolved_inputs.get("symbols_source_path")) if resolved_inputs.get("symbols_source_path") is not None else None,
                "workbook_path": str(resolved_inputs.get("workbook_path")) if resolved_inputs.get("workbook_path") is not None else None,
                "export_bundle_root": str(resolved_inputs.get("export_bundle_root")) if resolved_inputs.get("export_bundle_root") is not None else None,
                "structure_artifacts_dir": str(resolved_inputs.get("structure_artifacts_dir")) if resolved_inputs.get("structure_artifacts_dir") is not None else None,
            },
            "resolution_mode": resolved_inputs.get("resolution_mode"),
            "errors": structure_manifest.get("errors", []),
            "warnings": structure_manifest.get("warnings", []),
        }, indent=2, sort_keys=True))
        return 2

    manifest = write_snapshot_bundles_for_symbols(
        symbols,
        args.timeframe,
        source=args.source,
        output_dir=Path(args.output_dir).expanduser(),
        generated_at=args.generated_at,
    )
    manifest["structure_manifest"] = structure_manifest
    manifest["resolved_inputs"] = {
        "symbols_source_path": str(resolved_inputs.get("symbols_source_path")) if resolved_inputs.get("symbols_source_path") is not None else None,
        "workbook_path": str(resolved_inputs.get("workbook_path")) if resolved_inputs.get("workbook_path") is not None else None,
        "export_bundle_root": str(resolved_inputs.get("export_bundle_root")) if resolved_inputs.get("export_bundle_root") is not None else None,
        "structure_artifacts_dir": str(resolved_inputs.get("structure_artifacts_dir")) if resolved_inputs.get("structure_artifacts_dir") is not None else None,
    }
    manifest["resolution_mode"] = str(resolved_inputs.get("resolution_mode", "canonical"))
    manifest["errors"] = list(manifest.get("errors", [])) + list(resolved_inputs.get("errors", []))
    manifest["warnings"] = list(manifest.get("warnings", [])) + list(resolved_inputs.get("warnings", []))
    manifest["structure_source_mode"] = str(structure_manifest.get("resolution_mode", "unknown"))
    manifest["symbols_processed"] = int(manifest.get("counts", {}).get("symbols_built", 0))
    manifest["symbols_failed"] = int(manifest.get("counts", {}).get("errors", 0))

    manifest_path_value = manifest.get("manifest_path")
    if isinstance(manifest_path_value, str) and manifest_path_value.strip():
        manifest_path = Path(manifest_path_value).expanduser()
        if manifest_path.exists():
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
