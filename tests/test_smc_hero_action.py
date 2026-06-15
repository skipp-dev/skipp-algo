"""Tests for the Hero Action recommendation (ENG-WS3-05)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.smc_hero_action import (
    all_action_verbs,
    derive_hero_action,
)
from scripts.smc_hero_state import build_hero_state
from smc_integration.action_degradation import ActionDegradation

# ── Vocabulary ────────────────────────────────────────────────────────


class TestVocabulary:
    def test_four_action_verbs_in_severity_order(self) -> None:
        assert all_action_verbs() == ("act", "wait", "watch", "avoid")


# ── Per-state mapping ─────────────────────────────────────────────────


def _make_enrichment(degradation: str, score: float) -> dict:
    return {
        "action_degradation": {
            "tier": degradation,
            "reason": "test reason",
            "derived_from_state": "healthy",
        },
        "ensemble_quality": {"score": score, "available_components": [1, 2]},
        "signal_quality": {"SIGNAL_FRESHNESS": "fresh", "SIGNAL_QUALITY_TIER": "good"},
    }


class TestPerStateMapping:
    @pytest.mark.parametrize(
        "degradation,score,expected_verb",
        [
            # NO_TRADE always vermeiden
            ("no_trade", 0.95, "avoid"),
            ("no_trade", 0.20, "avoid"),
            # WATCHLIST always beobachten
            ("watchlist", 0.95, "watch"),
            ("watchlist", 0.20, "watch"),
            # SELECTIVE depends on quality
            ("selective", 0.85, "act"),
            ("selective", 0.65, "wait"),
            ("selective", 0.45, "watch"),
            ("selective", 0.10, "avoid"),
            # NONE depends on quality
            ("none", 0.85, "act"),
            ("none", 0.65, "act"),
            ("none", 0.45, "wait"),
            ("none", 0.10, "watch"),
        ],
    )
    def test_action_table_is_deterministic(
        self, degradation: str, score: float, expected_verb: str
    ) -> None:
        action = derive_hero_action(_make_enrichment(degradation, score))
        assert action.verb == expected_verb

    def test_one_primary_action_per_state(self) -> None:
        # Every (degradation, quality) pair must produce exactly one verb.
        verbs_seen: dict[tuple[str, str], str] = {}
        for deg in ActionDegradation:
            for q_score, q_label in [(0.95, "excellent"), (0.65, "good"), (0.45, "limited"), (0.10, "avoid")]:
                a = derive_hero_action({
                    "action_degradation": {
                        "tier": deg.value, "reason": "x",
                        "derived_from_state": "healthy",
                    },
                    "ensemble_quality": {"score": q_score},
                })
                key = (deg.value, q_label)
                assert key not in verbs_seen
                verbs_seen[key] = a.verb
        assert len(verbs_seen) == 16


# ── Verb localisation ─────────────────────────────────────────────────


class TestVerbLocalisation:
    @pytest.mark.parametrize(
        "verb,verb_de",
        [
            ("act", "handeln"),
            ("wait", "warten"),
            ("watch", "beobachten"),
            ("avoid", "vermeiden"),
        ],
    )
    def test_german_verb_table(self, verb: str, verb_de: str) -> None:
        # Find a degradation/quality combo that yields the desired verb
        target = {"act": ("none", 0.95), "wait": ("none", 0.45),
                  "watch": ("watchlist", 0.95), "avoid": ("no_trade", 0.95)}
        deg, score = target[verb]
        action = derive_hero_action(_make_enrichment(deg, score))
        assert action.verb == verb
        assert action.verb_de == verb_de


# ── Reason composition ───────────────────────────────────────────────


class TestReason:
    def test_degraded_action_uses_degradation_reason(self) -> None:
        action = derive_hero_action({
            "action_degradation": {
                "tier": "watchlist",
                "reason": "Manifest älter als 24h",
                "derived_from_state": "watch_only",
            },
            "ensemble_quality": {"score": 0.85, "main_risk": "irrelevant"},
        })
        assert action.reason == "Manifest älter als 24h"

    def test_healthy_action_uses_quality_main_risk(self) -> None:
        action = derive_hero_action({
            "action_degradation": {"tier": "none", "reason": "", "derived_from_state": "healthy"},
            "ensemble_quality": {"score": 0.85, "main_risk": "FOMC in 1h"},
        })
        assert action.verb == "act"
        assert action.reason == "FOMC in 1h"

    def test_reason_is_never_empty_for_any_state(self) -> None:
        # Defaults: empty enrichment yields verb=watch (no_trade NONE →
        # actually default is no degradation block + no trust, derive from
        # empty enrichment gives healthy, quality avoid → watch).
        action = derive_hero_action({})
        assert action.reason


# ── Action does not contradict main risk ──────────────────────────────


class TestActionDoesNotContradict:
    def test_no_trade_action_carries_blocker_reason(self) -> None:
        action = derive_hero_action({
            "trust_state": {
                "state": "unavailable",
                "action_impact": "suppress_product",
                "cause": {
                    "domain": "structure", "failure_type": "missing",
                    "code": "MISSING_STRUCTURE_DOMAIN",
                    "description": "Structure missing",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "fail",
            },
            "ensemble_quality": {"score": 0.95, "main_risk": "Sizing"},
        })
        assert action.verb == "avoid"
        assert action.degradation == "no_trade"
        # The reason must reflect the actual blocker (data state), not
        # the quality main_risk which would contradict the action.
        assert action.reason == "Structure missing"

    def test_act_action_does_not_quote_data_state(self) -> None:
        # For an act action, the trust must be healthy → the reason
        # must come from setup, never from a degradation reason.
        action = derive_hero_action({
            "ensemble_quality": {"score": 0.92, "main_risk": "Sizing", "why_now": "BOS confirm"},
        })
        assert action.verb == "act"
        assert action.degradation == "none"
        assert action.reason == "Sizing"


# ── HERO_ACTION boundary projection ───────────────────────────────────


class TestHeroActionBoundaryProjection:
    @pytest.mark.parametrize(
        "degradation,score,expected_hero_action",
        [
            ("no_trade", 0.95, "BLOCKED"),
            ("no_trade", 0.20, "BLOCKED"),
            ("watchlist", 0.95, "WATCH"),
            ("watchlist", 0.20, "WATCH"),
            ("selective", 0.85, "ACTIVE"),
            ("selective", 0.65, "WATCH"),
            ("selective", 0.45, "WATCH"),
            ("selective", 0.10, "AVOID"),
            ("none", 0.85, "ACTIVE"),
            ("none", 0.65, "ACTIVE"),
            ("none", 0.45, "WATCH"),
            ("none", 0.10, "WATCH"),
        ],
    )
    def test_producer_b_maps_to_single_uppercase_pine_field(
        self, degradation: str, score: float, expected_hero_action: str
    ) -> None:
        hero_state = build_hero_state(_make_enrichment(degradation, score))
        assert hero_state["HERO_ACTION"] == expected_hero_action


# ── End-to-end Pine library emission ──────────────────────────────────


class TestPineLibraryEmission:
    def test_pine_library_emits_only_default_hero_action(self, tmp_path: Path) -> None:
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        out = tmp_path / "lib.pine"
        enrichment = {"providers": {"provider_count": 0, "stale_providers": ""}}
        enrichment["hero_state"] = build_hero_state(enrichment)
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment=enrichment,
        )
        text = out.read_text(encoding="utf-8")
        assert "// ── Hero Action (ENG-WS3-05) ──" not in text
        assert "HERO_ACTION_VERB" not in text
        assert 'export const string HERO_ACTION = "WATCH"' in text

    def test_pine_library_emits_active_hero_action_for_excellent_healthy(self, tmp_path: Path) -> None:
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        out = tmp_path / "lib.pine"
        enrichment = {
            "providers": {"provider_count": 1, "stale_providers": ""},
            "signal_quality": {"SIGNAL_FRESHNESS": "fresh", "SIGNAL_QUALITY_TIER": "good"},
            "ensemble_quality": {
                "score": 0.92, "available_components": ["BOS", "OB", "FVG", "SWEEP"],
                "main_risk": "Position sizing only",
            },
        }
        enrichment["hero_state"] = build_hero_state(enrichment)
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment=enrichment,
        )
        text = out.read_text(encoding="utf-8")
        assert "HERO_ACTION_VERB" not in text
        assert 'export const string HERO_ACTION = "ACTIVE"' in text
