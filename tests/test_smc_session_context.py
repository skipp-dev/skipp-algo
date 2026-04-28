from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from scripts.smc_session_context import (
    build_dwm_levels,
    build_killzones,
    build_opening_levels,
    build_session_liquidity_context,
)


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


def test_killzones_accept_datetime_timestamps() -> None:
    rows = [
        {"timestamp": pd.Timestamp("2026-03-24T00:00:00Z"), "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.3, "volume": 100.0},
        {"timestamp": pd.Timestamp("2026-03-24T06:30:00Z"), "open": 100.3, "high": 102.0, "low": 100.1, "close": 101.5, "volume": 100.0},
        {"timestamp": pd.Timestamp("2026-03-24T13:30:00Z"), "open": 101.5, "high": 103.0, "low": 101.0, "close": 102.2, "volume": 100.0},
    ]

    kz = build_killzones(pd.DataFrame(rows), tz="America/New_York")

    assert {item["name"] for item in kz} == {"Asia", "London", "NY AM"}


def test_dwm_levels_accept_datetime_timestamps() -> None:
    rows = [
        {"timestamp": pd.Timestamp("2026-03-24T14:00:00Z"), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100.0},
        {"timestamp": pd.Timestamp("2026-03-24T19:00:00Z"), "open": 100.5, "high": 102.0, "low": 100.2, "close": 101.8, "volume": 100.0},
        {"timestamp": pd.Timestamp("2026-03-25T14:00:00Z"), "open": 101.8, "high": 103.0, "low": 101.5, "close": 102.6, "volume": 100.0},
        {"timestamp": pd.Timestamp("2026-03-25T19:00:00Z"), "open": 102.6, "high": 104.0, "low": 102.1, "close": 103.4, "volume": 100.0},
    ]

    levels = build_dwm_levels(pd.DataFrame(rows))

    assert levels["day_open"] == 101.8
    assert levels["prev_day_high"] == 102.0
    assert levels["prev_day_low"] == 99.0


def test_dwm_levels_buckets_by_local_tz_not_utc() -> None:
    """Bars in a single ET trading day must aggregate into one ``_day``
    bucket even when the ET → UTC conversion straddles UTC midnight.

    Pre-fix: ``build_dwm_levels`` bucketed by ``_dt.dt.floor("D")`` on the
    UTC-anchored series, so a Monday 21:00 ET bar (= Tuesday 01:00 UTC)
    was attributed to Tuesday's bucket — silently mis-aligning
    prev_day_high / prev_week_high vs. ``build_killzones`` (which uses
    ET via ``_to_local_bars``). Found via SMC bug-hunt v2 phase 1.
    """
    rows = [
        # Monday ET — both bars are Monday's session, but the 21:00 ET bar
        # is already Tuesday in UTC.
        {"timestamp": pd.Timestamp("2026-03-23T22:00:00Z"), "open": 100.0, "high": 200.0, "low": 99.0, "close": 199.0, "volume": 100.0},
        {"timestamp": pd.Timestamp("2026-03-24T01:00:00Z"), "open": 199.0, "high": 300.0, "low": 198.0, "close": 299.0, "volume": 100.0},
        # Tuesday ET
        {"timestamp": pd.Timestamp("2026-03-24T14:00:00Z"), "open": 299.0, "high": 150.0, "low": 140.0, "close": 145.0, "volume": 100.0},
        # Wednesday ET (current "day" — so prev_day_* must look at Tuesday)
        {"timestamp": pd.Timestamp("2026-03-25T14:00:00Z"), "open": 145.0, "high": 120.0, "low": 110.0, "close": 115.0, "volume": 100.0},
    ]

    levels = build_dwm_levels(pd.DataFrame(rows), tz="America/New_York")

    # Tuesday (the prev day from Wednesday's POV) high must NOT include
    # the 300.0 spike that actually belongs to Monday's post-market.
    assert levels["prev_day_high"] == 150.0, levels
    assert levels["day_open"] == 145.0, levels
