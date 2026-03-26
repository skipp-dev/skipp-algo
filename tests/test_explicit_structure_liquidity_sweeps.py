from __future__ import annotations

import pandas as pd

from scripts.explicit_structure_from_bars import build_liquidity_sweeps_from_bars


def _sweep_bars() -> pd.DataFrame:
    timestamps = pd.date_range("2024-02-01", periods=9, freq="D", tz="UTC")
    highs = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 14.0, 14.5]
    lows = [5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 9.0, 4.0, 5.2]
    closes = [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 6.6, 9.0]

    rows = []
    for idx, ts in enumerate(timestamps):
        rows.append(
            {
                "symbol": "AAPL",
                "timestamp": ts,
                "open": closes[idx] - 0.3,
                "high": highs[idx],
                "low": lows[idx],
                "close": closes[idx],
                "volume": 1000 + idx,
            }
        )
    return pd.DataFrame(rows)


def test_build_liquidity_sweeps_detects_both_sides() -> None:
    bars = _sweep_bars()
    sweeps = build_liquidity_sweeps_from_bars(bars, symbol="AAPL", timeframe="1D")

    assert sweeps
    sides = {item["side"] for item in sweeps}
    assert "BUY_SIDE" in sides
    assert "SELL_SIDE" in sides
    assert all(str(item["id"]).startswith("sweep:") for item in sweeps)
