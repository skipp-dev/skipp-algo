from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from smc_integration.batch import load_symbols_from_source, write_snapshot_bundles_for_symbols
from smc_integration.structure_batch import DEFAULT_WORKBOOK, write_structure_artifacts_from_workbook


def _parse_symbols_csv(raw: str) -> list[str]:
    return [item.strip().upper() for item in str(raw).split(",") if item.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export SMC snapshot bundles for a watchlist/source.")
    parser.add_argument("--timeframe", required=True, help="Timeframe, e.g. 15m")
    parser.add_argument("--source", default="auto", help="Integration source name or auto")
    parser.add_argument("--output-dir", default="reports/smc_snapshot_bundles", help="Output directory for bundles and manifest")
    parser.add_argument("--generated-at", type=float, default=None, help="Optional fixed generated_at timestamp")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol override")
    parser.add_argument("--structure-workbook", default=str(DEFAULT_WORKBOOK), help="Workbook path used for structure artifact batch export")
    parser.add_argument("--structure-output-dir", default="reports/smc_structure_artifacts", help="Output directory for structure artifacts and manifest")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    symbols = _parse_symbols_csv(args.symbols) if str(args.symbols).strip() else load_symbols_from_source(args.source)
    structure_manifest = write_structure_artifacts_from_workbook(
        workbook=Path(args.structure_workbook).expanduser(),
        timeframe=args.timeframe,
        symbols=symbols,
        output_dir=Path(args.structure_output_dir).expanduser(),
        generated_at=args.generated_at,
    )

    manifest = write_snapshot_bundles_for_symbols(
        symbols,
        args.timeframe,
        source=args.source,
        output_dir=Path(args.output_dir).expanduser(),
        generated_at=args.generated_at,
    )
    manifest["structure_manifest"] = structure_manifest

    manifest_path_value = manifest.get("manifest_path")
    if isinstance(manifest_path_value, str) and manifest_path_value.strip():
        manifest_path = Path(manifest_path_value).expanduser()
        if manifest_path.exists():
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
