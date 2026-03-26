from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from smc_integration.batch import load_symbols_from_source, write_snapshot_bundles_for_symbols


def _parse_symbols_csv(raw: str) -> list[str]:
    return [item.strip().upper() for item in str(raw).split(",") if item.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export SMC snapshot bundles for a watchlist/source.")
    parser.add_argument("--timeframe", required=True, help="Timeframe, e.g. 15m")
    parser.add_argument("--source", default="auto", help="Integration source name or auto")
    parser.add_argument("--output-dir", default="reports/smc_snapshot_bundles", help="Output directory for bundles and manifest")
    parser.add_argument("--generated-at", type=float, default=None, help="Optional fixed generated_at timestamp")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol override")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    symbols = _parse_symbols_csv(args.symbols) if str(args.symbols).strip() else load_symbols_from_source(args.source)
    manifest = write_snapshot_bundles_for_symbols(
        symbols,
        args.timeframe,
        source=args.source,
        output_dir=Path(args.output_dir).expanduser(),
        generated_at=args.generated_at,
    )

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
