"""Tests for smc_liquidity_sweeps — liquidity sweep layer (v5.2).

Covers:
- neutral/default mode
- bullish sweep detection
- bearish sweep detection
- sweep type classification
- reclaim detection
- quality score
- override merging
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_liquidity_sweeps import (
    DEFAULTS,
    SWEEP_DEPTH_MIN_PCT,
    SWEEP_DEPTH_STOP_HUNT_PCT,
    build_liquidity_sweeps,
)


def _make_snapshot(**kwargs) -> pd.DataFrame:
    defaults = {
        "symbol": "AAPL",
        "recent_bull_sweep": False,
        "recent_bear_sweep": False,
        "sweep_type": "",
        "sweep_depth_pct": 0.0,
        "sweep_volume_ratio": 0.0,
        "sweep_zone_top": 0.0,
        "sweep_zone_bottom": 0.0,
        "sweep_reclaim_active": False,
        "sweep_bias_bull": True,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


class TestNeutralDefaults:
    def test_no_snapshot_returns_defaults(self):
        result = build_liquidity_sweeps()
        assert result == DEFAULTS

    def test_none_snapshot_returns_defaults(self):
        result = build_liquidity_sweeps(snapshot=None)
        assert result == DEFAULTS

    def test_empty_snapshot_returns_defaults(self):
        result = build_liquidity_sweeps(snapshot=pd.DataFrame())
        assert result == DEFAULTS

    def test_all_keys_present(self):
        result = build_liquidity_sweeps()
        assert set(result.keys()) == set(DEFAULTS.keys())


class TestBullishSweep:
    @pytest.fixture()
    def result(self):
        return build_liquidity_sweeps(
            snapshot=_make_snapshot(
                recent_bull_sweep=True,
                sweep_depth_pct=0.5,
                sweep_volume_ratio=1.5,
                sweep_zone_top=105.0,
                sweep_zone_bottom=104.0,
                sweep_reclaim_active=True,
            )
        )

    def test_bull_sweep_detected(self, result):
        assert result["RECENT_BULL_SWEEP"] is True

    def test_direction_bull(self, result):
        assert result["SWEEP_DIRECTION"] == "BULL"

    def test_liquidity_sell_side(self, result):
        assert result["LIQUIDITY_TAKEN_DIRECTION"] == "SELL_SIDE"

    def test_zone_levels(self, result):
        assert result["SWEEP_ZONE_TOP"] == 105.0
        assert result["SWEEP_ZONE_BOTTOM"] == 104.0

    def test_reclaim_active(self, result):
        assert result["SWEEP_RECLAIM_ACTIVE"] is True

    def test_quality_score_high(self, result):
        assert result["SWEEP_QUALITY_SCORE"] >= 4


class TestBearishSweep:
    @pytest.fixture()
    def result(self):
        return build_liquidity_sweeps(
            snapshot=_make_snapshot(
                recent_bear_sweep=True,
                sweep_depth_pct=0.3,
                sweep_volume_ratio=1.3,
                sweep_zone_top=96.0,
                sweep_zone_bottom=95.0,
            )
        )

    def test_bear_sweep_detected(self, result):
        assert result["RECENT_BEAR_SWEEP"] is True

    def test_direction_bear(self, result):
        assert result["SWEEP_DIRECTION"] == "BEAR"

    def test_liquidity_buy_side(self, result):
        assert result["LIQUIDITY_TAKEN_DIRECTION"] == "BUY_SIDE"


class TestBothSidesSweep:
    def test_missing_bias_is_none(self):
        """Both sides swept, no ``sweep_bias_bull`` -> ambiguous NONE, not bull."""
        snap = pd.DataFrame([{
            "symbol": "AAPL",
            "recent_bull_sweep": True,
            "recent_bear_sweep": True,
        }])
        result = build_liquidity_sweeps(snapshot=snap)
        assert result["SWEEP_DIRECTION"] == "NONE"
        assert result["LIQUIDITY_TAKEN_DIRECTION"] == "NONE"

    def test_bias_true_is_bull(self):
        result = build_liquidity_sweeps(
            snapshot=_make_snapshot(
                recent_bull_sweep=True, recent_bear_sweep=True, sweep_bias_bull=True
            )
        )
        assert result["SWEEP_DIRECTION"] == "BULL"
        assert result["LIQUIDITY_TAKEN_DIRECTION"] == "SELL_SIDE"

    def test_bias_false_is_bear(self):
        result = build_liquidity_sweeps(
            snapshot=_make_snapshot(
                recent_bull_sweep=True, recent_bear_sweep=True, sweep_bias_bull=False
            )
        )
        assert result["SWEEP_DIRECTION"] == "BEAR"
        assert result["LIQUIDITY_TAKEN_DIRECTION"] == "BUY_SIDE"


class TestSweepTypeClassification:
    def test_explicit_stop_hunt(self):
        result = build_liquidity_sweeps(
            snapshot=_make_snapshot(
                recent_bull_sweep=True,
                sweep_type="STOP_HUNT",
            )
        )
        assert result["SWEEP_TYPE"] == "STOP_HUNT"

    def test_inferred_stop_hunt(self):
        result = build_liquidity_sweeps(
            snapshot=_make_snapshot(
                recent_bull_sweep=True,
                sweep_depth_pct=0.5,
                sweep_volume_ratio=1.5,
            )
        )
        assert result["SWEEP_TYPE"] == "STOP_HUNT"

    def test_inferred_liquidity_grab(self):
        result = build_liquidity_sweeps(
            snapshot=_make_snapshot(
                recent_bull_sweep=True,
                sweep_depth_pct=0.05,
                sweep_volume_ratio=1.5,
            )
        )
        assert result["SWEEP_TYPE"] == "LIQUIDITY_GRAB"

    def test_inferred_inducement(self):
        result = build_liquidity_sweeps(
            snapshot=_make_snapshot(
                recent_bull_sweep=True,
                sweep_depth_pct=0.05,
                sweep_volume_ratio=0.5,
            )
        )
        assert result["SWEEP_TYPE"] == "INDUCEMENT"

    def test_no_sweep_none(self):
        result = build_liquidity_sweeps(snapshot=_make_snapshot())
        assert result["SWEEP_TYPE"] == "NONE"


class TestQualityScore:
    def test_zero_no_sweep(self):
        result = build_liquidity_sweeps(snapshot=_make_snapshot())
        assert result["SWEEP_QUALITY_SCORE"] == 0

    def test_max_score(self):
        result = build_liquidity_sweeps(
            snapshot=_make_snapshot(
                recent_bull_sweep=True,
                sweep_depth_pct=0.5,
                sweep_volume_ratio=1.5,
                sweep_reclaim_active=True,
            )
        )
        assert result["SWEEP_QUALITY_SCORE"] == 5


class TestOverrides:
    def test_override_sweep_type(self):
        result = build_liquidity_sweeps(
            overrides={"SWEEP_TYPE": "CUSTOM"},
        )
        assert result["SWEEP_TYPE"] == "CUSTOM"

    def test_unknown_override_ignored(self):
        result = build_liquidity_sweeps(overrides={"NOT_A_FIELD": 42})
        assert "NOT_A_FIELD" not in result


# ---------------------------------------------------------------------------
# STOP_HUNT depth boundary
# ---------------------------------------------------------------------------
# The gate used to be written as ``SWEEP_DEPTH_MIN_PCT * 3``. In IEEE-754
# ``0.1 * 3`` is 0.30000000000000004, so a sweep at *exactly* the documented 0.3%
# depth did NOT clear it and classified LIQUIDITY_GRAB — an accident of float
# arithmetic, not a decision. The gate is now its own named constant and 0.3
# means 0.3.


def _classified(depth: float, vol_ratio: float) -> str:
    df = _make_snapshot(
        recent_bull_sweep=True,
        sweep_depth_pct=depth,
        sweep_volume_ratio=vol_ratio,
    )
    return build_liquidity_sweeps(snapshot=df)["SWEEP_TYPE"]


def test_stop_hunt_gate_is_its_own_constant_not_derived_from_the_min_depth() -> None:
    """The threshold must not be re-derived from SWEEP_DEPTH_MIN_PCT.

    Deriving it is what introduced the float artifact. Pinning the identity here
    means a future edit cannot quietly reintroduce ``MIN_PCT * 3``.
    """
    assert SWEEP_DEPTH_STOP_HUNT_PCT == 0.3
    assert SWEEP_DEPTH_STOP_HUNT_PCT != SWEEP_DEPTH_MIN_PCT * 3, (
        "the stop-hunt gate is being derived from SWEEP_DEPTH_MIN_PCT again — "
        "0.1*3 is 0.30000000000000004, which is exactly the boundary bug this "
        "constant exists to remove"
    )


@pytest.mark.parametrize(
    "depth,vol_ratio,expected",
    [
        (0.3 - 1e-9, 1.2, "LIQUIDITY_GRAB"),  # just under -> not deep enough
        (0.3, 1.2, "STOP_HUNT"),              # exactly at the gate -> clears it
        (0.3 + 1e-9, 1.2, "STOP_HUNT"),       # just over
        (0.3, 1.2 - 1e-9, "INDUCEMENT"),      # deep enough, volume too thin
        (0.5, 1.5, "STOP_HUNT"),              # comfortably over both
    ],
)
def test_stop_hunt_depth_boundary_is_inclusive_at_exactly_three_tenths(
    depth: float, vol_ratio: float, expected: str
) -> None:
    assert _classified(depth, vol_ratio) == expected


def test_explicit_sweep_type_still_wins_over_the_boundary_rule() -> None:
    """The passthrough branch is unaffected by the threshold change."""
    df = _make_snapshot(
        recent_bull_sweep=True,
        sweep_type="INDUCEMENT",
        sweep_depth_pct=0.3,
        sweep_volume_ratio=1.5,
    )
    assert build_liquidity_sweeps(snapshot=df)["SWEEP_TYPE"] == "INDUCEMENT"
