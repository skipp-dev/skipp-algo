"""Tests for scripts/f2_simulate_chain.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_simulate_chain import main, simulate


def test_default_walk_ends_with_rollback(tmp_path: Path) -> None:
    manifest = simulate(workdir=tmp_path)
    # Default fixture: 3 hold days + 1 rollback day, but ring is only
    # grown on days BEFORE the rollback (append step gated on rc=0).
    assert manifest["narrative"][-2].startswith("auto-revert")
    assert manifest["narrative"][-1].startswith("operator rotate")
    # Revert actually ran.
    rec = manifest["revert_record"]
    assert rec["action"] == "reverted"
    assert rec["new_status"] == "shadow"
    # Artifact on disk reflects the revert.
    artifact = json.loads(Path(manifest["artifact"]).read_text(encoding="utf-8"))
    assert artifact["status"] == "shadow"
    # Manifest persisted.
    assert (tmp_path / "simulation_manifest.json").exists()


def test_simulate_writes_issue_body_and_title(tmp_path: Path) -> None:
    manifest = simulate(workdir=tmp_path)
    assert manifest["issue_title"].startswith("[F2 rollback]")
    body_path = Path(manifest["issue_body"])
    assert body_path.exists()
    body = body_path.read_text(encoding="utf-8")
    assert "f2-rollback" in body
    assert "f2_revert_contextual_weights.py" in body or "demoted" in body


def test_simulate_ring_grows_only_on_green_days(tmp_path: Path) -> None:
    manifest = simulate(workdir=tmp_path)
    # 3 hold days BEFORE the rollback day; rollback day breaks the loop
    # before appending. But the walk is "break on first rollback", so
    # the 3rd hold day (still rc=0) gets appended. Final ring length 3.
    history = json.loads(Path(manifest["history_path"]).read_text(encoding="utf-8"))
    # After rotate the ring is empty.
    assert history == []


def test_simulate_summary_and_status_reflect_post_rollback_state(tmp_path: Path) -> None:
    manifest = simulate(workdir=tmp_path)
    summary = manifest["summary"]
    assert summary["latest_report"]["decision"] == "rollback"
    assert summary["latest_report"]["date"] == "2026-04-21"
    status = manifest["status"]
    assert status["artifact"]["status"] == "shadow"
    assert status["revert_journal"]["len"] == 1


def test_simulate_weekly_digest_sees_all_days(tmp_path: Path) -> None:
    manifest = simulate(workdir=tmp_path)
    weekly = manifest["weekly_digest"]
    # Default days = 4; all land in the 7-day window.
    assert weekly["len"] == 4
    assert weekly["decisions"] == {"hold": 3, "rollback": 1}


def test_simulate_custom_days_no_rollback(tmp_path: Path) -> None:
    days = [
        ("2026-04-20", "hold",    -0.002),
        ("2026-04-21", "promote", -0.010),
    ]
    manifest = simulate(workdir=tmp_path, days=days)
    # No rollback branch executed.
    assert manifest["revert_record"] is None
    assert manifest["rotate_record"] is None
    assert manifest["issue_title"] is None
    # Artifact still production.
    artifact = json.loads(Path(manifest["artifact"]).read_text(encoding="utf-8"))
    assert artifact["status"] == "production"


def test_cli_happy_path_prints_narrative(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--workdir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "F2 dry-run simulation" in out
    assert "auto-revert" in out
    assert "manifest:" in out


def test_cli_quiet_prints_only_manifest_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--workdir", str(tmp_path), "--quiet"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out == str(tmp_path / "simulation_manifest.json")
    assert Path(out).exists()
