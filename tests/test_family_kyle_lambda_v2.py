"""ADR-0016 — Kyle's lambda shadow feature: extractor contract tests.

Covers the hand-computed OLS slope, the honest-None refusals (short history,
missing signed volume, missing close, zero variance, degenerate period), the
sign (lambda may be negative), and leak-freedom (no bar after the anchor is
read).
"""

from __future__ import annotations

from governance.family_event_score import ATR_PERIOD
from governance.family_kyle_lambda_v2 import (
    KYLE_LAMBDA_SOURCE,
    kyle_lambda_at,
)

_T0 = 1_700_000_000.0
_STEP = 86_400.0  # daily bars


def _bar(i: int, close: float, signed: float | None) -> dict:
    row: dict = {
        "timestamp": _T0 + i * _STEP,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
    }
    if signed is not None:
        row["signed_volume"] = signed
    return row


def test_source_tag_is_stable() -> None:
    assert KYLE_LAMBDA_SOURCE == "microstructure_kyle_lambda_v2"


def test_hand_computed_positive_slope() -> None:
    # period=3, anchor_idx=3. Window k=1,2,3:
    #   x = signed_volume = [1, 2, 3]
    #   y = close change   = [2, 4, 6]   (slope of y on x is exactly 2.0)
    bars = [
        _bar(0, 10.0, None),  # close[0] read for y_1, signed not needed at idx0
        _bar(1, 12.0, 1.0),   # y_1 = 12-10 = 2, x_1 = 1
        _bar(2, 16.0, 2.0),   # y_2 = 16-12 = 4, x_2 = 2
        _bar(3, 22.0, 3.0),   # y_3 = 22-16 = 6, x_3 = 3
    ]
    assert kyle_lambda_at(bars, 3, period=3) == 2.0


def test_negative_slope_is_returned() -> None:
    # y = -2x over the same x grid -> slope -2.0 (lambda may be negative).
    bars = [
        _bar(0, 10.0, None),
        _bar(1, 8.0, 1.0),    # y_1 = -2, x_1 = 1
        _bar(2, 4.0, 2.0),    # y_2 = -4, x_2 = 2
        _bar(3, -2.0, 3.0),   # y_3 = -6, x_3 = 3
    ]
    assert kyle_lambda_at(bars, 3, period=3) == -2.0


def test_none_when_history_too_short() -> None:
    bars = [_bar(0, 10.0, 1.0), _bar(1, 11.0, 1.0), _bar(2, 13.0, 2.0)]
    # anchor_idx=2 < period=3 -> honest None.
    assert kyle_lambda_at(bars, 2, period=3) is None


def test_none_when_signed_volume_missing_in_window() -> None:
    bars = [
        _bar(0, 10.0, None),
        _bar(1, 12.0, 1.0),
        _bar(2, 16.0, None),  # missing signed volume inside the window
        _bar(3, 22.0, 3.0),
    ]
    assert kyle_lambda_at(bars, 3, period=3) is None


def test_none_when_close_missing_in_window() -> None:
    bars = [
        _bar(0, 10.0, None),
        {"timestamp": _T0 + _STEP, "high": 1.0, "low": 1.0, "signed_volume": 1.0},
        _bar(2, 16.0, 2.0),
        _bar(3, 22.0, 3.0),
    ]
    assert kyle_lambda_at(bars, 3, period=3) is None


def test_none_when_signed_volume_has_zero_variance() -> None:
    # All signed volumes equal -> sxx == 0 -> no defined slope -> None.
    bars = [
        _bar(0, 10.0, None),
        _bar(1, 12.0, 5.0),
        _bar(2, 16.0, 5.0),
        _bar(3, 22.0, 5.0),
    ]
    assert kyle_lambda_at(bars, 3, period=3) is None


def test_none_when_period_below_two() -> None:
    bars = [_bar(i, 10.0 + i, 1.0 + i) for i in range(5)]
    assert kyle_lambda_at(bars, 4, period=1) is None


def test_none_when_anchor_out_of_range() -> None:
    bars = [_bar(i, 10.0 + i, 1.0 + i) for i in range(4)]
    assert kyle_lambda_at(bars, 4, period=3) is None


def test_leak_free_ignores_bars_after_anchor() -> None:
    head = [
        _bar(0, 10.0, None),
        _bar(1, 12.0, 1.0),
        _bar(2, 16.0, 2.0),
        _bar(3, 22.0, 3.0),
    ]
    # Appending arbitrary future bars must not change the value at anchor_idx=3.
    tail = [*head, _bar(4, 999.0, -50.0), _bar(5, -999.0, 80.0)]
    assert kyle_lambda_at(head, 3, period=3) == kyle_lambda_at(tail, 3, period=3)


def test_default_period_uses_atr_lookback() -> None:
    # With the default ATR_PERIOD window and a clean linear impact y = 0.5x,
    # the slope is exactly 0.5 regardless of the (varying) signed-volume grid.
    n = ATR_PERIOD + 2
    closes = [100.0]
    signed: list[float | None] = [None]
    for i in range(1, n):
        x = float(i)  # strictly increasing -> non-zero variance
        signed.append(x)
        closes.append(closes[-1] + 0.5 * x)
    bars = [_bar(i, closes[i], signed[i]) for i in range(n)]
    anchor = n - 1
    result = kyle_lambda_at(bars, anchor)
    assert result is not None
    assert abs(result - 0.5) < 1e-9
