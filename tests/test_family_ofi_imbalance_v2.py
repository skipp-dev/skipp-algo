"""ADR-0016 / ADR-0019 — order-flow imbalance shadow feature: extractor tests.

Covers the hand-computed activity-weighted imbalance ratio, the [0,1] range and
clamp, the honest-None refusals (short history, missing signed/abs volume, zero
traded size, degenerate period, anchor out of range), and leak-freedom.
"""

from __future__ import annotations

from governance.family_event_score import ATR_PERIOD
from governance.family_ofi_imbalance_v2 import (
    OFI_IMBALANCE_SOURCE,
    ofi_imbalance_at,
)

_T0 = 1_700_000_000.0
_STEP = 86_400.0  # daily bars


def _bar(
    i: int,
    *,
    signed: float | None,
    abs_vol: float | None,
    close: float = 100.0,
) -> dict:
    row: dict = {
        "timestamp": _T0 + i * _STEP,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
    }
    if signed is not None:
        row["signed_volume"] = signed
    if abs_vol is not None:
        row["abs_volume"] = abs_vol
    return row


def test_source_tag_is_stable() -> None:
    assert OFI_IMBALANCE_SOURCE == "microstructure_ofi_imbalance_v2"


def test_hand_computed_activity_weighted_ratio() -> None:
    # period=3, window k=0,1,2:
    #   signed = [ 30, -10,  20] -> sum  40
    #   abs    = [100, 100, 100] -> sum 300
    #   OFI = |40| / 300 = 0.133333...
    bars = [
        _bar(0, signed=30.0, abs_vol=100.0),
        _bar(1, signed=-10.0, abs_vol=100.0),
        _bar(2, signed=20.0, abs_vol=100.0),
    ]
    assert ofi_imbalance_at(bars, 2, period=3) == 40.0 / 300.0


def test_fully_one_sided_flow_is_one() -> None:
    # Every bar fully one-sided in the same direction -> OFI == 1.0.
    bars = [
        _bar(0, signed=100.0, abs_vol=100.0),
        _bar(1, signed=50.0, abs_vol=50.0),
    ]
    assert ofi_imbalance_at(bars, 1, period=2) == 1.0


def test_balanced_two_sided_flow_is_zero() -> None:
    # Net signed flow cancels exactly -> OFI == 0.0 despite heavy turnover.
    bars = [
        _bar(0, signed=100.0, abs_vol=100.0),
        _bar(1, signed=-100.0, abs_vol=100.0),
    ]
    assert ofi_imbalance_at(bars, 1, period=2) == 0.0


def test_none_when_history_too_short() -> None:
    bars = [
        _bar(0, signed=30.0, abs_vol=100.0),
        _bar(1, signed=-10.0, abs_vol=100.0),
    ]
    assert ofi_imbalance_at(bars, 1, period=3) is None


def test_none_when_signed_volume_missing_in_window() -> None:
    bars = [
        _bar(0, signed=30.0, abs_vol=100.0),
        _bar(1, signed=None, abs_vol=100.0),
        _bar(2, signed=20.0, abs_vol=100.0),
    ]
    assert ofi_imbalance_at(bars, 2, period=3) is None


def test_none_when_abs_volume_missing_in_window() -> None:
    bars = [
        _bar(0, signed=30.0, abs_vol=100.0),
        _bar(1, signed=-10.0, abs_vol=None),  # OHLCV-only / no-trade bar
        _bar(2, signed=20.0, abs_vol=100.0),
    ]
    assert ofi_imbalance_at(bars, 2, period=3) is None


def test_none_when_total_abs_volume_zero() -> None:
    bars = [
        _bar(0, signed=0.0, abs_vol=0.0),
        _bar(1, signed=0.0, abs_vol=0.0),
        _bar(2, signed=0.0, abs_vol=0.0),
    ]
    assert ofi_imbalance_at(bars, 2, period=3) is None


def test_none_when_abs_volume_negative() -> None:
    bars = [
        _bar(0, signed=30.0, abs_vol=100.0),
        _bar(1, signed=-10.0, abs_vol=-5.0),  # corrupt negative magnitude
        _bar(2, signed=20.0, abs_vol=100.0),
    ]
    assert ofi_imbalance_at(bars, 2, period=3) is None


def test_none_when_period_below_one() -> None:
    bars = [_bar(i, signed=10.0, abs_vol=100.0) for i in range(5)]
    assert ofi_imbalance_at(bars, 4, period=0) is None


def test_none_when_anchor_out_of_range() -> None:
    bars = [_bar(i, signed=10.0, abs_vol=100.0) for i in range(4)]
    assert ofi_imbalance_at(bars, 4, period=3) is None


def test_ratio_clamped_to_one() -> None:
    # |signed| nominally equals abs here; float summation must never exceed 1.0.
    bars = [_bar(i, signed=100.0, abs_vol=100.0) for i in range(ATR_PERIOD)]
    result = ofi_imbalance_at(bars, ATR_PERIOD - 1)
    assert result is not None
    assert result <= 1.0


def test_leak_free_ignores_bars_after_anchor() -> None:
    head = [
        _bar(0, signed=30.0, abs_vol=100.0),
        _bar(1, signed=-10.0, abs_vol=100.0),
        _bar(2, signed=20.0, abs_vol=100.0),
    ]
    tail = [
        *head,
        _bar(3, signed=999.0, abs_vol=999.0),
        _bar(4, signed=-999.0, abs_vol=999.0),
    ]
    assert ofi_imbalance_at(head, 2, period=3) == ofi_imbalance_at(
        tail, 2, period=3
    )


def test_default_period_uses_atr_lookback() -> None:
    # Constant 25% net one-sidedness on every bar -> aggregate is exactly 0.25.
    n = ATR_PERIOD + 2
    bars = [_bar(i, signed=25.0, abs_vol=100.0) for i in range(n)]
    anchor = n - 1
    result = ofi_imbalance_at(bars, anchor)
    assert result is not None
    assert abs(result - 0.25) < 1e-9
