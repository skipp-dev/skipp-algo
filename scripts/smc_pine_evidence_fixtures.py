"""Deterministic enrichment fixtures for the Pine Scenario Catalog (WS1-FT-02).

This module is the read-only fixture slice for ticket ``WS1-FT-02`` from
``docs/smc_deep_review_2026-04-20_pine_evidence_first_ticketset.md``.

For every scenario in ``scripts/smc_pine_scenario_catalog.PINE_SCENARIO_CATALOG``
this module produces a deterministic enrichment dict that, when fed through
``scripts.smc_hero_state.build_hero_state``, yields exactly the Hero State
the catalog declares as expected for that scenario.

The fixtures are intentionally minimal: they only populate the enrichment
sub-blocks that ``build_hero_state`` actually consumes. They are not meant
to be a full enrichment payload, only a stable "shape of the world" that
realises one canonical decision-case per scenario.

Goals
-----
1. Determinism — calling :func:`build_evidence_fixture` twice with the same
   ``scenario_id`` returns equal dicts.
2. Catalog parity — running the fixture through :func:`build_hero_state`
   reproduces the catalog's expected hero fields and degradation reason.
3. Read-only — no I/O, no clock, no environment lookups.

This slice does not introduce any gate logic or report change. It only
creates the deterministic mapping that ``WS1-FT-03`` will consume to compare
hero output against the catalog inside the release-gates.
"""
from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any, Mapping

from scripts.smc_pine_scenario_catalog import (
    PINE_SCENARIO_CATALOG,
    get_pine_scenario,
)


def _bullish_active_fixture(setup_quality: str) -> dict[str, Any]:
    """Healthy bullish setup with selectable signal_quality tier."""
    return {
        "regime": {"regime": "BULLISH"},
        "layering": {"trade_state": "ALLOWED"},
        "providers": {"stale_providers": ""},
        "signal_quality": {
            "SIGNAL_FRESHNESS": "fresh",
            "SIGNAL_QUALITY_TIER": setup_quality,
        },
        "ensemble_quality": {"tier": "good"},
        "calendar": {
            "high_impact_macro_today": False,
            "macro_event_name": "",
        },
        "zone_priority": {
            "ZONE_PRIORITY_CATALYST": "",
            "ZONE_PRIORITY_REASON": "",
        },
        "event_risk": {"EVENT_RISK_LEVEL": "NONE"},
        "volatility_regime": {"label": "NORMAL"},
    }


def _stale_context_fixture() -> dict[str, Any]:
    """Otherwise-valid bullish setup with stale signal freshness."""
    return {
        "regime": {"regime": "BULLISH"},
        "layering": {"trade_state": "ALLOWED"},
        "providers": {"stale_providers": ""},
        "signal_quality": {
            "SIGNAL_FRESHNESS": "stale",
            "SIGNAL_QUALITY_TIER": "ok",
        },
        "ensemble_quality": {"tier": "good"},
        "calendar": {
            "high_impact_macro_today": False,
            "macro_event_name": "",
        },
        "zone_priority": {
            "ZONE_PRIORITY_CATALYST": "",
            "ZONE_PRIORITY_REASON": "",
        },
        "event_risk": {"EVENT_RISK_LEVEL": "NONE"},
        "volatility_regime": {"label": "NORMAL"},
    }


def _blocked_no_trade_fixture() -> dict[str, Any]:
    """Healthy data, but layering blocks the trade because of an event."""
    return {
        "regime": {"regime": "NEUTRAL"},
        "layering": {"trade_state": "BLOCKED"},
        "providers": {"stale_providers": ""},
        "signal_quality": {
            "SIGNAL_FRESHNESS": "fresh",
            "SIGNAL_QUALITY_TIER": "ok",
        },
        "ensemble_quality": {"tier": "good"},
        "calendar": {
            "high_impact_macro_today": True,
            "macro_event_name": "FOMC Rate Decision",
        },
        "zone_priority": {
            "ZONE_PRIORITY_CATALYST": "",
            "ZONE_PRIORITY_REASON": "",
        },
        "event_risk": {"EVENT_RISK_LEVEL": "HIGH"},
        "volatility_regime": {"label": "NORMAL"},
    }


_FIXTURE_BUILDERS: Mapping[str, Any] = MappingProxyType(
    {
        "ws1_bos_bullish_continuation": lambda: _bullish_active_fixture("high"),
        "ws1_choch_reclaim_long": lambda: _bullish_active_fixture("good"),
        "ws1_ob_reclaim_valid_trigger": lambda: _bullish_active_fixture("good"),
        "ws1_fvg_fill_actionable": lambda: _bullish_active_fixture("ok"),
        "ws1_stale_context_watch": _stale_context_fixture,
        "ws1_blocked_no_trade": _blocked_no_trade_fixture,
    }
)


def build_evidence_fixture(scenario_id: str) -> dict[str, Any]:
    """Build a deterministic enrichment fixture for ``scenario_id``.

    The returned dict is freshly constructed (deep-copied) on every call so
    callers can mutate it freely without leaking state into the next call.

    Raises
    ------
    KeyError
        When ``scenario_id`` is not part of the canonical catalog.
    """
    # Guard ID against catalog up-front so callers see a consistent error.
    get_pine_scenario(scenario_id)
    try:
        builder = _FIXTURE_BUILDERS[scenario_id]
    except KeyError as exc:  # pragma: no cover - defensive parity check
        raise KeyError(
            f"no evidence fixture registered for scenario_id={scenario_id!r}"
        ) from exc
    return deepcopy(builder())


def list_evidence_fixtures() -> tuple[tuple[str, dict[str, Any]], ...]:
    """Return ``(scenario_id, fixture)`` pairs for the full catalog."""
    return tuple(
        (scenario.scenario_id, build_evidence_fixture(scenario.scenario_id))
        for scenario in PINE_SCENARIO_CATALOG
    )


__all__ = [
    "build_evidence_fixture",
    "list_evidence_fixtures",
]
