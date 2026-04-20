"""Unit tests for the Hero State Contract (scripts/smc_hero_state.py)."""
from __future__ import annotations

import pytest

from scripts.smc_hero_state import DEFAULTS, build_hero_state, _derive_trust, _derive_bias, _derive_action


class TestDeriveTrust:
    def test_healthy(self):
        assert _derive_trust(signal_freshness="fresh", stale_providers="", ensemble_tier="good") == "healthy"

    def test_warmup_on_aging(self):
        assert _derive_trust(signal_freshness="aging", stale_providers="", ensemble_tier="good") == "warmup"

    def test_degraded_on_many_stale(self):
        assert _derive_trust(signal_freshness="fresh", stale_providers="regime,news", ensemble_tier="good") == "degraded"

    def test_degraded_on_low_ensemble(self):
        assert _derive_trust(signal_freshness="fresh", stale_providers="", ensemble_tier="low") == "degraded"

    def test_stale_on_stale_freshness(self):
        assert _derive_trust(signal_freshness="stale", stale_providers="", ensemble_tier="good") == "stale"

    def test_unavailable_on_stale_plus_providers(self):
        assert _derive_trust(signal_freshness="stale", stale_providers="regime,news", ensemble_tier="low") == "unavailable"


class TestDeriveBias:
    def test_bullish_long(self):
        assert _derive_bias(regime="BULLISH", trade_state="ALLOWED") == "LONG"

    def test_bearish_short(self):
        assert _derive_bias(regime="BEARISH", trade_state="ALLOWED") == "SHORT"

    def test_risk_off_short(self):
        assert _derive_bias(regime="RISK_OFF", trade_state="ALLOWED") == "SHORT"

    def test_neutral_flat(self):
        assert _derive_bias(regime="NEUTRAL", trade_state="ALLOWED") == "FLAT"

    def test_blocked_always_flat(self):
        assert _derive_bias(regime="BULLISH", trade_state="BLOCKED") == "FLAT"

    def test_avoid_always_flat(self):
        assert _derive_bias(regime="BEARISH", trade_state="AVOID") == "FLAT"


class TestDeriveAction:
    def test_active_when_healthy(self):
        assert _derive_action(trade_state="ALLOWED", trust="healthy") == "ACTIVE"

    def test_watch_when_stale(self):
        assert _derive_action(trade_state="ALLOWED", trust="stale") == "WATCH"

    def test_watch_when_unavailable(self):
        assert _derive_action(trade_state="ALLOWED", trust="unavailable") == "WATCH"

    def test_blocked_override(self):
        assert _derive_action(trade_state="BLOCKED", trust="healthy") == "BLOCKED"

    def test_avoid_override(self):
        assert _derive_action(trade_state="AVOID", trust="healthy") == "AVOID"

    def test_watch_trade_state(self):
        assert _derive_action(trade_state="WATCH", trust="healthy") == "WATCH"


class TestBuildHeroState:
    def test_defaults_on_empty_enrichment(self):
        result = build_hero_state({})
        # Empty enrichment means stale signal freshness and low ensemble → stale trust
        assert result["HERO_MARKET_MODE"] == "NEUTRAL"
        assert result["HERO_BIAS"] == "FLAT"
        assert result["HERO_TRUST"] == "stale"
        assert result["HERO_SETUP_QUALITY"] == "low"
        assert result["HERO_WHY_NOW"] == ""
        assert result["HERO_RISK"] == "DATA_STALE"
        assert result["HERO_ACTION"] == "WATCH"

    def test_full_enrichment(self):
        enrichment = {
            "regime": {"regime": "BULLISH"},
            "layering": {"trade_state": "ALLOWED"},
            "signal_quality": {"SIGNAL_FRESHNESS": "fresh", "SIGNAL_QUALITY_TIER": "good"},
            "providers": {"stale_providers": ""},
            "ensemble_quality": {"tier": "good"},
            "calendar": {"high_impact_macro_today": True, "macro_event_name": "FOMC"},
            "zone_priority": {"ZONE_PRIORITY_CATALYST": "OB_RECLAIM", "ZONE_PRIORITY_REASON": "breakout"},
            "event_risk": {"EVENT_RISK_LEVEL": "NONE"},
            "volatility_regime": {"label": "NORMAL"},
        }
        result = build_hero_state(enrichment)
        assert result["HERO_MARKET_MODE"] == "BULLISH"
        assert result["HERO_BIAS"] == "LONG"
        assert result["HERO_TRUST"] == "healthy"
        assert result["HERO_SETUP_QUALITY"] == "good"
        assert "FOMC" in result["HERO_WHY_NOW"]
        assert result["HERO_ACTION"] == "ACTIVE"
        assert result["HERO_RISK"] == ""

    def test_degraded_data_changes_action(self):
        enrichment = {
            "regime": {"regime": "BULLISH"},
            "layering": {"trade_state": "ALLOWED"},
            "signal_quality": {"SIGNAL_FRESHNESS": "stale"},
            "providers": {"stale_providers": "regime,news,calendar"},
            "ensemble_quality": {"tier": "low"},
        }
        result = build_hero_state(enrichment)
        assert result["HERO_TRUST"] == "unavailable"
        assert result["HERO_ACTION"] == "WATCH"
        assert result["HERO_RISK"] == "DATA_STALE"

    def test_event_risk_surfaces(self):
        enrichment = {
            "regime": {"regime": "NEUTRAL"},
            "layering": {"trade_state": "ALLOWED"},
            "signal_quality": {"SIGNAL_FRESHNESS": "fresh"},
            "providers": {"stale_providers": ""},
            "ensemble_quality": {"tier": "good"},
            "event_risk": {"EVENT_RISK_LEVEL": "HIGH"},
            "volatility_regime": {"label": "NORMAL"},
        }
        result = build_hero_state(enrichment)
        assert result["HERO_RISK"] == "EVENT_RISK"

    def test_volatility_risk_surfaces(self):
        enrichment = {
            "regime": {"regime": "NEUTRAL"},
            "layering": {"trade_state": "ALLOWED"},
            "signal_quality": {"SIGNAL_FRESHNESS": "fresh"},
            "providers": {"stale_providers": ""},
            "ensemble_quality": {"tier": "good"},
            "event_risk": {"EVENT_RISK_LEVEL": "NONE"},
            "volatility_regime": {"label": "EXTREME"},
        }
        result = build_hero_state(enrichment)
        assert result["HERO_RISK"] == "VOLATILITY"

    def test_all_seven_keys_present(self):
        result = build_hero_state({})
        assert set(result.keys()) == set(DEFAULTS.keys())
        assert len(result) == 7
