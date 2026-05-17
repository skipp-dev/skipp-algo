"""Hero Surface input map invariant test (PR 3 of 2026-04-20 deep-review).

Validates that ``spec/hero_surface_input_map.json`` matches the actual input
surface in ``SMC_Dashboard.pine`` and ``SMC_Mobile_Dashboard.pine``:

* Every input declared as a "Surface" / "Mobile Surface" assignment in the map
  is present in the file with the documented group and is visible
  (``display.none`` MUST NOT be set).
* Every input in any documented operator-only group MUST carry
  ``display = display.none``.

The test fails closed if either pine file is restructured without updating the
map, preventing silent surface drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pine_input_surface import parse_inputs

REPO_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = REPO_ROOT / "spec" / "hero_surface_input_map.json"


@pytest.fixture(scope="module")
def hero_map() -> dict:
    return json.loads(MAP_PATH.read_text())


@pytest.mark.parametrize("pine_file", ["SMC_Dashboard.pine", "SMC_Mobile_Dashboard.pine"])
def test_surface_assignments_visible_and_in_documented_group(hero_map, pine_file):
    spec = hero_map["files"][pine_file]
    assignments = spec["assignments"]
    inputs = {inp.varname: inp for inp in parse_inputs((REPO_ROOT / pine_file).read_text(encoding="utf-8").splitlines())}

    for varname, want in assignments.items():
        assert varname in inputs, f"{pine_file}: declared surface input '{varname}' missing from file"
        inp = inputs[varname]
        assert inp.group == want["group"], (
            f"{pine_file}: '{varname}' must live in group {want['group']!r}, found {inp.group!r}"
        )
        assert not inp.has_display_none, (
            f"{pine_file}: surface input '{varname}' must remain visible (display != display.none)"
        )


@pytest.mark.parametrize("pine_file", ["SMC_Dashboard.pine", "SMC_Mobile_Dashboard.pine"])
def test_operator_only_groups_are_display_none(hero_map, pine_file):
    spec = hero_map["files"][pine_file]
    if not spec.get("operator_only_must_be_display_none"):
        pytest.skip("operator_only_must_be_display_none disabled for this file")
    op_groups = set(spec["operator_only_groups"])
    inputs = parse_inputs((REPO_ROOT / pine_file).read_text(encoding="utf-8").splitlines())

    leaks = [
        f"{inp.varname} (group={inp.group!r}, line {inp.lineno})"
        for inp in inputs
        if inp.group in op_groups and not inp.has_display_none
    ]
    assert not leaks, (
        f"{pine_file}: operator-only inputs leaked into visible surface: {leaks}"
    )


def test_hero_state_consumers_are_referenced_in_dashboard(hero_map):
    """Every advertised mp.HERO_* consumer must actually be read by the dashboard."""
    dash = (REPO_ROOT / "SMC_Dashboard.pine").read_text(encoding="utf-8")
    missing = [name for name in hero_map["hero_state_consumers"] if name not in dash]
    assert not missing, f"SMC_Dashboard.pine does not reference advertised hero consumers: {missing}"
