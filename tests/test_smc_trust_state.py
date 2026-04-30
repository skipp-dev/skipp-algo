"""Tests for the unified Trust-State model (ENG-WS2-01)."""
from __future__ import annotations

import pytest

from smc_integration.trust_state import (
    ACTION_IMPACT_ADVISORY_ONLY,
    ACTION_IMPACT_NO_NEW_ENTRIES,
    ACTION_IMPACT_NONE,
    ACTION_IMPACT_SUPPRESS_PRODUCT,
    TrustState,
    all_trust_states,
    derive_trust_state,
    state_action_impact,
)

# ── State vocabulary ──────────────────────────────────────────────────


class TestVocabulary:
    def test_all_five_canonical_states_exist(self) -> None:
        names = {s.name for s in TrustState}
        assert names == {
            "HEALTHY",
            "DEGRADED",
            "STALE",
            "WATCH_ONLY",
            "UNAVAILABLE",
        }

    def test_severity_order_is_stable_and_complete(self) -> None:
        order = list(all_trust_states())
        assert order == [
            TrustState.HEALTHY,
            TrustState.DEGRADED,
            TrustState.STALE,
            TrustState.WATCH_ONLY,
            TrustState.UNAVAILABLE,
        ]

    @pytest.mark.parametrize(
        "state,impact",
        [
            (TrustState.HEALTHY, ACTION_IMPACT_NONE),
            (TrustState.DEGRADED, ACTION_IMPACT_ADVISORY_ONLY),
            (TrustState.STALE, ACTION_IMPACT_ADVISORY_ONLY),
            (TrustState.WATCH_ONLY, ACTION_IMPACT_NO_NEW_ENTRIES),
            (TrustState.UNAVAILABLE, ACTION_IMPACT_SUPPRESS_PRODUCT),
        ],
    )
    def test_state_action_impact_table(self, state: TrustState, impact: str) -> None:
        assert state_action_impact(state) == impact


# ── Derivation ────────────────────────────────────────────────────────


def _alert(domain: str, code: str, message: str = "") -> dict[str, object]:
    return {"domain": domain, "code": code, "message": message}


class TestDerivation:
    def test_empty_report_is_healthy(self) -> None:
        assessment = derive_trust_state({})
        assert assessment.state is TrustState.HEALTHY
        assert assessment.action_impact == ACTION_IMPACT_NONE
        assert assessment.cause.domain is None
        assert assessment.cause.code is None
        assert assessment.contributing_alerts == ()

    def test_ok_report_with_no_alerts_is_healthy(self) -> None:
        assessment = derive_trust_state(
            {"overall_status": "ok", "domain_alerts": []}
        )
        assert assessment.state is TrustState.HEALTHY
        assert assessment.derived_from_overall_status == "ok"

    def test_advisory_only_volume_stale_yields_stale(self) -> None:
        # Volume stale = ADVISORY + stale → STALE bucket.
        report = {
            "overall_status": "warn",
            "domain_alerts": [_alert("volume", "STALE_META_VOLUME_DOMAIN")],
        }
        assessment = derive_trust_state(report)
        assert assessment.state is TrustState.STALE
        assert assessment.action_impact == ACTION_IMPACT_ADVISORY_ONLY
        assert assessment.cause.domain == "volume"
        assert assessment.cause.failure_type == "stale"
        assert assessment.cause.code == "STALE_META_VOLUME_DOMAIN"

    def test_news_missing_fallback_keeps_healthy(self) -> None:
        # news/missing maps to FALLBACK semantics → HEALTHY (no degradation).
        report = {
            "overall_status": "ok",
            "domain_alerts": [_alert("news", "MISSING_NEWS_DOMAIN")],
        }
        assessment = derive_trust_state(report)
        assert assessment.state is TrustState.HEALTHY

    def test_structure_stale_yields_watch_only(self) -> None:
        # structure/stale maps to SUPPRESS → WATCH_ONLY (no new entries).
        report = {
            "overall_status": "fail",
            "domain_alerts": [_alert("structure", "STALE_MANIFEST_GENERATED_AT")],
        }
        assessment = derive_trust_state(report)
        assert assessment.state is TrustState.WATCH_ONLY
        assert assessment.action_impact == ACTION_IMPACT_NO_NEW_ENTRIES
        assert assessment.cause.domain == "structure"
        assert assessment.cause.failure_type == "stale"

    def test_structure_missing_yields_unavailable(self) -> None:
        # structure/missing → HARD_DEGRADE → UNAVAILABLE.
        report = {
            "overall_status": "fail",
            "domain_alerts": [_alert("structure", "MISSING_STRUCTURE_DOMAIN")],
        }
        assessment = derive_trust_state(report)
        assert assessment.state is TrustState.UNAVAILABLE
        assert assessment.action_impact == ACTION_IMPACT_SUPPRESS_PRODUCT
        assert assessment.cause.domain == "structure"

    def test_worst_state_wins_when_multiple_alerts_present(self) -> None:
        report = {
            "overall_status": "fail",
            "domain_alerts": [
                _alert("volume", "STALE_META_VOLUME_DOMAIN"),       # → STALE
                _alert("structure", "STALE_MANIFEST_FILE_MTIME"),  # → WATCH_ONLY
                _alert("news", "STALE_META_NEWS_DOMAIN"),          # → STALE
            ],
        }
        assessment = derive_trust_state(report)
        assert assessment.state is TrustState.WATCH_ONLY
        # Cause must match the chosen state, not the first alert.
        assert assessment.cause.domain == "structure"
        assert assessment.cause.failure_type == "stale"

    def test_overall_status_fail_without_alerts_is_unavailable(self) -> None:
        # Defensive path: report claims fail but lists no alerts.
        report = {"overall_status": "fail", "domain_alerts": []}
        assessment = derive_trust_state(report)
        assert assessment.state is TrustState.UNAVAILABLE
        assert assessment.cause.code == "FAIL"
        assert assessment.derived_from_overall_status == "fail"

    def test_already_classified_alerts_are_not_reclassified(self) -> None:
        # If the caller already enriched the alerts, we must accept the
        # provided failure_action verbatim (idempotency).
        pre_classified = {
            "domain": "structure",
            "code": "INVALID_STRUCTURE",
            "failure_action": "hard_degrade",
            "failure_affects_entry": True,
            "failure_max_tolerable_hours": None,
        }
        assessment = derive_trust_state(
            {"overall_status": "fail", "domain_alerts": [pre_classified]}
        )
        assert assessment.state is TrustState.UNAVAILABLE
        assert assessment.contributing_alerts and assessment.contributing_alerts[0]["failure_action"] == "hard_degrade"

    def test_cause_and_effect_are_separate_fields(self) -> None:
        report = {
            "overall_status": "warn",
            "domain_alerts": [_alert("volume", "STALE_META_VOLUME_DOMAIN", "Volume älter als 12h")],
        }
        assessment = derive_trust_state(report)
        # cause = WHY (domain/code/description), effect = WHAT NEXT (action_impact).
        assert assessment.cause.description == "Volume älter als 12h"
        assert assessment.action_impact == ACTION_IMPACT_ADVISORY_ONLY
        # The two surfaces must not collapse into one string.
        assert isinstance(assessment.cause.code, str)
        assert assessment.action_impact != assessment.cause.code


# ── JSON projection ───────────────────────────────────────────────────


class TestAsDict:
    def test_as_dict_is_deterministic_and_complete(self) -> None:
        report = {
            "overall_status": "fail",
            "domain_alerts": [_alert("structure", "STALE_MANIFEST_GENERATED_AT")],
        }
        d = derive_trust_state(report).as_dict()
        assert set(d) == {
            "state",
            "action_impact",
            "cause",
            "contributing_alerts",
            "derived_from_overall_status",
        }
        assert d["state"] == "watch_only"
        assert d["action_impact"] == ACTION_IMPACT_NO_NEW_ENTRIES
        assert d["cause"]["domain"] == "structure"
        assert d["derived_from_overall_status"] == "fail"

    def test_as_dict_for_healthy_has_none_cause(self) -> None:
        d = derive_trust_state({}).as_dict()
        assert d["state"] == "healthy"
        assert d["cause"] == {
            "domain": None,
            "failure_type": None,
            "code": None,
            "description": None,
        }
        assert d["contributing_alerts"] == []
