"""ADR-0021 — VRVP volume-profile location shadow features: extractor tests.

Covers the two recorded-only location scalars over the trailing volume profile:
the signed range-normalised VPOC distance (sign + bounds), the discrete
value-area position (-1 below VAL / 0 inside / +1 above VAH), the honest-None
refusals (anchor out of range, window underflow, missing close, degenerate
price range), and point-in-time leak-freedom.
"""

from __future__ import annotations

from governance.family_vrvp_v2 import (
    VRVP_SOURCE,
    vrvp_value_area_position_at,
    vrvp_vpoc_distance_at,
)

_T0 = 1_700_000_000.0
_STEP = 900.0  # 15-minute bars


def _bar(
    *,
    high: float,
    low: float,
    close: float,
    volume: float,
    i: int = 0,
) -> dict:
    return {
        "timestamp": _T0 + i * _STEP,
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _mass_at_100(n: int) -> list[dict]:
    """``n`` bars piling volume in a tight band around price 100."""

    return [
        _bar(high=100.5, low=99.5, close=100.0, volume=1000.0, i=i)
        for i in range(n)
    ]


def test_source_tag_is_stable() -> None:
    assert VRVP_SOURCE == "volume_profile_vrvp_v2"


def test_vpoc_distance_zero_when_close_at_value() -> None:
    # All volume and the anchor close sit on the busiest price -> ~0 distance.
    bars = _mass_at_100(5)
    dist = vrvp_vpoc_distance_at(bars, 4, period=5)
    assert dist is not None
    # VPOC is a binned row midpoint, so it lands within one row of the close.
    assert abs(dist) < 0.05


def test_vpoc_distance_positive_when_close_above_value() -> None:
    # Bulk volume at 100; a tiny anchor bar marks price up at 110.
    bars = [
        *_mass_at_100(4),
        _bar(high=110.0, low=109.0, close=110.0, volume=1.0, i=4),
    ]
    dist = vrvp_vpoc_distance_at(bars, 4, period=5)
    assert dist is not None
    assert dist > 0.0
    assert -1.0 <= dist <= 1.0


def test_vpoc_distance_negative_when_close_below_value() -> None:
    bars = [
        *_mass_at_100(4),
        _bar(high=91.0, low=90.0, close=90.0, volume=1.0, i=4),
    ]
    dist = vrvp_vpoc_distance_at(bars, 4, period=5)
    assert dist is not None
    assert dist < 0.0
    assert -1.0 <= dist <= 1.0


def test_value_area_position_inside_is_zero() -> None:
    bars = _mass_at_100(5)
    assert vrvp_value_area_position_at(bars, 4, period=5) == 0.0


def test_value_area_position_above_is_plus_one() -> None:
    bars = [
        *_mass_at_100(4),
        _bar(high=110.0, low=109.0, close=110.0, volume=1.0, i=4),
    ]
    assert vrvp_value_area_position_at(bars, 4, period=5) == 1.0


def test_value_area_position_below_is_minus_one() -> None:
    bars = [
        *_mass_at_100(4),
        _bar(high=91.0, low=90.0, close=90.0, volume=1.0, i=4),
    ]
    assert vrvp_value_area_position_at(bars, 4, period=5) == -1.0


def test_none_when_anchor_out_of_range() -> None:
    bars = _mass_at_100(3)
    assert vrvp_vpoc_distance_at(bars, 9, period=3) is None
    assert vrvp_value_area_position_at(bars, 9, period=3) is None
    assert vrvp_vpoc_distance_at(bars, -1, period=3) is None
    assert vrvp_value_area_position_at(bars, -1, period=3) is None


def test_none_when_window_underflows() -> None:
    bars = _mass_at_100(3)
    # period exceeds available history before the anchor.
    assert vrvp_vpoc_distance_at(bars, 1, period=5) is None
    assert vrvp_value_area_position_at(bars, 1, period=5) is None


def test_none_when_anchor_close_missing() -> None:
    bars = _mass_at_100(4)
    broken = dict(bars[-1])
    broken.pop("close")
    broken.pop("c", None)
    bars = [*bars[:-1], broken]
    assert vrvp_vpoc_distance_at(bars, 4, period=5) is None
    assert vrvp_value_area_position_at(bars, 4, period=5) is None


def test_none_when_price_range_degenerate() -> None:
    # Every bar is a single price point -> the profiled range collapses and the
    # underlying profile refuses; both scalars are honestly absent.
    bars = [
        _bar(high=100.0, low=100.0, close=100.0, volume=100.0, i=i)
        for i in range(5)
    ]
    assert vrvp_vpoc_distance_at(bars, 4, period=5) is None
    assert vrvp_value_area_position_at(bars, 4, period=5) is None


def test_leak_free_ignores_bars_after_anchor() -> None:
    base = _mass_at_100(5)
    poison = [
        *base,
        _bar(high=600.0, low=400.0, close=550.0, volume=10_000_000.0, i=5),
    ]
    assert vrvp_vpoc_distance_at(base, 4, period=5) == vrvp_vpoc_distance_at(
        poison, 4, period=5
    )
    assert vrvp_value_area_position_at(base, 4, period=5) == (
        vrvp_value_area_position_at(poison, 4, period=5)
    )
