"""Pine Evidence Lane gate (WS1-FT-03 + WS1-FT-05).

Realises the read-only evidence hook for ticket ``WS1-FT-03`` from
``docs/smc_deep_review_2026-04-20_pine_evidence_first_ticketset.md``,
extended by ``WS1-FT-05`` (Evidence Failure Reporting):

For every scenario in the WS1-FT-01 catalog this module:

1. resolves a deterministic enrichment fixture (``WS1-FT-02``),
2. runs it through ``scripts.smc_hero_state.build_hero_state``,
3. compares the realised Hero State against the catalog's expected fields
   and degradation reason.

Failures are explicitly classified into three drift types so an operator
does not need to read raw CI logs to triage:

- ``missing_artifact``  — no fixture builder is registered for the
  scenario (catalog/fixture mapping out of sync),
- ``stale_manifest``    — fixture exists but the enrichment shape it
  returns is missing the keys the Hero State Contract requires,
- ``semantic_drift``    — fixture builds and runs, but the Hero State
  output drifts from the catalog's expected fields.

Every failure carries a ``primary_blocker`` string (a single concise,
human-readable reason) and the gate aggregates per-bucket scenario IDs
in ``details.failure_buckets`` for fast operator triage.

The check is in-process, deterministic and free of I/O.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scripts.smc_hero_state import build_hero_state
from scripts.smc_pine_evidence_fixtures import build_evidence_fixture
from scripts.smc_pine_scenario_catalog import PINE_SCENARIO_CATALOG, PineScenario

_HERO_RISK_FIELD = "HERO_RISK"

# Required top-level enrichment keys the Hero State Contract consumes. A
# fixture that omits any of these is treated as a stale-manifest failure
# rather than a semantic drift, because the missing key prevents the
# semantic check from being meaningful.
_REQUIRED_FIXTURE_KEYS: tuple[str, ...] = (
    "regime",
    "layering",
    "providers",
    "signal_quality",
)

# Drift-type vocabulary surfaced in ``details.failure_buckets`` and on each
# failure row's ``drift_type`` field.
DRIFT_TYPE_MISSING_ARTIFACT = "missing_artifact"
DRIFT_TYPE_STALE_MANIFEST = "stale_manifest"
DRIFT_TYPE_SEMANTIC_DRIFT = "semantic_drift"

DRIFT_TYPES: tuple[str, ...] = (
    DRIFT_TYPE_MISSING_ARTIFACT,
    DRIFT_TYPE_STALE_MANIFEST,
    DRIFT_TYPE_SEMANTIC_DRIFT,
)


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


def _missing_fixture_keys(fixture: Mapping[str, Any]) -> list[str]:
    """Return required top-level enrichment keys absent from the fixture."""
    return [key for key in _REQUIRED_FIXTURE_KEYS if key not in fixture]


def _evaluate_scenario(scenario: PineScenario) -> dict[str, Any]:
    """Build the per-scenario evidence row, classified by drift type."""
    # 1) missing_artifact — fixture builder not registered.
    try:
        fixture = build_evidence_fixture(scenario.scenario_id)
    except KeyError as exc:
        return {
            "scenario_id": scenario.scenario_id,
            "name": scenario.name,
            "status": "fail",
            "drift_type": DRIFT_TYPE_MISSING_ARTIFACT,
            "primary_blocker": f"missing fixture for scenario {scenario.scenario_id!r}",
            "expected_action": scenario.expected_action,
            "observed_action": "",
            "drifts": [],
            "missing_keys": [],
            "exception": str(exc),
        }

    # 2) stale_manifest — fixture present but missing required keys.
    missing_keys = _missing_fixture_keys(fixture)
    if missing_keys:
        return {
            "scenario_id": scenario.scenario_id,
            "name": scenario.name,
            "status": "fail",
            "drift_type": DRIFT_TYPE_STALE_MANIFEST,
            "primary_blocker": (
                f"fixture missing required key {missing_keys[0]!r}"
            ),
            "expected_action": scenario.expected_action,
            "observed_action": "",
            "drifts": [],
            "missing_keys": missing_keys,
        }

    # 3) semantic_drift (or pass).
    hero = build_hero_state(fixture)
    expected = _expected_for(scenario)
    drifts = _diff_fields(expected, hero)
    if drifts:
        first = drifts[0]
        primary = (
            f"{first['field']} expected {first['expected']!r} "
            f"observed {first['observed']!r}"
        )
        return {
            "scenario_id": scenario.scenario_id,
            "name": scenario.name,
            "status": "fail",
            "drift_type": DRIFT_TYPE_SEMANTIC_DRIFT,
            "primary_blocker": primary,
            "expected_action": scenario.expected_action,
            "observed_action": str(hero.get("HERO_ACTION", "")),
            "drifts": drifts,
            "missing_keys": [],
        }

    return {
        "scenario_id": scenario.scenario_id,
        "name": scenario.name,
        "status": "ok",
        "drift_type": None,
        "primary_blocker": None,
        "expected_action": scenario.expected_action,
        "observed_action": str(hero.get("HERO_ACTION", "")),
        "drifts": [],
        "missing_keys": [],
    }


def _build_failure_buckets(
    failed_rows: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Group failed scenario IDs by drift type, in stable order."""
    buckets: dict[str, list[str]] = {drift: [] for drift in DRIFT_TYPES}
    for row in failed_rows:
        drift = row.get("drift_type")
        if drift in buckets:
            buckets[drift].append(row["scenario_id"])
    return buckets


def build_evidence_lane_gate() -> dict[str, Any]:
    """Build the ``evidence_lane`` gate dict in the same shape as other gates.

    Returns a dict with at least ``name``, ``status``, ``blocking`` and
    ``details``. ``details`` carries:

    - ``scenarios_checked``: number of catalog scenarios evaluated,
    - ``scenarios_passed``: number with no drift,
    - ``scenarios_failed``: number with at least one drift,
    - ``failures``: per-failed-scenario rows including ``drift_type`` and
      ``primary_blocker`` (WS1-FT-05),
    - ``failure_buckets``: scenario IDs grouped by drift type
      (``missing_artifact``, ``stale_manifest``, ``semantic_drift``)
      so an operator can read missing-evidence vs. semantic drift at a
      glance,
    - ``primary_blockers``: ordered list of ``{scenario_id, drift_type,
      primary_blocker}`` rows for fast triage,
    - ``scenario_results``: full per-scenario rows (in catalog order).
    """
    rows = [_evaluate_scenario(scenario) for scenario in PINE_SCENARIO_CATALOG]
    failed = [row for row in rows if row["status"] == "fail"]

    failures: list[dict[str, Any]] = [
        {
            "code": "PINE_EVIDENCE_DRIFT",
            "scenario_id": row["scenario_id"],
            "name": row["name"],
            "drift_type": row["drift_type"],
            "primary_blocker": row["primary_blocker"],
            "drifts": row["drifts"],
            "missing_keys": row["missing_keys"],
        }
        for row in failed
    ]

    primary_blockers = [
        {
            "scenario_id": row["scenario_id"],
            "drift_type": row["drift_type"],
            "primary_blocker": row["primary_blocker"],
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
            "failure_buckets": _build_failure_buckets(failed),
            "primary_blockers": primary_blockers,
            "scenario_results": rows,
        },
    }


__all__ = [
    "DRIFT_TYPES",
    "DRIFT_TYPE_MISSING_ARTIFACT",
    "DRIFT_TYPE_SEMANTIC_DRIFT",
    "DRIFT_TYPE_STALE_MANIFEST",
    "build_evidence_lane_gate",
]
