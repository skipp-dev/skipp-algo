"""Tests for smc_fvg_lifecycle_light adapter.

Covers: fresh active FVG, partially filled, fully mitigated,
bull/bear tie-break nearest selection, and maturity derivation.
"""
from __future__ import annotations

import pytest
from scripts.smc_fvg_lifecycle_light import build_fvg_lifecycle_light, DEFAULTS


def _imbalance(
    *,
    bull_active: bool = False,
    bear_active: bool = False,
    bull_top: float = 0.0,
    bull_bottom: float = 0.0,
    bear_top: float = 0.0,
    bear_bottom: float = 0.0,
    bull_mit_pct: float = 0.0,
    bear_mit_pct: float = 0.0,
    bull_full_mit: bool = False,
    bear_full_mit: bool = False,
) -> dict:
    return {
        "BULL_FVG_ACTIVE": bull_active,
        "BEAR_FVG_ACTIVE": bear_active,
        "BULL_FVG_TOP": bull_top,
        "BULL_FVG_BOTTOM": bull_bottom,
        "BEAR_FVG_TOP": bear_top,
        "BEAR_FVG_BOTTOM": bear_bottom,
        "BULL_FVG_MITIGATION_PCT": bull_mit_pct,
        "BEAR_FVG_MITIGATION_PCT": bear_mit_pct,
        "BULL_FVG_FULL_MITIGATION": bull_full_mit,
        "BEAR_FVG_FULL_MITIGATION": bear_full_mit,
    }


class TestFreshActiveFVG:
    def test_bull_fresh_minimal_fill(self):
        il = _imbalance(bull_active=True, bull_top=105, bull_bottom=100, bull_mit_pct=0.05)
        result = build_fvg_lifecycle_light(imbalance=il, current_price=103)
        assert result["PRIMARY_FVG_SIDE"] == "BULL"
        assert result["FVG_FRESH"] is True
        assert result["FVG_INVALIDATED"] is False
        assert result["FVG_MATURITY_LEVEL"] == 0

    def test_bear_fresh_minimal_fill(self):
        il = _imbalance(bear_active=True, bear_top=110, bear_bottom=105, bear_mit_pct=0.1)
        result = build_fvg_lifecycle_light(imbalance=il, current_price=107)
        assert result["PRIMARY_FVG_SIDE"] == "BEAR"
        assert result["FVG_FRESH"] is True
        assert result["FVG_MATURITY_LEVEL"] == 0


class TestPartiallyFilled:
    def test_moderate_fill_aging(self):
        il = _imbalance(bull_active=True, bull_top=105, bull_bottom=100, bull_mit_pct=0.35)
        result = build_fvg_lifecycle_light(imbalance=il, current_price=103)
        assert result["FVG_MATURITY_LEVEL"] == 1
        assert result["FVG_FRESH"] is True  # maturity 1 <= MATURITY_FRESH_MAX

    def test_heavy_fill_mature(self):
        il = _imbalance(bull_active=True, bull_top=105, bull_bottom=100, bull_mit_pct=0.6)
        result = build_fvg_lifecycle_light(imbalance=il, current_price=103)
        assert result["FVG_MATURITY_LEVEL"] == 2
        assert result["FVG_FRESH"] is False

    def test_near_full_fill_expiring(self):
        il = _imbalance(bull_active=True, bull_top=105, bull_bottom=100, bull_mit_pct=0.85)
        result = build_fvg_lifecycle_light(imbalance=il, current_price=103)
        assert result["FVG_MATURITY_LEVEL"] == 3
        assert result["FVG_FRESH"] is False


class TestFullMitigation:
    def test_full_mitigation_invalidated(self):
        il = _imbalance(
            bull_active=True, bull_top=105, bull_bottom=100,
            bull_mit_pct=1.0, bull_full_mit=True,
        )
        result = build_fvg_lifecycle_light(imbalance=il, current_price=103)
        assert result["FVG_INVALIDATED"] is True
        assert result["FVG_FRESH"] is False

    def test_bear_full_mitigation(self):
        il = _imbalance(
            bear_active=True, bear_top=110, bear_bottom=105,
            bear_mit_pct=1.0, bear_full_mit=True,
        )
        result = build_fvg_lifecycle_light(imbalance=il, current_price=107)
        assert result["FVG_INVALIDATED"] is True
        assert result["PRIMARY_FVG_SIDE"] == "BEAR"


class TestTieBreakNearest:
    def test_bull_nearer_selected(self):
        il = _imbalance(
            bull_active=True, bull_top=102, bull_bottom=100,
            bear_active=True, bear_top=115, bear_bottom=110,
        )
        result = build_fvg_lifecycle_light(imbalance=il, current_price=103)
        assert result["PRIMARY_FVG_SIDE"] == "BULL"

    def test_bear_nearer_selected(self):
        il = _imbalance(
            bull_active=True, bull_top=90, bull_bottom=85,
            bear_active=True, bear_top=105, bear_bottom=103,
        )
        result = build_fvg_lifecycle_light(imbalance=il, current_price=104)
        assert result["PRIMARY_FVG_SIDE"] == "BEAR"

    def test_equal_distance_prefers_bull(self):
        # When equidistant, bull <= bear distance → bull selected
        il = _imbalance(
            bull_active=True, bull_top=105, bull_bottom=100,
            bear_active=True, bear_top=110, bear_bottom=105,
        )
        result = build_fvg_lifecycle_light(imbalance=il, current_price=102.5)
        assert result["PRIMARY_FVG_SIDE"] == "BULL"


class TestNoFVG:
    def test_no_active_returns_defaults(self):
        result = build_fvg_lifecycle_light(imbalance={})
        assert result == DEFAULTS

    def test_none_imbalance_returns_defaults(self):
        result = build_fvg_lifecycle_light(imbalance=None)
        assert result == DEFAULTS

    def test_overrides_on_empty(self):
        result = build_fvg_lifecycle_light(
            imbalance={}, overrides={"PRIMARY_FVG_SIDE": "BULL"}
        )
        assert result["PRIMARY_FVG_SIDE"] == "BULL"
