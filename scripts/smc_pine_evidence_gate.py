"""Pine Evidence Lane gate (WS1-FT-03).

Realises the read-only evidence hook for ticket ``WS1-FT-03`` from
``docs/smc_deep_review_2026-04-20_pine_evidence_first_ticketset.md``.

For every scenario in the WS1-FT-01 catalog this module:

1. builds a deterministic enrichment fixture (``WS1-FT-02``),
2. runs it through ``scripts.smc_hero_state.build_hero_state``,
3. compares the realised Hero State against the catalog's expected fields
   and degradation reason.

A semantic drift between the catalog and the live Hero State Contract
fails the gate, so an accidental change in ``smc_hero_state`` semantics
that breaks a canonical Pine decision-case blocks the structural release
pass.

The check is in-process, deterministic and free of I/O — it only depends
on the three modules already pinned by tests in this slice.
"""
from __future__ import annotations

from typing import Any, Mapping

from scripts.smc_hero_state import build_hero_state
from scripts.smc_pine_evidence_fixtures import build_evidence_fixture
from scripts.smc_pine_scenario_catalog import PINE_SCENARIO_CATALOG, PineScenario


_HERO_RISK_FIELD = "HERO_RISK"


def _expected_for(scenario: PineScenario) -> dict[str, str]:
    """Catalog-side expected Hero fields for a scenario."""
    return {
        "HERO_MARKET_MODE": scenario.expected_market_mode,
        "HERO_BIAS": scenario.expected_bias,
        "HERO_TRUST": scenario.expected_trust,
        "HERO_SETUP_QUALITY": scenario.expected_setup_quality,
        "HERO_ACTION": scenario.expected_action,
        # Mirrors the visible degradation rule from the catalog: ACTIVE
        # scenarios must surface no risk; non-ACTIVE scenarios must surface
        # the catalog's degradation_reason.
        _HERO_RISK_FIELD: scenario.degradation_reason,
    }


def _diff_fields(
    expected: Mapping[str, str], observed: Mapping[str, str]
) -> list[dict[str, str]]:
    """Return one entry per drifted field in stable key order."""
    drifts: list[dict[str, str]] = []
    for field in (
        "HERO_MARKET_MODE",
        "HERO_BIAS",
        "HERO_TRUST",
        "HERO_SETUP_QUALITY",
        "HERO_ACTION",
        _HERO_RISK_FIELD,
    ):
        exp = expected[field]
        obs = str(observed.get(field, ""))
        if exp != obs:
            drifts.append({"field": field, "expected": exp, "observed": obs})
    return drifts


def _evaluate_scenario(scenario: PineScenario) -> dict[str, Any]:
    """Build the per-scenario evidence row."""
    fixture = build_evidence_fixture(scenario.scenario_id)
    hero = build_hero_state(fixture)
    expected = _expected_for(scenario)
    drifts = _diff_fields(expected, hero)
    return {
        "scenario_id": scenario.scenario_id,
        "name": scenario.name,
        "status": "ok" if not drifts else "fail",
        "expected_action": scenario.expected_action,
        "observed_action": str(hero.get("HERO_ACTION", "")),
        "drifts": drifts,
    }


def build_evidence_lane_gate() -> dict[str, Any]:
    """Build the ``evidence_lane`` gate dict in the same shape as other gates.

    Returns a dict with at least ``name``, ``status``, ``blocking`` and
    ``details``. ``details`` carries:

    - ``scenarios_checked``: number of catalog scenarios evaluated,
    - ``scenarios_passed``: number with no drift,
    - ``scenarios_failed``: number with at least one drift,
    - ``failures``: per-failed-scenario rows with drift details,
    - ``scenario_results``: full per-scenario rows (in catalog order).
    """
    rows = [_evaluate_scenario(scenario) for scenario in PINE_SCENARIO_CATALOG]
    failed = [row for row in rows if row["status"] == "fail"]

    failures: list[dict[str, Any]] = [
        {
            "code": "PINE_EVIDENCE_DRIFT",
            "scenario_id": row["scenario_id"],
            "name": row["name"],
            "drifts": row["drifts"],
        }
        for row in failed
    ]

    status = "ok" if not failed else "fail"
    return {
        "name": "evidence_lane",
        "status": status,
        "blocking": True,
        "details": {
            "scenarios_checked": len(rows),
            "scenarios_passed": len(rows) - len(failed),
            "scenarios_failed": len(failed),
            "failures": failures,
            "scenario_results": rows,
        },
    }


__all__ = ["build_evidence_lane_gate"]
