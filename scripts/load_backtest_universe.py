"""CLI consumer for the per-day universe snapshots (#2352, re-audit F2).

Usage::

    python scripts/load_backtest_universe.py --trade-date 2024-01-15 --strict-universe

In strict mode (default for CI), this exits non-zero with
:class:`databento_universe.MissingUniverseSnapshotError` when no snapshot
exists for the requested trade date, so a survivorship-biased backtest run
cannot silently emerge.

Without ``--strict-universe`` it falls back to the live vendor with the
survivorship-bias warning from #2351 / A4 and prints the resolved symbol
list to stdout.

This is the consume-side primitive that future backtest entrypoints
(walk-forward harnesses, family-smoke runners) should call instead of
``fetch_us_equity_universe(...)``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from databento_universe import (
    MissingUniverseSnapshotError,
    load_universe_for_backtest,
)


def _parse_trade_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--trade-date must be an ISO-8601 date (YYYY-MM-DD), got {value!r}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve the universe a backtest should consume for a given trade date.",
    )
    parser.add_argument(
        "--trade-date",
        type=_parse_trade_date,
        required=True,
        help="Trade date (YYYY-MM-DD) the backtest is run for.",
    )
    parser.add_argument(
        "--strict-universe",
        action="store_true",
        help=(
            "Refuse to fall back to the live vendor when no snapshot exists. "
            "Recommended for CI / promotion-gate runs to avoid silent survivorship bias."
        ),
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=None,
        help="Override the snapshot root (default: artifacts/universe/).",
    )
    parser.add_argument(
        "--fmp-api-key",
        default="",
        help="Optional FMP API key for the live fallback fetcher.",
    )
    parser.add_argument(
        "--min-market-cap",
        type=float,
        default=None,
        help="Optional market-cap floor for the live fallback fetcher.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write a JSON {symbols, metadata} payload to this path instead of stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        frame, metadata = load_universe_for_backtest(
            args.trade_date,
            strict=args.strict_universe,
            snapshot_root=args.snapshot_root,
            fmp_api_key=args.fmp_api_key,
            min_market_cap=args.min_market_cap,
        )
    except MissingUniverseSnapshotError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    symbols = sorted({str(s) for s in frame.get("symbol", []).tolist() if str(s).strip()})
    payload = {
        "trade_date": args.trade_date.isoformat(),
        "strict_universe": bool(args.strict_universe),
        "symbols": symbols,
        "size": len(symbols),
        "metadata": metadata,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    else:
        print(body)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
