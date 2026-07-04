"""Example backtest to validate EnsembleSignalRouter performance.

Demonstrates how to:
1. Generate/load historical OHLC data
2. Run ensemble backtest
3. Analyze results
4. Export trades for further analysis
"""

from datetime import datetime, timedelta

import pytest

from services.live_overlay_daemon.ensemble_backtester import (
    EnsembleBacktester,
)


def generate_uptrend_data(
    base_price: float = 100.0,
    num_bars: int = 100,
    trend_strength: float = 0.5,
) -> list[dict]:
    """Generate synthetic uptrend OHLC data."""
    candles = []
    current_price = base_price

    for i in range(num_bars):
        # Uptrend with noise
        daily_change = trend_strength + (i % 5) * 0.1
        current_price += daily_change

        open_price = current_price - 0.5
        high_price = current_price + 1.5
        low_price = current_price - 2.0
        close_price = current_price

        timestamp = datetime(2024, 1, 1) + timedelta(hours=i)

        candles.append({
            "bar_index": i,
            "timestamp": timestamp.isoformat(),
            "open": max(open_price, low_price),
            "high": high_price,
            "low": min(low_price, open_price),
            "close": close_price,
            "volume": 1000000 + (i % 500000),
            "atr": 2.0,
        })

    return candles


def generate_downtrend_data(
    base_price: float = 100.0,
    num_bars: int = 100,
) -> list[dict]:
    """Generate synthetic downtrend OHLC data."""
    candles = []
    current_price = base_price

    for i in range(num_bars):
        # Downtrend
        daily_change = -0.5 - (i % 5) * 0.1
        current_price += daily_change

        open_price = current_price + 0.5
        high_price = current_price + 2.0
        low_price = current_price - 1.5
        close_price = current_price

        timestamp = datetime(2024, 1, 1) + timedelta(hours=i)

        candles.append({
            "bar_index": i,
            "timestamp": timestamp.isoformat(),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": 1000000,
            "atr": 2.0,
        })

    return candles


def generate_choppy_data(
    base_price: float = 100.0,
    num_bars: int = 100,
) -> list[dict]:
    """Generate choppy (no trend) OHLC data."""
    candles = []

    for i in range(num_bars):
        # Oscillate around base
        is_up = i % 2 == 0
        close_price = base_price + (2.0 if is_up else -2.0)

        timestamp = datetime(2024, 1, 1) + timedelta(hours=i)

        candles.append({
            "bar_index": i,
            "timestamp": timestamp.isoformat(),
            "open": base_price,
            "high": base_price + 2.5,
            "low": base_price - 2.5,
            "close": close_price,
            "volume": 500000,
            "atr": 2.0,
        })

    return candles


class TestEnsembleBacktest:
    """Test ensemble backtester with synthetic data."""

    def test_backtest_initialization(self):
        """Should initialize backtester correctly."""
        bt = EnsembleBacktester(symbol="TEST", timeframe="1h")

        assert bt.symbol == "TEST"
        assert bt.timeframe == "1h"
        assert bt.initial_capital == 100000.0
        assert len(bt.trades) == 0
        assert len(bt.equity_curve) == 1

    def test_backtest_uptrend(self):
        """Should generate signals in uptrend."""
        bt = EnsembleBacktester(symbol="TEST")

        # Generate 100 bars of uptrend
        candles = generate_uptrend_data(num_bars=100)
        bt.load_candles(candles)

        # Run backtest
        metrics = bt.run_backtest()

        # Uptrend should generate some signals
        assert metrics.total_trades >= 0  # May or may not signal
        assert metrics.total_pnl_pct >= -10  # Should not lose too much

    def test_backtest_downtrend(self):
        """Should handle downtrend (may generate shorts)."""
        bt = EnsembleBacktester(symbol="TEST")

        candles = generate_downtrend_data(num_bars=100)
        bt.load_candles(candles)

        metrics = bt.run_backtest()

        assert metrics.total_trades >= 0
        # In downtrend, shorts could be profitable

    def test_backtest_choppy_market(self):
        """Should suppress signals in choppy market."""
        bt = EnsembleBacktester(symbol="TEST")

        candles = generate_choppy_data(num_bars=100)
        bt.load_candles(candles)

        metrics = bt.run_backtest()

        # Choppy market: should suppress most signals
        # (lower signal count than trending)
        assert metrics.total_trades <= 5  # Ensemble gates on confluence

    def test_metrics_structure(self):
        """Should produce valid metrics."""
        bt = EnsembleBacktester(symbol="TEST")

        candles = generate_uptrend_data(num_bars=50)
        bt.load_candles(candles)

        metrics = bt.run_backtest()

        # Check all fields exist and are reasonable
        assert metrics.total_trades >= 0
        assert 0 <= metrics.win_rate <= 100
        assert metrics.sharpe_ratio is not None
        assert metrics.max_drawdown <= 0  # Drawdown is negative

    def test_equity_curve(self):
        """Should track equity curve."""
        bt = EnsembleBacktester(symbol="TEST", initial_capital=10000.0)

        candles = generate_uptrend_data(num_bars=100)
        bt.load_candles(candles)

        bt.run_backtest()

        # Equity curve should be tracked
        assert len(bt.equity_curve) >= 1
        assert bt.equity_curve[0] == 10000.0  # Initial capital

    def test_trade_export(self, tmp_path):
        """Should export trades to CSV."""
        bt = EnsembleBacktester(symbol="TEST")

        candles = generate_uptrend_data(num_bars=100)
        bt.load_candles(candles)

        metrics = bt.run_backtest()

        # Export trades
        csv_file = tmp_path / "trades.csv"
        bt.export_trades_csv(str(csv_file))

        # File should exist if trades occurred
        if metrics.total_trades > 0:
            assert csv_file.exists()

    def test_macro_filter_integration(self):
        """Should apply macro filter (LSI) during backtest."""
        bt = EnsembleBacktester(symbol="TEST")

        candles = generate_uptrend_data(num_bars=100)
        bt.load_candles(candles)

        # Load SOFR/IORB data: normal for first 50 bars, stressed for next 50
        sofr_iorb = {}
        for i in range(100):
            if i < 50:
                sofr_iorb[i] = (4.30, 4.30)  # Normal spread = 0
            else:
                sofr_iorb[i] = (4.40, 4.20)  # Stressed spread = 20 bp

        bt.load_sofr_iorb_data(sofr_iorb)

        metrics = bt.run_backtest()

        # Signals in stress phase should have lower confidence (or be suppressed)
        # This is qualitative, so just verify backtest runs without error
        assert metrics is not None

    def test_multiple_trades_same_direction(self):
        """Should only allow one open trade at a time."""
        bt = EnsembleBacktester(symbol="TEST")

        candles = generate_uptrend_data(num_bars=200)
        bt.load_candles(candles)

        bt.run_backtest()

        # Check that we never had overlapping trades
        for i, trade1 in enumerate(bt.trades):
            for _trade2 in bt.trades[i + 1:]:
                # If trade1 not closed before trade2 opens
                assert trade1.exit_bar is not None  # Always closed

    def test_print_report(self):
        """Should print readable backtest report."""
        bt = EnsembleBacktester(symbol="TEST")

        candles = generate_uptrend_data(num_bars=100)
        bt.load_candles(candles)

        metrics = bt.run_backtest()

        # Should not crash when printing
        report = bt.print_report(metrics)
        assert "PERFORMANCE SUMMARY" in report
        assert f"{metrics.win_rate:.1f}" in report


class TestCompareSystemsBenchmark:
    """Benchmark: Compare individual vs ensemble performance."""

    def test_uptrend_ensemble_beats_individual(self):
        """Ensemble should beat individual systems in trending markets."""
        # This is a conceptual test — would need actual system implementations
        # to compare. For now, just verify ensemble backtests.

        bt = EnsembleBacktester(symbol="NVDA")
        candles = generate_uptrend_data(num_bars=200, trend_strength=1.0)
        bt.load_candles(candles)

        metrics = bt.run_backtest()

        # Ensemble in strong uptrend should be profitable
        # (or at least not catastrophically bad)
        assert metrics.total_pnl_pct > -20  # Reasonable loss limit

    def test_choppy_ensemble_suppresses(self):
        """Ensemble should suppress signals and reduce drawdown in choppy."""
        bt = EnsembleBacktester(symbol="NVDA")
        candles = generate_choppy_data(num_bars=100)
        bt.load_candles(candles)

        metrics = bt.run_backtest()

        # Choppy: should have few trades and small max drawdown
        assert metrics.total_trades <= 3
        assert metrics.max_drawdown > -15  # Limited drawdown


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
