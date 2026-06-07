"""ADR-0020 — unsigned UOA activity shadow feature: extractor tests.

Covers the recent-vs-baseline premium-activity ratio (``abs_uoa_activity_at``):
the hand-computed ``short_mean / long_mean`` over the trailing ``period`` window
versus its ``period * 4`` baseline, the flat/elevated/quiet regimes, the
gap-tolerant no-print bars, leak-freedom, and the honest-None refusals (short
history, corrupt value, negative premium, zero baseline, degenerate period,
anchor out of range).

The direction-free companion to ``signed_uoa_notional_at``: it reads only the
embedded ``uoa_abs_notional`` key, so the bars here carry only that key.
"""

from __future__ import annotations

from governance.family_signed_uoa_notional_v2 import (
    ABS_UOA_ACTIVITY_SOURCE,
    abs_uoa_activity_at,
)

_T0 = 1_700_000_000.0
_STEP = 86_400.0  # daily bars


def _bar(i: int, *, abs_notional: float | None, close: float = 100.0) -> dict:
    """One bar carrying only the unsigned ``uoa_abs_notional`` key.

    A ``None`` ``abs_notional`` embeds no key at all -> the bar saw no option
    prints (gap-tolerant: contributes 0 to both windows).
    """
    row: dict = {
        "timestamp": _T0 + i * _STEP,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
    }
    if abs_notional is not None:
        row["uoa_abs_notional"] = abs_notional
    return row


def test_source_tag_is_stable() -> None:
    assert ABS_UOA_ACTIVITY_SOURCE == "options_flow_abs_uoa_activity_v2"


def test_hand_computed_activity_ratio() -> None:
    # period=1 -> baseline_period=4. Window k=0..3, abs=[100,200,300,400]:
    #   short window (k=3)     = 400 -> short_mean = 400 / 1 = 400
    #   baseline window (k0..3)= 1000 -> long_mean = 1000 / 4 = 250
    #   activity = 400 / 250 = 1.6
    bars = [
        _bar(0, abs_notional=100.0),
        _bar(1, abs_notional=200.0),
        _bar(2, abs_notional=300.0),
        _bar(3, abs_notional=400.0),
    ]
    assert abs_uoa_activity_at(bars, 3, period=1) == 1.6


def test_flat_activity_is_one() -> None:
    # Constant premium -> recent equals its own baseline -> exactly 1.0.
    bars = [_bar(i, abs_notional=500.0) for i in range(4)]
    assert abs_uoa_activity_at(bars, 3, period=1) == 1.0


def test_elevated_recent_activity_above_one() -> None:
    # A recent premium spike -> ratio > 1. abs=[100,100,100,700]:
    #   short = 700, long = 1000 / 4 = 250 -> 2.8
    bars = [
        _bar(0, abs_notional=100.0),
        _bar(1, abs_notional=100.0),
        _bar(2, abs_notional=100.0),
        _bar(3, abs_notional=700.0),
    ]
    assert abs_uoa_activity_at(bars, 3, period=1) == 2.8


def test_quiet_recent_activity_below_one() -> None:
    # Recent lull after a busy baseline -> ratio < 1. abs=[700,100,100,100]:
    #   short = 100, long = 1000 / 4 = 250 -> 0.4
    bars = [
        _bar(0, abs_notional=700.0),
        _bar(1, abs_notional=100.0),
        _bar(2, abs_notional=100.0),
        _bar(3, abs_notional=100.0),
    ]
    assert abs_uoa_activity_at(bars, 3, period=1) == 0.4


def test_longer_period_window() -> None:
    # period=2 -> baseline_period=8, need anchor_idx >= 7.
    #   abs = [100]*6 + [400, 400]
    #   short window (k=6,7)   = 800 -> short_mean = 800 / 2 = 400
    #   baseline window (k0..7)= 1400 -> long_mean = 1400 / 8 = 175
    #   activity = 400 / 175
    bars = [_bar(i, abs_notional=100.0) for i in range(6)]
    bars += [_bar(6, abs_notional=400.0), _bar(7, abs_notional=400.0)]
    assert abs_uoa_activity_at(bars, 7, period=2) == 400.0 / 175.0


def test_no_print_bars_are_gap_tolerant() -> None:
    # Bars with no embedded key saw no prints -> contribute 0 to both windows
    # (not a refusal). abs=[None,None,None,400]:
    #   short = 400, long = 400 / 4 = 100 -> 4.0
    bars = [
        _bar(0, abs_notional=None),
        _bar(1, abs_notional=None),
        _bar(2, abs_notional=None),
        _bar(3, abs_notional=400.0),
    ]
    assert abs_uoa_activity_at(bars, 3, period=1) == 4.0


def test_none_when_history_too_short() -> None:
    # period=1 needs baseline_period=4 bars of history (anchor_idx >= 3).
    bars = [_bar(i, abs_notional=100.0) for i in range(3)]
    assert abs_uoa_activity_at(bars, 2, period=1) is None


def test_none_when_baseline_has_no_premium() -> None:
    # OPRA never pulled (or whole baseline window quiet) -> baseline total is
    # zero -> undefined ratio -> honest None.
    bars = [_bar(i, abs_notional=None) for i in range(4)]
    assert abs_uoa_activity_at(bars, 3, period=1) is None


def test_none_when_abs_corrupt() -> None:
    bars = [
        _bar(0, abs_notional=100.0),
        _bar(1, abs_notional=100.0),
        _bar(2, abs_notional=100.0),
        _bar(3, abs_notional=float("nan")),
    ]
    assert abs_uoa_activity_at(bars, 3, period=1) is None


def test_none_when_abs_negative() -> None:
    # A negative premium magnitude is impossible (sum of price*size*100) ->
    # treated as corrupt -> refuse the window.
    bars = [
        _bar(0, abs_notional=100.0),
        _bar(1, abs_notional=100.0),
        _bar(2, abs_notional=100.0),
        _bar(3, abs_notional=-5.0),
    ]
    assert abs_uoa_activity_at(bars, 3, period=1) is None


def test_none_on_degenerate_period() -> None:
    bars = [_bar(i, abs_notional=100.0) for i in range(4)]
    assert abs_uoa_activity_at(bars, 3, period=0) is None


def test_none_when_anchor_out_of_range() -> None:
    bars = [_bar(i, abs_notional=100.0) for i in range(4)]
    assert abs_uoa_activity_at(bars, 9, period=1) is None


def test_leak_free_ignores_bars_after_anchor() -> None:
    # A huge premium print AFTER the anchor must not change the value.
    base = [_bar(i, abs_notional=100.0) for i in range(4)]
    with_future = [*base, _bar(4, abs_notional=9_999_999.0)]
    assert abs_uoa_activity_at(base, 3, period=1) == abs_uoa_activity_at(
        with_future, 3, period=1
    )
