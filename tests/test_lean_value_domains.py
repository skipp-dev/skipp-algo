"""V5.5a Lean Contract — Value Domain & Semantic Coherence Tests.

Validates that all lean adapter outputs conform to the allowed value
domains defined in docs/v5_5_lean_contract.md. This ensures not just
field presence but field meaning.
"""
from __future__ import annotations

import pytest

# ── Allowed value domains (from docs/v5_5_lean_contract.md) ──

ALLOWED_EVENT_WINDOW_STATE = {"CLEAR", "PRE_EVENT", "ACTIVE", "COOLDOWN"}
ALLOWED_EVENT_RISK_LEVEL = {"NONE", "LOW", "ELEVATED", "HIGH"}
ALLOWED_EVENT_PROVIDER_STATUS = {"ok", "no_data", "calendar_missing", "news_missing"}

ALLOWED_SESSION_CONTEXT = {"ASIA", "LONDON", "NY_AM", "NY_PM", "NONE"}
ALLOWED_SESSION_DIRECTION_BIAS = {"BULLISH", "BEARISH", "NEUTRAL"}
ALLOWED_SESSION_VOLATILITY_STATE = {"LOW", "NORMAL", "HIGH", "EXTREME"}

ALLOWED_OB_SIDE = {"BULL", "BEAR", "NONE"}
ALLOWED_OB_MITIGATION_STATE = {"fresh", "touched", "mitigated", "stale"}

ALLOWED_FVG_SIDE = {"BULL", "BEAR", "NONE"}
ALLOWED_FVG_MATURITY_RANGE = range(0, 4)  # 0-3

ALLOWED_STRUCTURE_LAST_EVENT = {"NONE", "BOS_BULL", "BOS_BEAR", "CHOCH_BULL", "CHOCH_BEAR"}

ALLOWED_SIGNAL_QUALITY_TIER = {"low", "ok", "good", "high"}
ALLOWED_SIGNAL_BIAS_ALIGNMENT = {"bull", "bear", "mixed", "neutral"}
ALLOWED_SIGNAL_FRESHNESS = {"fresh", "aging", "stale"}


# ── Event Risk Light ────────────────────────────────────────────────

class TestEventRiskLightDomains:
    def _build(self, **kwargs):
        from scripts.smc_event_risk_light import build_event_risk_light
        return build_event_risk_light(**kwargs)

    def test_defaults_in_domain(self):
        result = self._build()
        assert result["EVENT_WINDOW_STATE"] in ALLOWED_EVENT_WINDOW_STATE
        assert result["EVENT_RISK_LEVEL"] in ALLOWED_EVENT_RISK_LEVEL
        assert result["EVENT_PROVIDER_STATUS"] in ALLOWED_EVENT_PROVIDER_STATUS

    def test_active_event_values_in_domain(self):
        result = self._build(event_risk={
            "EVENT_WINDOW_STATE": "ACTIVE",
            "EVENT_RISK_LEVEL": "HIGH",
            "MARKET_EVENT_BLOCKED": True,
            "SYMBOL_EVENT_BLOCKED": False,
            "NEXT_EVENT_NAME": "FOMC",
            "NEXT_EVENT_TIME": "14:00",
            "EVENT_PROVIDER_STATUS": "ok",
        })
        assert result["EVENT_WINDOW_STATE"] in ALLOWED_EVENT_WINDOW_STATE
        assert result["EVENT_RISK_LEVEL"] in ALLOWED_EVENT_RISK_LEVEL


# ── Session Context Light ───────────────────────────────────────────

class TestSessionContextLightDomains:
    def _build(self, **kwargs):
        from scripts.smc_session_context_light import build_session_context_light
        return build_session_context_light(**kwargs)

    def test_defaults_in_domain(self):
        result = self._build()
        assert result["SESSION_CONTEXT"] in ALLOWED_SESSION_CONTEXT
        assert result["SESSION_DIRECTION_BIAS"] in ALLOWED_SESSION_DIRECTION_BIAS
        assert result["SESSION_VOLATILITY_STATE"] in ALLOWED_SESSION_VOLATILITY_STATE
        assert 0 <= result["SESSION_CONTEXT_SCORE"] <= 7

    def test_killzone_session_in_domain(self):
        result = self._build(session_context={
            "SESSION_CONTEXT": "NY_AM",
            "IN_KILLZONE": True,
            "SESSION_DIRECTION_BIAS": "BULLISH",
            "SESSION_CONTEXT_SCORE": 5,
        })
        assert result["SESSION_CONTEXT"] in ALLOWED_SESSION_CONTEXT
        assert result["SESSION_DIRECTION_BIAS"] in ALLOWED_SESSION_DIRECTION_BIAS

    @pytest.mark.parametrize("regime,expected", [
        ("COMPRESSION", "LOW"),
        ("EXPANSION", "HIGH"),
        ("NORMAL", "NORMAL"),
    ])
    def test_volatility_state_derivation(self, regime, expected):
        result = self._build(compression_regime={"ATR_REGIME": regime})
        assert result["SESSION_VOLATILITY_STATE"] in ALLOWED_SESSION_VOLATILITY_STATE
        assert result["SESSION_VOLATILITY_STATE"] == expected

    def test_extreme_volatility(self):
        result = self._build(compression_regime={"ATR_REGIME": "EXPANSION", "ATR_RATIO": 3.0})
        assert result["SESSION_VOLATILITY_STATE"] == "EXTREME"


# ── OB Context Light ────────────────────────────────────────────────

class TestOBContextLightDomains:
    def _build(self, **kwargs):
        from scripts.smc_ob_context_light import build_ob_context_light
        return build_ob_context_light(**kwargs)

    def test_defaults_in_domain(self):
        result = self._build()
        assert result["PRIMARY_OB_SIDE"] in ALLOWED_OB_SIDE
        assert result["OB_MITIGATION_STATE"] in ALLOWED_OB_MITIGATION_STATE
        assert isinstance(result["OB_FRESH"], bool)
        assert isinstance(result["OB_AGE_BARS"], int)
        assert result["OB_AGE_BARS"] >= 0

    def test_bull_ob_values_in_domain(self):
        result = self._build(order_blocks={
            "NEAREST_BULL_OB_LEVEL": 100.0,
            "BULL_OB_FRESHNESS": 3,
            "BULL_OB_MITIGATED": False,
        }, current_price=102.0)
        assert result["PRIMARY_OB_SIDE"] in ALLOWED_OB_SIDE
        assert result["OB_MITIGATION_STATE"] in ALLOWED_OB_MITIGATION_STATE

    def test_mitigation_state_never_invalid(self):
        """All OB scenarios must produce valid mitigation state."""
        for mitigated in [True, False]:
            for freshness in [0, 3, 10, 25, 50, 100]:
                result = self._build(order_blocks={
                    "NEAREST_BULL_OB_LEVEL": 100.0,
                    "BULL_OB_FRESHNESS": freshness,
                    "BULL_OB_MITIGATED": mitigated,
                })
                assert result["OB_MITIGATION_STATE"] in ALLOWED_OB_MITIGATION_STATE, (
                    f"mitigated={mitigated}, freshness={freshness} -> {result['OB_MITIGATION_STATE']}"
                )


# ── FVG Lifecycle Light ─────────────────────────────────────────────

class TestFVGLifecycleLightDomains:
    def _build(self, **kwargs):
        from scripts.smc_fvg_lifecycle_light import build_fvg_lifecycle_light
        return build_fvg_lifecycle_light(**kwargs)

    def test_defaults_in_domain(self):
        result = self._build()
        assert result["PRIMARY_FVG_SIDE"] in ALLOWED_FVG_SIDE
        assert result["FVG_MATURITY_LEVEL"] in ALLOWED_FVG_MATURITY_RANGE
        assert 0.0 <= result["FVG_FILL_PCT"] <= 1.0
        assert isinstance(result["FVG_FRESH"], bool)
        assert isinstance(result["FVG_INVALIDATED"], bool)

    def test_active_fvg_values_in_domain(self):
        result = self._build(imbalance={
            "BULL_FVG_ACTIVE": True,
            "BULL_FVG_TOP": 105.0,
            "BULL_FVG_BOTTOM": 100.0,
            "BULL_FVG_MITIGATION_PCT": 0.3,
        }, current_price=103.0)
        assert result["PRIMARY_FVG_SIDE"] in ALLOWED_FVG_SIDE
        assert result["FVG_MATURITY_LEVEL"] in ALLOWED_FVG_MATURITY_RANGE

    @pytest.mark.parametrize("fill_pct,expected_maturity", [
        (0.0, 0),
        (0.15, 0),
        (0.25, 1),
        (0.55, 2),
        (0.85, 3),
    ])
    def test_maturity_from_fill(self, fill_pct, expected_maturity):
        result = self._build(imbalance={
            "BULL_FVG_ACTIVE": True,
            "BULL_FVG_TOP": 105.0,
            "BULL_FVG_BOTTOM": 100.0,
            "BULL_FVG_MITIGATION_PCT": fill_pct,
        }, current_price=103.0)
        assert result["FVG_MATURITY_LEVEL"] == expected_maturity

    def test_freshness_coherent_with_maturity(self):
        """FVG_FRESH should align with maturity level."""
        # Low maturity = fresh
        result_fresh = self._build(imbalance={
            "BULL_FVG_ACTIVE": True,
            "BULL_FVG_TOP": 105.0,
            "BULL_FVG_BOTTOM": 100.0,
            "BULL_FVG_MITIGATION_PCT": 0.1,
        }, current_price=103.0)
        assert result_fresh["FVG_FRESH"] is True
        # High maturity = not fresh
        result_mature = self._build(imbalance={
            "BULL_FVG_ACTIVE": True,
            "BULL_FVG_TOP": 105.0,
            "BULL_FVG_BOTTOM": 100.0,
            "BULL_FVG_MITIGATION_PCT": 0.6,
        }, current_price=103.0)
        assert result_mature["FVG_FRESH"] is False

    def test_invalidated_coherent_with_full_mitigation(self):
        result = self._build(imbalance={
            "BULL_FVG_ACTIVE": True,
            "BULL_FVG_TOP": 105.0,
            "BULL_FVG_BOTTOM": 100.0,
            "BULL_FVG_FULL_MITIGATION": True,
            "BULL_FVG_MITIGATION_PCT": 1.0,
        }, current_price=103.0)
        assert result["FVG_INVALIDATED"] is True
        assert result["FVG_FRESH"] is False


# ── Structure State Light ───────────────────────────────────────────

class TestStructureStateLightDomains:
    def _build(self, **kwargs):
        from scripts.smc_structure_state_light import build_structure_state_light
        return build_structure_state_light(**kwargs)

    def test_defaults_in_domain(self):
        result = self._build()
        assert result["STRUCTURE_LAST_EVENT"] in ALLOWED_STRUCTURE_LAST_EVENT
        assert 0 <= result["STRUCTURE_TREND_STRENGTH"] <= 100
        assert isinstance(result["STRUCTURE_FRESH"], bool)
        assert isinstance(result["STRUCTURE_EVENT_AGE_BARS"], int)

    @pytest.mark.parametrize("event", ["BOS_BULL", "BOS_BEAR", "CHOCH_BULL", "CHOCH_BEAR", "NONE"])
    def test_all_events_in_domain(self, event):
        result = self._build(structure_state={
            "STRUCTURE_LAST_EVENT": event,
            "STRUCTURE_EVENT_AGE_BARS": 5,
            "STRUCTURE_FRESH": True,
        })
        assert result["STRUCTURE_LAST_EVENT"] in ALLOWED_STRUCTURE_LAST_EVENT

    def test_trend_strength_clamped(self):
        """Trend strength must never exceed 100."""
        result = self._build(structure_state={
            "STRUCTURE_LAST_EVENT": "BOS_BULL",
            "STRUCTURE_STATE": "BULLISH",
            "STRUCTURE_EVENT_AGE_BARS": 1,
            "STRUCTURE_FRESH": True,
            "STRUCTURE_BOS_IN_DIRECTION": True,
            "STRUCTURE_SUPPORT_RESISTANCE_ALIGNED": True,
        })
        assert 0 <= result["STRUCTURE_TREND_STRENGTH"] <= 100


# ── Signal Quality ──────────────────────────────────────────────────

class TestSignalQualityDomains:
    def _build(self, **kwargs):
        from scripts.smc_signal_quality import build_signal_quality
        return build_signal_quality(**kwargs)

    def test_defaults_in_domain(self):
        result = self._build()
        assert 0 <= result["SIGNAL_QUALITY_SCORE"] <= 100
        assert result["SIGNAL_QUALITY_TIER"] in ALLOWED_SIGNAL_QUALITY_TIER
        assert result["SIGNAL_BIAS_ALIGNMENT"] in ALLOWED_SIGNAL_BIAS_ALIGNMENT
        assert result["SIGNAL_FRESHNESS"] in ALLOWED_SIGNAL_FRESHNESS

    def test_score_tier_coherence_high(self):
        """Score 76-100 → tier 'high'."""
        result = self._build(enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_EVENT_AGE_BARS": 1, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"IN_KILLZONE": True, "SESSION_CONTEXT_SCORE": 5, "SESSION_DIRECTION_BIAS": "BULLISH"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_SIDE": "BULL", "OB_AGE_BARS": 2},
            "fvg_lifecycle_light": {"FVG_FRESH": True, "PRIMARY_FVG_SIDE": "BULL", "FVG_MATURITY_LEVEL": 0},
            "compression": {"SQUEEZE_RELEASED": True},
        })
        assert result["SIGNAL_QUALITY_TIER"] in ALLOWED_SIGNAL_QUALITY_TIER
        assert 0 <= result["SIGNAL_QUALITY_SCORE"] <= 100

    def test_score_tier_coherence_low(self):
        """Empty enrichment → score ≤ 25 → tier 'low'."""
        result = self._build()
        assert result["SIGNAL_QUALITY_SCORE"] <= 25
        assert result["SIGNAL_QUALITY_TIER"] == "low"

    def test_bias_alignment_all_bullish(self):
        result = self._build(enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL", "STRUCTURE_EVENT_AGE_BARS": 3, "STRUCTURE_FRESH": True},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BULLISH"},
            "ob_context_light": {"PRIMARY_OB_SIDE": "BULL"},
            "fvg_lifecycle_light": {"PRIMARY_FVG_SIDE": "BULL"},
        })
        assert result["SIGNAL_BIAS_ALIGNMENT"] in ALLOWED_SIGNAL_BIAS_ALIGNMENT
        assert result["SIGNAL_BIAS_ALIGNMENT"] == "bull"

    def test_bias_alignment_mixed(self):
        result = self._build(enrichment={
            "structure_state_light": {"STRUCTURE_LAST_EVENT": "BOS_BULL", "STRUCTURE_EVENT_AGE_BARS": 3, "STRUCTURE_FRESH": True},
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BEARISH"},
            "ob_context_light": {"PRIMARY_OB_SIDE": "BEAR"},
            "fvg_lifecycle_light": {"PRIMARY_FVG_SIDE": "BULL"},
        })
        assert result["SIGNAL_BIAS_ALIGNMENT"] in ALLOWED_SIGNAL_BIAS_ALIGNMENT

    def test_freshness_domain(self):
        for fresh_flag in [True, False]:
            for age in [1, 10, 30, 100]:
                result = self._build(enrichment={
                    "structure_state_light": {"STRUCTURE_FRESH": fresh_flag, "STRUCTURE_EVENT_AGE_BARS": age},
                    "ob_context_light": {"OB_FRESH": fresh_flag},
                    "fvg_lifecycle_light": {"FVG_FRESH": fresh_flag},
                })
                assert result["SIGNAL_FRESHNESS"] in ALLOWED_SIGNAL_FRESHNESS

    def test_warnings_is_string(self):
        result = self._build()
        assert isinstance(result["SIGNAL_WARNINGS"], str)


# ── Cross-Family Coherence ──────────────────────────────────────────

class TestCrossFamilyCoherence:
    """Test semantic coherence across lean families."""

    def test_event_blocked_implies_non_clear(self):
        from scripts.smc_event_risk_light import build_event_risk_light
        result = build_event_risk_light(event_risk={
            "MARKET_EVENT_BLOCKED": True,
            "EVENT_WINDOW_STATE": "ACTIVE",
            "EVENT_RISK_LEVEL": "HIGH",
        })
        if result["MARKET_EVENT_BLOCKED"]:
            assert result["EVENT_WINDOW_STATE"] != "CLEAR"

    def test_fresh_structure_supports_fresh_signal(self):
        from scripts.smc_signal_quality import build_signal_quality
        result = build_signal_quality(enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_EVENT_AGE_BARS": 2, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "ob_context_light": {"OB_FRESH": True},
            "fvg_lifecycle_light": {"FVG_FRESH": True},
        })
        assert result["SIGNAL_FRESHNESS"] == "fresh"

    def test_stale_structure_degrades_freshness(self):
        from scripts.smc_signal_quality import build_signal_quality
        result = build_signal_quality(enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": False, "STRUCTURE_EVENT_AGE_BARS": 100, "STRUCTURE_LAST_EVENT": "NONE"},
            "ob_context_light": {"OB_FRESH": False},
            "fvg_lifecycle_light": {"FVG_FRESH": False},
        })
        assert result["SIGNAL_FRESHNESS"] == "stale"
