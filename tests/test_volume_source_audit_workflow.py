"""Pins the post-close multi-session FMP volume-basis evidence chain."""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]


def _workflow() -> dict:
    return yaml.safe_load(
        (_ROOT / ".github/workflows/open-prep-outcome-backfill.yml").read_text(
            encoding="utf-8"
        )
    )


def test_post_close_workflow_collects_five_session_fmp_basis_evidence() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["backfill"]["steps"]
    step = next(item for item in steps if item.get("name") == "Measure FMP volume basis")
    run = str(step["run"])
    assert step["env"]["FMP_API_KEY"] == "${{ secrets.FMP_API_KEY }}"
    assert "scripts/measure_fmp_volume_basis.py" in run
    assert "--minimum-sessions 5" in run
    assert "artifacts/open_prep/volume_source_audit" in run


def test_measurement_artifacts_are_uploaded_and_committed() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["backfill"]["steps"]
    upload = next(item for item in steps if item.get("name") == "Upload run log")
    commit = next(item for item in steps if item.get("name") == "Commit refreshed outcomes via PR")
    assert "artifacts/open_prep/volume_source_audit/" in str(upload["with"]["path"])
    assert "artifacts/open_prep/volume_source_audit/" in str(commit["run"])


def test_daily_snapshot_embeds_explicit_fmp_15_session_adv() -> None:
    workflow = yaml.safe_load(
        (_ROOT / ".github/workflows/run-open-prep-daily.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["run"]["steps"]
    publish = next(item for item in steps if item.get("name") == "Publish open-prep snapshot to rolling bot branch")
    run = str(publish["run"])
    assert "--fmp-output" in run
    assert "scripts/apply_fmp_adv_reference.py" in run
    assert "refusing an opaque profile-ADV snapshot" in run
