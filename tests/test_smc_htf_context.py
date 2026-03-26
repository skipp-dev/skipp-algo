from __future__ import annotations

import pandas as pd

from scripts.smc_htf_context import (
    build_htf_bias_context,
    build_ipda_range,
    compute_calendar_boundaries,
    compute_fvg_bias_counter,
    select_ipda_htf,
)
from scripts.smc_price_action_engine import normalize_bars


def make_bars(rows: list[dict]) -> pd.DataFrame:
    return normalize_bars(pd.DataFrame(rows))


def test_fvg_bias_counter_resets_on_reversal() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
            {"timestamp": 2, "open": 10, "high": 12, "low": 10, "close": 11.5, "volume": 100},
            {"timestamp": 3, "open": 11, "high": 11.2, "low": 8, "close": 8.5, "volume": 100},
        ]
    )
    out = compute_fvg_bias_counter(df)
    assert out[-1]["counter"] < 0


def test_select_ipda_htf() -> None:
    assert select_ipda_htf("5m") == "D"
    assert select_ipda_htf("4H") == "W"
    assert select_ipda_htf("D") == "M"


def test_build_ipda_range_levels() -> None:
    out = build_ipda_range({"high": 110.0, "low": 95.0}, {"high": 108.0, "low": 90.0})
    assert out["range_high"] == 110.0
    assert out["range_low"] == 90.0
    assert out["q25"] == 95.0
    assert out["mid"] == 100.0
    assert out["q75"] == 105.0


def test_compute_calendar_boundaries() -> None:
    df = make_bars(
        [
            {"timestamp": 1700000000, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
            {"timestamp": 1700086400, "open": 10.5, "high": 11.5, "low": 10, "close": 11, "volume": 100},
            {"timestamp": 1700172800, "open": 11, "high": 11.7, "low": 10.8, "close": 11.4, "volume": 100},
        ]
    )
    out = compute_calendar_boundaries(df)
    assert "day_boundaries" in out
    assert "week_boundaries" in out
    assert "month_boundaries" in out


def test_build_htf_bias_context_shape() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
            {"timestamp": 2, "open": 10.5, "high": 11.2, "low": 10.0, "close": 10.9, "volume": 100},
            {"timestamp": 3, "open": 10.9, "high": 11.5, "low": 10.7, "close": 11.3, "volume": 100},
        ]
    )
    out = build_htf_bias_context(df, timeframe="15m", htf_frames=None)
    assert set(out.keys()) == {"selected_ipda_htf", "fvg_bias_counter", "ipda_range", "calendar_boundaries"}
