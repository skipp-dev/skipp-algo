from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from smc_integration.service import build_snapshot_bundle_for_symbol_timeframe


def export_snapshot_bundle(
    *,
    symbol: str,
    timeframe: str,
    source: str = "auto",
    output: Path | None = None,
) -> Path:
    bundle = build_snapshot_bundle_for_symbol_timeframe(
        symbol,
        timeframe,
        source=source,
    )

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
    )
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
