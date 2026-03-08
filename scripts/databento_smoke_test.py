from __future__ import annotations

import os
import sys
from datetime import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from databento_volatility_screener import (
    build_summary_table,
    fetch_symbol_day_detail,
    filter_supported_universe_for_databento,
    fetch_us_equity_universe,
    load_daily_bars,
    list_recent_trading_days,
    rank_top_fraction_per_day,
    run_intraday_screen,
)


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    databento_api_key = os.getenv("DATABENTO_API_KEY", "")
    fmp_api_key = os.getenv("FMP_API_KEY", "")
    if not databento_api_key:
        raise SystemExit("DATABENTO_API_KEY must be set in .env")

    dataset = "DBEQ.BASIC"
    lookback_days = 1
    min_market_cap = 200_000_000_000.0 if fmp_api_key else None
    window_start = time(16, 40)
    window_end = time(16, 45)
    premarket_anchor = time(8, 0)
    display_tz = "Europe/Berlin"

    trading_days = list_recent_trading_days(databento_api_key, dataset=dataset, lookback_days=lookback_days)
    print("TRADING_DAYS", trading_days)

    universe = fetch_us_equity_universe(fmp_api_key, min_market_cap=min_market_cap)
    universe, unsupported = filter_supported_universe_for_databento(
        databento_api_key,
        dataset=dataset,
        universe=universe,
        use_file_cache=True,
        force_refresh=True,
    )
    universe_symbols = set(universe["symbol"].dropna().astype(str).str.upper())
    print("UNIVERSE_COUNT", len(universe_symbols))
    print("UNIVERSE_SAMPLE", sorted(universe_symbols)[:10])
    print("UNSUPPORTED_SYMBOLS", unsupported)

    daily_bars = load_daily_bars(
        databento_api_key,
        dataset=dataset,
        trading_days=trading_days,
        universe_symbols=universe_symbols,
        use_file_cache=False,
        force_refresh=True,
    )
    print("DAILY_BARS_ROWS", len(daily_bars))

    intraday = run_intraday_screen(
        databento_api_key,
        dataset=dataset,
        trading_days=trading_days,
        universe_symbols=universe_symbols,
        daily_bars=daily_bars,
        display_timezone=display_tz,
        window_start=window_start,
        window_end=window_end,
        premarket_anchor_et=premarket_anchor,
        use_file_cache=False,
        force_refresh=True,
    )
    print("INTRADAY_ROWS", len(intraday))

    ranked = rank_top_fraction_per_day(intraday, ranking_metric="window_range_pct", top_fraction=0.10)
    summary = build_summary_table(ranked, universe)
    print("SUMMARY_ROWS", len(summary))
    if summary.empty:
        print("SUMMARY_EMPTY")
        return

    columns = [
        "trade_date",
        "symbol",
        "rank",
        "window_range_pct",
        "realized_vol_pct",
        "window_return_pct",
        "previous_close",
        "current_price",
    ]
    print("SUMMARY_TOP")
    print(summary[columns].head(10).to_string(index=False))

    row = summary.iloc[0]
    trade_date = pd.Timestamp(row["trade_date"]).date()
    previous_close = float(row["previous_close"]) if pd.notna(row["previous_close"]) else None
    second_detail, minute_detail = fetch_symbol_day_detail(
        databento_api_key,
        dataset=dataset,
        symbol=str(row["symbol"]),
        trade_date=trade_date,
        display_timezone=display_tz,
        window_start=window_start,
        window_end=window_end,
        premarket_anchor_et=premarket_anchor,
        previous_close=previous_close,
        use_file_cache=False,
        force_refresh=True,
    )
    print("DETAIL_SYMBOL", row["symbol"])
    print("SECOND_DETAIL_ROWS", len(second_detail))
    print("MINUTE_DETAIL_ROWS", len(minute_detail))
    if not minute_detail.empty:
        print("MINUTE_DETAIL_TOP")
        print(minute_detail.head(10).to_string(index=False))


if __name__ == "__main__":
    main()