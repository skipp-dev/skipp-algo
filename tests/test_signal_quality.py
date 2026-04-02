"""Regression tests for smc_signal_quality builder.

Snapshot-based tests validate known input→output mappings so that
future calibration changes are caught explicitly (update snapshots
intentionally, not silently).
"""
from __future__ import annotations

import pytest
from scripts.smc_signal_quality import (
    DEFAULTS,
    PENALTY_EVENT,
    TIER_GOOD,
    TIER_LOW,
    TIER_OK,
    build_signal_quality,
    _score_tier,
    _freshness_label,
    _bias_alignment,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_enrichment(
    *,
    structure_state: str = "NEUTRAL",
    structure_fresh: bool = False,
    structure_age: int = 999,
    in_killzone: bool = False,
    session_bias: str = "NEUTRAL",
    session_score: int = 0,
    recent_bull_sweep: bool = False,
    recent_bear_sweep: bool = False,
    sweep_quality: int = 0,
    sweep_direction: str = "NONE",
    ob_side: str = "NONE",
    ob_fresh: bool = False,
    ob_distance: float = 99.0,
    ob_mitigation: str = "stale",
    fvg_side: str = "NONE",
    fvg_fresh: bool = False,
    fvg_fill: float = 0.0,
    fvg_invalidated: bool = False,
    event_blocked: bool = False,
    event_risk_level: str = "NONE",
    squeeze_on: bool = False,
    atr_regime: str = "NORMAL",
) -> dict:
    """Build a minimal enrichment dict for testing."""
    return {
        "structure_state": {
            "STRUCTURE_STATE": structure_state,
            "STRUCTURE_FRESH": structure_fresh,
            "STRUCTURE_EVENT_AGE_BARS": structure_age,
        },
        "session_context": {
            "IN_KILLZONE": in_killzone,
            "SESSION_DIRECTION_BIAS": session_bias,
            "SESSION_CONTEXT_SCORE": session_score,
        },
        "liquidity_sweeps": {
            "RECENT_BULL_SWEEP": recent_bull_sweep,
            "RECENT_BEAR_SWEEP": recent_bear_sweep,
            "SWEEP_QUALITY_SCORE": sweep_quality,
            "SWEEP_DIRECTION": sweep_direction,
        },
        "ob_context_light": {
            "PRIMARY_OB_SIDE": ob_side,
            "OB_FRESH": ob_fresh,
            "PRIMARY_OB_DISTANCE": ob_distance,
            "OB_MITIGATION_STATE": ob_mitigation,
        },
        "fvg_lifecycle_light": {
            "PRIMARY_FVG_SIDE": fvg_side,
            "FVG_FRESH": fvg_fresh,
            "FVG_FILL_PCT": fvg_fill,
            "FVG_INVALIDATED": fvg_invalidated,
        },
        "event_risk": {
            "MARKET_EVENT_BLOCKED": event_blocked,
            "EVENT_RISK_LEVEL": event_risk_level,
        },
        "compression_regime": {
            "SQUEEZE_ON": squeeze_on,
            "ATR_REGIME": atr_regime,
        },
    }


# ── Tier boundary tests ────────────────────────────────────────────


class TestTierBoundaries:
    def test_tier_low(self):
        assert _score_tier(0) == "low"
        assert _score_tier(25) == "low"

    def test_tier_ok(self):
        assert _score_tier(26) == "ok"
        assert _score_tier(50) == "ok"

    def test_tier_good(self):
        assert _score_tier(51) == "good"
        assert _score_tier(75) == "good"

    def test_tier_high(self):
        assert _score_tier(76) == "high"
        assert _score_tier(100) == "high"


# ── Freshness label tests ──────────────────────────────────────────


class TestFreshnessLabel:
    def test_fresh_when_structure_and_fvg_fresh(self):
        assert _freshness_label(True, 3, True, False) == "fresh"

    def test_fresh_when_structure_very_recent(self):
        assert _freshness_label(True, 3, False, False) == "fresh"

    def test_aging_when_one_component_fresh(self):
        assert _freshness_label(False, 999, True, False) == "aging"

    def test_aging_when_structure_moderate(self):
        assert _freshness_label(False, 12, False, False) == "aging"

    def test_stale_when_nothing_fresh(self):
        assert _freshness_label(False, 999, False, False) == "stale"


# ── Bias alignment tests ───────────────────────────────────────────


class TestBiasAlignment:
    def test_all_neutral(self):
        assert _bias_alignment("NEUTRAL", "NEUTRAL", "NONE", "NONE", "NONE") == "neutral"

    def test_strong_bull(self):
        result = _bias_alignment("BULLISH", "BULLISH", "BULL", "BULL", "BULL")
        assert result == "bull"

    def test_strong_bear(self):
        result = _bias_alignment("BEARISH", "BEARISH", "BEAR", "BEAR", "BEAR")
        assert result == "bear"

    def test_mixed_signals(self):
        result = _bias_alignment("BULLISH", "BEARISH", "BULL", "BEAR", "NONE")
        assert result == "mixed"

    def test_bull_dominates(self):
        # 2 (struct) + 1 (session) = 3 bull, 1 (sweep) bear => 3 >= 2*1 => bull
        result = _bias_alignment("BULLISH", "BULLISH", "BEAR", "NONE", "NONE")
        assert result == "bull"


# ── Snapshot regression tests ──────────────────────────────────────


class TestSnapshotScenarios:
    """Known-good input→output pairs. Update snapshots intentionally."""

    def test_empty_enrichment(self):
        """No enrichment → low tier with baseline compression."""
        result = build_signal_quality(enrichment={})
        assert result["SIGNAL_QUALITY_TIER"] == "low"
        assert result["SIGNAL_QUALITY_SCORE"] == 4  # NORMAL atr compression only
        assert result["SIGNAL_FRESHNESS"] == "stale"
        assert "structure_stale" in result["SIGNAL_WARNINGS"]

    def test_ideal_bullish_setup(self):
        """Best-case bull scenario → high tier."""
        enr = _make_enrichment(
            structure_state="BULLISH",
            structure_fresh=True,
            structure_age=2,
            in_killzone=True,
            session_bias="BULLISH",
            session_score=5,
            recent_bull_sweep=True,
            sweep_quality=8,
            sweep_direction="BULL",
            ob_side="BULL",
            ob_fresh=True,
            ob_distance=0.5,
            fvg_side="BULL",
            fvg_fresh=True,
            fvg_fill=0.1,
            fvg_invalidated=False,
            squeeze_on=True,
        )
        result = build_signal_quality(enrichment=enr)
        assert result["SIGNAL_QUALITY_TIER"] == "high"
        assert result["SIGNAL_QUALITY_SCORE"] >= 76
        assert result["SIGNAL_FRESHNESS"] == "fresh"
        assert result["SIGNAL_BIAS_ALIGNMENT"] == "bull"
        assert result["SIGNAL_WARNINGS"] == ""

    def test_stale_structure(self):
        """Old structure, no other support → low."""
        enr = _make_enrichment(structure_state="BULLISH", structure_age=50)
        result = build_signal_quality(enrichment=enr)
        assert result["SIGNAL_QUALITY_TIER"] == "low"
        assert "structure_stale" in result["SIGNAL_WARNINGS"]

    def test_event_blocked_penalty(self):
        """Event block applies -15 penalty."""
        enr = _make_enrichment(
            structure_state="BULLISH",
            structure_fresh=True,
            structure_age=3,
            event_blocked=True,
        )
        result = build_signal_quality(enrichment=enr)
        assert "event_blocked" in result["SIGNAL_WARNINGS"]
        # Structure(20) + compression(4 NORMAL) - event(-15) = 9
        assert result["SIGNAL_QUALITY_SCORE"] <= 25

    def test_moderate_mixed_setup(self):
        """Mixed signals → ok tier."""
        enr = _make_enrichment(
            structure_state="BULLISH",
            structure_fresh=True,
            structure_age=5,
            in_killzone=True,
            session_score=3,
            ob_side="BULL",
            ob_fresh=False,
            ob_distance=2.5,
        )
        result = build_signal_quality(enrichment=enr)
        assert result["SIGNAL_QUALITY_TIER"] in ("ok", "good")
        assert result["SIGNAL_QUALITY_SCORE"] >= 26

    def test_squeeze_compression_boost(self):
        """Squeeze active → full compression component."""
        base = _make_enrichment(
            structure_state="NEUTRAL",
            structure_age=999,
            atr_regime="NORMAL",
        )
        result_normal = build_signal_quality(enrichment=base)
        squeeze = _make_enrichment(
            structure_state="NEUTRAL",
            structure_age=999,
            squeeze_on=True,
        )
        result_squeeze = build_signal_quality(enrichment=squeeze)
        # Squeeze should contribute more compression score
        assert result_squeeze["SIGNAL_QUALITY_SCORE"] > result_normal["SIGNAL_QUALITY_SCORE"]

    def test_atr_exhaustion_warning(self):
        """ATR exhaustion → warning, no compression contribution."""
        enr = _make_enrichment(atr_regime="EXHAUSTION")
        result = build_signal_quality(enrichment=enr)
        assert "atr_exhaustion" in result["SIGNAL_WARNINGS"]

    def test_fvg_invalidated_warning(self):
        """Invalidated FVG → warning."""
        enr = _make_enrichment(
            fvg_side="BULL",
            fvg_fresh=True,
            fvg_invalidated=True,
        )
        result = build_signal_quality(enrichment=enr)
        assert "fvg_invalidated" in result["SIGNAL_WARNINGS"]

    def test_outside_killzone_warning(self):
        """Outside killzone + low session score → warning."""
        enr = _make_enrichment(in_killzone=False, session_score=1)
        result = build_signal_quality(enrichment=enr)
        assert "outside_killzone" in result["SIGNAL_WARNINGS"]

    def test_overrides_applied_last(self):
        """Overrides override computed values."""
        enr = _make_enrichment(structure_state="BULLISH", structure_fresh=True)
        result = build_signal_quality(
            enrichment=enr,
            overrides={"SIGNAL_QUALITY_TIER": "forced"},
        )
        assert result["SIGNAL_QUALITY_TIER"] == "forced"

    def test_score_clamped_to_0_100(self):
        """Score never goes below 0 even with max penalty."""
        enr = _make_enrichment(event_blocked=True)
        result = build_signal_quality(enrichment=enr)
        assert result["SIGNAL_QUALITY_SCORE"] >= 0
        assert result["SIGNAL_QUALITY_SCORE"] <= 100

    def test_warnings_limited_to_three(self):
        """Only first 3 warnings are emitted."""
        enr = _make_enrichment(
            structure_age=999,
            in_killzone=False,
            session_score=0,
            fvg_side="BULL",
            fvg_invalidated=True,
            event_blocked=True,
            atr_regime="EXHAUSTION",
        )
        result = build_signal_quality(enrichment=enr)
        warnings = result["SIGNAL_WARNINGS"].split("|")
        assert len(warnings) <= 3


class TestComponentContributions:
    """Verify each component contributes the expected range."""

    def test_structure_fresh_max(self):
        enr = _make_enrichment(structure_fresh=True, structure_age=1)
        result = build_signal_quality(enrichment=enr)
        # Structure(20) + compression(NORMAL=4) = 24
        assert result["SIGNAL_QUALITY_SCORE"] >= 20

    def test_session_killzone_high_score(self):
        enr = _make_enrichment(in_killzone=True, session_score=5)
        result = build_signal_quality(enrichment=enr)
        # Session(20) + compression(4) = 24
        assert result["SIGNAL_QUALITY_SCORE"] >= 20

    def test_ob_fresh_close_max(self):
        enr = _make_enrichment(ob_side="BULL", ob_fresh=True, ob_distance=0.5)
        result = build_signal_quality(enrichment=enr)
        # OB(15) + compression(4) = 19
        assert result["SIGNAL_QUALITY_SCORE"] >= 15

    def test_fvg_fresh_active_max(self):
        enr = _make_enrichment(fvg_side="BULL", fvg_fresh=True, fvg_invalidated=False)
        result = build_signal_quality(enrichment=enr)
        # FVG(15) + compression(4) = 19
        assert result["SIGNAL_QUALITY_SCORE"] >= 15

    def test_caution_pre_event_penalty(self):
        """Elevated event risk applies partial penalty without blocking."""
        enr = _make_enrichment(
            structure_state="BULLISH",
            structure_fresh=True,
            structure_age=3,
            event_risk_level="ELEVATED",
        )
        result = build_signal_quality(enrichment=enr)
        assert "event_risk_high" in result["SIGNAL_WARNINGS"]
        # Structure(20) + compression(4) - event_elevated(-9) = 15
        assert result["SIGNAL_QUALITY_SCORE"] == 15

    def test_fresh_ob_fvg_confluence(self):
        """Fresh OB + fresh FVG confluence → strong score."""
        enr = _make_enrichment(
            structure_state="BULLISH",
            structure_fresh=True,
            structure_age=2,
            in_killzone=True,
            session_score=4,
            ob_side="BULL",
            ob_fresh=True,
            ob_distance=1.0,
            fvg_side="BULL",
            fvg_fresh=True,
            fvg_invalidated=False,
        )
        result = build_signal_quality(enrichment=enr)
        # Structure(20) + Session(20) + OB(15) + FVG(15) + compression(4) = 74
        assert result["SIGNAL_QUALITY_TIER"] in ("good", "high")
        assert result["SIGNAL_QUALITY_SCORE"] >= 70
        assert result["SIGNAL_FRESHNESS"] == "fresh"

    def test_compression_regime_scoring(self):
        """COMPRESSION ATR regime → mid compression score."""
        enr = _make_enrichment(atr_regime="COMPRESSION")
        result = build_signal_quality(enrichment=enr)
        # compression contributes int(15*0.5) = 7
        assert result["SIGNAL_QUALITY_SCORE"] >= 7


class TestOptionalVolatilityState:
    """v5.5b: Signal Quality must work without SESSION_VOLATILITY_STATE."""

    def test_no_session_light_block(self):
        """Signal quality works when session_context_light is absent."""
        enr = _make_enrichment(
            structure_state="BULLISH", structure_fresh=True, structure_age=3,
            in_killzone=True, session_score=4,
        )
        # Remove session_context_light entirely
        enr.pop("session_context_light", None)
        result = build_signal_quality(enrichment=enr)
        assert result["SIGNAL_QUALITY_TIER"] in ("ok", "good", "high")
        assert result["SIGNAL_QUALITY_SCORE"] > 0

    def test_session_light_without_volatility(self):
        """Signal quality works when session_context_light has no volatility."""
        enr = _make_enrichment(
            structure_state="BULLISH", structure_fresh=True, structure_age=3,
        )
        # Provide session light without volatility
        enr["session_context_light"] = {
            "IN_KILLZONE": True,
            "SESSION_DIRECTION_BIAS": "BULLISH",
            "SESSION_CONTEXT_SCORE": 5,
        }
        result = build_signal_quality(enrichment=enr)
        assert result["SIGNAL_QUALITY_SCORE"] > 0
        assert result["SIGNAL_QUALITY_TIER"] != ""


class TestLeanFirstPriority:
    """v5.5b: lean families are primary; broad blocks are fallback-only."""

    def test_structure_light_is_primary(self):
        """Structure State Light is preferred over broad structure_state."""
        enr = {
            "structure_state_light": {
                "STRUCTURE_FRESH": True,
                "STRUCTURE_EVENT_AGE_BARS": 2,
                "STRUCTURE_LAST_EVENT": "BOS_BULL",
            },
            "structure_state": {
                "STRUCTURE_FRESH": False,
                "STRUCTURE_EVENT_AGE_BARS": 999,
                "STRUCTURE_STATE": "BEARISH",
            },
        }
        result = build_signal_quality(enrichment=enr)
        # Should use lean (fresh, age=2) not broad (stale, age=999)
        assert result["SIGNAL_FRESHNESS"] != "stale"
        assert result["SIGNAL_BIAS_ALIGNMENT"] == "bull"

    def test_ob_light_is_primary(self):
        """OB Context Light is preferred over broad order_blocks."""
        enr = {
            "ob_context_light": {
                "PRIMARY_OB_SIDE": "BULL",
                "OB_FRESH": True,
                "PRIMARY_OB_DISTANCE": 0.5,
            },
            "order_blocks": {
                "OB_NEAREST_DISTANCE_PCT": 99.0,
                "BULL_OB_FRESHNESS": 100,
            },
        }
        result = build_signal_quality(enrichment=enr)
        assert result["SIGNAL_QUALITY_SCORE"] >= 15  # OB contribution

    def test_fvg_light_is_primary(self):
        """FVG Lifecycle Light is preferred over broad imbalance_lifecycle."""
        enr = {
            "fvg_lifecycle_light": {
                "PRIMARY_FVG_SIDE": "BULL",
                "FVG_FRESH": True,
                "FVG_FILL_PCT": 0.1,
                "FVG_INVALIDATED": False,
            },
            "imbalance_lifecycle": {
                "BULL_FVG_ACTIVE": False,
            },
        }
        result = build_signal_quality(enrichment=enr)
        assert result["SIGNAL_QUALITY_SCORE"] >= 15  # FVG contribution

    def test_event_risk_light_is_primary(self):
        """Event Risk Light is preferred over broad event_risk."""
        enr = {
            "event_risk_light": {
                "MARKET_EVENT_BLOCKED": True,
            },
            "event_risk": {
                "MARKET_EVENT_BLOCKED": False,
            },
        }
        result = build_signal_quality(enrichment=enr)
        assert "event_blocked" in result["SIGNAL_WARNINGS"]

    def test_event_risk_light_false_does_not_fallback_to_broad_true(self):
        """Lean event risk must win even when broad fallback disagrees."""
        enr = {
            "event_risk_light": {
                "MARKET_EVENT_BLOCKED": False,
                "SYMBOL_EVENT_BLOCKED": False,
                "EVENT_RISK_LEVEL": "NONE",
            },
            "event_risk": {
                "MARKET_EVENT_BLOCKED": True,
                "EVENT_RISK_LEVEL": "HIGH",
            },
        }
        result = build_signal_quality(enrichment=enr)
        assert "event_blocked" not in result["SIGNAL_WARNINGS"]
        assert "event_risk_high" not in result["SIGNAL_WARNINGS"]
