"""Build a PIT-safe portfolio sector/correlation context artifact."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from governance.portfolio_context import (
    CompletedClose,
    SectorAssignment,
    build_portfolio_risk_context,
)
from scripts.smc_atomic_write import atomic_write_text


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number} must contain a JSON object")
        rows.append(payload)
    return rows


def _json_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{path} must contain a JSON list of objects")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build PortfolioRiskContextV1.")
    parser.add_argument("--closes-jsonl", type=Path, required=True)
    parser.add_argument("--sectors-json", type=Path, required=True)
    parser.add_argument("--symbols", required=True, help="Comma-separated symbol set.")
    parser.add_argument("--as-of", required=True, help="Timezone-aware ISO decision timestamp.")
    parser.add_argument("--lookback-sessions", type=int, default=60)
    parser.add_argument("--min-pair-observations", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    symbols = tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip())
    closes = tuple(
        CompletedClose(
            symbol=str(row["symbol"]),
            session_date=date.fromisoformat(str(row["session_date"])),
            adjusted_close=float(row["adjusted_close"]),
            published_at=datetime.fromisoformat(str(row["published_at"])),
        )
        for row in _jsonl(args.closes_jsonl)
    )
    sectors = tuple(
        SectorAssignment(
            symbol=str(row["symbol"]),
            sector=str(row["sector"]),
            effective_at=datetime.fromisoformat(str(row["effective_at"])),
        )
        for row in _json_records(args.sectors_json)
    )
    context = build_portfolio_risk_context(
        symbols=symbols,
        closes=closes,
        sectors=sectors,
        as_of=datetime.fromisoformat(args.as_of),
        lookback_sessions=args.lookback_sessions,
        min_pair_observations=args.min_pair_observations,
        source=f"{args.closes_jsonl}:{args.sectors_json}",
    )
    atomic_write_text(
        json.dumps(context.to_dict(), sort_keys=True, indent=2) + "\n",
        args.output,
        fsync=True,
    )
    print(
        json.dumps(
            {
                "complete": context.complete,
                "pairs": len(context.pair_correlations),
                "missing_symbols": list(context.missing_symbols),
            },
            sort_keys=True,
        )
    )
    return 0 if context.complete else 3


if __name__ == "__main__":
    raise SystemExit(main())
