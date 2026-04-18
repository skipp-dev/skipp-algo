"""Tests for scripts/smc_library_layering.py."""

from __future__ import annotations

import pytest

from scripts.smc_library_layering import compute_library_layering
from smc_core.layering import TECH_WEIGHT, NEWS_WEIGHT, evaluate_sentiment_impact


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


# ---------------------------------------------------------------------------
# WP-12 (F-10): Weight constants are observable
# ---------------------------------------------------------------------------

class TestSentimentWeights:
    def test_weights_are_named_constants(self):
        assert TECH_WEIGHT == 0.7
        assert NEWS_WEIGHT == 0.3

    def test_weights_sum_to_one(self):
        assert TECH_WEIGHT + NEWS_WEIGHT == pytest.approx(1.0)

    def test_heat_uses_named_weights(self):
        """Formula matches TECH_WEIGHT/NEWS_WEIGHT constants."""
        result = compute_library_layering(
            technical_strength=1.0,
            technical_bias="BULLISH",
            news="BEARISH",
        )
        # signed_tech=1.0, signed_news=-0.5
        expected = 1.0 * TECH_WEIGHT + (-0.5) * NEWS_WEIGHT
        assert result["global_heat"] == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# WP-20: Sentiment impact evaluation — decidable measurement path
# ---------------------------------------------------------------------------

class TestSentimentImpact:
    def test_no_news_zero_delta(self):
        r = evaluate_sentiment_impact(0.5, 0.0)
        assert r["news_delta"] == pytest.approx(0.0, abs=0.01)

    def test_news_increases_conviction(self):
        r = evaluate_sentiment_impact(0.5, 0.8)
        assert r["heat_with_news"] > r["heat_without_news"]
        assert r["news_delta"] > 0

    def test_opposing_news_reduces_heat(self):
        r = evaluate_sentiment_impact(0.5, -0.8)
        assert r["heat_with_news"] < r["heat_without_news"]
        assert r["news_delta"] > 0

    def test_contribution_pct_bounded(self):
        r = evaluate_sentiment_impact(0.5, 1.0)
        assert 0 <= r["news_contribution_pct"] <= 100

    def test_zero_inputs_no_crash(self):
        r = evaluate_sentiment_impact(0.0, 0.0)
        assert r["news_contribution_pct"] == 0.0
        assert r["news_delta"] == 0.0
