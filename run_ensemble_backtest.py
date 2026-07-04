#!/usr/bin/env python3
"""
Complete Ensemble Backtest Runner

Fetches real data from FMP, runs ensemble backtest, analyzes results.

Usage:
    export FMP_API_KEY="your-api-key"
    python run_ensemble_backtest.py --symbol NVDA --days 180 --timeframe 1hour
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from services.live_overlay_daemon.fmp_data_loader import FMPDataLoader
from services.live_overlay_daemon.ensemble_backtester import EnsembleBacktester, BacktestMetrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def run_backtest(
    symbol: str = "NVDA",
    days: int = 180,
    timeframe: str = "1hour",
    output_dir: str = "./backtest_results",
    smt_quality_threshold: float = 70.0,
    impulse_propulsion_threshold: float = 6.0,
    minimum_sources: int = 2,
    enable_volatility_filter: bool = True,
    warmup_bars: int = 0,
    eval_last_bars: Optional[int] = None,
) -> dict:
    """Run complete ensemble backtest pipeline.

    Args:
        symbol: Stock symbol (e.g., "NVDA")
        days: How many days of historical data
        timeframe: "1min", "5min", "15min", "30min", "1hour", "daily"
        output_dir: Where to save results
        smt_quality_threshold: SMT quality gate (60-70)
        impulse_propulsion_threshold: Impulse propulsion gate (5.5-6.5)
        minimum_sources: Minimum systems for signal (1-3)
        enable_volatility_filter: Enable ATR-based volatility filter (default True)
        warmup_bars: Initial bars that only warm up system state (no entries)
        eval_last_bars: If set, evaluate only the last N bars — warmup_bars is
            derived as max(0, total_candles - N), overriding warmup_bars

    Returns: Results dict with metrics and metadata
    """
    # Create output directory
    Path(output_dir).mkdir(exist_ok=True)

    print("\n" + "=" * 80)
    print("ENSEMBLE BACKTEST RUNNER")
    print("=" * 80)

    # Step 1: Load data from FMP
    print(f"\n[1/5] Loading data from FMP...")
    try:
        loader = FMPDataLoader()
    except ValueError as e:
        print(f"❌ ERROR: {e}")
        print("   Set FMP_API_KEY environment variable")
        sys.exit(1)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    print(f"    Symbol: {symbol}")
    print(f"    Period: {start_date} to {end_date}")
    print(f"    Timeframe: {timeframe}")

    try:
        candles = loader.get_historical_price(
            symbol=symbol,
            period=timeframe,
            from_date=start_date,
            to_date=end_date,
            limit=5000,
        )
    except Exception as e:
        print(f"❌ Failed to fetch data: {e}")
        sys.exit(1)

    if not candles:
        print(f"❌ No data returned for {symbol}")
        sys.exit(1)

    print(f"✅ Loaded {len(candles)} candles")

    # Step 2: Load macro data
    print(f"\n[2/5] Loading macro data (SOFR/IORB)...")
    try:
        sofr_iorb_map = loader.get_sofr_iorb_spread(from_date=start_date)
        macro_candles = loader.map_macro_to_candles(candles, sofr_iorb_map)
        print(f"✅ Mapped to {len(macro_candles)} candles with macro data")
    except Exception as e:
        logger.warning(f"Could not load macro data: {e}")
        macro_candles = {}
        sofr_iorb_map = {}
        print(f"⚠️  Proceeding without macro data")

    # Step 3: Run backtest
    print(f"\n[3/5] Running ensemble backtest...")
    if eval_last_bars is not None:
        warmup_bars = max(0, len(candles) - int(eval_last_bars))
    if warmup_bars:
        print(f"    Warm-up: first {warmup_bars} bars (no entries)")
    bt = EnsembleBacktester(
        symbol=symbol,
        timeframe=timeframe,
        initial_capital=100_000,
        risk_per_trade=0.02,
        smt_quality_threshold=smt_quality_threshold,
        impulse_propulsion_threshold=impulse_propulsion_threshold,
        minimum_sources=minimum_sources,
        enable_volatility_filter=enable_volatility_filter,
        warmup_bars=warmup_bars,
    )

    bt.load_candles(candles)
    if macro_candles:
        bt.load_sofr_iorb_data(macro_candles)

    metrics = bt.run_backtest()
    print(f"✅ Backtest complete: {metrics.total_trades} trades")

    # Step 4: Export results
    print(f"\n[4/5] Exporting results...")

    # Save metrics
    metrics_file = Path(output_dir) / f"{symbol}_{timeframe}_metrics.json"
    with open(metrics_file, "w", encoding="utf-8") as f:
        json.dump(metrics.to_dict(), f, indent=2)
    print(f"   Metrics: {metrics_file}")

    # Save trades
    trades_file = Path(output_dir) / f"{symbol}_{timeframe}_trades.csv"
    bt.export_trades_csv(str(trades_file))
    print(f"   Trades: {trades_file}")

    # Save report
    report_file = Path(output_dir) / f"{symbol}_{timeframe}_report.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(bt.print_report(metrics))
    print(f"   Report: {report_file}")

    # Step 5: Print summary
    print(f"\n[5/5] Summary:")
    bt.print_report(metrics)

    # Decision
    print("\n" + "=" * 80)
    print("VALIDATION DECISION")
    print("=" * 80)

    go_live = (
        metrics.win_rate > 55 and
        metrics.sharpe_ratio > 1.3 and
        metrics.max_drawdown > -25  # More than -25%
    )

    if go_live:
        print(f"\n✅ PASS — Metrics acceptable for paper trading")
        print(f"   Win Rate: {metrics.win_rate:.1f}% ✅")
        print(f"   Sharpe:   {metrics.sharpe_ratio:.2f} ✅")
        print(f"   Max DD:   {metrics.max_drawdown:.1f}% ✅")
    else:
        print(f"\n⚠️  NEEDS WORK — Consider optimizing:")
        if metrics.win_rate <= 55:
            print(f"   Win Rate: {metrics.win_rate:.1f}% (target > 55%)")
        if metrics.sharpe_ratio <= 1.3:
            print(f"   Sharpe:   {metrics.sharpe_ratio:.2f} (target > 1.3)")
        if metrics.max_drawdown <= -25:
            print(f"   Max DD:   {metrics.max_drawdown:.1f}% (target > -25%)")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "total_candles": len(candles),
        "warmup_bars": warmup_bars,
        "metrics": metrics.to_dict(),
        "go_live": go_live,
        "output_dir": output_dir,
    }


def run_multi_symbol_backtest(symbols: list[str] = None, days: int = 180):
    """Run backtest for multiple symbols and compare."""
    if symbols is None:
        symbols = ["NVDA", "AAPL", "MSFT", "SPY", "QQQ"]

    print("\n" + "=" * 80)
    print("MULTI-SYMBOL ENSEMBLE BACKTEST")
    print("=" * 80)

    results = {}
    for symbol in symbols:
        print(f"\n{'='*80}")
        print(f"Testing {symbol}...")
        print(f"{'='*80}")

        try:
            result = run_backtest(
                symbol=symbol,
                days=days,
                timeframe="1hour",
                output_dir=f"./backtest_results/{symbol.lower()}",
            )
            results[symbol] = result
        except Exception as e:
            print(f"❌ Error testing {symbol}: {e}")
            results[symbol] = {"error": str(e)}

    # Summary comparison
    print("\n" + "=" * 80)
    print("COMPARISON ACROSS SYMBOLS")
    print("=" * 80)

    print(f"\n{'Symbol':<10} {'Trades':<10} {'Win%':<10} {'Sharpe':<10} {'PnL%':<10} {'Status':<15}")
    print("-" * 80)

    for symbol, result in results.items():
        if "error" in result:
            print(f"{symbol:<10} {'ERROR':<10} {'-':<10} {'-':<10} {'-':<10} {'FAILED':<15}")
        else:
            metrics = result["metrics"]
            status = "✅ GO LIVE" if result["go_live"] else "⚠️  NEEDS WORK"
            print(
                f"{symbol:<10} "
                f"{metrics['total_trades']:<10.0f} "
                f"{metrics['win_rate']:<10.1f} "
                f"{metrics['sharpe_ratio']:<10.2f} "
                f"{metrics['total_pnl_pct']:<10.2f} "
                f"{status:<15}"
            )

    print("\n" + "=" * 80)
    print("Results saved to ./backtest_results/")
    print("=" * 80)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ensemble Trading System Backtest Runner"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="NVDA",
        help="Stock symbol (e.g., NVDA, AAPL)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=180,
        help="Days of historical data",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1hour",
        choices=["1min", "5min", "15min", "30min", "1hour", "4hour", "daily"],
        help="Candle timeframe",
    )
    parser.add_argument(
        "--multi",
        action="store_true",
        help="Run backtest for multiple symbols",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./backtest_results",
        help="Output directory for results",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="FMP API key (or use FMP_API_KEY env var)",
    )

    args = parser.parse_args()

    # Set API key if provided
    if args.api_key:
        os.environ["FMP_API_KEY"] = args.api_key

    if args.multi:
        results = run_multi_symbol_backtest(days=args.days)
    else:
        result = run_backtest(
            symbol=args.symbol,
            days=args.days,
            timeframe=args.timeframe,
            output_dir=args.output,
        )
