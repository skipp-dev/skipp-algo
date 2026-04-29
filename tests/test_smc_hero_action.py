"""Tests for the Hero Action recommendation (ENG-WS3-05)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.smc_hero_action import (
    PINE_HERO_ACTION_FIELDS,
    all_action_verbs,
    derive_hero_action,
    render_hero_action_block_lines,
)
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


# ── Pine rendering ────────────────────────────────────────────────────


class TestPineRendering:
    def test_block_header_first(self) -> None:
        lines = render_hero_action_block_lines({})
        assert lines[0] == "// ── Hero Action (ENG-WS3-05) ──"

    def test_emits_five_fields_in_canonical_order(self) -> None:
        lines = render_hero_action_block_lines({})
        names = [line.split()[3] for line in lines if line.startswith("export const")]
        assert names == list(PINE_HERO_ACTION_FIELDS)

    def test_emits_full_avoid_block(self) -> None:
        text = "\n".join(render_hero_action_block_lines({
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
            "ensemble_quality": {"score": 0.92},
        }))
        assert 'HERO_ACTION_VERB = "avoid"' in text
        assert 'HERO_ACTION_VERB_DE = "vermeiden"' in text
        assert 'HERO_ACTION_REASON = "Structure missing"' in text
        assert 'HERO_ACTION_DEGRADATION = "no_trade"' in text
        assert 'HERO_ACTION_QUALITY = "excellent"' in text


# ── End-to-end Pine library emission ──────────────────────────────────


class TestPineLibraryEmission:
    def test_pine_library_emits_default_action_block(self, tmp_path: Path) -> None:
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        out = tmp_path / "lib.pine"
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment={"providers": {"provider_count": 0, "stale_providers": ""}},
        )
        text = out.read_text(encoding="utf-8")
        assert "// ── Hero Action (ENG-WS3-05) ──" in text
        # Default: no degradation + no quality → watch.
        assert 'export const string HERO_ACTION_VERB = "watch"' in text
        assert 'export const string HERO_ACTION_VERB_DE = "beobachten"' in text
        assert 'export const string HERO_ACTION_DEGRADATION = "none"' in text
        assert 'export const string HERO_ACTION_QUALITY = "avoid"' in text

    def test_pine_library_emits_act_block_for_excellent_healthy(self, tmp_path: Path) -> None:
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        out = tmp_path / "lib.pine"
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment={
                "providers": {"provider_count": 1, "stale_providers": ""},
                "ensemble_quality": {
                    "score": 0.92, "available_components": ["BOS", "OB", "FVG", "SWEEP"],
                    "main_risk": "Position sizing only",
                },
            },
        )
        text = out.read_text(encoding="utf-8")
        assert 'export const string HERO_ACTION_VERB = "act"' in text
        assert 'export const string HERO_ACTION_VERB_DE = "handeln"' in text
        assert 'export const string HERO_ACTION_REASON = "Position sizing only"' in text
        assert 'export const string HERO_ACTION_DEGRADATION = "none"' in text
        assert 'export const string HERO_ACTION_QUALITY = "excellent"' in text
