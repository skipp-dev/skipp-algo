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


def _frame(highs: list[float], lows: list[float], closes: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range("2024-03-01", periods=len(highs), freq="15min", tz="UTC")
    rows = []
    for i, ts in enumerate(timestamps):
        rows.append(
            {
                "symbol": "AAPL",
                "timestamp": ts,
                "open": closes[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": 100 + i,
            }
        )
    return pd.DataFrame(rows)


def test_broken_fractal_emits_first_break_for_high_fractal() -> None:
    # Bar 1 is a high fractal (high 12 > neighbours 10/9). The first future bar
    # whose close exceeds 12 is the trigger; later breaks are ignored.
    highs = [10.0, 12.0, 9.0, 9.5, 9.6, 13.0, 14.0]
    lows = [8.0, 9.0, 7.0, 7.5, 7.6, 9.0, 9.5]
    closes = [9.0, 11.0, 8.0, 8.5, 8.6, 12.5, 13.0]
    frame = _frame(highs, lows, closes)
    anchor_ts = int(frame.iloc[1]["timestamp"].timestamp())
    trigger_ts = int(frame.iloc[5]["timestamp"].timestamp())

    signals = compute_broken_fractal_signals(frame)
    bullish = [s for s in signals if s["side"] == "BULLISH" and s["anchor_ts"] == anchor_ts]

    assert len(bullish) == 1
    # Trigger is bar index 5 (first close 12.5 > level 12.0), not bar 6.
    assert bullish[0]["trigger_ts"] == trigger_ts
    assert bullish[0]["level"] == 12.0
    assert isinstance(bullish[0]["level"], float)


def test_broken_fractal_returns_python_floats_and_ints() -> None:
    bars = _bars(n=40)
    for sig in compute_broken_fractal_signals(bars):
        assert type(sig["anchor_ts"]) is int
        assert type(sig["trigger_ts"]) is int
        for key in ("level", "zone_high", "zone_low"):
            assert type(sig[key]) is float
