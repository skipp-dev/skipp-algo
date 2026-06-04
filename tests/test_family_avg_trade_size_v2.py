"""ADR-0016 / ADR-0019 — average trade size shadow feature: extractor tests.

Covers the hand-computed volume-weighted mean shares-per-trade, the honest-None
refusals (short history, missing volume, missing trade count, zero total count,
degenerate period, anchor out of range), and leak-freedom (no bar after the
anchor is read).
"""

from __future__ import annotations

from governance.family_avg_trade_size_v2 import (
    AVG_TRADE_SIZE_SOURCE,
    average_trade_size_at,
)
from governance.family_event_score import ATR_PERIOD

_T0 = 1_700_000_000.0
_STEP = 86_400.0  # daily bars


def _bar(
    i: int,
    *,
    volume: float | None,
    trade_count: float | None,
    close: float = 100.0,
) -> dict:
    row: dict = {
        "timestamp": _T0 + i * _STEP,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
    }
    if volume is not None:
        row["volume"] = volume
    if trade_count is not None:
        row["trade_count"] = trade_count
    return row


def test_source_tag_is_stable() -> None:
    assert AVG_TRADE_SIZE_SOURCE == "microstructure_avg_trade_size_v2"


def test_hand_computed_volume_weighted_mean() -> None:
    # period=3, anchor_idx=2. Window k=0,1,2:
    #   volume      = [100, 200, 300] -> sum 600
    #   trade_count = [  4,   6,  10] -> sum 20
    #   avg trade size = 600 / 20 = 30.0  (NOT mean of per-bar ratios 25,33.3,30)
    bars = [
        _bar(0, volume=100.0, trade_count=4.0),
        _bar(1, volume=200.0, trade_count=6.0),
        _bar(2, volume=300.0, trade_count=10.0),
    ]
    assert average_trade_size_at(bars, 2, period=3) == 30.0


def test_activity_weighting_not_simple_ratio_mean() -> None:
    # A thin high-ratio bar must not dominate: aggregate weighting pins the
    # estimate to the bulk of the activity.
    bars = [
        _bar(0, volume=1000.0, trade_count=100.0),  # ratio 10
        _bar(1, volume=10.0, trade_count=1.0),       # ratio 10
    ]
    # sum 1010 / sum 101 = 10.0
    assert average_trade_size_at(bars, 1, period=2) == 10.0


def test_none_when_history_too_short() -> None:
    bars = [
        _bar(0, volume=100.0, trade_count=4.0),
        _bar(1, volume=200.0, trade_count=6.0),
    ]
    # anchor_idx=1 < period-1=2 -> honest None.
    assert average_trade_size_at(bars, 1, period=3) is None


def test_none_when_volume_missing_in_window() -> None:
    bars = [
        _bar(0, volume=100.0, trade_count=4.0),
        _bar(1, volume=None, trade_count=6.0),  # missing volume inside window
        _bar(2, volume=300.0, trade_count=10.0),
    ]
    assert average_trade_size_at(bars, 2, period=3) is None


def test_none_when_trade_count_missing_in_window() -> None:
    bars = [
        _bar(0, volume=100.0, trade_count=4.0),
        _bar(1, volume=200.0, trade_count=None),  # OHLCV-only / no-trade bar
        _bar(2, volume=300.0, trade_count=10.0),
    ]
    assert average_trade_size_at(bars, 2, period=3) is None


def test_none_when_total_trade_count_zero() -> None:
    bars = [
        _bar(0, volume=0.0, trade_count=0.0),
        _bar(1, volume=0.0, trade_count=0.0),
        _bar(2, volume=0.0, trade_count=0.0),
    ]
    assert average_trade_size_at(bars, 2, period=3) is None


def test_none_when_period_below_one() -> None:
    bars = [_bar(i, volume=100.0, trade_count=4.0) for i in range(5)]
    assert average_trade_size_at(bars, 4, period=0) is None


def test_none_when_anchor_out_of_range() -> None:
    bars = [_bar(i, volume=100.0, trade_count=4.0) for i in range(4)]
    assert average_trade_size_at(bars, 4, period=3) is None


def test_none_when_volume_negative() -> None:
    bars = [
        _bar(0, volume=100.0, trade_count=4.0),
        _bar(1, volume=-5.0, trade_count=6.0),  # corrupt negative volume
        _bar(2, volume=300.0, trade_count=10.0),
    ]
    assert average_trade_size_at(bars, 2, period=3) is None


def test_leak_free_ignores_bars_after_anchor() -> None:
    head = [
        _bar(0, volume=100.0, trade_count=4.0),
        _bar(1, volume=200.0, trade_count=6.0),
        _bar(2, volume=300.0, trade_count=10.0),
    ]
    # Appending arbitrary future bars must not change the value at anchor_idx=2.
    tail = [
        *head,
        _bar(3, volume=99999.0, trade_count=1.0),
        _bar(4, volume=1.0, trade_count=99999.0),
    ]
    assert average_trade_size_at(head, 2, period=3) == average_trade_size_at(
        tail, 2, period=3
    )


def test_default_period_uses_atr_lookback() -> None:
    # Constant shares-per-trade of 25 on every bar -> aggregate is exactly 25.0
    # over the default ATR_PERIOD window.
    n = ATR_PERIOD + 2
    bars = [_bar(i, volume=250.0, trade_count=10.0) for i in range(n)]
    anchor = n - 1
    result = average_trade_size_at(bars, anchor)
    assert result is not None
    assert abs(result - 25.0) < 1e-9
