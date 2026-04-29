"""Structural pin-test for the F2 weekly-digest workflow YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "f2-weekly-digest.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_yaml_is_loadable() -> None:
    wf = _load()
    assert wf["name"] == "f2-weekly-digest"


def test_workflow_runs_monday_11utc() -> None:
    wf = _load()
    # PyYAML parses bare 'on:' as True under YAML 1.1.
    schedule = wf.get("on", wf.get(True))["schedule"]
    crons = [s["cron"] for s in schedule]
    assert "0 11 * * MON" in crons


def test_workflow_has_workflow_dispatch_window_input() -> None:
    wf = _load()
    on = wf.get("on", wf.get(True))
    wd = on["workflow_dispatch"]["inputs"]
    assert "window_days" in wd


def test_workflow_contents_read_only() -> None:
    perms = _load()["permissions"]
    # Weekly digest is read-only: no Issue-ping, no write ops.
    assert perms == {"contents": "read"}


def test_workflow_calls_weekly_digest_helper() -> None:
    wf = _load()
    steps = wf["jobs"]["digest"]["steps"]
    run_texts = "\n".join(s.get("run", "") for s in steps if "run" in s)
    assert "scripts/f2_weekly_digest.py" in run_texts
    assert "--reports-dir artifacts/reports" in run_texts
    assert "--format      md" in run_texts or "--format md" in run_texts


def test_upload_artifact_retention_is_long() -> None:
    wf = _load()
    steps = wf["jobs"]["digest"]["steps"]
    upload = next(s for s in steps if s.get("name", "").startswith("Upload digest"))
    # 180 days so the weekly rollup covers the §2.4 G3 30-day SPRT window
    # plus comfortable historical context.
    assert upload["with"]["retention-days"] == 180
    assert "artifacts/ci/f2/weekly_digest.json" in upload["with"]["path"]
