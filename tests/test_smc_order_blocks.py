"""Tests for smc_order_blocks — order block layer (v5.2).

Covers:
- neutral/default mode
- bullish OB scenario
- bearish OB scenario
- OB bias computation
- FVG confluence
- density scoring
- context score
- override merging
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_order_blocks import DEFAULTS, build_order_blocks


def _make_snapshot(**kwargs) -> pd.DataFrame:
    defaults = {
        "symbol": "AAPL",
        "nearest_bull_ob_level": 0.0,
        "nearest_bear_ob_level": 0.0,
        "bull_ob_freshness": 0,
        "bear_ob_freshness": 0,
        "bull_ob_mitigated": False,
        "bear_ob_mitigated": False,
        "bull_ob_fvg_confluence": False,
        "bear_ob_fvg_confluence": False,
        "ob_density": 0,
        "ob_nearest_distance_pct": 0.0,
        "ob_strength_score": 0,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


class TestNeutralDefaults:
    def test_no_snapshot_returns_defaults(self):
        result = build_order_blocks()
        assert result == DEFAULTS

    def test_none_snapshot_returns_defaults(self):
        result = build_order_blocks(snapshot=None)
        assert result == DEFAULTS

    def test_empty_snapshot_returns_defaults(self):
        result = build_order_blocks(snapshot=pd.DataFrame())
        assert result == DEFAULTS

    def test_all_keys_present(self):
        result = build_order_blocks()
        assert set(result.keys()) == set(DEFAULTS.keys())


class TestBullishOB:
    @pytest.fixture()
    def result(self):
        return build_order_blocks(
            snapshot=_make_snapshot(
                nearest_bull_ob_level=98.0,
                bull_ob_freshness=4,
                bull_ob_fvg_confluence=True,
                ob_density=3,
                ob_strength_score=4,
                ob_nearest_distance_pct=0.5,
            )
        )

    def test_level(self, result):
        assert result["NEAREST_BULL_OB_LEVEL"] == 98.0

    def test_freshness(self, result):
        assert result["BULL_OB_FRESHNESS"] == 4

    def test_fvg_confluence(self, result):
        assert result["BULL_OB_FVG_CONFLUENCE"] is True

    def test_bias_bullish(self, result):
        assert result["OB_BIAS"] == "BULLISH"

    def test_context_score_high(self, result):
        assert result["OB_CONTEXT_SCORE"] >= 4

    def test_distance(self, result):
        assert result["OB_NEAREST_DISTANCE_PCT"] == 0.5


class TestBearishOB:
    @pytest.fixture()
    def result(self):
        return build_order_blocks(
            snapshot=_make_snapshot(
                nearest_bear_ob_level=105.0,
                bear_ob_freshness=4,
                bear_ob_fvg_confluence=True,
                ob_strength_score=3,
            )
        )

    def test_level(self, result):
        assert result["NEAREST_BEAR_OB_LEVEL"] == 105.0

    def test_bias_bearish(self, result):
        assert result["OB_BIAS"] == "BEARISH"


class TestMitigatedOB:
    def test_mitigated_bull_excluded_from_bias(self):
        result = build_order_blocks(
            snapshot=_make_snapshot(
                nearest_bull_ob_level=98.0,
                bull_ob_freshness=5,
                bull_ob_mitigated=True,
            )
        )
        assert result["OB_BIAS"] == "NEUTRAL"

    def test_mitigated_bear_excluded_from_bias(self):
        result = build_order_blocks(
            snapshot=_make_snapshot(
                nearest_bear_ob_level=105.0,
                bear_ob_freshness=5,
                bear_ob_mitigated=True,
            )
        )
        assert result["OB_BIAS"] == "NEUTRAL"


class TestFreshnessClamp:
    def test_clamped_high(self):
        result = build_order_blocks(
            snapshot=_make_snapshot(bull_ob_freshness=10)
        )
        assert result["BULL_OB_FRESHNESS"] == 5

    def test_clamped_low(self):
        result = build_order_blocks(
            snapshot=_make_snapshot(bear_ob_freshness=-1)
        )
        assert result["BEAR_OB_FRESHNESS"] == 0


class TestContextScore:
    def test_zero_no_data(self):
        result = build_order_blocks(snapshot=_make_snapshot())
        assert result["OB_CONTEXT_SCORE"] == 0

    def test_max_score(self):
        result = build_order_blocks(
            snapshot=_make_snapshot(
                nearest_bull_ob_level=98.0,
                bull_ob_freshness=4,
                bull_ob_fvg_confluence=True,
                ob_density=4,
                ob_strength_score=4,
            )
        )
        assert result["OB_CONTEXT_SCORE"] == 5


class TestOverrides:
    def test_override_ob_bias(self):
        result = build_order_blocks(overrides={"OB_BIAS": "BULLISH"})
        assert result["OB_BIAS"] == "BULLISH"

    def test_unknown_override_ignored(self):
        result = build_order_blocks(overrides={"NOT_A_FIELD": 42})
        assert "NOT_A_FIELD" not in result
