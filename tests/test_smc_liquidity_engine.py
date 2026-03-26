from __future__ import annotations

import pandas as pd

from scripts.smc_liquidity_engine import detect_liquidity_levels, detect_liquidity_sweeps
from scripts.smc_price_action_engine import normalize_bars


def make_bars(rows: list[dict]) -> pd.DataFrame:
    return normalize_bars(pd.DataFrame(rows))


def test_detect_pivot_liquidity_levels() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
            {"timestamp": 2, "open": 10, "high": 13, "low": 9.5, "close": 12, "volume": 100},
            {"timestamp": 3, "open": 12, "high": 11.5, "low": 9, "close": 10.2, "volume": 100},
            {"timestamp": 4, "open": 10.3, "high": 11.0, "low": 8.2, "close": 9.0, "volume": 100},
            {"timestamp": 5, "open": 9.0, "high": 10.8, "low": 8.9, "close": 10.0, "volume": 100},
        ]
    )
    levels = detect_liquidity_levels(df, "AAPL", "15m")
    assert any(x["side"] == "BUY_SIDE" for x in levels)
    assert any(x["side"] == "SELL_SIDE" for x in levels)


def test_detect_buy_side_sweep_against_pivot_high() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
            {"timestamp": 2, "open": 10, "high": 13, "low": 9.5, "close": 12, "volume": 100},
            {"timestamp": 3, "open": 12, "high": 11.5, "low": 9, "close": 10.0, "volume": 100},
            {"timestamp": 4, "open": 10, "high": 13.5, "low": 9.8, "close": 12.5, "volume": 100},
        ]
    )
    levels = detect_liquidity_levels(df, "AAPL", "15m")
    sweeps = detect_liquidity_sweeps(df, levels, "AAPL", "15m")
    assert any(x["side"] == "BUY_SIDE" for x in sweeps)


def test_detect_sell_side_sweep_against_pivot_low() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 100},
            {"timestamp": 2, "open": 10.1, "high": 10.2, "low": 8.0, "close": 8.4, "volume": 100},
            {"timestamp": 3, "open": 8.5, "high": 9.6, "low": 8.8, "close": 9.3, "volume": 100},
            {"timestamp": 4, "open": 9.2, "high": 9.5, "low": 7.6, "close": 8.3, "volume": 100},
        ]
    )
    levels = detect_liquidity_levels(df, "AAPL", "15m")
    sweeps = detect_liquidity_sweeps(df, levels, "AAPL", "15m")
    assert any(x["side"] == "SELL_SIDE" for x in sweeps)
