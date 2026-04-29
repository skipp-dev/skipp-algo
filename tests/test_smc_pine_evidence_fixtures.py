"""Tests for the deterministic evidence fixtures (WS1-FT-02).

These tests pin three things:

1. Determinism — the same scenario_id always produces an equal fixture and
   fixtures do not leak mutation across calls.
2. Catalog parity — running each fixture through ``build_hero_state``
   reproduces the catalog's expected hero fields and degradation reason.
3. Coverage — every catalog scenario has a registered fixture.
"""
from __future__ import annotations

import pytest

from scripts.smc_hero_state import build_hero_state
from scripts.smc_pine_evidence_fixtures import (
    build_evidence_fixture,
    list_evidence_fixtures,
)
from scripts.smc_pine_scenario_catalog import PINE_SCENARIO_CATALOG

_SCENARIO_IDS = [s.scenario_id for s in PINE_SCENARIO_CATALOG]


class TestFixtureCoverage:
    def test_every_catalog_scenario_has_a_fixture(self) -> None:
        for scenario_id in _SCENARIO_IDS:
            fixture = build_evidence_fixture(scenario_id)
            assert isinstance(fixture, dict)
            assert fixture, f"fixture for {scenario_id} must not be empty"

    def test_list_fixtures_pairs_in_catalog_order(self) -> None:
        pairs = list_evidence_fixtures()
        assert tuple(scenario_id for scenario_id, _ in pairs) == tuple(_SCENARIO_IDS)

    def test_unknown_scenario_id_raises(self) -> None:
        with pytest.raises(KeyError):
            build_evidence_fixture("ws1_does_not_exist")


class TestFixtureDeterminism:
    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_same_id_returns_equal_dicts(self, scenario_id: str) -> None:
        first = build_evidence_fixture(scenario_id)
        second = build_evidence_fixture(scenario_id)
        assert first == second

    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_calls_return_independent_objects(self, scenario_id: str) -> None:
        first = build_evidence_fixture(scenario_id)
        second = build_evidence_fixture(scenario_id)
        first["regime"]["regime"] = "MUTATED"
        assert second["regime"]["regime"] != "MUTATED"


class TestCatalogParity:
    """Each fixture must round-trip back to the catalog's expected Hero State."""

    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_market_mode_matches_catalog(self, scenario_id: str) -> None:
        scenario = next(s for s in PINE_SCENARIO_CATALOG if s.scenario_id == scenario_id)
        hero = build_hero_state(build_evidence_fixture(scenario_id))
        assert hero["HERO_MARKET_MODE"] == scenario.expected_market_mode

    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_bias_matches_catalog(self, scenario_id: str) -> None:
        scenario = next(s for s in PINE_SCENARIO_CATALOG if s.scenario_id == scenario_id)
        hero = build_hero_state(build_evidence_fixture(scenario_id))
        assert hero["HERO_BIAS"] == scenario.expected_bias

    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_trust_matches_catalog(self, scenario_id: str) -> None:
        scenario = next(s for s in PINE_SCENARIO_CATALOG if s.scenario_id == scenario_id)
        hero = build_hero_state(build_evidence_fixture(scenario_id))
        assert hero["HERO_TRUST"] == scenario.expected_trust

    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_setup_quality_matches_catalog(self, scenario_id: str) -> None:
        scenario = next(s for s in PINE_SCENARIO_CATALOG if s.scenario_id == scenario_id)
        hero = build_hero_state(build_evidence_fixture(scenario_id))
        assert hero["HERO_SETUP_QUALITY"] == scenario.expected_setup_quality

    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_action_matches_catalog(self, scenario_id: str) -> None:
        scenario = next(s for s in PINE_SCENARIO_CATALOG if s.scenario_id == scenario_id)
        hero = build_hero_state(build_evidence_fixture(scenario_id))
        assert hero["HERO_ACTION"] == scenario.expected_action

    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_degradation_reason_matches_catalog(self, scenario_id: str) -> None:
        scenario = next(s for s in PINE_SCENARIO_CATALOG if s.scenario_id == scenario_id)
        hero = build_hero_state(build_evidence_fixture(scenario_id))
        if scenario.degradation_reason:
            # Non-ACTIVE scenarios: the catalog's degradation_reason must
            # appear as the visible HERO_RISK so the dashboard explains why.
            assert hero["HERO_RISK"] == scenario.degradation_reason
        else:
            # ACTIVE scenarios must not surface a risk reason.
            assert hero["HERO_RISK"] == ""
