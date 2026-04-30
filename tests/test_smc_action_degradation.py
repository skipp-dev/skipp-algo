"""Tests for the action-degradation policy (ENG-WS2-04)."""
from __future__ import annotations

from pathlib import Path

import pytest

from smc_integration.action_degradation import (
    ActionDegradation,
    all_action_tiers,
    derive_action_degradation,
    tier_for_trust_state,
)
from smc_integration.trust_state import (
    TrustState,
    TrustStateAssessment,
    TrustStateCause,
    derive_trust_state,
)

# ── Vocabulary ────────────────────────────────────────────────────────


class TestVocabulary:
    def test_four_tiers_exist(self) -> None:
        names = {t.name for t in ActionDegradation}
        assert names == {"NONE", "SELECTIVE", "WATCHLIST", "NO_TRADE"}

    def test_severity_order_is_stable(self) -> None:
        assert list(all_action_tiers()) == [
            ActionDegradation.NONE,
            ActionDegradation.SELECTIVE,
            ActionDegradation.WATCHLIST,
            ActionDegradation.NO_TRADE,
        ]


# ── Mapping table ─────────────────────────────────────────────────────


class TestMapping:
    @pytest.mark.parametrize(
        "state,tier",
        [
            (TrustState.HEALTHY, ActionDegradation.NONE),
            (TrustState.DEGRADED, ActionDegradation.SELECTIVE),
            (TrustState.STALE, ActionDegradation.SELECTIVE),
            (TrustState.WATCH_ONLY, ActionDegradation.WATCHLIST),
            (TrustState.UNAVAILABLE, ActionDegradation.NO_TRADE),
        ],
    )
    def test_canonical_mapping(self, state: TrustState, tier: ActionDegradation) -> None:
        assert tier_for_trust_state(state) is tier


# ── Derivation ────────────────────────────────────────────────────────


def _alert(domain: str, code: str, message: str = "") -> dict:
    return {"domain": domain, "code": code, "message": message}


class TestDerivation:
    def test_healthy_assessment_yields_none_with_empty_reason(self) -> None:
        assessment = derive_trust_state({})
        result = derive_action_degradation(assessment)
        assert result.tier is ActionDegradation.NONE
        assert result.reason == ""
        assert result.derived_from_state is TrustState.HEALTHY

    def test_volume_stale_yields_selective(self) -> None:
        assessment = derive_trust_state({
            "overall_status": "warn",
            "domain_alerts": [_alert("volume", "STALE_META_VOLUME_DOMAIN", "Volume älter als 12h")],
        })
        result = derive_action_degradation(assessment)
        assert result.tier is ActionDegradation.SELECTIVE
        assert result.reason == "Volume älter als 12h"
        assert result.derived_from_state is TrustState.STALE

    def test_structure_stale_yields_watchlist(self) -> None:
        assessment = derive_trust_state({
            "overall_status": "fail",
            "domain_alerts": [_alert("structure", "STALE_MANIFEST_GENERATED_AT")],
        })
        result = derive_action_degradation(assessment)
        assert result.tier is ActionDegradation.WATCHLIST
        assert result.derived_from_state is TrustState.WATCH_ONLY
        # Reason was empty in the alert, so we synthesise one from cause.
        assert "structure" in result.reason
        assert "STALE_MANIFEST_GENERATED_AT" in result.reason

    def test_structure_missing_yields_no_trade(self) -> None:
        assessment = derive_trust_state({
            "overall_status": "fail",
            "domain_alerts": [_alert("structure", "MISSING_STRUCTURE_DOMAIN", "Structure fehlt")],
        })
        result = derive_action_degradation(assessment)
        assert result.tier is ActionDegradation.NO_TRADE
        assert result.reason == "Structure fehlt"

    def test_reason_falls_back_to_state_when_cause_is_empty(self) -> None:
        assessment = TrustStateAssessment(
            state=TrustState.WATCH_ONLY,
            action_impact="no_new_entries",
            cause=TrustStateCause(domain=None, failure_type=None, code=None, description=None),
        )
        result = derive_action_degradation(assessment)
        assert result.tier is ActionDegradation.WATCHLIST
        assert result.reason  # never empty for a degraded tier
        assert "watchlist" in result.reason
        assert "watch_only" in result.reason


# ── as_dict ───────────────────────────────────────────────────────────


class TestAsDict:
    def test_as_dict_carries_three_stable_keys(self) -> None:
        assessment = derive_trust_state({
            "overall_status": "fail",
            "domain_alerts": [_alert("structure", "MISSING_STRUCTURE_DOMAIN", "Structure fehlt")],
        })
        d = derive_action_degradation(assessment).as_dict()
        assert set(d) == {"tier", "reason", "derived_from_state"}
        assert d["tier"] == "no_trade"
        assert d["derived_from_state"] == "unavailable"


# ── Pine export integration ───────────────────────────────────────────


class TestPineExport:
    def test_action_degradation_for_export_uses_attached_block(self) -> None:
        from scripts.smc_trust_state_export import action_degradation_for_export

        block = action_degradation_for_export({
            "action_degradation": {
                "tier": "watchlist",
                "reason": "Manifest stale",
                "derived_from_state": "watch_only",
            }
        })
        assert block == {
            "tier": "watchlist",
            "reason": "Manifest stale",
            "derived_from_state": "watch_only",
        }

    def test_action_degradation_for_export_rebuilds_from_trust_block(self) -> None:
        from scripts.smc_trust_state_export import action_degradation_for_export

        enr = {
            "trust_state": {
                "state": "watch_only",
                "action_impact": "no_new_entries",
                "cause": {
                    "domain": "structure",
                    "failure_type": "stale",
                    "code": "STALE_MANIFEST_GENERATED_AT",
                    "description": "Structure artifact stale > 24h",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "fail",
            }
        }
        block = action_degradation_for_export(enr)
        assert block["tier"] == "watchlist"
        assert block["derived_from_state"] == "watch_only"
        assert block["reason"] == "Structure artifact stale > 24h"

    def test_action_degradation_for_export_defaults_to_none(self) -> None:
        from scripts.smc_trust_state_export import action_degradation_for_export

        block = action_degradation_for_export({})
        assert block == {
            "tier": "none",
            "reason": "",
            "derived_from_state": "healthy",
        }

    def test_render_block_lines_emit_three_fields_in_stable_order(self) -> None:
        from scripts.smc_trust_state_export import (
            PINE_ACTION_DEGRADATION_FIELDS,
            render_action_degradation_block_lines,
        )

        lines = render_action_degradation_block_lines({})
        assert lines[0] == "// ── Action Degradation (ENG-WS2-04) ──"
        names = [
            line.split()[3] for line in lines if line.startswith("export const")
        ]
        assert names == list(PINE_ACTION_DEGRADATION_FIELDS)

    def test_render_block_lines_full_watchlist(self) -> None:
        from scripts.smc_trust_state_export import render_action_degradation_block_lines

        lines = render_action_degradation_block_lines({
            "trust_state": {
                "state": "watch_only",
                "action_impact": "no_new_entries",
                "cause": {
                    "domain": "structure",
                    "failure_type": "stale",
                    "code": "STALE_MANIFEST_GENERATED_AT",
                    "description": "Structure artifact stale > 24h",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "fail",
            }
        })
        joined = "\n".join(lines)
        assert 'ACTION_DEGRADATION_TIER = "watchlist"' in joined
        assert 'ACTION_DEGRADATION_REASON = "Structure artifact stale > 24h"' in joined
        assert 'ACTION_DEGRADATION_DERIVED_FROM = "watch_only"' in joined


# ── End-to-end Pine library emission ──────────────────────────────────


class TestPineLibraryEmission:
    def test_pine_library_emits_action_block_with_none_default(self, tmp_path: Path) -> None:
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        out = tmp_path / "lib.pine"
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment={"providers": {"provider_count": 0, "stale_providers": ""}},
        )
        text = out.read_text()
        assert "// ── Action Degradation (ENG-WS2-04) ──" in text
        assert 'export const string ACTION_DEGRADATION_TIER = "none"' in text
        assert 'export const string ACTION_DEGRADATION_REASON = ""' in text
        assert 'export const string ACTION_DEGRADATION_DERIVED_FROM = "healthy"' in text

    def test_pine_library_emits_full_action_block_for_watch_only(self, tmp_path: Path) -> None:
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        enrichment = {
            "providers": {"provider_count": 3, "stale_providers": "fmp_candles"},
            "trust_state": {
                "state": "watch_only",
                "action_impact": "no_new_entries",
                "cause": {
                    "domain": "structure",
                    "failure_type": "stale",
                    "code": "STALE_MANIFEST_GENERATED_AT",
                    "description": "Structure artifact older than 24h",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "fail",
            },
        }
        out = tmp_path / "lib.pine"
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment=enrichment,
        )
        text = out.read_text()
        assert 'export const string ACTION_DEGRADATION_TIER = "watchlist"' in text
        assert (
            'export const string ACTION_DEGRADATION_REASON = "Structure artifact older than 24h"'
            in text
        )
        assert 'export const string ACTION_DEGRADATION_DERIVED_FROM = "watch_only"' in text

    def test_pine_library_emits_no_trade_for_unavailable(self, tmp_path: Path) -> None:
        from scripts.generate_smc_micro_profiles import LISTS, write_pine_library

        enrichment = {
            "providers": {"provider_count": 1, "stale_providers": ""},
            "trust_state": {
                "state": "unavailable",
                "action_impact": "suppress_product",
                "cause": {
                    "domain": "structure",
                    "failure_type": "missing",
                    "code": "MISSING_STRUCTURE_DOMAIN",
                    "description": "Structure missing",
                },
                "contributing_alerts": [],
                "derived_from_overall_status": "fail",
            },
        }
        out = tmp_path / "lib.pine"
        write_pine_library(
            out,
            {name: [] for name in LISTS},
            asof_date="2026-04-20",
            universe_size=0,
            enrichment=enrichment,
        )
        text = out.read_text()
        assert 'export const string ACTION_DEGRADATION_TIER = "no_trade"' in text
        assert 'export const string ACTION_DEGRADATION_REASON = "Structure missing"' in text
        assert 'export const string ACTION_DEGRADATION_DERIVED_FROM = "unavailable"' in text
