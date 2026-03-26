from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from scripts.smc_session_context import build_dwm_levels, build_killzones, build_opening_levels, build_session_liquidity_context


def _bar(ts: str, open_: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    return {
        "timestamp": int(pd.Timestamp(ts, tz=ZoneInfo("America/New_York")).tz_convert("UTC").timestamp()),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def test_killzone_windows_present() -> None:
    rows = [
        _bar("2026-03-24 20:00", 100, 101, 99.5, 100.3),
        _bar("2026-03-24 22:00", 100.3, 102, 100.1, 101.5),
        _bar("2026-03-25 02:30", 101.5, 103, 101, 102.2),
        _bar("2026-03-25 09:30", 102.2, 103.5, 102, 103.0),
        _bar("2026-03-25 12:00", 103.0, 103.2, 102.4, 102.7),
        _bar("2026-03-25 13:30", 102.7, 104.0, 102.5, 103.8),
    ]
    df = pd.DataFrame(rows)
    kz = build_killzones(df, tz="America/New_York")
    names = {x["name"] for x in kz}
    assert "Asia" in names
    assert "London" in names
    assert "NY AM" in names


def test_dwm_levels_generated() -> None:
    rows = [
        _bar("2026-03-24 10:00", 100, 101, 99, 100.5),
        _bar("2026-03-24 15:00", 100.5, 102, 100.2, 101.8),
        _bar("2026-03-25 10:00", 101.8, 103, 101.5, 102.6),
        _bar("2026-03-25 15:00", 102.6, 104, 102.1, 103.4),
    ]
    df = pd.DataFrame(rows)
    levels = build_dwm_levels(df)
    assert "day_open" in levels
    assert "prev_day_high" in levels
    assert "prev_day_low" in levels


def test_opening_levels_include_defaults() -> None:
    rows = [
        _bar("2026-03-25 00:00", 100, 101, 99, 100.3),
        _bar("2026-03-25 06:00", 100.3, 101.2, 100.1, 100.8),
        _bar("2026-03-25 10:00", 100.8, 101.6, 100.6, 101.3),
        _bar("2026-03-25 14:00", 101.3, 102.0, 101.1, 101.9),
    ]
    df = pd.DataFrame(rows)
    levels = build_opening_levels(df, tz="America/New_York")
    names = {x["name"] for x in levels}
    assert {"00:00", "06:00", "10:00", "14:00"}.issubset(names)


def test_dst_safe_behavior_across_switch_week() -> None:
    rows = [
        _bar("2024-03-08 09:30", 100, 101, 99.8, 100.9),
        _bar("2024-03-11 09:30", 101, 102, 100.7, 101.8),
    ]
    df = pd.DataFrame(rows)
    kz = build_killzones(df, tz="America/New_York")
    assert isinstance(kz, list)


def test_build_session_liquidity_context_shape() -> None:
    rows = [
        _bar("2026-03-25 09:30", 100, 101, 99.8, 100.9),
        _bar("2026-03-25 10:00", 100.9, 101.5, 100.7, 101.2),
        _bar("2026-03-25 12:00", 101.2, 101.6, 100.9, 101.0),
        _bar("2026-03-25 14:00", 101.0, 102.0, 100.8, 101.8),
    ]
    df = pd.DataFrame(rows)
    context = build_session_liquidity_context(df, tz="America/New_York")
    assert set(context.keys()) == {"killzones", "session_pivots", "dwm_levels", "opening_levels"}
