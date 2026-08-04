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


# --- the digest's status, executed rather than described --------------------
#
# `digest` publishes status; the commit and summary steps read it. Measured
# 2026-08-04 with a value-preserving arm swap (built <-> skipped): all 9
# assertions across the 2 files that name this workflow stayed green.

import sys
from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

_DIGEST_STEP = "Build weekly digest"


def _digest(tmp_path: Path, *, reports_dir: bool, tool_rc: int = 0):
    if reports_dir:
        (tmp_path / "artifacts/reports").mkdir(parents=True, exist_ok=True)
    return run_step(
        "f2-weekly-digest.yml", _DIGEST_STEP, tmp_path,
        env={"REAL_PYTHON": sys.executable},
        stubs={"python": Stub(script=f'''
case "$1" in -c) exec "$REAL_PYTHON" "$@" ;; esac
exit {tool_rc}
''')},
        expressions={"steps.window.outputs.value": "7"},
    )


def test_no_reports_directory_is_a_skip(tmp_path: Path) -> None:
    result = _digest(tmp_path, reports_dir=False)
    assert result.returncode == 0, result.stderr
    assert result.outputs["status"] == "skipped"


def test_a_present_reports_directory_builds(tmp_path: Path) -> None:
    result = _digest(tmp_path, reports_dir=True)
    assert result.returncode == 0, result.stderr
    assert result.outputs["status"] == "built"


def test_a_failing_digest_tool_still_reports_built_and_warns(tmp_path: Path) -> None:
    """By design, and worth pinning precisely because it looks like a bug.

    The step tolerates a non-zero digest build so scheduled runs stay green
    unless the tooling itself is broken. `status=built` is therefore emitted
    either way -- but the warning is the only trace that anything went wrong,
    so it is the part that must not silently disappear.
    """
    result = _digest(tmp_path, reports_dir=True, tool_rc=3)
    assert result.returncode == 0, result.stderr
    assert result.outputs["status"] == "built"
    assert "::warning" in result.stdout and "exited 3" in result.stdout, (
        f"a failed digest build must leave a visible warning; got {result.stdout!r}"
    )
