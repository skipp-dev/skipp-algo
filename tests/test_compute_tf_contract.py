"""Tests for multi-timeframe aggregation in compute.py."""
from __future__ import annotations

from typing import Any

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
            # Model Databento bar-close stamps: the i-th 1m bar closes at
            # (i + 1) minutes, not at minute start.
            "ts_event": (i + 1) * 60_000_000_000,
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
    assert first["ts_event"] == 5 * 60_000_000_000
    assert second["volume"] == 5 * 100.0
    assert second["ts_event"] == 10 * 60_000_000_000


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


def test_aggregate_higher_timeframe_changes_indicators() -> None:
    bars = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0, "ts_event": (i + 1) * 60_000_000_000}
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
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100.0, "ts_event": 0},
        {"open": "bad", "high": None, "low": 99.0, "close": None, "volume": 100.0, "ts_event": 10 * 60_000_000_000},
    ]
    aggregated = compute._aggregate_bars(bars, "10m")
    assert len(aggregated) == 1


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
