from __future__ import annotations

import pandas as pd

from scripts.smc_price_action_engine import (
    detect_bos_from_pivots,
    detect_fvg_three_candle,
    detect_orderblocks_two_candle,
    normalize_bars,
)


def make_bars(rows: list[dict]) -> pd.DataFrame:
    return normalize_bars(pd.DataFrame(rows))


def test_detect_bullish_orderblock() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 8, "close": 9, "volume": 100},
            {"timestamp": 2, "open": 9, "high": 12, "low": 7, "close": 11.5, "volume": 100},
        ]
    )
    obs = detect_orderblocks_two_candle(df, "AAPL", "15m")
    assert len(obs) == 1
    ob = obs[0]
    assert ob["dir"] == "BULL"
    assert ob["high"] == 11
    assert ob["low"] == 7


def test_detect_bearish_orderblock() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"timestamp": 2, "open": 11, "high": 13, "low": 8, "close": 8.5, "volume": 100},
        ]
    )
    obs = detect_orderblocks_two_candle(df, "AAPL", "15m")
    assert len(obs) == 1
    ob = obs[0]
    assert ob["dir"] == "BEAR"
    assert ob["low"] == 9
    assert ob["high"] == 13


def test_detect_bullish_fvg() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
            {"timestamp": 2, "open": 10, "high": 12, "low": 10, "close": 11, "volume": 100},
            {"timestamp": 3, "open": 12, "high": 14, "low": 12.5, "close": 13, "volume": 100},
        ]
    )
    gaps = detect_fvg_three_candle(df, "AAPL", "15m")
    assert len(gaps) == 1
    assert gaps[0]["dir"] == "BULL"
    assert gaps[0]["low"] == 11
    assert gaps[0]["high"] == 12.5


def test_detect_bearish_fvg() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 14, "low": 13, "close": 13.5, "volume": 100},
            {"timestamp": 2, "open": 13.2, "high": 13.3, "low": 12.5, "close": 12.8, "volume": 100},
            {"timestamp": 3, "open": 12.5, "high": 12.0, "low": 10.5, "close": 11.0, "volume": 100},
        ]
    )
    gaps = detect_fvg_three_candle(df, "AAPL", "15m")
    assert len(gaps) == 1
    assert gaps[0]["dir"] == "BEAR"


def test_detect_bullish_bos_from_pivot_break() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 9.5, "high": 10.0, "low": 8.8, "close": 9.2, "volume": 100},
            {"timestamp": 2, "open": 9.2, "high": 12.0, "low": 9.0, "close": 11.2, "volume": 100},
            {"timestamp": 3, "open": 11.0, "high": 11.0, "low": 9.5, "close": 10.0, "volume": 100},
            {"timestamp": 4, "open": 10.0, "high": 11.5, "low": 9.7, "close": 11.0, "volume": 100},
            {"timestamp": 5, "open": 11.0, "high": 13.5, "low": 10.8, "close": 12.8, "volume": 100},
        ]
    )
    bos = detect_bos_from_pivots(df, "AAPL", "15m", pivot_lookup=1)
    assert any(x["dir"] == "UP" for x in bos)


def test_detect_bearish_bos_from_pivot_break() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 11.0, "high": 11.5, "low": 9.5, "close": 10.5, "volume": 100},
            {"timestamp": 2, "open": 10.5, "high": 10.8, "low": 8.0, "close": 8.4, "volume": 100},
            {"timestamp": 3, "open": 8.5, "high": 9.3, "low": 8.8, "close": 9.1, "volume": 100},
            {"timestamp": 4, "open": 9.0, "high": 9.2, "low": 8.2, "close": 8.8, "volume": 100},
            {"timestamp": 5, "open": 8.8, "high": 9.0, "low": 7.0, "close": 7.4, "volume": 100},
        ]
    )
    bos = detect_bos_from_pivots(df, "AAPL", "15m", pivot_lookup=1)
    assert any(x["dir"] == "DOWN" for x in bos)
