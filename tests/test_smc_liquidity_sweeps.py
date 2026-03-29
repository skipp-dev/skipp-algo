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

from scripts.smc_liquidity_sweeps import DEFAULTS, build_liquidity_sweeps


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
