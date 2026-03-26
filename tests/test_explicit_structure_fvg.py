from __future__ import annotations

import pandas as pd

from scripts.explicit_structure_from_bars import build_fvg_from_bars
from smc_core.ids import fvg_id


def _fvg_bars() -> pd.DataFrame:
    timestamps = pd.date_range("2024-03-01", periods=5, freq="D", tz="UTC")
    rows = [
        {"symbol": "AAPL", "timestamp": timestamps[0], "open": 97.0, "high": 100.0, "low": 95.0, "close": 99.0},
        {"symbol": "AAPL", "timestamp": timestamps[1], "open": 100.0, "high": 101.0, "low": 98.0, "close": 100.5},
        {"symbol": "AAPL", "timestamp": timestamps[2], "open": 104.0, "high": 108.0, "low": 103.0, "close": 107.0},
        {"symbol": "AAPL", "timestamp": timestamps[3], "open": 106.0, "high": 107.0, "low": 104.0, "close": 105.0},
        {"symbol": "AAPL", "timestamp": timestamps[4], "open": 96.0, "high": 99.0, "low": 94.0, "close": 95.0},
    ]
    return pd.DataFrame(rows)


def test_build_fvg_detects_bull_and_bear_gaps() -> None:
    bars = _fvg_bars()
    fvgs = build_fvg_from_bars(bars, symbol="AAPL", timeframe="1D")

    assert fvgs
    directions = {item["dir"] for item in fvgs}
    assert "BULL" in directions
    assert "BEAR" in directions
    assert all(item["high"] > item["low"] for item in fvgs)
    assert all(str(item["id"]).startswith("fvg:") for item in fvgs)


def test_fvg_id_is_anchored_to_confirmation_bar() -> None:
    bars = _fvg_bars()
    fvgs = build_fvg_from_bars(bars, symbol="AAPL", timeframe="1D")
    bullish = next(item for item in fvgs if item["dir"] == "BULL")

    confirm_ts = float(pd.Timestamp(bars.iloc[2]["timestamp"]).timestamp())
    expected = fvg_id(
        symbol="AAPL",
        timeframe="1D",
        anchor_ts=confirm_ts,
        dir="BULL",
        low=float(bullish["low"]),
        high=float(bullish["high"]),
    )
    assert bullish["id"] == expected
