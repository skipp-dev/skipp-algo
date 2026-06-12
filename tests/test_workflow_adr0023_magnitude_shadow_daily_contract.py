"""Contract pin: ``adr0023-magnitude-shadow-daily`` workflow (ADR-0023 §4.1).

Pins the cron schedule, off-hours-only live-window marker, runner timeout,
fail-soft permissions, and the script entrypoint so silent drift of the
Stage-1 daily magnitude-shadow scheduler is caught at validate-time. This
file also satisfies ``test_workflow_orphan_inventory`` by referencing the
workflow stem ``adr0023-magnitude-shadow-daily``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = (
    _REPO_ROOT / ".github" / "workflows" / "adr0023-magnitude-shadow-daily.yml"
)


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_mutating_on_cron() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: mutating-on-cron" in head, (
        "first-line live-window marker required by F-V6-F2.1 — "
        "mutating-on-cron because the workflow commits the shadow ledger back"
    )


def test_schedule_is_weekday_1330_utc() -> None:
    data = _load()
    # PyYAML parses bare ``on`` as boolean True — accept both keys.
    on_block = data.get("on") or data.get(True)
    crons = [entry["cron"] for entry in on_block["schedule"]]
    assert crons == ["30 13 * * 1-5"], crons


def test_workflow_dispatch_exposes_events_path_and_seed() -> None:
    data = _load()
    on_block = data.get("on") or data.get(True)
    inputs = on_block["workflow_dispatch"]["inputs"]
    assert "events-path" in inputs
    assert "seed" in inputs
    assert inputs["seed"]["default"] == "230022"


def test_permissions_allow_ledger_commit_back() -> None:
    data = _load()
    assert data["permissions"] == {"contents": "write", "actions": "read"}


def test_job_invokes_shadow_ledger_script() -> None:
    data = _load()
    job = data["jobs"]["magnitude-shadow"]
    assert job["timeout-minutes"] == 20
    steps_run = " ".join(step.get("run", "") for step in job["steps"])
    assert "scripts/run_magnitude_shadow_ledger.py" in steps_run
    assert "artifacts/governance/magnitude_resolution_shadow.jsonl" in steps_run


def test_fail_soft_treats_2_and_3_as_valid_verdicts() -> None:
    data = _load()
    job = data["jobs"]["magnitude-shadow"]
    ledger_step = next(
        step for step in job["steps"] if step.get("id") == "ledger"
    )
    run = ledger_step["run"]
    # Exit codes 0/2/3 are valid shadow verdicts; only other codes fail.
    assert "no_data" in run
    assert 'case "$rc" in' in run
    assert "none_resolve" in run
    assert "all_thin" in run


def test_upload_artifact_is_fail_soft() -> None:
    data = _load()
    upload_steps = [
        step
        for step in data["jobs"]["magnitude-shadow"]["steps"]
        if "actions/upload-artifact" in (step.get("uses") or "")
    ]
    assert len(upload_steps) == 1
    cfg = upload_steps[0]["with"]
    assert cfg["if-no-files-found"] == "ignore"
    assert cfg["retention-days"] == 30


def test_commit_back_gap_guard_present_and_fail_loud() -> None:
    """Workflow-Audit MITTEL-5 (B5): the triple fail-soft commit-back must be
    paired with a fail-loud gap guard, otherwise repeated silent commit-back
    failures open an unnoticed hole in the committed ledger."""
    data = _load()
    job = data["jobs"]["magnitude-shadow"]
    guard = next(
        step
        for step in job["steps"]
        if "gap" in step.get("name", "").lower()
    )
    # Guard must run BEFORE the ledger append (it inspects the committed
    # state at checkout, not today's freshly appended row).
    step_names = [step.get("id") or step.get("name") for step in job["steps"]]
    assert step_names.index(guard.get("id") or guard["name"]) < step_names.index("ledger")
    # Must not be fail-soft itself.
    assert not guard.get("continue-on-error", False)
    env = guard["env"]
    assert env["LEDGER_PATH"] == "artifacts/governance/magnitude_resolution_shadow.jsonl"
    assert int(env["GAP_BUDGET_DAYS"]) == 7
    run = guard["run"]
    assert "GAP_BUDGET_DAYS" in run
    assert "sys.exit(1)" in run  # fail-loud on gap breach
    assert "::error title=adr0023-gap-check::" in run
