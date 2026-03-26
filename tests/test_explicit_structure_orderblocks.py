from __future__ import annotations

import pandas as pd

from scripts.explicit_structure_from_bars import build_orderblocks_from_bars


def _orderblock_bars() -> pd.DataFrame:
    timestamps = pd.date_range("2024-04-01", periods=20, freq="D", tz="UTC")
    rows: list[dict[str, float | str | pd.Timestamp]] = []

    for idx, ts in enumerate(timestamps):
        base = 100.0 + idx * 0.1
        row = {
            "symbol": "AAPL",
            "timestamp": ts,
            "open": base,
            "high": base + 0.5,
            "low": base - 0.5,
            "close": base + 0.2,
            "volume": 1000.0 + idx,
        }
        if idx == 13:
            row = {
                "symbol": "AAPL",
                "timestamp": ts,
                "open": 102.0,
                "high": 102.3,
                "low": 100.0,
                "close": 100.4,
                "volume": 1013.0,
            }
        if idx == 14:
            row = {
                "symbol": "AAPL",
                "timestamp": ts,
                "open": 100.5,
                "high": 106.0,
                "low": 100.0,
                "close": 105.6,
                "volume": 2000.0,
            }
        rows.append(row)

    return pd.DataFrame(rows)


def test_build_orderblocks_detects_displacement_anchor() -> None:
    bars = _orderblock_bars()
    orderblocks = build_orderblocks_from_bars(bars, symbol="AAPL", timeframe="1D")

    assert orderblocks
    first = orderblocks[0]
    assert first["dir"] in {"BULL", "BEAR"}
    assert first["high"] > first["low"]
    assert first["valid"] is True
    assert str(first["id"]).startswith("ob:")
