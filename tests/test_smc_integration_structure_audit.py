from __future__ import annotations

import json
from pathlib import Path

from smc_integration.structure_audit import (
    build_structure_gap_report,
    discover_structure_category_coverage,
    discover_structure_source_candidates,
    structure_gap_report_to_dict,
)


ROOT = Path(__file__).resolve().parents[1]


def test_discover_structure_source_candidates_is_deterministic() -> None:
    one = discover_structure_source_candidates()
    two = discover_structure_source_candidates()
    assert one == two


def test_structure_candidates_are_real_paths_with_evidence() -> None:
    candidates = discover_structure_source_candidates()
    assert candidates

    paths = {candidate["path"] for candidate in candidates}
    assert "scripts/export_smc_structure_artifacts_from_workbook.py" in paths or "scripts/export_smc_structure_artifact.py" in paths

    for candidate in candidates:
        assert candidate["path"]
        assert candidate["evidence"]
        assert candidate["confidence"] in {"high", "medium", "low"}
        assert (ROOT / candidate["path"]).exists()


def test_build_structure_gap_report_has_required_keys() -> None:
    report = build_structure_gap_report()
    required = {
        "has_real_structure_provider",
        "best_candidate",
        "registered_structure_sources",
        "candidate_sources",
        "summary",
        "category_coverage",
        "available_categories",
        "missing_categories",
        "provider_by_category",
        "gaps",
        "structure_status",
    }
    assert required.issubset(report.keys())


def test_discover_structure_category_coverage_is_complete_and_deterministic() -> None:
    one = discover_structure_category_coverage()
    two = discover_structure_category_coverage()

    assert one == two
    assert set(one.keys()) == {"bos", "choch", "orderblocks", "fvg", "liquidity_sweeps"}

    for category, row in one.items():
        assert set(row.keys()) == {"available", "producer", "source_evidence", "notes"}
        assert isinstance(row["available"], bool)
        assert isinstance(row["source_evidence"], list)
        assert isinstance(row["notes"], list)
        if row["available"]:
            assert row["producer"] == "structure_artifact_json"
        else:
            assert row["producer"] is None


def test_gap_report_is_honest_for_current_repo_state() -> None:
    report = build_structure_gap_report()

    assert report["has_real_structure_provider"] is True
    assert isinstance(report["gaps"], list)
    assert any("orderblocks" in gap for gap in report["gaps"])
    assert any("FVG" in gap or "fvg" in gap for gap in report["gaps"])
    assert "bos" in report["available_categories"]
    assert "choch" in report["available_categories"]
    assert "orderblocks" in report["missing_categories"]
    assert "fvg" in report["missing_categories"]
    assert "liquidity_sweeps" in report["missing_categories"]


def test_structure_gap_report_is_json_serializable_and_stable() -> None:
    one = structure_gap_report_to_dict(build_structure_gap_report())
    two = structure_gap_report_to_dict(build_structure_gap_report())
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
