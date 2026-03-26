from __future__ import annotations

from smc_integration.structure_audit import discover_structure_category_coverage


def test_structure_category_coverage_contains_all_required_categories() -> None:
    coverage = discover_structure_category_coverage()
    assert set(coverage.keys()) == {"bos", "choch", "orderblocks", "fvg", "liquidity_sweeps"}


def test_structure_category_coverage_is_deterministic() -> None:
    one = discover_structure_category_coverage()
    two = discover_structure_category_coverage()
    assert one == two


def test_unavailable_categories_are_explicitly_marked_not_omitted() -> None:
    coverage = discover_structure_category_coverage()

    for category in ("orderblocks", "fvg", "liquidity_sweeps"):
        assert category in coverage
        assert coverage[category]["available"] is False
        assert coverage[category]["producer"] is None


def test_bos_choch_are_explicitly_marked_available() -> None:
    coverage = discover_structure_category_coverage()

    assert coverage["bos"]["available"] is True
    assert coverage["choch"]["available"] is True
    assert coverage["bos"]["producer"] == "structure_artifact_json"
    assert coverage["choch"]["producer"] == "structure_artifact_json"
