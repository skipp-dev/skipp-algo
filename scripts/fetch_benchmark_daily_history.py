"""Fetch a long daily-bars history workbook for the benchmark symbols.

ADR-0023 Option A (issue #3872 follow-up): the rolling export bundle carries
only ~21 trading days (``coverage_trade_days``), which is structurally too
short for 1D SMC structure detection — warmup plus label horizons (FVG=20
daily bars) exceed the frame, so the 1D slice yields zero FamilyEvents and
the governed live-1D magnitude track starves. This script fetches a LONG
daily history (default 420 trading days) for the 20 benchmark symbols only —
via the SAME guarded Databento loaders the production export uses — and
writes it as a minimal workbook with a single ``daily_bars`` sheet, the exact
shape ``smc_core.cached_workbook_reader.read_daily_bars`` expects.

Consumers (both opt-in, wired by smc-measurement-benchmark-rolling.yml):
  * the per-TF structure exporter, via ``--workbook`` for the 1D slice
    (explicit workbook without an explicit bundle root makes the workbook the
    sole daily source — see structure_batch.write_structure_artifacts_from_workbook);
  * the measurement harness, via ``SMC_DAILY_BARS_WORKBOOK_OVERRIDE`` (see
    measurement_evidence._load_source_bars), so detection AND labeling see
    the same long frame.

Cost note: ohlcv-1d for 20 symbols x ~420 trading days is a few thousand
rows — negligible next to the intraday exports this pipeline already runs.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

from databento_volatility_screener import list_recent_trading_days, load_daily_bars

DEFAULT_DATASET = "EQUS.MINI"
DEFAULT_TRADING_DAYS = 420
DEFAULT_MIN_ROWS_PER_SYMBOL = 250

_SHEET_COLUMNS = ("symbol", "trade_date", "open", "high", "low", "close", "volume")


def build_daily_bars_sheet(
    frame: pd.DataFrame,
    *,
    symbols: list[str],
    min_rows_per_symbol: int,
) -> pd.DataFrame:
    """Normalize the loader frame into the workbook ``daily_bars`` shape.

    Fails loud (``ValueError``) when a requested symbol is missing or its
    history is shorter than *min_rows_per_symbol*: a silently short 1D frame
    would recreate exactly the zero-capacity condition this script exists to
    fix, while the workflow's fail-soft wrapper degrades to the current
    (starved-but-alarmed) behaviour instead of shipping a bad workbook.
    """
    if frame is None or frame.empty:
        raise ValueError("daily bars frame is empty")
    missing_columns = [c for c in _SHEET_COLUMNS if c not in frame.columns]
    if missing_columns:
        raise ValueError(f"daily bars frame lacks columns: {missing_columns}")

    sheet = frame.loc[:, list(_SHEET_COLUMNS)].copy()
    sheet["symbol"] = sheet["symbol"].astype(str).str.strip().str.upper()
    wanted = [s.strip().upper() for s in symbols if s.strip()]
    sheet = sheet.loc[sheet["symbol"].isin(set(wanted))].copy()
    sheet = sheet.drop_duplicates(subset=["symbol", "trade_date"], keep="last")
    sheet = sheet.sort_values(["symbol", "trade_date"]).reset_index(drop=True)

    counts = sheet.groupby("symbol").size().to_dict()
    problems = []
    for symbol in wanted:
        n = int(counts.get(symbol, 0))
        if n < min_rows_per_symbol:
            problems.append(f"{symbol}={n}")
    if problems:
        raise ValueError(
            "insufficient daily history (need >= "
            f"{min_rows_per_symbol} rows/symbol): {', '.join(problems)}"
        )
    return sheet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        required=True,
        help="comma-separated benchmark symbols (uppercase tickers)",
    )
    parser.add_argument(
        "--trading-days",
        type=int,
        default=DEFAULT_TRADING_DAYS,
        help=f"trading days of history to fetch (default: {DEFAULT_TRADING_DAYS})",
    )
    parser.add_argument(
        "--dataset",
        default=(os.getenv("DATABENTO_DATASET") or "").strip() or DEFAULT_DATASET,
        help=f"Databento dataset (default: env DATABENTO_DATASET or {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--min-rows-per-symbol",
        type=int,
        default=DEFAULT_MIN_ROWS_PER_SYMBOL,
        help=(
            "reject the fetch when any requested symbol has fewer daily rows "
            f"(default: {DEFAULT_MIN_ROWS_PER_SYMBOL})"
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        help="output workbook path (.xlsx, written with a single daily_bars sheet)",
    )
    args = parser.parse_args(argv)

    api_key = (os.getenv("DATABENTO_API_KEY") or "").strip()
    if not api_key:
        print("error: DATABENTO_API_KEY is not set", file=sys.stderr)
        return 1
    symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]
    if not symbols:
        print("error: --symbols resolved to an empty list", file=sys.stderr)
        return 1

    try:
        trading_days = list_recent_trading_days(
            api_key, dataset=args.dataset, lookback_days=int(args.trading_days)
        )
        frame = load_daily_bars(
            api_key,
            dataset=args.dataset,
            trading_days=trading_days,
            universe_symbols=set(symbols),
            max_workers=1,
        )
        sheet = build_daily_bars_sheet(
            frame, symbols=symbols, min_rows_per_symbol=int(args.min_rows_per_symbol)
        )
    except Exception as exc:
        # Single fail-loud CLI boundary: the workflow wrapper converts this
        # rc=1 into a fail-soft warning and the 1D slice keeps the alarmed
        # status quo (plane_starved heartbeats + gap guard).
        print(f"error: daily history fetch failed: {exc}", file=sys.stderr)
        return 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp.xlsx")
    with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
        sheet.to_excel(writer, sheet_name="daily_bars", index=False)
    tmp.replace(output)

    per_symbol = sheet.groupby("symbol").size()
    print(
        f"benchmark daily history: {len(sheet)} rows, {per_symbol.size} symbols, "
        f"{sheet['trade_date'].min()}..{sheet['trade_date'].max()} -> {output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
