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
        "auxiliary_category_coverage",
        "structure_profile_supported",
        "structure_profiles_seen",
        "diagnostics_available",
        "auxiliary_available",
        "event_logic_versions_seen",
        "gaps",
        "structure_status",
    }
    assert required.issubset(report.keys())


def test_discover_structure_category_coverage_is_complete_and_deterministic() -> None:
    one = discover_structure_category_coverage()
    two = discover_structure_category_coverage()

    assert one == two
    assert set(one.keys()) == {"bos", "choch", "orderblocks", "fvg", "liquidity_sweeps"}

    for _category, row in one.items():
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

    coverage = report["category_coverage"]
    assert "bos" in report["available_categories"]
    assert "choch" in report["available_categories"]

    for category in ("orderblocks", "fvg", "liquidity_sweeps"):
        is_available = bool(coverage[category]["available"])
        if is_available:
            assert category in report["available_categories"]
            assert category not in report["missing_categories"]
        else:
            assert category in report["missing_categories"]

    assert isinstance(report["structure_profile_supported"], bool)
    assert isinstance(report["structure_profiles_seen"], list)
    assert isinstance(report["event_logic_versions_seen"], list)
    assert set(report["auxiliary_category_coverage"].keys()) == {
        "liquidity_lines",
        "session_ranges",
        "session_pivots",
        "ipda_range",
        "htf_fvg_bias",
        "broken_fractal_signals",
        # ADR-0021 (commit 2bedc96a) added ``rejection_blocks`` to the structure
        # contract's AUXILIARY_KEYS as a recorded-only category; keep the audit
        # honesty set aligned with the producer contract.
        "rejection_blocks",
    }


def test_structure_gap_report_is_json_serializable_and_has_expected_keys() -> None:
    report = structure_gap_report_to_dict(build_structure_gap_report())
    # Must be JSON-serializable without raising.
    serialized = json.dumps(report, sort_keys=True, default=str)
    assert isinstance(serialized, str)
    assert len(serialized) > 100

    # Key structure check.
    expected_keys = {
        "has_real_structure_provider",
        "best_candidate",
        "registered_structure_sources",
        "candidate_sources",
        "summary",
        "category_coverage",
        "available_categories",
        "missing_categories",
        "provider_by_category",
        "auxiliary_category_coverage",
        "structure_profile_supported",
        "structure_profiles_seen",
        "diagnostics_available",
        "auxiliary_available",
        "event_logic_versions_seen",
        "contract_health",
        "gaps",
        "structure_status",
        "extended_discovery",
    }
    assert expected_keys.issubset(set(report.keys()))


# ── pure helper coverage ─────────────────────────────────────────

from unittest.mock import patch

from smc_integration.structure_audit import (
    _collect_evidence,
    _confidence_for,
    _kind_for_path,
    _notes_for,
    _read_text_safely,
)


class TestKindForPath:
    def test_json(self) -> None:
        assert _kind_for_path(Path("foo.json")) == "json"

    def test_csv(self) -> None:
        assert _kind_for_path(Path("data.csv")) == "csv"

    def test_pine(self) -> None:
        assert _kind_for_path(Path("SMC_Core_Engine.pine")) == "pine"

    def test_script_py(self) -> None:
        assert _kind_for_path(Path("run.py")) == "script"

    def test_script_ts(self) -> None:
        assert _kind_for_path(Path("run.ts")) == "script"

    def test_generated(self) -> None:
        assert _kind_for_path(Path("generated/output.txt")) == "generated"

    def test_other(self) -> None:
        assert _kind_for_path(Path("readme.md")) == "other"


class TestReadTextSafely:
    def test_reads_utf8(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        assert _read_text_safely(f) == "hello world"

    def test_truncates(self, tmp_path: Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("x" * 1000, encoding="utf-8")
        assert len(_read_text_safely(f, max_chars=10)) == 10

    def test_latin1_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "latin.txt"
        f.write_bytes(b"\xff\xfe test")
        assert len(_read_text_safely(f)) > 0


class TestCollectEvidence:
    def test_finds_bos_and_fvg(self, tmp_path: Path) -> None:
        f = tmp_path / "test.json"
        f.write_text('{"bos": [], "fvg": []}', encoding="utf-8")
        evidence = _collect_evidence(f)
        assert "bos" in evidence
        assert "fvg" in evidence

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.json"
        f.write_text("{}", encoding="utf-8")
        assert _collect_evidence(f) == []

    def test_finds_orderblocks(self, tmp_path: Path) -> None:
        f = tmp_path / "ob.json"
        f.write_text('"orderblocks": [{"dir": "up"}]', encoding="utf-8")
        assert "orderblocks" in _collect_evidence(f)

    def test_finds_liquidity_sweeps(self, tmp_path: Path) -> None:
        f = tmp_path / "sweep.json"
        f.write_text('"liquidity_sweeps": []', encoding="utf-8")
        assert "liquidity_sweeps" in _collect_evidence(f)

    def test_finds_structure_underscore(self, tmp_path: Path) -> None:
        f = tmp_path / "meta.json"
        f.write_text("structure_score = 42", encoding="utf-8")
        assert "structure_" in _collect_evidence(f)

    def test_finds_reclaim(self, tmp_path: Path) -> None:
        f = tmp_path / "r.txt"
        f.write_text("We reclaim this zone", encoding="utf-8")
        assert "reclaim" in _collect_evidence(f)


class TestConfidenceFor:
    def test_high_when_all_explicit_keys(self) -> None:
        assert _confidence_for(Path("x"), ["bos", "orderblocks", "fvg", "liquidity_sweeps"]) == "high"

    def test_medium_when_some_explicit_keys(self) -> None:
        assert _confidence_for(Path("x"), ["bos", "fvg"]) == "medium"

    def test_medium_when_two_non_explicit(self) -> None:
        assert _confidence_for(Path("x"), ["sweep", "reclaim"]) == "medium"

    def test_low_when_single_non_explicit(self) -> None:
        assert _confidence_for(Path("x"), ["sweep"]) == "low"

    def test_low_on_empty(self) -> None:
        assert _confidence_for(Path("x"), []) == "low"


class TestNotesFor:
    def test_spec_examples_note(self, tmp_path: Path) -> None:
        import smc_integration.structure_audit as mod
        repo = tmp_path / "repo"
        spec_dir = repo / "spec" / "examples"
        spec_dir.mkdir(parents=True)
        f = spec_dir / "test.json"
        f.touch()
        with patch.object(mod, "_REPO_ROOT", repo):
            notes = _notes_for(f, ["bos"])
        assert any("Schema example" in n for n in notes)

    def test_reports_note(self, tmp_path: Path) -> None:
        import smc_integration.structure_audit as mod
        repo = tmp_path / "repo"
        reports_dir = repo / "reports"
        reports_dir.mkdir(parents=True)
        f = reports_dir / "test.json"
        f.touch()
        with patch.object(mod, "_REPO_ROOT", repo):
            notes = _notes_for(f, ["bos"])
        assert any("Report artifact" in n for n in notes)

    def test_scripts_note(self, tmp_path: Path) -> None:
        import smc_integration.structure_audit as mod
        repo = tmp_path / "repo"
        scripts_dir = repo / "scripts"
        scripts_dir.mkdir(parents=True)
        f = scripts_dir / "build.py"
        f.touch()
        with patch.object(mod, "_REPO_ROOT", repo):
            notes = _notes_for(f, ["bos"])
        assert any("Code path" in n for n in notes)

    def test_structure_only_without_explicit_keys(self, tmp_path: Path) -> None:
        import smc_integration.structure_audit as mod
        repo = tmp_path / "repo"
        repo.mkdir()
        f = repo / "test.py"
        f.touch()
        with patch.object(mod, "_REPO_ROOT", repo):
            notes = _notes_for(f, ["structure_"])
        assert any("meta fields" in n for n in notes)

    def test_reclaim_without_explicit_keys(self, tmp_path: Path) -> None:
        import smc_integration.structure_audit as mod
        repo = tmp_path / "repo"
        repo.mkdir()
        f = repo / "test.py"
        f.touch()
        with patch.object(mod, "_REPO_ROOT", repo):
            notes = _notes_for(f, ["reclaim"])
        assert any("Reclaim" in n for n in notes)

    def test_pine_engine_note(self, tmp_path: Path) -> None:
        import smc_integration.structure_audit as mod
        repo = tmp_path / "repo"
        repo.mkdir()
        f = repo / "SMC_Core_Engine.pine"
        f.touch()
        with patch.object(mod, "_REPO_ROOT", repo):
            notes = _notes_for(f, ["bos"])
        assert any("Pine runtime" in n for n in notes)


class TestCandidatePaths:
    def test_generated_dir_traversal(self, tmp_path: Path) -> None:
        import smc_integration.structure_audit as mod
        repo = tmp_path / "repo"
        gen_dir = repo / "pine" / "generated"
        gen_dir.mkdir(parents=True)
        (gen_dir / "out.json").write_text("{}", encoding="utf-8")
        (gen_dir / "out.pine").write_text("// pine", encoding="utf-8")
        with patch.object(mod, "_REPO_ROOT", repo):
            paths = mod._candidate_paths()
        names = {p.name for p in paths}
        assert "out.json" in names
        assert "out.pine" in names


class TestDiscoverCategoryCoverageNoProducer:
    def test_no_producer_adds_notes(self) -> None:
        mock_summary = {"mapped_structure_categories": {}}
        with patch("smc_integration.sources.structure_artifact_json.discover_normalized_contract_summary", return_value=mock_summary):
            from smc_integration.structure_audit import discover_structure_category_coverage
            coverage = discover_structure_category_coverage()
        # When no producer, bos and choch should have "No live" note
        assert any("No live" in n for n in coverage["bos"]["notes"])
        assert any("No live" in n for n in coverage["choch"]["notes"])
        # Unavailable categories get "not populated" note
        for cat in ("orderblocks", "fvg", "liquidity_sweeps"):
            assert any("not populated" in n for n in coverage[cat]["notes"])


class TestCandidatePathsDedup:
    def test_duplicate_paths_are_deduped(self, tmp_path: Path) -> None:
        import smc_integration.structure_audit as mod
        repo = tmp_path / "repo"
        gen_dir = repo / "pine" / "generated"
        gen_dir.mkdir(parents=True)
        dup_file = gen_dir / "dup.json"
        dup_file.write_text("{}", encoding="utf-8")
        with patch.object(mod, "_REPO_ROOT", repo):
            paths = mod._candidate_paths()
        # Count occurrences of the dup file
        count = sum(1 for p in paths if p == dup_file)
        assert count <= 1


class TestBuildStructureGapReportRealProviderWithPartialFields:
    def test_partial_fields_produce_gaps(self) -> None:
        from types import SimpleNamespace

        import smc_integration.structure_audit as mod

        fake_status = {
            "selected_structure_source": "fake_provider",
            "selected_structure_mode": "explicit",
            "selected_has_structure_capability": True,
            "any_registered_explicit_structure_provider": True,
            "explicit_structure_provider_names": ["fake_provider"],
            "notes": [],
        }

        fake_current = SimpleNamespace(
            snapshot_structure_mode="explicit",
            snapshot_meta_mode="merged",
            currently_maps_structure=True,
            currently_maps_meta=True,
            currently_maps_technical=False,
            currently_maps_news=False,
            mapped_structure_fields=[],  # no fields → all four gaps
        )
        fake_potential = SimpleNamespace(can_supply_symbols=True)
        fake_entry = SimpleNamespace(
            name="fake_provider",
            path_hint="reports/fake.json",
            current=fake_current,
            potential=fake_potential,
            known_gaps=[],
            capabilities=SimpleNamespace(has_structure=True, structure_mode="explicit"),
            notes=[],
        )

        fake_source = SimpleNamespace(
            name="fake_provider",
            path_hint="reports/fake.json",
            capabilities=SimpleNamespace(has_structure=True, structure_mode="explicit"),
            notes=[],
        )

        with (
            patch.object(mod, "discover_structure_source_candidates", return_value=[
                {"path": "spec/examples/test.json", "evidence": ["bos"], "confidence": "high", "kind": "json", "notes": []}
            ]),
            patch.object(mod, "discover_structure_category_coverage", return_value={
                cat: {"available": False, "producer": None, "source_evidence": [], "notes": []}
                for cat in ["bos", "choch", "orderblocks", "fvg", "liquidity_sweeps"]
            }),
            patch("smc_integration.repo_sources.discover_structure_source_status", return_value=fake_status),
            patch("smc_integration.repo_sources.discover_repo_sources", return_value=[fake_source]),
            patch("smc_integration.provider_matrix.discover_provider_matrix", return_value=[fake_entry]),
            patch("smc_integration.sources.structure_artifact_json.discover_normalized_contract_summary", return_value={
                "mapped_auxiliary_categories": {},
                "structure_profile_supported": False,
                "structure_profiles_seen": [],
                "diagnostics_available": False,
                "auxiliary_available": False,
                "event_logic_versions_seen": [],
                "health": {"issue_count": 0, "issues": []},
            }),
            patch("smc_integration.extended_structure_discovery.build_extended_structure_discovery_report", return_value={}),
        ):
            report = mod.build_structure_gap_report()

        # Should have per-field gap messages (lines 275, 277, 279, 281)
        assert any("BOS/CHOCH" in g for g in report["gaps"])
        assert any("orderblocks" in g for g in report["gaps"])
        assert any("FVG" in g for g in report["gaps"])
        assert any("liquidity sweeps" in g for g in report["gaps"])
        # And spec/examples best-candidate gap (line 284)
        assert any("schema examples" in g for g in report["gaps"])
