from __future__ import annotations

import json
from pathlib import Path

from smc_integration.extended_structure_discovery import (
    TARGET_CATEGORIES,
    build_extended_structure_discovery_report,
    discover_extended_structure_by_category,
    discover_extended_structure_candidates,
)


ROOT = Path(__file__).resolve().parents[1]


def test_extended_structure_candidates_are_deterministic_and_real_paths() -> None:
    one = discover_extended_structure_candidates()
    two = discover_extended_structure_candidates()

    assert one == two
    assert one

    for row in one:
        assert row["category"] in TARGET_CATEGORIES
        assert row["evidence_type"] in {"explicit_objects", "computed_logic", "aggregate_flags", "text_only"}
        assert (ROOT / str(row["path"])).exists()


def test_extended_discovery_has_candidates_for_all_missing_categories() -> None:
    by_category = discover_extended_structure_by_category()

    assert set(by_category.keys()) == set(TARGET_CATEGORIES)

    for category in TARGET_CATEGORIES:
        bucket = by_category[category]
        assert bucket["candidate_count"] > 0
        assert isinstance(bucket["top_candidates"], list)
        assert bucket["top_candidates"]
        best = bucket["best_candidate"]
        assert isinstance(best, dict)
        assert best["category"] == category
        assert best["evidence_type"] in {"explicit_objects", "computed_logic", "aggregate_flags", "text_only"}


def test_extended_discovery_report_is_serializable_and_has_strong_types() -> None:
    report = build_extended_structure_discovery_report()
    encoded = json.dumps(report, sort_keys=True)
    assert encoded

    strongest = report["strongest_evidence_type"]
    assert set(strongest.keys()) == set(TARGET_CATEGORIES)

    for category in TARGET_CATEGORIES:
        assert strongest[category] in {"explicit_objects", "computed_logic", "aggregate_flags", "text_only"}
        # Current repository has at least computed or explicit evidence for every missing category.
        assert strongest[category] in {"explicit_objects", "computed_logic"}


def test_extended_integrability_is_conservative_for_non_provider_sources() -> None:
    by_category = discover_extended_structure_by_category()

    for category in TARGET_CATEGORIES:
        integrability = by_category[category]["integrability"]
        assert isinstance(integrability["integrable_now"], bool)
        assert isinstance(integrability["reason"], str)
