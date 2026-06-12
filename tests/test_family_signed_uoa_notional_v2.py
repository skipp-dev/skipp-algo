"""ADR-0020 — signed UOA notional shadow feature: extractor tests.

Covers the hand-computed activity-weighted signed imbalance ratio, the
[-1, +1] range and clamp, the inverse-of-equity aggressor sign (A bullish,
B bearish), the gap-tolerant no-print bars, and the honest-None refusals
(short history, corrupt value, half-embedded pair, zero premium, degenerate
period, anchor out of range), and leak-freedom.
"""

from __future__ import annotations

from governance.family_signed_uoa_notional_v2 import (
    SIGNED_UOA_NOTIONAL_SOURCE,
    signed_uoa_notional_at,
)

_T0 = 1_700_000_000.0
_STEP = 86_400.0  # daily bars


def _bar(
    i: int,
    *,
    signed: float | None,
    abs_notional: float | None,
    close: float = 100.0,
) -> dict:
    row: dict = {
        "timestamp": _T0 + i * _STEP,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
    }
    if signed is not None:
        row["uoa_signed_notional"] = signed
    if abs_notional is not None:
        row["uoa_abs_notional"] = abs_notional
    return row


def test_source_tag_is_stable() -> None:
    assert SIGNED_UOA_NOTIONAL_SOURCE == "options_flow_signed_uoa_notional_v2"


def test_hand_computed_activity_weighted_signed_ratio() -> None:
    # period=3, window k=0,1,2:
    #   signed = [ 300, -100,  200] -> sum  400
    #   abs    = [1000, 1000, 1000] -> sum 3000
    #   signed_uoa = 400 / 3000 = 0.133333...
    bars = [
        _bar(0, signed=300.0, abs_notional=1000.0),
        _bar(1, signed=-100.0, abs_notional=1000.0),
        _bar(2, signed=200.0, abs_notional=1000.0),
    ]
    assert signed_uoa_notional_at(bars, 2, period=3) == 400.0 / 3000.0


def test_fully_bullish_flow_is_plus_one() -> None:
    # Every bar fully ask-lifting (bullish) -> +1.0.
    bars = [
        _bar(0, signed=1000.0, abs_notional=1000.0),
        _bar(1, signed=500.0, abs_notional=500.0),
    ]
    assert signed_uoa_notional_at(bars, 1, period=2) == 1.0


def test_fully_bearish_flow_is_minus_one() -> None:
    # Every bar fully bid-hitting (bearish) -> -1.0 (sign is preserved, unlike
    # OFI which takes the absolute value).
    bars = [
        _bar(0, signed=-1000.0, abs_notional=1000.0),
        _bar(1, signed=-500.0, abs_notional=500.0),
    ]
    assert signed_uoa_notional_at(bars, 1, period=2) == -1.0


def test_balanced_flow_is_zero() -> None:
    # Bullish and bearish premium cancel -> 0.0 despite heavy turnover.
    bars = [
        _bar(0, signed=1000.0, abs_notional=1000.0),
        _bar(1, signed=-1000.0, abs_notional=1000.0),
    ]
    assert signed_uoa_notional_at(bars, 1, period=2) == 0.0


def test_no_print_bars_are_gap_tolerant() -> None:
    # Bars 0 and 2 saw no option prints (no keys) -> contribute 0; only bar 1's
    # flow counts. signed = 200 / abs = 1000 -> 0.2.
    bars = [
        _bar(0, signed=None, abs_notional=None),
        _bar(1, signed=200.0, abs_notional=1000.0),
        _bar(2, signed=None, abs_notional=None),
    ]
    assert signed_uoa_notional_at(bars, 2, period=3) == 0.2


def test_none_when_history_too_short() -> None:
    bars = [
        _bar(0, signed=300.0, abs_notional=1000.0),
        _bar(1, signed=-100.0, abs_notional=1000.0),
    ]
    assert signed_uoa_notional_at(bars, 1, period=3) is None


def test_none_when_window_has_no_premium() -> None:
    # OPRA pulled but the whole window saw no prints (or all abs == 0) -> the
    # ratio is undefined -> honest None.
    bars = [
        _bar(0, signed=None, abs_notional=None),
        _bar(1, signed=None, abs_notional=None),
    ]
    assert signed_uoa_notional_at(bars, 1, period=2) is None


def test_none_when_signed_present_but_abs_absent() -> None:
    # Half-embedded pair is malformed (producer always embeds both) -> refuse.
    bars = [
        _bar(0, signed=300.0, abs_notional=1000.0),
        _bar(1, signed=200.0, abs_notional=None),
    ]
    assert signed_uoa_notional_at(bars, 1, period=2) is None


def test_none_when_abs_present_but_signed_absent() -> None:
    bars = [
        _bar(0, signed=300.0, abs_notional=1000.0),
        _bar(1, signed=None, abs_notional=1000.0),
    ]
    assert signed_uoa_notional_at(bars, 1, period=2) is None


def test_none_when_signed_corrupt() -> None:
    bars = [
        _bar(0, signed=300.0, abs_notional=1000.0),
        _bar(1, signed=float("nan"), abs_notional=1000.0),
    ]
    assert signed_uoa_notional_at(bars, 1, period=2) is None


def test_none_when_abs_negative() -> None:
    bars = [
        _bar(0, signed=300.0, abs_notional=1000.0),
        _bar(1, signed=200.0, abs_notional=-5.0),
    ]
    assert signed_uoa_notional_at(bars, 1, period=2) is None


def test_none_on_degenerate_period() -> None:
    bars = [_bar(0, signed=300.0, abs_notional=1000.0)]
    assert signed_uoa_notional_at(bars, 0, period=0) is None


def test_none_when_anchor_out_of_range() -> None:
    bars = [_bar(0, signed=300.0, abs_notional=1000.0)]
    assert signed_uoa_notional_at(bars, 5, period=1) is None


def test_leak_free_ignores_bars_after_anchor() -> None:
    # A huge bearish print AFTER the anchor must not change the value.
    base = [
        _bar(0, signed=200.0, abs_notional=1000.0),
        _bar(1, signed=200.0, abs_notional=1000.0),
    ]
    with_future = [*base, _bar(2, signed=-9_999_999.0, abs_notional=9_999_999.0)]
    assert signed_uoa_notional_at(base, 1, period=2) == signed_uoa_notional_at(
        with_future, 1, period=2
    )


def test_clamp_keeps_ratio_in_bounds() -> None:
    # Float rounding can nudge |signed| a hair over abs; the result must stay in
    # [-1, +1]. Construct signed == abs exactly so the ratio is the boundary.
    bars = [
        _bar(0, signed=1000.0, abs_notional=1000.0),
        _bar(1, signed=1000.0, abs_notional=1000.0),
    ]
    val = signed_uoa_notional_at(bars, 1, period=2)
    assert val is not None
    assert -1.0 <= val <= 1.0
