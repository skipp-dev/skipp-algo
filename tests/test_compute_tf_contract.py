"""Tests for multi-timeframe aggregation in compute.py."""
from __future__ import annotations

import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from services.live_overlay_daemon import compute


def _minute_bars(n: int, start_price: float = 100.0) -> list[dict[str, Any]]:
    bars = []
    for i in range(n):
        bars.append({
            "open": start_price,
            "high": start_price + 1.0,
            "low": start_price - 1.0,
            "close": start_price,
            "volume": 100.0,
            # Databento ohlcv-1m stamps ts_event at the bar OPEN: the i-th 1m
            # bar opens at minute (240 + i) and closes at (240 + i + 1). The
            # 240-minute base is clock-aligned to every bucket (5m/10m/4H) and
            # keeps ts_event > 0 (0 is the ignored missing-stamp sentinel).
            "ts_event": (240 + i) * 60_000_000_000,
        })
    return bars


def test_aggregate_5m_buckets_minute_bars() -> None:
    bars = _minute_bars(10)
    aggregated = compute._aggregate_bars(bars, "5m")
    assert len(aggregated) == 2
    first = aggregated[0]
    second = aggregated[1]
    assert first["open"] == 100.0
    assert first["close"] == 100.0
    assert first["high"] == 101.0
    assert first["low"] == 99.0
    assert first["volume"] == 5 * 100.0
    assert first["ts_event"] == (240 + 5) * 60_000_000_000  # bucket close of opens 240-244
    assert second["volume"] == 5 * 100.0
    assert second["ts_event"] == (240 + 10) * 60_000_000_000  # bucket close of opens 245-249


def test_aggregate_10m_combines_five_minute_bars() -> None:
    bars = _minute_bars(20)
    # Make the last 5-minute bucket distinct
    for i in range(15, 20):
        bars[i]["close"] = 200.0
        bars[i]["volume"] = 50.0
        bars[i]["high"] = 205.0
        bars[i]["low"] = 195.0

    aggregated = compute._aggregate_bars(bars, "10m")
    assert len(aggregated) == 2
    last = aggregated[-1]
    assert last["open"] == 100.0
    assert last["close"] == 200.0
    assert last["high"] == 205.0
    assert last["low"] == 99.0
    assert last["volume"] == 5 * 100.0 + 5 * 50.0


@pytest.mark.parametrize(
    ("session_date", "expected_utc_offset"),
    [
        (datetime.date(2026, 1, 15), datetime.timedelta(hours=-5)),
        (datetime.date(2026, 7, 24), datetime.timedelta(hours=-4)),
    ],
)
def test_aggregate_hourly_uses_new_york_rth_session_across_dst(
    session_date: datetime.date,
    expected_utc_offset: datetime.timedelta,
) -> None:
    market_tz = ZoneInfo("America/New_York")
    session_open = datetime.datetime.combine(
        session_date,
        datetime.time(9, 30),
        tzinfo=market_tz,
    )
    assert session_open.utcoffset() == expected_utc_offset

    bars = [
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
            "ts_event": int(
                (session_open + datetime.timedelta(minutes=minute)).timestamp()
                * 1_000_000_000
            ),
        }
        for minute in range(390)
    ]
    aggregated = compute._aggregate_bars(bars, "1H")

    assert [bar["volume"] for bar in aggregated] == [
        60.0,
        60.0,
        60.0,
        60.0,
        60.0,
        60.0,
        30.0,
    ]
    assert [
        datetime.datetime.fromtimestamp(
            int(bar["ts_event"]) / 1_000_000_000,
            market_tz,
        ).strftime("%H:%M")
        for bar in aggregated
    ] == ["10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00"]


def test_aggregate_four_hour_bars_anchor_to_rth_and_ignore_extended_hours() -> None:
    market_tz = ZoneInfo("America/New_York")
    session_open = datetime.datetime(
        2026,
        7,
        24,
        9,
        30,
        tzinfo=market_tz,
    )
    bars = [
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
            "ts_event": int(
                (session_open + datetime.timedelta(minutes=minute)).timestamp()
                * 1_000_000_000
            ),
        }
        for minute in range(-1, 391)
    ]

    aggregated = compute._aggregate_bars(bars, "4H")

    assert [bar["volume"] for bar in aggregated] == [240.0, 150.0]
    assert [
        datetime.datetime.fromtimestamp(
            int(bar["ts_event"]) / 1_000_000_000,
            market_tz,
        ).strftime("%H:%M")
        for bar in aggregated
    ] == ["13:30", "16:00"]


@pytest.mark.parametrize(
    ("timeframe", "expected_volumes", "expected_closes"),
    [
        ("1H", [60.0, 60.0, 60.0, 30.0], ["10:30", "11:30", "12:30", "13:00"]),
        ("4H", [210.0], ["13:00"]),
    ],
)
def test_aggregate_intraday_bars_honours_nyse_early_close(
    timeframe: str,
    expected_volumes: list[float],
    expected_closes: list[str],
) -> None:
    market_tz = ZoneInfo("America/New_York")
    session_open = datetime.datetime(2026, 11, 27, 9, 30, tzinfo=market_tz)
    bars = [
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
            "ts_event": int(
                (session_open + datetime.timedelta(minutes=minute)).timestamp()
                * 1_000_000_000
            ),
        }
        for minute in range(390)
    ]

    aggregated = compute._aggregate_bars(bars, timeframe)

    assert [bar["volume"] for bar in aggregated] == expected_volumes
    assert [
        datetime.datetime.fromtimestamp(
            int(bar["ts_event"]) / 1_000_000_000,
            market_tz,
        ).strftime("%H:%M")
        for bar in aggregated
    ] == expected_closes


def test_aggregate_higher_timeframe_changes_indicators() -> None:
    bars = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0, "ts_event": (240 + i) * 60_000_000_000}
        for i in range(25)
    ]

    payload_5m = compute.build_payload(
        "AAPL", bars, {"tone": "NEUTRAL", "global_heat": 0.0}, max_stale_secs=3600, tf="5m"
    )
    payload_4h = compute.build_payload(
        "AAPL", bars, {"tone": "NEUTRAL", "global_heat": 0.0}, max_stale_secs=3600, tf="4H"
    )

    # With only 25 1m bars, 4H aggregation yields a single bar -> different
    # indicator behaviour than 5m window with multiple bars.
    assert payload_5m["flow_rel_vol"] is not None
    assert payload_4h["flow_rel_vol"] is None  # only one aggregated bar, no prior avg


def test_aggregate_unsupported_timeframe_raises() -> None:
    with pytest.raises(ValueError):
        compute._aggregate_bars([], "1D")


def test_aggregate_skips_malformed_bars() -> None:
    bars = [
        # ts_event=0 is a sentinel/fallback value and must be ignored.
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100.0, "ts_event": 0},
        {"open": "bad", "high": None, "low": 99.0, "close": None, "volume": 100.0, "ts_event": 10 * 60_000_000_000},
    ]
    aggregated = compute._aggregate_bars(bars, "10m")
    assert len(aggregated) == 0


def test_aggregate_skips_missing_ts_event() -> None:
    bars = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100.0},
        {"open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 110.0, "ts_event": 60_000_000_000},
    ]
    aggregated = compute._aggregate_bars(bars, "5m")
    assert len(aggregated) == 1
    assert aggregated[0]["close"] == 101.5


def test_bars_for_timeframe_falls_back_when_aggregation_empty() -> None:
    bars = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100.0},
        {"open": 101.0, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 110.0},
    ]
    used = compute._bars_for_timeframe(bars, "4H")
    assert used == bars


def test_bars_for_timeframe_does_not_fallback_for_timestamped_malformed_bars() -> None:
    bars = [
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": None,
            "volume": 100.0,
            "ts_event": 60_000_000_000,
        },
        {
            "open": 101.0,
            "high": 102.0,
            "low": 100.0,
            "close": None,
            "volume": 110.0,
            "ts_event": 120_000_000_000,
        },
    ]
    used = compute._bars_for_timeframe(bars, "5m")
    assert used == []
