"""Unit tests for the Hero State Contract (scripts/smc_hero_state.py)."""
from __future__ import annotations

from scripts.smc_hero_state import DEFAULTS, _derive_action, _derive_bias, _derive_trust, build_hero_state


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


# ── Boundary-Contract Vocabulary Pins (F-2, F-4, F-6 · PR-BC-04) ──────


class TestHeroTrustVocabularyPins:
    """Pine-boundary F-2: SMC_Dashboard.pine:1753,1774 compare to
    lowercase ``HERO_TRUST`` literals. Pin the exact values and the
    declared vocabulary frozenset so a rename is a test failure.
    """

    def test_hero_trust_literals_pinned(self) -> None:
        from scripts.smc_hero_state import (
            HERO_TRUST_DEGRADED,
            HERO_TRUST_HEALTHY,
            HERO_TRUST_STALE,
            HERO_TRUST_UNAVAILABLE,
            HERO_TRUST_WARMUP,
        )
        assert HERO_TRUST_HEALTHY == "healthy"
        assert HERO_TRUST_WARMUP == "warmup"
        assert HERO_TRUST_DEGRADED == "degraded"
        assert HERO_TRUST_STALE == "stale"
        assert HERO_TRUST_UNAVAILABLE == "unavailable"

    def test_derive_trust_returns_value_in_declared_vocab(self) -> None:
        from scripts.smc_hero_state import HERO_TRUST_VOCAB

        combos = [
            ("fresh", "", "high"),
            ("fresh", "", "low"),
            ("aging", "", "good"),
            ("stale", "", "good"),
            ("stale", "a,b", "good"),
            ("fresh", "a,b", "high"),
        ]
        for freshness, stale, tier in combos:
            out = _derive_trust(
                signal_freshness=freshness,
                stale_providers=stale,
                ensemble_tier=tier,
            )
            assert out in HERO_TRUST_VOCAB, f"Unknown trust state: {out!r}"

    def test_project_trust_state_covers_all_enum_members(self) -> None:
        """Every ``TrustState`` must have a Hero mapping. Missing entries
        raise ``KeyError`` — a clear signal before WS2-03 wires
        ``TrustStateAssessment`` into Hero.
        """
        from scripts.smc_hero_state import HERO_TRUST_VOCAB, project_trust_state_to_hero
        from smc_integration.trust_state import TrustState

        for member in TrustState:
            result = project_trust_state_to_hero(member)
            assert isinstance(result, str)
            assert result in HERO_TRUST_VOCAB

    def test_project_trust_state_collapses_watch_only_to_degraded(self) -> None:
        """Document the single information-loss point (F-2, §5.3)."""
        from scripts.smc_hero_state import HERO_TRUST_DEGRADED, project_trust_state_to_hero
        from smc_integration.trust_state import TrustState

        assert project_trust_state_to_hero(TrustState.WATCH_ONLY) == HERO_TRUST_DEGRADED


class TestHeroSetupQualityVocabularyPins:
    """F-4: pin both Producer-A and Producer-B quality vocabularies and
    prove the A→B bridge covers the full ``_ACTION_TABLE`` domain so a
    future WS3 convergence is trivial.
    """

    def test_hero_setup_quality_matches_pine_literal_vocab(self) -> None:
        from scripts.smc_hero_state import (
            DEFAULTS,
            HERO_SETUP_QUALITY_VOCAB,
            build_hero_state,
        )

        assert DEFAULTS["HERO_SETUP_QUALITY"] in HERO_SETUP_QUALITY_VOCAB
        for tier in ["high", "good", "ok", "low"]:
            out = build_hero_state({
                "signal_quality": {"SIGNAL_QUALITY_TIER": tier},
            })
            assert out["HERO_SETUP_QUALITY"] in HERO_SETUP_QUALITY_VOCAB

    def test_hero_quality_a_to_b_covers_full_domain(self) -> None:
        from scripts.smc_hero_state import HERO_QUALITY_A_TO_B, HERO_SETUP_QUALITY_VOCAB

        assert set(HERO_QUALITY_A_TO_B.keys()) == set(HERO_SETUP_QUALITY_VOCAB)

    def test_hero_quality_a_to_b_targets_action_table_domain(self) -> None:
        """Every Producer-B key in ``_ACTION_TABLE`` must be reachable
        via ``HERO_QUALITY_A_TO_B``. Lackmus test for WS3 convergence.
        """
        from scripts.smc_hero_action import _ACTION_TABLE
        from scripts.smc_hero_state import HERO_QUALITY_A_TO_B

        producer_b_domain = {quality for (_deg, quality) in _ACTION_TABLE}
        assert set(HERO_QUALITY_A_TO_B.values()) == producer_b_domain


class TestHeroActionVocabularyPins:
    """F-6 docs: pin the Producer-A action vocabulary so the WS3
    reconciliation with the reserved ``HERO_ACTION_VERB`` (lowercase
    verb vocabulary) starts from a known-safe baseline.
    """

    def test_hero_action_literals_pinned(self) -> None:
        from scripts.smc_hero_state import (
            HERO_ACTION_ACTIVE,
            HERO_ACTION_AVOID,
            HERO_ACTION_BLOCKED,
            HERO_ACTION_WATCH,
        )
        assert HERO_ACTION_ACTIVE == "ACTIVE"
        assert HERO_ACTION_WATCH == "WATCH"
        assert HERO_ACTION_AVOID == "AVOID"
        assert HERO_ACTION_BLOCKED == "BLOCKED"

    def test_derive_action_returns_value_in_declared_vocab(self) -> None:
        from scripts.smc_hero_state import HERO_ACTION_VOCAB

        trade_states = ["ALLOWED", "SELECTIVE", "WATCH", "AVOID", "BLOCKED"]
        trust_states = ["healthy", "warmup", "degraded", "stale", "unavailable"]
        for ts in trade_states:
            for trust in trust_states:
                out = _derive_action(trade_state=ts, trust=trust)
                assert out in HERO_ACTION_VOCAB, (
                    f"_derive_action({ts!r}, {trust!r}) -> {out!r} "
                    f"not in HERO_ACTION_VOCAB"
                )
