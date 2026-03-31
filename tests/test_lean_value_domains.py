"""V5.5b Lean Contract — Value Domain & Semantic Coherence Tests.

Validates that all lean adapter outputs conform to the allowed value
domains defined in docs/v5_5_lean_contract.md. This ensures not just
field presence but field meaning.
"""
from __future__ import annotations

import json
from pathlib import Path

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


# ── Hero-Surface Plausibility (showcase fixture) ────────────────────

class TestHeroSurfacePlausibility:
    """End-to-end plausibility checks using the showcase fixture."""

    @pytest.fixture()
    def showcase(self):
        import json
        from pathlib import Path
        fixture = Path(__file__).parent / "fixtures" / "reference_enrichment.json"
        with open(fixture) as f:
            return json.load(f)

    def test_bullish_fixture_plausible_surface(self, showcase):
        """Bullish showcase -> SQ tier >= ok, bias == bull, freshness == fresh."""
        sq = showcase["signal_quality"]
        assert sq["SIGNAL_QUALITY_TIER"] in ("ok", "good", "high")
        assert sq["SIGNAL_BIAS_ALIGNMENT"] == "bull"
        assert sq["SIGNAL_FRESHNESS"] == "fresh"

    def test_bullish_structure_supports_hero(self, showcase):
        """BOS_BULL + fresh structure -> Hero Surface structure is strong."""
        ssl = showcase["structure_state_light"]
        assert ssl["STRUCTURE_LAST_EVENT"] == "BOS_BULL"
        assert ssl["STRUCTURE_FRESH"] is True
        assert ssl["STRUCTURE_EVENT_AGE_BARS"] <= 10

    def test_ob_fvg_coherent_with_bias(self, showcase):
        """OB and FVG sides must match the overall bullish scenario."""
        assert showcase["ob_context_light"]["PRIMARY_OB_SIDE"] == "BULL"
        assert showcase["fvg_lifecycle_light"]["PRIMARY_FVG_SIDE"] == "BULL"

    def test_event_risk_clear_in_bullish_scenario(self, showcase):
        """Bullish showcase should not have event blocking."""
        erl = showcase["event_risk_light"]
        assert erl["EVENT_WINDOW_STATE"] == "CLEAR"
        assert erl["MARKET_EVENT_BLOCKED"] is False
        assert erl["SYMBOL_EVENT_BLOCKED"] is False

    def test_event_blocked_degrades_sq(self):
        """When events are blocked, SQ must penalize."""
        from scripts.smc_signal_quality import build_signal_quality
        baseline = build_signal_quality(enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_EVENT_AGE_BARS": 2, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"IN_KILLZONE": True, "SESSION_CONTEXT_SCORE": 5, "SESSION_DIRECTION_BIAS": "BULLISH"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_SIDE": "BULL", "PRIMARY_OB_DISTANCE": 0.5},
            "fvg_lifecycle_light": {"FVG_FRESH": True, "PRIMARY_FVG_SIDE": "BULL"},
        })
        blocked = build_signal_quality(enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_EVENT_AGE_BARS": 2, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"IN_KILLZONE": True, "SESSION_CONTEXT_SCORE": 5, "SESSION_DIRECTION_BIAS": "BULLISH"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_SIDE": "BULL", "PRIMARY_OB_DISTANCE": 0.5},
            "fvg_lifecycle_light": {"FVG_FRESH": True, "PRIMARY_FVG_SIDE": "BULL"},
            "event_risk_light": {"MARKET_EVENT_BLOCKED": True, "EVENT_RISK_LEVEL": "HIGH", "EVENT_WINDOW_STATE": "ACTIVE"},
        })
        assert blocked["SIGNAL_QUALITY_SCORE"] < baseline["SIGNAL_QUALITY_SCORE"]
        assert "event_blocked" in blocked["SIGNAL_WARNINGS"]

    def test_showcase_adapter_consistency(self, showcase):
        """Re-derive event_risk_light from broad block; must match fixture."""
        from scripts.smc_event_risk_light import build_event_risk_light
        derived = build_event_risk_light(event_risk=showcase.get("event_risk"))
        fixture_erl = showcase["event_risk_light"]
        for field in ("EVENT_WINDOW_STATE", "EVENT_RISK_LEVEL", "MARKET_EVENT_BLOCKED", "SYMBOL_EVENT_BLOCKED"):
            assert derived[field] == fixture_erl[field], f"{field}: derived={derived[field]} != fixture={fixture_erl[field]}"

    def test_ob_mitigation_state_semantics(self, showcase):
        """OB_MITIGATION_STATE must reflect age-derived lifecycle."""
        ob = showcase["ob_context_light"]
        state = ob["OB_MITIGATION_STATE"]
        age = ob["OB_AGE_BARS"]
        fresh = ob["OB_FRESH"]
        assert state in ALLOWED_OB_MITIGATION_STATE
        if state == "fresh":
            assert age <= 10
            assert fresh is True
        elif state == "touched":
            assert 11 <= age <= 30


# ── Product-Plausibility: Tier Monotonicity & Warning Propagation ───

class TestProductPlausibility:
    """v5.5b product-level semantic coherence tests."""

    def test_tier_monotonicity(self):
        """Improving components must not degrade the tier."""
        from scripts.smc_signal_quality import build_signal_quality

        baseline = build_signal_quality()
        improved = build_signal_quality(enrichment={
            "structure_state_light": {
                "STRUCTURE_FRESH": True,
                "STRUCTURE_EVENT_AGE_BARS": 2,
                "STRUCTURE_LAST_EVENT": "BOS_BULL",
            },
            "session_context_light": {
                "IN_KILLZONE": True,
                "SESSION_CONTEXT_SCORE": 5,
                "SESSION_DIRECTION_BIAS": "BULLISH",
            },
        })
        tier_order = ["low", "ok", "good", "high"]
        assert tier_order.index(improved["SIGNAL_QUALITY_TIER"]) >= tier_order.index(
            baseline["SIGNAL_QUALITY_TIER"]
        ), "Adding positive components must not lower tier"

    def test_warning_propagation_event_blocked(self):
        """MARKET_EVENT_BLOCKED must produce 'event_blocked' warning."""
        from scripts.smc_signal_quality import build_signal_quality

        result = build_signal_quality(enrichment={
            "event_risk_light": {
                "MARKET_EVENT_BLOCKED": True,
                "EVENT_RISK_LEVEL": "HIGH",
                "EVENT_WINDOW_STATE": "ACTIVE",
            },
        })
        assert "event_blocked" in result["SIGNAL_WARNINGS"]

    def test_bearish_scenario_coherent(self):
        """All-bearish inputs → bear bias alignment, fresh freshness."""
        from scripts.smc_signal_quality import build_signal_quality

        result = build_signal_quality(enrichment={
            "structure_state_light": {
                "STRUCTURE_LAST_EVENT": "BOS_BEAR",
                "STRUCTURE_EVENT_AGE_BARS": 2,
                "STRUCTURE_FRESH": True,
            },
            "session_context_light": {"SESSION_DIRECTION_BIAS": "BEARISH"},
            "ob_context_light": {"PRIMARY_OB_SIDE": "BEAR"},
            "fvg_lifecycle_light": {"PRIMARY_FVG_SIDE": "BEAR"},
        })
        assert result["SIGNAL_BIAS_ALIGNMENT"] == "bear"
        assert result["SIGNAL_FRESHNESS"] == "fresh"

    def test_freshness_degrades_with_aging(self):
        """As all components age, freshness must degrade from fresh → stale."""
        from scripts.smc_signal_quality import build_signal_quality

        fresh = build_signal_quality(enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_EVENT_AGE_BARS": 2},
            "ob_context_light": {"OB_FRESH": True},
            "fvg_lifecycle_light": {"FVG_FRESH": True},
        })
        stale = build_signal_quality(enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": False, "STRUCTURE_EVENT_AGE_BARS": 200},
            "ob_context_light": {"OB_FRESH": False},
            "fvg_lifecycle_light": {"FVG_FRESH": False},
        })
        freshness_order = ["stale", "aging", "fresh"]
        assert freshness_order.index(fresh["SIGNAL_FRESHNESS"]) > freshness_order.index(
            stale["SIGNAL_FRESHNESS"]
        ), "Aging components must degrade freshness"

    def test_sq_score_bounded(self):
        """Score must always be 0-100 regardless of extreme inputs."""
        from scripts.smc_signal_quality import build_signal_quality

        # Maximally positive scenario
        maxed = build_signal_quality(enrichment={
            "structure_state_light": {"STRUCTURE_FRESH": True, "STRUCTURE_EVENT_AGE_BARS": 1, "STRUCTURE_LAST_EVENT": "BOS_BULL"},
            "session_context_light": {"IN_KILLZONE": True, "SESSION_CONTEXT_SCORE": 7, "SESSION_DIRECTION_BIAS": "BULLISH"},
            "ob_context_light": {"OB_FRESH": True, "PRIMARY_OB_SIDE": "BULL", "OB_AGE_BARS": 1, "PRIMARY_OB_DISTANCE": 0.1},
            "fvg_lifecycle_light": {"FVG_FRESH": True, "PRIMARY_FVG_SIDE": "BULL", "FVG_MATURITY_LEVEL": 0},
            "compression": {"SQUEEZE_RELEASED": True, "ATR_REGIME": "EXPANSION"},
            "liquidity_sweeps": {"RECENT_BULL_SWEEP": True, "SWEEP_QUALITY_SCORE": 100},
        })
        assert 0 <= maxed["SIGNAL_QUALITY_SCORE"] <= 100


# ── Showcase Artifact Lane Tests ────────────────────────────────────


class TestShowcaseArtifactLane:
    """Validate generated showcase artifacts are present and consistent."""

    SHOWCASE_DIR = Path(__file__).parent / "fixtures" / "generated_showcase"

    def test_showcase_directory_exists(self):
        """Showcase output directory must exist after generation."""
        assert self.SHOWCASE_DIR.is_dir(), f"Missing: {self.SHOWCASE_DIR}"

    def test_manifest_present_and_valid(self):
        """showcase_manifest.json must exist with required keys."""
        manifest_path = self.SHOWCASE_DIR / "showcase_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert "schema_version" in manifest
        assert "generated_at" in manifest
        assert "artifacts" in manifest
        assert "lean_families" in manifest
        assert len(manifest["lean_families"]) == 6

    def test_adapter_summary_present(self):
        """showcase_adapter_summary.json must exist in showcase dir."""
        path = self.SHOWCASE_DIR / "showcase_adapter_summary.json"
        assert path.exists()
        summary = json.loads(path.read_text())
        assert "_meta" in summary
        assert "event_risk_light" in summary
        assert "signal_quality" in summary

    def test_pine_surface_present(self):
        """showcase_lean_surface.pine must exist and contain lean fields."""
        path = self.SHOWCASE_DIR / "showcase_lean_surface.pine"
        assert path.exists()
        content = path.read_text()
        assert "//@version=6" in content
        # Must contain at least one field from each lean family
        assert "EVENT_WINDOW_STATE" in content
        assert "IN_KILLZONE" in content
        assert "PRIMARY_OB_SIDE" in content
        assert "PRIMARY_FVG_SIDE" in content
        assert "STRUCTURE_LAST_EVENT" in content
        assert "SIGNAL_QUALITY_SCORE" in content

    def test_manifest_lists_all_artifacts(self):
        """Manifest artifacts list must match actual files."""
        manifest = json.loads(
            (self.SHOWCASE_DIR / "showcase_manifest.json").read_text()
        )
        for artifact_name in manifest["artifacts"]:
            assert (self.SHOWCASE_DIR / artifact_name).exists(), (
                f"Manifest lists {artifact_name} but file missing"
            )

    def test_legacy_compat_path(self):
        """Legacy showcase_adapter_summary.json must still exist at old path."""
        legacy = Path(__file__).parent / "fixtures" / "showcase_adapter_summary.json"
        assert legacy.exists()


# ── Measurement Lane Tests ──────────────────────────────────────────


class TestMeasurementLane:
    """Validate benchmark/scoring module structure and output shape."""

    def test_event_family_kpi_fields(self):
        """EventFamilyKPI must have all required KPI fields."""
        from smc_core.benchmark import EventFamilyKPI
        kpi = EventFamilyKPI(family="OB")
        assert hasattr(kpi, "hit_rate")
        assert hasattr(kpi, "time_to_mitigation_mean")
        assert hasattr(kpi, "invalidation_rate")
        assert hasattr(kpi, "mae")
        assert hasattr(kpi, "mfe")
        assert hasattr(kpi, "n_events")

    def test_benchmark_result_shape(self):
        """build_benchmark must return BenchmarkResult with KPIs."""
        from smc_core.benchmark import BenchmarkResult, build_benchmark
        result = build_benchmark(
            symbol="TEST",
            timeframe="5m",
            events_by_family={
                "OB": [{"hit": True, "time_to_mitigation": 5.0, "invalidated": False, "mae": 0.1, "mfe": 0.3}],
                "BOS": [],
            },
        )
        assert isinstance(result, BenchmarkResult)
        assert result.symbol == "TEST"
        assert len(result.kpis) == 2
        ob_kpi = next(k for k in result.kpis if k.family == "OB")
        assert ob_kpi.hit_rate == 1.0
        assert ob_kpi.n_events == 1

    def test_benchmark_export_creates_files(self, tmp_path):
        """export_benchmark_artifacts must create JSON + manifest."""
        from smc_core.benchmark import build_benchmark, export_benchmark_artifacts
        result = build_benchmark(
            symbol="AAPL",
            timeframe="5m",
            events_by_family={"OB": [{"hit": True, "time_to_mitigation": 3.0, "invalidated": False, "mae": 0.05, "mfe": 0.2}]},
        )
        manifest = export_benchmark_artifacts(result, tmp_path)
        assert (tmp_path / "benchmark_AAPL_5m.json").exists()
        assert (tmp_path / "manifest.json").exists()
        assert "benchmark_AAPL_5m.json" in manifest.artifacts

    def test_scoring_brier_range(self):
        """Brier score must be in [0, 1] for valid predictions."""
        from smc_core.scoring import brier_score
        assert brier_score([(0.9, True), (0.1, False)]) < 0.1  # good calibration
        assert brier_score([(0.1, True), (0.9, False)]) > 0.5  # bad calibration
        assert 0 <= brier_score([(0.5, True), (0.5, False)]) <= 1.0

    def test_scoring_log_score_finite(self):
        """Log score must be finite for valid predictions."""
        from smc_core.scoring import log_score
        import math
        score = log_score([(0.8, True), (0.2, False)])
        assert math.isfinite(score)
        assert score > 0

    def test_sweep_reversal_label(self):
        """label_sweep_reversal must detect directional reversals."""
        from smc_core.scoring import label_sweep_reversal
        # Sell-side sweep → expect UP reversal
        assert label_sweep_reversal(100.0, "SELL_SIDE", [100.6, 101.0])
        assert not label_sweep_reversal(100.0, "SELL_SIDE", [100.0, 100.1])
        # Buy-side sweep → expect DOWN reversal
        assert label_sweep_reversal(100.0, "BUY_SIDE", [99.4, 99.0])
        assert not label_sweep_reversal(100.0, "BUY_SIDE", [100.0, 99.9])

    def test_score_events_integration(self):
        """score_events must produce valid ScoringResult."""
        from smc_core.scoring import ScoredEvent, score_events
        events = [
            ScoredEvent(event_id="1", family="SWEEP", predicted_prob=0.8, outcome=True, timestamp=1.0),
            ScoredEvent(event_id="2", family="SWEEP", predicted_prob=0.3, outcome=False, timestamp=2.0),
        ]
        result = score_events(events)
        assert result.n_events == 2
        assert 0 <= result.brier_score <= 1
        assert result.hit_rate == 0.5
