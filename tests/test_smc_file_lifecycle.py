"""Tests for legacy/experimental file classification (ENG-WS6-04)."""
from __future__ import annotations

from scripts.smc_file_lifecycle import (
    EXPLICIT_OVERRIDES,
    FileLifecycle,
    classify_file,
    classify_files,
)


class TestClassifyFile:
    def test_dashboard_is_production(self) -> None:
        assert classify_file("SMC_Dashboard.pine") is FileLifecycle.PRODUCTION
        assert classify_file("SMC_Mobile_Dashboard.pine") is FileLifecycle.PRODUCTION

    def test_choch_family_is_legacy(self) -> None:
        # DoD: 'Legacy- und Experimental-Dateien sind explizit markiert'.
        assert classify_file("CHOCH-Indicator.pine") is FileLifecycle.LEGACY
        assert classify_file("CHOCH-Strategy.pine") is FileLifecycle.LEGACY
        assert classify_file("CHoCH.pine") is FileLifecycle.LEGACY
        assert classify_file("QuickALGO.pine") is FileLifecycle.LEGACY

    def test_orderflow_is_experimental(self) -> None:
        assert classify_file("SMC_Orderflow_Overlay.pine") is FileLifecycle.EXPERIMENTAL

    def test_rev_family_is_experimental(self) -> None:
        assert classify_file("REV-BUY.pine") is FileLifecycle.EXPERIMENTAL
        assert classify_file("REV-Ladder.pine") is FileLifecycle.EXPERIMENTAL

    def test_setup_check_is_operator_only(self) -> None:
        assert classify_file("SMC_Setup_Check.pine") is FileLifecycle.OPERATOR_ONLY

    def test_unknown_file_is_unclassified(self) -> None:
        # Unclassified ≠ silently treated as production. Cleanup
        # tooling can later target this gap.
        assert classify_file("totally-new-file.pine") is FileLifecycle.UNCLASSIFIED


class TestClassifyFiles:
    def test_batch_classifies_each_entry(self) -> None:
        results = classify_files([
            "SMC_Dashboard.pine",
            "CHOCH-Indicator.pine",
            "SMC_Orderflow_Overlay.pine",
            "totally-new.pine",
        ])
        assert [r.lifecycle for r in results] == [
            FileLifecycle.PRODUCTION,
            FileLifecycle.LEGACY,
            FileLifecycle.EXPERIMENTAL,
            FileLifecycle.UNCLASSIFIED,
        ]

    def test_result_predicates(self) -> None:
        legacy = classify_files(["CHOCH-Indicator.pine"])[0]
        assert legacy.is_legacy
        assert not legacy.is_experimental
        assert not legacy.is_user_facing_production

        prod = classify_files(["SMC_Dashboard.pine"])[0]
        assert prod.is_user_facing_production

    def test_as_dict_round_trip(self) -> None:
        d = classify_files(["SMC_Dashboard.pine"])[0].as_dict()
        assert d["lifecycle"] == "production"
        assert d["is_user_facing_production"] is True


class TestOverrideTable:
    def test_no_override_disagrees_with_surface_matrix(self) -> None:
        # If a name is in EXPLICIT_OVERRIDES it should NOT also appear
        # in SURFACE_MATRIX — the matrix wins by resolution order so a
        # disagreement would be a silent bug.
        from scripts.smc_surface_matrix import SURFACE_MATRIX
        matrix_names = {e.name for e in SURFACE_MATRIX}
        overlap = matrix_names & set(EXPLICIT_OVERRIDES)
        assert overlap == set(), f"overrides shadowed by matrix: {sorted(overlap)}"
