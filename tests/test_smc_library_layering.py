"""Tests for scripts/smc_library_layering.py."""

from __future__ import annotations

import pytest

from scripts.smc_library_layering import compute_library_layering


class TestNeutralDefaults:
    def test_defaults_return_neutral_tone(self):
        result = compute_library_layering()
        assert result["tone"] == "NEUTRAL"

    def test_defaults_return_allowed(self):
        result = compute_library_layering()
        assert result["trade_state"] == "ALLOWED"

    def test_defaults_keys(self):
        result = compute_library_layering()
        assert set(result.keys()) == {"global_heat", "global_strength", "tone", "trade_state"}


class TestBullishHeat:
    def test_bullish_tech_produces_bullish_tone(self):
        result = compute_library_layering(technical_strength=0.8, technical_bias="BULLISH")
        assert result["tone"] == "BULLISH"
        assert result["global_heat"] > 0.15


class TestBearishHeat:
    def test_bearish_tech_and_news_produces_bearish_tone(self):
        result = compute_library_layering(
            technical_strength=0.3,
            technical_bias="BEARISH",
            news="BEARISH",
        )
        assert result["tone"] == "BEARISH"
        assert result["global_heat"] < -0.15


class TestRiskOffDiscouraged:
    def test_risk_off_regime_sets_discouraged(self):
        result = compute_library_layering(regime="RISK_OFF")
        assert result["trade_state"] == "DISCOURAGED"

    def test_rotation_regime_sets_discouraged(self):
        result = compute_library_layering(regime="ROTATION")
        assert result["trade_state"] == "DISCOURAGED"


class TestHolidayBlocked:
    def test_holiday_suspect_sets_blocked(self):
        result = compute_library_layering(volume_regime="HOLIDAY_SUSPECT")
        assert result["trade_state"] == "BLOCKED"

    def test_low_volume_sets_discouraged(self):
        result = compute_library_layering(volume_regime="LOW_VOLUME")
        assert result["trade_state"] == "DISCOURAGED"


class TestHeatFormula:
    def test_exact_formula(self):
        # signed_tech = 0.8 (BULLISH), signed_news = -0.5 * 1.0 = -0.5 (BEARISH strength 0.5)
        # global_heat = 0.8 * 0.7 + (-0.5) * 0.3 = 0.56 - 0.15 = 0.41
        result = compute_library_layering(
            technical_strength=0.8,
            technical_bias="BULLISH",
            news="BEARISH",
        )
        # news="BEARISH" → strength=0.5, bias=BEARISH → signed_news = -0.5
        # global_heat = 0.8 * 0.7 + (-0.5) * 0.3 = 0.56 - 0.15 = 0.41
        assert result["global_heat"] == pytest.approx(0.41, abs=0.01)

    def test_strength_at_least_abs_heat(self):
        result = compute_library_layering(
            technical_strength=0.6,
            technical_bias="BULLISH",
        )
        assert result["global_strength"] >= abs(result["global_heat"])
