"""Tests for the Hero Market-Mode head (ENG-WS3-03)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.smc_hero_market_mode import (
    HeroMarketMode,
    PINE_HERO_MARKET_FIELDS,
    derive_hero_market_mode,
    render_hero_market_mode_block_lines,
)


# ── Vocabulary / dataclass ────────────────────────────────────────────


class TestDataclass:
    def test_as_dict_carries_five_keys(self) -> None:
        head = HeroMarketMode(
            regime="risk_on", bias="long", session="us_open",
            trust="trusted", freshness="fresh",
        )
        assert head.as_dict() == {
            "regime": "risk_on",
            "bias": "long",
            "session": "us_open",
            "trust": "trusted",
            "freshness": "fresh",
        }


# ── Bias classification ───────────────────────────────────────────────


class TestBiasClassification:
    @pytest.mark.parametrize(
        "macro_bias,expected",
        [
            (0.5, "long"),
            (0.15, "long"),
            (0.14, "neutral"),
            (0.0, "neutral"),
            (-0.14, "neutral"),
            (-0.15, "short"),
            (-0.7, "short"),
        ],
    )
    def test_bias_thresholds(self, macro_bias: float, expected: str) -> None:
        head = derive_hero_market_mode({"regime": {"macro_bias": macro_bias}})
        assert head.bias == expected


# ── Trust → trust + freshness labels ──────────────────────────────────


class TestTrustAndFreshnessLabels:
    @pytest.mark.parametrize(
        "state,expected_trust,expected_freshness",
        [
            ("healthy", "trusted", "fresh"),
            ("degraded", "advisory", "fresh"),
            ("stale", "stale", "stale"),
            ("watch_only", "watch_only", "stale"),
            ("unavailable", "unavailable", "missing"),
        ],
    )
    def test_labels_from_attached_trust_block(
        self, state: str, expected_trust: str, expected_freshness: str
    ) -> None:
        head = derive_hero_market_mode({
            "trust_state": {
                "state": state,
                "action_impact": "x",
                "cause": {"domain": None, "failure_type": None, "code": None, "description": None},
                "contributing_alerts": [],
                "derived_from_overall_status": "ok",
            }
        })
        assert head.trust == expected_trust
        assert head.freshness == expected_freshness

    def test_falls_back_to_derived_trust_when_no_block(self) -> None:
        head = derive_hero_market_mode({
            "overall_status": "fail",
            "domain_alerts": [
                {"domain": "structure", "code": "MISSING_STRUCTURE_DOMAIN", "message": "missing"}
            ],
        })
        assert head.trust == "unavailable"
        assert head.freshness == "missing"

    def test_unknown_state_string_falls_back_to_healthy(self) -> None:
        head = derive_hero_market_mode({
            "trust_state": {
                "state": "rumour",
                "action_impact": "x",
                "cause": {"domain": None, "failure_type": None, "code": None, "description": None},
                "contributing_alerts": [],
                "derived_from_overall_status": "ok",
            }
        })
        assert head.trust == "trusted"


# ── Regime / Session ──────────────────────────────────────────────────


class TestRegimeAndSession:
    def test_regime_lowercased(self) -> None:
        head = derive_hero_market_mode({"regime": {"regime": "RISK_ON", "macro_bias": 0.0}})
        assert head.regime == "risk_on"

    def test_regime_default_neutral(self) -> None:
        head = derive_hero_market_mode({})
        assert head.regime == "neutral"

    def test_session_prefers_session_context_light(self) -> None:
        head = derive_hero_market_mode({
            "session_context_light": {"SESSION_CONTEXT": "LIGHT_LABEL"},
            "session_context": {"SESSION_CONTEXT": "FULL_LABEL"},
        })
        assert head.session == "LIGHT_LABEL"

    def test_session_falls_back_to_session_context(self) -> None:
        head = derive_hero_market_mode({
            "session_context": {"SESSION_CONTEXT": "FULL_LABEL"},
        })
        assert head.session == "FULL_LABEL"

    def test_session_default_unknown(self) -> None:
        head = derive_hero_market_mode({})
        assert head.session == "unknown"


# ── Empty enrichment defaults ─────────────────────────────────────────


class TestEmptyEnrichmentDefaults:
    def test_full_default_head(self) -> None:
        head = derive_hero_market_mode({})
        assert head == HeroMarketMode(
            regime="neutral",
            bias="neutral",
            session="unknown",
            trust="trusted",
            freshness="fresh",
        )


# ── Pine rendering ────────────────────────────────────────────────────


class TestPineRendering:
    def test_block_header_first(self) -> None:
        lines = render_hero_market_mode_block_lines({})
        assert lines[0] == "// ── Hero Market Mode (ENG-WS3-03) ──"

    def test_emits_five_fields_in_canonical_order(self) -> None:
        lines = render_hero_market_mode_block_lines({})
        names = [line.split()[3] for line in lines if line.startswith("export const")]
        assert names == list(PINE_HERO_MARKET_FIELDS)

    def test_emits_full_head_for_watch_only(self) -> None:
        text = "\n".join(render_hero_market_mode_block_lines({
            "regime": {"regime": "RISK_OFF", "macro_bias": -0.4},
            "session_context_light": {"SESSION_CONTEXT": "us_close"},
            "trust_state": {
                "state": "watch_only",
                "action_impact": "no_new_entries",
                "cause": {
                    "domain": "structure", "failure_type": "stale",
                    "code": "STALE_MANIFEST_GENERATED_AT",
                    "description": "Manifest älter als 24h",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "fail",
            },
        }))
        assert 'HERO_MARKET_REGIME = "risk_off"' in text
        assert 'HERO_MARKET_BIAS = "short"' in text
        assert 'HERO_MARKET_SESSION = "us_close"' in text
        assert 'HERO_MARKET_TRUST = "watch_only"' in text
        assert 'HERO_MARKET_FRESHNESS = "stale"' in text


# ── End-to-end: Pine library emission ─────────────────────────────────


class TestPineLibraryEmission:
    def test_pine_library_emits_hero_market_block(self, tmp_path: Path) -> None:
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        out = tmp_path / "lib.pine"
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment={
                "providers": {"provider_count": 1, "stale_providers": ""},
                "regime": {"regime": "RISK_ON", "macro_bias": 0.6},
                "session_context_light": {"SESSION_CONTEXT": "us_open"},
            },
        )
        text = out.read_text(encoding="utf-8")
        assert "// ── Hero Market Mode (ENG-WS3-03) ──" in text
        assert 'export const string HERO_MARKET_REGIME = "risk_on"' in text
        assert 'export const string HERO_MARKET_BIAS = "long"' in text
        assert 'export const string HERO_MARKET_SESSION = "us_open"' in text
        assert 'export const string HERO_MARKET_TRUST = "trusted"' in text
        assert 'export const string HERO_MARKET_FRESHNESS = "fresh"' in text

    def test_pine_library_emits_default_hero_market_block(self, tmp_path: Path) -> None:
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
        assert 'export const string HERO_MARKET_REGIME = "neutral"' in text
        assert 'export const string HERO_MARKET_BIAS = "neutral"' in text
        assert 'export const string HERO_MARKET_SESSION = "unknown"' in text
        assert 'export const string HERO_MARKET_TRUST = "trusted"' in text
        assert 'export const string HERO_MARKET_FRESHNESS = "fresh"' in text
