"""Tests for smc_core.reaction_zone (Phase C — Reaction Zone).

Covers:
- Zone boundaries are symmetric around swept_level
- ``close_back_inside_zone=True`` when bar closes within the zone
- ``close_back_inside_zone=False`` when no bar closes inside
- ``bars_to_confirm == -1`` when no confirmation found
- ``bars_to_confirm`` equals index of first confirming bar (1-indexed)
- ``confirmation_body_ratio >= MIN_CONFIRMATION_BODY_RATIO`` gating
- ``wick_rejection_ratio`` is bounded 0.0–1.0
- Empty ``post_sweep_bars`` returns sensible defaults
- Bearish sweep zone is correctly constructed above swept_level
- ``ReactionZone`` is immutable (frozen dataclass)
"""

from __future__ import annotations

import pytest

from smc_core.reaction_zone import (
    ZONE_WIDTH_FRACTION,
    compute_reaction_zone,
)

# ---------------------------------------------------------------------------
# Zone boundary computation
# ---------------------------------------------------------------------------


class TestZoneBoundaries:
    def test_bullish_sweep_zone_below_swept_level(self) -> None:
        zone = compute_reaction_zone(
            swept_level=100.0,
            sweep_extreme=105.0,
            is_bullish_sweep=True,
            post_sweep_bars=[],
        )
        expected_width = abs(100.0 - 105.0) * ZONE_WIDTH_FRACTION
        assert zone.reaction_zone_high == pytest.approx(100.0)
        assert zone.reaction_zone_low == pytest.approx(100.0 - expected_width)

    def test_bearish_sweep_zone_above_swept_level(self) -> None:
        zone = compute_reaction_zone(
            swept_level=100.0,
            sweep_extreme=95.0,
            is_bullish_sweep=False,
            post_sweep_bars=[],
        )
        expected_width = abs(100.0 - 95.0) * ZONE_WIDTH_FRACTION
        assert zone.reaction_zone_low == pytest.approx(100.0)
        assert zone.reaction_zone_high == pytest.approx(100.0 + expected_width)


# ---------------------------------------------------------------------------
# Confirmation detection
# ---------------------------------------------------------------------------


def _bar(close: float, body_fraction: float = 0.8) -> dict:
    """Build an OHLC bar with the specified close and body/range ratio."""
    candle_range = 1.0
    body = candle_range * body_fraction
    open_ = close - body / 2
    high = close + (candle_range - body) / 2
    low = close - body / 2 - (candle_range - body) / 2
    return {"open": open_, "high": high, "low": low, "close": close}


class TestConfirmation:
    def test_confirmed_first_bar_inside_zone(self) -> None:
        # swept_level=100, sweep_extreme=105 → zone [100 - 5*0.382, 100]
        swept = 100.0
        extreme = 105.0
        zone_width = abs(swept - extreme) * ZONE_WIDTH_FRACTION
        inside_close = swept - zone_width * 0.5  # inside the zone
        zone = compute_reaction_zone(
            swept_level=swept,
            sweep_extreme=extreme,
            is_bullish_sweep=True,
            post_sweep_bars=[_bar(inside_close, body_fraction=0.7)],
        )
        assert zone.close_back_inside_zone is True
        assert zone.bars_to_confirm == 1

    def test_not_confirmed_when_close_above_zone(self) -> None:
        swept = 100.0
        extreme = 105.0
        zone = compute_reaction_zone(
            swept_level=swept,
            sweep_extreme=extreme,
            is_bullish_sweep=True,
            post_sweep_bars=[_bar(101.0)],  # Still above swept_level → outside zone
        )
        assert zone.close_back_inside_zone is False
        assert zone.bars_to_confirm == -1

    def test_confirmation_requires_min_body_ratio(self) -> None:
        swept = 100.0
        extreme = 105.0
        zone_width = abs(swept - extreme) * ZONE_WIDTH_FRACTION
        inside_close = swept - zone_width * 0.5
        # Tiny body — below MIN_CONFIRMATION_BODY_RATIO
        tiny_body_bar = {
            "open": inside_close,
            "high": inside_close + 2.0,  # huge wick → tiny body ratio
            "low": inside_close - 2.0,
            "close": inside_close,
        }
        zone = compute_reaction_zone(
            swept_level=swept,
            sweep_extreme=extreme,
            is_bullish_sweep=True,
            post_sweep_bars=[tiny_body_bar],
        )
        assert zone.close_back_inside_zone is False

    def test_confirmed_on_second_bar(self) -> None:
        swept = 100.0
        extreme = 105.0
        zone_width = abs(swept - extreme) * ZONE_WIDTH_FRACTION
        inside_close = swept - zone_width * 0.5
        outside_bar = _bar(101.0)  # first bar outside zone
        inside_bar = _bar(inside_close, body_fraction=0.7)  # second bar inside
        zone = compute_reaction_zone(
            swept_level=swept,
            sweep_extreme=extreme,
            is_bullish_sweep=True,
            post_sweep_bars=[outside_bar, inside_bar],
        )
        assert zone.bars_to_confirm == 2

    def test_empty_bars_returns_no_confirmation(self) -> None:
        zone = compute_reaction_zone(
            swept_level=100.0,
            sweep_extreme=105.0,
            is_bullish_sweep=True,
            post_sweep_bars=[],
        )
        assert zone.close_back_inside_zone is False
        assert zone.bars_to_confirm == -1
        assert zone.confirmation_body_ratio == pytest.approx(0.0)

    def test_wick_rejection_ratio_bounded_0_1(self) -> None:
        swept = 100.0
        extreme = 105.0
        zone_width = abs(swept - extreme) * ZONE_WIDTH_FRACTION
        inside_close = swept - zone_width * 0.5
        zone = compute_reaction_zone(
            swept_level=swept,
            sweep_extreme=extreme,
            is_bullish_sweep=True,
            post_sweep_bars=[_bar(inside_close)],
        )
        assert 0.0 <= zone.wick_rejection_ratio <= 1.0


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_reaction_zone_is_frozen() -> None:
    zone = compute_reaction_zone(
        swept_level=100.0, sweep_extreme=105.0, is_bullish_sweep=True, post_sweep_bars=[]
    )
    with pytest.raises((AttributeError, TypeError)):
        zone.close_back_inside_zone = True  # type: ignore[misc]
