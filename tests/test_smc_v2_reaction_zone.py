"""Tests for smc_core.reaction_zone (Phase C — reaction to a liquidity sweep).

The two concepts are tested INDEPENDENTLY (they must never be conflated):

* ``level_reclaimed`` — authoritative reversal confirmation: a close back through
  the swept level in the reversal direction (bull: ``close >= swept_level``;
  bear: ``close <= swept_level``), UNBOUNDED on the favourable side (a strong
  reclaim counts — the classic "full reclaim" is a confirmation, not excluded).
* ``close_in_rejection_band`` — observation-only: a close that recovered into the
  narrow band on the swept side WITHOUT reclaiming the level.

Geometry uses the production contract: for a bullish/sell-side sweep the
``sweep_extreme`` is the sweep bar's LOW (below ``swept_level``); for a bearish
sweep it is the HIGH (above ``swept_level``).
"""

from __future__ import annotations

import pytest

from smc_core.reaction_zone import ZONE_WIDTH_FRACTION, compute_reaction_zone


def _bar(close: float, *, open_: float | None = None, high: float | None = None,
         low: float | None = None) -> dict:
    """OHLC bar; open defaults just below close (bullish body), wicks hug the body."""
    o = open_ if open_ is not None else close - 0.5
    h = high if high is not None else max(o, close) + 0.1
    lo = low if low is not None else min(o, close) - 0.1
    return {"open": o, "high": h, "low": lo, "close": close}


class TestBandGeometry:
    def test_bullish_band_is_below_the_swept_level(self) -> None:
        # bullish sweep: swept a low at 100 down to 98 (extreme = sweep-bar LOW).
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True, post_sweep_bars=[])
        w = abs(100.0 - 98.0) * ZONE_WIDTH_FRACTION
        assert z.rejection_band_high == pytest.approx(100.0)
        assert z.rejection_band_low == pytest.approx(100.0 - w)

    def test_bearish_band_is_above_the_swept_level(self) -> None:
        # bearish sweep: swept a high at 100 up to 102 (extreme = sweep-bar HIGH).
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=102.0,
                                  is_bullish_sweep=False, post_sweep_bars=[])
        w = abs(100.0 - 102.0) * ZONE_WIDTH_FRACTION
        assert z.rejection_band_low == pytest.approx(100.0)
        assert z.rejection_band_high == pytest.approx(100.0 + w)


class TestLevelReclaim:
    def test_full_reclaim_above_level_is_confirmed(self) -> None:
        # THE regression: a close ABOVE the swept low is the strongest bullish
        # reclaim and MUST confirm (the old geometry wrongly excluded it).
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True,
                                  post_sweep_bars=[_bar(101.0, open_=99.0)])
        assert z.level_reclaimed is True
        assert z.bars_to_reclaim == 1
        assert z.close_distance_pct == pytest.approx(1.0)  # (101-100)/100 * 100
        assert z.directional_body is True  # close 101 > open 99

    def test_partial_recovery_below_level_is_not_a_reclaim(self) -> None:
        # Closes back up but STILL below the swept low → rejection band, NOT reclaim.
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True,
                                  post_sweep_bars=[_bar(99.5, open_=98.5)])
        assert z.level_reclaimed is False
        assert z.close_in_rejection_band is True
        assert z.bars_to_rejection_band == 1

    def test_fade_confirms_neither(self) -> None:
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True,
                                  post_sweep_bars=[_bar(98.4, open_=98.6)])
        assert z.level_reclaimed is False
        assert z.close_in_rejection_band is False

    def test_bearish_full_reclaim_below_level_is_confirmed(self) -> None:
        # Symmetric: bearish reclaim = close BELOW the swept high.
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=102.0,
                                  is_bullish_sweep=False,
                                  post_sweep_bars=[_bar(99.0, open_=101.0)])
        assert z.level_reclaimed is True
        assert z.close_distance_pct == pytest.approx(1.0)  # (100-99)/100 * 100
        assert z.directional_body is True  # close 99 < open 101

    def test_bearish_partial_recovery_above_level_is_not_a_reclaim(self) -> None:
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=102.0,
                                  is_bullish_sweep=False,
                                  post_sweep_bars=[_bar(100.5, open_=101.5)])
        assert z.level_reclaimed is False
        assert z.close_in_rejection_band is True


class TestLevelDisjointness:
    """A close exactly ON the swept level is a reclaim, never 'in the band'.

    Regression for the band/reclaim overlap: with an inclusive band edge a close
    at ``swept_level`` set BOTH ``level_reclaimed`` and ``close_in_rejection_band``.
    The band is now half-open at the level so the two raw signals stay disjoint.
    """

    def test_bullish_close_exactly_on_level_is_reclaim_only(self) -> None:
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True,
                                  post_sweep_bars=[_bar(100.0, open_=99.0)])
        assert z.level_reclaimed is True
        assert z.close_in_rejection_band is False  # exactly on the level ≠ in band
        assert z.bars_to_rejection_band == -1

    def test_bearish_close_exactly_on_level_is_reclaim_only(self) -> None:
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=102.0,
                                  is_bullish_sweep=False,
                                  post_sweep_bars=[_bar(100.0, open_=101.0)])
        assert z.level_reclaimed is True
        assert z.close_in_rejection_band is False
        assert z.bars_to_rejection_band == -1

    def test_bullish_close_just_below_level_still_in_band(self) -> None:
        # Guard the other edge: a close just inside the band is unaffected.
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True,
                                  post_sweep_bars=[_bar(99.9, open_=99.0)])
        assert z.level_reclaimed is False
        assert z.close_in_rejection_band is True


class TestCandleQuality:
    def test_directional_body_false_for_counter_direction_candle(self) -> None:
        # A bearish candle that nonetheless closes above the level still reclaims
        # (level-cross is unbounded), but directional_body flags it as counter.
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True,
                                  post_sweep_bars=[_bar(100.5, open_=101.0)])
        assert z.level_reclaimed is True
        assert z.directional_body is False  # close 100.5 < open 101.0 (bearish body)

    def test_rejection_wick_is_the_swept_side_wick_and_bounded(self) -> None:
        # Bullish reclaim bar with a long LOWER wick (the swept-side rejection).
        bar = {"open": 100.2, "high": 100.6, "low": 98.5, "close": 100.5}
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True, post_sweep_bars=[bar])
        assert z.level_reclaimed is True
        rng = 100.6 - 98.5
        expected_lower_wick = (min(100.2, 100.5) - 98.5) / rng
        assert z.rejection_wick_ratio == pytest.approx(expected_lower_wick)
        assert 0.0 <= z.rejection_wick_ratio <= 1.0

    def test_reclaim_uses_first_bar_that_crosses(self) -> None:
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True,
                                  post_sweep_bars=[_bar(99.5, open_=98.5), _bar(101.0, open_=99.0)])
        assert z.bars_to_reclaim == 2
        assert z.bars_to_rejection_band == 1  # first bar recovered into the band


class TestDefaultsAndImmutability:
    def test_empty_bars_returns_defaults(self) -> None:
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True, post_sweep_bars=[])
        assert z.level_reclaimed is False
        assert z.close_in_rejection_band is False
        assert z.bars_to_reclaim == -1
        assert z.bars_to_rejection_band == -1
        assert z.body_ratio == pytest.approx(0.0)
        assert z.close_distance_pct == pytest.approx(0.0)

    def test_reaction_zone_is_frozen(self) -> None:
        z = compute_reaction_zone(swept_level=100.0, sweep_extreme=98.0,
                                  is_bullish_sweep=True, post_sweep_bars=[])
        with pytest.raises((AttributeError, TypeError)):
            z.level_reclaimed = True  # type: ignore[misc]
