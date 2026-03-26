from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from smc_integration.structure_batch import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_WORKBOOK,
    write_structure_artifacts_from_workbook,
)


def _parse_symbols_csv(raw: str) -> list[str] | None:
    values = [item.strip().upper() for item in str(raw).split(",") if item.strip()]
    return values if values else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export batch SMC structure artifacts from workbook data.")
    parser.add_argument("--workbook", default=str(DEFAULT_WORKBOOK), help="Workbook path containing daily_bars sheet")
    parser.add_argument("--timeframe", required=True, help="Target timeframe label for emitted structure IDs/artifacts")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol override")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory for artifacts + manifest")
    parser.add_argument("--generated-at", type=float, default=None, help="Optional fixed generated_at timestamp")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    manifest = write_structure_artifacts_from_workbook(
        workbook=Path(args.workbook).expanduser(),
        timeframe=str(args.timeframe).strip(),
        symbols=_parse_symbols_csv(args.symbols),
        output_dir=Path(args.output_dir).expanduser(),
        generated_at=args.generated_at,
    )

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
