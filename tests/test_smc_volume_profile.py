"""VRVP precise volume-by-price profile: extractor tests.

Covers volume conservation, span distribution across the rows a bar touches
(the LTF-equivalent precision the coarse close-bin profile lacks), the
buyer/seller delta split, multi-POC node separation, the ~value-area-percent
containment, degenerate-bar handling, the honest-None refusals (empty window, no
valid bars, zero volume, degenerate price range, bad parameters), and the
point-in-time leak-freedom of ``volume_profile_at``.
"""

from __future__ import annotations

import math

from scripts.smc_volume_profile import (
    VOLUME_PROFILE_SOURCE,
    VolumeProfile,
    compute_volume_profile,
    volume_profile_at,
)

_T0 = 1_700_000_000.0
_STEP = 900.0  # 15-minute bars


def _bar(
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    i: int = 0,
) -> dict:
    return {
        "timestamp": _T0 + i * _STEP,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def test_source_tag_is_stable() -> None:
    assert VOLUME_PROFILE_SOURCE == "smc_vrvp_v1"


def test_volume_is_conserved_across_rows() -> None:
    # Whatever the distribution, the profile must conserve total traded volume.
    bars = [
        _bar(open_=100.0, high=102.0, low=99.0, close=101.0, volume=1000.0, i=0),
        _bar(open_=101.0, high=103.0, low=100.0, close=100.5, volume=500.0, i=1),
        _bar(open_=100.5, high=101.0, low=98.0, close=98.5, volume=750.0, i=2),
    ]
    profile = compute_volume_profile(bars, rows=20)
    assert profile is not None
    assert math.isclose(profile.total_volume, 2250.0, rel_tol=1e-9)
    row_sum = sum(row.total for row in profile.rows)
    assert math.isclose(row_sum, 2250.0, rel_tol=1e-9)


def test_span_distribution_spreads_volume_beyond_close_row() -> None:
    # A single wide bar must light up multiple rows across its [low, high] span,
    # unlike a close-only profile which would put all volume in one row.
    bars = [_bar(open_=100.0, high=110.0, low=100.0, close=105.0, volume=1000.0)]
    profile = compute_volume_profile(bars, rows=10, distribution="uniform")
    assert profile is not None
    nonzero_rows = [row for row in profile.rows if row.total > 0.0]
    assert len(nonzero_rows) > 1
    # Uniform spread over a [100,110] bar across 10 rows of height 1 each => every
    # row carries an equal tenth of the volume.
    for row in profile.rows:
        assert math.isclose(row.total, 100.0, rel_tol=1e-9)


def test_delta_split_tracks_buyers_and_sellers() -> None:
    # One up bar (close >= open) and one down bar at the same price band: the row
    # they share must carry both up and down volume with the correct delta sign.
    bars = [
        _bar(open_=100.0, high=101.0, low=100.0, close=101.0, volume=600.0, i=0),
        _bar(open_=101.0, high=101.0, low=100.0, close=100.0, volume=200.0, i=1),
    ]
    profile = compute_volume_profile(bars, rows=4)
    assert profile is not None
    total_up = sum(row.up for row in profile.rows)
    total_down = sum(row.down for row in profile.rows)
    assert math.isclose(total_up, 600.0, rel_tol=1e-9)
    assert math.isclose(total_down, 200.0, rel_tol=1e-9)
    assert math.isclose(profile.rows[0].delta + sum(r.delta for r in profile.rows[1:]), 400.0, rel_tol=1e-9)


def test_degenerate_zero_range_bar_falls_into_close_row() -> None:
    # A zero-range bar cannot be spread; its whole volume lands in the close row.
    bars = [
        _bar(open_=100.0, high=105.0, low=100.0, close=102.0, volume=1000.0, i=0),
        _bar(open_=103.0, high=103.0, low=103.0, close=103.0, volume=400.0, i=1),
    ]
    profile = compute_volume_profile(bars, rows=5)
    assert profile is not None
    # Row covering price 103 must contain at least the degenerate bar's volume.
    target = next(row for row in profile.rows if row.low <= 103.0 < row.high)
    assert target.total >= 400.0


def test_multi_poc_returns_separated_nodes() -> None:
    # Two distinct high-volume price clusters must surface as two separated POCs,
    # not two adjacent rows of one peak.
    bars = []
    # Cluster near 100.
    for i in range(5):
        bars.append(_bar(open_=100.0, high=100.4, low=99.6, close=100.2, volume=1000.0, i=i))
    # Gap with light volume near 105.
    bars.append(_bar(open_=102.0, high=108.0, low=102.0, close=105.0, volume=50.0, i=5))
    # Cluster near 110.
    for i in range(6, 11):
        bars.append(_bar(open_=110.0, high=110.4, low=109.6, close=110.2, volume=1000.0, i=i))
    profile = compute_volume_profile(bars, rows=30, poc_count=2, poc_mode="volume_nodes")
    assert profile is not None
    assert len(profile.pocs) == 2
    # The two POCs should straddle the gap: one low (~100), one high (~110).
    low_poc, high_poc = sorted(profile.pocs)
    assert low_poc < 103.0
    assert high_poc > 107.0


def test_value_area_contains_target_fraction() -> None:
    bars = [
        _bar(open_=100.0, high=101.0, low=99.0, close=100.0, volume=2000.0, i=0),
        _bar(open_=100.0, high=105.0, low=100.0, close=104.0, volume=300.0, i=1),
        _bar(open_=104.0, high=104.0, low=95.0, close=96.0, volume=300.0, i=2),
    ]
    profile = compute_volume_profile(bars, rows=20, value_area_pct=0.70)
    assert profile is not None
    assert profile.val <= profile.vpoc <= profile.vah
    va_volume = sum(row.total for row in profile.rows if profile.value_area_low <= row.mid <= profile.value_area_high)
    assert va_volume >= 0.70 * profile.total_volume


def test_highest_rows_poc_mode_picks_top_rows() -> None:
    bars = [
        _bar(open_=100.0, high=101.0, low=99.0, close=100.0, volume=5000.0, i=0),
        _bar(open_=100.0, high=110.0, low=100.0, close=105.0, volume=100.0, i=1),
    ]
    profile = compute_volume_profile(bars, rows=22, poc_count=3, poc_mode="highest_rows")
    assert profile is not None
    assert len(profile.pocs) >= 1
    # The dominant cluster around 100 must be the primary POC.
    assert abs(profile.vpoc - 100.0) <= 2.0


def test_none_on_empty_window() -> None:
    assert compute_volume_profile([]) is None


def test_none_when_no_valid_bars() -> None:
    bad = [
        {"open": 1.0, "high": 2.0, "low": 1.0, "close": 1.5},  # missing volume
        {"open": 1.0, "high": 1.0, "low": 2.0, "close": 1.5, "volume": 10.0},  # high < low
        {"open": 1.0, "high": 2.0, "low": 1.0, "close": 1.5, "volume": -5.0},  # neg volume
    ]
    assert compute_volume_profile(bad) is None


def test_none_on_zero_total_volume() -> None:
    bars = [_bar(open_=100.0, high=101.0, low=99.0, close=100.0, volume=0.0)]
    assert compute_volume_profile(bars) is None


def test_none_on_degenerate_price_range() -> None:
    bars = [
        _bar(open_=100.0, high=100.0, low=100.0, close=100.0, volume=500.0, i=0),
        _bar(open_=100.0, high=100.0, low=100.0, close=100.0, volume=500.0, i=1),
    ]
    assert compute_volume_profile(bars) is None


def test_none_on_bad_parameters() -> None:
    bars = [_bar(open_=100.0, high=102.0, low=99.0, close=101.0, volume=1000.0)]
    assert compute_volume_profile(bars, rows=0) is None
    assert compute_volume_profile(bars, value_area_pct=0.0) is None
    assert compute_volume_profile(bars, value_area_pct=1.5) is None
    assert compute_volume_profile(bars, distribution="bogus") is None
    assert compute_volume_profile(bars, poc_mode="bogus") is None


def test_skips_individual_bad_bars_but_uses_good_ones() -> None:
    bars = [
        _bar(open_=100.0, high=102.0, low=99.0, close=101.0, volume=1000.0, i=0),
        {"open": 1.0, "high": 1.0, "low": 2.0, "close": 1.5, "volume": 10.0, "timestamp": _T0 + _STEP},
        _bar(open_=101.0, high=103.0, low=100.0, close=102.0, volume=500.0, i=2),
    ]
    profile = compute_volume_profile(bars, rows=10)
    assert profile is not None
    # Only the two good bars' volume is counted.
    assert math.isclose(profile.total_volume, 1500.0, rel_tol=1e-9)


def test_volume_profile_at_uses_trailing_window_only() -> None:
    bars = [
        _bar(open_=100.0, high=101.0, low=99.0, close=100.0, volume=100.0, i=0),
        _bar(open_=100.0, high=101.0, low=99.0, close=100.0, volume=100.0, i=1),
        _bar(open_=100.0, high=101.0, low=99.0, close=100.0, volume=100.0, i=2),
        _bar(open_=200.0, high=201.0, low=199.0, close=200.0, volume=999999.0, i=3),  # future
    ]
    profile = volume_profile_at(bars, anchor_idx=2, period=3)
    assert profile is not None
    # The huge future bar at index 3 must NOT influence the profile.
    assert math.isclose(profile.total_volume, 300.0, rel_tol=1e-9)
    assert profile.price_high <= 101.0


def test_volume_profile_at_leak_freedom_under_future_poison() -> None:
    base = [_bar(open_=100.0, high=101.0, low=99.0, close=100.0, volume=100.0, i=i) for i in range(5)]
    clean = volume_profile_at(base, anchor_idx=4, period=5)
    poisoned = [
        *base,
        _bar(open_=500.0, high=600.0, low=400.0, close=550.0, volume=10_000_000.0, i=5),
    ]
    after = volume_profile_at(poisoned, anchor_idx=4, period=5)
    assert clean is not None and after is not None
    assert math.isclose(clean.total_volume, after.total_volume, rel_tol=1e-12)
    assert math.isclose(clean.vpoc, after.vpoc, rel_tol=1e-12)


def test_volume_profile_at_none_paths() -> None:
    bars = [_bar(open_=100.0, high=101.0, low=99.0, close=100.0, volume=100.0, i=i) for i in range(3)]
    assert volume_profile_at(bars, anchor_idx=2, period=0) is None  # bad period
    assert volume_profile_at(bars, anchor_idx=-1, period=2) is None  # bad anchor
    assert volume_profile_at(bars, anchor_idx=5, period=2) is None  # anchor out of range
    assert volume_profile_at(bars, anchor_idx=1, period=5) is None  # window underflow


def test_returns_volume_profile_dataclass() -> None:
    bars = [_bar(open_=100.0, high=102.0, low=99.0, close=101.0, volume=1000.0)]
    profile = compute_volume_profile(bars)
    assert isinstance(profile, VolumeProfile)
    assert profile.source == VOLUME_PROFILE_SOURCE
    assert profile.diagnostics["distribution"] == "typical"
