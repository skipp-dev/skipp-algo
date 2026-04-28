"""Tests for the Hero Setup-Quality card (ENG-WS3-04)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.smc_hero_setup_quality import (
    PINE_HERO_QUALITY_FIELDS,
    HeroSetupQuality,
    all_quality_tiers,
    derive_hero_setup_quality,
    render_hero_setup_quality_block_lines,
)

# ── Vocabulary ────────────────────────────────────────────────────────


class TestVocabulary:
    def test_four_tiers_in_severity_order(self) -> None:
        assert all_quality_tiers() == ("excellent", "good", "limited", "avoid")


# ── Tier derivation ───────────────────────────────────────────────────


class TestTierDerivation:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (0.95, "excellent"),
            (0.80, "excellent"),
            (0.79, "good"),
            (0.60, "good"),
            (0.40, "limited"),
            (0.39, "avoid"),
            (0.0, "avoid"),
        ],
    )
    def test_tier_thresholds(self, score: float, expected: str) -> None:
        q = derive_hero_setup_quality({"ensemble_quality": {"score": score}})
        assert q.tier == expected

    @pytest.mark.parametrize(
        "raw_tier,expected",
        [("high", "excellent"), ("mid", "good"), ("low", "limited"), ("na", "avoid")],
    )
    def test_existing_ensemble_tier_translation(
        self, raw_tier: str, expected: str
    ) -> None:
        q = derive_hero_setup_quality({"ensemble_quality": {"tier": raw_tier}})
        assert q.tier == expected

    def test_unknown_raw_tier_falls_back_to_score(self) -> None:
        q = derive_hero_setup_quality({"ensemble_quality": {"tier": "rumour", "score": 0.65}})
        assert q.tier == "good"


# ── Why now / main risk ───────────────────────────────────────────────


class TestWhyNow:
    def test_explicit_hero_quality_why_now_wins(self) -> None:
        q = derive_hero_setup_quality({
            "hero_quality": {"why_now": "BOS confirmed at HTF level"},
            "ensemble_quality": {"score": 0.5, "why_now": "fallback"},
        })
        assert q.why_now == "BOS confirmed at HTF level"

    def test_falls_back_to_ensemble_quality_why_now(self) -> None:
        q = derive_hero_setup_quality({
            "ensemble_quality": {"score": 0.5, "why_now": "FVG fresh"},
        })
        assert q.why_now == "FVG fresh"

    @pytest.mark.parametrize(
        "score,must_contain",
        [
            (0.9, "excellent"),
            (0.7, "good"),
            (0.45, "selektiv"),
            (0.1, "beobachten"),
        ],
    )
    def test_default_why_now_is_never_empty(
        self, score: float, must_contain: str
    ) -> None:
        q = derive_hero_setup_quality({"ensemble_quality": {"score": score}})
        assert q.why_now
        assert must_contain in q.why_now


class TestMainRisk:
    def test_explicit_hero_quality_main_risk_wins(self) -> None:
        q = derive_hero_setup_quality({
            "hero_quality": {"main_risk": "FOMC in 30 minutes"},
            "ensemble_quality": {"score": 0.9, "main_risk": "fallback"},
        })
        assert q.main_risk == "FOMC in 30 minutes"

    def test_falls_back_to_ensemble_quality_main_risk(self) -> None:
        q = derive_hero_setup_quality({
            "ensemble_quality": {"score": 0.9, "main_risk": "Liquidity sweep risk"},
        })
        assert q.main_risk == "Liquidity sweep risk"

    def test_falls_back_to_trust_state_description(self) -> None:
        q = derive_hero_setup_quality({
            "ensemble_quality": {"score": 0.45},
            "trust_state": {
                "state": "watch_only",
                "action_impact": "x",
                "cause": {
                    "domain": "structure", "failure_type": "stale",
                    "code": "STALE_MANIFEST_GENERATED_AT",
                    "description": "Manifest älter als 24h",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "fail",
            },
        })
        assert q.main_risk == "Manifest älter als 24h"

    @pytest.mark.parametrize(
        "score,must_contain",
        [
            (0.9, "Position sizing"),
            (0.7, "Confluence partial"),
            (0.45, "thin"),
            (0.1, "unsupported"),
        ],
    )
    def test_default_main_risk_is_never_empty(
        self, score: float, must_contain: str
    ) -> None:
        q = derive_hero_setup_quality({"ensemble_quality": {"score": score}})
        assert q.main_risk
        assert must_contain in q.main_risk


# ── Family health ─────────────────────────────────────────────────────


class TestFamilyHealth:
    @pytest.mark.parametrize(
        "components,expected",
        [
            (4, "all_families"),
            (3, "three_families"),
            (2, "two_families"),
            (1, "single_family"),
            (0, "no_families"),
        ],
    )
    def test_component_count_to_label(
        self, components: int, expected: str
    ) -> None:
        q = derive_hero_setup_quality({
            "ensemble_quality": {"score": 0.5, "available_components": components}
        })
        assert q.family_health == expected

    def test_unknown_default(self) -> None:
        q = derive_hero_setup_quality({})
        assert q.family_health == "unknown"


# ── Empty enrichment defaults ─────────────────────────────────────────


class TestEmptyEnrichmentDefaults:
    def test_full_default_card(self) -> None:
        q = derive_hero_setup_quality({})
        assert q == HeroSetupQuality(
            tier="avoid",
            why_now="Confluence missing — beobachten",
            main_risk="Setup unsupported — keine Aktion",
            family_health="unknown",
        )


# ── Pine rendering ────────────────────────────────────────────────────


class TestPineRendering:
    def test_block_header_first(self) -> None:
        lines = render_hero_setup_quality_block_lines({})
        assert lines[0] == "// ── Hero Setup Quality (ENG-WS3-04) ──"

    def test_emits_four_fields_in_canonical_order(self) -> None:
        lines = render_hero_setup_quality_block_lines({})
        names = [line.split()[3] for line in lines if line.startswith("export const")]
        assert names == list(PINE_HERO_QUALITY_FIELDS)

    def test_emits_full_card_for_excellent(self) -> None:
        text = "\n".join(render_hero_setup_quality_block_lines({
            "ensemble_quality": {
                "score": 0.92, "available_components": 4,
                "why_now": "BOS + OB + FVG aligned",
                "main_risk": "FOMC in 1h",
            },
        }))
        assert 'HERO_QUALITY_TIER = "excellent"' in text
        assert 'HERO_QUALITY_WHY_NOW = "BOS + OB + FVG aligned"' in text
        assert 'HERO_QUALITY_MAIN_RISK = "FOMC in 1h"' in text
        assert 'HERO_QUALITY_FAMILY_HEALTH = "all_families"' in text

    def test_quotes_are_pine_escaped(self) -> None:
        text = "\n".join(render_hero_setup_quality_block_lines({
            "hero_quality": {"why_now": 'edge "tight"', "main_risk": "ok"},
        }))
        assert 'HERO_QUALITY_WHY_NOW = "edge \\"tight\\""' in text


# ── End-to-end ────────────────────────────────────────────────────────


class TestPineLibraryEmission:
    def test_pine_library_emits_default_card(self, tmp_path: Path) -> None:
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
        assert "// ── Hero Setup Quality (ENG-WS3-04) ──" in text
        assert 'export const string HERO_QUALITY_TIER = "avoid"' in text
        assert 'export const string HERO_QUALITY_FAMILY_HEALTH = "unknown"' in text

    def test_pine_library_emits_full_card_for_excellent(self, tmp_path: Path) -> None:
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
                    "score": 0.88,
                    "available_components": ["BOS", "OB", "FVG", "SWEEP"],
                    "why_now": "BOS + OB confirm",
                    "main_risk": "Position sizing only",
                },
            },
        )
        text = out.read_text(encoding="utf-8")
        assert 'export const string HERO_QUALITY_TIER = "excellent"' in text
        assert 'export const string HERO_QUALITY_WHY_NOW = "BOS + OB confirm"' in text
        assert 'export const string HERO_QUALITY_MAIN_RISK = "Position sizing only"' in text
        assert 'export const string HERO_QUALITY_FAMILY_HEALTH = "all_families"' in text
