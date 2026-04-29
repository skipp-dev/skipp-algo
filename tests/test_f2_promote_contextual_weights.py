"""Tests for scripts/f2_promote_contextual_weights.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_promote_contextual_weights import (
    main,
    promote_contextual_weights,
)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _spec(tmp: Path, artifact: Path, *, status: str = "live") -> Path:
    p = tmp / "spec.json"
    _write(p, {
        "name": "f2",
        "status": status,
        "arms": {"treatment": {"calibration_artifact": str(artifact)}},
    })
    return p


def _report(tmp: Path, decision: str = "promote") -> Path:
    p = tmp / "report.json"
    _write(p, {"decision": decision})
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_promote_demotes_status_and_appends_history(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow", "weights": {"OB": 1.0}})

    rec = promote_contextual_weights(
        spec_path=_spec(tmp_path, artifact),
        report_path=_report(tmp_path),
        journal_path=tmp_path / "j.jsonl",
        timestamp="2026-04-21T12-00-00Z",
    )
    assert rec["action"] == "promoted"
    assert rec["new_status"] == "production"

    new = json.loads(artifact.read_text(encoding="utf-8"))
    assert new["status"] == "production"
    assert len(new["promote_history"]) == 1
    assert new["promote_history"][0]["from_status"] == "shadow"
    assert new["promote_history"][0]["promoted_at_utc"] == "2026-04-21T12-00-00Z"
    # Original payload preserved.
    assert new["weights"] == {"OB": 1.0}


def test_promote_archives_prior_shadow_file(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow", "marker": "v1"})

    rec = promote_contextual_weights(
        spec_path=_spec(tmp_path, artifact),
        report_path=_report(tmp_path),
        journal_path=tmp_path / "j.jsonl",
        timestamp="2026-04-21T12-00-00Z",
    )
    archive = Path(rec["archived_to"])
    assert archive.exists()
    archived = json.loads(archive.read_text(encoding="utf-8"))
    assert archived == {"status": "shadow", "marker": "v1"}


# ---------------------------------------------------------------------------
# No-op paths
# ---------------------------------------------------------------------------


def test_promote_noop_when_already_production(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "production"})
    journal = tmp_path / "j.jsonl"

    rec = promote_contextual_weights(
        spec_path=_spec(tmp_path, artifact),
        report_path=_report(tmp_path),
        journal_path=journal,
    )
    assert rec["action"] == "noop_already_production"
    # Journal still gets a line.
    assert len(journal.read_text(encoding="utf-8").strip().splitlines()) == 1
    # Artifact untouched.
    assert json.loads(artifact.read_text(encoding="utf-8")) == {"status": "production"}


def test_promote_noop_when_artifact_missing(tmp_path: Path) -> None:
    artifact = tmp_path / "missing.json"
    journal = tmp_path / "j.jsonl"

    rec = promote_contextual_weights(
        spec_path=_spec(tmp_path, artifact),
        report_path=_report(tmp_path),
        journal_path=journal,
    )
    assert rec["action"] == "noop_missing_artifact"
    assert journal.exists()


def test_promote_noop_when_status_field_missing(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"weights": {}})

    rec = promote_contextual_weights(
        spec_path=_spec(tmp_path, artifact),
        report_path=_report(tmp_path),
        journal_path=tmp_path / "j.jsonl",
    )
    assert rec["action"] == "noop_already_production"
    assert rec["current_status"] is None


# ---------------------------------------------------------------------------
# Refusal paths
# ---------------------------------------------------------------------------


def test_promote_refuses_when_decision_not_promote(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})

    with pytest.raises(ValueError, match="refusing to promote"):
        promote_contextual_weights(
            spec_path=_spec(tmp_path, artifact),
            report_path=_report(tmp_path, decision="hold"),
            journal_path=tmp_path / "j.jsonl",
        )


def test_promote_force_overrides_decision_check(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})

    rec = promote_contextual_weights(
        spec_path=_spec(tmp_path, artifact),
        report_path=_report(tmp_path, decision="hold"),
        journal_path=tmp_path / "j.jsonl",
        force=True,
        timestamp="2026-04-21T12-00-00Z",
    )
    assert rec["action"] == "promoted"
    assert rec["force"] is True


def test_promote_archive_collision_raises(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})
    archive_dir = tmp_path / "arch"
    archive_dir.mkdir()
    # Pre-create the would-be archive target.
    (archive_dir / "treatment_2026-04-21T12-00-00Z.json").write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="archive collision"):
        promote_contextual_weights(
            spec_path=_spec(tmp_path, artifact),
            report_path=_report(tmp_path),
            journal_path=tmp_path / "j.jsonl",
            archive_dir=archive_dir,
            timestamp="2026-04-21T12-00-00Z",
        )


def test_promote_missing_spec_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="spec does not exist"):
        promote_contextual_weights(
            spec_path=tmp_path / "nope.json",
            report_path=_report(tmp_path),
            journal_path=tmp_path / "j.jsonl",
        )


def test_promote_missing_treatment_field_raises(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    _write(spec, {"status": "live", "arms": {"treatment": {}}})  # no calibration_artifact
    with pytest.raises(ValueError, match="calibration_artifact"):
        promote_contextual_weights(
            spec_path=spec,
            report_path=_report(tmp_path),
            journal_path=tmp_path / "j.jsonl",
        )


# ---------------------------------------------------------------------------
# Journal accumulation
# ---------------------------------------------------------------------------


def test_promote_journal_accumulates_across_runs(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})
    spec = _spec(tmp_path, artifact)
    journal = tmp_path / "j.jsonl"

    promote_contextual_weights(
        spec_path=spec, report_path=_report(tmp_path),
        journal_path=journal, timestamp="2026-04-21T12-00-00Z",
    )
    promote_contextual_weights(
        spec_path=spec, report_path=_report(tmp_path),
        journal_path=journal, timestamp="2026-04-21T13-00-00Z",
    )
    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    actions = [json.loads(ln)["action"] for ln in lines]
    assert actions == ["promoted", "noop_already_production"]


def test_promote_appends_to_existing_promote_history(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {
        "status": "shadow",
        "promote_history": [{"promoted_at_utc": "old", "from_status": "shadow"}],
    })
    promote_contextual_weights(
        spec_path=_spec(tmp_path, artifact),
        report_path=_report(tmp_path),
        journal_path=tmp_path / "j.jsonl",
        timestamp="2026-04-21T12-00-00Z",
    )
    new = json.loads(artifact.read_text(encoding="utf-8"))
    assert len(new["promote_history"]) == 2
    assert new["promote_history"][0]["promoted_at_utc"] == "old"
    assert new["promote_history"][1]["promoted_at_utc"] == "2026-04-21T12-00-00Z"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_happy_path_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})
    rc = main([
        "--spec", str(_spec(tmp_path, artifact)),
        "--report", str(_report(tmp_path)),
        "--journal", str(tmp_path / "j.jsonl"),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"action": "promoted"' in out


def test_cli_decision_not_promote_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})
    rc = main([
        "--spec", str(_spec(tmp_path, artifact)),
        "--report", str(_report(tmp_path, decision="rollback")),
        "--journal", str(tmp_path / "j.jsonl"),
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "refusing to promote" in err


def test_cli_force_overrides(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})
    rc = main([
        "--spec", str(_spec(tmp_path, artifact)),
        "--report", str(_report(tmp_path, decision="hold")),
        "--journal", str(tmp_path / "j.jsonl"),
        "--force",
    ])
    assert rc == 0
    new = json.loads(artifact.read_text(encoding="utf-8"))
    assert new["status"] == "production"


def test_cli_missing_spec_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([
        "--spec", str(tmp_path / "nope.json"),
        "--report", str(_report(tmp_path)),
        "--journal", str(tmp_path / "j.jsonl"),
    ])
    assert rc == 1
    assert "spec does not exist" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Spec-status guard (audit C1/C2/C3 follow-up)
# ---------------------------------------------------------------------------


def test_promote_refuses_when_spec_status_is_plumbing_only(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})
    spec_path = _spec(tmp_path, artifact, status="plumbing_only")

    with pytest.raises(ValueError, match="spec.status="):
        promote_contextual_weights(
            spec_path=spec_path,
            report_path=_report(tmp_path),
            journal_path=tmp_path / "j.jsonl",
        )
    # Artifact untouched.
    assert json.loads(artifact.read_text(encoding="utf-8")) == {"status": "shadow"}


def test_promote_refuses_when_spec_status_is_registered(tmp_path: Path) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})
    # Spec without an explicit status field defaults to 'registered',
    # which is also not 'live' and therefore must be refused.
    spec_path = tmp_path / "spec_no_status.json"
    _write(spec_path, {
        "name": "f2",
        "arms": {"treatment": {"calibration_artifact": str(artifact)}},
    })
    with pytest.raises(ValueError, match="registered"):
        promote_contextual_weights(
            spec_path=spec_path,
            report_path=_report(tmp_path),
            journal_path=tmp_path / "j.jsonl",
        )


def test_promote_force_does_not_bypass_spec_status_gate(tmp_path: Path) -> None:
    """``--force`` may bypass the report-decision check, but not the spec-status gate."""
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})
    spec_path = _spec(tmp_path, artifact, status="plumbing_only")
    report_path = _report(tmp_path, decision="hold")  # also non-promote

    with pytest.raises(ValueError, match="spec.status="):
        promote_contextual_weights(
            spec_path=spec_path,
            report_path=report_path,
            journal_path=tmp_path / "j.jsonl",
            force=True,
        )


def test_cli_refuses_with_exit_1_when_spec_status_not_live(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact = tmp_path / "treatment.json"
    _write(artifact, {"status": "shadow"})
    spec_path = _spec(tmp_path, artifact, status="plumbing_only")
    report_path = _report(tmp_path)

    rc = main([
        "--spec", str(spec_path),
        "--report", str(report_path),
        "--journal", str(tmp_path / "j.jsonl"),
    ])
    assert rc == 1
    captured = capsys.readouterr()
    assert "spec.status=" in captured.err
