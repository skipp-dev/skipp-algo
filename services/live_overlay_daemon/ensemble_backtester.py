"""Ensemble Signal Backtester — Validate all 4 systems before live integration.

Loads historical OHLC data, runs through EnsembleSignalRouter,
calculates performance metrics (win rate, Sharpe, drawdown, etc.).

Usage:
    backtester = EnsembleBacktester(symbol='NVDA', timeframe='1h')
    results = backtester.run_backtest(
        start_date='2024-01-01',
        end_date='2024-06-30',
        sofr_iorb_file='sofr_iorb_historical.csv'
    )
    backtester.print_report(results)
"""

from __future__ import annotations

import dataclasses
import logging
import statistics
from dataclasses import dataclass
from datetime import datetime

from services.live_overlay_daemon.ensemble_signal_router import (
    EnsembleSignal,
    EnsembleSignalRouter,
)

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Single trade execution."""

    entry_bar: int
    entry_price: float
    entry_time: datetime
    direction: str  # 'long' | 'short'
    stop_loss: float
    take_profit: float
    confidence: float
    sources_count: int

    # Exit (filled during backtest)
    exit_bar: int | None = None
    exit_price: float | None = None
    exit_time: datetime | None = None
    exit_reason: str | None = None  # 'tp' | 'sl' | 'timeout' | 'no_exit'

    # P&L
    pnl: float | None = None
    pnl_pct: float | None = None
    bars_held: int | None = None
    win: bool | None = None

    def is_closed(self) -> bool:
        """True if trade has been exited."""
        return self.exit_bar is not None

    def calculate_pnl(self, exit_price: float) -> tuple[float, float]:
        """Calculate P&L in absolute and percentage."""
        if self.direction == "long":
            pnl = exit_price - self.entry_price
        else:
            pnl = self.entry_price - exit_price

        pnl_pct = (pnl / self.entry_price) * 100 if self.entry_price != 0 else 0
        return pnl, pnl_pct


@dataclass
class BacktestMetrics:
    """Complete performance metrics."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float  # %
    avg_win: float  # %
    avg_loss: float  # %
    profit_factor: float  # Gross profit / Gross loss
    largest_win: float  # %
    largest_loss: float  # %

    total_pnl: float  # $
    total_pnl_pct: float  # %

    # Risk metrics
    max_drawdown: float  # %
    max_drawdown_bar_range: tuple[int, int]  # (from_bar, to_bar)

    sharpe_ratio: float  # Risk-adjusted return
    sortino_ratio: float  # Downside risk only
    calmar_ratio: float  # Return / Max drawdown

    # Time metrics
    avg_bars_held: float
    min_bars_held: int
    max_bars_held: int

    # System metrics
    avg_confidence: float  # 0-1
    avg_sources_count: float  # How many systems voted

    # Signal breakdown
    signals_by_source: dict[str, int]  # Count by source

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return dataclasses.asdict(self)


class EnsembleBacktester:
    """Backtester for EnsembleSignalRouter."""

    def __init__(
        self,
        symbol: str = "NVDA",
        timeframe: str = "1h",
        initial_capital: float = 100000.0,
        risk_per_trade: float = 0.02,  # 2% of capital
        smt_quality_threshold: float = 70.0,
        impulse_propulsion_threshold: float = 6.0,
        minimum_sources: int = 2,
        enable_volatility_filter: bool = True,
        warmup_bars: int = 0,
        slippage_bps: float = 0.0,
        commission_per_fill: float = 0.0,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        # initial_capital is the denominator for total return, per-bar equity
        # returns (Sharpe), and drawdown; a non-positive value makes all three
        # divide by zero. Reject at construction rather than crash later in
        # _calculate_metrics on an already-completed backtest.
        if not initial_capital > 0:
            raise ValueError(f"initial_capital must be positive, got {initial_capital}")
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        # Backtest-realism knobs (default 0 → results identical to before, so
        # existing baselines are unchanged; opt in to model real fills).
        #   slippage_bps: per-fill adverse price move in basis points of price
        #     (worsens both entry and exit).
        #   commission_per_fill: fixed cost deducted per fill (2× per round-trip).
        self.slippage_bps = max(0.0, float(slippage_bps))
        self.commission_per_fill = max(0.0, float(commission_per_fill))
        # Count of trades that exited on a bar where BOTH take-profit and
        # stop-loss were touched — OHLC can't resolve intrabar order, so we
        # assume the worst case (SL first). Surfaced so an inflated win rate
        # driven by many ambiguous bars is not silently hidden.
        self.ambiguous_bar_exits = 0
        # Bars at the start of the series during which the ensemble systems
        # warm up (candles are processed, state accumulates) but entry
        # signals are discarded. Makes results independent of cold-start
        # indicator state at the evaluation window's first bar.
        self.warmup_bars = max(int(warmup_bars), 0)

        self.router = EnsembleSignalRouter(
            smt_quality_threshold=smt_quality_threshold,
            impulse_propulsion_threshold=impulse_propulsion_threshold,
            minimum_sources=minimum_sources,
            enable_volatility_filter=enable_volatility_filter,
        )
        self.trades: list[Trade] = []
        self.open_trades: dict[int, Trade] = {}  # bar_index -> Trade

        # Historical data
        self.candles: list[dict] = []
        self.sofr_iorb_map: dict[int, tuple[float, float]] = {}  # bar_index -> (sofr, iorb)

        # Performance tracking
        self.equity_curve: list[float] = [initial_capital]
        self.drawdown_curve: list[float] = [0.0]

    def load_candles(self, candles: list[dict]) -> None:
        """Load historical OHLC data.

        Expected format:
        [
            {"bar_index": 0, "timestamp": "2024-01-01T00:00:00",
             "open": 100.0, "high": 102.0, "low": 98.0, "close": 101.0,
             "volume": 1000000},
            ...
        ]
        """
        self.candles = candles
        logger.info("[Backtest] Loaded %s candles for %s", len(candles), self.symbol)

    def load_sofr_iorb_data(self, data: dict[int, tuple[float, float]]) -> None:
        """Load SOFR/IORB spread data.

        Format: {bar_index: (sofr_rate, iorb_rate), ...}
        """
        self.sofr_iorb_map = data
        logger.info("[Backtest] Loaded SOFR/IORB data for %s bars", len(data))

    def run_backtest(self) -> BacktestMetrics:
        """Run complete backtest through all candles."""
        logger.info(
            "[Backtest] Starting: %s %s, "
            "%s bars, "
            "risk=%.1f%%",
            self.symbol,
            self.timeframe,
            len(self.candles),
            self.risk_per_trade * 100,
        )

        for i, candle in enumerate(self.candles):
            # Process candle
            signal = self._process_candle(candle)

            # Handle open trades (check for exits)
            self._check_trade_exits(i, candle)

            # Handle new signals (open trades); warm-up bars only build
            # system state and never open positions
            if signal and i >= self.warmup_bars:
                self._open_trade(i, signal, candle)

        # Close any remaining open trades at final price. Guard candles too:
        # the `open_trades` check alone would still index candles[-1] on an
        # empty series (IndexError) if a trade were ever open without candles.
        if self.open_trades and self.candles:
            final_candle = self.candles[-1]
            for trade in list(self.open_trades.values()):
                self._close_trade(
                    trade,
                    bar_index=len(self.candles) - 1,
                    exit_price=final_candle["close"],
                    exit_reason="backtest_end",
                )

        # Calculate metrics
        metrics = self._calculate_metrics()

        logger.info(
            "[Backtest] Complete: %s trades, "
            "Win Rate: %.1f%%, "
            "Sharpe: %.2f, "
            "Max DD: %.1f%%",
            metrics.total_trades,
            metrics.win_rate,
            metrics.sharpe_ratio,
            metrics.max_drawdown,
        )

        if self.ambiguous_bar_exits > 0:
            total = max(1, metrics.total_trades)
            logger.warning(
                "[Backtest] %s/%s trades (%.1f%%) exited on bars where BOTH TP "
                "and SL were touched — resolved worst-case (SL first); true "
                "results depend on unavailable intrabar sequencing.",
                self.ambiguous_bar_exits,
                metrics.total_trades,
                100.0 * self.ambiguous_bar_exits / total,
            )

        return metrics

    def _process_candle(self, candle: dict) -> EnsembleSignal | None:
        """Process single candle through ensemble."""
        bar_index = candle["bar_index"]

        # Get SOFR/IORB if available
        sofr, iorb = None, None
        if bar_index in self.sofr_iorb_map:
            sofr, iorb = self.sofr_iorb_map[bar_index]

        # Calculate ATR (simple: high-low)
        atr = candle.get("atr", (candle["high"] - candle["low"]) * 1.5)

        # Run ensemble
        signal = self.router.process_candle(
            bar_index=bar_index,
            open=candle["open"],
            high=candle["high"],
            low=candle["low"],
            close=candle["close"],
            atr=atr,
            volume=candle.get("volume", 1000000),
            htf_bias="neutral",  # No HTF data in backtest
            sofr_rate=sofr,
            iorb_rate=iorb,
        )

        return signal

    def _fill_price(self, price: float, direction: str, *, is_entry: bool) -> float:
        """Apply adverse slippage (bps of price) to a fill price.

        Default ``slippage_bps == 0`` returns the price unchanged. Otherwise the
        fill is always worse than the trigger: entries fill higher for longs /
        lower for shorts, exits fill lower for longs / higher for shorts.
        """
        if self.slippage_bps <= 0:
            return price
        factor = self.slippage_bps / 10_000.0
        long_side = direction == "long"
        worse_up = (is_entry and long_side) or (not is_entry and not long_side)
        return price * (1.0 + factor) if worse_up else price * (1.0 - factor)

    def _open_trade(self, bar_index: int, signal: EnsembleSignal, candle: dict) -> None:
        """Open new trade from signal."""
        # Skip if already have open trade (one at a time)
        if self.open_trades:
            return

        # Create trade
        trade = Trade(
            entry_bar=bar_index,
            entry_price=self._fill_price(signal.entry_price, signal.direction, is_entry=True),
            entry_time=datetime.fromisoformat(candle.get("timestamp", "2024-01-01T00:00:00")),
            direction=signal.direction,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            confidence=signal.confidence,
            sources_count=signal.sources_count,
        )

        self.open_trades[bar_index] = trade
        logger.debug(
            "[Trade] OPEN %s @ bar %s: "
            "entry=%.2f, sl=%.2f, "
            "tp=%.2f, conf=%.2f",
            signal.direction.upper(),
            bar_index,
            signal.entry_price,
            signal.stop_loss,
            signal.take_profit,
            signal.confidence,
        )

    def _check_trade_exits(self, bar_index: int, candle: dict) -> None:
        """Check if any open trades should be closed."""
        for trade in list(self.open_trades.values()):
            exit_reason = None
            exit_price = None

            tp_hit = (
                (trade.direction == "long" and candle["high"] >= trade.take_profit)
                or (trade.direction == "short" and candle["low"] <= trade.take_profit)
            )
            sl_hit = (
                (trade.direction == "long" and candle["low"] <= trade.stop_loss)
                or (trade.direction == "short" and candle["high"] >= trade.stop_loss)
            )

            if tp_hit and sl_hit:
                # Both levels touched in the same bar. OHLC cannot tell which
                # came first, so the optimistic "TP first" assumption would
                # systematically inflate results. Assume the worst case (SL
                # first) and count the ambiguity so it stays visible.
                self.ambiguous_bar_exits += 1
                exit_price = trade.stop_loss
                exit_reason = "sl"
            elif tp_hit:
                exit_price = trade.take_profit
                exit_reason = "tp"
            elif sl_hit:
                exit_price = trade.stop_loss
                exit_reason = "sl"
            # Check timeout (100 bars max). `>= 100` closes at exactly 100 bars
            # held; `> 100` kept the trade open for 101 bars, contradicting the
            # documented cap.
            elif bar_index - trade.entry_bar >= 100:
                exit_price = candle["close"]
                exit_reason = "timeout"

            if exit_reason:
                self._close_trade(trade, bar_index, exit_price, exit_reason)

    def _close_trade(
        self,
        trade: Trade,
        bar_index: int,
        exit_price: float,
        exit_reason: str,
    ) -> None:
        """Close trade and record P&L."""
        fill_price = self._fill_price(exit_price, trade.direction, is_entry=False)
        pnl, pnl_pct = trade.calculate_pnl(fill_price)
        # Round-trip commission: one fill on entry, one on exit.
        if self.commission_per_fill > 0:
            pnl -= 2.0 * self.commission_per_fill
            pnl_pct = (pnl / trade.entry_price) * 100 if trade.entry_price != 0 else 0.0

        trade.exit_bar = bar_index
        trade.exit_price = fill_price
        trade.exit_reason = exit_reason
        trade.bars_held = bar_index - trade.entry_bar
        trade.pnl = pnl
        trade.pnl_pct = pnl_pct
        trade.win = pnl > 0

        self.trades.append(trade)
        if trade.entry_bar in self.open_trades:
            del self.open_trades[trade.entry_bar]

        logger.debug(
            "[Trade] CLOSE %s @ bar %s: "
            "exit=%.2f, PnL=%+.2f%%, reason=%s",
            trade.direction.upper(),
            bar_index,
            exit_price,
            pnl_pct,
            exit_reason,
        )

        # Update equity
        current_equity = self.equity_curve[-1]
        new_equity = current_equity + pnl
        self.equity_curve.append(new_equity)

    def _calculate_metrics(self) -> BacktestMetrics:
        """Calculate all performance metrics."""
        if not self.trades:
            return BacktestMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                profit_factor=0.0,
                largest_win=0.0,
                largest_loss=0.0,
                total_pnl=0.0,
                total_pnl_pct=0.0,
                max_drawdown=0.0,
                max_drawdown_bar_range=(0, 0),
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                calmar_ratio=0.0,
                avg_bars_held=0.0,
                min_bars_held=0,
                max_bars_held=0,
                avg_confidence=0.0,
                avg_sources_count=0.0,
                signals_by_source={},
            )

        # Basic stats
        wins = [t for t in self.trades if t.win]
        losses = [t for t in self.trades if not t.win]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / len(self.trades)) * 100 if self.trades else 0

        # P&L stats
        win_pcts = [t.pnl_pct for t in wins] if wins else [0]
        loss_pcts = [t.pnl_pct for t in losses] if losses else [0]

        avg_win = statistics.mean(win_pcts) if wins else 0
        avg_loss = statistics.mean(loss_pcts) if losses else 0

        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.01

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        largest_win = max(win_pcts) if wins else 0
        largest_loss = min(loss_pcts) if losses else 0

        total_pnl = sum(t.pnl for t in self.trades)
        total_pnl_pct = (total_pnl / self.initial_capital) * 100

        # Drawdown
        max_dd, dd_range = self._calculate_max_drawdown()

        # Sharpe / Sortino: annualize by sqrt(periods), not periods (a Sharpe ratio scales with the sqrt of the horizon).
        returns = [
            (self.equity_curve[i + 1] - self.equity_curve[i]) / self.equity_curve[i]
            for i in range(len(self.equity_curve) - 1)
        ]

        if returns:
            mean_return = statistics.mean(returns)
            std_return = statistics.stdev(returns) if len(returns) > 1 else 0.01
            sharpe = (mean_return / std_return * (252 ** 0.5)) if std_return > 0 else 0
        else:
            sharpe = 0

        # Sortino (downside only)
        downside_returns = [r for r in returns if r < 0]
        if downside_returns and len(downside_returns) > 1:
            downside_std = statistics.stdev(downside_returns)
            sortino = (mean_return / downside_std * (252 ** 0.5)) if downside_std > 0 else 0
        else:
            sortino = 0

        # Calmar
        if abs(max_dd) > 0:
            calmar = total_pnl_pct / abs(max_dd)
        else:
            calmar = 0

        # Time stats
        bars_held = [t.bars_held for t in self.trades if t.bars_held]
        avg_bars = statistics.mean(bars_held) if bars_held else 0
        min_bars = min(bars_held) if bars_held else 0
        max_bars = max(bars_held) if bars_held else 0

        # Confidence
        avg_conf = statistics.mean([t.confidence for t in self.trades])
        avg_sources = statistics.mean([t.sources_count for t in self.trades])

        # Signal breakdown
        signals_by_source = {}
        for trade in self.trades:
            key = "multiple" if trade.sources_count > 1 else "single"
            signals_by_source[key] = signals_by_source.get(key, 0) + 1

        return BacktestMetrics(
            total_trades=len(self.trades),
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            largest_win=largest_win,
            largest_loss=largest_loss,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            max_drawdown=max_dd,
            max_drawdown_bar_range=dd_range,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            avg_bars_held=avg_bars,
            min_bars_held=min_bars,
            max_bars_held=max_bars,
            avg_confidence=avg_conf,
            avg_sources_count=avg_sources,
            signals_by_source=signals_by_source,
        )

    def _calculate_max_drawdown(self) -> tuple[float, tuple[int, int]]:
        """Calculate maximum drawdown and when it occurred."""
        if not self.equity_curve or len(self.equity_curve) < 2:
            return 0.0, (0, 0)

        max_equity = self.equity_curve[0]
        max_dd = 0.0
        max_dd_from = 0
        max_dd_to = 0

        for i, equity in enumerate(self.equity_curve):
            if equity > max_equity:
                max_equity = equity

            dd = (equity - max_equity) / max_equity if max_equity > 0 else 0

            if dd < max_dd:
                max_dd = dd
                max_dd_to = i
                max_dd_from = i  # Would need more tracking for precise from

        return max_dd * 100, (max_dd_from, max_dd_to)

    def print_report(self, metrics: BacktestMetrics) -> str:
        """Print human-readable backtest report."""
        report = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ENSEMBLE BACKTEST REPORT                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

📊 PERFORMANCE SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Total P&L ............................ {metrics.total_pnl:>+.2f} $ ({metrics.total_pnl_pct:>+.2f}%)
  Total Trades ......................... {metrics.total_trades:>5} trades
  Win Rate ............................. {metrics.win_rate:>6.1f}%
  Winning Trades ....................... {metrics.winning_trades:>5}
  Losing Trades ........................ {metrics.losing_trades:>5}

📈 PROFITABILITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Avg Win / Trade ....................... {metrics.avg_win:>+6.2f}%
  Avg Loss / Trade ...................... {metrics.avg_loss:>+6.2f}%
  Largest Win ........................... {metrics.largest_win:>+6.2f}%
  Largest Loss .......................... {metrics.largest_loss:>+6.2f}%
  Profit Factor ......................... {metrics.profit_factor:>6.2f}x

🎯 RISK METRICS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Max Drawdown .......................... {metrics.max_drawdown:>-6.2f}%
  Sharpe Ratio .......................... {metrics.sharpe_ratio:>6.2f}
  Sortino Ratio ......................... {metrics.sortino_ratio:>6.2f}
  Calmar Ratio .......................... {metrics.calmar_ratio:>6.2f}

⏱️  TRADE DURATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Avg Bars Held ......................... {metrics.avg_bars_held:>6.1f} bars
  Min / Max ............................. {metrics.min_bars_held:>5} / {metrics.max_bars_held:<5} bars

🤖 ENSEMBLE QUALITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Avg Confidence ........................ {metrics.avg_confidence:>6.2f}
  Avg System Agreement .................. {metrics.avg_sources_count:>6.1f} systems/signal
  Single System Signals ................. {metrics.signals_by_source.get('single', 0):>5}
  Multi System Signals .................. {metrics.signals_by_source.get('multiple', 0):>5}

╔══════════════════════════════════════════════════════════════════════════════╗
"""
        print(report)
        return report

    def export_trades_csv(self, filepath: str) -> None:
        """Export all trades to CSV for further analysis."""
        import csv

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "entry_bar",
                    "entry_time",
                    "entry_price",
                    "direction",
                    "stop_loss",
                    "take_profit",
                    "confidence",
                    "sources_count",
                    "exit_bar",
                    "exit_price",
                    "exit_reason",
                    "pnl",
                    "pnl_pct",
                    "bars_held",
                    "win",
                ],
            )
            writer.writeheader()
            for trade in self.trades:
                writer.writerow({
                    "entry_bar": trade.entry_bar,
                    "entry_time": trade.entry_time.isoformat() if trade.entry_time else "",
                    "entry_price": f"{trade.entry_price:.2f}",
                    "direction": trade.direction,
                    "stop_loss": f"{trade.stop_loss:.2f}",
                    "take_profit": f"{trade.take_profit:.2f}",
                    "confidence": f"{trade.confidence:.2f}",
                    "sources_count": trade.sources_count,
                    "exit_bar": trade.exit_bar,
                    "exit_price": f"{trade.exit_price:.2f}" if trade.exit_price else "",
                    "exit_reason": trade.exit_reason,
                    "pnl": f"{trade.pnl:+.2f}" if trade.pnl is not None else "",
                    "pnl_pct": f"{trade.pnl_pct:+.2f}%" if trade.pnl_pct is not None else "",
                    "bars_held": trade.bars_held,
                    "win": trade.win,
                })

        logger.info("[Backtest] Exported %s trades to %s", len(self.trades), filepath)
