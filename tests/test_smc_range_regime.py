"""Tests for smc_range_regime (AP4 v5.3).

11 fields, covering:
  - defaults / neutral outputs
  - trending regime detection
  - ranging regime detection
  - breakout regime detection
  - range position (HIGH/MID/LOW)
  - range duration
  - volume profile (VPOC, VAH, VAL)
  - balance state
  - regime score
  - overrides & symbol filter
  - return contract
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_range_regime import DEFAULTS, build_range_regime


# ── Test data helpers ────────────────────────────────────────────────

def _trending_up_bars() -> pd.DataFrame:
    """Strong uptrend — slope well above threshold."""
    return pd.DataFrame({
        "open":  [100, 102, 104, 106, 108, 110, 112, 114, 116, 118],
        "high":  [102, 104, 106, 108, 110, 112, 114, 116, 118, 120],
        "low":   [99,  101, 103, 105, 107, 109, 111, 113, 115, 117],
        "close": [101, 103, 105, 107, 109, 111, 113, 115, 117, 119],
    })


def _ranging_bars() -> pd.DataFrame:
    """Tight range — oscillates within a narrow band."""
    return pd.DataFrame({
        "open":  [100, 100.5, 100, 100.5, 100, 100.5, 100, 100.5, 100, 100.5],
        "high":  [101, 101,   101, 101,   101, 101,   101, 101,   101, 101],
        "low":   [99,  99.5,  99,  99.5,  99,  99.5,  99,  99.5,  99,  99.5],
        "close": [100.5, 100, 100.5, 100, 100.5, 100, 100.5, 100, 100.5, 100],
    })


def _breakout_bars() -> pd.DataFrame:
    """Range then breakout — last bar explodes beyond range + ATR×1.5."""
    return pd.DataFrame({
        "open":  [100, 100.5, 100, 100.5, 100, 100.5, 100, 100.5, 100, 115],
        "high":  [101, 101,   101, 101,   101, 101,   101, 101,   101, 120],
        "low":   [99,  99.5,  99,  99.5,  99,  99.5,  99,  99.5,  99,  114],
        "close": [100.5, 100, 100.5, 100, 100.5, 100, 100.5, 100, 100.5, 118],
    })


def _bars_close_at_high() -> pd.DataFrame:
    """Bars with close near range high → RANGE_POSITION = HIGH."""
    return pd.DataFrame({
        "open":  [100, 101, 102, 103, 104],
        "high":  [102, 103, 104, 105, 106],
        "low":   [99,  100, 101, 102, 103],
        "close": [101, 102, 103, 104, 105.5],
    })


def _bars_close_at_low() -> pd.DataFrame:
    """Bars with close near range low → RANGE_POSITION = LOW."""
    return pd.DataFrame({
        "open":  [106, 105, 104, 103, 102],
        "high":  [107, 106, 105, 104, 103],
        "low":   [104, 103, 102, 101, 100],
        "close": [105, 104, 103, 102, 100.5],
    })


def _bars_with_volume() -> pd.DataFrame:
    """Bars with volume data for VPOC/VAH/VAL detection."""
    return pd.DataFrame({
        "open":   [100, 102, 103, 104, 103, 102, 101, 103, 104, 102],
        "high":   [102, 104, 105, 106, 105, 104, 103, 105, 106, 104],
        "low":    [99,  101, 102, 103, 102, 101, 100, 102, 103, 101],
        "close":  [101, 103, 104, 105, 103, 102, 101, 104, 105, 103],
        "volume": [100, 200, 500, 800, 300, 200, 100, 600, 900, 400],
    })


def _flat_bars() -> pd.DataFrame:
    """No movement at all."""
    return pd.DataFrame({
        "open":  [100, 100, 100],
        "high":  [100, 100, 100],
        "low":   [100, 100, 100],
        "close": [100, 100, 100],
    })


# ── Tests ────────────────────────────────────────────────────────────

class TestDefaults:
    def test_field_count(self):
        assert len(DEFAULTS) == 11

    def test_all_neutral(self):
        result = build_range_regime()
        assert result == DEFAULTS


class TestNoneInputs:
    def test_none_snapshot(self):
        result = build_range_regime(snapshot=None)
        assert result == DEFAULTS

    def test_empty_df(self):
        result = build_range_regime(snapshot=pd.DataFrame())
        assert result == DEFAULTS

    def test_too_few_bars(self):
        df = pd.DataFrame({"open": [1, 2], "high": [2, 3], "low": [0, 1], "close": [1, 2]})
        result = build_range_regime(snapshot=df)
        assert result == DEFAULTS


class TestTrendingRegime:
    def test_trending_detected(self):
        result = build_range_regime(snapshot=_trending_up_bars())
        assert result["RANGE_REGIME"] == "TRENDING"

    def test_trending_imbalanced(self):
        result = build_range_regime(snapshot=_trending_up_bars())
        assert result["RANGE_BALANCE_STATE"] == "IMBALANCED_UP"


class TestRangingRegime:
    def test_ranging_detected(self):
        result = build_range_regime(snapshot=_ranging_bars())
        assert result["RANGE_REGIME"] == "RANGING"

    def test_ranging_balanced(self):
        result = build_range_regime(snapshot=_ranging_bars())
        assert result["RANGE_BALANCE_STATE"] == "BALANCED"


class TestBreakoutRegime:
    def test_breakout_detected(self):
        result = build_range_regime(snapshot=_breakout_bars())
        assert result["RANGE_REGIME"] == "BREAKOUT"


class TestRangePosition:
    def test_position_high(self):
        result = build_range_regime(snapshot=_bars_close_at_high())
        assert result["RANGE_POSITION"] == "HIGH"

    def test_position_low(self):
        result = build_range_regime(snapshot=_bars_close_at_low())
        assert result["RANGE_POSITION"] == "LOW"

    def test_position_mid_ranging(self):
        result = build_range_regime(snapshot=_ranging_bars())
        assert result["RANGE_POSITION"] == "MID"


class TestRangeBoundaries:
    def test_range_high_low(self):
        result = build_range_regime(snapshot=_trending_up_bars())
        assert result["RANGE_HIGH"] == 120
        assert result["RANGE_LOW"] == 99

    def test_range_width_pct(self):
        result = build_range_regime(snapshot=_trending_up_bars())
        assert result["RANGE_WIDTH_PCT"] > 0


class TestRangeDuration:
    def test_ranging_all_bars_within(self):
        result = build_range_regime(snapshot=_ranging_bars())
        assert result["RANGE_DURATION_BARS"] == len(_ranging_bars())


class TestVolumeProfile:
    def test_vpoc_populated(self):
        result = build_range_regime(snapshot=_bars_with_volume())
        assert result["RANGE_VPOC_LEVEL"] > 0

    def test_vah_above_val(self):
        result = build_range_regime(snapshot=_bars_with_volume())
        assert result["RANGE_VAH_LEVEL"] >= result["RANGE_VAL_LEVEL"]

    def test_no_volume_no_profile(self):
        result = build_range_regime(snapshot=_ranging_bars())
        assert result["RANGE_VPOC_LEVEL"] == 0.0


class TestRegimeScore:
    def test_trending_has_score(self):
        result = build_range_regime(snapshot=_trending_up_bars())
        assert result["RANGE_REGIME_SCORE"] >= 2

    def test_flat_low_score(self):
        result = build_range_regime(snapshot=_flat_bars())
        # flat bars still produce RANGING (width=0%) but not much confidence
        assert result["RANGE_REGIME_SCORE"] <= 2


class TestOverrides:
    def test_override_applied(self):
        result = build_range_regime(
            snapshot=_ranging_bars(),
            overrides={"RANGE_REGIME": "BREAKOUT"},
        )
        assert result["RANGE_REGIME"] == "BREAKOUT"

    def test_unknown_override_ignored(self):
        result = build_range_regime(overrides={"UNKNOWN": 999})
        assert "UNKNOWN" not in result


class TestSymbolFilter:
    def test_matching_symbol(self):
        df = _trending_up_bars().copy()
        df["symbol"] = "AAPL"
        result = build_range_regime(snapshot=df, symbol="AAPL")
        assert result["RANGE_REGIME"] == "TRENDING"

    def test_non_matching_symbol(self):
        df = _trending_up_bars().copy()
        df["symbol"] = "AAPL"
        result = build_range_regime(snapshot=df, symbol="MSFT")
        assert result == DEFAULTS


class TestReturnContract:
    def test_all_keys_present(self):
        result = build_range_regime(snapshot=_trending_up_bars())
        for key in DEFAULTS:
            assert key in result, f"Missing key: {key}"

    def test_no_extra_keys(self):
        result = build_range_regime(snapshot=_trending_up_bars())
        for key in result:
            assert key in DEFAULTS, f"Extra key: {key}"

    def test_returns_dict(self):
        result = build_range_regime()
        assert isinstance(result, dict)
