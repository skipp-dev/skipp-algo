"""Deterministic bar fixtures for parity testing.

Each fixture returns a pd.DataFrame with columns:
  symbol, timestamp, open, high, low, close, volume

The bars are synthetic but designed to trigger at least one event
in each structure family (BOS, OB, FVG, sweep) so parity checks
have non-trivial content.
"""
from __future__ import annotations

import pandas as pd


def _ts(day: int) -> pd.Timestamp:
    return pd.Timestamp(f"2024-01-{day:02d}", tz="UTC")


# ── Generic / legacy fixtures ───────────────────────────────────

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


# ── Targeted SMC-family fixtures ────────────────────────────────


def make_bullish_bos_bars(symbol: str = "TEST") -> pd.DataFrame:
    """Steady uptrend with pullbacks — produces multiple BOS UP events."""
    rows: list[dict] = []
    for i in range(20):
        base = 100.0 + i * 1.5
        if i % 5 == 3:
            base -= 3.0
        rows.append({
            "symbol": symbol, "timestamp": _ts(i + 1),
            "open": base, "high": base + 2.0,
            "low": base - 1.5, "close": base + 1.0, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def make_bearish_bos_bars(symbol: str = "TEST") -> pd.DataFrame:
    """Steady downtrend with bounces — produces multiple BOS DOWN events."""
    rows: list[dict] = []
    for i in range(20):
        base = 130.0 - i * 1.5
        if i % 5 == 3:
            base += 3.0
        rows.append({
            "symbol": symbol, "timestamp": _ts(i + 1),
            "open": base, "high": base + 1.5,
            "low": base - 2.0, "close": base - 1.0, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def make_orderblock_bars(symbol: str = "TEST") -> pd.DataFrame:
    """Two-candle displacement patterns — produces BULL and BEAR orderblocks."""
    rows = [
        {"symbol": symbol, "timestamp": _ts(1), "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(2), "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(3), "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1000},
        # BULL OB: down candle → up candle with close > prev high
        {"symbol": symbol, "timestamp": _ts(4), "open": 110, "high": 115, "low": 95, "close": 100, "volume": 2000},
        {"symbol": symbol, "timestamp": _ts(5), "open": 100, "high": 125, "low": 98, "close": 120, "volume": 3000},
        {"symbol": symbol, "timestamp": _ts(6), "open": 120, "high": 122, "low": 118, "close": 121, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(7), "open": 121, "high": 123, "low": 119, "close": 122, "volume": 1000},
        # BEAR OB: up candle → down candle with close < prev low
        {"symbol": symbol, "timestamp": _ts(8), "open": 105, "high": 125, "low": 100, "close": 120, "volume": 2000},
        {"symbol": symbol, "timestamp": _ts(9), "open": 120, "high": 121, "low": 88, "close": 92, "volume": 3000},
        {"symbol": symbol, "timestamp": _ts(10), "open": 92, "high": 95, "low": 90, "close": 93, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(11), "open": 93, "high": 96, "low": 91, "close": 94, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(12), "open": 94, "high": 97, "low": 92, "close": 95, "volume": 1000},
    ]
    return pd.DataFrame(rows)


def make_fvg_bars(symbol: str = "TEST") -> pd.DataFrame:
    """Gapped candle sequences — produces BULL and BEAR FVGs."""
    rows = [
        {"symbol": symbol, "timestamp": _ts(1), "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(2), "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1000},
        # Bull FVG: bar[i].low > bar[i-2].high
        {"symbol": symbol, "timestamp": _ts(3), "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(4), "open": 103, "high": 112, "low": 103, "close": 110, "volume": 2000},
        {"symbol": symbol, "timestamp": _ts(5), "open": 110, "high": 115, "low": 107, "close": 112, "volume": 1500},
        {"symbol": symbol, "timestamp": _ts(6), "open": 112, "high": 114, "low": 110, "close": 113, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(7), "open": 113, "high": 115, "low": 111, "close": 114, "volume": 1000},
        # Bear FVG: bar[i].high < bar[i-2].low
        {"symbol": symbol, "timestamp": _ts(8), "open": 114, "high": 115, "low": 113, "close": 114, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(9), "open": 114, "high": 114, "low": 100, "close": 102, "volume": 2000},
        {"symbol": symbol, "timestamp": _ts(10), "open": 102, "high": 108, "low": 100, "close": 105, "volume": 1500},
        {"symbol": symbol, "timestamp": _ts(11), "open": 105, "high": 107, "low": 103, "close": 106, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(12), "open": 106, "high": 108, "low": 104, "close": 107, "volume": 1000},
    ]
    return pd.DataFrame(rows)


def make_sweep_bars(symbol: str = "TEST") -> pd.DataFrame:
    """Pivot3 levels with spike-and-reverse — produces BUY_SIDE and SELL_SIDE sweeps."""
    rows = [
        # Pivot HIGH at bar 2: high(110) > bar1.high(105) and > bar3.high(106)
        {"symbol": symbol, "timestamp": _ts(1), "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(2), "open": 103, "high": 110, "low": 102, "close": 107, "volume": 1500},
        {"symbol": symbol, "timestamp": _ts(3), "open": 107, "high": 106, "low": 100, "close": 103, "volume": 1000},
        # Pivot LOW at bar 5: low(92) < bar4.low(97) and < bar6.low(96)
        {"symbol": symbol, "timestamp": _ts(4), "open": 103, "high": 105, "low": 97, "close": 100, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(5), "open": 100, "high": 101, "low": 92, "close": 98, "volume": 1500},
        {"symbol": symbol, "timestamp": _ts(6), "open": 98, "high": 102, "low": 96, "close": 100, "volume": 1000},
        # Holding bars
        {"symbol": symbol, "timestamp": _ts(7), "open": 100, "high": 103, "low": 98, "close": 101, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(8), "open": 101, "high": 104, "low": 99, "close": 102, "volume": 1000},
        # BUY_SIDE sweep: spike above pivot high(110) but close below it
        {"symbol": symbol, "timestamp": _ts(9), "open": 102, "high": 113, "low": 101, "close": 105, "volume": 2000},
        # SELL_SIDE sweep: spike below pivot low(92) but close above it
        {"symbol": symbol, "timestamp": _ts(10), "open": 105, "high": 106, "low": 89, "close": 97, "volume": 2000},
        {"symbol": symbol, "timestamp": _ts(11), "open": 97, "high": 100, "low": 95, "close": 98, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(12), "open": 98, "high": 101, "low": 96, "close": 99, "volume": 1000},
    ]
    return pd.DataFrame(rows)


def make_mixed_bars(symbol: str = "TEST") -> pd.DataFrame:
    """Bars engineered to produce all structure families: BOS, OB, FVG, and sweeps."""
    rows = [
        # Uptrend → BOS UP
        {"symbol": symbol, "timestamp": _ts(1), "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(2), "open": 101, "high": 104, "low": 100, "close": 103, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(3), "open": 103, "high": 106, "low": 102, "close": 105, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(4), "open": 105, "high": 101, "low": 99, "close": 100, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(5), "open": 100, "high": 108, "low": 99, "close": 107, "volume": 1500},
        # Bull OB displacement
        {"symbol": symbol, "timestamp": _ts(6), "open": 115, "high": 118, "low": 105, "close": 108, "volume": 2000},
        {"symbol": symbol, "timestamp": _ts(7), "open": 108, "high": 125, "low": 107, "close": 122, "volume": 3000},
        # FVG gap up
        {"symbol": symbol, "timestamp": _ts(8), "open": 122, "high": 123, "low": 121, "close": 122, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(9), "open": 122, "high": 135, "low": 122, "close": 133, "volume": 2000},
        {"symbol": symbol, "timestamp": _ts(10), "open": 133, "high": 138, "low": 126, "close": 135, "volume": 1500},
        # Spike above (sweep setup)
        {"symbol": symbol, "timestamp": _ts(11), "open": 135, "high": 145, "low": 134, "close": 134.5, "volume": 2000},
        # Reversal — BOS DOWN
        {"symbol": symbol, "timestamp": _ts(12), "open": 134, "high": 135, "low": 125, "close": 126, "volume": 1500},
        {"symbol": symbol, "timestamp": _ts(13), "open": 126, "high": 128, "low": 120, "close": 121, "volume": 1500},
        {"symbol": symbol, "timestamp": _ts(14), "open": 121, "high": 123, "low": 115, "close": 116, "volume": 1500},
        # Bear OB displacement
        {"symbol": symbol, "timestamp": _ts(15), "open": 110, "high": 120, "low": 108, "close": 118, "volume": 2000},
        {"symbol": symbol, "timestamp": _ts(16), "open": 118, "high": 119, "low": 95, "close": 98, "volume": 3000},
        # Tail bars
        {"symbol": symbol, "timestamp": _ts(17), "open": 98, "high": 101, "low": 96, "close": 99, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(18), "open": 99, "high": 102, "low": 97, "close": 100, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(19), "open": 100, "high": 103, "low": 98, "close": 101, "volume": 1000},
        {"symbol": symbol, "timestamp": _ts(20), "open": 101, "high": 104, "low": 99, "close": 102, "volume": 1000},
    ]
    return pd.DataFrame(rows)


# ── Expected minimum families per fixture (for guard assertions) ──

EXPECTED_FAMILIES: dict[str, set[str]] = {
    "bullish_bos": {"bos"},
    "bearish_bos": {"bos"},
    "orderblock": {"orderblocks"},
    "fvg": {"fvg"},
    "sweep": {"liquidity_sweeps"},
    "mixed": {"bos", "orderblocks", "fvg", "liquidity_sweeps"},
    "trending_30d": {"bos"},
    "reversal_30d": {"bos"},
    "flat_20d": set(),  # may produce empty
}


# Registry: (name, factory, symbol, timeframe)
PARITY_FIXTURES = [
    ("trending_30d", make_trending_bars, "TEST", "1D"),
    ("reversal_30d", make_reversal_bars, "TEST", "1D"),
    ("flat_20d", make_flat_bars, "TEST", "1D"),
    ("bullish_bos", make_bullish_bos_bars, "TEST", "1D"),
    ("bearish_bos", make_bearish_bos_bars, "TEST", "1D"),
    ("orderblock", make_orderblock_bars, "TEST", "1D"),
    ("fvg", make_fvg_bars, "TEST", "1D"),
    ("sweep", make_sweep_bars, "TEST", "1D"),
    ("mixed", make_mixed_bars, "TEST", "1D"),
]
