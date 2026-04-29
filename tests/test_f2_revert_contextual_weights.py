"""Tests for scripts/f2_revert_contextual_weights.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_revert_contextual_weights import (
    ARCHIVE_SUBDIR_DEFAULT,
    main,
    revert_contextual_weights,
)


def _spec(artifact_path: Path) -> dict:
    return {
        "schema_version": 1,
        "name": "test-spec",
        "arms": {
            "control": {"label": "static"},
            "treatment": {
                "label": "contextual",
                "calibration_artifact": str(artifact_path),
            },
        },
    }


def _report(decision: str = "rollback") -> dict:
    return {"schema_version": 1, "decision": decision}


def _setup(tmp_path: Path, *, artifact_status: str | None = "production") -> tuple[Path, Path, Path, Path]:
    spec_path = tmp_path / "spec.json"
    report_path = tmp_path / "report.json"
    artifact_path = tmp_path / "treatment.json"
    journal = tmp_path / "journal.jsonl"

    spec_path.write_text(json.dumps(_spec(artifact_path)), encoding="utf-8")
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    payload: dict = {"weights": {"OB": 1.0}, "ece": 0.12}
    if artifact_status is not None:
        payload["status"] = artifact_status
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    return spec_path, report_path, artifact_path, journal


# ---------------------------------------------------------------------------
# revert_contextual_weights()
# ---------------------------------------------------------------------------


def test_revert_demotes_production_artifact_and_archives(tmp_path: Path) -> None:
    spec, report, artifact, journal = _setup(tmp_path)
    rec = revert_contextual_weights(
        spec_path=spec, report_path=report, journal_path=journal,
        timestamp="2026-04-21T10-00-00Z",
    )
    assert rec["action"] == "reverted"
    assert rec["new_status"] == "shadow"

    # Live file is now shadow with revert_history appended.
    new_artifact = json.loads(artifact.read_text(encoding="utf-8"))
    assert new_artifact["status"] == "shadow"
    assert len(new_artifact["revert_history"]) == 1
    entry = new_artifact["revert_history"][0]
    assert entry["from_status"] == "production"
    assert entry["report_decision"] == "rollback"
    assert entry["reverted_at_utc"] == "2026-04-21T10-00-00Z"

    # Archive contains the original payload (status=production).
    archived = Path(rec["archived_to"])
    assert archived.parent.name == ARCHIVE_SUBDIR_DEFAULT
    archived_payload = json.loads(archived.read_text(encoding="utf-8"))
    assert archived_payload["status"] == "production"

    # Journal has exactly one JSONL line.
    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["action"] == "reverted"


def test_revert_noop_when_already_shadow(tmp_path: Path) -> None:
    spec, report, artifact, journal = _setup(tmp_path, artifact_status="shadow")
    rec = revert_contextual_weights(
        spec_path=spec, report_path=report, journal_path=journal,
    )
    assert rec["action"] == "noop_already_shadow"
    # Artifact untouched.
    assert json.loads(artifact.read_text(encoding="utf-8"))["status"] == "shadow"
    # Journal still records the run.
    assert journal.read_text(encoding="utf-8").strip().splitlines()


def test_revert_noop_when_artifact_missing(tmp_path: Path) -> None:
    spec, report, artifact, journal = _setup(tmp_path)
    artifact.unlink()
    rec = revert_contextual_weights(
        spec_path=spec, report_path=report, journal_path=journal,
    )
    assert rec["action"] == "noop_missing_artifact"
    assert journal.exists()


def test_revert_noop_when_status_field_missing(tmp_path: Path) -> None:
    spec, report, _artifact, journal = _setup(tmp_path, artifact_status=None)
    rec = revert_contextual_weights(
        spec_path=spec, report_path=report, journal_path=journal,
    )
    assert rec["action"] == "noop_already_shadow"
    assert rec["current_status"] is None


def test_revert_refuses_when_decision_not_rollback(tmp_path: Path) -> None:
    spec, report, _, journal = _setup(tmp_path)
    report.write_text(json.dumps(_report("hold")), encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to revert"):
        revert_contextual_weights(
            spec_path=spec, report_path=report, journal_path=journal,
        )


def test_revert_force_flag_overrides_decision(tmp_path: Path) -> None:
    spec, report, _artifact, journal = _setup(tmp_path)
    report.write_text(json.dumps(_report("hold")), encoding="utf-8")
    rec = revert_contextual_weights(
        spec_path=spec, report_path=report, journal_path=journal,
        force=True, timestamp="2026-04-21T11-00-00Z",
    )
    assert rec["action"] == "reverted"
    assert rec["force"] is True


def test_revert_archive_collision_raises(tmp_path: Path) -> None:
    spec, report, artifact, journal = _setup(tmp_path)
    archive = tmp_path / "arch"
    archive.mkdir()
    (archive / f"{artifact.stem}_2026-04-21T12-00-00Z.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="archive collision"):
        revert_contextual_weights(
            spec_path=spec, report_path=report, journal_path=journal,
            archive_dir=archive, timestamp="2026-04-21T12-00-00Z",
        )
    # Live file untouched.
    assert json.loads(artifact.read_text(encoding="utf-8"))["status"] == "production"


def test_revert_appends_to_existing_revert_history(tmp_path: Path) -> None:
    spec, report, artifact, journal = _setup(tmp_path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["revert_history"] = [{"reverted_at_utc": "2025-01-01T00-00-00Z"}]
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    revert_contextual_weights(
        spec_path=spec, report_path=report, journal_path=journal,
        timestamp="2026-04-21T13-00-00Z",
    )
    new = json.loads(artifact.read_text(encoding="utf-8"))
    assert len(new["revert_history"]) == 2
    assert new["revert_history"][-1]["reverted_at_utc"] == "2026-04-21T13-00-00Z"


def test_revert_journal_appends_across_runs(tmp_path: Path) -> None:
    spec, report, _, journal = _setup(tmp_path, artifact_status="shadow")
    revert_contextual_weights(spec_path=spec, report_path=report, journal_path=journal)
    revert_contextual_weights(spec_path=spec, report_path=report, journal_path=journal)
    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert all(json.loads(ln)["action"] == "noop_already_shadow" for ln in lines)


def test_revert_raises_on_missing_spec(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="spec does not exist"):
        revert_contextual_weights(
            spec_path=tmp_path / "no.json",
            report_path=tmp_path / "no.json",
            journal_path=tmp_path / "j.jsonl",
        )


def test_revert_raises_on_missing_treatment_artifact_field(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    report_path = tmp_path / "r.json"
    spec_path.write_text(json.dumps({"arms": {"treatment": {}}}), encoding="utf-8")
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    with pytest.raises(ValueError, match="arms.treatment.calibration_artifact"):
        revert_contextual_weights(
            spec_path=spec_path, report_path=report_path,
            journal_path=tmp_path / "j.jsonl",
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_happy_path(tmp_path: Path) -> None:
    spec, report, artifact, journal = _setup(tmp_path)
    rc = main([
        "--spec",   str(spec),
        "--report", str(report),
        "--journal", str(journal),
    ])
    assert rc == 0
    assert json.loads(artifact.read_text(encoding="utf-8"))["status"] == "shadow"


def test_cli_returns_1_on_decision_not_rollback(tmp_path: Path) -> None:
    spec, report, _, journal = _setup(tmp_path)
    report.write_text(json.dumps(_report("hold")), encoding="utf-8")
    rc = main([
        "--spec",   str(spec),
        "--report", str(report),
        "--journal", str(journal),
    ])
    assert rc == 1


def test_cli_force_flag(tmp_path: Path) -> None:
    spec, report, artifact, journal = _setup(tmp_path)
    report.write_text(json.dumps(_report("hold")), encoding="utf-8")
    rc = main([
        "--spec",   str(spec),
        "--report", str(report),
        "--journal", str(journal),
        "--force",
    ])
    assert rc == 0
    assert json.loads(artifact.read_text(encoding="utf-8"))["status"] == "shadow"


def test_cli_returns_1_on_missing_spec(tmp_path: Path) -> None:
    rc = main([
        "--spec",   str(tmp_path / "no.json"),
        "--report", str(tmp_path / "no.json"),
    ])
    assert rc == 1
