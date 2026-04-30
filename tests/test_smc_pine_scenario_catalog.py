"""Tests for the Pine Scenario Catalog (WS1-FT-01).

These tests pin the read-only contract introduced by
``scripts/smc_pine_scenario_catalog.py``. They guard:

- the canonical scenario list (count + ids + delivery order),
- per-field vocabulary alignment with the Hero State Contract,
- the invariant that every non-ACTIVE action carries a visible degradation
  reason and ACTIVE actions never do,
- and the lookup helpers.
"""
from __future__ import annotations

import pytest

from scripts.smc_hero_state import build_hero_state
from scripts.smc_pine_scenario_catalog import (
    PINE_SCENARIO_CATALOG,
    PineScenario,
    get_pine_scenario,
    list_pine_scenarios,
)

_EXPECTED_IDS_IN_ORDER: tuple[str, ...] = (
    "ws1_bos_bullish_continuation",
    "ws1_choch_reclaim_long",
    "ws1_ob_reclaim_valid_trigger",
    "ws1_fvg_fill_actionable",
    "ws1_stale_context_watch",
    "ws1_blocked_no_trade",
)


_HERO_MARKET_MODES = {"BULLISH", "BEARISH", "NEUTRAL", "RISK_OFF"}
_HERO_BIASES = {"LONG", "SHORT", "FLAT"}
_HERO_TRUST = {"healthy", "warmup", "degraded", "stale", "unavailable"}
_HERO_QUALITIES = {"high", "good", "ok", "low"}
_HERO_ACTIONS = {"ACTIVE", "WATCH", "AVOID", "BLOCKED"}


class TestCatalogShape:
    def test_catalog_has_all_six_canonical_scenarios(self) -> None:
        assert len(PINE_SCENARIO_CATALOG) == 6

    def test_catalog_ids_in_delivery_order(self) -> None:
        assert tuple(s.scenario_id for s in PINE_SCENARIO_CATALOG) == _EXPECTED_IDS_IN_ORDER

    def test_list_helper_returns_same_tuple_as_constant(self) -> None:
        assert list_pine_scenarios() is PINE_SCENARIO_CATALOG

    def test_scenarios_are_immutable(self) -> None:
        scenario = PINE_SCENARIO_CATALOG[0]
        with pytest.raises(AttributeError):
            scenario.expected_action = "WATCH"  # type: ignore[misc]


class TestCatalogVocabulary:
    @pytest.mark.parametrize("scenario", PINE_SCENARIO_CATALOG, ids=lambda s: s.scenario_id)
    def test_market_mode_in_hero_vocabulary(self, scenario: PineScenario) -> None:
        assert scenario.expected_market_mode in _HERO_MARKET_MODES

    @pytest.mark.parametrize("scenario", PINE_SCENARIO_CATALOG, ids=lambda s: s.scenario_id)
    def test_bias_in_hero_vocabulary(self, scenario: PineScenario) -> None:
        assert scenario.expected_bias in _HERO_BIASES

    @pytest.mark.parametrize("scenario", PINE_SCENARIO_CATALOG, ids=lambda s: s.scenario_id)
    def test_trust_in_hero_vocabulary(self, scenario: PineScenario) -> None:
        assert scenario.expected_trust in _HERO_TRUST

    @pytest.mark.parametrize("scenario", PINE_SCENARIO_CATALOG, ids=lambda s: s.scenario_id)
    def test_setup_quality_in_hero_vocabulary(self, scenario: PineScenario) -> None:
        assert scenario.expected_setup_quality in _HERO_QUALITIES

    @pytest.mark.parametrize("scenario", PINE_SCENARIO_CATALOG, ids=lambda s: s.scenario_id)
    def test_action_in_hero_vocabulary(self, scenario: PineScenario) -> None:
        assert scenario.expected_action in _HERO_ACTIONS


class TestDegradationInvariant:
    @pytest.mark.parametrize("scenario", PINE_SCENARIO_CATALOG, ids=lambda s: s.scenario_id)
    def test_active_has_no_degradation(self, scenario: PineScenario) -> None:
        if scenario.expected_action == "ACTIVE":
            assert scenario.degradation_reason == ""

    @pytest.mark.parametrize("scenario", PINE_SCENARIO_CATALOG, ids=lambda s: s.scenario_id)
    def test_non_active_carries_visible_reason(self, scenario: PineScenario) -> None:
        if scenario.expected_action != "ACTIVE":
            assert scenario.degradation_reason != ""


class TestProductCoverage:
    """Pin that the catalog covers the six product cases listed in
    ``docs/smc_deep_review_2026-04-20_pine_evidence_first_ticketset.md``.
    """

    def test_includes_bos(self) -> None:
        assert any("bos" in s.scenario_id for s in PINE_SCENARIO_CATALOG)

    def test_includes_choch(self) -> None:
        assert any("choch" in s.scenario_id for s in PINE_SCENARIO_CATALOG)

    def test_includes_ob_reclaim(self) -> None:
        assert any("ob_reclaim" in s.scenario_id for s in PINE_SCENARIO_CATALOG)

    def test_includes_fvg_fill(self) -> None:
        assert any("fvg_fill" in s.scenario_id for s in PINE_SCENARIO_CATALOG)

    def test_includes_stale_context(self) -> None:
        stale = [s for s in PINE_SCENARIO_CATALOG if s.expected_trust == "stale"]
        assert stale, "expected at least one stale-context scenario"
        assert all(s.expected_action != "ACTIVE" for s in stale)

    def test_includes_blocked_no_trade(self) -> None:
        blocked = [s for s in PINE_SCENARIO_CATALOG if s.expected_action == "BLOCKED"]
        assert blocked, "expected at least one BLOCKED scenario"


class TestLookupHelper:
    def test_get_returns_known_scenario(self) -> None:
        scenario = get_pine_scenario("ws1_bos_bullish_continuation")
        assert scenario.expected_action == "ACTIVE"
        assert scenario.expected_market_mode == "BULLISH"

    def test_get_raises_on_unknown_id(self) -> None:
        with pytest.raises(KeyError) as info:
            get_pine_scenario("ws1_does_not_exist")
        assert "ws1_does_not_exist" in str(info.value)


class TestConstructorValidation:
    def test_invalid_market_mode_rejected(self) -> None:
        with pytest.raises(ValueError):
            PineScenario(
                scenario_id="x",
                name="x",
                inputs_summary="x",
                expected_market_mode="SIDEWAYS",
                expected_bias="LONG",
                expected_trust="healthy",
                expected_setup_quality="good",
                expected_action="ACTIVE",
                degradation_reason="",
            )

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(ValueError):
            PineScenario(
                scenario_id="x",
                name="x",
                inputs_summary="x",
                expected_market_mode="BULLISH",
                expected_bias="LONG",
                expected_trust="healthy",
                expected_setup_quality="good",
                expected_action="HOLD",
                degradation_reason="",
            )

    def test_active_with_degradation_rejected(self) -> None:
        with pytest.raises(ValueError):
            PineScenario(
                scenario_id="x",
                name="x",
                inputs_summary="x",
                expected_market_mode="BULLISH",
                expected_bias="LONG",
                expected_trust="healthy",
                expected_setup_quality="good",
                expected_action="ACTIVE",
                degradation_reason="DATA_STALE",
            )

    def test_non_active_without_degradation_rejected(self) -> None:
        with pytest.raises(ValueError):
            PineScenario(
                scenario_id="x",
                name="x",
                inputs_summary="x",
                expected_market_mode="BULLISH",
                expected_bias="LONG",
                expected_trust="stale",
                expected_setup_quality="ok",
                expected_action="WATCH",
                degradation_reason="",
            )


class TestHeroVocabularyParity:
    """The catalog contract must align with the live Hero State Contract.

    Building Hero State on an empty enrichment must not produce values outside
    the catalog's vocabulary; this guards against silent drift between the
    catalog and ``scripts/smc_hero_state.py``.
    """

    def test_hero_state_values_are_within_catalog_vocabulary(self) -> None:
        hero = build_hero_state({})
        assert hero["HERO_MARKET_MODE"] in _HERO_MARKET_MODES
        assert hero["HERO_BIAS"] in _HERO_BIASES
        assert hero["HERO_TRUST"] in _HERO_TRUST
        assert hero["HERO_SETUP_QUALITY"] in _HERO_QUALITIES
        assert hero["HERO_ACTION"] in _HERO_ACTIONS
