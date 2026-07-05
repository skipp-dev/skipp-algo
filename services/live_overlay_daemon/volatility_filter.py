#!/usr/bin/env python3
"""
VOLATILITY FILTER
Skip choppy markets, trade only trending regimes.

Design:
  ATR Ratio = Current ATR / SMA(ATR, 20 periods)

  • Ratio < 0.8: Market too calm/boring (skip, wait for volatility)
  • 0.8 <= Ratio <= 1.5: GOOD TRADING ZONE (normal volatility)
  • Ratio > 1.5: Market too choppy/volatile (skip, wait for calm)

This filters out both extremes:
  - Too boring → no trending momentum
  - Too choppy → noise, random signals
"""

import math

import numpy as np


class VolatilityFilter:
    """Filter trades based on ATR volatility regime."""

    def __init__(self, atr_period=14, sma_period=20, ratio_min=0.8, ratio_max=1.5):
        """
        Args:
            atr_period: Period for ATR calculation (default 14)
            sma_period: Period for SMA of ATR (default 20)
            ratio_min: Minimum acceptable ATR ratio (skip if below)
            ratio_max: Maximum acceptable ATR ratio (skip if above)
        """
        self.atr_period = atr_period
        self.sma_period = sma_period
        self.ratio_min = ratio_min
        self.ratio_max = ratio_max

        # Cache for ATR values
        self.atr_history = []
        self.prev_close = None

    def calculate_atr(self, high, low, close):
        """Calculate True Range and ATR for a candle."""
        # A non-finite (NaN / ±inf) candle must not poison atr_history or
        # prev_close: a single NaN would make every future ATR — and the ratio
        # the trade gate reads — NaN forever. Skip it and keep the last ATR.
        if not (math.isfinite(high) and math.isfinite(low) and math.isfinite(close)):
            return self.atr_history[-1] if self.atr_history else None

        prev_close = self.prev_close
        self.prev_close = close

        if len(self.atr_history) == 0:
            # Initialize with TR
            tr = high - low
            self.atr_history.append(tr)
            return tr

        # True Range = max(high-low, |high-prev_close|, |low-prev_close|)
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))

        # Wilder's smoothing for ATR
        if len(self.atr_history) < self.atr_period:
            self.atr_history.append(tr)
            # Not enough data yet, return average TR
            result = sum(self.atr_history) / len(self.atr_history)
        else:
            # Wilder's ATR = (prev_ATR * (period-1) + TR) / period
            prev_atr = self.atr_history[-1]
            result = (prev_atr * (self.atr_period - 1) + tr) / self.atr_period
            self.atr_history.append(result)

        # Only the trailing SMA window (and last ATR) is ever read;
        # cap the history so long-running daemons don't leak memory.
        max_keep = max(self.sma_period, self.atr_period)
        if len(self.atr_history) > max_keep:
            del self.atr_history[:-max_keep]
        return result

    def get_atr_ratio(self):
        """Get current ATR / SMA(ATR, 20)."""
        if len(self.atr_history) < self.sma_period:
            return None  # Not enough data

        current_atr = self.atr_history[-1]
        atr_sma = np.mean(self.atr_history[-self.sma_period:])

        if atr_sma == 0 or not math.isfinite(atr_sma) or not math.isfinite(current_atr):
            return None

        ratio = current_atr / atr_sma
        return ratio if math.isfinite(ratio) else None

    def is_tradeable(self):
        """
        Check if current market regime is tradeable.

        Returns:
            bool: True if market is in trading zone (0.8-1.5 ratio)
            str: Reason if not tradeable ("too_calm", "too_choppy", "insufficient_data")
        """
        ratio = self.get_atr_ratio()

        if ratio is None:
            return False, "insufficient_data"

        # Fail CLOSED on corrupt data: a NaN ratio makes both threshold
        # comparisons below False and would otherwise fall through to
        # "tradeable" — opening the gate on garbage instead of skipping.
        if not math.isfinite(ratio):
            return False, "non_finite_atr"

        if ratio < self.ratio_min:
            return False, "too_calm"

        if ratio > self.ratio_max:
            return False, "too_choppy"

        return True, "tradeable"

    def reset(self):
        """Reset for new backtest."""
        self.atr_history = []
        self.prev_close = None


# Example usage for backtesting
def apply_volatility_filter_to_backtest(candles, filter_obj):
    """
    Apply volatility filter to a list of candles.
    Returns: List of (index, is_tradeable, reason)
    """
    results = []

    for i, candle in enumerate(candles):
        high = candle.get("high", 0)
        low = candle.get("low", 0)
        close = candle.get("close", 0)

        # Update filter
        filter_obj.calculate_atr(high, low, close)
        is_tradeable, reason = filter_obj.is_tradeable()

        results.append({
            "index": i,
            "is_tradeable": is_tradeable,
            "reason": reason,
            "atr_ratio": filter_obj.get_atr_ratio(),
        })

    return results


if __name__ == "__main__":
    print("Volatility Filter Module")
    print("="*90)
    print()
    print("Design:")
    print("  ATR Ratio = Current ATR / SMA(ATR, 20)")
    print()
    print("Trading Zones:")
    print("  Ratio < 0.8:      Too calm (skip)")
    print("  0.8-1.5:          GOOD ZONE ✅")
    print("  Ratio > 1.5:      Too choppy (skip)")
    print()
    print("Use in ensemble_signal_router:")
    print("  Before generating signals, check: is_tradeable()?")
    print("  If False, skip signal generation for that candle.")
    print()
