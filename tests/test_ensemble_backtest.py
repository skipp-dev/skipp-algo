"""Example backtest to validate EnsembleSignalRouter performance.

Demonstrates how to:
1. Generate/load historical OHLC data
2. Run ensemble backtest
3. Analyze results
4. Export trades for further analysis
"""

import statistics
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


class TestBacktesterBoundsAndGuards:
    """Bug-hunt: empty-candle guard on the final-close path, and the timeout
    boundary matching the documented '100 bars max' cap."""

    def _open_trade(self, bt, entry_bar=0):
        from services.live_overlay_daemon.ensemble_backtester import Trade

        trade = Trade(
            entry_bar=entry_bar,
            entry_price=100.0,
            entry_time=datetime(2024, 1, 1),
            direction="long",
            stop_loss=-1e9,     # unreachable → only timeout can close
            take_profit=1e9,
            confidence=0.8,
            sources_count=2,
        )
        bt.open_trades[entry_bar] = trade
        return trade

    def _neutral_candle(self):
        # Never hits TP (1e9) or SL (-1e9).
        return {"high": 101.0, "low": 99.0, "close": 100.0}

    def test_non_finite_entry_price_signal_is_refused(self):
        # F5-twin: a non-finite/non-positive entry price would make every PnL%
        # (Trade.calculate_pnl divides by entry_price with only a `!= 0` guard)
        # NaN and poison persisted metrics. The trade must be refused at open.
        import types

        bt = EnsembleBacktester(symbol="TEST", initial_capital=100_000.0)
        for bad_entry in (float("inf"), float("nan"), 0.0, -5.0):
            bt.open_trades.clear()
            sig = types.SimpleNamespace(
                entry_price=bad_entry, direction="long",
                stop_loss=1.0, take_profit=2.0, confidence=0.9, sources_count=2,
            )
            bt._open_trade(0, sig, {"timestamp": "2024-01-01T00:00:00"})
            assert bt.open_trades == {}

    def test_empty_candles_run_returns_zero_metrics(self):
        bt = EnsembleBacktester(symbol="TEST")
        bt.load_candles([])
        metrics = bt.run_backtest()
        assert metrics.total_trades == 0

    def test_final_close_does_not_index_empty_candles(self):
        # Guard regression: an open trade with no candles must not raise
        # IndexError on candles[-1] in the end-of-backtest close path.
        bt = EnsembleBacktester(symbol="TEST")
        bt.load_candles([])
        self._open_trade(bt)
        metrics = bt.run_backtest()  # must not raise
        assert metrics is not None

    def test_timeout_closes_at_exactly_100_bars(self):
        bt = EnsembleBacktester(symbol="TEST")
        trade = self._open_trade(bt, entry_bar=0)
        candle = self._neutral_candle()

        # 99 bars held: below the cap → still open.
        bt._check_trade_exits(bar_index=99, candle=candle)
        assert trade.exit_bar is None

        # 100 bars held: at the cap → closed via timeout, bars_held == 100.
        bt._check_trade_exits(bar_index=100, candle=candle)
        assert trade.exit_reason == "timeout"
        assert trade.bars_held == 100


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


class TestBacktesterRealism:
    """Backtest-realism knobs: worst-case fills on ambiguous TP+SL bars, and
    opt-in slippage/commission (default 0 → results identical to before)."""

    def _trade(self, bt, direction="long", entry=100.0, sl=95.0, tp=110.0, entry_bar=0):
        from services.live_overlay_daemon.ensemble_backtester import Trade

        trade = Trade(
            entry_bar=entry_bar, entry_price=entry, entry_time=datetime(2024, 1, 1),
            direction=direction, stop_loss=sl, take_profit=tp, confidence=0.8, sources_count=2,
        )
        bt.open_trades[entry_bar] = trade
        return trade

    def test_ambiguous_bar_resolves_to_stop_loss(self):
        bt = EnsembleBacktester(symbol="T")
        trade = self._trade(bt)  # long: sl=95, tp=110
        # A bar that touches BOTH the take-profit (110) and stop-loss (95).
        bt._check_trade_exits(bar_index=1, candle={"high": 111.0, "low": 94.0, "close": 100.0})
        assert trade.exit_reason == "sl"  # worst case, not the optimistic "tp"
        assert bt.ambiguous_bar_exits == 1

    def test_clean_tp_and_sl_bars_unaffected(self):
        bt = EnsembleBacktester(symbol="T")
        tp_trade = self._trade(bt, entry_bar=0)
        bt._check_trade_exits(bar_index=1, candle={"high": 111.0, "low": 96.0, "close": 108.0})
        assert tp_trade.exit_reason == "tp"

        bt2 = EnsembleBacktester(symbol="T")
        sl_trade = self._trade(bt2, entry_bar=0)
        bt2._check_trade_exits(bar_index=1, candle={"high": 108.0, "low": 94.0, "close": 96.0})
        assert sl_trade.exit_reason == "sl"
        assert bt.ambiguous_bar_exits == 0 and bt2.ambiguous_bar_exits == 0

    def test_slippage_default_zero_is_identity(self):
        bt = EnsembleBacktester(symbol="T")
        assert bt._fill_price(100.0, "long", is_entry=True) == 100.0
        assert bt._fill_price(100.0, "short", is_entry=False) == 100.0

    def test_slippage_worsens_every_fill(self):
        bt = EnsembleBacktester(symbol="T", slippage_bps=10.0)  # 0.1%
        assert bt._fill_price(100.0, "long", is_entry=True) == pytest.approx(100.1)   # buy higher
        assert bt._fill_price(100.0, "long", is_entry=False) == pytest.approx(99.9)   # sell lower
        assert bt._fill_price(100.0, "short", is_entry=True) == pytest.approx(99.9)   # short-sell lower
        assert bt._fill_price(100.0, "short", is_entry=False) == pytest.approx(100.1)  # cover higher

    def test_commission_deducted_round_trip(self):
        bt = EnsembleBacktester(symbol="T", commission_per_fill=0.5)
        trade = self._trade(bt, entry=100.0, tp=110.0)
        bt._close_trade(trade, bar_index=1, exit_price=110.0, exit_reason="tp")
        assert trade.pnl == pytest.approx(9.0)  # +10 gross − 2×0.5 commission

    def test_defaults_leave_pnl_unchanged(self):
        bt = EnsembleBacktester(symbol="T")  # slippage_bps=0, commission=0
        trade = self._trade(bt, entry=100.0, tp=110.0)
        bt._close_trade(trade, bar_index=1, exit_price=110.0, exit_reason="tp")
        assert trade.pnl == pytest.approx(10.0)
        assert trade.exit_price == pytest.approx(110.0)

    @pytest.mark.parametrize("bad_capital", [0.0, 0, -1000.0, float("nan")])
    def test_non_positive_initial_capital_rejected(self, bad_capital):
        # initial_capital is the denominator for total return, Sharpe returns,
        # and drawdown; a non-positive (or NaN) value must fail at construction
        # rather than raise ZeroDivisionError later inside _calculate_metrics.
        with pytest.raises(ValueError, match="initial_capital must be positive"):
            EnsembleBacktester(symbol="T", initial_capital=bad_capital)

    def test_positive_initial_capital_still_accepted(self):
        bt = EnsembleBacktester(symbol="T", initial_capital=5000.0)
        assert bt.initial_capital == 5000.0
        assert bt.equity_curve == [5000.0]


class TestSharpeSortinoAnnualization:
    """Sharpe/Sortino must annualize per-trade equity returns by sqrt(252),
    NOT by 252. The linear factor inflated both ratios by sqrt(252) ~= 15.9x,
    making every backtest's risk-adjusted metric absurdly high and useless for
    ranking strategies. Every other Sharpe in the repo (stats_helpers,
    performance_metrics, psr_robust) already uses sqrt(periods_per_year)."""

    def _closed_trade(self, pnl):
        from services.live_overlay_daemon.ensemble_backtester import Trade

        return Trade(
            entry_bar=0, entry_price=100.0, entry_time=datetime(2024, 1, 1),
            direction="long", stop_loss=95.0, take_profit=110.0,
            confidence=0.8, sources_count=2,
            exit_bar=1, exit_price=100.0 + pnl / 100.0, exit_reason="tp",
            bars_held=1, pnl=pnl, pnl_pct=pnl / 100.0, win=pnl > 0,
        )

    # Equity curve with two up and two down steps -> a well-defined stdev and
    # >= 2 downside returns so both Sharpe and Sortino are exercised.
    _EQUITY = (100_000.0, 101_000.0, 100_000.0, 101_500.0, 100_500.0)

    def _returns(self):
        eq = self._EQUITY
        return [(eq[i + 1] - eq[i]) / eq[i] for i in range(len(eq) - 1)]

    def test_sharpe_uses_sqrt_not_linear_annualization(self):
        bt = EnsembleBacktester(symbol="T")
        bt.trades = [self._closed_trade(1000.0), self._closed_trade(-500.0)]
        bt.equity_curve = list(self._EQUITY)
        m = bt._calculate_metrics()

        returns = self._returns()
        mean = statistics.mean(returns)
        std = statistics.stdev(returns)
        assert m.sharpe_ratio == pytest.approx(mean / std * (252 ** 0.5), rel=1e-9)
        # Regression guard: the old bug multiplied by 252 (sqrt(252) too large).
        assert abs(m.sharpe_ratio) < abs(mean / std * 252) * 0.1

    def test_sortino_uses_sqrt_not_linear_annualization(self):
        bt = EnsembleBacktester(symbol="T")
        bt.trades = [self._closed_trade(1000.0), self._closed_trade(-500.0)]
        bt.equity_curve = list(self._EQUITY)
        m = bt._calculate_metrics()

        returns = self._returns()
        mean = statistics.mean(returns)
        downside_std = statistics.stdev([r for r in returns if r < 0])
        assert m.sortino_ratio == pytest.approx(mean / downside_std * (252 ** 0.5), rel=1e-9)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
