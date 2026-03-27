"""Deterministic bar fixtures for parity testing.

Each fixture returns a pd.DataFrame with columns:
  symbol, timestamp, open, high, low, close, volume

The bars are synthetic but designed to trigger at least one event
in each structure family (BOS, OB, FVG, sweep) so parity checks
have non-trivial content.
"""
from __future__ import annotations

import pandas as pd


def make_trending_bars(symbol: str = "TEST", periods: int = 30) -> pd.DataFrame:
    """Uptrending bars with swing structure — triggers BOS events."""
    timestamps = pd.date_range("2024-01-01", periods=periods, freq="D", tz="UTC")
    rows: list[dict] = []
    for i, ts in enumerate(timestamps):
        # gentle uptrend with periodic pullbacks to create swings
        base = 100.0 + i * 0.5
        if i % 5 == 3:
            # pullback bar
            base -= 1.5
        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts,
                "open": base,
                "high": base + 1.0,
                "low": base - 0.8,
                "close": base + 0.4,
                "volume": 1000.0 + i * 10,
            }
        )
    return pd.DataFrame(rows)


def make_reversal_bars(symbol: str = "TEST", periods: int = 30) -> pd.DataFrame:
    """Bars that trend up then reverse — should trigger CHOCH events."""
    timestamps = pd.date_range("2024-01-01", periods=periods, freq="D", tz="UTC")
    rows: list[dict] = []
    mid = periods // 2
    for i, ts in enumerate(timestamps):
        if i < mid:
            base = 100.0 + i * 0.6
        else:
            base = 100.0 + mid * 0.6 - (i - mid) * 0.7
        if i % 5 == 3:
            base -= 1.0
        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts,
                "open": base,
                "high": base + 1.2,
                "low": base - 1.0,
                "close": base + 0.3,
                "volume": 1200.0 + i * 5,
            }
        )
    return pd.DataFrame(rows)


def make_flat_bars(symbol: str = "TEST", periods: int = 20) -> pd.DataFrame:
    """Range-bound bars — may produce zero events in some families."""
    timestamps = pd.date_range("2024-01-01", periods=periods, freq="D", tz="UTC")
    rows: list[dict] = []
    for i, ts in enumerate(timestamps):
        base = 100.0 + (i % 3) * 0.2
        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts,
                "open": base,
                "high": base + 0.5,
                "low": base - 0.5,
                "close": base + 0.1,
                "volume": 800.0,
            }
        )
    return pd.DataFrame(rows)


# Registry: (name, factory, symbol, timeframe)
PARITY_FIXTURES = [
    ("trending_30d", make_trending_bars, "TEST", "1D"),
    ("reversal_30d", make_reversal_bars, "TEST", "1D"),
    ("flat_20d", make_flat_bars, "TEST", "1D"),
]
