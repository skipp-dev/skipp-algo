"""Semantic tests for the v5.5 Event Risk Light adapter."""
from __future__ import annotations

from scripts.smc_event_risk_light import build_event_risk_light, DEFAULTS


class TestDefaults:
    def test_no_input_returns_defaults(self):
        result = build_event_risk_light()
        assert result == DEFAULTS

    def test_default_window_state_is_clear(self):
        assert DEFAULTS["EVENT_WINDOW_STATE"] == "CLEAR"

    def test_default_blocks_are_false(self):
        assert DEFAULTS["MARKET_EVENT_BLOCKED"] is False
        assert DEFAULTS["SYMBOL_EVENT_BLOCKED"] is False

    def test_field_count(self):
        assert len(DEFAULTS) == 7


class TestPassthrough:
    def test_active_macro_event(self):
        er = {
            "EVENT_WINDOW_STATE": "ACTIVE",
            "EVENT_RISK_LEVEL": "HIGH",
            "NEXT_EVENT_NAME": "FOMC Rate Decision",
            "NEXT_EVENT_TIME": "14:00",
            "MARKET_EVENT_BLOCKED": True,
            "SYMBOL_EVENT_BLOCKED": False,
            "EVENT_PROVIDER_STATUS": "ok",
        }
        result = build_event_risk_light(event_risk=er)
        assert result["EVENT_WINDOW_STATE"] == "ACTIVE"
        assert result["EVENT_RISK_LEVEL"] == "HIGH"
        assert result["MARKET_EVENT_BLOCKED"] is True
        assert result["SYMBOL_EVENT_BLOCKED"] is False

    def test_symbol_blocked_earnings(self):
        er = {
            "EVENT_WINDOW_STATE": "CLEAR",
            "EVENT_RISK_LEVEL": "ELEVATED",
            "MARKET_EVENT_BLOCKED": False,
            "SYMBOL_EVENT_BLOCKED": True,
        }
        result = build_event_risk_light(event_risk=er)
        assert result["MARKET_EVENT_BLOCKED"] is False
        assert result["SYMBOL_EVENT_BLOCKED"] is True
        assert result["EVENT_RISK_LEVEL"] == "ELEVATED"

    def test_deprecated_fields_not_passed_through(self):
        """Deprecated internal fields must NOT appear in lean output."""
        er = {
            "EVENT_WINDOW_STATE": "CLEAR",
            "NEXT_EVENT_CLASS": "MACRO",
            "NEXT_EVENT_IMPACT": "HIGH",
            "EVENT_RESTRICT_BEFORE_MIN": 30,
        }
        result = build_event_risk_light(event_risk=er)
        assert "NEXT_EVENT_CLASS" not in result
        assert "NEXT_EVENT_IMPACT" not in result
        assert "EVENT_RESTRICT_BEFORE_MIN" not in result


class TestOverrides:
    def test_override_window_state(self):
        result = build_event_risk_light(overrides={"EVENT_WINDOW_STATE": "COOLDOWN"})
        assert result["EVENT_WINDOW_STATE"] == "COOLDOWN"

    def test_override_ignores_unknown_keys(self):
        result = build_event_risk_light(overrides={"UNKNOWN_FIELD": True})
        assert "UNKNOWN_FIELD" not in result
