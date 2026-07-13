from __future__ import annotations

from pathlib import Path

from scripts.verify_structure_artifact_availability import verify_structure_artifact_availability
from smc_integration.structure_batch import write_structure_artifacts_from_workbook
from tests.helpers.smc_test_artifacts import make_minimal_workbook


def test_verifier_fails_without_primary_manifest(tmp_path: Path) -> None:
    report = verify_structure_artifact_availability(tmp_path, ["1D"])
    assert report["ok"] is False
    assert "manifest unavailable" in report["failures"][0]


def test_verifier_accepts_consumable_primary_manifest(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=["AAPL"],
        output_dir=tmp_path / "reports" / "smc_structure_artifacts",
        generated_at=1780000000.0,
    )
    report = verify_structure_artifact_availability(tmp_path, ["1D"])
    assert report == {"ok": True, "verified": {"1D": 1}, "failures": []}
