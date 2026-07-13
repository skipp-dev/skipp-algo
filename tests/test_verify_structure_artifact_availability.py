from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.verify_structure_artifact_availability import (
    main,
    verify_structure_artifact_availability,
)
from smc_integration.structure_batch import write_structure_artifacts_from_workbook
from tests.helpers.smc_test_artifacts import make_minimal_workbook

GENERATED_AT = 1780000000.0  # 2026-05-29, after the helper workbook's 2026-03 bars


def _materialize(tmp_path: Path, *, symbols: list[str] | None = None) -> Path:
    workbook = make_minimal_workbook(tmp_path, symbols=symbols)
    write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols or ["AAPL"],
        output_dir=tmp_path / "reports" / "smc_structure_artifacts",
        generated_at=GENERATED_AT,
    )
    return tmp_path / "reports" / "smc_structure_artifacts"


def test_verifier_fails_without_primary_manifest(tmp_path: Path) -> None:
    report = verify_structure_artifact_availability(tmp_path, ["1D"])
    assert report["ok"] is False
    assert "manifest unavailable" in report["failures"][0]


def test_verifier_accepts_consumable_primary_manifest(tmp_path: Path) -> None:
    _materialize(tmp_path)
    report = verify_structure_artifact_availability(tmp_path, ["1D"])
    assert report["ok"] is True
    assert report["verified"] == {"1D": 1}
    assert report["failures"] == []
    assert report["details"]["1D"]["symbols"] == ["AAPL"]
    assert report["details"]["1D"]["generated_at"] == GENERATED_AT


def test_verifier_fails_on_incomplete_production_counts(tmp_path: Path) -> None:
    artifact_dir = _materialize(tmp_path)
    manifest_path = artifact_dir / "manifest_1D.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["symbols_requested"] = 3
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = verify_structure_artifact_availability(tmp_path, ["1D"])
    assert report["ok"] is False
    assert any("incomplete production" in failure for failure in report["failures"])


def test_verifier_fails_on_counted_producer_errors(tmp_path: Path) -> None:
    artifact_dir = _materialize(tmp_path)
    manifest_path = artifact_dir / "manifest_1D.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["errors"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = verify_structure_artifact_availability(tmp_path, ["1D"])
    assert report["ok"] is False
    assert any("producer error" in failure for failure in report["failures"])


def test_verifier_fails_on_missing_counts_block(tmp_path: Path) -> None:
    artifact_dir = _materialize(tmp_path)
    manifest_path = artifact_dir / "manifest_1D.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["counts"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = verify_structure_artifact_availability(tmp_path, ["1D"])
    assert report["ok"] is False
    assert any("missing counts block" in failure for failure in report["failures"])


def test_verifier_fails_on_missing_generator_provenance(tmp_path: Path) -> None:
    artifact_dir = _materialize(tmp_path)
    manifest_path = artifact_dir / "manifest_1D.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["provenance"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = verify_structure_artifact_availability(tmp_path, ["1D"])
    assert report["ok"] is False
    assert any("missing generator provenance" in failure for failure in report["failures"])
    assert report["details"]["1D"]["provenance"] is None


def test_verifier_reports_generator_provenance_in_details(tmp_path: Path) -> None:
    _materialize(tmp_path)
    report = verify_structure_artifact_availability(tmp_path, ["1D"])
    assert report["ok"] is True
    provenance = report["details"]["1D"]["provenance"]
    assert provenance["generator_path"] == "smc_integration/structure_batch.py"
    assert provenance["input_fingerprint"]["kind"] == "workbook_sha256"


def test_verifier_enforces_expected_symbol_set(tmp_path: Path) -> None:
    _materialize(tmp_path)
    report = verify_structure_artifact_availability(
        tmp_path, ["1D"], expect_symbols=["AAPL", "MSFT"]
    )
    assert report["ok"] is False
    assert any("expected symbols missing" in failure and "MSFT" in failure for failure in report["failures"])
    assert report["details"]["1D"]["missing_symbols"] == ["MSFT"]

    satisfied = verify_structure_artifact_availability(tmp_path, ["1D"], expect_symbols=["AAPL"])
    assert satisfied["ok"] is True


def test_verifier_enforces_manifest_freshness(tmp_path: Path) -> None:
    _materialize(tmp_path)
    stale = verify_structure_artifact_availability(
        tmp_path, ["1D"], max_age_seconds=3600.0, now=GENERATED_AT + 7200.0
    )
    assert stale["ok"] is False
    assert any("stale" in failure for failure in stale["failures"])

    fresh = verify_structure_artifact_availability(
        tmp_path, ["1D"], max_age_seconds=3600.0, now=GENERATED_AT + 60.0
    )
    assert fresh["ok"] is True
    assert fresh["details"]["1D"]["age_seconds"] == 60.0


def test_verifier_rejects_impossible_read_side_provenance(tmp_path: Path) -> None:
    artifact_dir = _materialize(tmp_path)
    artifact_path = artifact_dir / "AAPL_1D.structure.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    # Claim an observed-data timestamp NEWER than generated_at: impossible.
    payload.setdefault("structure", {}).setdefault("bos", []).append(
        {"anchor_ts": GENERATED_AT + 86400.0}
    )
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    report = verify_structure_artifact_availability(tmp_path, ["1D"])
    assert report["ok"] is False
    assert any("impossible provenance" in failure for failure in report["failures"])


def test_cli_persists_evidence_report(tmp_path: Path, monkeypatch, capsys) -> None:
    _materialize(tmp_path)
    output_path = tmp_path / "artifacts" / "ci" / "structure_artifact_availability.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_structure_artifact_availability",
            "--timeframes",
            "1D",
            "--root",
            str(tmp_path),
            "--expect-symbols",
            "AAPL",
            "--output",
            str(output_path),
        ],
    )
    assert main() == 0
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["ok"] is True
    assert persisted["checked"]["expect_symbols"] == ["AAPL"]
    assert persisted == json.loads(capsys.readouterr().out)


def test_cli_exit_code_and_evidence_on_failure(tmp_path: Path, monkeypatch) -> None:
    output_path = tmp_path / "artifacts" / "ci" / "structure_artifact_availability.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_structure_artifact_availability",
            "--timeframes",
            "1D",
            "--root",
            str(tmp_path),
            "--output",
            str(output_path),
        ],
    )
    assert main() == 1
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["ok"] is False
    assert persisted["failures"]
