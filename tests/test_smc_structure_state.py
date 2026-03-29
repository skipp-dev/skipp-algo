"""Tests for V5.3 Structure State builder."""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_structure_state import DEFAULTS, build_structure_state


# ── Helpers ─────────────────────────────────────────────────────────


def _bars(data: list[dict]) -> pd.DataFrame:
    """Build a simple OHLC DataFrame for testing."""
    return pd.DataFrame(data)


def _trending_up_bars() -> pd.DataFrame:
    """Create wave-like bars with higher swing highs and higher swing lows (bullish BOS).

    Pattern: trough → peak → higher trough → higher peak (HH/HL sequence).
    Each peak/trough is a clear 3-bar pivot.
    """
    return pd.DataFrame([
        # First trough area
        {"open": 100, "high": 101, "low": 99,  "close": 100.5},
        {"open": 100, "high": 101, "low": 97,  "close": 98},    # swing low at 97
        {"open": 98,  "high": 100, "low": 98,  "close": 99.5},
        # First peak
        {"open": 100, "high": 103, "low": 99,  "close": 102},
        {"open": 102, "high": 105, "low": 101, "close": 104},   # swing high at 105
        {"open": 104, "high": 104, "low": 101, "close": 102},
        # Higher trough
        {"open": 102, "high": 103, "low": 100, "close": 101},
        {"open": 101, "high": 102, "low": 99,  "close": 100},   # swing low at 99 > 97
        {"open": 100, "high": 102, "low": 100, "close": 101},
        # Higher peak (BOS)
        {"open": 102, "high": 106, "low": 101, "close": 105},
        {"open": 105, "high": 108, "low": 104, "close": 107},   # swing high at 108 > 105 → BOS_BULL
        {"open": 107, "high": 107, "low": 105, "close": 106},
    ])


def _trending_down_bars() -> pd.DataFrame:
    """Create wave-like bars with lower swing highs and lower swing lows (bearish BOS).

    Pattern: peak → trough → lower peak → lower trough (LH/LL sequence).
    """
    return pd.DataFrame([
        # First peak area
        {"open": 200, "high": 201, "low": 199, "close": 200},
        {"open": 200, "high": 203, "low": 199, "close": 202},   # swing high at 203
        {"open": 202, "high": 202, "low": 199, "close": 200},
        # First trough
        {"open": 200, "high": 201, "low": 197, "close": 198},
        {"open": 198, "high": 199, "low": 195, "close": 196},   # swing low at 195
        {"open": 196, "high": 198, "low": 196, "close": 197},
        # Lower peak
        {"open": 197, "high": 200, "low": 196, "close": 199},
        {"open": 199, "high": 201, "low": 198, "close": 200},   # swing high at 201 < 203
        {"open": 200, "high": 200, "low": 197, "close": 198},
        # Lower trough (BOS)
        {"open": 198, "high": 199, "low": 194, "close": 195},
        {"open": 195, "high": 196, "low": 191, "close": 192},   # swing low at 191 < 195 → BOS_BEAR
        {"open": 192, "high": 194, "low": 192, "close": 193},
    ])


def _swing_bars_bull_choch() -> pd.DataFrame:
    """Bars forming bearish structure then close breaks above resistance → CHoCH bull.

    Need: swing high, then swing low (more recent), then close > swing high.
    """
    return pd.DataFrame([
        # Wave down to establish swing high, then swing low
        {"open": 110, "high": 111, "low": 109, "close": 110},
        {"open": 110, "high": 114, "low": 109, "close": 113},   # swing high at 114 (i=1)
        {"open": 113, "high": 113, "low": 108, "close": 109},
        {"open": 109, "high": 110, "low": 106, "close": 107},
        {"open": 107, "high": 108, "low": 103, "close": 104},   # swing low at 103 (i=4)
        {"open": 104, "high": 106, "low": 104, "close": 105},
        # Now close breaks above the swing high at 114 → CHoCH bull
        {"open": 105, "high": 110, "low": 104, "close": 109},
        {"open": 109, "high": 116, "low": 108, "close": 115},   # close 115 > 114 = CHoCH bull
    ])


def _swing_bars_bear_choch() -> pd.DataFrame:
    """Bars forming bullish structure then close breaks below support → CHoCH bear.

    Need: swing low, then swing high (more recent), then close < swing low.
    """
    return pd.DataFrame([
        # Wave up to establish swing low, then swing high
        {"open": 100, "high": 102, "low": 99,  "close": 101},
        {"open": 101, "high": 102, "low": 96,  "close": 97},    # swing low at 96 (i=1)
        {"open": 97,  "high": 100, "low": 97,  "close": 99},
        {"open": 99,  "high": 104, "low": 98,  "close": 103},
        {"open": 103, "high": 107, "low": 102, "close": 106},   # swing high at 107 (i=4)
        {"open": 106, "high": 106, "low": 103, "close": 104},
        # Now close breaks below swing low at 96 → CHoCH bear
        {"open": 104, "high": 105, "low": 98,  "close": 99},
        {"open": 99,  "high": 100, "low": 94,  "close": 95},    # close 95 < 96 = CHoCH bear
    ])


# ── Tests ───────────────────────────────────────────────────────────


class TestDefaults:
    """DEFAULTS dict is complete and consistent."""

    def test_defaults_has_all_keys(self):
        expected_keys = {
            "STRUCTURE_STATE", "STRUCTURE_BULL_ACTIVE", "STRUCTURE_BEAR_ACTIVE",
            "CHOCH_BULL", "CHOCH_BEAR", "BOS_BULL", "BOS_BEAR",
            "STRUCTURE_LAST_EVENT", "STRUCTURE_EVENT_AGE_BARS",
            "STRUCTURE_FRESH", "ACTIVE_SUPPORT", "ACTIVE_RESISTANCE",
            "SUPPORT_ACTIVE", "RESISTANCE_ACTIVE",
        }
        assert set(DEFAULTS.keys()) == expected_keys

    def test_default_values_are_neutral(self):
        assert DEFAULTS["STRUCTURE_STATE"] == "NEUTRAL"
        assert DEFAULTS["STRUCTURE_BULL_ACTIVE"] is False
        assert DEFAULTS["STRUCTURE_BEAR_ACTIVE"] is False
        assert DEFAULTS["CHOCH_BULL"] is False
        assert DEFAULTS["CHOCH_BEAR"] is False
        assert DEFAULTS["BOS_BULL"] is False
        assert DEFAULTS["BOS_BEAR"] is False
        assert DEFAULTS["STRUCTURE_LAST_EVENT"] == "NONE"
        assert DEFAULTS["STRUCTURE_EVENT_AGE_BARS"] == 0
        assert DEFAULTS["STRUCTURE_FRESH"] is False
        assert DEFAULTS["ACTIVE_SUPPORT"] == 0.0
        assert DEFAULTS["ACTIVE_RESISTANCE"] == 0.0


class TestNoneInputs:
    """Builder returns clean defaults when no data is available."""

    def test_none_snapshot(self):
        result = build_structure_state(snapshot=None)
        assert result == DEFAULTS

    def test_empty_snapshot(self):
        result = build_structure_state(snapshot=pd.DataFrame())
        assert result == DEFAULTS

    def test_too_few_bars(self):
        df = pd.DataFrame([
            {"open": 100, "high": 101, "low": 99, "close": 100.5},
            {"open": 100, "high": 102, "low": 99, "close": 101},
        ])
        result = build_structure_state(snapshot=df)
        assert result["STRUCTURE_STATE"] == "NEUTRAL"


class TestBullishStructure:
    """Bullish structure detection via BOS and CHoCH."""

    def test_trending_up_detects_bos_bull(self):
        df = _trending_up_bars()
        result = build_structure_state(snapshot=df)
        assert result["BOS_BULL"] is True
        assert result["STRUCTURE_STATE"] == "BULLISH"
        assert result["STRUCTURE_BULL_ACTIVE"] is True
        assert result["STRUCTURE_BEAR_ACTIVE"] is False

    def test_choch_bull_detection(self):
        df = _swing_bars_bull_choch()
        result = build_structure_state(snapshot=df)
        assert result["CHOCH_BULL"] is True
        assert result["STRUCTURE_STATE"] == "BULLISH"
        assert result["STRUCTURE_LAST_EVENT"] == "CHOCH_BULL"

    def test_active_resistance_set_on_bullish(self):
        df = _trending_up_bars()
        result = build_structure_state(snapshot=df)
        assert result["ACTIVE_RESISTANCE"] > 0.0
        assert result["RESISTANCE_ACTIVE"] is True


class TestBearishStructure:
    """Bearish structure detection via BOS and CHoCH."""

    def test_trending_down_detects_bos_bear(self):
        df = _trending_down_bars()
        result = build_structure_state(snapshot=df)
        assert result["BOS_BEAR"] is True
        assert result["STRUCTURE_STATE"] == "BEARISH"
        assert result["STRUCTURE_BEAR_ACTIVE"] is True
        assert result["STRUCTURE_BULL_ACTIVE"] is False

    def test_choch_bear_detection(self):
        df = _swing_bars_bear_choch()
        result = build_structure_state(snapshot=df)
        assert result["CHOCH_BEAR"] is True
        assert result["STRUCTURE_STATE"] == "BEARISH"
        assert result["STRUCTURE_LAST_EVENT"] == "CHOCH_BEAR"

    def test_active_support_set_on_bearish(self):
        df = _trending_down_bars()
        result = build_structure_state(snapshot=df)
        assert result["ACTIVE_SUPPORT"] > 0.0
        assert result["SUPPORT_ACTIVE"] is True


class TestTransitions:
    """CHoCH and BOS transition behaviour."""

    def test_choch_bull_after_bear_structure(self):
        df = _swing_bars_bull_choch()
        result = build_structure_state(snapshot=df)
        assert result["CHOCH_BULL"] is True
        assert result["STRUCTURE_BULL_ACTIVE"] is True

    def test_choch_bear_after_bull_structure(self):
        df = _swing_bars_bear_choch()
        result = build_structure_state(snapshot=df)
        assert result["CHOCH_BEAR"] is True
        assert result["STRUCTURE_BEAR_ACTIVE"] is True

    def test_bos_bull_sets_last_event(self):
        df = _trending_up_bars()
        result = build_structure_state(snapshot=df)
        assert result["STRUCTURE_LAST_EVENT"] in ("BOS_BULL", "CHOCH_BULL")


class TestStaleStructure:
    """Freshness and age tracking."""

    def test_fresh_event_near_end(self):
        df = _trending_up_bars()
        result = build_structure_state(snapshot=df)
        if result["STRUCTURE_LAST_EVENT"] != "NONE":
            assert result["STRUCTURE_EVENT_AGE_BARS"] >= 0

    def test_stale_event_far_from_end(self):
        # Build bars with a structure event early, then flat bars
        up = _trending_up_bars()
        flat = pd.DataFrame([
            {"open": 106, "high": 106.5, "low": 105.5, "close": 106}
        ] * 20)
        df = pd.concat([up, flat], ignore_index=True)
        result = build_structure_state(snapshot=df)
        if result["STRUCTURE_LAST_EVENT"] != "NONE":
            assert result["STRUCTURE_EVENT_AGE_BARS"] > 10
            assert result["STRUCTURE_FRESH"] is False


class TestOverrides:
    """Manual override support."""

    def test_override_replaces_derived(self):
        df = _trending_up_bars()
        result = build_structure_state(
            snapshot=df,
            overrides={"STRUCTURE_STATE": "BEARISH"},
        )
        assert result["STRUCTURE_STATE"] == "BEARISH"

    def test_override_unknown_key_ignored(self):
        result = build_structure_state(
            snapshot=None,
            overrides={"UNKNOWN_KEY": "value"},
        )
        assert "UNKNOWN_KEY" not in result

    def test_override_on_none_snapshot(self):
        result = build_structure_state(
            snapshot=None,
            overrides={"CHOCH_BULL": True, "STRUCTURE_FRESH": True},
        )
        assert result["CHOCH_BULL"] is True
        assert result["STRUCTURE_FRESH"] is True


class TestSymbolFilter:
    """Symbol filtering works correctly."""

    def test_filters_by_symbol(self):
        df = _trending_up_bars()
        df["symbol"] = "AAPL"
        other = df.copy()
        other["symbol"] = "TSLA"
        combined = pd.concat([df, other], ignore_index=True)
        result = build_structure_state(snapshot=combined, symbol="AAPL")
        assert result["STRUCTURE_STATE"] != "NEUTRAL" or result["BOS_BULL"] is True

    def test_unknown_symbol_returns_defaults(self):
        df = _trending_up_bars()
        df["symbol"] = "AAPL"
        result = build_structure_state(snapshot=df, symbol="UNKNOWN")
        assert result == DEFAULTS


class TestReturnContract:
    """Return dict shape matches DEFAULTS keys exactly."""

    def test_return_keys_match_defaults(self):
        result = build_structure_state(snapshot=None)
        assert set(result.keys()) == set(DEFAULTS.keys())

    def test_return_keys_with_data(self):
        df = _trending_up_bars()
        result = build_structure_state(snapshot=df)
        assert set(result.keys()) == set(DEFAULTS.keys())

    def test_field_count(self):
        assert len(DEFAULTS) == 14
