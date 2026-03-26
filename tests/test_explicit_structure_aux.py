from __future__ import annotations

import pandas as pd

from scripts.explicit_structure_aux import (
    build_ipda_operating_range,
    build_session_pivots,
    build_session_ranges,
    compute_broken_fractal_signals,
    compute_htf_fvg_bias,
)


def _bars(symbol: str = "AAPL", n: int = 32) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=n, freq="30min", tz="UTC")
    rows: list[dict] = []
    for i, ts in enumerate(timestamps):
        base = 100.0 + (i % 7) * 0.4 + i * 0.03
        close = base + (0.2 if i % 2 == 0 else -0.15)
        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts,
                "open": base,
                "high": max(base, close) + 0.4,
                "low": min(base, close) - 0.4,
                "close": close,
                "volume": 500 + i,
            }
        )
    return pd.DataFrame(rows)


def test_session_ranges_and_pivots_are_derived() -> None:
    bars = _bars()
    ranges = build_session_ranges(bars)
    pivots = build_session_pivots(ranges)

    assert isinstance(ranges, list)
    assert isinstance(pivots, list)
    if ranges:
        assert set(ranges[0].keys()) == {"session", "date", "start_ts", "end_ts", "high", "low", "mid", "range"}


def test_ipda_range_includes_quartiles() -> None:
    ipda = build_ipda_operating_range(_bars(), timeframe="15m")
    assert ipda["selected_htf"] == "D"
    assert ipda["range_low"] <= ipda["range_25"] <= ipda["range_50"] <= ipda["range_75"] <= ipda["range_high"]


def test_htf_bias_and_broken_fractal_helpers_return_valid_shapes() -> None:
    bars = _bars(n=48)
    bias = compute_htf_fvg_bias(bars)
    signals = compute_broken_fractal_signals(bars)

    assert set(bias.keys()) == {"counter", "bias"}
    assert bias["bias"] in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert isinstance(signals, list)
