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
