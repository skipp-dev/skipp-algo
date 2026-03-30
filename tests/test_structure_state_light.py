"""Semantic tests for the v5.5 Structure State Light adapter."""
from __future__ import annotations

from scripts.smc_structure_state_light import build_structure_state_light, DEFAULTS


class TestDefaults:
    def test_no_input_returns_safe_structure(self):
        result = build_structure_state_light()
        assert result["STRUCTURE_LAST_EVENT"] == "NONE"
        assert result["STRUCTURE_EVENT_AGE_BARS"] == 0
        assert result["STRUCTURE_FRESH"] is False
        # Empty input still computes base strength (NEUTRAL=10 + aging bonus)
        assert result["STRUCTURE_TREND_STRENGTH"] >= 0

    def test_field_count(self):
        assert len(DEFAULTS) == 4

    def test_default_trend_strength_zero(self):
        assert DEFAULTS["STRUCTURE_TREND_STRENGTH"] == 0

    def test_default_fresh_false(self):
        assert DEFAULTS["STRUCTURE_FRESH"] is False


class TestTrendStrength:
    def test_bullish_fresh_bos_sr(self):
        """Maximum strength: directional + fresh + BOS + S/R."""
        ss = {
            "STRUCTURE_STATE": "BULLISH",
            "STRUCTURE_FRESH": True,
            "STRUCTURE_LAST_EVENT": "BOS_BULL",
            "STRUCTURE_EVENT_AGE_BARS": 2,
            "BOS_BULL": True,
            "SUPPORT_ACTIVE": True,
            "RESISTANCE_ACTIVE": True,
        }
        result = build_structure_state_light(structure_state=ss)
        assert result["STRUCTURE_TREND_STRENGTH"] == 100  # 40+30+15+15

    def test_neutral_stale(self):
        ss = {
            "STRUCTURE_STATE": "NEUTRAL",
            "STRUCTURE_FRESH": False,
            "STRUCTURE_EVENT_AGE_BARS": 50,
            "STRUCTURE_LAST_EVENT": "NONE",
        }
        result = build_structure_state_light(structure_state=ss)
        assert result["STRUCTURE_TREND_STRENGTH"] == 10  # only neutral base

    def test_bearish_direction_adds_base(self):
        ss = {
            "STRUCTURE_STATE": "BEARISH",
            "STRUCTURE_FRESH": False,
            "STRUCTURE_EVENT_AGE_BARS": 50,
            "STRUCTURE_LAST_EVENT": "NONE",
        }
        result = build_structure_state_light(structure_state=ss)
        assert result["STRUCTURE_TREND_STRENGTH"] == 40  # directional base only

    def test_aging_freshness_bonus(self):
        """Age 10 bars -> 15 pts freshness bonus."""
        ss = {
            "STRUCTURE_STATE": "BULLISH",
            "STRUCTURE_FRESH": False,
            "STRUCTURE_EVENT_AGE_BARS": 10,
            "STRUCTURE_LAST_EVENT": "BOS_BULL",
        }
        result = build_structure_state_light(structure_state=ss)
        # 40 (directional) + 15 (aging <= 15) + 8 (BOS_ prefix) = 63
        assert result["STRUCTURE_TREND_STRENGTH"] == 63

    def test_bos_in_direction(self):
        """BOS in trend direction gives full 15 bonus."""
        ss = {
            "STRUCTURE_STATE": "BEARISH",
            "STRUCTURE_FRESH": False,
            "STRUCTURE_EVENT_AGE_BARS": 50,
            "BOS_BEAR": True,
            "STRUCTURE_LAST_EVENT": "NONE",
        }
        result = build_structure_state_light(structure_state=ss)
        assert result["STRUCTURE_TREND_STRENGTH"] == 55  # 40 + 15

    def test_partial_sr_bonus(self):
        ss = {
            "STRUCTURE_STATE": "BULLISH",
            "STRUCTURE_FRESH": False,
            "STRUCTURE_EVENT_AGE_BARS": 50,
            "SUPPORT_ACTIVE": True,
            "STRUCTURE_LAST_EVENT": "NONE",
        }
        result = build_structure_state_light(structure_state=ss)
        assert result["STRUCTURE_TREND_STRENGTH"] == 48  # 40 + 8

    def test_clamped_to_100(self):
        """Strength must never exceed 100."""
        ss = {
            "STRUCTURE_STATE": "BULLISH",
            "STRUCTURE_FRESH": True,
            "STRUCTURE_EVENT_AGE_BARS": 1,
            "STRUCTURE_LAST_EVENT": "BOS_BULL",
            "BOS_BULL": True,
            "SUPPORT_ACTIVE": True,
            "RESISTANCE_ACTIVE": True,
        }
        result = build_structure_state_light(structure_state=ss)
        assert result["STRUCTURE_TREND_STRENGTH"] <= 100


class TestPassthrough:
    def test_last_event_passed(self):
        ss = {"STRUCTURE_LAST_EVENT": "CHOCH_BEAR"}
        result = build_structure_state_light(structure_state=ss)
        assert result["STRUCTURE_LAST_EVENT"] == "CHOCH_BEAR"

    def test_age_bars_passed(self):
        ss = {"STRUCTURE_EVENT_AGE_BARS": 42}
        result = build_structure_state_light(structure_state=ss)
        assert result["STRUCTURE_EVENT_AGE_BARS"] == 42

    def test_fresh_passed(self):
        ss = {"STRUCTURE_FRESH": True}
        result = build_structure_state_light(structure_state=ss)
        assert result["STRUCTURE_FRESH"] is True


class TestOverrides:
    def test_override_strength(self):
        result = build_structure_state_light(overrides={"STRUCTURE_TREND_STRENGTH": 88})
        assert result["STRUCTURE_TREND_STRENGTH"] == 88

    def test_override_on_computed(self):
        ss = {
            "STRUCTURE_STATE": "BULLISH",
            "STRUCTURE_FRESH": True,
            "STRUCTURE_LAST_EVENT": "BOS_BULL",
        }
        result = build_structure_state_light(
            structure_state=ss,
            overrides={"STRUCTURE_FRESH": False}
        )
        assert result["STRUCTURE_FRESH"] is False
