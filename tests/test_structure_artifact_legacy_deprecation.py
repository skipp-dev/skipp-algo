"""Lifecycle telemetry for the deprecated legacy single-file structure ingress (ADR-0027)."""
from __future__ import annotations

import logging
from pathlib import Path

from scripts.export_smc_structure_artifact import export_structure_artifact
from smc_integration.sources import structure_artifact_json
from smc_integration.structure_batch import write_structure_artifacts_from_workbook
from tests.helpers.smc_test_artifacts import make_minimal_workbook

LOGGER_NAME = "smc_integration.sources.structure_artifact_json"


def _isolate_usage(monkeypatch) -> None:
    monkeypatch.setattr(structure_artifact_json, "_LEGACY_USAGE", {"count": 0, "first_context": None})


def _legacy_only(monkeypatch, tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    empty_dir = tmp_path / "no-primary"
    empty_dir.mkdir()
    legacy_path = tmp_path / "smc_structure_artifact.json"
    export_structure_artifact(workbook=workbook, output=legacy_path, generated_at=1780000000.0)
    monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", empty_dir)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", legacy_path)


def test_legacy_consumption_counts_and_warns_exactly_once(monkeypatch, tmp_path: Path, caplog) -> None:
    _isolate_usage(monkeypatch)
    _legacy_only(monkeypatch, tmp_path)
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        first = structure_artifact_json.load_normalized_structure_contract_input("AAPL", "15m")
        second = structure_artifact_json.load_normalized_structure_contract_input("AAPL", "15m")
    assert first is not None
    assert second is not None
    usage = structure_artifact_json.legacy_single_file_usage()
    assert usage["count"] == 2
    assert usage["first_context"] == "load_normalized_structure_contract_input"
    deprecation_warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and "DEPRECATED" in record.getMessage()
    ]
    assert len(deprecation_warnings) == 1


def test_primary_per_tf_path_does_not_touch_legacy_telemetry(monkeypatch, tmp_path: Path) -> None:
    _isolate_usage(monkeypatch)
    workbook = make_minimal_workbook(tmp_path)
    artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=["AAPL"],
        output_dir=artifact_dir,
        generated_at=1780000000.0,
    )
    monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "absent.json")
    loaded = structure_artifact_json.load_normalized_structure_contract_input("AAPL", "1D")
    assert loaded is not None
    assert structure_artifact_json.legacy_single_file_usage() == {"count": 0, "first_context": None}


def test_contract_health_reports_legacy_usage_telemetry(monkeypatch, tmp_path: Path) -> None:
    _isolate_usage(monkeypatch)
    _legacy_only(monkeypatch, tmp_path)
    health = structure_artifact_json.discover_contract_health()
    usage = health["legacy_single_file_usage"]
    assert usage["count"] >= 1
    assert usage["first_context"] == "_iter_normalized_contracts"
    assert any(issue["code"] == "LEGACY_SINGLE_FILE_FALLBACK" for issue in health["issues"])
