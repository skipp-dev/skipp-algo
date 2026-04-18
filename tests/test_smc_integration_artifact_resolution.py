from __future__ import annotations

from pathlib import Path

from smc_integration.artifact_resolution import (
    resolve_export_bundle_root,
    resolve_production_workbook_path,
    resolve_structure_artifact_inputs,
)
from tests.helpers.smc_test_artifacts import make_minimal_workbook


def test_explicit_workbook_path_wins(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    resolved = resolve_production_workbook_path(str(workbook))
    assert resolved == workbook


def test_canonical_workbook_used_when_explicit_absent(tmp_path: Path, monkeypatch) -> None:
    workbook = make_minimal_workbook(tmp_path)

    import smc_integration.artifact_resolution as module

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    resolved = module.resolve_production_workbook_path(None)
    assert resolved == workbook


def test_no_workbook_found_returns_none_with_structured_error(tmp_path: Path, monkeypatch) -> None:
    import smc_integration.artifact_resolution as module

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    result = module.resolve_structure_artifact_inputs(explicit_workbook_path="")
    assert result["workbook_path"] is None
    assert any(item.get("code") == "WORKBOOK_NOT_FOUND" for item in result["errors"])


def test_explicit_export_bundle_root_wins(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir(parents=True, exist_ok=True)
    resolved = resolve_export_bundle_root(str(root))
    assert resolved == root


def test_resolution_output_contains_deterministic_keys(tmp_path: Path, monkeypatch) -> None:
    workbook = make_minimal_workbook(tmp_path)

    import smc_integration.artifact_resolution as module

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    out = module.resolve_structure_artifact_inputs(explicit_workbook_path=str(workbook))
    assert set(out.keys()) == {
        "workbook_path",
        "export_bundle_root",
        "structure_artifacts_dir",
        "single_structure_artifact_path",
        "resolution_mode",
        "errors",
        "warnings",
        "resolution_detail",
    }


def test_no_hidden_workspace_dependency(tmp_path: Path, monkeypatch) -> None:
    import smc_integration.artifact_resolution as module

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    resolved = module.resolve_production_workbook_path(None)
    assert resolved is None


# ── pure helper coverage ─────────────────────────────────────────

import smc_integration.artifact_resolution as _ar


class TestToExistingPath:
    def test_none_returns_none(self) -> None:
        assert _ar._to_existing_path(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _ar._to_existing_path("") is None

    def test_whitespace_returns_none(self) -> None:
        assert _ar._to_existing_path("   ") is None

    def test_nonexistent_returns_none(self, tmp_path: Path) -> None:
        assert _ar._to_existing_path(str(tmp_path / "nope.txt")) is None

    def test_existing_file_returns_path(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.touch()
        result = _ar._to_existing_path(str(f))
        assert result == f


class TestRepoAbsolute:
    def test_already_absolute(self, tmp_path: Path) -> None:
        assert _ar._repo_absolute(tmp_path / "foo") == (tmp_path / "foo").resolve()

    def test_relative_resolves_against_repo_root(self, monkeypatch) -> None:
        import smc_integration.artifact_resolution as module
        monkeypatch.setattr(module, "REPO_ROOT", Path("/fake/repo"))
        result = module._repo_absolute(Path("reports/test.json"))
        assert str(result) == str(Path("/fake/repo/reports/test.json").resolve())


class TestMode:
    def test_explicit(self) -> None:
        assert _ar._mode(True, False) == "explicit"
        assert _ar._mode(True, True) == "explicit"

    def test_canonical(self) -> None:
        assert _ar._mode(False, True) == "canonical"

    def test_missing(self) -> None:
        assert _ar._mode(False, False) == "missing"


class TestResolveExportBundleRoot:
    def test_existing_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "bundle"
        d.mkdir()
        assert _ar.resolve_export_bundle_root(str(d)) == d

    def test_file_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(_ar, "REPO_ROOT", tmp_path)
        f = tmp_path / "not_a_dir.txt"
        f.touch()
        assert _ar.resolve_export_bundle_root(str(f)) is None

    def test_none_falls_through(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(_ar, "REPO_ROOT", tmp_path)
        # No canonical dir exists
        assert _ar.resolve_export_bundle_root(None) is None


class TestResolveStructureArtifactInputsEdgeCases:
    def test_all_explicit_paths(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(_ar, "REPO_ROOT", tmp_path)
        workbook = make_minimal_workbook(tmp_path)
        artifacts_dir = tmp_path / "my_artifacts"
        artifacts_dir.mkdir()
        single_artifact = tmp_path / "single.json"
        single_artifact.write_text("{}", encoding="utf-8")

        result = _ar.resolve_structure_artifact_inputs(
            explicit_workbook_path=str(workbook),
            explicit_structure_artifacts_dir=str(artifacts_dir),
            explicit_single_structure_artifact_path=str(single_artifact),
        )
        assert result["workbook_path"] is not None
        assert result["structure_artifacts_dir"] is not None
        assert result["errors"] == []

    def test_empty_explicit_paths_treated_as_none(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(_ar, "REPO_ROOT", tmp_path)
        result = _ar.resolve_structure_artifact_inputs(
            explicit_workbook_path="",
            explicit_export_bundle_root="",
            explicit_structure_artifacts_dir="",
            explicit_single_structure_artifact_path="",
        )
        assert result["workbook_path"] is None
