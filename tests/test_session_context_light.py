"""Tests for smc_session_context_light adapter.

Covers: required field pass-through, optional volatility state derivation,
behavior with and without compression_regime data.
"""
from __future__ import annotations

import pytest
from scripts.smc_session_context_light import (
    build_session_context_light,
    DEFAULTS,
    REQUIRED_DEFAULTS,
    OPTIONAL_DEFAULTS,
)


class TestRequiredFieldPassthrough:
    """4 required fields must always pass through correctly."""

    def test_defaults_when_no_input(self):
        result = build_session_context_light()
        assert result["SESSION_CONTEXT"] == "NONE"
        assert result["IN_KILLZONE"] is False
        assert result["SESSION_DIRECTION_BIAS"] == "NEUTRAL"
        assert result["SESSION_CONTEXT_SCORE"] == 0

    def test_passthrough_values(self):
        sc = {
            "SESSION_CONTEXT": "LONDON",
            "IN_KILLZONE": True,
            "SESSION_DIRECTION_BIAS": "BULLISH",
            "SESSION_CONTEXT_SCORE": 5,
        }
        result = build_session_context_light(session_context=sc)
        assert result["SESSION_CONTEXT"] == "LONDON"
        assert result["IN_KILLZONE"] is True
        assert result["SESSION_DIRECTION_BIAS"] == "BULLISH"
        assert result["SESSION_CONTEXT_SCORE"] == 5


class TestVolatilityStateWithData:
    """SESSION_VOLATILITY_STATE derivation when compression_regime is available."""

    def test_squeeze_maps_to_low(self):
        result = build_session_context_light(
            compression_regime={"SQUEEZE_ON": True, "ATR_REGIME": "COMPRESSION"}
        )
        assert result["SESSION_VOLATILITY_STATE"] == "LOW"

    def test_compression_regime_maps_to_low(self):
        result = build_session_context_light(
            compression_regime={"ATR_REGIME": "COMPRESSION"}
        )
        assert result["SESSION_VOLATILITY_STATE"] == "LOW"

    def test_expansion_extreme(self):
        result = build_session_context_light(
            compression_regime={"ATR_REGIME": "EXPANSION", "ATR_RATIO": 2.5}
        )
        assert result["SESSION_VOLATILITY_STATE"] == "EXTREME"

    def test_expansion_high(self):
        result = build_session_context_light(
            compression_regime={"ATR_REGIME": "EXPANSION", "ATR_RATIO": 1.5}
        )
        assert result["SESSION_VOLATILITY_STATE"] == "HIGH"

    def test_exhaustion_high(self):
        result = build_session_context_light(
            compression_regime={"ATR_REGIME": "EXHAUSTION"}
        )
        assert result["SESSION_VOLATILITY_STATE"] == "HIGH"

    def test_normal_regime(self):
        result = build_session_context_light(
            compression_regime={"ATR_REGIME": "NORMAL"}
        )
        assert result["SESSION_VOLATILITY_STATE"] == "NORMAL"


class TestVolatilityStateWithout:
    """SESSION_VOLATILITY_STATE when compression_regime is absent."""

    def test_no_compression_defaults_to_normal(self):
        result = build_session_context_light(session_context={"SESSION_CONTEXT": "NY_AM"})
        assert result["SESSION_VOLATILITY_STATE"] == "NORMAL"

    def test_none_compression_defaults_to_normal(self):
        result = build_session_context_light(
            session_context={"SESSION_CONTEXT": "LONDON"},
            compression_regime=None,
        )
        assert result["SESSION_VOLATILITY_STATE"] == "NORMAL"

    def test_empty_compression_defaults_to_normal(self):
        result = build_session_context_light(compression_regime={})
        assert result["SESSION_VOLATILITY_STATE"] == "NORMAL"

    def test_runtime_functional_without_volatility(self):
        """All 4 required fields work correctly regardless of volatility state."""
        sc = {
            "SESSION_CONTEXT": "NY_AM",
            "IN_KILLZONE": True,
            "SESSION_DIRECTION_BIAS": "BULLISH",
            "SESSION_CONTEXT_SCORE": 6,
        }
        result = build_session_context_light(session_context=sc)
        # Required fields are correct
        assert result["SESSION_CONTEXT"] == "NY_AM"
        assert result["IN_KILLZONE"] is True
        assert result["SESSION_DIRECTION_BIAS"] == "BULLISH"
        assert result["SESSION_CONTEXT_SCORE"] == 6
        # Optional field falls back to safe default
        assert result["SESSION_VOLATILITY_STATE"] == "NORMAL"


class TestDefaults:
    """Verify default structure matches v5.5b contract."""

    def test_required_defaults_count(self):
        assert len(REQUIRED_DEFAULTS) == 4

    def test_optional_defaults_count(self):
        assert len(OPTIONAL_DEFAULTS) == 1

    def test_combined_defaults_count(self):
        assert len(DEFAULTS) == 5

    def test_overrides(self):
        result = build_session_context_light(
            overrides={"SESSION_VOLATILITY_STATE": "HIGH"}
        )
        assert result["SESSION_VOLATILITY_STATE"] == "HIGH"
