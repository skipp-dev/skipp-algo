"""Tests for smc_range_profile_regime — 22-field contract."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.smc_range_profile_regime import DEFAULTS, build_range_profile_regime


# ── helpers ─────────────────────────────────────────────────────

def _bars(n: int = 20, *, base: float = 100.0, spread: float = 2.0,
          trend: float = 0.0, volume: float = 1000.0) -> pd.DataFrame:
    """Generate synthetic OHLCV bars."""
    rng = np.random.default_rng(42)
    closes = base + np.cumsum(rng.normal(trend, spread / 10, n))
    highs = closes + rng.uniform(0.1, spread / 2, n)
    lows = closes - rng.uniform(0.1, spread / 2, n)
    opens = closes + rng.normal(0, 0.1, n)
    volumes = rng.uniform(volume * 0.5, volume * 1.5, n)
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    })


# ═════════════════════════════════════════════════════════════════
# 1. Defaults / contract
# ═════════════════════════════════════════════════════════════════


class TestDefaults:
    def test_field_count(self):
        assert len(DEFAULTS) == 22

    def test_no_args_returns_defaults(self):
        result = build_range_profile_regime()
        assert set(result.keys()) == set(DEFAULTS.keys())

    def test_none_snapshot_returns_defaults(self):
        result = build_range_profile_regime(snapshot=None)
        assert result["RANGE_ACTIVE"] is False
        assert result["RANGE_BREAK_DIRECTION"] == "NONE"
        assert result["PROFILE_SENTIMENT_BIAS"] == "NEUTRAL"

    def test_empty_snapshot_returns_defaults(self):
        result = build_range_profile_regime(snapshot=pd.DataFrame())
        assert result["PRED_RANGE_MID"] == 0.0


# ═════════════════════════════════════════════════════════════════
# 2. Range boundaries
# ═════════════════════════════════════════════════════════════════


class TestRangeBoundaries:
    @pytest.fixture()
    def result(self):
        return build_range_profile_regime(snapshot=_bars(20))

    def test_range_top_positive(self, result):
        assert result["RANGE_TOP"] > 0

    def test_range_bottom_positive(self, result):
        assert result["RANGE_BOTTOM"] > 0

    def test_top_above_bottom(self, result):
        assert result["RANGE_TOP"] > result["RANGE_BOTTOM"]

    def test_mid_between(self, result):
        assert result["RANGE_BOTTOM"] <= result["RANGE_MID"] <= result["RANGE_TOP"]

    def test_width_atr_positive(self, result):
        assert result["RANGE_WIDTH_ATR"] > 0

    def test_range_active_flag(self, result):
        assert isinstance(result["RANGE_ACTIVE"], bool)


# ═════════════════════════════════════════════════════════════════
# 3. Profile / volume
# ═════════════════════════════════════════════════════════════════


class TestProfile:
    @pytest.fixture()
    def result(self):
        return build_range_profile_regime(snapshot=_bars(30, volume=5000))

    def test_poc_populated(self, result):
        assert result["PROFILE_POC"] > 0

    def test_value_area_top_above_bottom(self, result):
        assert result["PROFILE_VALUE_AREA_TOP"] >= result["PROFILE_VALUE_AREA_BOTTOM"]

    def test_value_area_active_bool(self, result):
        assert isinstance(result["PROFILE_VALUE_AREA_ACTIVE"], bool)


# ═════════════════════════════════════════════════════════════════
# 4. Sentiment
# ═════════════════════════════════════════════════════════════════


class TestSentiment:
    def test_sentiment_sums_to_one_approx(self):
        result = build_range_profile_regime(snapshot=_bars(20))
        total = result["PROFILE_BULLISH_SENTIMENT"] + result["PROFILE_BEARISH_SENTIMENT"]
        # Can be <1 if there are flat bars
        assert 0.5 <= total <= 1.0

    def test_bias_valid_values(self):
        result = build_range_profile_regime(snapshot=_bars(20))
        assert result["PROFILE_SENTIMENT_BIAS"] in ("BULL", "BEAR", "NEUTRAL")


# ═════════════════════════════════════════════════════════════════
# 5. Liquidity distribution
# ═════════════════════════════════════════════════════════════════


class TestLiquidity:
    def test_above_below_pct_non_negative(self):
        result = build_range_profile_regime(snapshot=_bars(20))
        assert result["LIQUIDITY_ABOVE_PCT"] >= 0
        assert result["LIQUIDITY_BELOW_PCT"] >= 0

    def test_imbalance_is_diff(self):
        result = build_range_profile_regime(snapshot=_bars(20))
        expected = round(result["LIQUIDITY_ABOVE_PCT"] - result["LIQUIDITY_BELOW_PCT"], 4)
        assert result["LIQUIDITY_IMBALANCE"] == expected


# ═════════════════════════════════════════════════════════════════
# 6. Predictive range bands
# ═════════════════════════════════════════════════════════════════


class TestPredictiveBands:
    @pytest.fixture()
    def result(self):
        return build_range_profile_regime(snapshot=_bars(20))

    def test_pred_mid_populated(self, result):
        assert result["PRED_RANGE_MID"] > 0

    def test_upper_bands_ordered(self, result):
        assert result["PRED_RANGE_UPPER_2"] >= result["PRED_RANGE_UPPER_1"]

    def test_lower_bands_ordered(self, result):
        assert result["PRED_RANGE_LOWER_2"] <= result["PRED_RANGE_LOWER_1"]

    def test_extreme_is_bool(self, result):
        assert isinstance(result["IN_PREDICTIVE_RANGE_EXTREME"], bool)


# ═════════════════════════════════════════════════════════════════
# 7. Breakout detection
# ═════════════════════════════════════════════════════════════════


class TestBreakout:
    def test_no_breakout_default(self):
        result = build_range_profile_regime(snapshot=_bars(20, spread=0.5))
        assert result["RANGE_BREAK_DIRECTION"] in ("NONE", "UP", "DOWN")

    def test_forced_breakout_up(self):
        df = _bars(19, base=100.0, spread=0.5)
        # Add one bar far above the range
        spike = pd.DataFrame([{
            "open": 120.0, "high": 125.0, "low": 119.0,
            "close": 122.0, "volume": 5000.0,
        }])
        df = pd.concat([df, spike], ignore_index=True)
        result = build_range_profile_regime(snapshot=df)
        assert result["RANGE_BREAK_DIRECTION"] == "UP"

    def test_forced_breakout_down(self):
        df = _bars(19, base=100.0, spread=0.5)
        spike = pd.DataFrame([{
            "open": 80.0, "high": 81.0, "low": 78.0,
            "close": 79.0, "volume": 5000.0,
        }])
        df = pd.concat([df, spike], ignore_index=True)
        result = build_range_profile_regime(snapshot=df)
        assert result["RANGE_BREAK_DIRECTION"] == "DOWN"


# ═════════════════════════════════════════════════════════════════
# 8. Overrides
# ═════════════════════════════════════════════════════════════════


class TestOverrides:
    def test_override_range_active(self):
        result = build_range_profile_regime(overrides={"RANGE_ACTIVE": True})
        assert result["RANGE_ACTIVE"] is True

    def test_unknown_override_ignored(self):
        result = build_range_profile_regime(overrides={"NOT_A_FIELD": 42})
        assert "NOT_A_FIELD" not in result


# ═════════════════════════════════════════════════════════════════
# 9. Insufficient data
# ═════════════════════════════════════════════════════════════════


class TestInsufficientData:
    def test_two_bars_returns_defaults(self):
        df = _bars(2)
        result = build_range_profile_regime(snapshot=df)
        assert result["RANGE_ACTIVE"] is False

    def test_no_volume_skips_profile(self):
        df = _bars(20).drop(columns=["volume"])
        result = build_range_profile_regime(snapshot=df)
        assert result["PROFILE_POC"] == 0.0

    def test_symbol_filter(self):
        df = _bars(10)
        df["symbol"] = "TSLA"
        result = build_range_profile_regime(snapshot=df, symbol="AAPL")
        # No matching rows → defaults
        assert result["RANGE_ACTIVE"] is False
