"""Tests for smc_liquidity_pools — liquidity pools layer (v5.2).

Covers:
- neutral/default mode
- buy-side pool detection
- sell-side pool detection
- imbalance computation
- magnet direction
- quality score
- override merging
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_liquidity_pools import DEFAULTS, build_liquidity_pools


def _make_snapshot(**kwargs) -> pd.DataFrame:
    defaults = {
        "symbol": "AAPL",
        "buy_side_pool_level": 0.0,
        "sell_side_pool_level": 0.0,
        "buy_side_pool_strength": 0,
        "sell_side_pool_strength": 0,
        "pool_proximity_pct": 0.0,
        "pool_cluster_density": 0,
        "untested_buy_pools": 0,
        "untested_sell_pools": 0,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


class TestNeutralDefaults:
    def test_no_snapshot_returns_defaults(self):
        result = build_liquidity_pools()
        assert result == DEFAULTS

    def test_none_snapshot_returns_defaults(self):
        result = build_liquidity_pools(snapshot=None)
        assert result == DEFAULTS

    def test_empty_snapshot_returns_defaults(self):
        result = build_liquidity_pools(snapshot=pd.DataFrame())
        assert result == DEFAULTS

    def test_all_keys_present(self):
        result = build_liquidity_pools()
        assert set(result.keys()) == set(DEFAULTS.keys())


class TestBuySidePool:
    @pytest.fixture()
    def result(self):
        return build_liquidity_pools(
            snapshot=_make_snapshot(
                buy_side_pool_level=105.0,
                buy_side_pool_strength=4,
                pool_proximity_pct=0.5,
                pool_cluster_density=3,
                untested_buy_pools=3,
            )
        )

    def test_pool_level(self, result):
        assert result["BUY_SIDE_POOL_LEVEL"] == 105.0

    def test_pool_strength(self, result):
        assert result["BUY_SIDE_POOL_STRENGTH"] == 4

    def test_proximity(self, result):
        assert result["POOL_PROXIMITY_PCT"] == 0.5

    def test_imbalance_positive(self, result):
        assert result["POOL_IMBALANCE"] > 0

    def test_magnet_up(self, result):
        assert result["POOL_MAGNET_DIRECTION"] == "UP"

    def test_quality_high(self, result):
        assert result["POOL_QUALITY_SCORE"] >= 4


class TestSellSidePool:
    @pytest.fixture()
    def result(self):
        return build_liquidity_pools(
            snapshot=_make_snapshot(
                sell_side_pool_level=95.0,
                sell_side_pool_strength=4,
                pool_proximity_pct=0.8,
                pool_cluster_density=4,
                untested_sell_pools=5,
            )
        )

    def test_pool_level(self, result):
        assert result["SELL_SIDE_POOL_LEVEL"] == 95.0

    def test_imbalance_negative(self, result):
        assert result["POOL_IMBALANCE"] < 0

    def test_magnet_down(self, result):
        assert result["POOL_MAGNET_DIRECTION"] == "DOWN"


class TestImbalance:
    def test_balanced(self):
        result = build_liquidity_pools(
            snapshot=_make_snapshot(
                buy_side_pool_strength=3,
                sell_side_pool_strength=3,
                untested_buy_pools=2,
                untested_sell_pools=2,
            )
        )
        assert result["POOL_IMBALANCE"] == 0.0
        assert result["POOL_MAGNET_DIRECTION"] == "NONE"

    def test_no_data_zero(self):
        result = build_liquidity_pools(snapshot=_make_snapshot())
        assert result["POOL_IMBALANCE"] == 0.0


class TestStrengthClamping:
    def test_strength_clamped_high(self):
        result = build_liquidity_pools(
            snapshot=_make_snapshot(buy_side_pool_strength=10)
        )
        assert result["BUY_SIDE_POOL_STRENGTH"] == 5

    def test_strength_clamped_low(self):
        result = build_liquidity_pools(
            snapshot=_make_snapshot(sell_side_pool_strength=-1)
        )
        assert result["SELL_SIDE_POOL_STRENGTH"] == 0


class TestQualityScore:
    def test_zero_no_data(self):
        result = build_liquidity_pools(snapshot=_make_snapshot())
        assert result["POOL_QUALITY_SCORE"] == 0

    def test_max_score(self):
        result = build_liquidity_pools(
            snapshot=_make_snapshot(
                buy_side_pool_level=105.0,
                buy_side_pool_strength=4,
                pool_proximity_pct=0.5,
                pool_cluster_density=4,
                untested_buy_pools=5,
            )
        )
        assert result["POOL_QUALITY_SCORE"] == 5


class TestOverrides:
    def test_override_magnet_direction(self):
        result = build_liquidity_pools(
            overrides={"POOL_MAGNET_DIRECTION": "UP"},
        )
        assert result["POOL_MAGNET_DIRECTION"] == "UP"

    def test_unknown_override_ignored(self):
        result = build_liquidity_pools(overrides={"NOT_A_FIELD": 42})
        assert "NOT_A_FIELD" not in result
