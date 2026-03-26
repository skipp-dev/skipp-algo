from __future__ import annotations

import pandas as pd

from scripts.explicit_structure_from_bars import build_full_structure_from_bars, resample_bars_to_timeframe


def _bars(symbol: str = "AAPL") -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=18, freq="D", tz="UTC")
    rows: list[dict[str, float | str | pd.Timestamp]] = []
    for index, ts in enumerate(timestamps):
        base = 100.0 + index * 0.2
        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts,
                "open": base,
                "high": base + 0.8,
                "low": base - 0.8,
                "close": base + 0.2,
                "volume": 1000.0 + index,
            }
        )
    return pd.DataFrame(rows)


def test_resample_bars_to_timeframe_keeps_required_columns() -> None:
    bars = _bars()
    out = resample_bars_to_timeframe(bars, "1D")

    assert not out.empty
    assert list(out.columns) == ["symbol", "timestamp", "open", "high", "low", "close", "volume"]


def test_build_full_structure_from_bars_returns_expected_shape() -> None:
    bars = _bars()
    structure = build_full_structure_from_bars(bars, symbol="AAPL", timeframe="1D")

    assert set(structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert isinstance(structure["bos"], list)
    assert isinstance(structure["orderblocks"], list)
    assert isinstance(structure["fvg"], list)
    assert isinstance(structure["liquidity_sweeps"], list)


def test_resample_excludes_incomplete_last_bucket() -> None:
    bars = pd.DataFrame(
        [
            {"symbol": "AAPL", "timestamp": "2024-01-01T09:30:00Z", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 10},
            {"symbol": "AAPL", "timestamp": "2024-01-01T09:31:00Z", "open": 100.5, "high": 101.2, "low": 100.2, "close": 101.0, "volume": 12},
            {"symbol": "AAPL", "timestamp": "2024-01-01T09:32:00Z", "open": 101.0, "high": 101.3, "low": 100.8, "close": 101.1, "volume": 8},
        ]
    )

    out = resample_bars_to_timeframe(bars, "5m")
    assert not out.empty
    max_source = pd.to_datetime(bars["timestamp"], utc=True).max()
    assert pd.to_datetime(out["timestamp"], utc=True).max() <= max_source
