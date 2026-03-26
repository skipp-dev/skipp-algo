from __future__ import annotations

import pandas as pd

from scripts.smc_structure_qualifiers import (
    build_pivots_top_bottom,
    build_structure_qualifiers,
    detect_broken_fractal,
    detect_ppdd,
)
from scripts.smc_price_action_engine import detect_high_volume_bars, detect_ob_fvg_stack, detect_structure_breaking_fvg, normalize_bars


def make_bars(rows: list[dict]) -> pd.DataFrame:
    return normalize_bars(pd.DataFrame(rows))


def test_detect_structure_breaking_fvg_returns_list() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
            {"timestamp": 2, "open": 10, "high": 14, "low": 10, "close": 13, "volume": 100},
            {"timestamp": 3, "open": 13, "high": 12, "low": 10.5, "close": 11, "volume": 100},
            {"timestamp": 4, "open": 11, "high": 12.5, "low": 11.5, "close": 12.2, "volume": 100},
            {"timestamp": 5, "open": 12.2, "high": 14.0, "low": 12.8, "close": 13.6, "volume": 100},
        ]
    )
    out = detect_structure_breaking_fvg(df, pivot_lookup=1)
    assert isinstance(out, list)


def test_detect_high_volume_bars() -> None:
    rows = []
    for i in range(1, 20):
        rows.append({"timestamp": i, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100})
    rows.append({"timestamp": 21, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1000})
    df = make_bars(rows)
    out = detect_high_volume_bars(df, ema_period=12, multiplier=1.5)
    assert any(x["kind"] == "HVB" for x in out)


def test_detect_ob_fvg_stack() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 8, "close": 9, "volume": 100},
            {"timestamp": 2, "open": 9, "high": 12, "low": 7, "close": 11.5, "volume": 100},
            {"timestamp": 3, "open": 12, "high": 14, "low": 12.5, "close": 13, "volume": 100},
        ]
    )
    out = detect_ob_fvg_stack(df)
    assert any(x["kind"] == "OB_FVG_STACK" for x in out)


def test_detect_ppdd() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10.0, "high": 10.5, "low": 9.5, "close": 9.8, "volume": 100},
            {"timestamp": 2, "open": 9.8, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 100},
            {"timestamp": 3, "open": 11.0, "high": 12.5, "low": 8.5, "close": 8.6, "volume": 100},
            {"timestamp": 4, "open": 8.6, "high": 9.2, "low": 8.2, "close": 8.9, "volume": 100},
        ]
    )
    piv = build_pivots_top_bottom(df, pivot_lookup=1)
    out = detect_ppdd(df, piv)
    assert isinstance(out, list)


def test_detect_broken_fractal_provisional_and_confirmed() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 9.5, "close": 10.8, "volume": 100},
            {"timestamp": 2, "open": 10.7, "high": 12.0, "low": 10.2, "close": 11.8, "volume": 100},
            {"timestamp": 3, "open": 11.7, "high": 13.0, "low": 10.9, "close": 12.8, "volume": 100},
            {"timestamp": 4, "open": 12.7, "high": 12.6, "low": 10.1, "close": 10.3, "volume": 100},
            {"timestamp": 5, "open": 10.2, "high": 10.4, "low": 8.8, "close": 9.0, "volume": 100},
            {"timestamp": 6, "open": 9.0, "high": 9.6, "low": 8.6, "close": 9.4, "volume": 100},
            {"timestamp": 7, "open": 9.5, "high": 13.4, "low": 9.3, "close": 13.2, "volume": 100},
        ]
    )
    prov = detect_broken_fractal(df, n=2, mode="provisional")
    conf = detect_broken_fractal(df, n=2, mode="confirmed")
    assert isinstance(prov, list)
    assert isinstance(conf, list)


def test_build_structure_qualifiers_shape() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
            {"timestamp": 2, "open": 10, "high": 13, "low": 9, "close": 12, "volume": 100},
            {"timestamp": 3, "open": 12, "high": 11.5, "low": 8.8, "close": 9.5, "volume": 100},
            {"timestamp": 4, "open": 9.6, "high": 12.8, "low": 9.5, "close": 12.6, "volume": 1000},
            {"timestamp": 5, "open": 12.6, "high": 14.0, "low": 12.7, "close": 13.9, "volume": 1200},
        ]
    )
    out = build_structure_qualifiers(df, pivot_lookup=1)
    assert set(out.keys()) == {
        "structure_breaking_fvg",
        "high_volume_bars",
        "ob_fvg_stack",
        "ppdd",
        "broken_fractal_provisional",
        "broken_fractal_confirmed",
    }
